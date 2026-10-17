"""Slice F6: the delivery-risk rules, on hand-built facts with a fixed clock."""

import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.services.calendar import WorkCalendar
from app.services.risk import (
    AllocationFacts,
    BatchFacts,
    ComponentFacts,
    LineFacts,
    assess_line,
    share_batches,
)

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 20, 10, 0, tzinfo=IST)  # a Tuesday
STALE = timedelta(hours=48)
# Monday to Saturday, 09:00-17:00: eight working hours a day.
CAL = WorkCalendar(frozenset(range(1, 7)), time(9), time(17), frozenset(), IST)
D = Decimal


def batch(**overrides) -> BatchFacts:
    values = dict(
        id=uuid.uuid4(),
        number="OB-00001",
        supplier_name="Hosur Coaters",
        status="at_supplier",
        quantity=D(200),
        expected_return_date=date(2026, 10, 26),
        sent_date=date(2026, 10, 15),
    )
    values.update(overrides)
    return BatchFacts(**values)


def allocation(b: BatchFacts, qty: str, promised: date, number: str) -> AllocationFacts:
    return AllocationFacts(
        id=uuid.uuid4(),
        batch_id=b.id,
        component_id=uuid.uuid4(),
        quantity=D(qty),
        priority=(promised, number, 1),
        order_number=number,
        line_no=1,
    )


def line(
    allocations: list[AllocationFacts],
    required: str,
    promised: date,
    minutes: int = 18 * 60,
    operation: str | None = "Powder coating",
) -> LineFacts:
    return LineFacts(
        line_id=uuid.uuid4(),
        order_id=uuid.uuid4(),
        order_number=allocations[0].order_number if allocations else "SO-00009",
        customer_name="Agri Irrigation",
        site_id=uuid.uuid4(),
        line_no=1,
        item_code="PMP-5HP",
        unit_code="PCS",
        remaining=D(required),
        promised_date=promised,
        components=[
            ComponentFacts(
                id=uuid.uuid4(),
                item_code="HSG-CAST",
                unit_code="PCS",
                required=D(required),
                outsourced_operation=operation,
                allocations=allocations,
            )
        ],
        operation_minutes=minutes,
        operation_count=3 if minutes else 0,
    )


def assess(facts: LineFacts, batches: list[BatchFacts], calendar=CAL, now=NOW):
    allocations = [a for b in batches for a in all_allocations[b.id]]
    shares = share_batches({b.id: b for b in batches}, allocations)
    return assess_line(facts, {b.id: b for b in batches}, shares, calendar, now, STALE)


all_allocations: dict[uuid.UUID, list[AllocationFacts]] = {}


def linked(b: BatchFacts, *allocs: AllocationFacts) -> None:
    all_allocations[b.id] = list(allocs)


def reported(b: BatchFacts, rejected: str, hours_ago: int, revised: date | None) -> BatchFacts:
    b.reported_rejected = D(rejected)
    b.reported_at = NOW - timedelta(hours=hours_ago)
    b.revised_return_date = revised
    return b


def codes(risk) -> list[str]:
    return [i.code for i in risk.issues]


def test_acceptance_scenario_120_done_20_rejected_60_pending_is_on_track() -> None:
    b = reported(batch(), "20", hours_ago=22, revised=date(2026, 10, 28))
    first = allocation(b, "40", date(2026, 11, 3), "SO-00001")
    second = allocation(b, "60", date(2026, 11, 10), "SO-00002")
    linked(b, first, second)

    risk = assess(line([first], "40", date(2026, 11, 3)), [b])

    [component] = risk.components
    [share] = component.allocations
    # Nothing is usable yet: the 120 completed are still at the supplier.
    assert (component.usable_now, share.from_supplier, share.short) == (0, 40, 0)
    assert share.estimate_date == date(2026, 10, 28)
    assert "revised date" in share.estimate_source
    # 18 working hours from Wed 28 Oct 09:00 on an 8-hour day finish Fri 30 Oct 11:00.
    assert risk.projected_finish == datetime(2026, 10, 30, 11, 0, tzinfo=IST)
    assert (risk.projected_date, risk.slack_days, risk.headline) == (
        date(2026, 10, 30),
        4,
        "on_track",
    )


