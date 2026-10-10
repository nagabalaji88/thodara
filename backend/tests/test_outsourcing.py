"""Slice F3: outsourced batches and which order lines they serve."""

import uuid

import pytest
from conftest import AddMember, csrf_headers, sign_in_as
from httpx import AsyncClient
from sqlalchemy import select
from test_dependencies import flow, put  # noqa: F401  (flow is a fixture)
from test_orders import API, act, data, patch, post  # noqa: F401

from app.main import app
from app.models import AuditEvent


async def needs_castings(client: AsyncClient, order_id: str, qty_per_unit: str = "1") -> dict:
    order = (await client.get(f"{API}/orders/{order_id}")).json()
    line = order["lines"][0]
    casting = (await client.get(f"{API}/master-data/items", params={"q": "HSG-CAST"})).json()
    return await put(
        client,
        f"/orders/{order_id}/lines/{line['id']}/dependencies",
        {
            "order_version": order["version"],
            "components": [
                {
                    "item_id": casting["items"][0]["id"],
                    "qty_per_unit": qty_per_unit,
                    "outsourced_operation": "Powder coating",
                }
            ],
            "operations": [{"name": "Assembly", "kind": "in_house", "duration_minutes": 240}],
        },
    )


@pytest.fixture
async def planned(client: AsyncClient, flow: dict[str, str]) -> dict[str, str]:  # noqa: F811
    order = await needs_castings(client, flow["order"])
    return {**flow, "component": order["lines"][0]["components"][0]["id"]}


def batch_body(ids: dict[str, str], **overrides) -> dict:
    body = {
        "site_id": ids["site"],
        "supplier_id": ids["coater"],
        "item_id": ids["casting"],
        "operation": "Powder coating",
        "quantity": "200",
        "expected_return_date": "2026-11-02",
    }
    body.update(overrides)
    return body


async def second_order(client: AsyncClient, ids: dict[str, str], quantity: str = "60") -> dict:
    order = await post(
        client,
        "/orders",
        {
            "site_id": ids["site"],
            "customer_id": ids["bharat"],
            "customer_reference": "PO-SECOND",
            "lines": [
                {
                    "item_id": ids["pump"],
                    "quantity": quantity,
                    "requested_date": "2026-11-20",
                    "promised_date": "2026-11-20",
                }
            ],
        },
    )
    order = await act(client, f"/orders/{order['id']}/confirm", {"version": order["version"]})
    return await needs_castings(client, order["id"])


async def events(action: str) -> list[AuditEvent]:
    async with app.state.session_factory() as db:
        return list(await db.scalars(select(AuditEvent).where(AuditEvent.action == action)))


async def test_one_batch_serves_several_orders_and_shows_them(
    client: AsyncClient, planned: dict[str, str]
) -> None:
    other = await second_order(client, planned)
    other_component = other["lines"][0]["components"][0]["id"]
    batch = await post(
        client,
        "/outsourcing/batches",
        batch_body(
            planned,
            allocations=[
                {"component_id": planned["component"], "quantity": "40"},
                {"component_id": other_component, "quantity": "60"},
            ],
        ),
    )

    assert (batch["number"], batch["status"], batch["quantity"], batch["unit_code"]) == (
        "OB-00001",
        "planned",
        "200",
        "PCS",
    )
    assert batch["allocated_qty"] == "100"
    assert [
        (a["order_number"], a["quantity"], a["component_required_qty"])
        for a in batch["allocations"]
    ] == [
        ("SO-00001", "40", "40"),
        (other["number"], "60", "60"),
    ]
    order = (await client.get(f"{API}/orders/{planned['order']}")).json()
    component = order["lines"][0]["components"][0]
    assert component["allocated_qty"] == "40"
    assert [
        (a["batch_number"], a["supplier_name"], a["batch_status"]) for a in component["allocations"]
    ] == [("OB-00001", "Hosur Coaters", "planned")]
    [created] = await events("outsourcing.batch_created")
    assert len(created.details["allocations"]) == 2
    listed = (await client.get(f"{API}/outsourcing/batches")).json()
    assert (listed["total"], listed["items"][0]["order_count"]) == (1, 2)


