"""Basic stock per warehouse (slice G2, ADR-0010).

Receipts and issues post at once. Opening balances and adjustments wait for someone other
than the person who entered them to approve. Nothing is edited: mistakes are reversed by an
opposite movement. Stock never goes below zero.
"""

import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AuthContext, require_csrf, require_permission
from app.api.masterdata import STALE, audit, commit_or_conflict
from app.api.orders import check_precision
from app.core.audit import actor_label
from app.db.session import get_db
from app.models.dispatch import DispatchNote
from app.models.identity import Site
from app.models.inventory import NEEDS_APPROVAL, StockBalance, StockMovement
from app.models.masterdata import Item, UnitOfMeasure, Warehouse
from app.schemas.stock import (
    StockBalanceOut,
    StockDecision,
    StockMovementCreate,
    StockMovementOut,
    StockReject,
    StockReverse,
    StockSummary,
)
from app.services.stock import plain, post_movement

router = APIRouter(prefix="/stock", tags=["stock"])
READ = require_permission("stock:read")
RECORD = require_permission("stock:record")
APPROVE = require_permission("stock:approve")
CSRF = [Depends(require_csrf)]
REVERSIBLE = ("opening", "receipt", "issue", "adjustment")


def now() -> datetime:
    return datetime.now(UTC)


async def reversal_of(db: AsyncSession, movement_id: uuid.UUID) -> StockMovement | None:
    return await db.scalar(
        select(StockMovement).where(
            StockMovement.reverses_id == movement_id,
            StockMovement.status.in_(("pending_approval", "posted")),
        )
    )


async def movement_out(
    db: AsyncSession, movement: StockMovement, context: AuthContext
) -> StockMovementOut:
    item = await db.get(Item, movement.item_id)
    unit = await db.get(UnitOfMeasure, item.base_unit_id)
    warehouse = await db.get(Warehouse, movement.warehouse_id)
    site = await db.get(Site, movement.site_id)
    dispatch = await db.get(DispatchNote, movement.dispatch_id) if movement.dispatch_id else None
    reversed_ = await reversal_of(db, movement.id) is not None
    return StockMovementOut(
        id=movement.id,
        site_id=site.id,
        site_name=site.name,
        warehouse_id=warehouse.id,
        warehouse_code=warehouse.code,
        item_id=item.id,
        item_code=item.code,
        item_name=item.name,
        unit_code=unit.code,
        kind=movement.kind,
        quantity=movement.quantity,
        status=movement.status,
        movement_date=movement.movement_date,
        reason=movement.reason,
        reference=movement.reference,
        balance_after=movement.balance_after,
        dispatch_id=movement.dispatch_id,
        dispatch_number=dispatch.number if dispatch else None,
        reverses_id=movement.reverses_id,
        reversed=reversed_,
        created_by_label=movement.created_by_label,
        created_at=movement.created_at,
        decided_by_label=movement.decided_by_label,
        decided_at=movement.decided_at,
        decision_note=movement.decision_note,
        can_decide=movement.status == "pending_approval"
        and "stock:approve" in context.permissions
        and movement.created_by != context.user.id,
        can_reverse=movement.status == "posted"
        and movement.kind in REVERSIBLE
        and not reversed_
        and "stock:record" in context.permissions,
        version=movement.version,
    )


async def get_movement(
    db: AsyncSession, context: AuthContext, movement_id: uuid.UUID
) -> StockMovement:
    movement = await db.scalar(
        select(StockMovement).where(
            StockMovement.tenant_id == context.tenant.id, StockMovement.id == movement_id
        )
    )
    if movement is None or not context.can_access_site(movement.site_id):
        raise HTTPException(status_code=404, detail="Stock movement not found")
    return movement


def site_today(site: Site):
    return now().astimezone(ZoneInfo(site.time_zone)).date()


