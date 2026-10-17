"""Slice F8: dispatch against orders, limited by usable material, and the first reports."""

# ruff: noqa: F811  (pytest fixtures are imported and then used as parameters)

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from conftest import AddMember, csrf_headers, sign_in_as
from httpx import AsyncClient
from sqlalchemy import select
from test_orders import API, act, data, post  # noqa: F401
from test_risk import calendar, day, order_risk, put, scene, supplier_says  # noqa: F401

from app.main import app
from app.models import AuditEvent, BatchAllocation


def dispatch_body(order: dict, *lines: tuple[str, str], **extra) -> dict:
    values = {
        "submission_key": str(uuid.uuid4()),
        "order_id": order["id"],
        "dispatch_date": day(0),
        "carrier": "VRL Logistics",
        "document_reference": "LR-77120",
        "lines": [{"line_id": line_id, "quantity": qty} for line_id, qty in lines],
    }
    values.update(extra)
    return values


def line_of(order: dict) -> str:
    return order["lines"][0]["id"]


async def accept(client: AsyncClient, scene: dict, accepted: str, held: str) -> dict:
    """The supplier finished; 100 came back; quality accepted some and held the rest."""
    batch = await supplier_says(client, scene, "100", "0", "0")
    batch = await post(
        client,
        f"/outsourcing/batches/{batch['id']}/receipts",
        {
            "version": batch["version"],
            "submission_key": str(uuid.uuid4()),
            "received_qty": "100",
            "receipt_date": day(0),
        },
    )
    receipt = batch["receipts"][0]
    return await act(
        client,
        f"/outsourcing/batches/{batch['id']}/receipts/{receipt['id']}/inspection",
        {
            "version": receipt["version"],
            "accepted_qty": accepted,
            "rejected_qty": "0",
            "held_qty": held,
            "rework_qty": "0",
            "note": "Thickness check pending" if held != "0" else None,
        },
    )


async def readiness(client: AsyncClient, order: dict) -> dict:
    report = (
        await client.get(f"{API}/dispatch/readiness", params={"order_id": order["id"]})
    ).json()
    return report["lines"][0]


@pytest.fixture
async def ready(client: AsyncClient, scene: dict) -> dict:
    await calendar(client, scene["site"])
    return scene


async def test_only_accepted_material_can_ship(client: AsyncClient, ready: dict) -> None:
    early = ready["early"]
    assert (await readiness(client, early))["shippable"] == "0"
    blocked = await post(
        client, "/dispatch", dispatch_body(early, (line_of(early), "10")), expect=422
    )
    assert "only 0 PCS can be built from accepted, usable material" in blocked["detail"]

    await accept(client, ready, accepted="50", held="50")
    first = await readiness(client, early)
    assert (first["shippable"], first["components"][0]["usable_for_line"]) == ("40", "40")
    assert (await readiness(client, ready["late"]))["shippable"] == "10"


async def test_dispatch_ships_consumes_and_closes_the_order(
    client: AsyncClient, ready: dict
) -> None:
    await accept(client, ready, accepted="50", held="50")
    early = ready["early"]
    note = await post(client, "/dispatch", dispatch_body(early, (line_of(early), "40")))

    assert (note["number"], note["status"], note["lines"][0]["quantity"]) == (
        "DN-00001",
        "posted",
        "40",
    )
    assert note["lines"][0]["on_time"] is True
    order = (await client.get(f"{API}/orders/{early['id']}")).json()
    line = order["lines"][0]
    assert (order["status"], line["status"], line["shipped_qty"], line["remaining_qty"]) == (
        "closed",
        "fulfilled",
        "40",
        "0",
    )
    # The 40 accepted castings are used up: only 10 accepted remain for the other order.
    assert (await readiness(client, ready["late"]))["shippable"] == "10"
    async with app.state.session_factory() as db:
        consumed = sorted(a.consumed_qty for a in await db.scalars(select(BatchAllocation)))
        event = await db.scalar(select(AuditEvent).where(AuditEvent.action == "dispatch.posted"))
    assert [int(c) for c in consumed] == [0, 40]
    assert event.details["lines"][0]["consumption"][0]["consumed"] == "40"
    cancel = await act(
        client,
        f"/orders/{early['id']}/cancel",
        {"version": order["version"], "reason": "Too late"},
        expect=409,
    )
    assert "cannot be cancelled" in cancel["detail"]


async def test_partial_dispatch_keeps_the_line_open(client: AsyncClient, ready: dict) -> None:
    await accept(client, ready, accepted="100", held="0")
    early = ready["early"]
    await post(client, "/dispatch", dispatch_body(early, (line_of(early), "15")))
    order = (await client.get(f"{API}/orders/{early['id']}")).json()
    assert (order["status"], order["lines"][0]["remaining_qty"]) == ("confirmed", "25")
    risk = await order_risk(client, early)
    assert (risk["remaining"], risk["components"][0]["required"]) == ("25", "25")
    over = await post(client, "/dispatch", dispatch_body(early, (line_of(early), "26")), 422)
    assert "only 25 PCS left to ship" in over["detail"]


