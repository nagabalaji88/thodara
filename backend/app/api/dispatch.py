"""Dispatch against customer orders (slice F8).

A dispatch note is posted when goods leave the site. It raises the shipped quantity on each
order line, uses up finished-goods stock first and then the components the rest was built from
(accepted outsourced material and component stock, G2), and can only be undone by cancelling
it with a reason, which reverses exactly what it did.
"""

import uuid
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    AuthContext,
    require_csrf,
    require_permission,
)
from app.api.masterdata import STALE, audit, commit_or_conflict
from app.api.orders import check_precision, close_if_finished, get_order, plain, to_unit
from app.core.audit import actor_label
from app.db.session import get_db
from app.models.dispatch import DispatchLine, DispatchNote
from app.models.identity import Site
from app.models.inventory import StockMovement
from app.models.masterdata import Customer, Item, UnitOfMeasure
from app.models.orders import OrderLineComponent, SalesOrder, SalesOrderLine
from app.models.outsourcing import BatchAllocation, OutsourcedBatch
from app.schemas.dispatch import (
    DispatchCancel,
    DispatchCreate,
    DispatchDecision,
    DispatchLineOut,
    DispatchOut,
    LineReadiness,
    Readiness,
    ReadinessComponent,
)
from app.services.fulfillment import ZERO, unit_step
from app.services.numbering import allocate_number
from app.services.risk import LineRisk
from app.services.risk_loader import assess_lines
from app.services.stock import put_back, take_stock

router = APIRouter(prefix="/dispatch", tags=["dispatch"])
READ = require_permission("orders:read")
MANAGE = require_permission("dispatch:manage")
APPROVE = require_permission("dispatch:approve")
CSRF = [Depends(require_csrf)]


def now() -> datetime:
    return datetime.now(UTC)


async def dispatch_out(db: AsyncSession, note: DispatchNote, context: AuthContext) -> DispatchOut:
    order = await db.get(SalesOrder, note.order_id)
    customer = await db.get(Customer, order.customer_id)
    site = await db.get(Site, note.site_id)
    lines = []
    for dl, line, item_code, unit in await db.execute(
        select(DispatchLine, SalesOrderLine, Item.code, UnitOfMeasure)
        .join(SalesOrderLine, SalesOrderLine.id == DispatchLine.line_id)
        .join(Item, Item.id == SalesOrderLine.item_id)
        .join(UnitOfMeasure, UnitOfMeasure.id == SalesOrderLine.unit_id)
        .where(DispatchLine.dispatch_id == note.id)
        .order_by(SalesOrderLine.line_no)
    ):
        lines.append(
            DispatchLineOut(
                line_id=line.id,
                line_no=line.line_no,
                item_code=item_code,
                unit_code=unit.code,
                quantity=to_unit(dl.quantity, unit),
                promised_date=dl.promised_date,
                on_time=dl.on_time,
                exception_reason=dl.exception_reason,
            )
        )
    return DispatchOut(
        id=note.id,
        number=note.number,
        order_id=order.id,
        order_number=order.number,
        customer_name=customer.name,
        site_name=site.name,
        dispatch_date=note.dispatch_date,
        carrier=note.carrier,
        vehicle_reference=note.vehicle_reference,
        document_reference=note.document_reference,
        note=note.note,
        status=note.status,
        cancel_reason=note.cancel_reason,
        created_by_label=note.created_by_label,
        created_at=note.created_at,
        cancelled_by_label=note.cancelled_by_label,
        cancelled_at=note.cancelled_at,
        decided_by_label=note.decided_by_label,
        decided_at=note.decided_at,
        decision_note=note.decision_note,
        can_decide=note.status == "pending_approval"
        and "dispatch:approve" in context.permissions
        and note.created_by != context.user.id,
        version=note.version,
        lines=lines,
    )


