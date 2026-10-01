import csv
import hashlib
import io
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AuthContext, require_csrf, require_permission
from app.api.masterdata import STALE, audit, commit_or_conflict, json_safe
from app.core.audit import actor_label
from app.db.session import get_db
from app.models.identity import Site
from app.models.masterdata import Customer, Item, UnitOfMeasure
from app.models.orders import PromiseChange, SalesOrder, SalesOrderLine
from app.schemas.orders import (
    LineAdd,
    LineIn,
    LineOut,
    LineUpdate,
    OrderCreate,
    OrderImportIssue,
    OrderImportReport,
    OrderImportRequest,
    OrderOut,
    OrderPage,
    OrderSummary,
    OrderUpdate,
    PromiseChangeIn,
    PromiseOut,
    ReasonedAction,
    VersionOnly,
)
from app.services.numbering import allocate_number

router = APIRouter(prefix="/orders", tags=["customer orders"])
READ = require_permission("orders:read")
MANAGE = require_permission("orders:manage")
CSRF = [Depends(require_csrf)]
ZERO = Decimal(0)
MAX_IMPORT_ROWS = 2000


# Quantities ------------------------------------------------------------------


def shipped_qty(line: SalesOrderLine) -> Decimal:
    # Dispatch (F8) will post shipments; until then nothing has shipped.
    return ZERO


def remaining_qty(line: SalesOrderLine) -> Decimal:
    return line.ordered_qty - shipped_qty(line) - line.cancelled_qty - line.short_closed_qty


def plain(quantity: Decimal) -> str:
    """Audit-friendly number without trailing zeros or exponent: 40.000000 -> "40"."""
    return format(quantity.normalize(), "f")


def to_unit(quantity: Decimal, unit: UnitOfMeasure) -> Decimal:
    """Present a quantity at its unit's precision (stored values never exceed it)."""
    return quantity.quantize(Decimal(1).scaleb(-unit.decimal_places))


def check_precision(quantity: Decimal, unit: UnitOfMeasure) -> None:
    exponent = quantity.normalize().as_tuple().exponent
    places = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    if places > unit.decimal_places:
        raise HTTPException(
            status_code=422,
            detail=f"{unit.code} allows {unit.decimal_places} decimal place(s); "
            f"{quantity.normalize()} has {places}",
        )


# Loading and access -----------------------------------------------------------


async def get_order(db: AsyncSession, context: AuthContext, order_id: uuid.UUID) -> SalesOrder:
    order = await db.scalar(
        select(SalesOrder).where(
            SalesOrder.tenant_id == context.tenant.id, SalesOrder.id == order_id
        )
    )
    if order is None or not context.can_access_site(order.site_id):
        raise HTTPException(status_code=404, detail="Order not found")
    return order


async def get_line(db: AsyncSession, order: SalesOrder, line_id: uuid.UUID) -> SalesOrderLine:
    line = await db.scalar(
        select(SalesOrderLine).where(
            SalesOrderLine.order_id == order.id, SalesOrderLine.id == line_id
        )
    )
    if line is None:
        raise HTTPException(status_code=404, detail="Order line not found")
    return line


async def active_item_and_unit(
    db: AsyncSession, context: AuthContext, item_id: uuid.UUID
) -> tuple[Item, UnitOfMeasure]:
    item = await db.scalar(
        select(Item).where(Item.tenant_id == context.tenant.id, Item.id == item_id)
    )
    if item is None or item.status != "active":
        raise HTTPException(status_code=422, detail="Choose an active item")
    unit = await db.get(UnitOfMeasure, item.base_unit_id)
    return item, unit


def require_version(current: int, given: int) -> None:
    if current != given:
        raise HTTPException(status_code=409, detail=STALE)


