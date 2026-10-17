"""Slice F6: delivery risk through the API, with dates relative to today."""

# ruff: noqa: F811  (pytest fixtures are imported and then used as parameters)

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from conftest import AddMember, csrf_headers, sign_in_as
from httpx import AsyncClient
from sqlalchemy import select
from test_orders import API, act, data, post  # noqa: F401

from app.main import app
from app.models import AuditEvent

# The test site works in India time; "today" must match its calendar.
TODAY = datetime.now(ZoneInfo("Asia/Kolkata")).date()


def day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


async def put(client: AsyncClient, path: str, body: dict, expect: int = 200) -> dict:
    response = await client.put(f"{API}{path}", headers=csrf_headers(client), json=body)
    assert response.status_code == expect, response.text
    return response.json()


async def confirmed(client, data, customer: str, reference: str, quantity: str, promised: int):
    order = await post(
        client,
        "/orders",
        {
            "site_id": data["site"],
            "customer_id": data[customer],
            "customer_reference": reference,
            "lines": [
                {
                    "item_id": data["pump"],
                    "quantity": quantity,
                    "requested_date": day(promised),
                    "promised_date": day(promised),
                }
            ],
        },
    )
    order = await act(client, f"/orders/{order['id']}/confirm", {"version": order["version"]})
    line = order["lines"][0]
    return await put(
        client,
        f"/orders/{order['id']}/lines/{line['id']}/dependencies",
        {
            "order_version": order["version"],
            "components": [
                {
                    "item_id": data["casting"],
                    "qty_per_unit": "1",
                    "outsourced_operation": "Powder coating",
                }
            ],
            "operations": [{"name": "Assembly", "kind": "in_house", "duration_minutes": 480}],
        },
    )


@pytest.fixture
async def scene(client: AsyncClient, data: dict[str, str]) -> dict:
    """Two confirmed orders (40 and 60 pumps) sharing one batch of 100 castings at a coater."""
    units = (await client.get(f"{API}/master-data/units")).json()["items"]
    pcs = next(u for u in units if u["code"] == "PCS")
    casting = await post(
        client,
        "/master-data/items",
        {
            "code": "HSG-CAST",
            "name": "Casting",
            "item_type": "component",
            "base_unit_id": pcs["id"],
        },
    )
    coater = await post(
        client,
        "/master-data/suppliers",
        {"code": "COAT", "name": "Hosur Coaters", "provides_job_work": True},
    )
    data = {**data, "casting": casting["id"]}
    early = await confirmed(client, data, "acme", "PO-EARLY", "40", 30)
    late = await confirmed(client, data, "bharat", "PO-LATE", "60", 40)
    batch = await post(
        client,
        "/outsourcing/batches",
        {
            "site_id": data["site"],
            "supplier_id": coater["id"],
            "item_id": casting["id"],
            "operation": "Powder coating",
            "quantity": "100",
            "expected_return_date": day(10),
            "allocations": [
                {"component_id": early["lines"][0]["components"][0]["id"], "quantity": "40"},
                {"component_id": late["lines"][0]["components"][0]["id"], "quantity": "60"},
            ],
        },
    )
    batch = await act(
        client,
        f"/outsourcing/batches/{batch['id']}/send",
        {"version": batch["version"], "sent_date": day(-1)},
    )
    return {**data, "early": early, "late": late, "batch": batch}


async def calendar(client: AsyncClient, site: str) -> None:
    await put(
        client,
        f"/organization/sites/{site}/calendar",
        {"working_days": [1, 2, 3, 4, 5, 6], "shift_start": "09:00", "shift_end": "17:00"},
    )


async def order_risk(client: AsyncClient, order: dict) -> dict:
    response = await client.get(f"{API}/orders/{order['id']}/risk")
    assert response.status_code == 200, response.text
    return response.json()["lines"][0]