async def get_note(db: AsyncSession, context: AuthContext, note_id: uuid.UUID) -> DispatchNote:
    note = await db.scalar(
        select(DispatchNote).where(
            DispatchNote.tenant_id == context.tenant.id, DispatchNote.id == note_id
        )
    )
    if note is None or not context.can_access_site(note.site_id):
        raise HTTPException(status_code=404, detail="Dispatch note not found")
    return note


# Readiness: how much of each line can ship from stock and accepted material -----


class Tracked:
    """One tracked component of a line and what is available to it now.

    Outsourced components are served by accepted batch material; components without an
    outsourced step by the site's stock of the item, once it is tracked there (ADR-0010).
    """

    def __init__(self, component: OrderLineComponent, unit: UnitOfMeasure, risk) -> None:
        self.component = component
        self.unit = unit
        view = next((c for c in risk.components if c.component_id == component.id), None)
        self.from_stock = bool(view and view.stock_tracked)
        self.shares = list(view.allocations) if view else []
        self.usable = (
            view.in_stock if self.from_stock else sum((a.accepted for a in self.shares), ZERO)
        )

    def need(self, quantity: Decimal) -> Decimal:
        return (self.component.qty_per_unit * quantity).quantize(
            unit_step(self.unit), rounding=ROUND_CEILING
        )


class Supply:
    """Everything that limits and feeds one line: finished goods first, then components."""

    def __init__(self, risk: LineRisk | None = None) -> None:
        self.parts: list[Tracked] = []
        # None when the line's item has no stock record at the site (not tracked).
        self.finished: Decimal | None = risk.from_stock if risk and risk.stock_tracked else None


async def tracked_components(
    db: AsyncSession, risks: dict[uuid.UUID, LineRisk]
) -> dict[uuid.UUID, Supply]:
    tracked = {line_id: Supply(risk) for line_id, risk in risks.items()}
    if not risks:
        return tracked
    for component, unit in await db.execute(
        select(OrderLineComponent, UnitOfMeasure)
        .join(UnitOfMeasure, UnitOfMeasure.id == OrderLineComponent.unit_id)
        .where(OrderLineComponent.line_id.in_(risks))
    ):
        allocated = await db.scalar(
            select(BatchAllocation.id).where(BatchAllocation.component_id == component.id)
        )
        part = Tracked(component, unit, risks[component.line_id])
        # Untracked components (no outsourced step, no stock record) are not checked.
        if component.outsourced_operation or allocated or part.from_stock:
            tracked[component.line_id].parts.append(part)
    return tracked


def shippable(line: SalesOrderLine, unit: UnitOfMeasure, supply: Supply) -> Decimal | None:
    """Finished goods for the line plus what its tracked components can build.

    None when no component is tracked: what can be built is then not checked.
    """
    if not supply.parts:
        return None
    remaining = line.ordered_qty - line.shipped_qty - line.cancelled_qty - line.short_closed_qty
    build = remaining
    for t in supply.parts:
        build = min(
            build,
            (t.usable / t.component.qty_per_unit).quantize(unit_step(unit), rounding=ROUND_FLOOR),
        )
    return max(min(remaining, (supply.finished or ZERO) + build), ZERO)


async def order_readiness(db: AsyncSession, context: AuthContext, order: SalesOrder):
    risks = {
        r.line_id: r
        for r in await assess_lines(db, context.tenant.id, context.site_ids, order.id, now())
    }
    return risks, await tracked_components(db, risks)