@pytest.mark.parametrize(
    "change, expect, detail",
    [
        ({"dispatch_date": "2099-01-01"}, 422, "future"),
        ({"dispatch_date": "2001-01-01"}, 422, "before the order date"),
        ({"lines": "twice"}, 422, "each order line once"),
        ({"lines": "foreign"}, 422, "belong to this order"),
        ({"lines": "fraction"}, 422, "decimal place"),
    ],
)
async def test_dispatch_validation(
    client: AsyncClient, ready: dict, change: dict, expect: int, detail: str
) -> None:
    await accept(client, ready, accepted="100", held="0")
    early = ready["early"]
    body = dispatch_body(early, (line_of(early), "5"))
    if change.get("lines") == "twice":
        body["lines"] = body["lines"] * 2
    elif change.get("lines") == "foreign":
        body["lines"] = [{"line_id": line_of(ready["late"]), "quantity": "5"}]
    elif change.get("lines") == "fraction":
        body["lines"][0]["quantity"] = "2.5"
    else:
        body.update(change)
    response = await client.post(f"{API}/dispatch", headers=csrf_headers(client), json=body)
    assert response.status_code == expect
    assert detail in response.json()["detail"]


async def test_shipping_beyond_usable_material_is_an_owner_exception(
    client: AsyncClient, ready: dict, add_member: AddMember, workspace_records: dict
) -> None:
    await accept(client, ready, accepted="20", held="80")
    early = ready["early"]
    await add_member("stores@example.com", "stores", site_ids=[workspace_records["site_id"]])
    await sign_in_as(client, "stores@example.com")
    entry = {"line_id": line_of(early), "quantity": "30", "exception_reason": "Customer accepts"}
    refused = await post(client, "/dispatch", dispatch_body(early, lines=[entry]), expect=403)
    assert "owner or administrator" in refused["detail"]

    await sign_in_as(client, "owner@example.com")
    note = await post(client, "/dispatch", dispatch_body(early, lines=[entry]))
    assert note["lines"][0]["exception_reason"] == "Customer accepts"
    async with app.state.session_factory() as db:
        consumed = max(a.consumed_qty for a in await db.scalars(select(BatchAllocation)))
    assert int(consumed) == 20  # only accepted material is ever consumed


async def test_cancelling_a_dispatch_reverses_it_exactly(client: AsyncClient, ready: dict) -> None:
    await accept(client, ready, accepted="100", held="0")
    early = ready["early"]
    note = await post(client, "/dispatch", dispatch_body(early, (line_of(early), "40")))
    path = f"/dispatch/{note['id']}/cancel"
    await act(client, path, {"version": note["version"], "reason": "x"}, expect=422)
    cancelled = await act(
        client, path, {"version": note["version"], "reason": "Truck turned back at the gate"}
    )

    assert (cancelled["status"], cancelled["cancelled_by_label"]) == (
        "cancelled",
        "A. Owner <owner@example.com>",
    )
    order = (await client.get(f"{API}/orders/{early['id']}")).json()
    assert (order["status"], order["lines"][0]["shipped_qty"], order["lines"][0]["status"]) == (
        "confirmed",
        "0",
        "open",
    )
    component = order["lines"][0]["components"][0]
    assert (component["allocated_qty"], component["allocations"][0]["consumed_qty"]) == ("40", "0")
    assert (await readiness(client, early))["shippable"] == "40"
    await act(client, path, {"version": cancelled["version"], "reason": "Again"}, expect=409)


async def test_a_repeated_dispatch_is_posted_once(client: AsyncClient, ready: dict) -> None:
    await accept(client, ready, accepted="100", held="0")
    body = dispatch_body(ready["early"], (line_of(ready["early"]), "10"))
    first = await client.post(f"{API}/dispatch", headers=csrf_headers(client), json=body)
    again = await client.post(f"{API}/dispatch", headers=csrf_headers(client), json=body)
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json()["id"] == again.json()["id"]
    order = (await client.get(f"{API}/orders/{ready['early']['id']}")).json()
    assert order["lines"][0]["shipped_qty"] == "10"


