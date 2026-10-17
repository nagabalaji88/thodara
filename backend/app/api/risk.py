"""Explainable delivery risk (slice F6) and its company settings."""

import uuid
from collections import Counter
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AuthContext, require_csrf, require_permission
from app.api.masterdata import STALE, audit, commit_or_conflict
from app.api.orders import get_order
from app.db.session import get_db
from app.models.organization import DEFAULT_STALE_HOURS, FulfillmentSettings
from app.schemas.risk import (
    FulfillmentSettingsIn,
    FulfillmentSettingsOut,
    LineRiskOut,
    RiskReport,
    SuggestionOut,
)
from app.services.risk import SEVERITY
from app.services.risk_loader import assess_lines, stale_hours
from app.services.suggestions import suggest

router = APIRouter(tags=["delivery risk"])
READ = require_permission("orders:read")
CONFIGURE = require_permission("tenant:configure")
WORKSPACE = require_permission("workspace:read")


async def report(db: AsyncSession, context: AuthContext, order_id: uuid.UUID | None, headline):
    now = datetime.now(UTC)
    lines = await assess_lines(db, context.tenant.id, context.site_ids, order_id, now)
    counts = Counter(line.headline for line in lines)
    if headline:
        lines = [line for line in lines if line.headline == headline]
    lines.sort(key=lambda r: (SEVERITY.index(r.headline), r.promised_date or datetime.max.date()))
    return RiskReport(
        computed_at=now,
        stale_after_hours=await stale_hours(db, context.tenant.id),
        counts={code: counts.get(code, 0) for code in SEVERITY},
        lines=[
            LineRiskOut.model_validate(line).model_copy(
                update={"suggestions": [SuggestionOut.model_validate(x) for x in suggest(line)]}
            )
            for line in lines
        ],
    )


@router.get("/fulfillment/risk", response_model=RiskReport)
async def risk_board(
    headline: str | None = Query(default=None, pattern="^(" + "|".join(SEVERITY) + ")$"),
    context: AuthContext = Depends(READ),
    db: AsyncSession = Depends(get_db),
):
    """Every open line of a confirmed order at the user's sites, most severe first."""
    return await report(db, context, None, headline)


@router.get("/orders/{order_id}/risk", response_model=RiskReport)
async def order_risk(
    order_id: uuid.UUID,
    context: AuthContext = Depends(READ),
    db: AsyncSession = Depends(get_db),
):
    order = await get_order(db, context, order_id)
    return await report(db, context, order.id, None)


async def settings_out(db: AsyncSession, tenant_id: uuid.UUID) -> FulfillmentSettingsOut:
    row = await db.scalar(
        select(FulfillmentSettings).where(FulfillmentSettings.tenant_id == tenant_id)
    )
    if row is None:
        return FulfillmentSettingsOut(
            supplier_update_stale_hours=DEFAULT_STALE_HOURS, is_default=True, version=None
        )
    return FulfillmentSettingsOut(
        supplier_update_stale_hours=row.supplier_update_stale_hours,
        is_default=False,
        version=row.version,
    )


@router.get("/fulfillment/settings", response_model=FulfillmentSettingsOut)
async def read_settings(
    context: AuthContext = Depends(WORKSPACE), db: AsyncSession = Depends(get_db)
):
    return await settings_out(db, context.tenant.id)


@router.put(
    "/fulfillment/settings",
    response_model=FulfillmentSettingsOut,
    dependencies=[Depends(require_csrf)],
)
async def save_settings(
    payload: FulfillmentSettingsIn,
    request: Request,
    context: AuthContext = Depends(CONFIGURE),
    db: AsyncSession = Depends(get_db),
):
    row = await db.scalar(
        select(FulfillmentSettings).where(FulfillmentSettings.tenant_id == context.tenant.id)
    )
    if (row is None) != (payload.version is None) or (row and row.version != payload.version):
        raise HTTPException(status_code=409, detail=STALE)
    before = row.supplier_update_stale_hours if row else DEFAULT_STALE_HOURS
    if row is None:
        row = FulfillmentSettings(id=uuid.uuid4(), tenant_id=context.tenant.id)
        db.add(row)
    row.supplier_update_stale_hours = payload.supplier_update_stale_hours
    audit(
        db,
        context,
        request,
        "fulfillment.settings_changed",
        {
            "before": {"supplier_update_stale_hours": before},
            "after": {"supplier_update_stale_hours": payload.supplier_update_stale_hours},
        },
    )
    await commit_or_conflict(db, STALE)
    return await settings_out(db, context.tenant.id)
