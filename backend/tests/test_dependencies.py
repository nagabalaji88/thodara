"""Slice F2: what each customer-order line depends on."""

import uuid

import pytest
from conftest import AddMember, csrf_headers, sign_in_as
from httpx import AsyncClient
from sqlalchemy import select
from test_orders import API, act, data, patch, post  # noqa: F401  (data is a fixture)

from app.main import app
from app.models import AuditEvent


async def put(client: AsyncClient, path: str, body: dict, expect: int = 200) -> dict:
    response = await client.put(f"{API}{path}", headers=csrf_headers(client), json=body)
    assert response.status_code == expect, response.text
    return response.json()


@pytest.fixture
async def flow(client: AsyncClient, data: dict[str, str]) -> dict[str, str]:  # noqa: F811
    """A confirmed order for 40 pumps, a casting component and a job-work coater."""
    units = (await client.get(f"{API}/master-data/units")).json()["items"]
    pcs = next(u for u in units if u["code"] == "PCS")
    casting = await post(
        client,
        "/master-data/items",
        {
            "code": "HSG-CAST",
            "name": "Housing casting",
            "item_type": "component",
            "base_unit_id": pcs["id"],
        },
    )
    coater = await post(
        client,
        "/master-data/suppliers",
        {"code": "COAT", "name": "Hosur Coaters", "provides_job_work": True},
    )
    trader = await post(client, "/master-data/suppliers", {"code": "TRADE", "name": "Traders"})
    order = await post(
        client,
        "/orders",
        {
            "site_id": data["site"],
            "customer_id": data["acme"],
            "customer_reference": "PO-FLOW",
            "lines": [
                {
                    "item_id": data["pump"],
                    "quantity": "40",
                    "requested_date": "2026-11-10",
                    "promised_date": "2026-11-12",
                }
            ],
        },
    )
    order = await act(client, f"/orders/{order['id']}/confirm", {"version": order["version"]})
    return {
        **data,
        "casting": casting["id"],
        "coater": coater["id"],
        "trader": trader["id"],
        "order": order["id"],
        "line": order["lines"][0]["id"],
    }


def dependencies(flow: dict[str, str], version: int, **overrides) -> dict:
    body = {
        "order_version": version,
        "components": [
            {
                "item_id": flow["casting"],
                "qty_per_unit": "1",
                "outsourced_operation": "Powder  coating",
            },
            {"item_id": flow["resin"], "qty_per_unit": "0.333"},
        ],
        "operations": [
            {"name": "Assembly", "kind": "in_house", "duration_minutes": 240},
            {"name": "Testing", "kind": "in_house", "duration_minutes": 60},
            {"name": "Truck to customer", "kind": "transport", "duration_minutes": 480},
        ],
    }
    body.update(overrides)
    return body


async def order(client: AsyncClient, flow: dict[str, str]) -> dict:
    return (await client.get(f"{API}/orders/{flow['order']}")).json()


def path(flow: dict[str, str]) -> str:
    return f"/orders/{flow['order']}/lines/{flow['line']}/dependencies"


async def test_dependencies_show_required_quantities_and_are_audited(
    client: AsyncClient, flow: dict[str, str]
) -> None:
    current = await order(client, flow)
    saved = await put(client, path(flow), dependencies(flow, current["version"]))

    line = saved["lines"][0]
    casting, resin = line["components"]
    assert (casting["item_code"], casting["required_qty"], casting["unit_code"]) == (
        "HSG-CAST",
        "40",
        "PCS",
    )
    assert casting["outsourced_operation"] == "Powder coating"
    # 0.333 kg x 40 = 13.32 kg, shown at the unit's three decimals.
    assert (resin["required_qty"], resin["unit_code"], resin["outsourced_operation"]) == (
        "13.320",
        "KG",
        None,
    )
    assert [(o["sequence"], o["name"], o["kind"]) for o in line["operations"]] == [
        (1, "Assembly", "in_house"),
        (2, "Testing", "in_house"),
        (3, "Truck to customer", "transport"),
    ]
    assert saved["version"] == current["version"] + 1
    async with app.state.session_factory() as db:
        event = await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "orders.dependencies_changed")
        )
    assert event.details["before"] == {"components": [], "operations": []}
    assert event.details["after"]["components"][1] == {
        "item_id": flow["resin"],
        "qty_per_unit": "0.333",
        "outsourced_operation": None,
    }


async def test_resaving_identical_dependencies_changes_nothing(
    client: AsyncClient, flow: dict[str, str]
) -> None:
    first = await put(
        client, path(flow), dependencies(flow, (await order(client, flow))["version"])
    )
    again = await put(client, path(flow), dependencies(flow, first["version"]))

    assert again["version"] == first["version"]
    async with app.state.session_factory() as db:
        events = (
            await db.scalars(
                select(AuditEvent).where(AuditEvent.action == "orders.dependencies_changed")
            )
        ).all()
    assert len(events) == 1