@router.get("/balances", response_model=StockSummary)
async def list_balances(
    site_id: uuid.UUID | None = None,
    item_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=80),
    context: AuthContext = Depends(READ),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(StockBalance, Item, UnitOfMeasure.code, Warehouse, Site)
        .join(Item, Item.id == StockBalance.item_id)
        .join(UnitOfMeasure, UnitOfMeasure.id == Item.base_unit_id)
        .join(Warehouse, Warehouse.id == StockBalance.warehouse_id)
        .join(Site, Site.id == StockBalance.site_id)
        .where(StockBalance.tenant_id == context.tenant.id)
        .order_by(Item.code, Site.name, Warehouse.code)
    )
    if context.site_ids is not None:
        query = query.where(StockBalance.site_id.in_(context.site_ids))
    if site_id is not None:
        query = query.where(StockBalance.site_id == site_id)
    if item_id is not None:
        query = query.where(StockBalance.item_id == item_id)
    if q:
        like = f"%{q.strip().upper()}%"
        query = query.where(func.upper(Item.code).like(like) | func.upper(Item.name).like(like))
    pending_query = (
        select(StockMovement.warehouse_id, StockMovement.item_id, func.count())
        .where(
            StockMovement.tenant_id == context.tenant.id,
            StockMovement.status == "pending_approval",
        )
        .group_by(StockMovement.warehouse_id, StockMovement.item_id)
    )
    pending = {(w, i): n for w, i, n in await db.execute(pending_query)}
    balances = [
        StockBalanceOut(
            site_id=site.id,
            site_name=site.name,
            warehouse_id=warehouse.id,
            warehouse_code=warehouse.code,
            warehouse_name=warehouse.name,
            item_id=item.id,
            item_code=item.code,
            item_name=item.name,
            item_type=item.item_type,
            unit_code=unit_code,
            on_hand=balance.on_hand,
            pending=pending.get((warehouse.id, item.id), 0),
        )
        for balance, item, unit_code, warehouse, site in await db.execute(query.limit(500))
    ]
    mine = select(func.count()).where(
        StockMovement.tenant_id == context.tenant.id,
        StockMovement.status == "pending_approval",
        StockMovement.created_by != context.user.id,
    )
    if context.site_ids is not None:
        mine = mine.where(StockMovement.site_id.in_(context.site_ids))
    pending_for_me = (await db.scalar(mine) if "stock:approve" in context.permissions else 0) or 0
    return StockSummary(balances=balances, pending_for_me=pending_for_me)


@router.get("/movements", response_model=list[StockMovementOut])
async def list_movements(
    item_id: uuid.UUID | None = None,
    warehouse_id: uuid.UUID | None = None,
    status: str | None = Query(default=None, pattern="^(pending_approval|posted|rejected)$"),
    limit: int = Query(default=100, ge=1, le=500),
    context: AuthContext = Depends(READ),
    db: AsyncSession = Depends(get_db),
):
    query = select(StockMovement).where(StockMovement.tenant_id == context.tenant.id)
    if context.site_ids is not None:
        query = query.where(StockMovement.site_id.in_(context.site_ids))
    if item_id is not None:
        query = query.where(StockMovement.item_id == item_id)
    if warehouse_id is not None:
        query = query.where(StockMovement.warehouse_id == warehouse_id)
    if status is not None:
        query = query.where(StockMovement.status == status)
    movements = await db.scalars(
        query.order_by(StockMovement.created_at.desc(), StockMovement.id).limit(limit)
    )
    return [await movement_out(db, m, context) for m in movements]