async def supplier_says(client, scene, completed, rejected, pending, hours_ago=1, revised=None):
    batch = (await client.get(f"{API}/outsourcing/batches/{scene['batch']['id']}")).json()
    reported_at = (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat()
    return await post(
        client,
        f"/outsourcing/batches/{batch['id']}/updates",
        {
            "version": batch["version"],
            "submission_key": str(uuid.uuid4()),
            "completed_qty": completed,
            "rejected_qty": rejected,
            "pending_qty": pending,
            "contact_method": "phone",
            "reported_at": reported_at,
            "revised_return_date": revised,
        },
    )


async def test_risk_needs_a_calendar_then_projects_from_the_batch(
    client: AsyncClient, scene: dict
) -> None:
    await supplier_says(client, scene, "60", "0", "40")
    without = await order_risk(client, scene["early"])
    assert without["headline"] == "unknown"
    assert "no working calendar" in without["issues"][0]["message"]

    await calendar(client, scene["site"])
    risk = await order_risk(client, scene["early"])

    assert risk["headline"] == "on_track"
    [component] = risk["components"]
    assert (component["required"], component["usable_now"]) == ("40", "0")
    [share] = component["allocations"]
    assert (share["batch_number"], share["from_supplier"], share["estimate_date"]) == (
        "OB-00001",
        "40",
        day(10),
    )
    assert share["estimate_source"] == "planned return date"
    assert risk["projected_date"] is not None and risk["projected_date"] >= day(10)
    assert risk["slack_days"] > 0


async def test_supplier_rejections_short_the_later_order_on_the_board(
    client: AsyncClient, scene: dict
) -> None:
    await calendar(client, scene["site"])
    # 100 sent; the supplier rejected 30, so only 70 can come back usable.
    await supplier_says(client, scene, "50", "30", "20", revised=day(12))

    board = (await client.get(f"{API}/fulfillment/risk")).json()

    assert board["counts"]["quantity_shortage"] == 1
    assert board["counts"]["on_track"] == 1
    first, second = board["lines"]
    assert (first["order_number"], first["headline"]) == (
        scene["late"]["number"],
        "quantity_shortage",
    )
    assert "only 30 of the 60 PCS" in first["issues"][0]["message"]
    assert (second["order_number"], second["headline"]) == (scene["early"]["number"], "on_track")
    assert second["components"][0]["allocations"][0]["estimate_date"] == day(12)
    only_short = (
        await client.get(f"{API}/fulfillment/risk", params={"headline": "quantity_shortage"})
    ).json()
    assert [line["order_number"] for line in only_short["lines"]] == [scene["late"]["number"]]


async def test_stale_threshold_is_a_company_setting(
    client: AsyncClient, scene: dict, add_member: AddMember, workspace_records: dict
) -> None:
    await calendar(client, scene["site"])
    await supplier_says(client, scene, "60", "0", "40", hours_ago=3)
    settings = (await client.get(f"{API}/fulfillment/settings")).json()
    assert settings == {"supplier_update_stale_hours": 48, "is_default": True, "version": None}
    assert (await order_risk(client, scene["early"]))["headline"] == "on_track"

    saved = await put(client, "/fulfillment/settings", {"supplier_update_stale_hours": 2})
    assert (saved["supplier_update_stale_hours"], saved["is_default"]) == (2, False)
    risk = await order_risk(client, scene["early"])
    assert risk["headline"] == "unknown"
    assert "last supplier update 3 h ago" in risk["issues"][0]["message"]

    await put(client, "/fulfillment/settings", {"supplier_update_stale_hours": 5}, expect=409)
    await put(
        client,
        "/fulfillment/settings",
        {"version": saved["version"], "supplier_update_stale_hours": 0},
        expect=422,
    )
    await add_member(
        "planner@example.com", "production_manager", site_ids=[workspace_records["site_id"]]
    )
    await sign_in_as(client, "planner@example.com")
    await put(
        client,
        "/fulfillment/settings",
        {"version": saved["version"], "supplier_update_stale_hours": 72},
        expect=403,
    )
    async with app.state.session_factory() as db:
        event = await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "fulfillment.settings_changed")
        )
    assert event.details == {
        "before": {"supplier_update_stale_hours": 48},
        "after": {"supplier_update_stale_hours": 2},
    }


async def test_receipts_and_quality_make_material_usable(client: AsyncClient, scene: dict) -> None:
    await calendar(client, scene["site"])
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
    assert (await order_risk(client, scene["early"]))["components"][0]["usable_now"] == "0"
    await act(
        client,
        f"/outsourcing/batches/{batch['id']}/receipts/{receipt['id']}/inspection",
        {
            "version": receipt["version"],
            "accepted_qty": "50",
            "rejected_qty": "0",
            "held_qty": "50",
            "rework_qty": "0",
            "note": "Thickness check on 50",
        },
    )

    early = await order_risk(client, scene["early"])
    late = await order_risk(client, scene["late"])
    assert (early["headline"], early["components"][0]["usable_now"]) == ("ready", "40")
    assert early["components_ready_date"] == day(0)
    assert late["headline"] == "quality_hold"
    assert late["components"][0]["allocations"][0]["held"] == "50"


async def test_risk_respects_site_and_tenant_scope(
    client: AsyncClient, scene: dict, add_member: AddMember, workspace_records: dict
) -> None:
    hosur = await post(client, "/organization/sites", {"name": "Hosur Plant"})
    await add_member("hosur@example.com", "production_manager", site_ids=[uuid.UUID(hosur["id"])])
    await add_member(
        "rival@example.com",
        "owner",
        tenant_id=workspace_records["other_tenant_id"],
        home_site_id=workspace_records["other_site_id"],
    )
    for email in ("hosur@example.com", "rival@example.com"):
        await sign_in_as(client, email)
        board = (await client.get(f"{API}/fulfillment/risk")).json()
        assert board["lines"] == []
        response = await client.get(f"{API}/orders/{scene['early']['id']}/risk")
        assert response.status_code == 404

    await add_member("viewer@example.com", "read_only", site_ids=[workspace_records["site_id"]])
    await sign_in_as(client, "viewer@example.com")
    assert len((await client.get(f"{API}/fulfillment/risk")).json()["lines"]) == 2


async def test_a_draft_order_has_no_risk_yet(client: AsyncClient, data: dict) -> None:
    order = await post(
        client,
        "/orders",
        {
            "site_id": data["site"],
            "customer_id": data["acme"],
            "lines": [{"item_id": data["pump"], "quantity": "5", "requested_date": day(20)}],
        },
    )
    report = (await client.get(f"{API}/orders/{order['id']}/risk")).json()
    assert report["lines"] == []
    assert date.fromisoformat(report["computed_at"][:10]) >= TODAY - timedelta(days=1)