def test_a_tight_promise_is_at_risk_with_the_calculation_shown() -> None:
    b = reported(batch(), "20", hours_ago=22, revised=date(2026, 10, 28))
    a = allocation(b, "40", date(2026, 10, 29), "SO-00001")
    linked(b, a)

    risk = assess(line([a], "40", date(2026, 10, 29)), [b])

    assert (risk.headline, risk.slack_days) == ("at_risk", -1)
    assert "Projected ready 2026-10-30, 1 day(s) after the promised 2026-10-29" in (
        risk.issues[0].message
    )


def test_rejections_make_the_later_promise_short_not_the_earlier_one() -> None:
    b = reported(batch(quantity=D(100)), "30", hours_ago=5, revised=None)
    early = allocation(b, "40", date(2026, 11, 3), "SO-00001")
    late = allocation(b, "60", date(2026, 11, 10), "SO-00002")
    linked(b, early, late)

    first = assess(line([early], "40", date(2026, 11, 3)), [b])
    second = assess(line([late], "60", date(2026, 11, 10)), [b])

    assert first.headline == "on_track"
    assert second.headline == "quantity_shortage"
    [share] = second.components[0].allocations
    assert (share.from_supplier, share.short, share.ahead) == (30, 30, ["SO-00001/1"])
    assert "only 30 of the 60 PCS" in second.issues[0].message
    assert "after SO-00001/1" in second.issues[0].message


def test_accepted_material_goes_to_the_earliest_promise_first() -> None:
    b = batch(received=D(50), accepted=D(50))
    b = reported(b, "0", hours_ago=5, revised=None)
    early = allocation(b, "40", date(2026, 11, 3), "SO-00001")
    late = allocation(b, "60", date(2026, 11, 10), "SO-00002")
    linked(b, early, late)

    first = assess(line([early], "40", date(2026, 11, 3)), [b])
    second = assess(line([late], "60", date(2026, 11, 10)), [b])

    assert (first.headline, first.components[0].usable_now) == ("ready", 40)
    assert first.components_ready_date == NOW.date()
    [share] = second.components[0].allocations
    assert (share.accepted, share.from_supplier) == (10, 50)


def test_material_on_quality_hold_is_flagged_not_counted_as_usable() -> None:
    b = batch(received=D(100), accepted=D(30), held=D(70))
    b = reported(b, "0", hours_ago=5, revised=None)
    a = allocation(b, "40", date(2026, 11, 3), "SO-00001")
    linked(b, a)

    risk = assess(line([a], "40", date(2026, 11, 3)), [b])

    assert risk.headline == "quality_hold"
    assert (risk.components[0].usable_now, risk.components[0].allocations[0].held) == (30, 10)


def test_missing_or_old_supplier_news_is_unknown_never_late() -> None:
    old = reported(batch(), "0", hours_ago=72, revised=date(2026, 10, 28))
    silent = batch(number="OB-00002", sent_date=date(2026, 10, 10))
    a = allocation(old, "40", date(2026, 11, 3), "SO-00001")
    b = allocation(silent, "40", date(2026, 11, 3), "SO-00002")
    linked(old, a)
    linked(silent, b)

    stale = assess(line([a], "40", date(2026, 11, 3)), [old])
    never = assess(line([b], "40", date(2026, 11, 3)), [silent])

    assert stale.headline == never.headline == "unknown"
    assert "last supplier update 3 days ago" in stale.issues[0].message
    assert "no supplier update since it was sent on 2026-10-10" in never.issues[0].message
    assert "not late" in stale.issues[0].message
    # A date is still projected from what is known; it is simply not trusted yet.
    assert stale.projected_date == date(2026, 10, 30)
    fresh = assess(line([a], "40", date(2026, 11, 3)), [old], now=NOW - timedelta(hours=30))
    assert fresh.headline == "on_track"