@router.post("/movements", response_model=StockMovementOut, status_code=201, dependencies=CSRF)
async def record_movement(
    payload: StockMovementCreate,
    request: Request,
    response: Response,
    context: AuthContext = Depends(RECORD),
    db: AsyncSession = Depends(get_db),
):
    replay = await db.scalar(
        select(StockMovement).where(
            StockMovement.tenant_id == context.tenant.id,
            StockMovement.submission_key == payload.submission_key,
        )
    )
    if replay is not None:
        response.status_code = 200
        return await movement_out(db, await get_movement(db, context, replay.id), context)
    warehouse = await db.scalar(
        select(Warehouse).where(
            Warehouse.tenant_id == context.tenant.id, Warehouse.id == payload.warehouse_id
        )
    )
    if warehouse is None or not context.can_access_site(warehouse.site_id):
        raise HTTPException(status_code=404, detail="Warehouse not found")
    if warehouse.status != "active":
        raise HTTPException(status_code=409, detail=f"Warehouse {warehouse.code} is inactive")
    item = await db.scalar(
        select(Item).where(Item.tenant_id == context.tenant.id, Item.id == payload.item_id)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    if item.status != "active":
        raise HTTPException(status_code=409, detail=f"Item {item.code} is inactive")
    if item.item_type == "service":
        raise HTTPException(status_code=422, detail="Services are not held in stock")
    unit = await db.get(UnitOfMeasure, item.base_unit_id)
    check_precision(payload.quantity, unit)
    site = await db.get(Site, warehouse.site_id)
    if payload.movement_date > site_today(site):
        raise HTTPException(status_code=422, detail="The date cannot be in the future")
    if payload.kind == "adjustment":
        if payload.direction is None:
            raise HTTPException(
                status_code=422, detail="Say whether the adjustment adds or removes stock"
            )
        sign = 1 if payload.direction == "in" else -1
    elif payload.direction is not None:
        raise HTTPException(status_code=422, detail="Only adjustments take a direction")
    else:
        sign = -1 if payload.kind == "issue" else 1
    if payload.kind in ("issue", "adjustment") and not payload.reason:
        raise HTTPException(status_code=422, detail="Give a reason for issues and adjustments")
    if payload.kind == "opening":
        existing = await db.scalar(
            select(StockMovement.id).where(
                StockMovement.tenant_id == context.tenant.id,
                StockMovement.warehouse_id == warehouse.id,
                StockMovement.item_id == item.id,
                StockMovement.kind == "opening",
                StockMovement.status.in_(("pending_approval", "posted")),
            )
        )
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=f"{item.code} already has an opening balance in {warehouse.code}; "
                "use an adjustment",
            )
    movement = StockMovement(
        id=uuid.uuid4(),
        tenant_id=context.tenant.id,
        site_id=warehouse.site_id,
        warehouse_id=warehouse.id,
        item_id=item.id,
        kind=payload.kind,
        quantity=payload.quantity * sign,
        status="pending_approval",
        movement_date=payload.movement_date,
        reason=payload.reason,
        reference=payload.reference,
        submission_key=payload.submission_key,
        created_by=context.user.id,
        created_by_label=actor_label(context.user),
        created_at=now(),
    )
    db.add(movement)
    await db.flush()
    details = {
        "movement_id": str(movement.id),
        "kind": movement.kind,
        "item": item.code,
        "warehouse": warehouse.code,
        "quantity": plain(movement.quantity),
        "unit": unit.code,
        "movement_date": movement.movement_date.isoformat(),
        "reason": movement.reason,
        "reference": movement.reference,
    }
    if payload.kind in NEEDS_APPROVAL:
        audit(db, context, request, "stock.approval_requested", details)
    else:
        await post_movement(db, movement)
        details["balance_after"] = plain(movement.balance_after)
        audit(db, context, request, "stock.posted", details)
    await commit_or_conflict(db, "This stock entry could not be saved; reload and try again")
    return await movement_out(db, movement, context)


async def pending_movement(db, context, movement_id, version) -> StockMovement:
    movement = await get_movement(db, context, movement_id)
    if movement.version != version:
        raise HTTPException(status_code=409, detail=STALE)
    if movement.status != "pending_approval":
        raise HTTPException(status_code=409, detail="This entry is not waiting for approval")
    if movement.created_by == context.user.id:
        raise HTTPException(
            status_code=403, detail="You cannot approve or reject a stock entry you made"
        )
    return movement


def decide(movement: StockMovement, context: AuthContext, note: str | None) -> None:
    movement.decided_by = context.user.id
    movement.decided_by_label = actor_label(context.user)
    movement.decided_at = now()
    movement.decision_note = note