@pytest.mark.parametrize(
    "override, detail",
    [
        ({"supplier_id": "trader"}, "job-work supplier"),
        ({"item_id": "acme"}, "active item"),
        ({"quantity": "2.5"}, "decimal place"),
        ({"quantity": "0"}, None),
        ({"operation": ""}, None),
        ({"expected_return_date": "1999-01-01"}, None),
    ],
)
async def test_batch_needs_a_job_work_supplier_and_valid_values(
    client: AsyncClient, planned: dict[str, str], override: dict, detail: str | None
) -> None:
    override = {k: planned.get(v, v) for k, v in override.items()}
    response = await client.post(
        f"{API}/outsourcing/batches",
        headers=csrf_headers(client),
        json=batch_body(planned, **override),
    )
    assert response.status_code == 422
    if detail:
        assert detail in response.json()["detail"]
    assert (await client.get(f"{API}/outsourcing/batches")).json()["total"] == 0


async def test_allocations_cannot_exceed_the_batch_or_the_need(
    client: AsyncClient, planned: dict[str, str]
) -> None:
    other = await second_order(client, planned, quantity="300")
    other_component = other["lines"][0]["components"][0]["id"]
    batch = await post(client, "/outsourcing/batches", batch_body(planned, quantity="100"))
    path = f"/outsourcing/batches/{batch['id']}/allocations"

    too_much_for_line = await act(
        client,
        path,
        {"version": batch["version"], "component_id": planned["component"], "quantity": "41"},
        expect=422,
    )
    assert "needs only 40" in too_much_for_line["detail"]
    batch = await act(
        client,
        path,
        {"version": batch["version"], "component_id": planned["component"], "quantity": "40"},
    )
    duplicate = await act(
        client,
        path,
        {"version": batch["version"], "component_id": planned["component"], "quantity": "1"},
        expect=409,
    )
    assert "already allocated" in duplicate["detail"]
    too_much_for_batch = await act(
        client,
        path,
        {"version": batch["version"], "component_id": other_component, "quantity": "61"},
        expect=422,
    )
    assert "Only 60 PCS" in too_much_for_batch["detail"]
    stale = await act(
        client,
        path,
        {"version": batch["version"] - 1, "component_id": other_component, "quantity": "1"},
        expect=409,
    )
    assert "changed by someone else" in stale["detail"]


async def test_allocations_need_the_same_item_site_and_a_confirmed_order(
    client: AsyncClient, planned: dict[str, str]
) -> None:
    resin_batch = await post(
        client,
        "/outsourcing/batches",
        batch_body(planned, item_id=planned["resin"], quantity="5"),
    )
    wrong_item = await act(
        client,
        f"/outsourcing/batches/{resin_batch['id']}/allocations",
        {"version": resin_batch["version"], "component_id": planned["component"], "quantity": "1"},
        expect=422,
    )
    assert "does not need" in wrong_item["detail"]

    hosur = await post(client, "/organization/sites", {"name": "Hosur Plant"})
    far = await post(client, "/outsourcing/batches", batch_body(planned, site_id=hosur["id"]))
    other_site = await act(
        client,
        f"/outsourcing/batches/{far['id']}/allocations",
        {"version": far["version"], "component_id": planned["component"], "quantity": "1"},
        expect=422,
    )
    assert "different site" in other_site["detail"]

    draft = await post(
        client,
        "/orders",
        {
            "site_id": planned["site"],
            "customer_id": planned["bharat"],
            "lines": [
                {"item_id": planned["pump"], "quantity": "5", "requested_date": "2026-11-20"}
            ],
        },
    )
    draft = await needs_castings(client, draft["id"])
    batch = await post(client, "/outsourcing/batches", batch_body(planned))
    not_confirmed = await act(
        client,
        f"/outsourcing/batches/{batch['id']}/allocations",
        {
            "version": batch["version"],
            "component_id": draft["lines"][0]["components"][0]["id"],
            "quantity": "1",
        },
        expect=409,
    )
    assert "confirmed order" in not_confirmed["detail"]


