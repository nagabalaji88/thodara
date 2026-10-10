"""What each customer-order line depends on, and how much of it is still needed."""

import uuid
from collections import defaultdict
from decimal import ROUND_CEILING, Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.masterdata import Item, Supplier, UnitOfMeasure
from app.models.orders import OrderLineComponent, OrderLineOperation, SalesOrderLine
from app.models.outsourcing import BatchAllocation, OutsourcedBatch, SupplierUpdate
from app.schemas.orders import AllocationOut, ComponentOut, OperationOut

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


async def allocations_by_component(
    db: AsyncSession, component_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[AllocationOut]]:
    result: dict[uuid.UUID, list[AllocationOut]] = defaultdict(list)
    if not component_ids:
        return result
    rows = (
        await db.execute(
            select(BatchAllocation, OutsourcedBatch, Supplier, UnitOfMeasure)
            .join(OutsourcedBatch, OutsourcedBatch.id == BatchAllocation.batch_id)
            .join(Supplier, Supplier.id == OutsourcedBatch.supplier_id)
            .join(UnitOfMeasure, UnitOfMeasure.id == OutsourcedBatch.unit_id)
            .where(BatchAllocation.component_id.in_(component_ids))
            .order_by(OutsourcedBatch.number)
        )
    ).all()
    latest = await current_updates(db, [batch.id for _, batch, _, _ in rows])
    for allocation, batch, supplier, unit in rows:
        report = latest.get(batch.id)
        step = unit_step(unit)
        result[allocation.component_id].append(
            AllocationOut(
                id=allocation.id,
                batch_id=batch.id,
                batch_number=batch.number,
                batch_status=batch.status,
                supplier_name=supplier.name,
                quantity=allocation.quantity,
                batch_quantity=batch.quantity.quantize(step),
                expected_return_date=batch.expected_return_date,
                revised_return_date=report.revised_return_date if report else None,
                last_reported_at=report.reported_at if report else None,
                reported_completed=report.completed_qty.quantize(step) if report else None,
                reported_rejected=report.rejected_qty.quantize(step) if report else None,
                reported_pending=report.pending_qty.quantize(step) if report else None,
                blocker=report.blocker if report else None,
            )
        )
    return result


async def batch_updates(
    db: AsyncSession, batch_ids: list[uuid.UUID]
) -> tuple[list[SupplierUpdate], set[uuid.UUID]]:
    """All supplier updates for these batches, oldest first, and the ids later corrected."""
    if not batch_ids:
        return [], set()
    rows = list(
        await db.scalars(
            select(SupplierUpdate)
            .where(SupplierUpdate.batch_id.in_(batch_ids))
            .order_by(SupplierUpdate.reported_at, SupplierUpdate.recorded_at, SupplierUpdate.id)
        )
    )
    return rows, {r.corrects_id for r in rows if r.corrects_id}


async def current_updates(
    db: AsyncSession, batch_ids: list[uuid.UUID]
) -> dict[uuid.UUID, SupplierUpdate]:
    """The newest update per batch that has not been corrected."""
    rows, superseded = await batch_updates(db, batch_ids)
    current: dict[uuid.UUID, SupplierUpdate] = {}
    for row in rows:
        if row.id not in superseded:
            current[row.batch_id] = row
    return current


async def allocated_batches(db: AsyncSession, component_ids: list[uuid.UUID]) -> set[str]:
    """Numbers of batches allocated to any of these components."""
    if not component_ids:
        return set()
    rows = await db.scalars(
        select(OutsourcedBatch.number)
        .join(BatchAllocation, BatchAllocation.batch_id == OutsourcedBatch.id)
        .where(BatchAllocation.component_id.in_(component_ids))
    )
    return set(rows)


async def release_allocations(db: AsyncSession, line_ids: list[uuid.UUID]) -> list[dict[str, str]]:
    """Free the batch quantity earmarked for lines that are no longer open."""
    if not line_ids:
        return []
    rows = (
        await db.execute(
            select(BatchAllocation, OutsourcedBatch.number, OrderLineComponent.line_id)
            .join(OutsourcedBatch, OutsourcedBatch.id == BatchAllocation.batch_id)
            .join(OrderLineComponent, OrderLineComponent.id == BatchAllocation.component_id)
            .where(OrderLineComponent.line_id.in_(line_ids))
            .order_by(OutsourcedBatch.number)
        )
    ).all()
    released = []
    for allocation, number, line_id in rows:
        released.append(
            {
                "batch": number,
                "line_id": str(line_id),
                "quantity": format(allocation.quantity.normalize(), "f"),
            }
        )
        await db.delete(allocation)
    return released


async def check_allocations_fit(
    db: AsyncSession, line: SalesOrderLine, ordered_qty: Decimal
) -> None:
    """Refuse a quantity cut that would leave a component with more allocated than needed."""
    rows = (
        await db.execute(
            select(OrderLineComponent, UnitOfMeasure, func.sum(BatchAllocation.quantity))
            .join(UnitOfMeasure, UnitOfMeasure.id == OrderLineComponent.unit_id)
            .join(BatchAllocation, BatchAllocation.component_id == OrderLineComponent.id)
            .where(OrderLineComponent.line_id == line.id)
            .group_by(OrderLineComponent.id, UnitOfMeasure.id)
        )
    ).all()
    open_qty = ordered_qty - line.cancelled_qty - line.short_closed_qty
    for component, unit, allocated in rows:
        needed = (component.qty_per_unit * open_qty).quantize(
            unit_step(unit), rounding=ROUND_CEILING
        )
        if allocated > needed:
            raise HTTPException(
                status_code=409,
                detail=f"{format(allocated.normalize(), 'f')} {unit.code} is allocated from "
                "outsourced batches; reduce those allocations before cutting the quantity",
            )
