"""Explainable delivery risk for customer-order lines (slice F6).

Everything here is deterministic. Risk is calculated on read from the current facts (orders,
dependencies, batch allocations, supplier updates, receipts, quality decisions and the site
calendar), so it can never drift from them, and every figure in the result can be traced to one
of those inputs. Missing information is reported as unknown; it never becomes a delay.

How a batch's material is shared: the lines allocated to a batch are served in order of their
promised date (then order number and line), first from accepted material, then from material
awaiting inspection, then from material on quality hold, then from what is still expected from
the supplier. Material the supplier reported as rejected is assumed not to come back usable.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from app.services.calendar import WorkCalendar

ZERO = Decimal(0)

# Most severe first. The headline of a line is the most severe issue it has.
SEVERITY = (
    "confirmed_late",
    "quantity_shortage",
    "at_risk",
    "quality_hold",
    "unknown",
    "on_track",
    "ready",
)


@dataclass
class BatchFacts:
    id: uuid.UUID
    number: str
    supplier_name: str
    status: str  # planned | at_supplier
    quantity: Decimal
    expected_return_date: date
    sent_date: date | None
    received: Decimal = ZERO
    accepted: Decimal = ZERO
    awaiting: Decimal = ZERO
    held: Decimal = ZERO
    reported_completed: Decimal | None = None
    reported_rejected: Decimal | None = None
    # Pieces the supplier's figures do not account for (within tolerance); not assumed to return.
    reported_unaccounted: Decimal | None = None
    reported_at: datetime | None = None
    revised_return_date: date | None = None
    blocker: str | None = None

    @property
    def expected_from_supplier(self) -> Decimal:
        """What may still come back usable from the supplier."""
        if self.status == "planned":
            return self.quantity
        at_supplier = self.quantity - self.received
        missing = max(ZERO, self.reported_unaccounted or ZERO)
        return max(ZERO, at_supplier - (self.reported_rejected or ZERO) - missing)


@dataclass
class AllocationFacts:
    id: uuid.UUID
    batch_id: uuid.UUID
    component_id: uuid.UUID
    quantity: Decimal
    priority: tuple  # (promised date or max, order number, line no)
    order_number: str
    line_no: int


@dataclass
class Share:
    """What one allocation gets from its batch, tier by tier."""

    accepted: Decimal = ZERO
    awaiting: Decimal = ZERO
    held: Decimal = ZERO
    from_supplier: Decimal = ZERO
    short: Decimal = ZERO
    ahead: list[str] = field(default_factory=list)  # lines served first from the same batch


def share_batches(
    batches: dict[uuid.UUID, BatchFacts], allocations: list[AllocationFacts]
) -> dict[uuid.UUID, Share]:
    """Distribute each batch's material over its allocations in priority order."""
    by_batch: dict[uuid.UUID, list[AllocationFacts]] = defaultdict(list)
    for allocation in allocations:
        by_batch[allocation.batch_id].append(allocation)
    shares: dict[uuid.UUID, Share] = {}
    for batch_id, group in by_batch.items():
        batch = batches[batch_id]
        tiers = {
            "accepted": batch.accepted,
            "awaiting": batch.awaiting,
            "held": batch.held,
            "from_supplier": batch.expected_from_supplier,
        }
        served: list[str] = []
        for allocation in sorted(group, key=lambda a: a.priority):
            share = Share(ahead=list(served))
            need = allocation.quantity
            for tier in tiers:
                take = min(need, tiers[tier])
                setattr(share, tier, take)
                tiers[tier] -= take
                need -= take
            share.short = need
            shares[allocation.id] = share
            served.append(f"{allocation.order_number}/{allocation.line_no}")
    return shares


@dataclass
class ComponentFacts:
    id: uuid.UUID
    item_code: str
    unit_code: str
    required: Decimal
    outsourced_operation: str | None
    allocations: list[AllocationFacts]


@dataclass
class LineFacts:
    line_id: uuid.UUID
    order_id: uuid.UUID
    order_number: str
    customer_name: str
    site_id: uuid.UUID
    line_no: int
    item_code: str
    unit_code: str
    remaining: Decimal
    promised_date: date | None
    components: list[ComponentFacts]
    operation_minutes: int
    operation_count: int


@dataclass
class Issue:
    code: str
    message: str