async def order_out(db: AsyncSession, order: SalesOrder) -> OrderOut:
    site = await db.get(Site, order.site_id)
    customer = await db.get(Customer, order.customer_id)
    lines = (
        await db.scalars(
            select(SalesOrderLine)
            .where(SalesOrderLine.order_id == order.id)
            .order_by(SalesOrderLine.line_no)
        )
    ).all()
    items = (
        {
            i.id: i
            for i in await db.scalars(
                select(Item).where(Item.id.in_([line.item_id for line in lines]))
            )
        }
        if lines
        else {}
    )
    units = (
        {
            u.id: u
            for u in await db.scalars(
                select(UnitOfMeasure).where(UnitOfMeasure.id.in_([line.unit_id for line in lines]))
            )
        }
        if lines
        else {}
    )
    history: dict[uuid.UUID, list[PromiseOut]] = defaultdict(list)
    if lines:
        rows = await db.scalars(
            select(PromiseChange)
            .where(PromiseChange.line_id.in_([line.id for line in lines]))
            .order_by(PromiseChange.changed_at, PromiseChange.id)
        )
        for change in rows:
            history[change.line_id].append(
                PromiseOut(
                    previous_date=change.previous_date,
                    new_date=change.new_date,
                    reason_code=change.reason_code,
                    note=change.note,
                    changed_by_label=change.changed_by_label,
                    changed_at=change.changed_at,
                )
            )
    return OrderOut(
        id=order.id,
        number=order.number,
        site_id=order.site_id,
        site_name=site.name,
        customer_id=order.customer_id,
        customer_code=customer.code,
        customer_name=customer.name,
        customer_reference=order.customer_reference,
        order_date=order.order_date,
        status=order.status,
        status_reason=order.status_reason,
        notes=order.notes,
        confirmed_at=order.confirmed_at,
        version=order.version,
        created_at=order.created_at,
        updated_at=order.updated_at,
        lines=[
            LineOut(
                id=line.id,
                line_no=line.line_no,
                item_id=line.item_id,
                item_code=items[line.item_id].code,
                item_name=items[line.item_id].name,
                unit_code=units[line.unit_id].code,
                ordered_qty=to_unit(line.ordered_qty, units[line.unit_id]),
                shipped_qty=to_unit(shipped_qty(line), units[line.unit_id]),
                cancelled_qty=to_unit(line.cancelled_qty, units[line.unit_id]),
                short_closed_qty=to_unit(line.short_closed_qty, units[line.unit_id]),
                remaining_qty=to_unit(remaining_qty(line), units[line.unit_id]),
                requested_date=line.requested_date,
                promised_date=line.promised_date,
                status=line.status,
                status_reason=line.status_reason,
                version=line.version,
                promise_history=history[line.id],
            )
            for line in lines
        ],
    )


def record_promise(
    db: AsyncSession,
    context: AuthContext,
    line: SalesOrderLine,
    previous: date | None,
    new: date,
    reason_code: str,
    note: str | None,
) -> None:
    db.add(
        PromiseChange(
            tenant_id=line.tenant_id,
            line_id=line.id,
            previous_date=previous,
            new_date=new,
            reason_code=reason_code,
            note=note,
            changed_by=context.user.id,
            changed_by_label=actor_label(context.user),
            changed_at=datetime.now(UTC),
        )
    )


async def add_line(
    db: AsyncSession,
    context: AuthContext,
    order: SalesOrder,
    payload: LineIn,
    line_no: int,
) -> SalesOrderLine:
    item, unit = await active_item_and_unit(db, context, payload.item_id)
    check_precision(payload.quantity, unit)
    line = SalesOrderLine(
        id=uuid.uuid4(),
        tenant_id=context.tenant.id,
        order_id=order.id,
        line_no=line_no,
        item_id=item.id,
        unit_id=unit.id,
        ordered_qty=payload.quantity,
        requested_date=payload.requested_date,
        promised_date=payload.promised_date,
    )
    db.add(line)
    return line