@router.get("/readiness", response_model=Readiness)
async def readiness(
    order_id: uuid.UUID,
    context: AuthContext = Depends(READ),
    db: AsyncSession = Depends(get_db),
):
    order = await get_order(db, context, order_id)
    risks, tracked = await order_readiness(db, context, order)
    lines = []
    for line, item_code, unit in await db.execute(
        select(SalesOrderLine, Item.code, UnitOfMeasure)
        .join(Item, Item.id == SalesOrderLine.item_id)
        .join(UnitOfMeasure, UnitOfMeasure.id == SalesOrderLine.unit_id)
        .where(SalesOrderLine.order_id == order.id, SalesOrderLine.id.in_(risks))
        .order_by(SalesOrderLine.line_no)
    ):
        supply = tracked[line.id]
        limit = shippable(line, unit, supply)
        lines.append(
            LineReadiness(
                line_id=line.id,
                line_no=line.line_no,
                item_code=item_code,
                unit_code=unit.code,
                remaining=to_unit(risks[line.id].remaining, unit),
                promised_date=line.promised_date,
                shippable=to_unit(limit, unit) if limit is not None else None,
                finished_stock=to_unit(supply.finished, unit)
                if supply.finished is not None
                else None,
                components=[
                    ReadinessComponent(
                        item_code=next(
                            c.item_code
                            for c in risks[line.id].components
                            if c.component_id == t.component.id
                        ),
                        unit_code=t.unit.code,
                        qty_per_unit=t.component.qty_per_unit.normalize(),
                        usable_for_line=to_unit(t.usable, t.unit),
                        source="stock" if t.from_stock else "batch",
                    )
                    for t in supply.parts
                ],
            )
        )
    return Readiness(order_id=order.id, lines=lines)


# Posting -------------------------------------------------------------------------


async def check_lines(
    db: AsyncSession,
    context: AuthContext,
    order: SalesOrder,
    wanted: list[tuple[uuid.UUID, Decimal, str | None]],
    allow_over: bool,
):
    """Validate each requested line against what is left and what accepted material allows.

    Returns (line, quantity, exception reason, tracked components, over the limit?) per line.
    """
    lines = {
        line.id: line
        for line in await db.scalars(
            select(SalesOrderLine).where(
                SalesOrderLine.order_id == order.id,
                SalesOrderLine.id.in_([line_id for line_id, _, _ in wanted]),
            )
        )
    }
    if len(lines) != len(wanted):
        raise HTTPException(status_code=422, detail="Every line must belong to this order")
    _, tracked = await order_readiness(db, context, order)
    checked = []
    for line_id, quantity, reason in wanted:
        line = lines[line_id]
        unit = await db.get(UnitOfMeasure, line.unit_id)
        check_precision(quantity, unit)
        if line.status != "open":
            raise HTTPException(status_code=409, detail=f"Line {line.line_no} is not open")
        remaining = line.ordered_qty - line.shipped_qty - line.cancelled_qty - line.short_closed_qty
        if quantity > remaining:
            raise HTTPException(
                status_code=422,
                detail=f"Line {line.line_no} has only {plain(remaining)} {unit.code} left to ship",
            )
        items = tracked.get(line.id) or Supply()
        limit = shippable(line, unit, items)
        over = limit is not None and quantity > limit
        if over and not reason:
            raise HTTPException(
                status_code=422,
                detail=f"Line {line.line_no}: only {plain(limit)} {unit.code} can ship from "
                "finished-goods stock and accepted, usable material. Shipping more needs an "
                "exception with a reason, approved by someone else.",
            )
        if over and not allow_over:
            raise HTTPException(status_code=409, detail="This exception still needs approval")
        checked.append((line, quantity, reason if over else None, items, over))
    return checked