@dataclass
class AllocationView:
    allocation_id: uuid.UUID
    batch_number: str
    batch_id: uuid.UUID
    supplier_name: str
    batch_status: str
    allocated: Decimal
    accepted: Decimal
    awaiting: Decimal
    held: Decimal
    from_supplier: Decimal
    short: Decimal
    estimate_date: date | None
    estimate_source: str | None
    last_update_at: datetime | None
    stale: bool
    ahead: list[str]
    # Reported complete by the supplier but not yet received at our gate.
    ready_to_collect: Decimal = ZERO


@dataclass
class ComponentView:
    component_id: uuid.UUID
    item_code: str
    unit_code: str
    required: Decimal
    outsourced_operation: str | None
    uncovered: Decimal
    usable_now: Decimal
    allocations: list[AllocationView]


@dataclass
class LineRisk:
    line_id: uuid.UUID
    order_id: uuid.UUID
    order_number: str
    customer_name: str
    line_no: int
    item_code: str
    unit_code: str
    remaining: Decimal
    promised_date: date | None
    headline: str
    issues: list[Issue]
    components_ready_date: date | None
    projected_finish: datetime | None
    projected_date: date | None
    slack_days: int | None
    operation_minutes: int
    components: list[ComponentView]
    notes: list[str]
    time_zone: str | None


def _fmt(quantity: Decimal) -> str:
    return format(quantity.normalize(), "f")


