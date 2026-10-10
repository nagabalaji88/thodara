"""Fulfillment dependencies per order line (slice F2)."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AuthContext, require_csrf, require_permission
from app.api.masterdata import audit, commit_or_conflict
from app.api.orders import (
    active_item_and_unit,
    get_line,
    get_order,
    order_out,
    plain,
    require_version,
    touch,
)
from app.db.session import get_db
from app.models.orders import (
    OrderLineComponent,
    OrderLineOperation,
    SalesOrder,
    SalesOrderLine,
)
from app.schemas.orders import DependenciesIn, DependencyTemplate, OrderOut
from app.services.fulfillment import allocated_batches, load_dependencies

router = APIRouter(prefix="/orders", tags=["fulfillment dependencies"])
READ = require_permission("orders:read")
PLAN = require_permission("orders:plan")
CSRF = [Depends(require_csrf)]


def summary(
    components: list[OrderLineComponent], operations: list[OrderLineOperation]
) -> dict[str, Any]:
    return {
        "components": [
            {
                "item_id": str(c.item_id),
                "qty_per_unit": plain(c.qty_per_unit),
                "outsourced_operation": c.outsourced_operation,
            }
            for c in sorted(components, key=lambda c: c.position)
        ],
        "operations": [
            {"name": o.name, "kind": o.kind, "duration_minutes": o.duration_minutes}
            for o in sorted(operations, key=lambda o: o.sequence)
        ],
    }


@router.put("/{order_id}/lines/{line_id}/dependencies", response_model=OrderOut, dependencies=CSRF)
async def replace_dependencies(
    order_id: uuid.UUID,
    line_id: uuid.UUID,
    payload: DependenciesIn,
    request: Request,
    context: AuthContext = Depends(PLAN),
    db: AsyncSession = Depends(get_db),
):
    order = await get_order(db, context, order_id)
    require_version(order.version, payload.order_version)
    line = await get_line(db, order, line_id)
    if order.status not in ("draft", "confirmed") or line.status != "open":
        raise HTTPException(
            status_code=409, detail="Dependencies can change only on open lines of active orders"
        )
    item_ids = [c.item_id for c in payload.components]
    if len(set(item_ids)) != len(item_ids):
        raise HTTPException(status_code=422, detail="List each component item once")
    if line.item_id in item_ids:
        raise HTTPException(status_code=422, detail="A line cannot depend on the item it delivers")

    existing = {
        c.item_id: c
        for c in await db.scalars(
            select(OrderLineComponent).where(OrderLineComponent.line_id == line.id)
        )
    }
    old_operations = list(
        await db.scalars(select(OrderLineOperation).where(OrderLineOperation.line_id == line.id))
    )
    before = summary(list(existing.values()), old_operations)
    after = {
        "components": [
            {
                "item_id": str(c.item_id),
                "qty_per_unit": plain(c.qty_per_unit),
                "outsourced_operation": c.outsourced_operation,
            }
            for c in payload.components
        ],
        "operations": [
            {"name": o.name, "kind": o.kind, "duration_minutes": o.duration_minutes}
            for o in payload.operations
        ],
    }
    if after == before:
        return await order_out(db, order)

    removed = [c for item_id, c in existing.items() if item_id not in item_ids]
    linked = await allocated_batches(db, [c.id for c in removed])
    if linked:
        raise HTTPException(
            status_code=409,
            detail="Remove the batch allocations first: " + ", ".join(sorted(linked)),
        )
    for component in removed:
        await db.delete(component)

    components: list[OrderLineComponent] = []
    for position, entry in enumerate(payload.components, start=1):
        component = existing.get(entry.item_id)
        if component is None:
            item, unit = await active_item_and_unit(db, context, entry.item_id)
            component = OrderLineComponent(
                id=uuid.uuid4(),
                tenant_id=context.tenant.id,
                line_id=line.id,
                item_id=item.id,
                unit_id=unit.id,
            )
            db.add(component)
        component.position = position
        component.qty_per_unit = entry.qty_per_unit
        component.outsourced_operation = entry.outsourced_operation
        components.append(component)

    await db.execute(delete(OrderLineOperation).where(OrderLineOperation.line_id == line.id))
    operations = [
        OrderLineOperation(
            id=uuid.uuid4(),
            tenant_id=context.tenant.id,
            line_id=line.id,
            sequence=sequence,
            name=entry.name,
            kind=entry.kind,
            duration_minutes=entry.duration_minutes,
        )
        for sequence, entry in enumerate(payload.operations, start=1)
    ]
    db.add_all(operations)
    touch(order, context)
    audit(
        db,
        context,
        request,
        "orders.dependencies_changed",
        {
            "order_id": str(order.id),
            "number": order.number,
            "line_id": str(line.id),
            "line_no": line.line_no,
            "order_status": order.status,
            "before": before,
            "after": after,
        },
    )
    await commit_or_conflict(db, "These dependencies were changed at the same time; reload")
    return await order_out(db, order)


@router.get("/dependency-template", response_model=DependencyTemplate)
async def dependency_template(
    item_id: uuid.UUID = Query(),
    context: AuthContext = Depends(READ),
    db: AsyncSession = Depends(get_db),
):
    """The dependencies most recently entered for another line delivering this item."""
    query = (
        select(SalesOrderLine, SalesOrder.number)
        .join(SalesOrder, SalesOrder.id == SalesOrderLine.order_id)
        .where(
            SalesOrderLine.tenant_id == context.tenant.id,
            SalesOrderLine.item_id == item_id,
            select(OrderLineComponent.id)
            .where(OrderLineComponent.line_id == SalesOrderLine.id)
            .exists()
            | select(OrderLineOperation.id)
            .where(OrderLineOperation.line_id == SalesOrderLine.id)
            .exists(),
        )
        .order_by(SalesOrder.updated_at.desc(), SalesOrderLine.line_no)
        .limit(1)
    )
    if context.site_ids is not None:
        query = query.where(SalesOrder.site_id.in_(context.site_ids))
    row = (await db.execute(query)).first()
    if row is None:
        return DependencyTemplate(source_order_number=None, components=[], operations=[])
    line, number = row
    components, operations = await load_dependencies(db, [line])
    return DependencyTemplate(
        source_order_number=number,
        components=[c.model_copy(update={"allocations": []}) for c in components[line.id]],
        operations=operations[line.id],
    )
