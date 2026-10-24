"""First operational reports for the fulfillment release (slice F8).

Every figure has a written definition returned with it, is limited to the sites the user can
access, and is calculated when requested (the response says when).
"""

import statistics
import uuid
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AuthContext, require_permission
from app.db.session import get_db
from app.models.actions import RecoveryAction
from app.models.dispatch import DispatchLine, DispatchNote
from app.models.identity import Site
from app.models.masterdata import Customer, Supplier
from app.models.orders import OrderLineComponent, SalesOrder, SalesOrderLine
from app.models.outsourcing import BatchAllocation, OutsourcedBatch
from app.services.fulfillment import current_updates
from app.services.risk import SEVERITY
from app.services.risk_loader import assess_lines, stale_hours

router = APIRouter(prefix="/reports", tags=["reports"])
READ = require_permission("orders:read")

DEFINITIONS = {
    "on_time_rate": "Dispatched order lines whose dispatch date was on or before the promised "
    "date in force when they shipped, divided by dispatched lines that had a promise. Cancelled "
    "dispatch notes are excluded. One line shipped in two notes counts twice.",
    "days_late": "For late dispatch lines: dispatch date minus promised date, in calendar days.",
    "open_risk": "Open lines of confirmed orders by their current delivery-risk headline "
    "(ADR-0006), calculated now.",
    "stale_updates": "Batches at a supplier whose latest supplier update (or, with none, the date "
    "sent) is older than the company's stale threshold.",
    "action_age": "Open actions by time since they were raised.",
    "time_to_close": "For actions closed in the period: hours from raised to closed (median).",
    "early_warning": "For order lines dispatched in the period that had recovery actions: days "
    "between the first action being raised and the promised date. Higher is earlier; negative "
    "means the team first acted after the promise had passed.",
}


class Bucket(BaseModel):
    label: str
    count: int


class CustomerDelivery(BaseModel):
    customer_name: str
    lines: int
    on_time: int
    late: int


class DeliveryReport(BaseModel):
    dispatch_lines: int
    with_promise: int
    on_time: int
    late: int
    on_time_rate: float | None
    average_days_late: float | None
    by_customer: list[CustomerDelivery]


class StaleBatch(BaseModel):
    batch_id: uuid.UUID
    number: str
    supplier_name: str
    sent_date: date | None
    last_update_at: datetime | None
    hours_since: int
    orders_waiting: int


class ActionReport(BaseModel):
    open: int
    overdue: int
    awaiting_approval: int
    age: list[Bucket]
    closed_in_period: int
    median_hours_to_close: float | None
    outcomes: dict[str, int]


class EarlyWarning(BaseModel):
    lines_with_actions: int
    average_days_ahead: float | None
    acted_after_promise: int


