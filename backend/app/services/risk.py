"""Explainable delivery risk for customer-order lines (slice F6).

Everything here is deterministic. Risk is calculated on read from the current facts (orders,
dependencies, batch allocations, supplier updates, receipts, quality decisions and the site
calendar), so it can never drift from them, and every figure in the result can be traced to one
of those inputs. Missing information is reported as unknown; it never becomes a delay.

How a batch's material is shared: the lines allocated to a batch are served in order of their
promised date (then order number and line), first from accepted material, then from material
awaiting inspection, then from material on quality hold, then from what is still expected from
the supplier. Material the supplier reported as rejected is assumed not to come back usable.

How stock is shared (G2, ADR-0010): stock is not reserved. A site's finished-goods stock of an
item covers open lines in promised-date order first; what is left of each line must be built,
and components with no outsourced step are then covered from the site's component stock in the
same order. Items with no posted stock at a site are not tracked there and are assumed
available, as before.
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
class StockDemand:
    """One claim on a site's stock of an item: a line's finished goods or one of its components."""

    key: uuid.UUID  # line id for finished goods, component id for components
    site_id: uuid.UUID
    item_id: uuid.UUID
    quantity: Decimal
    priority: tuple  # (promised date or max, order number, line no)
    label: str


@dataclass
class StockShare:
    covered: Decimal = ZERO
    ahead: list[str] = field(default_factory=list)  # lines served first from the same stock


def share_stock(
    pools: dict[tuple[uuid.UUID, uuid.UUID], Decimal], demands: list[StockDemand]
) -> tuple[dict[uuid.UUID, StockShare], dict[tuple[uuid.UUID, uuid.UUID], Decimal]]:
    """Serve each claim from its site's stock in priority order. Returns shares and what is left.

    Claims on untracked items (no pool) get no share at all, which means "not tracked".
    """
    left = dict(pools)
    served: dict[tuple[uuid.UUID, uuid.UUID], list[str]] = defaultdict(list)
    shares: dict[uuid.UUID, StockShare] = {}
    for demand in sorted(demands, key=lambda d: d.priority):
        place = (demand.site_id, demand.item_id)
        if place not in left:
            continue
        take = min(demand.quantity, left[place])
        left[place] -= take
        shares[demand.key] = StockShare(covered=take, ahead=list(served[place]))
        if demand.quantity > 0:
            served[place].append(demand.label)
    return shares, left


@dataclass
class ComponentFacts:
    id: uuid.UUID
    item_code: str
    unit_code: str
    required: Decimal
    outsourced_operation: str | None
    allocations: list[AllocationFacts]
    # Components without an outsourced step are covered from site stock when tracked (G2).
    stock_tracked: bool = False
    in_stock: Decimal = ZERO
    stock_ahead: list[str] = field(default_factory=list)


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
    # Finished-goods stock of the line's item that covers part of the line (G2).
    stock_tracked: bool = False
    from_stock: Decimal = ZERO
    stock_ahead: list[str] = field(default_factory=list)
    transport_minutes: int = 0


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
    stock_tracked: bool = False
    in_stock: Decimal = ZERO
    stock_ahead: list[str] = field(default_factory=list)


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
    stock_tracked: bool = False
    from_stock: Decimal = ZERO
    stock_ahead: list[str] = field(default_factory=list)


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

    # Everything still open can ship from finished-goods stock: only transport remains.
    all_from_stock = line.stock_tracked and line.remaining > 0 and line.from_stock >= line.remaining
    if line.stock_tracked and line.from_stock > 0:
        notes.append(
            f"{_fmt(line.from_stock)} {line.unit_code} of this line comes from finished-goods "
            "stock" + (f", after {', '.join(line.stock_ahead)}" if line.stock_ahead else "") + "."
        )
    if not line.components and not line.operation_count and not all_from_stock:
        issues.append(Issue("unknown", "No components or remaining work recorded for this line."))

    for component in line.components:
        if component.required <= 0:
            # Nothing of this component is needed: finished-goods stock covers the line.
            views.append(
                ComponentView(
                    component_id=component.id,
                    item_code=component.item_code,
                    unit_code=component.unit_code,
                    required=ZERO,
                    outsourced_operation=component.outsourced_operation,
                    uncovered=ZERO,
                    usable_now=ZERO,
                    allocations=[],
                    stock_tracked=component.stock_tracked,
                )
            )
            continue
        if component.stock_tracked:
            if component.in_stock < component.required:
                issues.append(
                    Issue(
                        "quantity_shortage",
                        f"Only {_fmt(component.in_stock)} of the {_fmt(component.required)} "
                        f"{component.unit_code} {component.item_code} this line needs is in "
                        "stock at the site"
                        + (
                            f", after {', '.join(component.stock_ahead)}"
                            if component.stock_ahead
                            else ""
                        )
                        + ".",
                    )
                )
            views.append(
                ComponentView(
                    component_id=component.id,
                    item_code=component.item_code,
                    unit_code=component.unit_code,
                    required=component.required,
                    outsourced_operation=None,
                    uncovered=ZERO,
                    usable_now=component.in_stock,
                    allocations=[],
                    stock_tracked=True,
                    in_stock=component.in_stock,
                    stock_ahead=component.stock_ahead,
                )
            )
            continue
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
    elif components_ready is not None and (
        line.components or line.operation_count or all_from_stock
    ):
        start = (
            now
            if components_ready <= today
            else datetime.combine(components_ready, time.min, calendar.time_zone)
        )
        minutes = line.transport_minutes if all_from_stock else line.operation_minutes
        finish = calendar.add_working_minutes(start, minutes)
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
    tracked = [v for v in views if v.allocations or v.outsourced_operation or v.stock_tracked]
    if codes:
        headline = min(codes, key=SEVERITY.index)
    elif all_from_stock or (tracked and all(v.usable_now >= v.required for v in tracked)):
        # Finished goods cover the line, or every tracked component is usable now.
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
        stock_tracked=line.stock_tracked,
        from_stock=line.from_stock if line.stock_tracked else ZERO,
        stock_ahead=line.stock_ahead,
    )
