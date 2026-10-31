"""Posting stock movements and reading on-hand quantities (slice G2, ADR-0010)."""

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import tr
from app.models.inventory import StockBalance, StockMovement
from app.models.masterdata import Item, UnitOfMeasure, Warehouse

ZERO = Decimal(0)


def plain(quantity: Decimal) -> str:
    return format(quantity.normalize(), "f")


async def post_movement(db: AsyncSession, movement: StockMovement) -> None:
    """Apply a movement to its warehouse balance. Refuses to take stock below zero."""
    balance = await db.scalar(
        select(StockBalance).where(
            StockBalance.tenant_id == movement.tenant_id,
            StockBalance.warehouse_id == movement.warehouse_id,
            StockBalance.item_id == movement.item_id,
        )
    )
    if balance is None:
        balance = StockBalance(
            id=uuid.uuid4(),
            tenant_id=movement.tenant_id,
            site_id=movement.site_id,
            warehouse_id=movement.warehouse_id,
            item_id=movement.item_id,
            on_hand=ZERO,
        )
        db.add(balance)
    after = balance.on_hand + movement.quantity
    if after < 0:
        item = await db.get(Item, movement.item_id)
        unit = await db.get(UnitOfMeasure, item.base_unit_id)
        warehouse = await db.get(Warehouse, movement.warehouse_id)
        raise HTTPException(
            status_code=409,
            detail=tr(
                (
                    "Only {balance_on_hand} {unit_code} {item_code} in {warehouse_code}; "
                    "this would take it to {after}. Stock cannot go below zero."
                ),
                balance_on_hand=plain(balance.on_hand),
                unit_code=unit.code,
                item_code=item.code,
                warehouse_code=warehouse.code,
                after=plain(after),
            ),
        )
    balance.on_hand = after
    movement.status = "posted"
    movement.balance_after = after
    movement.posted_at = datetime.now(UTC)
    await db.flush()


async def site_stock(
    db: AsyncSession, tenant_id: uuid.UUID, site_ids: set[uuid.UUID]
) -> dict[tuple[uuid.UUID, uuid.UUID], Decimal]:
    """On-hand per (site, item), summed over the site's warehouses.

    Only items with a balance row appear: an item is stock-tracked at a site once something
    has been posted for it there (ADR-0010). Absent means "no stock figure", not zero.
    """
    pools: dict[tuple[uuid.UUID, uuid.UUID], Decimal] = defaultdict(lambda: ZERO)
    if not site_ids:
        return {}
    for balance in await db.scalars(
        select(StockBalance).where(
            StockBalance.tenant_id == tenant_id, StockBalance.site_id.in_(site_ids)
        )
    ):
        pools[(balance.site_id, balance.item_id)] += balance.on_hand
    return dict(pools)


async def take_stock(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    site_id: uuid.UUID,
    item_id: uuid.UUID,
    quantity: Decimal,
    movement_date: date,
    dispatch_id: uuid.UUID,
    reference: str,
    user_id: uuid.UUID,
    user_label: str,
) -> list[dict]:
    """Use up to `quantity` from the site's warehouses, fullest first. Returns what was used."""
    used = []
    need = quantity
    balances = await db.scalars(
        select(StockBalance)
        .join(Warehouse, Warehouse.id == StockBalance.warehouse_id)
        .where(
            StockBalance.tenant_id == tenant_id,
            StockBalance.site_id == site_id,
            StockBalance.item_id == item_id,
            StockBalance.on_hand > 0,
        )
        .order_by(StockBalance.on_hand.desc(), Warehouse.code)
    )
    for balance in list(balances):
        if need <= 0:
            break
        take = min(need, balance.on_hand)
        movement = StockMovement(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            site_id=site_id,
            warehouse_id=balance.warehouse_id,
            item_id=item_id,
            kind="dispatch",
            quantity=-take,
            status="pending_approval",
            movement_date=movement_date,
            reference=reference,
            dispatch_id=dispatch_id,
            created_by=user_id,
            created_by_label=user_label,
            created_at=datetime.now(UTC),
        )
        db.add(movement)
        await post_movement(db, movement)
        used.append(
            {"stock_movement_id": str(movement.id), "item_id": str(item_id), "used": plain(take)}
        )
        need -= take
    return used


async def put_back(
    db: AsyncSession,
    original: StockMovement,
    *,
    reason: str,
    movement_date: date,
    user_id: uuid.UUID,
    user_label: str,
) -> StockMovement:
    """Post the exact opposite of a movement (used when a dispatch is cancelled)."""
    reversal = StockMovement(
        id=uuid.uuid4(),
        tenant_id=original.tenant_id,
        site_id=original.site_id,
        warehouse_id=original.warehouse_id,
        item_id=original.item_id,
        kind="reversal",
        quantity=-original.quantity,
        status="pending_approval",
        movement_date=movement_date,
        reason=reason,
        reference=original.reference,
        reverses_id=original.id,
        dispatch_id=original.dispatch_id,
        created_by=user_id,
        created_by_label=user_label,
        created_at=datetime.now(UTC),
    )
    db.add(reversal)
    await post_movement(db, reversal)
    return reversal
