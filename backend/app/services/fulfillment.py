"""What each customer-order line depends on, and how much of it is still needed."""

import uuid
from collections import defaultdict
from decimal import ROUND_CEILING, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.masterdata import Item, UnitOfMeasure
from app.models.orders import OrderLineComponent, OrderLineOperation, SalesOrderLine
from app.schemas.orders import ComponentOut, OperationOut

ZERO = Decimal(0)


def unit_step(unit: UnitOfMeasure) -> Decimal:
    return Decimal(1).scaleb(-unit.decimal_places)


def line_remaining(line: SalesOrderLine) -> Decimal:
    # Shipments arrive with dispatch (F8); until then nothing has shipped.
    if line.status != "open":
        return ZERO
    return line.ordered_qty - line.cancelled_qty - line.short_closed_qty


def required_qty(
    component: OrderLineComponent, line: SalesOrderLine, unit: UnitOfMeasure
) -> Decimal:
    """Quantity per unit x remaining line quantity, rounded up to the component unit."""
    return (component.qty_per_unit * line_remaining(line)).quantize(
        unit_step(unit), rounding=ROUND_CEILING
    )


async def load_dependencies(
    db: AsyncSession, lines: list[SalesOrderLine]
) -> tuple[dict[uuid.UUID, list[ComponentOut]], dict[uuid.UUID, list[OperationOut]]]:
    components: dict[uuid.UUID, list[ComponentOut]] = defaultdict(list)
    operations: dict[uuid.UUID, list[OperationOut]] = defaultdict(list)
    if not lines:
        return components, operations
    by_id = {line.id: line for line in lines}
    rows = (
        await db.scalars(
            select(OrderLineComponent)
            .where(OrderLineComponent.line_id.in_(by_id))
            .order_by(OrderLineComponent.line_id, OrderLineComponent.position)
        )
    ).all()
    if rows:
        items = {
            i.id: i
            for i in await db.scalars(select(Item).where(Item.id.in_({r.item_id for r in rows})))
        }
        units = {
            u.id: u
            for u in await db.scalars(
                select(UnitOfMeasure).where(UnitOfMeasure.id.in_({r.unit_id for r in rows}))
            )
        }
        allocations = await allocations_by_component(db, [r.id for r in rows])
        for row in rows:
            unit = units[row.unit_id]
            allocated = sum((a.quantity for a in allocations[row.id]), ZERO)
            components[row.line_id].append(
                ComponentOut(
                    id=row.id,
                    item_id=row.item_id,
                    item_code=items[row.item_id].code,
                    item_name=items[row.item_id].name,
                    unit_code=unit.code,
                    qty_per_unit=row.qty_per_unit.normalize(),
                    required_qty=required_qty(row, by_id[row.line_id], unit),
                    allocated_qty=allocated.quantize(unit_step(unit)),
                    outsourced_operation=row.outsourced_operation,
                    allocations=[
                        a.model_copy(update={"quantity": a.quantity.quantize(unit_step(unit))})
                        for a in allocations[row.id]
                    ],
                )
            )
    for op in await db.scalars(
        select(OrderLineOperation)
        .where(OrderLineOperation.line_id.in_(by_id))
        .order_by(OrderLineOperation.line_id, OrderLineOperation.sequence)
    ):
        operations[op.line_id].append(
            OperationOut(
                id=op.id,
                sequence=op.sequence,
                name=op.name,
                kind=op.kind,
                duration_minutes=op.duration_minutes,
            )
        )
    return components, operations


async def allocations_by_component(db: AsyncSession, component_ids: list[uuid.UUID]):
    # Outsourced batches (F3) fill this in.
    return defaultdict(list)


async def allocated_batches(db: AsyncSession, component_ids: list[uuid.UUID]) -> set[str]:
    """Numbers of batches allocated to any of these components (F3 fills this in)."""
    return set()