async def test_sending_records_custody_and_freezes_the_plan(
    client: AsyncClient, planned: dict[str, str]
) -> None:
    batch = await post(client, "/outsourcing/batches", batch_body(planned))
    send = f"/outsourcing/batches/{batch['id']}/send"
    await act(client, send, {"version": batch["version"], "sent_date": "2099-01-01"}, expect=422)
    sent = await act(
        client,
        send,
        {"version": batch["version"], "sent_date": "2026-10-05", "challan_reference": "DC-1182"},
    )

    assert (sent["status"], sent["sent_date"], sent["challan_reference"]) == (
        "at_supplier",
        "2026-10-05",
        "DC-1182",
    )
    [movement] = sent["movements"]
    assert (movement["kind"], movement["quantity"], movement["document_reference"]) == (
        "sent_to_supplier",
        "200",
        "DC-1182",
    )
    assert movement["recorded_by_label"] == "A. Owner <owner@example.com>"
    await act(client, send, {"version": sent["version"], "sent_date": "2026-10-05"}, expect=409)
    await patch(
        client,
        f"/outsourcing/batches/{batch['id']}",
        {"version": sent["version"], "quantity": "150"},
        expect=409,
    )
    noted = await patch(
        client,
        f"/outsourcing/batches/{batch['id']}",
        {"version": sent["version"], "notes": "Collect with the Friday truck"},
    )
    assert noted["notes"] == "Collect with the Friday truck"
    [sent_event] = await events("outsourcing.batch_sent")
    assert sent_event.details["challan_reference"] == "DC-1182"


async def test_planned_batches_can_change_but_not_below_allocations(
    client: AsyncClient, planned: dict[str, str]
) -> None:
    batch = await post(
        client,
        "/outsourcing/batches",
        batch_body(planned, allocations=[{"component_id": planned["component"], "quantity": "40"}]),
    )
    path = f"/outsourcing/batches/{batch['id']}"
    await patch(client, path, {"version": batch["version"], "quantity": "39"}, expect=409)
    changed = await patch(
        client,
        path,
        {"version": batch["version"], "quantity": "50", "expected_return_date": "2026-11-05"},
    )
    assert (changed["quantity"], changed["expected_return_date"]) == ("50", "2026-11-05")
    [updated] = await events("outsourcing.batch_updated")
    assert (updated.details["before"]["quantity"], updated.details["after"]["quantity"]) == (
        "200",
        "50",
    )


async def test_cancel_and_close_release_allocations(
    client: AsyncClient, planned: dict[str, str]
) -> None:
    allocation = [{"component_id": planned["component"], "quantity": "40"}]
    first = await post(client, "/outsourcing/batches", batch_body(planned, allocations=allocation))
    await act(
        client,
        f"/outsourcing/batches/{first['id']}/cancel",
        {"version": first["version"], "reason": "x"},
        expect=422,
    )
    cancelled = await act(
        client,
        f"/outsourcing/batches/{first['id']}/cancel",
        {"version": first["version"], "reason": "Supplier has no capacity this month"},
    )
    assert (cancelled["status"], cancelled["allocations"]) == ("cancelled", [])

    second = await post(client, "/outsourcing/batches", batch_body(planned, allocations=allocation))
    sent = await act(
        client,
        f"/outsourcing/batches/{second['id']}/send",
        {"version": second["version"], "sent_date": "2026-10-05"},
    )
    await act(
        client,
        f"/outsourcing/batches/{second['id']}/cancel",
        {"version": sent["version"], "reason": "Too late to cancel"},
        expect=409,
    )
    closed = await act(
        client,
        f"/outsourcing/batches/{second['id']}/close",
        {"version": sent["version"], "reason": "Settled with the supplier outside Thodara"},
    )
    assert (closed["status"], closed["status_reason"], closed["allocations"]) == (
        "closed",
        "Settled with the supplier outside Thodara",
        [],
    )
    order = (await client.get(f"{API}/orders/{planned['order']}")).json()
    assert order["lines"][0]["components"][0]["allocated_qty"] == "0"
    [closed_event] = await events("outsourcing.batch_closed")
    assert closed_event.details["released_allocations"][0]["quantity"] == "40"


