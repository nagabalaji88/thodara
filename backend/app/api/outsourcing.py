"""Outsourced batches and their links to customer-order lines (slice F3)."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AuthContext, require_csrf, require_permission
from app.api.masterdata import STALE, audit, commit_or_conflict, json_safe
from app.api.orders import check_precision, plain, require_version, to_unit
from app.core.audit import actor_label
from app.db.session import get_db
from app.models.identity import Site
from app.models.masterdata import Customer, Item, Supplier, UnitOfMeasure
from app.models.orders import OrderLineComponent, SalesOrder, SalesOrderLine
from app.models.outsourcing import (
    BatchAllocation,
    BatchMovement,
    BatchReceipt,
    OutsourcedBatch,
    QualityDecision,
    SupplierUpdate,
)
from app.schemas.outsourcing import (
    AllocationAdd,
    AllocationIn,
    BatchAllocationOut,
    BatchCreate,
    BatchOut,
    BatchPage,
    BatchReasoned,
    BatchSend,
    BatchSummary,
    BatchUpdate,
    Candidate,
    DecisionOut,
    HoldReleaseIn,
    InspectionIn,
    MovementOut,
    QuantityPicture,
    ReceiptIn,
    ReceiptOut,
    SupplierUpdateIn,
    SupplierUpdateOut,
)
from app.services.fulfillment import (
    ZERO,
    ReceiptTotals,
    batch_updates,
    current_updates,
    receipt_totals,
    release,
    required_qty,
)
from app.services.numbering import allocate_number

router = APIRouter(prefix="/outsourcing", tags=["outsourced batches"])
READ = require_permission("outsourcing:read")
MANAGE = require_permission("outsourcing:manage")
CSRF = [Depends(require_csrf)]
ACTIVE = ("planned", "at_supplier")


# Loading ----------------------------------------------------------------------


async def get_batch(db: AsyncSession, context: AuthContext, batch_id: uuid.UUID) -> OutsourcedBatch:
    batch = await db.scalar(
        select(OutsourcedBatch).where(
            OutsourcedBatch.tenant_id == context.tenant.id, OutsourcedBatch.id == batch_id
        )
    )
    if batch is None or not context.can_access_site(batch.site_id):
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch


async def batch_allocated(db: AsyncSession, batch_id: uuid.UUID) -> Decimal:
    total = await db.scalar(
        select(func.sum(BatchAllocation.quantity)).where(BatchAllocation.batch_id == batch_id)
    )
    return total or ZERO


async def component_allocated(db: AsyncSession, component_id: uuid.UUID) -> Decimal:
    total = await db.scalar(
        select(func.sum(BatchAllocation.quantity - BatchAllocation.consumed_qty)).where(
            BatchAllocation.component_id == component_id
        )
    )
    return total or ZERO


async def allocation_rows(db: AsyncSession, batch_ids: list[uuid.UUID]):
    return (
        await db.execute(
            select(
                BatchAllocation,
                OrderLineComponent,
                SalesOrderLine,
                SalesOrder,
                Customer.name,
                Item.code,
                UnitOfMeasure,
            )
            .join(OrderLineComponent, OrderLineComponent.id == BatchAllocation.component_id)
            .join(SalesOrderLine, SalesOrderLine.id == OrderLineComponent.line_id)
            .join(SalesOrder, SalesOrder.id == SalesOrderLine.order_id)
            .join(Customer, Customer.id == SalesOrder.customer_id)
            .join(Item, Item.id == SalesOrderLine.item_id)
            .join(UnitOfMeasure, UnitOfMeasure.id == OrderLineComponent.unit_id)
            .where(BatchAllocation.batch_id.in_(batch_ids))
            .order_by(SalesOrderLine.promised_date, SalesOrder.number, SalesOrderLine.line_no)
        )
    ).all()


async def batch_out(db: AsyncSession, batch: OutsourcedBatch) -> BatchOut:
    site = await db.get(Site, batch.site_id)
    supplier = await db.get(Supplier, batch.supplier_id)
    item = await db.get(Item, batch.item_id)
    unit = await db.get(UnitOfMeasure, batch.unit_id)
    allocations = [
        BatchAllocationOut(
            id=allocation.id,
            component_id=component.id,
            quantity=to_unit(allocation.quantity, unit),
            consumed_qty=to_unit(allocation.consumed_qty, unit),
            order_id=order.id,
            order_number=order.number,
            order_status=order.status,
            customer_name=customer_name,
            line_no=line.line_no,
            line_item_code=line_item_code,
            line_status=line.status,
            promised_date=line.promised_date,
            component_required_qty=required_qty(component, line, component_unit),
        )
        for (
            allocation,
            component,
            line,
            order,
            customer_name,
            line_item_code,
            component_unit,
        ) in await allocation_rows(db, [batch.id])
    ]
    movements = [
        MovementOut(
            kind=m.kind,
            quantity=to_unit(m.quantity, unit),
            movement_date=m.movement_date,
            document_reference=m.document_reference,
            note=m.note,
            recorded_by_label=m.recorded_by_label,
            recorded_at=m.recorded_at,
        )
        for m in await db.scalars(
            select(BatchMovement)
            .where(BatchMovement.batch_id == batch.id)
            .order_by(BatchMovement.recorded_at, BatchMovement.id)
        )
    ]
    sent = sum((m.quantity for m in movements if m.kind == "sent_to_supplier"), ZERO)
    receipts, totals = await receipts_out(db, batch, unit)
    rows, superseded = await batch_updates(db, [batch.id])
    updates = [update_out(row, unit, superseded) for row in rows]
    current = [u for u in updates if not u.superseded]
    latest = current[-1] if current else None
    return BatchOut(
        id=batch.id,
        number=batch.number,
        site_id=batch.site_id,
        site_name=site.name,
        supplier_id=supplier.id,
        supplier_code=supplier.code,
        supplier_name=supplier.name,
        item_id=item.id,
        item_code=item.code,
        item_name=item.name,
        unit_code=unit.code,
        operation=batch.operation,
        quantity=to_unit(batch.quantity, unit),
        allocated_qty=to_unit(sum((a.quantity for a in allocations), ZERO), unit),
        expected_return_date=batch.expected_return_date,
        status=batch.status,
        status_reason=batch.status_reason,
        sent_date=batch.sent_date,
        challan_reference=batch.challan_reference,
        notes=batch.notes,
        version=batch.version,
        created_at=batch.created_at,
        updated_at=batch.updated_at,
        allocations=allocations,
        movements=movements,
        quantities=QuantityPicture(
            sent=to_unit(sent, unit),
            reported_completed=latest.completed_qty if latest else None,
            reported_rejected=latest.rejected_qty if latest else None,
            reported_pending=latest.pending_qty if latest else None,
            received=to_unit(totals.received, unit),
            awaiting_inspection=to_unit(totals.awaiting, unit),
            accepted=to_unit(totals.accepted, unit),
            held=to_unit(totals.held, unit),
            rejected_at_inspection=to_unit(totals.rejected, unit),
            rework=to_unit(totals.rework, unit),
            still_at_supplier=to_unit(sent - totals.received, unit),
        ),
        latest_update=latest,
        updates=list(reversed(updates)),
        receipts=receipts,
    )


async def receipts_out(
    db: AsyncSession, batch: OutsourcedBatch, unit: UnitOfMeasure
) -> tuple[list[ReceiptOut], ReceiptTotals]:
    rows = list(
        await db.scalars(
            select(BatchReceipt)
            .where(BatchReceipt.batch_id == batch.id)
            .order_by(BatchReceipt.receipt_date, BatchReceipt.recorded_at, BatchReceipt.id)
        )
    )
    decisions: dict[uuid.UUID, list[DecisionOut]] = {r.id: [] for r in rows}
    if rows:
        for d in await db.scalars(
            select(QualityDecision)
            .where(QualityDecision.receipt_id.in_(decisions))
            .order_by(QualityDecision.decided_at, QualityDecision.id)
        ):
            decisions[d.receipt_id].append(
                DecisionOut(
                    kind=d.kind,
                    accepted_qty=to_unit(d.accepted_qty, unit),
                    rejected_qty=to_unit(d.rejected_qty, unit),
                    held_qty=to_unit(d.held_qty, unit),
                    rework_qty=to_unit(d.rework_qty, unit),
                    note=d.note,
                    decided_by_label=d.decided_by_label,
                    decided_at=d.decided_at,
                )
            )
    totals = ReceiptTotals()
    for row in rows:
        totals.add(row)
    return [
        ReceiptOut(
            id=r.id,
            received_qty=to_unit(r.received_qty, unit),
            receipt_date=r.receipt_date,
            document_reference=r.document_reference,
            note=r.note,
            status=r.status,
            accepted_qty=to_unit(r.accepted_qty, unit),
            rejected_qty=to_unit(r.rejected_qty, unit),
            held_qty=to_unit(r.held_qty, unit),
            rework_qty=to_unit(r.rework_qty, unit),
            received_by_label=r.received_by_label,
            recorded_at=r.recorded_at,
            version=r.version,
            decisions=decisions[r.id],
        )
        for r in rows
    ], totals


def update_out(row: SupplierUpdate, unit: UnitOfMeasure, superseded: set[uuid.UUID]):
    return SupplierUpdateOut(
        id=row.id,
        completed_qty=to_unit(row.completed_qty, unit),
        rejected_qty=to_unit(row.rejected_qty, unit),
        pending_qty=to_unit(row.pending_qty, unit),
        revised_return_date=row.revised_return_date,
        blocker=row.blocker,
        source=row.source,
        contact_method=row.contact_method,
        contact_name=row.contact_name,
        reported_at=row.reported_at,
        confirmation_state=row.confirmation_state,
        corrects_id=row.corrects_id,
        correction_reason=row.correction_reason,
        superseded=row.id in superseded,
        recorded_by_label=row.recorded_by_label,
        recorded_at=row.recorded_at,
    )


def touch(batch: OutsourcedBatch, context: AuthContext) -> None:
    batch.updated_by = context.user.id
    batch.updated_at = datetime.now(UTC)


def batch_snapshot(batch: OutsourcedBatch) -> dict[str, Any]:
    return {
        "operation": batch.operation,
        "quantity": plain(batch.quantity),
        "expected_return_date": batch.expected_return_date.isoformat(),
        "notes": batch.notes,
    }


# Allocation rules ---------------------------------------------------------------


async def allocate(
    db: AsyncSession,
    context: AuthContext,
    batch: OutsourcedBatch,
    unit: UnitOfMeasure,
    entry: AllocationIn,
    already_in_batch: Decimal,
) -> dict[str, str]:
    """Validate and add one allocation. Returns its audit summary."""
    row = (
        await db.execute(
            select(OrderLineComponent, SalesOrderLine, SalesOrder, UnitOfMeasure)
            .join(SalesOrderLine, SalesOrderLine.id == OrderLineComponent.line_id)
            .join(SalesOrder, SalesOrder.id == SalesOrderLine.order_id)
            .join(UnitOfMeasure, UnitOfMeasure.id == OrderLineComponent.unit_id)
            .where(
                OrderLineComponent.tenant_id == context.tenant.id,
                OrderLineComponent.id == entry.component_id,
            )
        )
    ).first()
    if row is None or not context.can_access_site(row[2].site_id):
        raise HTTPException(status_code=422, detail="Choose an order-line component you can access")
    component, line, order, component_unit = row
    if order.status != "confirmed" or line.status != "open":
        raise HTTPException(
            status_code=409,
            detail=f"{order.number} line {line.line_no} is not an open line of a confirmed order",
        )
    if order.site_id != batch.site_id:
        raise HTTPException(
            status_code=422, detail=f"{order.number} is fulfilled from a different site"
        )
    if component.item_id != batch.item_id:
        raise HTTPException(
            status_code=422,
            detail=f"{order.number} line {line.line_no} does not need this batch's item",
        )
    check_precision(entry.quantity, unit)
    existing = await db.scalar(
        select(BatchAllocation.id).where(
            BatchAllocation.batch_id == batch.id, BatchAllocation.component_id == component.id
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"{order.number} line {line.line_no} is already allocated from this batch",
        )
    free = batch.quantity - already_in_batch
    if entry.quantity > free:
        raise HTTPException(
            status_code=422,
            detail=f"Only {plain(free)} {unit.code} of {batch.number} is not yet allocated",
        )
    open_need = required_qty(component, line, component_unit) - await component_allocated(
        db, component.id
    )
    if entry.quantity > open_need:
        raise HTTPException(
            status_code=422,
            detail=f"{order.number} line {line.line_no} needs only {plain(max(open_need, ZERO))} "
            f"{unit.code} more",
        )
    db.add(
        BatchAllocation(
            id=uuid.uuid4(),
            tenant_id=context.tenant.id,
            batch_id=batch.id,
            component_id=component.id,
            quantity=entry.quantity,
            created_by=context.user.id,
        )
    )
    await db.flush()
    return {
        "order": order.number,
        "line_no": str(line.line_no),
        "component_id": str(component.id),
        "quantity": plain(entry.quantity),
    }


# Endpoints --------------------------------------------------------------------


@router.get("/batches", response_model=BatchPage)
async def list_batches(
    q: str | None = Query(default=None, max_length=80),
    status: str | None = Query(default=None, pattern="^(planned|at_supplier|closed|cancelled)$"),
    supplier_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100_000),
    context: AuthContext = Depends(READ),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(OutsourcedBatch, Supplier, Item, UnitOfMeasure, Site)
        .join(Supplier, Supplier.id == OutsourcedBatch.supplier_id)
        .join(Item, Item.id == OutsourcedBatch.item_id)
        .join(UnitOfMeasure, UnitOfMeasure.id == OutsourcedBatch.unit_id)
        .join(Site, Site.id == OutsourcedBatch.site_id)
        .where(OutsourcedBatch.tenant_id == context.tenant.id)
    )
    if context.site_ids is not None:
        query = query.where(OutsourcedBatch.site_id.in_(context.site_ids))
    if status:
        query = query.where(OutsourcedBatch.status == status)
    if supplier_id:
        query = query.where(OutsourcedBatch.supplier_id == supplier_id)
    if q and q.strip():
        pattern = (
            "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        )
        query = query.where(
            or_(
                *(
                    column.ilike(pattern, escape="\\")
                    for column in (
                        OutsourcedBatch.number,
                        OutsourcedBatch.operation,
                        OutsourcedBatch.challan_reference,
                        Supplier.code,
                        Supplier.name,
                        Item.code,
                        Item.name,
                    )
                )
            )
        )
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (
        await db.execute(
            query.order_by(OutsourcedBatch.expected_return_date, OutsourcedBatch.number)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    stats: dict[uuid.UUID, tuple[Decimal, int]] = {}
    if rows:
        stat_rows = await db.execute(
            select(
                BatchAllocation.batch_id,
                func.sum(BatchAllocation.quantity),
                func.count(func.distinct(SalesOrderLine.order_id)),
            )
            .join(OrderLineComponent, OrderLineComponent.id == BatchAllocation.component_id)
            .join(SalesOrderLine, SalesOrderLine.id == OrderLineComponent.line_id)
            .where(BatchAllocation.batch_id.in_([r[0].id for r in rows]))
            .group_by(BatchAllocation.batch_id)
        )
        stats = {r[0]: (r[1], r[2]) for r in stat_rows}
    latest = await current_updates(db, [r[0].id for r in rows])
    receipts = await receipt_totals(db, [r[0].id for r in rows])
    return BatchPage(
        items=[
            BatchSummary(
                id=batch.id,
                number=batch.number,
                site_name=site.name,
                supplier_name=supplier.name,
                item_code=item.code,
                item_name=item.name,
                unit_code=unit.code,
                operation=batch.operation,
                quantity=to_unit(batch.quantity, unit),
                allocated_qty=to_unit(stats.get(batch.id, (ZERO, 0))[0], unit),
                order_count=stats.get(batch.id, (ZERO, 0))[1],
                expected_return_date=batch.expected_return_date,
                sent_date=batch.sent_date,
                status=batch.status,
                **report_fields(latest.get(batch.id), unit),
                **receipt_fields(receipts.get(batch.id), unit),
            )
            for batch, supplier, item, unit, site in rows
        ],
        total=total,
    )


def report_fields(report: SupplierUpdate | None, unit: UnitOfMeasure) -> dict[str, Any]:
    if report is None:
        return {}
    return {
        "last_reported_at": report.reported_at,
        "reported_completed": to_unit(report.completed_qty, unit),
        "reported_rejected": to_unit(report.rejected_qty, unit),
        "reported_pending": to_unit(report.pending_qty, unit),
        "revised_return_date": report.revised_return_date,
        "blocker": report.blocker,
    }


def receipt_fields(totals: ReceiptTotals | None, unit: UnitOfMeasure) -> dict[str, Any]:
    if totals is None:
        return {}
    return {
        "received_qty": to_unit(totals.received, unit),
        "accepted_qty": to_unit(totals.accepted, unit),
        "held_qty": to_unit(totals.held, unit),
    }


@router.get("/candidates", response_model=list[Candidate])
async def allocation_candidates(
    item_id: uuid.UUID,
    site_id: uuid.UUID,
    context: AuthContext = Depends(READ),
    db: AsyncSession = Depends(get_db),
):
    """Open order-line needs for this item at this site that are not yet covered by batches."""
    if not context.can_access_site(site_id):
        return []
    rows = (
        await db.execute(
            select(OrderLineComponent, SalesOrderLine, SalesOrder, Customer.name, Item.code)
            .join(SalesOrderLine, SalesOrderLine.id == OrderLineComponent.line_id)
            .join(SalesOrder, SalesOrder.id == SalesOrderLine.order_id)
            .join(Customer, Customer.id == SalesOrder.customer_id)
            .join(Item, Item.id == SalesOrderLine.item_id)
            .where(
                OrderLineComponent.tenant_id == context.tenant.id,
                OrderLineComponent.item_id == item_id,
                SalesOrder.site_id == site_id,
                SalesOrder.status == "confirmed",
                SalesOrderLine.status == "open",
            )
            .order_by(SalesOrderLine.promised_date, SalesOrder.number, SalesOrderLine.line_no)
        )
    ).all()
    candidates = []
    for component, line, order, customer_name, line_item_code in rows:
        unit = await db.get(UnitOfMeasure, component.unit_id)
        needed = required_qty(component, line, unit)
        allocated = await component_allocated(db, component.id)
        if needed - allocated <= 0:
            continue
        candidates.append(
            Candidate(
                component_id=component.id,
                order_id=order.id,
                order_number=order.number,
                customer_name=customer_name,
                line_no=line.line_no,
                line_item_code=line_item_code,
                promised_date=line.promised_date,
                outsourced_operation=component.outsourced_operation,
                required_qty=needed,
                allocated_qty=to_unit(allocated, unit),
                open_qty=to_unit(needed - allocated, unit),
            )
        )
    return candidates


@router.post("/batches", response_model=BatchOut, status_code=201, dependencies=CSRF)
async def create_batch(
    payload: BatchCreate,
    request: Request,
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    site = await db.scalar(
        select(Site).where(Site.tenant_id == context.tenant.id, Site.id == payload.site_id)
    )
    if site is None or not context.can_access_site(site.id) or site.status != "active":
        raise HTTPException(status_code=422, detail="Choose an active site you can access")
    supplier = await db.scalar(
        select(Supplier).where(
            Supplier.tenant_id == context.tenant.id, Supplier.id == payload.supplier_id
        )
    )
    if supplier is None or supplier.status != "active" or not supplier.provides_job_work:
        raise HTTPException(status_code=422, detail="Choose an active job-work supplier")
    item = await db.scalar(
        select(Item).where(Item.tenant_id == context.tenant.id, Item.id == payload.item_id)
    )
    if item is None or item.status != "active":
        raise HTTPException(status_code=422, detail="Choose an active item")
    unit = await db.get(UnitOfMeasure, item.base_unit_id)
    check_precision(payload.quantity, unit)
    component_ids = [a.component_id for a in payload.allocations]
    if len(set(component_ids)) != len(component_ids):
        raise HTTPException(status_code=422, detail="Allocate to each order line once")
    batch = OutsourcedBatch(
        id=uuid.uuid4(),
        tenant_id=context.tenant.id,
        site_id=site.id,
        number=await allocate_number(db, context.tenant.id, "outsourced_batch"),
        supplier_id=supplier.id,
        item_id=item.id,
        unit_id=unit.id,
        operation=payload.operation,
        quantity=payload.quantity,
        expected_return_date=payload.expected_return_date,
        notes=payload.notes,
        created_by=context.user.id,
        updated_by=context.user.id,
    )
    db.add(batch)
    await db.flush()
    allocated = ZERO
    summaries = []
    for entry in payload.allocations:
        summaries.append(await allocate(db, context, batch, unit, entry, allocated))
        allocated += entry.quantity
    audit(
        db,
        context,
        request,
        "outsourcing.batch_created",
        {
            "batch_id": str(batch.id),
            "number": batch.number,
            "supplier": supplier.code,
            "item": item.code,
            **batch_snapshot(batch),
            "allocations": summaries,
        },
    )
    await commit_or_conflict(db, "This batch could not be saved; reload and try again")
    return await batch_out(db, batch)


@router.get("/batches/{batch_id}", response_model=BatchOut)
async def read_batch(
    batch_id: uuid.UUID,
    context: AuthContext = Depends(READ),
    db: AsyncSession = Depends(get_db),
):
    return await batch_out(db, await get_batch(db, context, batch_id))


@router.patch("/batches/{batch_id}", response_model=BatchOut, dependencies=CSRF)
async def update_batch(
    batch_id: uuid.UUID,
    payload: BatchUpdate,
    request: Request,
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    batch = await get_batch(db, context, batch_id)
    require_version(batch.version, payload.version)
    fields = payload.model_fields_set - {"version"}
    if batch.status not in ACTIVE:
        raise HTTPException(status_code=409, detail=f"A {batch.status} batch cannot be edited")
    planned_only = fields & {"operation", "quantity", "expected_return_date"}
    if planned_only and batch.status != "planned":
        raise HTTPException(
            status_code=409,
            detail="Once a batch is at the supplier, its quantity, operation and return date "
            "change only through supplier updates",
        )
    for field in planned_only:
        if getattr(payload, field) is None:
            raise HTTPException(status_code=422, detail=f"{field} cannot be empty")
    if "quantity" in fields:
        unit = await db.get(UnitOfMeasure, batch.unit_id)
        check_precision(payload.quantity, unit)
        allocated = await batch_allocated(db, batch.id)
        if payload.quantity < allocated:
            raise HTTPException(
                status_code=409,
                detail=f"{plain(allocated)} {unit.code} is allocated to orders; "
                "reduce the allocations first",
            )
    before = batch_snapshot(batch)
    for field in fields:
        setattr(batch, field, getattr(payload, field))
    after = batch_snapshot(batch)
    if before != after:
        touch(batch, context)
        audit(
            db,
            context,
            request,
            "outsourcing.batch_updated",
            {"batch_id": str(batch.id), "number": batch.number, "before": before, "after": after},
        )
    await commit_or_conflict(db, STALE)
    return await batch_out(db, batch)


@router.post("/batches/{batch_id}/send", response_model=BatchOut, dependencies=CSRF)
async def send_batch(
    batch_id: uuid.UUID,
    payload: BatchSend,
    request: Request,
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    batch = await get_batch(db, context, batch_id)
    require_version(batch.version, payload.version)
    if batch.status != "planned":
        raise HTTPException(status_code=409, detail="Only a planned batch can be sent")
    site = await db.get(Site, batch.site_id)
    today = datetime.now(UTC).astimezone(ZoneInfo(site.time_zone)).date()
    if payload.sent_date > today:
        raise HTTPException(status_code=422, detail="The sent date cannot be in the future")
    batch.status = "at_supplier"
    batch.sent_date = payload.sent_date
    batch.challan_reference = payload.challan_reference
    touch(batch, context)
    db.add(
        BatchMovement(
            id=uuid.uuid4(),
            tenant_id=batch.tenant_id,
            batch_id=batch.id,
            kind="sent_to_supplier",
            quantity=batch.quantity,
            movement_date=payload.sent_date,
            document_reference=payload.challan_reference,
            recorded_by=context.user.id,
            recorded_by_label=actor_label(context.user),
            recorded_at=datetime.now(UTC),
        )
    )
    audit(
        db,
        context,
        request,
        "outsourcing.batch_sent",
        {
            "batch_id": str(batch.id),
            "number": batch.number,
            "quantity": plain(batch.quantity),
            "sent_date": payload.sent_date.isoformat(),
            "challan_reference": payload.challan_reference,
        },
    )
    await commit_or_conflict(db, STALE)
    return await batch_out(db, batch)


async def finish(
    db: AsyncSession,
    context: AuthContext,
    request: Request,
    batch: OutsourcedBatch,
    status: str,
    reason: str,
) -> BatchOut:
    released = []
    for allocation in await db.scalars(
        select(BatchAllocation).where(BatchAllocation.batch_id == batch.id)
    ):
        freed = await release(db, allocation)
        if freed > 0:
            released.append(
                {"component_id": str(allocation.component_id), "quantity": plain(freed)}
            )
    previous = batch.status
    batch.status = status
    batch.status_reason = reason
    touch(batch, context)
    audit(
        db,
        context,
        request,
        f"outsourcing.batch_{status}",
        {
            "batch_id": str(batch.id),
            "number": batch.number,
            "from": previous,
            "reason": reason,
            "released_allocations": released,
        },
    )
    await commit_or_conflict(db, STALE)
    return await batch_out(db, batch)


@router.post("/batches/{batch_id}/cancel", response_model=BatchOut, dependencies=CSRF)
async def cancel_batch(
    batch_id: uuid.UUID,
    payload: BatchReasoned,
    request: Request,
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    batch = await get_batch(db, context, batch_id)
    require_version(batch.version, payload.version)
    if batch.status != "planned":
        raise HTTPException(
            status_code=409,
            detail="Only a planned batch can be cancelled; material at the supplier must be "
            "returned or the batch closed with a reason",
        )
    return await finish(db, context, request, batch, "cancelled", payload.reason)


@router.post("/batches/{batch_id}/close", response_model=BatchOut, dependencies=CSRF)
async def close_batch(
    batch_id: uuid.UUID,
    payload: BatchReasoned,
    request: Request,
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    batch = await get_batch(db, context, batch_id)
    require_version(batch.version, payload.version)
    if batch.status != "at_supplier":
        raise HTTPException(status_code=409, detail="Only a batch at the supplier can be closed")
    return await finish(db, context, request, batch, "closed", payload.reason)


@router.post("/batches/{batch_id}/allocations", response_model=BatchOut, dependencies=CSRF)
async def add_allocation(
    batch_id: uuid.UUID,
    payload: AllocationAdd,
    request: Request,
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    batch = await get_batch(db, context, batch_id)
    require_version(batch.version, payload.version)
    if batch.status not in ACTIVE:
        raise HTTPException(status_code=409, detail=f"A {batch.status} batch cannot be allocated")
    unit = await db.get(UnitOfMeasure, batch.unit_id)
    summary = await allocate(db, context, batch, unit, payload, await batch_allocated(db, batch.id))
    touch(batch, context)
    audit(
        db,
        context,
        request,
        "outsourcing.allocation_added",
        {"batch_id": str(batch.id), "number": batch.number, **summary},
    )
    await commit_or_conflict(db, STALE)
    return await batch_out(db, batch)


@router.delete(
    "/batches/{batch_id}/allocations/{allocation_id}", response_model=BatchOut, dependencies=CSRF
)
async def remove_allocation(
    batch_id: uuid.UUID,
    allocation_id: uuid.UUID,
    request: Request,
    version: int = Query(ge=1),
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    batch = await get_batch(db, context, batch_id)
    require_version(batch.version, version)
    allocation = await db.scalar(
        select(BatchAllocation).where(
            BatchAllocation.batch_id == batch.id, BatchAllocation.id == allocation_id
        )
    )
    if allocation is None:
        raise HTTPException(status_code=404, detail="Allocation not found")
    if allocation.consumed_qty > 0:
        raise HTTPException(
            status_code=409,
            detail="Material from this allocation has shipped; it can no longer be unlinked",
        )
    touch(batch, context)
    audit(
        db,
        context,
        request,
        "outsourcing.allocation_removed",
        {
            "batch_id": str(batch.id),
            "number": batch.number,
            "component_id": str(allocation.component_id),
            "quantity": plain(allocation.quantity),
        },
    )
    await db.delete(allocation)
    await commit_or_conflict(db, STALE)
    return await batch_out(db, batch)


# Supplier updates (slice F4) ---------------------------------------------------

RECORD = require_permission("supplier_updates:record")


def as_utc(value: datetime) -> datetime:
    # SQLite hands back naive datetimes; they were stored as UTC.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


CLOCK_SKEW = timedelta(minutes=5)


@router.post(
    "/batches/{batch_id}/updates", response_model=BatchOut, status_code=201, dependencies=CSRF
)
async def record_supplier_update(
    batch_id: uuid.UUID,
    payload: SupplierUpdateIn,
    request: Request,
    response: Response,
    context: AuthContext = Depends(RECORD),
    db: AsyncSession = Depends(get_db),
):
    batch = await get_batch(db, context, batch_id)
    replay = await db.scalar(
        select(SupplierUpdate).where(
            SupplierUpdate.tenant_id == context.tenant.id,
            SupplierUpdate.submission_key == payload.submission_key,
        )
    )
    if replay is not None:
        if replay.batch_id != batch.id:
            raise HTTPException(status_code=409, detail="This submission key was already used")
        # The same form was submitted twice (double tap, retry): keep the first record.
        response.status_code = 200
        return await batch_out(db, batch)
    require_version(batch.version, payload.version)
    if batch.status != "at_supplier":
        raise HTTPException(
            status_code=409, detail="Supplier updates apply only to batches at the supplier"
        )
    unit = await db.get(UnitOfMeasure, batch.unit_id)
    for quantity in (payload.completed_qty, payload.rejected_qty, payload.pending_qty):
        check_precision(quantity, unit)
    total = payload.completed_qty + payload.rejected_qty + payload.pending_qty
    if total != batch.quantity:
        raise HTTPException(
            status_code=422,
            detail=f"Completed, rejected and pending must add up to the {plain(batch.quantity)} "
            f"{unit.code} sent; these add up to {plain(total)}",
        )
    site = await db.get(Site, batch.site_id)
    zone = ZoneInfo(site.time_zone)
    now = datetime.now(UTC)
    if payload.reported_at > now + CLOCK_SKEW:
        raise HTTPException(status_code=422, detail="The report time cannot be in the future")
    if payload.reported_at.astimezone(zone).date() < batch.sent_date:
        raise HTTPException(status_code=422, detail="The report time is before the batch was sent")
    if payload.revised_return_date and payload.revised_return_date < batch.sent_date:
        raise HTTPException(
            status_code=422, detail="The revised return date is before the batch was sent"
        )

    # Store UTC so ordering never depends on the offset the client used.
    reported_at = payload.reported_at.astimezone(UTC)
    current = (await current_updates(db, [batch.id])).get(batch.id)
    current_at = as_utc(current.reported_at) if current else None
    if payload.corrects_id is not None:
        if current is None or payload.corrects_id != current.id:
            raise HTTPException(
                status_code=409, detail="Only the latest supplier update can be corrected"
            )
        if not payload.correction_reason or len(payload.correction_reason.strip()) < 3:
            raise HTTPException(status_code=422, detail="Say why the update is being corrected")
        if reported_at < current_at:
            raise HTTPException(
                status_code=422,
                detail="A correction cannot be dated before the update it corrects",
            )
    else:
        if payload.correction_reason:
            raise HTTPException(
                status_code=422, detail="A correction reason needs the update it corrects"
            )
        if current is not None:
            if reported_at < current_at:
                raise HTTPException(
                    status_code=422,
                    detail="A newer supplier update already exists; "
                    "record an older report as a correction",
                )
            for field, label in (("completed_qty", "completed"), ("rejected_qty", "rejected")):
                if getattr(payload, field) < getattr(current, field):
                    raise HTTPException(
                        status_code=422,
                        detail=f"The supplier earlier reported {plain(getattr(current, field))} "
                        f"{unit.code} {label}; recording less needs a correction with a reason",
                    )

    update = SupplierUpdate(
        id=uuid.uuid4(),
        tenant_id=context.tenant.id,
        batch_id=batch.id,
        completed_qty=payload.completed_qty,
        rejected_qty=payload.rejected_qty,
        pending_qty=payload.pending_qty,
        revised_return_date=payload.revised_return_date,
        blocker=payload.blocker,
        source="manufacturer_entered",
        contact_method=payload.contact_method,
        contact_name=payload.contact_name,
        reported_at=reported_at,
        confirmation_state="supplier_confirmation_pending",
        corrects_id=payload.corrects_id,
        correction_reason=payload.correction_reason if payload.corrects_id else None,
        submission_key=payload.submission_key,
        recorded_by=context.user.id,
        recorded_by_label=actor_label(context.user),
        recorded_at=now,
    )
    db.add(update)
    touch(batch, context)
    audit(
        db,
        context,
        request,
        "outsourcing.supplier_update_corrected"
        if payload.corrects_id
        else "outsourcing.supplier_update_recorded",
        {
            "batch_id": str(batch.id),
            "number": batch.number,
            "update_id": str(update.id),
            "source": update.source,
            "confirmation_state": update.confirmation_state,
            "contact_method": update.contact_method,
            "contact_name": update.contact_name,
            "reported_at": update.reported_at.isoformat(),
            "completed": plain(update.completed_qty),
            "rejected": plain(update.rejected_qty),
            "pending": plain(update.pending_qty),
            "revised_return_date": json_safe(update.revised_return_date),
            "blocker": update.blocker,
            "corrects_id": json_safe(update.corrects_id),
            "correction_reason": update.correction_reason,
        },
    )
    await commit_or_conflict(db, STALE)
    return await batch_out(db, batch)


# Receipts and quality (slice F5) ---------------------------------------------

RECEIVE = require_permission("receipts:record")
DECIDE = require_permission("quality:decide")


def site_today(site: Site):
    return datetime.now(UTC).astimezone(ZoneInfo(site.time_zone)).date()


@router.post(
    "/batches/{batch_id}/receipts", response_model=BatchOut, status_code=201, dependencies=CSRF
)
async def record_receipt(
    batch_id: uuid.UUID,
    payload: ReceiptIn,
    request: Request,
    response: Response,
    context: AuthContext = Depends(RECEIVE),
    db: AsyncSession = Depends(get_db),
):
    batch = await get_batch(db, context, batch_id)
    replay = await db.scalar(
        select(BatchReceipt).where(
            BatchReceipt.tenant_id == context.tenant.id,
            BatchReceipt.submission_key == payload.submission_key,
        )
    )
    if replay is not None:
        if replay.batch_id != batch.id:
            raise HTTPException(status_code=409, detail="This submission key was already used")
        response.status_code = 200
        return await batch_out(db, batch)
    require_version(batch.version, payload.version)
    if batch.status != "at_supplier":
        raise HTTPException(
            status_code=409, detail="Receipts are recorded only for batches at the supplier"
        )
    unit = await db.get(UnitOfMeasure, batch.unit_id)
    check_precision(payload.received_qty, unit)
    already = (await receipt_totals(db, [batch.id])).get(batch.id, ReceiptTotals()).received
    outstanding = batch.quantity - already
    if payload.received_qty > outstanding:
        raise HTTPException(
            status_code=422,
            detail=f"Only {plain(outstanding)} {unit.code} of {batch.number} is still at the "
            "supplier",
        )
    site = await db.get(Site, batch.site_id)
    if payload.receipt_date > site_today(site):
        raise HTTPException(status_code=422, detail="The receipt date cannot be in the future")
    if payload.receipt_date < batch.sent_date:
        raise HTTPException(status_code=422, detail="The receipt date is before the batch was sent")
    now = datetime.now(UTC)
    receipt = BatchReceipt(
        id=uuid.uuid4(),
        tenant_id=context.tenant.id,
        batch_id=batch.id,
        received_qty=payload.received_qty,
        receipt_date=payload.receipt_date,
        document_reference=payload.document_reference,
        note=payload.note,
        submission_key=payload.submission_key,
        received_by=context.user.id,
        received_by_label=actor_label(context.user),
        recorded_at=now,
    )
    db.add(receipt)
    db.add(
        BatchMovement(
            id=uuid.uuid4(),
            tenant_id=batch.tenant_id,
            batch_id=batch.id,
            kind="received_from_supplier",
            quantity=payload.received_qty,
            movement_date=payload.receipt_date,
            document_reference=payload.document_reference,
            note=payload.note,
            recorded_by=context.user.id,
            recorded_by_label=actor_label(context.user),
            recorded_at=now,
        )
    )
    touch(batch, context)
    audit(
        db,
        context,
        request,
        "outsourcing.receipt_recorded",
        {
            "batch_id": str(batch.id),
            "number": batch.number,
            "receipt_id": str(receipt.id),
            "quantity": plain(payload.received_qty),
            "receipt_date": payload.receipt_date.isoformat(),
            "document_reference": payload.document_reference,
        },
    )
    await commit_or_conflict(db, STALE)
    return await batch_out(db, batch)


async def get_receipt(
    db: AsyncSession, batch: OutsourcedBatch, receipt_id: uuid.UUID
) -> BatchReceipt:
    receipt = await db.scalar(
        select(BatchReceipt).where(BatchReceipt.batch_id == batch.id, BatchReceipt.id == receipt_id)
    )
    if receipt is None:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return receipt


def decide(
    db: AsyncSession,
    context: AuthContext,
    receipt: BatchReceipt,
    kind: str,
    accepted: Decimal,
    rejected: Decimal,
    held: Decimal,
    rework: Decimal,
    note: str | None,
) -> None:
    db.add(
        QualityDecision(
            id=uuid.uuid4(),
            tenant_id=receipt.tenant_id,
            receipt_id=receipt.id,
            kind=kind,
            accepted_qty=accepted,
            rejected_qty=rejected,
            held_qty=held,
            rework_qty=rework,
            note=note,
            decided_by=context.user.id,
            decided_by_label=actor_label(context.user),
            decided_at=datetime.now(UTC),
        )
    )


@router.post(
    "/batches/{batch_id}/receipts/{receipt_id}/inspection",
    response_model=BatchOut,
    dependencies=CSRF,
)
async def record_inspection(
    batch_id: uuid.UUID,
    receipt_id: uuid.UUID,
    payload: InspectionIn,
    request: Request,
    context: AuthContext = Depends(DECIDE),
    db: AsyncSession = Depends(get_db),
):
    batch = await get_batch(db, context, batch_id)
    receipt = await get_receipt(db, batch, receipt_id)
    require_version(receipt.version, payload.version)
    if receipt.status != "awaiting_inspection":
        raise HTTPException(
            status_code=409,
            detail="This receipt is already inspected; release held material instead",
        )
    unit = await db.get(UnitOfMeasure, batch.unit_id)
    parts = (payload.accepted_qty, payload.rejected_qty, payload.held_qty, payload.rework_qty)
    for quantity in parts:
        check_precision(quantity, unit)
    if sum(parts, ZERO) != receipt.received_qty:
        raise HTTPException(
            status_code=422,
            detail=f"Accepted, rejected, held and rework must add up to the "
            f"{plain(receipt.received_qty)} {unit.code} received; these add up to "
            f"{plain(sum(parts, ZERO))}",
        )
    if sum(parts[1:], ZERO) > 0 and not payload.note:
        raise HTTPException(
            status_code=422, detail="Say why material was rejected, held or sent for rework"
        )
    receipt.accepted_qty = payload.accepted_qty
    receipt.rejected_qty = payload.rejected_qty
    receipt.held_qty = payload.held_qty
    receipt.rework_qty = payload.rework_qty
    receipt.status = "inspected"
    decide(db, context, receipt, "inspection", *parts, payload.note)
    touch(batch, context)
    audit(
        db,
        context,
        request,
        "quality.inspection_recorded",
        {
            "batch_id": str(batch.id),
            "number": batch.number,
            "receipt_id": str(receipt.id),
            "received": plain(receipt.received_qty),
            "accepted": plain(payload.accepted_qty),
            "rejected": plain(payload.rejected_qty),
            "held": plain(payload.held_qty),
            "rework": plain(payload.rework_qty),
            "note": payload.note,
        },
    )
    await commit_or_conflict(db, STALE)
    return await batch_out(db, batch)


@router.post(
    "/batches/{batch_id}/receipts/{receipt_id}/release",
    response_model=BatchOut,
    dependencies=CSRF,
)
async def release_hold(
    batch_id: uuid.UUID,
    receipt_id: uuid.UUID,
    payload: HoldReleaseIn,
    request: Request,
    context: AuthContext = Depends(DECIDE),
    db: AsyncSession = Depends(get_db),
):
    batch = await get_batch(db, context, batch_id)
    receipt = await get_receipt(db, batch, receipt_id)
    require_version(receipt.version, payload.version)
    if receipt.held_qty <= 0:
        raise HTTPException(status_code=409, detail="Nothing on this receipt is on hold")
    unit = await db.get(UnitOfMeasure, batch.unit_id)
    parts = (payload.accepted_qty, payload.rejected_qty, payload.rework_qty)
    for quantity in parts:
        check_precision(quantity, unit)
    released = sum(parts, ZERO)
    if released <= 0 or released > receipt.held_qty:
        raise HTTPException(
            status_code=422,
            detail=f"Release between 1 and {plain(receipt.held_qty)} {unit.code} held; "
            f"this releases {plain(released)}",
        )
    receipt.accepted_qty += payload.accepted_qty
    receipt.rejected_qty += payload.rejected_qty
    receipt.rework_qty += payload.rework_qty
    receipt.held_qty -= released
    decide(
        db,
        context,
        receipt,
        "hold_release",
        payload.accepted_qty,
        payload.rejected_qty,
        receipt.held_qty,
        payload.rework_qty,
        payload.reason,
    )
    touch(batch, context)
    audit(
        db,
        context,
        request,
        "quality.hold_released",
        {
            "batch_id": str(batch.id),
            "number": batch.number,
            "receipt_id": str(receipt.id),
            "accepted": plain(payload.accepted_qty),
            "rejected": plain(payload.rejected_qty),
            "rework": plain(payload.rework_qty),
            "still_held": plain(receipt.held_qty),
            "reason": payload.reason,
        },
    )
    await commit_or_conflict(db, STALE)
    return await batch_out(db, batch)
