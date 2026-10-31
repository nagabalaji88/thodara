"""Importing outsourced batches from a spreadsheet (slice G6, ADR-0014).

The whole file is checked, including the same allocation checks as the screen, inside a
transaction that is rolled back for a preview. A file with any problem creates nothing, and
importing the same file again creates nothing new.
"""

import csv
import io
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AuthContext, require_csrf, require_permission
from app.api.masterdata import audit
from app.api.orders import check_precision, plain
from app.api.outsourcing import allocate
from app.core.audit import actor_label
from app.core.i18n import tr
from app.db.session import get_db
from app.models.identity import Site
from app.models.masterdata import Customer, Item, Supplier, UnitOfMeasure
from app.models.orders import OrderLineComponent, SalesOrder, SalesOrderLine
from app.models.outsourcing import BatchMovement, OutsourcedBatch
from app.schemas.outsourcing import (
    AllocationIn,
    BatchImportIssue,
    BatchImportReport,
    BatchImportRequest,
)
from app.services.numbering import allocate_number

router = APIRouter(prefix="/outsourcing", tags=["outsourcing"])
MANAGE = require_permission("outsourcing:manage")
CSRF = [Depends(require_csrf)]
MAX_ROWS = 2000
REQUIRED = {"supplier_code", "item_code", "operation", "quantity", "expected_return_date"}
OPTIONAL = {
    "sent_date",
    "challan_reference",
    "batch_reference",
    "material_owner",
    "owner_customer_code",
    "order_number",
    "line_no",
    "allocate_qty",
    "notes",
}
# Columns that describe the batch itself; rows of one batch must agree on them.
BATCH_COLUMNS = (
    "item_code",
    "operation",
    "quantity",
    "expected_return_date",
    "sent_date",
    "material_owner",
    "owner_customer_code",
    "notes",
)


def parse_date(text: str) -> date:
    value = date.fromisoformat(text)
    if not date(2000, 1, 1) <= value <= date(2100, 12, 31):
        raise ValueError
    return value


def positive(text: str) -> Decimal | None:
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value.is_finite() and value > 0 else None


