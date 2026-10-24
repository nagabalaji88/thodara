"""Slice G1: reconciliation tolerance, manual batch priority and the same-person flag."""

# ruff: noqa: F811  (pytest fixtures are imported and then used as parameters)

import uuid
from datetime import UTC, datetime, timedelta

from conftest import AddMember, csrf_headers, sign_in_as
from httpx import AsyncClient
from sqlalchemy import select
from test_dispatch import accept, ready  # noqa: F401
from test_orders import API, act, data, post  # noqa: F401
from test_risk import calendar, day, order_risk, put, scene, supplier_says  # noqa: F401

from app.main import app
from app.models import AuditEvent


async def report_figures(client: AsyncClient, scene: dict, *figures: str, expect: int = 201):
    batch = (await client.get(f"{API}/outsourcing/batches/{scene['batch']['id']}")).json()
    response = await client.post(
        f"{API}/outsourcing/batches/{batch['id']}/updates",
        headers=csrf_headers(client),
        json={
            "version": batch["version"],
            "submission_key": str(uuid.uuid4()),
            "completed_qty": figures[0],
            "rejected_qty": figures[1],
            "pending_qty": figures[2],
            "contact_method": "phone",
            "reported_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        },
    )
    assert response.status_code == expect, response.text
    return response.json()


# Tolerance -----------------------------------------------------------------------------


async def test_supplier_figures_may_differ_within_the_company_tolerance(
    client: AsyncClient, ready: dict
) -> None:
    # 100 sent; the default ±2% allows 2 pieces either way.
    within = await report_figures(client, ready, "60", "0", "38")
    assert within["latest_update"]["unaccounted_qty"] == "2"
    assert within["quantities"]["reported_unaccounted"] == "2"
    beyond = await report_figures(client, ready, "60", "0", "37", expect=422)
    assert "within ±2% (2 PCS); these add up to 97" in beyond["detail"]

    over = await report_figures(client, ready, "60", "0", "41")
    assert over["latest_update"]["unaccounted_qty"] == "-1"


async def test_unaccounted_pieces_are_not_assumed_to_come_back(
    client: AsyncClient, ready: dict
) -> None:
    # The earlier order needs 40, the later 60. With 2 pieces unaccounted, only 98 can return.
    await report_figures(client, ready, "60", "0", "38")
    late = await order_risk(client, ready["late"])
    [share] = late["components"][0]["allocations"]
    assert (share["from_supplier"], share["short"]) == ("58", "2")
    assert late["headline"] == "quantity_shortage"


async def test_tolerance_is_a_company_setting(
    client: AsyncClient, ready: dict, add_member: AddMember, workspace_records: dict
) -> None:
    saved = await put(client, "/fulfillment/settings", {"reconciliation_tolerance_percent": "5"})
    assert (saved["reconciliation_tolerance_percent"], saved["supplier_update_stale_hours"]) == (
        "5",
        48,
    )
    await report_figures(client, ready, "60", "0", "35")
    await put(
        client,
        "/fulfillment/settings",
        {"version": saved["version"], "reconciliation_tolerance_percent": "25"},
        expect=422,
    )
    await put(client, "/fulfillment/settings", {"version": saved["version"]}, expect=422)
    async with app.state.session_factory() as db:
        event = await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "fulfillment.settings_changed")
        )
    assert event.details == {
        "before": {"reconciliation_tolerance_percent": "2"},
        "after": {"reconciliation_tolerance_percent": "5"},
    }
    await add_member("buyer@example.com", "procurement", site_ids=[workspace_records["site_id"]])
    await sign_in_as(client, "buyer@example.com")
    await put(
        client,
        "/fulfillment/settings",
        {"version": saved["version"], "reconciliation_tolerance_percent": "10"},
        expect=403,
    )


# Manual priority -----------------------------------------------------------------------