async def apply_dispatch(
    db: AsyncSession, note: DispatchNote, order: SalesOrder, rows: list[DispatchLine], checked
) -> list[dict]:
    """Post the dispatch: ship, use stock and accepted material, fulfil lines, close the order.

    Finished goods go first; the rest is built from the components. Only what is there is used,
    even under an approved exception, so stock never goes below zero.
    """
    summary = []
    by_line = {row.line_id: row for row in rows}
    taking = {
        "tenant_id": note.tenant_id,
        "site_id": note.site_id,
        "movement_date": note.dispatch_date,
        "dispatch_id": note.id,
        "reference": note.number,
        "user_id": note.created_by,
        "user_label": note.created_by_label,
    }
    for line, quantity, exception, supply, _ in checked:
        consumption = []
        built = quantity
        if supply.finished is not None:
            finished = min(quantity, supply.finished)
            consumption += await take_stock(db, item_id=line.item_id, quantity=finished, **taking)
            built = quantity - finished
        for t in supply.parts:
            need = t.need(built)
            if t.from_stock:
                consumption += await take_stock(
                    db, item_id=t.component.item_id, quantity=min(need, t.usable), **taking
                )
                continue
            for share in sorted(t.shares, key=lambda a: a.accepted, reverse=True):
                take = min(need, share.accepted)
                if take <= 0:
                    continue
                allocation = await db.get(BatchAllocation, share.allocation_id)
                allocation.consumed_qty += take
                consumption.append({"allocation_id": str(allocation.id), "consumed": plain(take)})
                need -= take
        line.shipped_qty += quantity
        on_time = note.dispatch_date <= line.promised_date if line.promised_date else None
        if line.ordered_qty - line.shipped_qty - line.cancelled_qty - line.short_closed_qty == 0:
            line.status = "fulfilled"
            # Whatever the line still had earmarked in batches is free for other orders.
            for allocation in await db.scalars(
                select(BatchAllocation)
                .join(OrderLineComponent, OrderLineComponent.id == BatchAllocation.component_id)
                .where(OrderLineComponent.line_id == line.id)
            ):
                spare = allocation.quantity - allocation.consumed_qty
                if spare <= 0:
                    continue
                consumption.append(
                    {
                        "allocation_id": str(allocation.id),
                        "batch_id": str(allocation.batch_id),
                        "component_id": str(allocation.component_id),
                        "released": plain(spare),
                    }
                )
                if allocation.consumed_qty > 0:
                    allocation.quantity = allocation.consumed_qty
                else:
                    await db.delete(allocation)
        row = by_line[line.id]
        row.promised_date = line.promised_date
        row.on_time = on_time
        row.consumption = consumption
        summary.append(
            {
                "line_no": line.line_no,
                "quantity": plain(quantity),
                "on_time": on_time,
                "exception_reason": exception,
                "consumption": consumption,
            }
        )
    note.status = "posted"
    await db.flush()
    await close_if_finished(db, order)
    order.updated_at = now()
    return summary


