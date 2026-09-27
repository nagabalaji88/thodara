import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.api.dependencies import AuthContext, require_csrf, require_permission
from app.db.session import get_db
from app.models.identity import AuditEvent, Site
from app.models.masterdata import (
    Customer,
    Item,
    Supplier,
    UnitConversion,
    UnitOfMeasure,
    Warehouse,
)
from app.schemas.masterdata import (
    ConversionCreate,
    ConversionOut,
    CustomerCreate,
    CustomerOut,
    CustomerUpdate,
    ItemCreate,
    ItemOut,
    ItemUpdate,
    Page,
    SupplierCreate,
    SupplierOut,
    SupplierUpdate,
    UnitCreate,
    UnitOut,
    UnitUpdate,
    WarehouseCreate,
    WarehouseOut,
    WarehouseUpdate,
)

router = APIRouter(prefix="/master-data", tags=["master data"])
READ = require_permission("masterdata:read")
CSRF = [Depends(require_csrf)]
NOT_FOUND = "Record not found"
STALE = "This record was changed by someone else. Reload it and try again."

MasterModel = type[UnitOfMeasure] | type[Customer] | type[Supplier] | type[Item] | type[Warehouse]


def json_safe(value: Any) -> Any:
    if isinstance(value, uuid.UUID | Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def snapshot(record: object, fields: list[str]) -> dict[str, Any]:
    return {field: json_safe(getattr(record, field)) for field in fields}


def audit(
    db: AsyncSession,
    context: AuthContext,
    request: Request,
    action: str,
    details: dict[str, Any],
) -> None:
    db.add(
        AuditEvent(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            action=action,
            request_id=request.state.request_id,
            details=details,
        )
    )


async def commit_or_conflict(db: AsyncSession, conflict_detail: str) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=conflict_detail) from exc
    except StaleDataError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=STALE) from exc


async def ensure_code_free(db: AsyncSession, model: MasterModel, tenant_id: uuid.UUID, code: str):
    existing = await db.scalar(
        select(model.id).where(model.tenant_id == tenant_id, model.code == code)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Code {code} is already in use"
        )


