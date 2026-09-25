import csv
import hashlib
import io
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AuthContext, get_auth_context, require_csrf
from app.api.masterdata import audit, commit_or_conflict, create_record, json_safe
from app.db.session import get_db
from app.models.masterdata import Customer, Item, Supplier, UnitOfMeasure
from app.schemas.masterdata import (
    CustomerCreate,
    ImportEntity,
    ImportIssue,
    ImportReport,
    ImportRequest,
    ItemCreate,
    SupplierCreate,
)

router = APIRouter(prefix="/master-data/imports", tags=["master data"])
MAX_ROWS = 2000
TRUE_VALUES = {"yes", "y", "true", "1"}
FALSE_VALUES = {"no", "n", "false", "0"}


@dataclass(frozen=True)
class ImportSpec:
    model: Any
    schema: type[BaseModel]
    entity: str
    permission: str
    required: frozenset[str]
    optional: frozenset[str]


SPECS: dict[str, ImportSpec] = {
    "customers": ImportSpec(
        Customer,
        CustomerCreate,
        "customer",
        "customers:manage",
        frozenset({"code", "name"}),
        frozenset({"contact_email", "contact_phone", "city"}),
    ),
    "suppliers": ImportSpec(
        Supplier,
        SupplierCreate,
        "supplier",
        "suppliers:manage",
        frozenset({"code", "name"}),
        frozenset({"contact_email", "contact_phone", "city", "provides_job_work"}),
    ),
    "items": ImportSpec(
        Item,
        ItemCreate,
        "item",
        "items:manage",
        frozenset({"code", "name", "item_type", "base_unit_code"}),
        frozenset({"tracking", "description"}),
    ),
}


@dataclass
class Plan:
    total_rows: int = 0
    to_create: list[dict[str, Any]] = field(default_factory=list)
    unchanged: int = 0
    errors: list[ImportIssue] = field(default_factory=list)

    def error(self, row: int, message: str, column: str | None = None) -> None:
        self.errors.append(ImportIssue(row=row, field=column, message=message))


async def build_plan(
    db: AsyncSession, context: AuthContext, spec: ImportSpec, csv_text: str
) -> Plan:
    plan = Plan()
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("﻿")))
    try:
        header = [(name or "").strip().lower() for name in (reader.fieldnames or [])]
    except csv.Error as exc:
        plan.error(1, f"The file could not be read as CSV: {exc}")
        return plan
    missing = spec.required - set(header)
    unknown = set(header) - spec.required - spec.optional
    if missing:
        plan.error(1, "Missing column(s): " + ", ".join(sorted(missing)))
    if unknown:
        plan.error(1, "Unknown column(s): " + ", ".join(sorted(unknown)))
    if len(header) != len(set(header)):
        plan.error(1, "Each column may appear only once")
    if plan.errors:
        return plan
    reader.fieldnames = header

    units: dict[str, UnitOfMeasure] = {}
    if spec.model is Item:
        rows = await db.scalars(
            select(UnitOfMeasure).where(
                UnitOfMeasure.tenant_id == context.tenant.id, UnitOfMeasure.status == "active"
            )
        )
        units = {unit.code: unit for unit in rows}

    candidates: list[tuple[int, dict[str, Any]]] = []
    seen: dict[str, int] = {}
    try:
        for raw in reader:
            row_number = reader.line_num
            if None in raw:
                plan.error(row_number, "This row has more values than there are columns")
                continue
            values = {key: (value or "").strip() for key, value in raw.items()}
            if not any(values.values()):
                continue
            plan.total_rows += 1
            if plan.total_rows > MAX_ROWS:
                plan.error(row_number, f"A file may contain at most {MAX_ROWS} rows")
                break
            raw_code = values.get("code", "").strip().upper()
            if raw_code and raw_code in seen:
                plan.error(
                    row_number, f"Code {raw_code} also appears on row {seen[raw_code]}", "code"
                )
                continue
            if raw_code:
                seen[raw_code] = row_number
            data = await _row_to_input(values, spec, units, plan, row_number)
            if data is None:
                continue
            try:
                parsed = spec.schema.model_validate(data)
            except ValidationError as exc:
                for issue in exc.errors():
                    column = str(issue["loc"][0]) if issue["loc"] else None
                    if column == "base_unit_id":
                        column = "base_unit_code"
                    plan.error(row_number, issue["msg"], column)
                continue
            candidates.append((row_number, parsed.model_dump()))
    except csv.Error as exc:
        plan.error(reader.line_num, f"The file could not be read as CSV: {exc}")
        return plan

    existing = {}
    if candidates:
        codes = [values_out["code"] for _, values_out in candidates]
        rows = await db.scalars(
            select(spec.model).where(
                spec.model.tenant_id == context.tenant.id, spec.model.code.in_(codes)
            )
        )
        existing = {record.code: record for record in rows}
    for row_number, values_out in candidates:
        record = existing.get(values_out["code"])
        if record is None:
            plan.to_create.append(values_out)
            continue
        differing = [
            key for key, value in values_out.items() if getattr(record, key) != value
        ]
        if differing:
            plan.error(
                row_number,
                f"Code {values_out['code']} already exists with different "
                f"{', '.join(sorted(differing))}; change it in the app instead",
                "code",
            )
        else:
            plan.unchanged += 1
    if plan.total_rows == 0 and not plan.errors:
        plan.error(1, "The file has no data rows")
    return plan


async def _row_to_input(
    values: dict[str, str],
    spec: ImportSpec,
    units: dict[str, UnitOfMeasure],
    plan: Plan,
    row_number: int,
) -> dict[str, Any] | None:
    data: dict[str, Any] = {key: value for key, value in values.items() if value != ""}
    if "provides_job_work" in data:
        flag = data["provides_job_work"].lower()
        if flag not in TRUE_VALUES | FALSE_VALUES:
            plan.error(row_number, "Use yes or no", "provides_job_work")
            return None
        data["provides_job_work"] = flag in TRUE_VALUES
    if spec.model is Item:
        unit_code = data.pop("base_unit_code", "").upper()
        unit = units.get(unit_code)
        if unit is None:
            plan.error(row_number, f"No active unit with code {unit_code or '(blank)'}",
                       "base_unit_code")
            return None
        data["base_unit_id"] = unit.id
    return data


@router.post("/{entity}", response_model=ImportReport, dependencies=[Depends(require_csrf)])
async def import_records(
    entity: ImportEntity,
    payload: ImportRequest,
    request: Request,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    spec = SPECS[entity]
    if spec.permission not in context.permissions:
        raise HTTPException(status_code=403, detail="Permission denied")
    plan = await build_plan(db, context, spec, payload.csv_text)
    report = ImportReport(
        entity=entity,
        total_rows=plan.total_rows,
        to_create=len(plan.to_create),
        unchanged=plan.unchanged,
        errors=plan.errors,
        committed=False,
    )
    if not payload.commit:
        return report
    if plan.errors:
        return JSONResponse(status_code=422, content=report.model_dump(mode="json"))
    for values in plan.to_create:
        await create_record(db, context, request, spec.model, spec.entity, values, "import")
    audit(
        db,
        context,
        request,
        "masterdata.import.committed",
        {
            "entity": entity,
            "created": len(plan.to_create),
            "unchanged": plan.unchanged,
            "file_sha256": hashlib.sha256(payload.csv_text.encode()).hexdigest(),
            "codes": [json_safe(values["code"]) for values in plan.to_create][:200],
        },
    )
    await commit_or_conflict(db, "Another change created one of these codes; preview again")
    report.committed = True
    return report