async def test_order_changes_respect_and_release_allocations(
    client: AsyncClient, planned: dict[str, str]
) -> None:
    batch = await post(
        client,
        "/outsourcing/batches",
        batch_body(planned, allocations=[{"component_id": planned["component"], "quantity": "40"}]),
    )
    order = (await client.get(f"{API}/orders/{planned['order']}")).json()
    line = order["lines"][0]

    cut = await patch(
        client,
        f"/orders/{order['id']}/lines/{line['id']}",
        {"version": line["version"], "quantity": "30"},
        expect=409,
    )
    assert "allocated" in cut["detail"]
    removed = await put(
        client,
        f"/orders/{order['id']}/lines/{line['id']}/dependencies",
        {"order_version": order["version"], "components": [], "operations": []},
        expect=409,
    )
    assert batch["number"] in removed["detail"]

    closed = await act(
        client,
        f"/orders/{order['id']}/lines/{line['id']}/short-close",
        {"version": line["version"], "reason": "Customer reduced the schedule"},
    )
    assert closed["lines"][0]["components"][0]["allocations"] == []
    batch = (await client.get(f"{API}/outsourcing/batches/{batch['id']}")).json()
    assert (batch["allocated_qty"], batch["allocations"]) == ("0", [])
    [event] = await events("orders.line_short_closed")
    assert event.details["released_allocations"][0]["batch"] == "OB-00001"


async def test_candidates_list_uncovered_needs_at_the_site(
    client: AsyncClient, planned: dict[str, str]
) -> None:
    params = {"item_id": planned["casting"], "site_id": planned["site"]}
    [candidate] = (await client.get(f"{API}/outsourcing/candidates", params=params)).json()
    assert (
        candidate["order_number"],
        candidate["open_qty"],
        candidate["outsourced_operation"],
    ) == (
        "SO-00001",
        "40",
        "Powder coating",
    )
    await post(
        client,
        "/outsourcing/batches",
        batch_body(planned, allocations=[{"component_id": planned["component"], "quantity": "25"}]),
    )
    [candidate] = (await client.get(f"{API}/outsourcing/candidates", params=params)).json()
    assert (candidate["allocated_qty"], candidate["open_qty"]) == ("25", "15")


async def test_batch_permissions_and_scope(
    client: AsyncClient,
    planned: dict[str, str],
    add_member: AddMember,
    workspace_records: dict[str, object],
) -> None:
    site = workspace_records["site_id"]
    batch = await post(client, "/outsourcing/batches", batch_body(planned))
    hosur = await post(client, "/organization/sites", {"name": "Hosur Plant"})
    for email, role, sites in [
        ("buyer@example.com", "procurement", [site]),
        ("coordinator@example.com", "production_coordinator", [site]),
        ("stores@example.com", "stores", [site]),
        ("hosur@example.com", "procurement", [uuid.UUID(hosur["id"])]),
    ]:
        await add_member(email, role, site_ids=sites)
    await add_member(
        "rival@example.com",
        "owner",
        tenant_id=workspace_records["other_tenant_id"],
        home_site_id=workspace_records["other_site_id"],
    )

    await sign_in_as(client, "buyer@example.com")
    created = await post(client, "/outsourcing/batches", batch_body(planned, quantity="10"))
    assert created["number"] == "OB-00002"

    for email in ("coordinator@example.com", "stores@example.com"):
        await sign_in_as(client, email)
        assert (await client.get(f"{API}/outsourcing/batches")).json()["total"] == 2
        await post(client, "/outsourcing/batches", batch_body(planned), expect=403)
        await act(
            client,
            f"/outsourcing/batches/{batch['id']}/cancel",
            {"version": batch["version"], "reason": "Not my call"},
            expect=403,
        )

    for email in ("hosur@example.com", "rival@example.com"):
        await sign_in_as(client, email)
        assert (await client.get(f"{API}/outsourcing/batches")).json()["total"] == 0
        assert (await client.get(f"{API}/outsourcing/batches/{batch['id']}")).status_code == 404
        await act(
            client,
            f"/outsourcing/batches/{batch['id']}/cancel",
            {"version": batch["version"], "reason": "Not my site"},
            expect=404,
        )
        await post(client, "/outsourcing/batches", batch_body(planned), expect=422)
        candidates = await client.get(
            f"{API}/outsourcing/candidates",
            params={"item_id": planned["casting"], "site_id": planned["site"]},
        )
        assert candidates.json() == []