async def test_required_quantity_rounds_up_and_follows_the_open_quantity(
    client: AsyncClient, flow: dict[str, str]
) -> None:
    current = await order(client, flow)
    body = dependencies(
        flow,
        current["version"],
        components=[{"item_id": flow["casting"], "qty_per_unit": "0.51"}],
        operations=[],
    )
    saved = await put(client, path(flow), body)
    # 0.51 x 40 = 20.4 castings; a part of a piece cannot be sent, so 21 are needed.
    assert saved["lines"][0]["components"][0]["required_qty"] == "21"

    line = saved["lines"][0]
    closed = await act(
        client,
        f"/orders/{flow['order']}/lines/{flow['line']}/short-close",
        {"version": line["version"], "reason": "Customer reduced the schedule"},
    )
    assert closed["lines"][0]["components"][0]["required_qty"] == "0"


@pytest.mark.parametrize(
    "change, expect",
    [
        ({"components": [{"item_id": "casting", "qty_per_unit": "1"}] * 2}, 422),
        ({"components": [{"item_id": "pump", "qty_per_unit": "1"}]}, 422),
        ({"components": [{"item_id": "casting", "qty_per_unit": "0"}]}, 422),
        ({"components": [{"item_id": "acme", "qty_per_unit": "1"}]}, 422),
        ({"operations": [{"name": "Paint", "kind": "outsourced", "duration_minutes": 60}]}, 422),
        ({"operations": [{"name": "Paint", "kind": "in_house", "duration_minutes": 0}]}, 422),
        ({"operations": [{"name": " ", "kind": "in_house", "duration_minutes": 30}]}, 422),
        ({"order_version": 1}, 409),
    ],
)
async def test_invalid_dependencies_are_rejected(
    client: AsyncClient, flow: dict[str, str], change: dict, expect: int
) -> None:
    current = await order(client, flow)
    for key in ("components",):
        if key in change:
            change[key] = [{**c, "item_id": flow[c["item_id"]]} for c in change[key]]
    await put(client, path(flow), dependencies(flow, current["version"], **change), expect=expect)
    assert (await order(client, flow))["lines"][0]["components"] == []


async def test_inactive_items_and_closed_orders_cannot_take_dependencies(
    client: AsyncClient, flow: dict[str, str]
) -> None:
    await patch(
        client, f"/master-data/items/{flow['casting']}", {"version": 1, "status": "inactive"}
    )
    current = await order(client, flow)
    await put(client, path(flow), dependencies(flow, current["version"]), expect=422)

    cancelled = await act(
        client,
        f"/orders/{flow['order']}/cancel",
        {"version": current["version"], "reason": "Customer withdrew"},
    )
    body = dependencies(
        flow, cancelled["version"], components=[{"item_id": flow["resin"], "qty_per_unit": "1"}]
    )
    await put(client, path(flow), body, expect=409)


async def test_only_planners_change_dependencies(
    client: AsyncClient,
    flow: dict[str, str],
    add_member: AddMember,
    workspace_records: dict[str, object],
) -> None:
    site = workspace_records["site_id"]
    for email, role in [
        ("planner@example.com", "production_manager"),
        ("coordinator@example.com", "production_coordinator"),
        ("stores@example.com", "stores"),
    ]:
        await add_member(email, role, site_ids=[site])

    for email in ("coordinator@example.com", "stores@example.com"):
        await sign_in_as(client, email)
        current = await order(client, flow)
        await put(client, path(flow), dependencies(flow, current["version"]), expect=403)

    await sign_in_as(client, "planner@example.com")
    current = await order(client, flow)
    saved = await put(client, path(flow), dependencies(flow, current["version"]))
    assert len(saved["lines"][0]["components"]) == 2


async def test_dependencies_respect_site_and_tenant_scope(
    client: AsyncClient,
    flow: dict[str, str],
    add_member: AddMember,
    workspace_records: dict[str, object],
) -> None:
    current = await order(client, flow)
    await put(client, path(flow), dependencies(flow, current["version"]))
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
        await put(client, path(flow), dependencies(flow, current["version"] + 1), expect=404)
        template = (
            await client.get(f"{API}/orders/dependency-template", params={"item_id": flow["pump"]})
        ).json()
        assert template == {"source_order_number": None, "components": [], "operations": []}


async def test_template_copies_the_latest_dependencies_for_the_item(
    client: AsyncClient, flow: dict[str, str]
) -> None:
    empty = await client.get(f"{API}/orders/dependency-template", params={"item_id": flow["pump"]})
    assert empty.json()["source_order_number"] is None

    current = await order(client, flow)
    await put(client, path(flow), dependencies(flow, current["version"]))
    template = (
        await client.get(f"{API}/orders/dependency-template", params={"item_id": flow["pump"]})
    ).json()

    assert template["source_order_number"] == current["number"]
    assert [(c["item_code"], c["qty_per_unit"]) for c in template["components"]] == [
        ("HSG-CAST", "1"),
        ("RESIN", "0.333"),
    ]
    assert [o["name"] for o in template["operations"]] == [
        "Assembly",
        "Testing",
        "Truck to customer",
    ]