def line_snapshot(line: SalesOrderLine) -> dict[str, Any]:
    return {
        "line_id": str(line.id),
        "line_no": line.line_no,
        "item_id": str(line.item_id),
        "quantity": plain(line.ordered_qty),
        "requested_date": line.requested_date.isoformat(),
        "promised_date": line.promised_date.isoformat() if line.promised_date else None,
    }


def touch(order: SalesOrder, context: AuthContext) -> None:
    order.updated_by = context.user.id
    order.updated_at = datetime.now(UTC)


async def close_if_finished(db: AsyncSession, order: SalesOrder) -> None:
    open_lines = await db.scalar(
        select(func.count())
        .select_from(SalesOrderLine)
        .where(SalesOrderLine.order_id == order.id, SalesOrderLine.status == "open")
    )
    if order.status == "confirmed" and not open_lines:
        order.status = "closed"


# Endpoints --------------------------------------------------------------------


@router.get("", response_model=OrderPage)
async def list_orders(
    q: str | None = Query(default=None, max_length=80),
    status: str | None = Query(default=None, pattern="^(draft|confirmed|cancelled|closed)$"),
    site_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100_000),
    context: AuthContext = Depends(READ),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(SalesOrder, Customer, Site)
        .join(Customer, Customer.id == SalesOrder.customer_id)
        .join(Site, Site.id == SalesOrder.site_id)
        .where(SalesOrder.tenant_id == context.tenant.id)
    )
    if context.site_ids is not None:
        query = query.where(SalesOrder.site_id.in_(context.site_ids))
    if site_id is not None:
        query = query.where(SalesOrder.site_id == site_id)
    if status:
        query = query.where(SalesOrder.status == status)
    if q and q.strip():
        pattern = (
            "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        )
        query = query.where(
            or_(
                SalesOrder.number.ilike(pattern, escape="\\"),
                SalesOrder.customer_reference.ilike(pattern, escape="\\"),
                Customer.code.ilike(pattern, escape="\\"),
                Customer.name.ilike(pattern, escape="\\"),
            )
        )
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (
        await db.execute(
            query.order_by(SalesOrder.order_date.desc(), SalesOrder.number.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    stats: dict[uuid.UUID, tuple[int, int, date | None]] = {}
    if rows:
        stat_rows = await db.execute(
            select(
                SalesOrderLine.order_id,
                func.count(),
                func.sum(case((SalesOrderLine.status == "open", 1), else_=0)),
                func.min(SalesOrderLine.promised_date).filter(SalesOrderLine.status == "open"),
            )
            .where(SalesOrderLine.order_id.in_([order.id for order, _, _ in rows]))
            .group_by(SalesOrderLine.order_id)
        )
        stats = {r[0]: (r[1], int(r[2] or 0), r[3]) for r in stat_rows}
    return OrderPage(
        items=[
            OrderSummary(
                id=order.id,
                number=order.number,
                customer_code=customer.code,
                customer_name=customer.name,
                customer_reference=order.customer_reference,
                site_name=site.name,
                order_date=order.order_date,
                status=order.status,
                line_count=stats.get(order.id, (0, 0, None))[0],
                open_lines=stats.get(order.id, (0, 0, None))[1],
                next_promised_date=stats.get(order.id, (0, 0, None))[2],
            )
            for order, customer, site in rows
        ],
        total=total,
    )


@router.post("", response_model=OrderOut, status_code=201, dependencies=CSRF)
async def create_order(
    payload: OrderCreate,
    request: Request,
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    site = await db.scalar(
        select(Site).where(Site.tenant_id == context.tenant.id, Site.id == payload.site_id)
    )
    if site is None or not context.can_access_site(site.id) or site.status != "active":
        raise HTTPException(status_code=422, detail="Choose an active site you can access")
    customer = await db.scalar(
        select(Customer).where(
            Customer.tenant_id == context.tenant.id, Customer.id == payload.customer_id
        )
    )
    if customer is None or customer.status != "active":
        raise HTTPException(status_code=422, detail="Choose an active customer")
    order, lines = await build_order(
        db,
        context,
        site,
        customer,
        payload.customer_reference,
        payload.order_date,
        payload.notes,
        payload.lines,
    )
    audit(
        db,
        context,
        request,
        "orders.created",
        {
            "order_id": str(order.id),
            "number": order.number,
            "customer": customer.code,
            "customer_reference": order.customer_reference,
            "lines": [line_snapshot(line) for line in lines],
            "source": "manual",
        },
    )
    await commit_or_conflict(db, "This customer reference already has an order")
    return await order_out(db, order)


async def build_order(
    db: AsyncSession,
    context: AuthContext,
    site: Site,
    customer: Customer,
    customer_reference: str | None,
    order_date: date | None,
    notes: str | None,
    lines: list[LineIn],
) -> tuple[SalesOrder, list[SalesOrderLine]]:
    if customer_reference:
        duplicate = await db.scalar(
            select(SalesOrder.number).where(
                SalesOrder.tenant_id == context.tenant.id,
                SalesOrder.customer_id == customer.id,
                SalesOrder.customer_reference == customer_reference,
            )
        )
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail=f"{customer.code} reference {customer_reference} is already order "
                f"{duplicate}",
            )
    order = SalesOrder(
        id=uuid.uuid4(),
        tenant_id=context.tenant.id,
        site_id=site.id,
        customer_id=customer.id,
        number=await allocate_number(db, context.tenant.id, "sales_order"),
        customer_reference=customer_reference,
        order_date=order_date or datetime.now(ZoneInfo(site.time_zone)).date(),
        notes=notes,
        created_by=context.user.id,
        updated_by=context.user.id,
    )
    db.add(order)
    await db.flush()
    created = [
        await add_line(db, context, order, line, index) for index, line in enumerate(lines, start=1)
    ]
    await db.flush()
    return order, created


@router.get("/{order_id}", response_model=OrderOut)
async def read_order(
    order_id: uuid.UUID,
    context: AuthContext = Depends(READ),
    db: AsyncSession = Depends(get_db),
):
    return await order_out(db, await get_order(db, context, order_id))


@router.patch("/{order_id}", response_model=OrderOut, dependencies=CSRF)
async def update_order(
    order_id: uuid.UUID,
    payload: OrderUpdate,
    request: Request,
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    order = await get_order(db, context, order_id)
    require_version(order.version, payload.version)
    if order.status not in ("draft", "confirmed"):
        raise HTTPException(status_code=409, detail=f"A {order.status} order cannot be edited")
    changes = {}
    for field in payload.model_fields_set - {"version"}:
        before, after = getattr(order, field), getattr(payload, field)
        if before != after:
            changes[field] = {"from": before, "to": after}
            setattr(order, field, after)
    if changes:
        touch(order, context)
        audit(
            db,
            context,
            request,
            "orders.updated",
            {"order_id": str(order.id), "number": order.number, "changes": changes},
        )
    await commit_or_conflict(db, "This customer reference already has an order")
    return await order_out(db, order)


@router.post("/{order_id}/lines", response_model=OrderOut, status_code=201, dependencies=CSRF)
async def add_order_line(
    order_id: uuid.UUID,
    payload: LineAdd,
    request: Request,
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    order = await get_order(db, context, order_id)
    require_version(order.version, payload.order_version)
    if order.status not in ("draft", "confirmed"):
        raise HTTPException(
            status_code=409, detail=f"Lines cannot be added to a {order.status} order"
        )
    if order.status == "confirmed" and payload.promised_date is None:
        raise HTTPException(
            status_code=422, detail="A line added to a confirmed order needs a promised date"
        )
    next_no = (
        await db.scalar(
            select(func.max(SalesOrderLine.line_no)).where(SalesOrderLine.order_id == order.id)
        )
        or 0
    ) + 1
    line = await add_line(
        db, context, order, LineIn(**payload.model_dump(exclude={"order_version"})), next_no
    )
    await db.flush()
    if order.status == "confirmed":
        record_promise(db, context, line, None, payload.promised_date, "initial", None)
    touch(order, context)
    audit(
        db,
        context,
        request,
        "orders.line_added",
        {
            "order_id": str(order.id),
            "number": order.number,
            "amendment": order.status == "confirmed",
            "after": line_snapshot(line),
        },
    )
    await commit_or_conflict(db, STALE)
    return await order_out(db, order)


@router.patch("/{order_id}/lines/{line_id}", response_model=OrderOut, dependencies=CSRF)
async def update_order_line(
    order_id: uuid.UUID,
    line_id: uuid.UUID,
    payload: LineUpdate,
    request: Request,
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    order = await get_order(db, context, order_id)
    line = await get_line(db, order, line_id)
    require_version(line.version, payload.version)
    if order.status not in ("draft", "confirmed") or line.status != "open":
        raise HTTPException(status_code=409, detail="Only open lines on active orders can change")
    fields = payload.model_fields_set - {"version"}
    if order.status == "confirmed" and "promised_date" in fields:
        raise HTTPException(
            status_code=409,
            detail="Change the promised date of a confirmed order with a reason",
        )
    for field in fields:
        if getattr(payload, field) is None and field != "promised_date":
            raise HTTPException(status_code=422, detail=f"{field} cannot be empty")
    if "quantity" in fields:
        unit = await db.get(UnitOfMeasure, line.unit_id)
        check_precision(payload.quantity, unit)
        floor = shipped_qty(line) + line.cancelled_qty + line.short_closed_qty
        if payload.quantity <= floor:
            raise HTTPException(
                status_code=409,
                detail=f"Quantity must stay above the {floor.normalize()} "
                "already shipped or closed",
            )
    before = line_snapshot(line)
    if "quantity" in fields:
        line.ordered_qty = payload.quantity
    for field in ("requested_date", "promised_date"):
        if field in fields:
            setattr(line, field, getattr(payload, field))
    after = line_snapshot(line)
    if before != after:
        touch(order, context)
        audit(
            db,
            context,
            request,
            "orders.line_updated",
            {
                "order_id": str(order.id),
                "number": order.number,
                "amendment": order.status == "confirmed",
                "before": before,
                "after": after,
            },
        )
    await commit_or_conflict(db, STALE)
    return await order_out(db, order)


@router.delete("/{order_id}/lines/{line_id}", response_model=OrderOut, dependencies=CSRF)
async def remove_order_line(
    order_id: uuid.UUID,
    line_id: uuid.UUID,
    request: Request,
    version: int = Query(ge=1),
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    order = await get_order(db, context, order_id)
    line = await get_line(db, order, line_id)
    require_version(line.version, version)
    if order.status != "draft":
        raise HTTPException(
            status_code=409, detail="Lines can only be removed from drafts; short-close instead"
        )
    count = await db.scalar(
        select(func.count()).select_from(SalesOrderLine).where(SalesOrderLine.order_id == order.id)
    )
    if count == 1:
        raise HTTPException(status_code=409, detail="An order needs at least one line")
    audit(
        db,
        context,
        request,
        "orders.line_removed",
        {"order_id": str(order.id), "number": order.number, "before": line_snapshot(line)},
    )
    await db.delete(line)
    touch(order, context)
    await commit_or_conflict(db, STALE)
    return await order_out(db, order)


@router.post("/{order_id}/confirm", response_model=OrderOut, dependencies=CSRF)
async def confirm_order(
    order_id: uuid.UUID,
    payload: VersionOnly,
    request: Request,
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    order = await get_order(db, context, order_id)
    require_version(order.version, payload.version)
    if order.status != "draft":
        raise HTTPException(status_code=409, detail=f"A {order.status} order cannot be confirmed")
    lines = (
        await db.scalars(select(SalesOrderLine).where(SalesOrderLine.order_id == order.id))
    ).all()
    missing = sorted(line.line_no for line in lines if line.promised_date is None)
    if missing:
        raise HTTPException(
            status_code=422,
            detail="Every line needs a promised date before confirming (line "
            + ", ".join(map(str, missing))
            + ")",
        )
    for line in lines:
        record_promise(db, context, line, None, line.promised_date, "initial", None)
    order.status = "confirmed"
    order.confirmed_at = datetime.now(UTC)
    touch(order, context)
    audit(
        db,
        context,
        request,
        "orders.confirmed",
        {
            "order_id": str(order.id),
            "number": order.number,
            "promises": {str(line.line_no): line.promised_date.isoformat() for line in lines},
        },
    )
    await commit_or_conflict(db, STALE)
    return await order_out(db, order)


@router.post("/{order_id}/lines/{line_id}/promise", response_model=OrderOut, dependencies=CSRF)
async def change_promise(
    order_id: uuid.UUID,
    line_id: uuid.UUID,
    payload: PromiseChangeIn,
    request: Request,
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    order = await get_order(db, context, order_id)
    line = await get_line(db, order, line_id)
    require_version(line.version, payload.version)
    if order.status != "confirmed" or line.status != "open":
        raise HTTPException(
            status_code=409, detail="Promises change only on open lines of confirmed orders"
        )
    if payload.new_date == line.promised_date:
        raise HTTPException(status_code=422, detail="The new date is the same as the current one")
    previous = line.promised_date
    line.promised_date = payload.new_date
    record_promise(db, context, line, previous, payload.new_date, payload.reason_code, payload.note)
    touch(order, context)
    audit(
        db,
        context,
        request,
        "orders.promise_changed",
        {
            "order_id": str(order.id),
            "number": order.number,
            "line_no": line.line_no,
            "from": json_safe(previous),
            "to": payload.new_date.isoformat(),
            "reason_code": payload.reason_code,
            "note": payload.note,
        },
    )
    await commit_or_conflict(db, STALE)
    return await order_out(db, order)


@router.post("/{order_id}/cancel", response_model=OrderOut, dependencies=CSRF)
async def cancel_order(
    order_id: uuid.UUID,
    payload: ReasonedAction,
    request: Request,
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    order = await get_order(db, context, order_id)
    require_version(order.version, payload.version)
    if order.status not in ("draft", "confirmed"):
        raise HTTPException(status_code=409, detail=f"A {order.status} order cannot be cancelled")
    lines = (
        await db.scalars(select(SalesOrderLine).where(SalesOrderLine.order_id == order.id))
    ).all()
    if any(shipped_qty(line) > 0 for line in lines):
        raise HTTPException(
            status_code=409, detail="Part of this order has shipped; short-close lines instead"
        )
    for line in lines:
        if line.status == "open":
            line.cancelled_qty = remaining_qty(line) + line.cancelled_qty
            line.status = "cancelled"
            line.status_reason = payload.reason
    order.status = "cancelled"
    order.status_reason = payload.reason
    touch(order, context)
    audit(
        db,
        context,
        request,
        "orders.cancelled",
        {"order_id": str(order.id), "number": order.number, "reason": payload.reason},
    )
    await commit_or_conflict(db, STALE)
    return await order_out(db, order)


@router.post("/{order_id}/lines/{line_id}/short-close", response_model=OrderOut, dependencies=CSRF)
async def short_close_line(
    order_id: uuid.UUID,
    line_id: uuid.UUID,
    payload: ReasonedAction,
    request: Request,
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    order = await get_order(db, context, order_id)
    line = await get_line(db, order, line_id)
    require_version(line.version, payload.version)
    if order.status != "confirmed" or line.status != "open":
        raise HTTPException(
            status_code=409, detail="Only open lines of confirmed orders can be short-closed"
        )
    closed = remaining_qty(line)
    line.short_closed_qty += closed
    line.status = "short_closed"
    line.status_reason = payload.reason
    await db.flush()
    await close_if_finished(db, order)
    touch(order, context)
    audit(
        db,
        context,
        request,
        "orders.line_short_closed",
        {
            "order_id": str(order.id),
            "number": order.number,
            "line_no": line.line_no,
            "quantity": plain(closed),
            "reason": payload.reason,
        },
    )
    await commit_or_conflict(db, STALE)
    return await order_out(db, order)


# Import -----------------------------------------------------------------------

REQUIRED = {"customer_reference", "customer_code", "item_code", "quantity", "requested_date"}
OPTIONAL = {"promised_date", "order_date", "notes"}


def _parse_date(value: str) -> date:
    parsed = date.fromisoformat(value)
    if not 2000 <= parsed.year <= 2100:
        raise ValueError
    return parsed


@router.post("/import", response_model=OrderImportReport, dependencies=CSRF)
async def import_orders(
    payload: OrderImportRequest,
    request: Request,
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    site = await db.scalar(
        select(Site).where(Site.tenant_id == context.tenant.id, Site.id == payload.site_id)
    )
    if site is None or not context.can_access_site(site.id) or site.status != "active":
        raise HTTPException(status_code=422, detail="Choose an active site you can access")
    errors: list[OrderImportIssue] = []

    def err(row: int, message: str, field: str | None = None) -> None:
        errors.append(OrderImportIssue(row=row, field=field, message=message))

    reader = csv.DictReader(io.StringIO(payload.csv_text.lstrip("﻿")))
    header = [(h or "").strip().lower() for h in (reader.fieldnames or [])]
    if missing := REQUIRED - set(header):
        err(1, "Missing column(s): " + ", ".join(sorted(missing)))
    if unknown := set(header) - REQUIRED - OPTIONAL:
        err(1, "Unknown column(s): " + ", ".join(sorted(unknown)))
    if len(header) != len(set(header)):
        err(1, "Each column may appear only once")
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    total = 0
    if not errors:
        reader.fieldnames = header
        customers = {
            c.code: c
            for c in await db.scalars(
                select(Customer).where(
                    Customer.tenant_id == context.tenant.id, Customer.status == "active"
                )
            )
        }
        items = {
            i.code: i
            for i in await db.scalars(
                select(Item).where(Item.tenant_id == context.tenant.id, Item.status == "active")
            )
        }
        units = {
            u.id: u
            for u in await db.scalars(
                select(UnitOfMeasure).where(UnitOfMeasure.tenant_id == context.tenant.id)
            )
        }
        try:
            for raw in reader:
                row = reader.line_num
                if None in raw:
                    err(row, "This row has more values than there are columns")
                    continue
                values = {k: (v or "").strip() for k, v in raw.items()}
                if not any(values.values()):
                    continue
                total += 1
                if total > MAX_IMPORT_ROWS:
                    err(row, f"A file may contain at most {MAX_IMPORT_ROWS} rows")
                    break
                ok = True
                reference = values["customer_reference"]
                if not reference or len(reference) > 80:
                    err(
                        row,
                        "Give the customer's order reference (up to 80 characters)",
                        "customer_reference",
                    )
                    ok = False
                customer = customers.get(values["customer_code"].upper())
                if customer is None:
                    err(
                        row,
                        f"No active customer with code {values['customer_code'] or '(blank)'}",
                        "customer_code",
                    )
                    ok = False
                item = items.get(values["item_code"].upper())
                if item is None:
                    err(
                        row,
                        f"No active item with code {values['item_code'] or '(blank)'}",
                        "item_code",
                    )
                    ok = False
                try:
                    quantity = Decimal(values["quantity"])
                    if not quantity.is_finite() or quantity <= 0:
                        raise InvalidOperation
                except InvalidOperation:
                    err(row, "Enter a positive number", "quantity")
                    ok = False
                    quantity = None
                if item is not None and quantity is not None:
                    unit = units[item.base_unit_id]
                    try:
                        check_precision(quantity, unit)
                    except HTTPException as exc:
                        err(row, exc.detail, "quantity")
                        ok = False
                parsed: dict[str, date | None] = {}
                for field in ("requested_date", "promised_date", "order_date"):
                    text = values.get(field, "")
                    if not text:
                        parsed[field] = None
                        if field == "requested_date":
                            err(row, "Enter a date as YYYY-MM-DD", field)
                            ok = False
                        continue
                    try:
                        parsed[field] = _parse_date(text)
                    except ValueError:
                        err(row, "Enter a date as YYYY-MM-DD between 2000 and 2100", field)
                        ok = False
                if not ok:
                    continue
                key = (customer.code, reference)
                group = groups.setdefault(
                    key,
                    {
                        "row": row,
                        "customer": customer,
                        "reference": reference,
                        "order_date": parsed["order_date"],
                        "notes": values.get("notes") or None,
                        "lines": [],
                    },
                )
                if parsed["order_date"] and group["order_date"] not in (None, parsed["order_date"]):
                    err(
                        row,
                        f"Order date differs from row {group['row']} of the same order",
                        "order_date",
                    )
                    continue
                group["lines"].append(
                    (
                        row,
                        LineIn(
                            item_id=item.id,
                            quantity=quantity,
                            requested_date=parsed["requested_date"],
                            promised_date=parsed["promised_date"],
                        ),
                        item.code,
                    )
                )
        except (csv.Error, ValidationError) as exc:
            err(reader.line_num, f"The file could not be read: {exc}")
    if total == 0 and not errors:
        err(1, "The file has no data rows")

    to_create: list[dict[str, Any]] = []
    unchanged = 0
    for (customer_code, reference), group in groups.items():
        existing = await db.scalar(
            select(SalesOrder).where(
                SalesOrder.tenant_id == context.tenant.id,
                SalesOrder.customer_id == group["customer"].id,
                SalesOrder.customer_reference == reference,
            )
        )
        if existing is None:
            to_create.append(group)
            continue
        existing_lines = (
            await db.scalars(
                select(SalesOrderLine)
                .where(SalesOrderLine.order_id == existing.id)
                .order_by(SalesOrderLine.line_no)
            )
        ).all()
        same = [
            (line.item_id, line.ordered_qty, line.requested_date, line.promised_date)
            for line in existing_lines
        ] == [
            (li.item_id, li.quantity, li.requested_date, li.promised_date)
            for _, li, _ in group["lines"]
        ]
        if same:
            unchanged += 1
        else:
            err(
                group["row"],
                f"{customer_code} reference {reference} is already order "
                f"{existing.number} with different lines; change it in the app instead",
                "customer_reference",
            )

    report = OrderImportReport(
        total_rows=total,
        orders_to_create=len(to_create),
        lines_to_create=sum(len(g["lines"]) for g in to_create),
        unchanged_orders=unchanged,
        errors=errors,
        committed=False,
    )
    if not payload.commit:
        return report
    if errors:
        return JSONResponse(status_code=422, content=report.model_dump(mode="json"))
    numbers = []
    for group in to_create:
        order, lines = await build_order(
            db,
            context,
            site,
            group["customer"],
            group["reference"],
            group["order_date"],
            group["notes"],
            [line for _, line, _ in group["lines"]],
        )
        numbers.append(order.number)
        audit(
            db,
            context,
            request,
            "orders.created",
            {
                "order_id": str(order.id),
                "number": order.number,
                "customer": group["customer"].code,
                "customer_reference": group["reference"],
                "lines": [line_snapshot(line) for line in lines],
                "source": "import",
            },
        )
    audit(
        db,
        context,
        request,
        "orders.import_committed",
        {
            "site_id": str(site.id),
            "orders": numbers,
            "unchanged": unchanged,
            "file_sha256": hashlib.sha256(payload.csv_text.encode()).hexdigest(),
        },
    )
    await commit_or_conflict(db, "Another change created one of these orders; preview again")
    report.committed = True
    report.created_numbers = numbers
    return report