def test_an_expected_date_that_has_passed_leaves_the_projection_unknown() -> None:
    b = reported(batch(), "0", hours_ago=5, revised=date(2026, 10, 18))
    a = allocation(b, "40", date(2026, 11, 3), "SO-00001")
    linked(b, a)

    risk = assess(line([a], "40", date(2026, 11, 3)), [b])

    assert (risk.headline, risk.projected_date, risk.components_ready_date) == (
        "unknown",
        None,
        None,
    )
    assert "expected back by 2026-10-18" in risk.issues[0].message


def test_no_calendar_no_dependencies_and_uncovered_need() -> None:
    b = reported(batch(), "0", hours_ago=5, revised=None)
    a = allocation(b, "40", date(2026, 11, 3), "SO-00001")
    linked(b, a)
    assert assess(line([a], "40", date(2026, 11, 3)), [b], calendar=None).headline == "unknown"

    bare = line([], "40", date(2026, 11, 3), minutes=0)
    bare.components = []
    nothing = assess(bare, [])
    assert "No components or remaining work" in nothing.issues[0].message
    assert (nothing.projected_date, nothing.slack_days) == (None, None)  # no made-up date

    uncovered = assess(line([], "40", date(2026, 11, 3)), [])
    assert uncovered.headline == "quantity_shortage"
    assert "40 PCS HSG-CAST needed for Powder coating is not covered" in uncovered.issues[0].message


def test_a_passed_promise_is_confirmed_late_and_outranks_everything() -> None:
    b = reported(batch(quantity=D(100)), "70", hours_ago=72, revised=None)
    a = allocation(b, "40", date(2026, 10, 19), "SO-00001")
    linked(b, a)

    risk = assess(line([a], "40", date(2026, 10, 19)), [b])

    assert risk.headline == "confirmed_late"
    assert codes(risk)[0] == "confirmed_late"
    assert {"quantity_shortage", "unknown"} <= set(codes(risk))


def test_a_planned_batch_uses_its_planned_return_date() -> None:
    b = batch(status="planned", sent_date=None, expected_return_date=date(2026, 10, 27))
    b.blocker = None
    a = allocation(b, "40", date(2026, 11, 3), "SO-00001")
    linked(b, a)

    risk = assess(line([a], "40", date(2026, 11, 3)), [b])

    share = risk.components[0].allocations[0]
    assert (share.estimate_date, share.estimate_source) == (
        date(2026, 10, 27),
        "planned return; not sent yet",
    )
    assert risk.headline == "on_track"


def test_supplier_blockers_are_evidence_not_a_classification() -> None:
    b = reported(batch(), "0", hours_ago=5, revised=None)
    b.blocker = "Coating line down"
    a = allocation(b, "40", date(2026, 11, 3), "SO-00001")
    linked(b, a)

    risk = assess(line([a], "40", date(2026, 11, 3)), [b])

    assert risk.headline == "on_track"
    assert risk.notes == ["OB-00001 blocker reported by the supplier: Coating line down"]


def test_a_line_served_by_two_batches_waits_for_the_later_one() -> None:
    quick = reported(batch(number="OB-00001"), "0", hours_ago=5, revised=date(2026, 10, 26))
    slow = reported(batch(number="OB-00002"), "0", hours_ago=5, revised=date(2026, 10, 28))
    a = allocation(quick, "20", date(2026, 11, 3), "SO-00001")
    b = allocation(slow, "20", date(2026, 11, 3), "SO-00001")
    b.component_id = a.component_id
    linked(quick, a)
    linked(slow, b)

    risk = assess(line([a, b], "40", date(2026, 11, 3)), [quick, slow])

    assert risk.components_ready_date == date(2026, 10, 28)
    assert risk.projected_date == date(2026, 10, 30)