class FulfillmentReport(BaseModel):
    computed_at: datetime
    date_from: date
    date_to: date
    time_zone: str
    stale_after_hours: int
    delivery: DeliveryReport
    open_risk: dict[str, int]
    stale_batches: list[StaleBatch]
    actions: ActionReport
    early_warning: EarlyWarning
    definitions: dict[str, str]


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@router.get("/fulfillment", response_model=FulfillmentReport)
async def fulfillment_report(
    date_from: date | None = None,
    date_to: date | None = None,
    context: AuthContext = Depends(READ),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(UTC)
    sites = select(Site).where(Site.tenant_id == context.tenant.id).order_by(Site.created_at)
    if context.site_ids is not None:
        sites = sites.where(Site.id.in_(context.site_ids))
    first_site = await db.scalar(sites.limit(1))
    zone_name = first_site.time_zone if first_site else "UTC"
    zone = ZoneInfo(zone_name)
    today = now.astimezone(zone).date()
    date_to = date_to or today
    date_from = date_from or date_to - timedelta(days=29)
    if date_from > date_to or (date_to - date_from).days > 366:
        raise HTTPException(status_code=422, detail="Choose a period of up to a year")
    period_start = datetime.combine(date_from, time.min, zone)
    period_end = datetime.combine(date_to + timedelta(days=1), time.min, zone)

    def scoped(query, column):
        return query.where(column.in_(context.site_ids)) if context.site_ids is not None else query

    # Delivery performance -----------------------------------------------------------
    shipped = (
        await db.execute(
            scoped(
                select(DispatchLine, DispatchNote, Customer.name)
                .join(DispatchNote, DispatchNote.id == DispatchLine.dispatch_id)
                .join(SalesOrder, SalesOrder.id == DispatchNote.order_id)
                .join(Customer, Customer.id == SalesOrder.customer_id)
                .where(
                    DispatchNote.tenant_id == context.tenant.id,
                    DispatchNote.status == "posted",
                    DispatchNote.dispatch_date >= date_from,
                    DispatchNote.dispatch_date <= date_to,
                ),
                DispatchNote.site_id,
            )
        )
    ).all()
    per_customer: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    late_days = []
    for line, note, customer in shipped:
        row = per_customer[customer]
        row[0] += 1
        if line.on_time is True:
            row[1] += 1
        elif line.on_time is False:
            row[2] += 1
            late_days.append((note.dispatch_date - line.promised_date).days)
    on_time = sum(1 for line, _, _ in shipped if line.on_time is True)
    late = sum(1 for line, _, _ in shipped if line.on_time is False)
    delivery = DeliveryReport(
        dispatch_lines=len(shipped),
        with_promise=on_time + late,
        on_time=on_time,
        late=late,
        on_time_rate=round(on_time / (on_time + late), 4) if on_time + late else None,
        average_days_late=round(statistics.mean(late_days), 1) if late_days else None,
        by_customer=[
            CustomerDelivery(customer_name=name, lines=v[0], on_time=v[1], late=v[2])
            for name, v in sorted(per_customer.items())
        ],
    )

    # Current risk and stale suppliers ---------------------------------------------------
    risks = await assess_lines(db, context.tenant.id, context.site_ids, None, now)
    counts = Counter(r.headline for r in risks)
    threshold = await stale_hours(db, context.tenant.id)
    batches = (
        await db.execute(
            scoped(
                select(OutsourcedBatch, Supplier.name)
                .join(Supplier, Supplier.id == OutsourcedBatch.supplier_id)
                .where(
                    OutsourcedBatch.tenant_id == context.tenant.id,
                    OutsourcedBatch.status == "at_supplier",
                ),
                OutsourcedBatch.site_id,
            )
        )
    ).all()
    latest = await current_updates(db, [b.id for b, _ in batches])
    stale = []
    for batch, supplier in batches:
        report = latest.get(batch.id)
        last = as_utc(report.reported_at) if report else None
        since = last or (
            datetime.combine(batch.sent_date, time.min, zone) if batch.sent_date else now
        )
        hours = int((now - since).total_seconds() // 3600)
        if hours <= threshold:
            continue
        waiting = len(
            set(
                await db.scalars(
                    select(SalesOrderLine.order_id)
                    .join(OrderLineComponent, OrderLineComponent.line_id == SalesOrderLine.id)
                    .join(BatchAllocation, BatchAllocation.component_id == OrderLineComponent.id)
                    .where(
                        BatchAllocation.batch_id == batch.id,
                        BatchAllocation.quantity > BatchAllocation.consumed_qty,
                    )
                )
            )
        )
        stale.append(
            StaleBatch(
                batch_id=batch.id,
                number=batch.number,
                supplier_name=supplier,
                sent_date=batch.sent_date,
                last_update_at=last,
                hours_since=hours,
                orders_waiting=waiting,
            )
        )
    stale.sort(key=lambda s: -s.hours_since)

    # Actions --------------------------------------------------------------------------
    actions = list(
        await db.scalars(
            scoped(
                select(RecoveryAction).where(RecoveryAction.tenant_id == context.tenant.id),
                RecoveryAction.site_id,
            )
        )
    )
    active = [a for a in actions if a.status in ("open", "awaiting_approval")]
    buckets = Counter()
    for a in active:
        age = (now - as_utc(a.created_at)).total_seconds() / 86400
        label = (
            "under 1 day"
            if age < 1
            else "1–3 days"
            if age < 3
            else "3–7 days"
            if age < 7
            else "over 7 days"
        )
        buckets[label] += 1
    closed = [
        a for a in actions if a.closed_at and period_start <= as_utc(a.closed_at) < period_end
    ]
    hours_to_close = [
        (as_utc(a.closed_at) - as_utc(a.created_at)).total_seconds() / 3600 for a in closed
    ]
    action_report = ActionReport(
        open=len(active),
        overdue=sum(1 for a in active if as_utc(a.due_at) < now),
        awaiting_approval=sum(1 for a in active if a.status == "awaiting_approval"),
        age=[
            Bucket(label=label, count=buckets[label])
            for label in ("under 1 day", "1–3 days", "3–7 days", "over 7 days")
        ],
        closed_in_period=len(closed),
        median_hours_to_close=round(statistics.median(hours_to_close), 1)
        if hours_to_close
        else None,
        outcomes=dict(Counter(a.outcome or a.status for a in closed)),
    )

    # Early warning ----------------------------------------------------------------------
    first_action: dict[uuid.UUID, datetime] = {}
    for a in actions:
        if a.line_id and (
            a.line_id not in first_action or as_utc(a.created_at) < first_action[a.line_id]
        ):
            first_action[a.line_id] = as_utc(a.created_at)
    ahead = []
    seen: set[uuid.UUID] = set()
    for line, _, _ in shipped:
        if line.line_id in seen or line.line_id not in first_action or not line.promised_date:
            continue
        seen.add(line.line_id)
        ahead.append((line.promised_date - first_action[line.line_id].astimezone(zone).date()).days)
    early = EarlyWarning(
        lines_with_actions=len(ahead),
        average_days_ahead=round(statistics.mean(ahead), 1) if ahead else None,
        acted_after_promise=sum(1 for d in ahead if d < 0),
    )

    return FulfillmentReport(
        computed_at=now,
        date_from=date_from,
        date_to=date_to,
        time_zone=zone_name,
        stale_after_hours=threshold,
        delivery=delivery,
        open_risk={code: counts.get(code, 0) for code in SEVERITY},
        stale_batches=stale,
        actions=action_report,
        early_warning=early,
        definitions=DEFINITIONS,
    )