async def test_a_planner_can_serve_a_later_promise_first(
    client: AsyncClient, ready: dict, add_member: AddMember, workspace_records: dict
) -> None:
    await accept(client, ready, accepted="50", held="50")
    batch = (await client.get(f"{API}/outsourcing/batches/{ready['batch']['id']}")).json()
    late_allocation = next(
        a for a in batch["allocations"] if a["order_number"] == ready["late"]["number"]
    )
    path = f"/outsourcing/batches/{batch['id']}/allocations/{late_allocation['id']}/priority"
    await act(client, path, {"version": batch["version"], "rank": 1, "reason": "x"}, 422)

    await add_member("buyer@example.com", "procurement", site_ids=[workspace_records["site_id"]])
    await sign_in_as(client, "buyer@example.com")
    await act(client, path, {"version": batch["version"], "rank": 1, "reason": "Key account"}, 403)

    await sign_in_as(client, "owner@example.com")
    ranked = await act(
        client,
        path,
        {"version": batch["version"], "rank": 1, "reason": "Key account; line-side stock out"},
    )
    shown = next(a for a in ranked["allocations"] if a["id"] == late_allocation["id"])
    assert (shown["priority_rank"], shown["priority_set_by_label"]) == (
        1,
        "A. Owner <owner@example.com>",
    )
    # The later promise now takes the 50 accepted castings; the earlier one waits.
    late = await order_risk(client, ready["late"])
    early = await order_risk(client, ready["early"])
    assert late["components"][0]["usable_now"] == "50"
    assert early["components"][0]["usable_now"] == "0"
    assert early["components"][0]["allocations"][0]["ahead"] == [f"{ready['late']['number']}/1"]

    cleared = await act(
        client, path, {"version": ranked["version"], "rank": None, "reason": "Back to normal"}
    )
    assert (
        next(a for a in cleared["allocations"] if a["id"] == late_allocation["id"])["priority_rank"]
        is None
    )
    assert (await order_risk(client, ready["early"]))["components"][0]["usable_now"] == "40"
    async with app.state.session_factory() as db:
        actions = [
            e.action
            for e in await db.scalars(select(AuditEvent).order_by(AuditEvent.created_at))
            if "priority" in e.action
        ]
    assert actions == ["outsourcing.priority_set", "outsourcing.priority_cleared"]


# Same person received and inspected -----------------------------------------------------


async def test_receiving_and_inspecting_by_one_person_is_allowed_but_flagged(
    client: AsyncClient, ready: dict, add_member: AddMember, workspace_records: dict
) -> None:
    batch = await accept(client, ready, accepted="100", held="0")  # owner did both
    decision = batch["receipts"][0]["decisions"][0]
    assert decision["same_person"] is True

    site = workspace_records["site_id"]
    await add_member("stores@example.com", "stores", site_ids=[site])
    await add_member("qc@example.com", "quality", site_ids=[site])
    other = await post(
        client,
        "/outsourcing/batches",
        {
            "site_id": ready["site"],
            "supplier_id": ready["batch"]["supplier_id"],
            "item_id": ready["casting"],
            "operation": "Powder coating",
            "quantity": "10",
            "expected_return_date": day(5),
        },
    )
    other = await act(
        client,
        f"/outsourcing/batches/{other['id']}/send",
        {"version": other["version"], "sent_date": day(-1)},
    )
    await sign_in_as(client, "stores@example.com")
    other = await post(
        client,
        f"/outsourcing/batches/{other['id']}/receipts",
        {
            "version": other["version"],
            "submission_key": str(uuid.uuid4()),
            "received_qty": "10",
            "receipt_date": day(0),
        },
    )
    await sign_in_as(client, "qc@example.com")
    receipt = other["receipts"][0]
    inspected = await act(
        client,
        f"/outsourcing/batches/{other['id']}/receipts/{receipt['id']}/inspection",
        {
            "version": receipt["version"],
            "accepted_qty": "10",
            "rejected_qty": "0",
            "held_qty": "0",
            "rework_qty": "0",
        },
    )
    assert inspected["receipts"][0]["decisions"][0]["same_person"] is False

    await sign_in_as(client, "owner@example.com")
    checks = (await client.get(f"{API}/reports/fulfillment")).json()["quality_checks"]
    assert checks == {"decisions": 2, "same_person": 1}
