"""Load the facts the delivery-risk calculation needs, scoped to a tenant and its sites."""

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.organization import load_work_calendar
from app.models.identity import Site
from app.models.masterdata import Customer, Item, Supplier, UnitOfMeasure
from app.models.orders import (
    OrderLineComponent,
    OrderLineOperation,
    SalesOrder,
    SalesOrderLine,
)
from app.models.organization import DEFAULT_STALE_HOURS, FulfillmentSettings
from app.models.outsourcing import BatchAllocation, OutsourcedBatch
from app.services.fulfillment import current_updates, line_remaining, receipt_totals, required_qty
from app.services.risk import (
    ZERO,
    AllocationFacts,
    BatchFacts,
    ComponentFacts,
    LineFacts,
    LineRisk,
    assess_line,
    share_batches,
)

LAST_DAY = date.max


async def stale_hours(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    hours = await db.scalar(
        select(FulfillmentSettings.supplier_update_stale_hours).where(
            FulfillmentSettings.tenant_id == tenant_id
        )
    )
    return hours or DEFAULT_STALE_HOURS


async def assess_lines(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    site_ids: frozenset[uuid.UUID] | None,
    order_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> list[LineRisk]:
    """Risk for every open line of a confirmed order in scope (optionally one order)."""
    now = now or datetime.now(UTC)
    query = (
        select(SalesOrderLine, SalesOrder, Customer.name, Item.code, UnitOfMeasure.code)
        .join(SalesOrder, SalesOrder.id == SalesOrderLine.order_id)
        .join(Customer, Customer.id == SalesOrder.customer_id)
        .join(Item, Item.id == SalesOrderLine.item_id)
        .join(UnitOfMeasure, UnitOfMeasure.id == SalesOrderLine.unit_id)
        .where(
            SalesOrder.tenant_id == tenant_id,
            SalesOrder.status == "confirmed",
            SalesOrderLine.status == "open",
        )
        .order_by(SalesOrderLine.promised_date, SalesOrder.number, SalesOrderLine.line_no)
    )
    if site_ids is not None:
        query = query.where(SalesOrder.site_id.in_(site_ids))
    if order_id is not None:
        query = query.where(SalesOrder.id == order_id)
    rows = (await db.execute(query)).all()
    if not rows:
        return []
    line_ids = [line.id for line, *_ in rows]

    components: dict[uuid.UUID, list[tuple]] = defaultdict(list)
    for component, item_code, unit in await db.execute(
        select(OrderLineComponent, Item.code, UnitOfMeasure)
        .join(Item, Item.id == OrderLineComponent.item_id)
        .join(UnitOfMeasure, UnitOfMeasure.id == OrderLineComponent.unit_id)
        .where(OrderLineComponent.line_id.in_(line_ids))
        .order_by(OrderLineComponent.position)
    ):
        components[component.line_id].append((component, item_code, unit))
    operations = {
        line_id: (int(total), int(count))
        for line_id, total, count in await db.execute(
            select(
                OrderLineOperation.line_id,
                func.sum(OrderLineOperation.duration_minutes),
                func.count(),
            )
            .where(OrderLineOperation.line_id.in_(line_ids))
            .group_by(OrderLineOperation.line_id)
        )
    }

    component_ids = [c.id for group in components.values() for c, _, _ in group]
    batch_ids = (
        list(
            await db.scalars(
                select(BatchAllocation.batch_id)
                .where(BatchAllocation.component_id.in_(component_ids))
                .distinct()
            )
        )
        if component_ids
        else []
    )

    # Every allocation on those batches, including other orders' lines, because they compete
    # for the same material in promised-date order.
    allocations: list[AllocationFacts] = []
    if batch_ids:
        for allocation, line_no, promised, number in await db.execute(
            select(
                BatchAllocation,
                SalesOrderLine.line_no,
                SalesOrderLine.promised_date,
                SalesOrder.number,
            )
            .join(OrderLineComponent, OrderLineComponent.id == BatchAllocation.component_id)
            .join(SalesOrderLine, SalesOrderLine.id == OrderLineComponent.line_id)
            .join(SalesOrder, SalesOrder.id == SalesOrderLine.order_id)
            .where(BatchAllocation.batch_id.in_(batch_ids))
        ):
            allocations.append(
                AllocationFacts(
                    id=allocation.id,
                    batch_id=allocation.batch_id,
                    component_id=allocation.component_id,
                    quantity=allocation.quantity,
                    priority=(promised or LAST_DAY, number, line_no),
                    order_number=number,
                    line_no=line_no,
                )
            )

    batches: dict[uuid.UUID, BatchFacts] = {}
    if batch_ids:
        latest = await current_updates(db, batch_ids)
        totals = await receipt_totals(db, batch_ids)
        for batch, supplier_name in await db.execute(
            select(OutsourcedBatch, Supplier.name)
            .join(Supplier, Supplier.id == OutsourcedBatch.supplier_id)
            .where(OutsourcedBatch.id.in_(batch_ids))
        ):
            report = latest.get(batch.id)
            received = totals.get(batch.id)
            reported_at = report.reported_at if report else None
            if reported_at is not None and reported_at.tzinfo is None:
                reported_at = reported_at.replace(tzinfo=UTC)  # SQLite returns naive UTC
            batches[batch.id] = BatchFacts(
                id=batch.id,
                number=batch.number,
                supplier_name=supplier_name,
                status=batch.status,
                quantity=batch.quantity,
                expected_return_date=batch.expected_return_date,
                sent_date=batch.sent_date,
                received=received.received if received else ZERO,
                accepted=received.accepted if received else ZERO,
                awaiting=received.awaiting if received else ZERO,
                held=received.held if received else ZERO,
                reported_completed=report.completed_qty if report else None,
                reported_rejected=report.rejected_qty if report else None,
                reported_at=reported_at,
                revised_return_date=report.revised_return_date if report else None,
                blocker=report.blocker if report else None,
            )
    shares = share_batches(batches, allocations)
    by_component: dict[uuid.UUID, list[AllocationFacts]] = defaultdict(list)
    for allocation in allocations:
        by_component[allocation.component_id].append(allocation)

    calendars = {}
    for site_id in {order.site_id for _, order, *_ in rows}:
        site = await db.get(Site, site_id)
        calendars[site_id] = await load_work_calendar(db, site)
    stale_after = timedelta(hours=await stale_hours(db, tenant_id))

    results = []
    for line, order, customer_name, item_code, unit_code in rows:
        facts = LineFacts(
            line_id=line.id,
            order_id=order.id,
            order_number=order.number,
            customer_name=customer_name,
            site_id=order.site_id,
            line_no=line.line_no,
            item_code=item_code,
            unit_code=unit_code,
            remaining=line_remaining(line),
            promised_date=line.promised_date,
            components=[
                ComponentFacts(
                    id=component.id,
                    item_code=component_item,
                    unit_code=unit.code,
                    required=required_qty(component, line, unit),
                    outsourced_operation=component.outsourced_operation,
                    allocations=by_component[component.id],
                )
                for component, component_item, unit in components[line.id]
            ],
            operation_minutes=operations.get(line.id, (0, 0))[0],
            operation_count=operations.get(line.id, (0, 0))[1],
        )
        results.append(
            assess_line(facts, batches, shares, calendars[order.site_id], now, stale_after)
        )
    return results