async def test_dispatch_permissions_and_scope(
    client: AsyncClient, ready: dict, add_member: AddMember, workspace_records: dict
) -> None:
    await accept(client, ready, accepted="100", held="0")
    early = ready["early"]
    hosur = await post(client, "/organization/sites", {"name": "Hosur Plant"})
    await add_member("qc@example.com", "quality", site_ids=[workspace_records["site_id"]])
    await add_member("far@example.com", "dispatch", site_ids=[uuid.UUID(hosur["id"])])
    await add_member("despatch@example.com", "dispatch", site_ids=[workspace_records["site_id"]])
    body = lambda: dispatch_body(early, (line_of(early), "5"))  # noqa: E731

    await sign_in_as(client, "qc@example.com")
    await post(client, "/dispatch", body(), expect=403)
    await sign_in_as(client, "far@example.com")
    await post(client, "/dispatch", body(), expect=404)
    await sign_in_as(client, "despatch@example.com")
    note = await post(client, "/dispatch", body())
    await sign_in_as(client, "far@example.com")
    assert (await client.get(f"{API}/dispatch")).json() == []
    assert (await client.get(f"{API}/dispatch/{note['id']}")).status_code == 404


async def test_fulfillment_report_measures_delivery_risk_and_actions(
    client: AsyncClient, ready: dict, data: dict
) -> None:
    await accept(client, ready, accepted="100", held="0")
    early = ready["early"]
    await post(
        client,
        "/actions",
        {
            "submission_key": str(uuid.uuid4()),
            "kind": "collect",
            "title": "Collect the coated castings",
            "line_id": line_of(early),
            "owner_id": str(
                (
                    await client.get(f"{API}/actions/assignees", params={"site_id": ready["site"]})
                ).json()[0]["user_id"]
            ),
            "due_at": (datetime.now(UTC) + timedelta(hours=4)).isoformat(),
        },
    )
    await post(client, "/dispatch", dispatch_body(early, (line_of(early), "40")))
    # A second order promised two days ago ships today: late.
    overdue = await post(
        client,
        "/orders",
        {
            "site_id": data["site"],
            "customer_id": data["bharat"],
            "order_date": day(-5),
            "lines": [
                {
                    "item_id": data["pump"],
                    "quantity": "5",
                    "requested_date": day(-2),
                    "promised_date": day(-2),
                }
            ],
        },
    )
    overdue = await act(client, f"/orders/{overdue['id']}/confirm", {"version": overdue["version"]})
    await post(client, "/dispatch", dispatch_body(overdue, (line_of(overdue), "5")))
    await put(client, "/fulfillment/settings", {"supplier_update_stale_hours": 1})

    report = (await client.get(f"{API}/reports/fulfillment")).json()

    delivery = report["delivery"]
    assert (delivery["dispatch_lines"], delivery["on_time"], delivery["late"]) == (2, 1, 1)
    assert (delivery["on_time_rate"], delivery["average_days_late"]) == (0.5, 2.0)
    assert {c["customer_name"]: c["late"] for c in delivery["by_customer"]} == {
        "Acme": 0,
        "Bharat": 1,
    }
    assert report["open_risk"]["on_track"] + report["open_risk"]["ready"] >= 1
    assert report["actions"]["open"] == 1
    assert report["actions"]["age"][0] == {"label": "under 1 day", "count": 1}
    assert report["early_warning"]["lines_with_actions"] == 1
    assert report["early_warning"]["average_days_ahead"] == 30
    assert set(report["definitions"]) >= {"on_time_rate", "stale_updates", "early_warning"}
    bad = await client.get(
        f"{API}/reports/fulfillment", params={"date_from": day(0), "date_to": day(-1)}
    )
    assert bad.status_code == 422


async def test_report_lists_stale_batches_and_respects_scope(
    client: AsyncClient, ready: dict, add_member: AddMember, workspace_records: dict
) -> None:
    await supplier_says(client, ready, "40", "0", "60", hours_ago=5)
    fresh = (await client.get(f"{API}/reports/fulfillment")).json()
    assert fresh["stale_batches"] == []  # 5 hours old is fresh under the 48-hour default
    await put(client, "/fulfillment/settings", {"supplier_update_stale_hours": 2})
    report = (await client.get(f"{API}/reports/fulfillment")).json()
    [batch] = report["stale_batches"]
    assert (batch["number"], batch["orders_waiting"], batch["hours_since"] >= 5) == (
        "OB-00001",
        2,
        True,
    )
    hosur = await post(client, "/organization/sites", {"name": "Hosur Plant"})
    await add_member("far@example.com", "read_only", site_ids=[uuid.UUID(hosur["id"])])
    await sign_in_as(client, "far@example.com")
    far = (await client.get(f"{API}/reports/fulfillment")).json()
    assert far["stale_batches"] == [] and far["delivery"]["dispatch_lines"] == 0


async def test_cancelled_dispatches_do_not_count(client: AsyncClient, ready: dict) -> None:
    await accept(client, ready, accepted="100", held="0")
    early = ready["early"]
    note = await post(client, "/dispatch", dispatch_body(early, (line_of(early), "40")))
    await act(
        client,
        f"/dispatch/{note['id']}/cancel",
        {"version": note["version"], "reason": "Truck turned back"},
    )
    report = (await client.get(f"{API}/reports/fulfillment")).json()
    assert report["delivery"]["dispatch_lines"] == 0