def _age(moment: datetime, now: datetime) -> str:
    hours = int((now - moment).total_seconds() // 3600)
    return f"{hours} h" if hours < 48 else f"{hours // 24} days"


def assess_line(
    line: LineFacts,
    batches: dict[uuid.UUID, BatchFacts],
    shares: dict[uuid.UUID, Share],
    calendar: WorkCalendar | None,
    now: datetime,
    stale_after: timedelta,
) -> LineRisk:
    tz = calendar.time_zone if calendar else UTC
    today = now.astimezone(tz).date()
    issues: list[Issue] = []
    unknown_date = False
    ready_dates: list[date] = []
    views: list[ComponentView] = []
    notes: list[str] = []

    if not line.components and not line.operation_count:
        issues.append(Issue("unknown", "No components or remaining work recorded for this line."))

    for component in line.components:
        allocated = sum((a.quantity for a in component.allocations), ZERO)
        uncovered = max(ZERO, component.required - allocated)
        allocation_views = []
        usable_now = ZERO
        for allocation in component.allocations:
            batch = batches[allocation.batch_id]
            share = shares[allocation.id]
            usable_now += share.accepted
            estimate, source, stale = None, None, False
            if share.from_supplier > 0:
                if batch.status == "planned":
                    estimate, source = batch.expected_return_date, "planned return; not sent yet"
                elif batch.revised_return_date:
                    estimate = batch.revised_return_date
                    source = "supplier's revised date (entered by staff, not confirmed)"
                else:
                    estimate, source = batch.expected_return_date, "planned return date"
                if batch.status == "at_supplier":
                    last = batch.reported_at or (
                        datetime.combine(batch.sent_date, time.min, tz) if batch.sent_date else None
                    )
                    if last is not None and now - last > stale_after:
                        stale = True
                        heard = (
                            f"last supplier update {_age(batch.reported_at, now)} ago"
                            if batch.reported_at
                            else f"no supplier update since it was sent on {batch.sent_date}"
                        )
                        issues.append(
                            Issue(
                                "unknown",
                                f"{batch.number} ({batch.supplier_name}): {heard}. "
                                "Its status is unknown, not late.",
                            )
                        )
                if estimate < today:
                    issues.append(
                        Issue(
                            "unknown",
                            f"{batch.number} was expected back by {estimate} but "
                            f"{_fmt(share.from_supplier)} {component.unit_code} for this line "
                            "has not arrived. Ask the supplier for a new date.",
                        )
                    )
                    unknown_date = True
                else:
                    ready_dates.append(estimate)
                if batch.blocker:
                    # Evidence for a person to judge; free text never classifies a line.
                    notes.append(
                        f"{batch.number} blocker reported by the supplier: {batch.blocker}"
                    )
            if share.held > 0:
                issues.append(
                    Issue(
                        "quality_hold",
                        f"{_fmt(share.held)} {component.unit_code} {component.item_code} for this "
                        f"line is on quality hold in {batch.number}; it is not usable until "
                        "released.",
                    )
                )
            if share.short > 0:
                issues.append(
                    Issue(
                        "quantity_shortage",
                        f"{batch.number} is expected to deliver only "
                        f"{_fmt(allocation.quantity - share.short)} of the "
                        f"{_fmt(allocation.quantity)} {component.unit_code} linked to this line"
                        + (f", after {', '.join(share.ahead)}" if share.ahead else "")
                        + " (supplier-reported rejections and our inspection results counted).",
                    )
                )
            allocation_views.append(
                AllocationView(
                    allocation_id=allocation.id,
                    batch_number=batch.number,
                    batch_id=batch.id,
                    supplier_name=batch.supplier_name,
                    batch_status=batch.status,
                    allocated=allocation.quantity,
                    accepted=share.accepted,
                    awaiting=share.awaiting,
                    held=share.held,
                    from_supplier=share.from_supplier,
                    short=share.short,
                    estimate_date=estimate,
                    estimate_source=source,
                    last_update_at=batch.reported_at,
                    stale=stale,
                    ahead=share.ahead,
                    ready_to_collect=max(ZERO, (batch.reported_completed or ZERO) - batch.received)
                    if batch.status == "at_supplier"
                    else ZERO,
                )
            )
        if uncovered > 0 and (component.outsourced_operation or component.allocations):
            issues.append(
                Issue(
                    "quantity_shortage",
                    f"{_fmt(uncovered)} {component.unit_code} {component.item_code} needed "
                    f"for {component.outsourced_operation or 'this line'} is not covered by "
                    "any outsourced batch.",
                )
            )
        views.append(
            ComponentView(
                component_id=component.id,
                item_code=component.item_code,
                unit_code=component.unit_code,
                required=component.required,
                outsourced_operation=component.outsourced_operation,
                uncovered=uncovered
                if (component.outsourced_operation or component.allocations)
                else ZERO,
                usable_now=usable_now,
                allocations=allocation_views,
            )
        )

    components_ready = max(ready_dates) if ready_dates else today
    if unknown_date:
        components_ready = None
    finish: datetime | None = None
    if calendar is None:
        issues.append(
            Issue(
                "unknown",
                "The fulfilling site has no working calendar, so the remaining work cannot be "
                "scheduled. Set one under Company & sites.",
            )
        )
    elif components_ready is not None and (line.components or line.operation_count):
        start = (
            now
            if components_ready <= today
            else datetime.combine(components_ready, time.min, calendar.time_zone)
        )
        finish = calendar.add_working_minutes(start, line.operation_minutes)
    projected = finish.astimezone(calendar.time_zone).date() if finish and calendar else None

    slack = None
    if line.promised_date is not None:
        if today > line.promised_date:
            issues.append(
                Issue(
                    "confirmed_late",
                    f"The promised date {line.promised_date} has passed and "
                    f"{_fmt(line.remaining)} {line.unit_code} is still open.",
                )
            )
        if projected is not None:
            slack = (line.promised_date - projected).days
            if slack < 0 and today <= line.promised_date:
                issues.append(
                    Issue(
                        "at_risk",
                        f"Projected ready {projected}, {-slack} day(s) after the promised "
                        f"{line.promised_date}.",
                    )
                )

    codes = {issue.code for issue in issues}
    outsourced = [v for v in views if v.allocations or v.outsourced_operation]
    if codes:
        headline = min(codes, key=SEVERITY.index)
    elif outsourced and all(v.usable_now >= v.required for v in outsourced):
        # Every outsourced component this line needs is accepted and usable now.
        headline = "ready"
    else:
        headline = "on_track"
    return LineRisk(
        line_id=line.line_id,
        order_id=line.order_id,
        order_number=line.order_number,
        customer_name=line.customer_name,
        line_no=line.line_no,
        item_code=line.item_code,
        unit_code=line.unit_code,
        remaining=line.remaining,
        promised_date=line.promised_date,
        headline=headline,
        issues=sorted(issues, key=lambda i: SEVERITY.index(i.code)),
        components_ready_date=components_ready,
        projected_finish=finish,
        projected_date=projected,
        slack_days=slack,
        operation_minutes=line.operation_minutes,
        components=views,
        notes=notes,
        time_zone=calendar.time_zone.key if calendar else None,
    )