@router.post("", response_model=DispatchOut, status_code=201, dependencies=CSRF)
async def post_dispatch(
    payload: DispatchCreate,
    request: Request,
    response: Response,
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    replay = await db.scalar(
        select(DispatchNote).where(
            DispatchNote.tenant_id == context.tenant.id,
            DispatchNote.submission_key == payload.submission_key,
        )
    )
    if replay is not None:
        response.status_code = 200
        return await dispatch_out(db, await get_note(db, context, replay.id), context)
    order = await get_order(db, context, payload.order_id)
    if order.status != "confirmed":
        raise HTTPException(status_code=409, detail="Only confirmed orders can be dispatched")
    site = await db.get(Site, order.site_id)
    if payload.dispatch_date > datetime.now(ZoneInfo(site.time_zone)).date():
        raise HTTPException(status_code=422, detail="The dispatch date cannot be in the future")
    if payload.dispatch_date < order.order_date:
        raise HTTPException(status_code=422, detail="The dispatch date is before the order date")
    line_ids = [entry.line_id for entry in payload.lines]
    if len(set(line_ids)) != len(line_ids):
        raise HTTPException(status_code=422, detail="List each order line once")
    checked = await check_lines(
        db,
        context,
        order,
        [(e.line_id, e.quantity, e.exception_reason) for e in payload.lines],
        allow_over=True,
    )
    pending = any(over for *_, over in checked)
    note = DispatchNote(
        id=uuid.uuid4(),
        tenant_id=context.tenant.id,
        site_id=order.site_id,
        order_id=order.id,
        number=await allocate_number(db, context.tenant.id, "dispatch"),
        dispatch_date=payload.dispatch_date,
        carrier=payload.carrier,
        vehicle_reference=payload.vehicle_reference,
        document_reference=payload.document_reference,
        note=payload.note,
        status="pending_approval" if pending else "posted",
        submission_key=payload.submission_key,
        created_by=context.user.id,
        created_by_label=actor_label(context.user),
        created_at=now(),
    )
    db.add(note)
    await db.flush()
    rows = [
        DispatchLine(
            id=uuid.uuid4(),
            tenant_id=context.tenant.id,
            dispatch_id=note.id,
            line_id=line.id,
            quantity=quantity,
            promised_date=line.promised_date,
            exception_reason=exception,
        )
        for line, quantity, exception, _, _ in checked
    ]
    db.add_all(rows)
    await db.flush()
    details = {
        "dispatch_id": str(note.id),
        "number": note.number,
        "order": order.number,
        "dispatch_date": note.dispatch_date.isoformat(),
        "document_reference": note.document_reference,
    }
    if pending:
        # Nothing ships until someone other than the requester approves the exception.
        details["lines"] = [
            {"line_no": line.line_no, "quantity": plain(q), "exception_reason": reason}
            for line, q, reason, _, _ in checked
        ]
        audit(db, context, request, "dispatch.exception_requested", details)
    else:
        details["lines"] = await apply_dispatch(db, note, order, rows, checked)
        audit(db, context, request, "dispatch.posted", details)
    await commit_or_conflict(db, "This dispatch could not be saved; reload the order")
    return await dispatch_out(db, note, context)


async def pending_note(db, context, note_id, version) -> DispatchNote:
    note = await get_note(db, context, note_id)
    if note.version != version:
        raise HTTPException(status_code=409, detail=STALE)
    if note.status != "pending_approval":
        raise HTTPException(status_code=409, detail="This dispatch is not waiting for approval")
    if note.created_by == context.user.id:
        raise HTTPException(
            status_code=403, detail="You cannot decide on a dispatch exception you requested"
        )
    return note


@router.post("/{note_id}/approve", response_model=DispatchOut, dependencies=CSRF)
async def approve_dispatch(
    note_id: uuid.UUID,
    payload: DispatchDecision,
    request: Request,
    context: AuthContext = Depends(APPROVE),
    db: AsyncSession = Depends(get_db),
):
    note = await pending_note(db, context, note_id, payload.version)
    order = await db.get(SalesOrder, note.order_id)
    if order.status != "confirmed":
        raise HTTPException(status_code=409, detail=f"Order {order.number} is {order.status}")
    rows = list(await db.scalars(select(DispatchLine).where(DispatchLine.dispatch_id == note.id)))
    # Re-checked now: quantities left and accepted material may have changed since the request.
    checked = await check_lines(
        db,
        context,
        order,
        [(row.line_id, row.quantity, row.exception_reason) for row in rows],
        allow_over=True,
    )
    note.decided_by = context.user.id
    note.decided_by_label = actor_label(context.user)
    note.decided_at = now()
    note.decision_note = payload.note
    summary = await apply_dispatch(db, note, order, rows, checked)
    audit(
        db,
        context,
        request,
        "dispatch.exception_approved",
        {
            "dispatch_id": str(note.id),
            "number": note.number,
            "note": payload.note,
            "lines": summary,
        },
    )
    await commit_or_conflict(db, STALE)
    return await dispatch_out(db, note, context)


@router.post("/{note_id}/reject", response_model=DispatchOut, dependencies=CSRF)
async def reject_dispatch(
    note_id: uuid.UUID,
    payload: DispatchCancel,
    request: Request,
    context: AuthContext = Depends(APPROVE),
    db: AsyncSession = Depends(get_db),
):
    note = await pending_note(db, context, note_id, payload.version)
    note.status = "rejected"
    note.decided_by = context.user.id
    note.decided_by_label = actor_label(context.user)
    note.decided_at = now()
    note.decision_note = payload.reason
    audit(
        db,
        context,
        request,
        "dispatch.exception_rejected",
        {"dispatch_id": str(note.id), "number": note.number, "reason": payload.reason},
    )
    await commit_or_conflict(db, STALE)
    return await dispatch_out(db, note, context)


@router.get("", response_model=list[DispatchOut])
async def list_dispatches(
    order_id: uuid.UUID | None = None,
    status: str | None = Query(
        default=None, pattern="^(pending_approval|posted|rejected|cancelled)$"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    context: AuthContext = Depends(READ),
    db: AsyncSession = Depends(get_db),
):
    query = select(DispatchNote).where(DispatchNote.tenant_id == context.tenant.id)
    if context.site_ids is not None:
        query = query.where(DispatchNote.site_id.in_(context.site_ids))
    if order_id is not None:
        query = query.where(DispatchNote.order_id == order_id)
    if status is not None:
        query = query.where(DispatchNote.status == status)
    notes = await db.scalars(
        query.order_by(DispatchNote.dispatch_date.desc(), DispatchNote.number.desc()).limit(limit)
    )
    return [await dispatch_out(db, note, context) for note in notes]


@router.get("/{note_id}", response_model=DispatchOut)
async def read_dispatch(
    note_id: uuid.UUID,
    context: AuthContext = Depends(READ),
    db: AsyncSession = Depends(get_db),
):
    return await dispatch_out(db, await get_note(db, context, note_id), context)


@router.post("/{note_id}/cancel", response_model=DispatchOut, dependencies=CSRF)
async def cancel_dispatch(
    note_id: uuid.UUID,
    payload: DispatchCancel,
    request: Request,
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    note = await get_note(db, context, note_id)
    if note.version != payload.version:
        raise HTTPException(status_code=409, detail=STALE)
    if note.status != "posted":
        raise HTTPException(status_code=409, detail="Only a posted dispatch note can be cancelled")
    order = await db.get(SalesOrder, note.order_id)
    site = await db.get(Site, note.site_id)
    for dl in list(
        await db.scalars(select(DispatchLine).where(DispatchLine.dispatch_id == note.id))
    ):
        line = await db.get(SalesOrderLine, dl.line_id)
        if line.status not in ("open", "fulfilled"):
            raise HTTPException(
                status_code=409,
                detail=f"Line {line.line_no} was {line.status.replace('_', '-')} after this "
                "dispatch; it cannot be reversed",
            )
        line.shipped_qty -= dl.quantity
        line.status = "open"
        for step in dl.consumption or []:
            if "stock_movement_id" in step:
                used = await db.get(StockMovement, uuid.UUID(step["stock_movement_id"]))
                await put_back(
                    db,
                    used,
                    reason=f"Dispatch {note.number} cancelled: {payload.reason}",
                    movement_date=datetime.now(ZoneInfo(site.time_zone)).date(),
                    user_id=context.user.id,
                    user_label=actor_label(context.user),
                )
                continue
            allocation = await db.get(BatchAllocation, uuid.UUID(step["allocation_id"]))
            if "consumed" in step and allocation is not None:
                allocation.consumed_qty -= Decimal(step["consumed"])
            elif "released" in step:
                if allocation is not None:
                    allocation.quantity += Decimal(step["released"])
                else:
                    batch = await db.get(OutsourcedBatch, uuid.UUID(step["batch_id"]))
                    if batch is not None and batch.status in ("planned", "at_supplier"):
                        db.add(
                            BatchAllocation(
                                id=uuid.UUID(step["allocation_id"]),
                                tenant_id=note.tenant_id,
                                batch_id=batch.id,
                                component_id=uuid.UUID(step["component_id"]),
                                quantity=Decimal(step["released"]),
                                created_by=context.user.id,
                            )
                        )
    if order.status == "closed":
        order.status = "confirmed"
    order.updated_at = now()
    note.status = "cancelled"
    note.cancel_reason = payload.reason
    note.cancelled_by = context.user.id
    note.cancelled_by_label = actor_label(context.user)
    note.cancelled_at = now()
    audit(
        db,
        context,
        request,
        "dispatch.cancelled",
        {"dispatch_id": str(note.id), "number": note.number, "reason": payload.reason},
    )
    await commit_or_conflict(db, STALE)
    return await dispatch_out(db, note, context)