async def get_record(db: AsyncSession, model: MasterModel, context: AuthContext, record_id):
    record = await db.scalar(
        select(model).where(model.tenant_id == context.tenant.id, model.id == record_id)
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    if isinstance(record, Warehouse) and not context.can_access_site(record.site_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    return record


def apply_update(record: Any, payload: BaseModel, nullable: frozenset[str]) -> dict[str, Any]:
    """Apply only the fields the client sent; return {field: {from, to}} for the audit trail."""
    if payload.version != record.version:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=STALE)
    changes: dict[str, Any] = {}
    for field in payload.model_fields_set - {"version"}:
        value = getattr(payload, field)
        if value is None and field not in nullable:
            raise HTTPException(
                status_code=422,
                detail=f"{field} cannot be empty",
            )
        before = getattr(record, field)
        if before != value:
            changes[field] = {"from": json_safe(before), "to": json_safe(value)}
            setattr(record, field, value)
    return changes


async def list_page(
    db: AsyncSession,
    model: MasterModel,
    context: AuthContext,
    q: str | None,
    record_status: str | None,
    limit: int,
    offset: int,
    filters: tuple[Any, ...] = (),
):
    query = select(model).where(model.tenant_id == context.tenant.id, *filters)
    if record_status:
        query = query.where(model.status == record_status)
    if q and q.strip():
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.where(
            or_(model.code.ilike(pattern, escape="\\"), model.name.ilike(pattern, escape="\\"))
        )
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = await db.scalars(query.order_by(model.code).limit(limit).offset(offset))
    return rows.all(), total or 0


def page_params(
    q: str | None = Query(default=None, max_length=80),
    status_filter: str | None = Query(
        default=None, alias="status", pattern="^(active|inactive)$"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> dict[str, Any]:
    return {"q": q, "record_status": status_filter, "limit": limit, "offset": offset}


async def create_record(
    db: AsyncSession,
    context: AuthContext,
    request: Request,
    model: MasterModel,
    entity: str,
    values: dict[str, Any],
    source: str = "manual",
):
    await ensure_code_free(db, model, context.tenant.id, values["code"])
    record = model(
        tenant_id=context.tenant.id,
        created_by=context.user.id,
        updated_by=context.user.id,
        **values,
    )
    db.add(record)
    await db.flush()
    audit(
        db,
        context,
        request,
        f"masterdata.{entity}.created",
        {"record_id": str(record.id), "code": record.code, "source": source,
         "after": {key: json_safe(value) for key, value in values.items()}},
    )
    return record


async def update_record(
    db: AsyncSession,
    context: AuthContext,
    request: Request,
    record: Any,
    entity: str,
    payload: BaseModel,
    nullable: frozenset[str],
):
    changes = apply_update(record, payload, nullable)
    if changes:
        record.updated_by = context.user.id
        audit(
            db,
            context,
            request,
            f"masterdata.{entity}.updated",
            {"record_id": str(record.id), "code": record.code, "changes": changes},
        )
    await commit_or_conflict(db, STALE)
    await db.refresh(record)
    return record


# Units of measure


@router.get("/units", response_model=Page[UnitOut])
async def list_units(
    params: dict = Depends(page_params),
    context: AuthContext = Depends(READ),
    db: AsyncSession = Depends(get_db),
):
    items, total = await list_page(db, UnitOfMeasure, context, **params)
    return Page[UnitOut](items=items, total=total)


@router.post("/units", response_model=UnitOut, status_code=201, dependencies=CSRF)
async def create_unit(
    payload: UnitCreate,
    request: Request,
    context: AuthContext = Depends(require_permission("units:manage")),
    db: AsyncSession = Depends(get_db),
):
    record = await create_record(
        db, context, request, UnitOfMeasure, "unit", payload.model_dump()
    )
    await commit_or_conflict(db, f"Code {payload.code} is already in use")
    return record


@router.patch("/units/{record_id}", response_model=UnitOut, dependencies=CSRF)
async def update_unit(
    record_id: uuid.UUID,
    payload: UnitUpdate,
    request: Request,
    context: AuthContext = Depends(require_permission("units:manage")),
    db: AsyncSession = Depends(get_db),
):
    record = await get_record(db, UnitOfMeasure, context, record_id)
    if payload.status == "inactive" and record.status == "active":
        in_use = await db.scalar(
            select(func.count())
            .select_from(Item)
            .where(
                Item.tenant_id == context.tenant.id,
                Item.base_unit_id == record.id,
                Item.status == "active",
            )
        )
        if in_use:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"{in_use} active item(s) use {record.code} as their base unit",
            )
    return await update_record(db, context, request, record, "unit", payload, frozenset())


@router.get("/unit-conversions", response_model=list[ConversionOut])
async def list_conversions(
    context: AuthContext = Depends(READ),
    db: AsyncSession = Depends(get_db),
):
    conversions = (
        await db.scalars(
            select(UnitConversion).where(UnitConversion.tenant_id == context.tenant.id)
        )
    ).all()
    units = await units_by_id(db, context.tenant.id)
    return sorted(
        (conversion_out(conversion, units) for conversion in conversions),
        key=lambda row: (row.from_unit_code, row.to_unit_code),
    )


async def units_by_id(db: AsyncSession, tenant_id: uuid.UUID) -> dict[uuid.UUID, UnitOfMeasure]:
    rows = await db.scalars(select(UnitOfMeasure).where(UnitOfMeasure.tenant_id == tenant_id))
    return {unit.id: unit for unit in rows}


def conversion_out(
    conversion: UnitConversion, units: dict[uuid.UUID, UnitOfMeasure]
) -> ConversionOut:
    return ConversionOut(
        id=conversion.id,
        from_unit_id=conversion.from_unit_id,
        from_unit_code=units[conversion.from_unit_id].code,
        to_unit_id=conversion.to_unit_id,
        to_unit_code=units[conversion.to_unit_id].code,
        factor=conversion.factor,
        created_at=conversion.created_at,
    )


@router.post(
    "/unit-conversions", response_model=ConversionOut, status_code=201, dependencies=CSRF
)
async def create_conversion(
    payload: ConversionCreate,
    request: Request,
    context: AuthContext = Depends(require_permission("units:manage")),
    db: AsyncSession = Depends(get_db),
):
    if payload.from_unit_id == payload.to_unit_id:
        raise HTTPException(status_code=422, detail="Choose two different units")
    from_unit = await get_record(db, UnitOfMeasure, context, payload.from_unit_id)
    to_unit = await get_record(db, UnitOfMeasure, context, payload.to_unit_id)
    if from_unit.status != "active" or to_unit.status != "active":
        raise HTTPException(status_code=409, detail="Both units must be active")
    if from_unit.dimension != to_unit.dimension:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{from_unit.code} measures {from_unit.dimension} and {to_unit.code} measures "
                f"{to_unit.dimension}; only units of the same kind can be converted"
            ),
        )
    existing = await db.scalar(
        select(UnitConversion.id).where(
            UnitConversion.tenant_id == context.tenant.id,
            or_(
                (UnitConversion.from_unit_id == from_unit.id)
                & (UnitConversion.to_unit_id == to_unit.id),
                (UnitConversion.from_unit_id == to_unit.id)
                & (UnitConversion.to_unit_id == from_unit.id),
            ),
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"A conversion between {from_unit.code} and {to_unit.code} already exists",
        )
    conversion = UnitConversion(
        tenant_id=context.tenant.id,
        from_unit_id=from_unit.id,
        to_unit_id=to_unit.id,
        factor=payload.factor,
        created_by=context.user.id,
    )
    db.add(conversion)
    await db.flush()
    audit(
        db,
        context,
        request,
        "masterdata.unit_conversion.created",
        {
            "record_id": str(conversion.id),
            "from_unit": from_unit.code,
            "to_unit": to_unit.code,
            "factor": str(payload.factor),
        },
    )
    await commit_or_conflict(db, "This conversion already exists")
    await db.refresh(conversion)
    return conversion_out(conversion, {from_unit.id: from_unit, to_unit.id: to_unit})


@router.delete("/unit-conversions/{record_id}", status_code=204, dependencies=CSRF)
async def delete_conversion(
    record_id: uuid.UUID,
    request: Request,
    context: AuthContext = Depends(require_permission("units:manage")),
    db: AsyncSession = Depends(get_db),
):
    conversion = await db.scalar(
        select(UnitConversion).where(
            UnitConversion.tenant_id == context.tenant.id, UnitConversion.id == record_id
        )
    )
    if conversion is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    units = await units_by_id(db, context.tenant.id)
    audit(
        db,
        context,
        request,
        "masterdata.unit_conversion.deleted",
        {
            "record_id": str(conversion.id),
            "from_unit": units[conversion.from_unit_id].code,
            "to_unit": units[conversion.to_unit_id].code,
            "factor": str(conversion.factor),
        },
    )
    await db.delete(conversion)
    await db.commit()
    return Response(status_code=204)


# Customers and suppliers

PARTY_NULLABLE = frozenset({"contact_email", "contact_phone", "city"})


@router.get("/customers", response_model=Page[CustomerOut])
async def list_customers(
    params: dict = Depends(page_params),
    context: AuthContext = Depends(READ),
    db: AsyncSession = Depends(get_db),
):
    items, total = await list_page(db, Customer, context, **params)
    return Page[CustomerOut](items=items, total=total)


@router.post("/customers", response_model=CustomerOut, status_code=201, dependencies=CSRF)
async def create_customer(
    payload: CustomerCreate,
    request: Request,
    context: AuthContext = Depends(require_permission("customers:manage")),
    db: AsyncSession = Depends(get_db),
):
    values = payload.model_dump()
    record = await create_record(db, context, request, Customer, "customer", values)
    await commit_or_conflict(db, f"Code {payload.code} is already in use")
    return record


@router.patch("/customers/{record_id}", response_model=CustomerOut, dependencies=CSRF)
async def update_customer(
    record_id: uuid.UUID,
    payload: CustomerUpdate,
    request: Request,
    context: AuthContext = Depends(require_permission("customers:manage")),
    db: AsyncSession = Depends(get_db),
):
    record = await get_record(db, Customer, context, record_id)
    return await update_record(db, context, request, record, "customer", payload, PARTY_NULLABLE)


@router.get("/suppliers", response_model=Page[SupplierOut])
async def list_suppliers(
    params: dict = Depends(page_params),
    context: AuthContext = Depends(READ),
    db: AsyncSession = Depends(get_db),
):
    items, total = await list_page(db, Supplier, context, **params)
    return Page[SupplierOut](items=items, total=total)


@router.post("/suppliers", response_model=SupplierOut, status_code=201, dependencies=CSRF)
async def create_supplier(
    payload: SupplierCreate,
    request: Request,
    context: AuthContext = Depends(require_permission("suppliers:manage")),
    db: AsyncSession = Depends(get_db),
):
    values = payload.model_dump()
    record = await create_record(db, context, request, Supplier, "supplier", values)
    await commit_or_conflict(db, f"Code {payload.code} is already in use")
    return record


@router.patch("/suppliers/{record_id}", response_model=SupplierOut, dependencies=CSRF)
async def update_supplier(
    record_id: uuid.UUID,
    payload: SupplierUpdate,
    request: Request,
    context: AuthContext = Depends(require_permission("suppliers:manage")),
    db: AsyncSession = Depends(get_db),
):
    record = await get_record(db, Supplier, context, record_id)
    return await update_record(db, context, request, record, "supplier", payload, PARTY_NULLABLE)


# Items


async def active_unit(db: AsyncSession, context: AuthContext, unit_id: uuid.UUID) -> UnitOfMeasure:
    unit = await db.scalar(
        select(UnitOfMeasure).where(
            UnitOfMeasure.tenant_id == context.tenant.id, UnitOfMeasure.id == unit_id
        )
    )
    if unit is None or unit.status != "active":
        raise HTTPException(status_code=422, detail="Choose an active unit of measure")
    return unit


@router.get("/items", response_model=Page[ItemOut])
async def list_items(
    params: dict = Depends(page_params),
    context: AuthContext = Depends(READ),
    db: AsyncSession = Depends(get_db),
):
    items, total = await list_page(db, Item, context, **params)
    return Page[ItemOut](items=items, total=total)


@router.post("/items", response_model=ItemOut, status_code=201, dependencies=CSRF)
async def create_item(
    payload: ItemCreate,
    request: Request,
    context: AuthContext = Depends(require_permission("items:manage")),
    db: AsyncSession = Depends(get_db),
):
    await active_unit(db, context, payload.base_unit_id)
    record = await create_record(db, context, request, Item, "item", payload.model_dump())
    await commit_or_conflict(db, f"Code {payload.code} is already in use")
    return record


@router.patch("/items/{record_id}", response_model=ItemOut, dependencies=CSRF)
async def update_item(
    record_id: uuid.UUID,
    payload: ItemUpdate,
    request: Request,
    context: AuthContext = Depends(require_permission("items:manage")),
    db: AsyncSession = Depends(get_db),
):
    record = await get_record(db, Item, context, record_id)
    if payload.base_unit_id is not None and payload.base_unit_id != record.base_unit_id:
        await active_unit(db, context, payload.base_unit_id)
    return await update_record(
        db, context, request, record, "item", payload, frozenset({"description"})
    )


# Warehouses


@router.get("/warehouses", response_model=Page[WarehouseOut])
async def list_warehouses(
    params: dict = Depends(page_params),
    site_id: uuid.UUID | None = None,
    context: AuthContext = Depends(READ),
    db: AsyncSession = Depends(get_db),
):
    filters = []
    if context.site_ids is not None:
        filters.append(Warehouse.site_id.in_(context.site_ids))
    if site_id is not None:
        filters.append(Warehouse.site_id == site_id)
    items, total = await list_page(db, Warehouse, context, **params, filters=tuple(filters))
    return Page[WarehouseOut](items=items, total=total)


@router.post("/warehouses", response_model=WarehouseOut, status_code=201, dependencies=CSRF)
async def create_warehouse(
    payload: WarehouseCreate,
    request: Request,
    context: AuthContext = Depends(require_permission("warehouses:manage")),
    db: AsyncSession = Depends(get_db),
):
    site = await db.scalar(
        select(Site).where(Site.tenant_id == context.tenant.id, Site.id == payload.site_id)
    )
    if site is None or not context.can_access_site(site.id):
        raise HTTPException(status_code=404, detail="Site not found")
    if site.status != "active":
        raise HTTPException(status_code=409, detail="Warehouses can only be added to active sites")
    record = await create_record(
        db, context, request, Warehouse, "warehouse", payload.model_dump()
    )
    await commit_or_conflict(db, f"Code {payload.code} is already in use")
    return record


@router.patch("/warehouses/{record_id}", response_model=WarehouseOut, dependencies=CSRF)
async def update_warehouse(
    record_id: uuid.UUID,
    payload: WarehouseUpdate,
    request: Request,
    context: AuthContext = Depends(require_permission("warehouses:manage")),
    db: AsyncSession = Depends(get_db),
):
    record = await get_record(db, Warehouse, context, record_id)
    return await update_record(db, context, request, record, "warehouse", payload, frozenset())