@router.post("/movements/{movement_id}/approve", response_model=StockMovementOut, dependencies=CSRF)
async def approve_movement(
    movement_id: uuid.UUID,
    payload: StockDecision,
    request: Request,
    context: AuthContext = Depends(APPROVE),
    db: AsyncSession = Depends(get_db),
):
    movement = await pending_movement(db, context, movement_id, payload.version)
    decide(movement, context, payload.note)
    # The balance is checked now, not when it was entered.
    await post_movement(db, movement)
    audit(
        db,
        context,
        request,
        "stock.approved",
        {
            "movement_id": str(movement.id),
            "kind": movement.kind,
            "quantity": plain(movement.quantity),
            "balance_after": plain(movement.balance_after),
            "note": payload.note,
        },
    )
    await commit_or_conflict(db, STALE)
    return await movement_out(db, movement, context)


@router.post("/movements/{movement_id}/reject", response_model=StockMovementOut, dependencies=CSRF)
async def reject_movement(
    movement_id: uuid.UUID,
    payload: StockReject,
    request: Request,
    context: AuthContext = Depends(APPROVE),
    db: AsyncSession = Depends(get_db),
):
    movement = await pending_movement(db, context, movement_id, payload.version)
    decide(movement, context, payload.reason)
    movement.status = "rejected"
    audit(
        db,
        context,
        request,
        "stock.rejected",
        {"movement_id": str(movement.id), "kind": movement.kind, "reason": payload.reason},
    )
    await commit_or_conflict(db, STALE)
    return await movement_out(db, movement, context)


@router.post(
    "/movements/{movement_id}/reverse",
    response_model=StockMovementOut,
    status_code=201,
    dependencies=CSRF,
)
async def reverse_movement(
    movement_id: uuid.UUID,
    payload: StockReverse,
    request: Request,
    response: Response,
    context: AuthContext = Depends(RECORD),
    db: AsyncSession = Depends(get_db),
):
    replay = await db.scalar(
        select(StockMovement).where(
            StockMovement.tenant_id == context.tenant.id,
            StockMovement.submission_key == payload.submission_key,
        )
    )
    if replay is not None:
        response.status_code = 200
        return await movement_out(db, await get_movement(db, context, replay.id), context)
    original = await get_movement(db, context, movement_id)
    if original.version != payload.version:
        raise HTTPException(status_code=409, detail=STALE)
    if original.status != "posted" or original.kind not in REVERSIBLE:
        raise HTTPException(
            status_code=409,
            detail="Only a posted opening, receipt, issue or adjustment can be reversed here",
        )
    if await reversal_of(db, original.id) is not None:
        raise HTTPException(status_code=409, detail="This entry has already been reversed")
    site = await db.get(Site, original.site_id)
    reversal = StockMovement(
        id=uuid.uuid4(),
        tenant_id=original.tenant_id,
        site_id=original.site_id,
        warehouse_id=original.warehouse_id,
        item_id=original.item_id,
        kind="reversal",
        quantity=-original.quantity,
        status="pending_approval",
        movement_date=site_today(site),
        reason=payload.reason,
        reference=original.reference,
        reverses_id=original.id,
        submission_key=payload.submission_key,
        created_by=context.user.id,
        created_by_label=actor_label(context.user),
        created_at=now(),
    )
    db.add(reversal)
    await db.flush()
    details = {
        "movement_id": str(reversal.id),
        "reverses": str(original.id),
        "kind": original.kind,
        "quantity": plain(reversal.quantity),
        "reason": payload.reason,
    }
    # Reversing an entry that needed approval needs approval too.
    if original.kind in NEEDS_APPROVAL:
        audit(db, context, request, "stock.approval_requested", details)
    else:
        await post_movement(db, reversal)
        details["balance_after"] = plain(reversal.balance_after)
        audit(db, context, request, "stock.posted", details)
    await commit_or_conflict(db, "This reversal could not be saved; reload and try again")
    return await movement_out(db, reversal, context)