@router.post("/batches/import", response_model=BatchImportReport, dependencies=CSRF)
async def import_batches(
    payload: BatchImportRequest,
    request: Request,
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    site = await db.scalar(
        select(Site).where(Site.tenant_id == context.tenant.id, Site.id == payload.site_id)
    )
    if site is None or not context.can_access_site(site.id) or site.status != "active":
        raise HTTPException(status_code=422, detail=tr("Choose an active site you can access"))
    today = datetime.now(UTC).astimezone(ZoneInfo(site.time_zone)).date()
    errors: list[BatchImportIssue] = []

    def err(row: int, message: str, field: str | None = None) -> None:
        errors.append(BatchImportIssue(row=row, field=field, message=message))

    reader = csv.DictReader(io.StringIO(payload.csv_text.lstrip("﻿")))
    header = [(h or "").strip().lower() for h in (reader.fieldnames or [])]
    if missing := REQUIRED - set(header):
        err(1, tr("Missing column(s): {items}", items=", ".join(sorted(missing))))
    if unknown := set(header) - REQUIRED - OPTIONAL:
        err(1, tr("Unknown column(s): {items}", items=", ".join(sorted(unknown))))
    if len(header) != len(set(header)):
        err(1, tr("Each column may appear only once"))

    groups: dict[tuple[str, str], dict[str, Any]] = {}
    total = 0
    if not errors:
        reader.fieldnames = header
        suppliers = {
            s.code: s
            for s in await db.scalars(
                select(Supplier).where(
                    Supplier.tenant_id == context.tenant.id,
                    Supplier.status == "active",
                    Supplier.provides_job_work.is_(True),
                )
            )
        }
        items = {
            i.code: i
            for i in await db.scalars(
                select(Item).where(Item.tenant_id == context.tenant.id, Item.status == "active")
            )
        }
        customers = {
            c.code: c
            for c in await db.scalars(
                select(Customer).where(
                    Customer.tenant_id == context.tenant.id, Customer.status == "active"
                )
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
                    err(row, tr("This row has more values than there are columns"))
                    continue
                v = {k: (value or "").strip() for k, value in raw.items()}
                if not any(v.values()):
                    continue
                total += 1
                if total > MAX_ROWS:
                    err(row, tr("A file may contain at most {max_rows} rows", max_rows=MAX_ROWS))
                    break
                ok = True
                supplier = suppliers.get(v["supplier_code"].upper())
                if supplier is None:
                    err(
                        row,
                        tr(
                            "No active job-work supplier with code {code}",
                            code=v["supplier_code"] or "(blank)",
                        ),
                        "supplier_code",
                    )
                    ok = False
                item = items.get(v["item_code"].upper())
                if item is None:
                    err(
                        row,
                        tr("No active item with code {value}", value=v["item_code"] or "(blank)"),
                        "item_code",
                    )
                    ok = False
                if not v["operation"] or len(v["operation"]) > 80:
                    err(row, tr("Give the outsourced step (up to 80 characters)"), "operation")
                    ok = False
                quantity = positive(v["quantity"])
                if quantity is None:
                    err(row, tr("Enter a positive number"), "quantity")
                    ok = False
                elif item is not None:
                    try:
                        check_precision(quantity, units[item.base_unit_id])
                    except HTTPException as exc:
                        err(row, exc.detail, "quantity")
                        ok = False
                dates: dict[str, date | None] = {}
                for field in ("expected_return_date", "sent_date"):
                    text = v.get(field, "")
                    dates[field] = None
                    if not text:
                        if field == "expected_return_date":
                            err(row, tr("Enter a date as YYYY-MM-DD"), field)
                            ok = False
                        continue
                    try:
                        dates[field] = parse_date(text)
                    except ValueError:
                        err(row, tr("Enter a date as YYYY-MM-DD between 2000 and 2100"), field)
                        ok = False
                challan = v.get("challan_reference", "")
                reference = v.get("batch_reference", "")
                if bool(v.get("sent_date")) != bool(challan):
                    err(
                        row,
                        tr("Give the sent date and our challan number together"),
                        "challan_reference",
                    )
                    ok = False
                if dates["sent_date"] and dates["sent_date"] > today:
                    err(row, tr("The sent date cannot be in the future"), "sent_date")
                    ok = False
                if len(challan) > 80 or len(reference) > 80:
                    err(row, tr("References may have up to 80 characters"), "batch_reference")
                    ok = False
                if not challan and not reference:
                    err(
                        row,
                        tr(
                            "Give our challan number or a batch reference so the batch "
                            "can be recognised again"
                        ),
                        "batch_reference",
                    )
                    ok = False
                owner = (v.get("material_owner") or "own").lower()
                owner_code = v.get("owner_customer_code", "").upper()
                owner_customer = customers.get(owner_code) if owner_code else None
                if owner not in ("own", "customer"):
                    err(row, tr("Material owner is own or customer"), "material_owner")
                    ok = False
                elif owner == "customer" and owner_customer is None:
                    err(
                        row,
                        tr(
                            "Customer-supplied material needs owner_customer_code of an "
                            "active customer"
                        ),
                        "owner_customer_code",
                    )
                    ok = False
                elif owner == "own" and owner_code:
                    err(
                        row,
                        tr("Our own material does not name a customer"),
                        "owner_customer_code",
                    )
                    ok = False
                link = [v.get(k, "") for k in ("order_number", "line_no", "allocate_qty")]
                allocation = None
                if any(link) and not all(link):
                    err(
                        row,
                        tr("Give order_number, line_no and allocate_qty together"),
                        "order_number",
                    )
                    ok = False
                elif all(link):
                    line_no = int(link[1]) if link[1].isdigit() else None
                    qty = positive(link[2])
                    if line_no is None or qty is None:
                        err(
                            row,
                            tr("Line number and quantity must be positive numbers"),
                            "line_no",
                        )
                        ok = False
                    else:
                        allocation = (row, link[0].upper(), line_no, qty)
                if not ok:
                    continue
                key = (supplier.code, f"c:{challan}" if challan else f"r:{reference}")
                details = {k: v.get(k, "") for k in BATCH_COLUMNS} | {
                    "material_owner": owner,
                    "owner_customer_code": owner_code,
                }
                group = groups.setdefault(
                    key,
                    {
                        "row": row,
                        "details": details,
                        "supplier": supplier,
                        "item": item,
                        "quantity": quantity,
                        "expected": dates["expected_return_date"],
                        "sent": dates["sent_date"],
                        "challan": challan or None,
                        "reference": reference or None,
                        "owner": owner,
                        "owner_customer": owner_customer,
                        "notes": v.get("notes") or None,
                        "operation": v["operation"],
                        "allocations": [],
                    },
                )
                if group["details"] != details:
                    err(
                        row,
                        tr(
                            "Batch details differ from row {first} of the same batch",
                            first=group["row"],
                        ),
                    )
                    continue
                if group["reference"] is None and reference:
                    group["reference"] = reference
                if allocation:
                    group["allocations"].append(allocation)
        except csv.Error as exc:
            err(reader.line_num, tr("The file could not be read: {exc}", exc=exc))
    if total == 0 and not errors:
        err(1, tr("The file has no data rows"))

    to_create: list[dict[str, Any]] = []
    unchanged = 0
    for (_, key), group in groups.items():
        match = (
            OutsourcedBatch.challan_reference == group["challan"]
            if key.startswith("c:")
            else OutsourcedBatch.reference == group["reference"]
        )
        existing = await db.scalar(
            select(OutsourcedBatch).where(
                OutsourcedBatch.tenant_id == context.tenant.id,
                OutsourcedBatch.supplier_id == group["supplier"].id,
                match,
            )
        )
        if existing is None:
            to_create.append(group)
        elif (
            existing.item_id,
            existing.operation,
            existing.quantity,
            existing.site_id,
        ) == (group["item"].id, group["operation"], group["quantity"], site.id):
            unchanged += 1
        else:
            err(
                group["row"],
                tr(
                    "{supplier} {reference} is already batch {number} with different "
                    "details; change it in the app instead",
                    supplier=group["supplier"].code,
                    reference=group["challan"] or group["reference"],
                    number=existing.number,
                ),
                "challan_reference" if group["challan"] else "batch_reference",
            )

    created: list[str] = []
    allocations = 0
    # Built inside the transaction so allocations get exactly the screen's checks; a preview,
    # or a file with any problem, is rolled back.
    if not errors:
        for group in to_create:
            created.append(await build(db, context, request, site, group, err))
            allocations += len(group["allocations"])

    report = BatchImportReport(
        total_rows=total,
        batches_to_create=len(to_create),
        sent_batches=sum(1 for g in to_create if g["sent"]),
        allocations_to_create=allocations,
        unchanged_batches=unchanged,
        errors=errors,
        committed=False,
    )
    if errors or not payload.commit:
        await db.rollback()
        if errors and payload.commit:
            return JSONResponse(status_code=422, content=report.model_dump(mode="json"))
        return report
    audit(
        db,
        context,
        request,
        "outsourcing.batches_imported",
        {"site": site.name, "created": created, "unchanged": unchanged, "rows": total},
    )
    await db.commit()
    return report.model_copy(update={"committed": True, "created_numbers": created})


async def build(db, context, request, site, group, err) -> str:
    """Create one batch (and its sending and allocations) exactly as the screen would."""
    item = group["item"]
    unit = await db.get(UnitOfMeasure, item.base_unit_id)
    batch = OutsourcedBatch(
        id=uuid.uuid4(),
        tenant_id=context.tenant.id,
        site_id=site.id,
        number=await allocate_number(db, context.tenant.id, "outsourced_batch"),
        supplier_id=group["supplier"].id,
        item_id=item.id,
        unit_id=unit.id,
        operation=group["operation"],
        quantity=group["quantity"],
        expected_return_date=group["expected"],
        notes=group["notes"],
        reference=group["reference"],
        material_owner=group["owner"],
        owner_customer_id=group["owner_customer"].id if group["owner_customer"] else None,
        created_by=context.user.id,
        updated_by=context.user.id,
    )
    db.add(batch)
    await db.flush()
    summaries = []
    allocated = Decimal(0)
    for row, order_number, line_no, qty in group["allocations"]:
        component = await db.scalar(
            select(OrderLineComponent)
            .join(SalesOrderLine, SalesOrderLine.id == OrderLineComponent.line_id)
            .join(SalesOrder, SalesOrder.id == SalesOrderLine.order_id)
            .where(
                SalesOrder.tenant_id == context.tenant.id,
                SalesOrder.number == order_number,
                SalesOrderLine.line_no == line_no,
                OrderLineComponent.item_id == item.id,
            )
        )
        if component is None:
            err(
                row,
                tr(
                    "{order_number} line {line_no} has no component {item_code}",
                    order_number=order_number,
                    line_no=line_no,
                    item_code=item.code,
                ),
                "order_number",
            )
            continue
        try:
            summaries.append(
                await allocate(
                    db,
                    context,
                    batch,
                    unit,
                    AllocationIn(component_id=component.id, quantity=qty),
                    allocated,
                )
            )
            allocated += qty
        except HTTPException as exc:
            err(row, str(exc.detail), "allocate_qty")
    audit(
        db,
        context,
        request,
        "outsourcing.batch_created",
        {
            "batch_id": str(batch.id),
            "number": batch.number,
            "supplier": group["supplier"].code,
            "item": item.code,
            "source": "import",
            "operation": batch.operation,
            "quantity": plain(batch.quantity),
            "reference": batch.reference,
            "material_owner": batch.material_owner,
            "allocations": summaries,
        },
    )
    if group["sent"]:
        batch.status = "at_supplier"
        batch.sent_date = group["sent"]
        batch.challan_reference = group["challan"]
        db.add(
            BatchMovement(
                id=uuid.uuid4(),
                tenant_id=batch.tenant_id,
                batch_id=batch.id,
                kind="sent_to_supplier",
                quantity=batch.quantity,
                movement_date=group["sent"],
                document_reference=group["challan"],
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
                "sent_date": group["sent"].isoformat(),
                "challan_reference": group["challan"],
                "source": "import",
            },
        )
    await db.flush()
    return batch.number
