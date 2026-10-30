"""Slice G2: basic stock per warehouse, used by delivery risk and dispatch (ADR-0010)."""

# ruff: noqa: F811  (pytest fixtures are imported and then used as parameters)

import uuid

import pytest
from conftest import AddMember, sign_in_as
from httpx import AsyncClient
from sqlalchemy import select
from test_dispatch import accept, dispatch_body, line_of, readiness  # noqa: F401
from test_orders import API, act, data, post  # noqa: F401
from test_risk import calendar, day, order_risk, put, scene, supplier_says  # noqa: F401

from app.main import app
from app.models import AuditEvent, StockMovement


async def warehouse(client: AsyncClient, site: str, code: str) -> str:
    created = await post(
        client, "/master-data/warehouses", {"code": code, "name": f"Store {code}", "site_id": site}
    )
    return created["id"]


async def enter(client: AsyncClient, wh: str, item: str, kind: str, qty: str, expect=201, **extra):
    body = {
        "submission_key": str(uuid.uuid4()),
        "warehouse_id": wh,
        "item_id": item,
        "kind": kind,
        "quantity": qty,
        "movement_date": day(0),
        **extra,
    }
    return await post(client, "/stock/movements", body, expect=expect)


async def on_hand(client: AsyncClient, item: str) -> dict[str, str]:
    summary = (await client.get(f"{API}/stock/balances?item_id={item}")).json()
    return {b["warehouse_code"]: b["on_hand"] for b in summary["balances"]}


async def stock_actions() -> list[str]:
    async with app.state.session_factory() as db:
        events = await db.scalars(select(AuditEvent).order_by(AuditEvent.created_at))
        return [e.action for e in events if e.action.startswith("stock.")]


@pytest.fixture
async def stores(client: AsyncClient, scene: dict) -> dict:
    """The risk scene plus two warehouses at the site."""
    return {
        **scene,
        "w1": await warehouse(client, scene["site"], "FG1"),
        "w2": await warehouse(client, scene["site"], "FG2"),
    }


# The ledger --------------------------------------------------------------------------


async def test_receipts_and_issues_post_at_once_and_never_go_below_zero(
    client: AsyncClient, stores: dict
) -> None:
    pump, w1 = stores["pump"], stores["w1"]
    received = await enter(client, w1, pump, "receipt", "30", reference="GRN-1")
    assert (received["status"], received["quantity"], received["balance_after"]) == (
        "posted",
        "30",
        "30",
    )
    blocked = await enter(client, w1, pump, "issue", "40", expect=409, reason="Sample")
    assert "Only 30 PCS PUMP-5HP in FG1" in blocked["detail"]
    assert "cannot go below zero" in blocked["detail"]
    await enter(client, w1, pump, "issue", "10", expect=422)  # an issue needs a reason
    await enter(client, w1, pump, "issue", "2.5", expect=422, reason="Sample")  # PCS: whole
    issued = await enter(client, w1, pump, "issue", "10", reason="Sample to customer")
    assert (issued["quantity"], issued["balance_after"]) == ("-10", "20")
    assert await on_hand(client, pump) == {"FG1": "20"}
    await enter(client, w1, pump, "receipt", "1", expect=422, movement_date=day(1))
    await enter(client, w1, pump, "adjustment", "1", expect=422, reason="Count")  # direction
    await enter(client, w1, pump, "receipt", "1", expect=422, direction="in")
    assert await stock_actions() == ["stock.posted", "stock.posted"]


async def test_opening_balances_and_adjustments_need_someone_elses_approval(
    client: AsyncClient, stores: dict, add_member: AddMember, workspace_records: dict
) -> None:
    pump, w1 = stores["pump"], stores["w1"]
    site = workspace_records["site_id"]
    await add_member("stores@example.com", "stores", site_ids=[site])
    await add_member("approver@example.com", "approver", site_ids=[site])

    opening = await enter(client, w1, pump, "opening", "50", reason="Count on 1 Oct")
    assert (opening["status"], opening["balance_after"], opening["can_decide"]) == (
        "pending_approval",
        None,
        False,
    )
    assert await on_hand(client, pump) == {}  # nothing counts before approval
    path = f"/stock/movements/{opening['id']}"
    own = await act(client, f"{path}/approve", {"version": opening["version"]}, 403)
    assert "you made" in own["detail"]
    await enter(client, w1, pump, "opening", "5", expect=409)  # one opening per warehouse

    await sign_in_as(client, "stores@example.com")
    await act(client, f"{path}/approve", {"version": opening["version"]}, 403)  # no permission
    await sign_in_as(client, "approver@example.com")
    await enter(client, w1, pump, "receipt", "5", expect=403)  # approvers do not enter stock
    assert (await client.get(f"{API}/stock/balances")).json()["pending_for_me"] == 1
    [listed] = (await client.get(f"{API}/stock/movements?status=pending_approval")).json()
    assert listed["can_decide"] is True
    approved = await act(
        client, f"{path}/approve", {"version": opening["version"], "note": "Matches count"}
    )
    assert (approved["status"], approved["balance_after"], approved["decided_by_label"]) == (
        "posted",
        "50",
        "approver <approver@example.com>",
    )

    await sign_in_as(client, "stores@example.com")
    too_much = await enter(client, w1, pump, "adjustment", "60", direction="out", reason="Scrap")
    damaged = await enter(client, w1, pump, "adjustment", "5", direction="out", reason="Damaged")
    found = await enter(client, w1, pump, "adjustment", "2", direction="in", reason="Found")
    await sign_in_as(client, "approver@example.com")
    refused = await act(
        client, f"/stock/movements/{too_much['id']}/approve", {"version": too_much["version"]}, 409
    )
    assert "cannot go below zero" in refused["detail"]
    await act(client, f"/stock/movements/{damaged['id']}/approve", {"version": damaged["version"]})
    rejected = await act(
        client,
        f"/stock/movements/{found['id']}/reject",
        {"version": found["version"], "reason": "Already counted"},
    )
    assert rejected["status"] == "rejected"
    await act(
        client, f"/stock/movements/{found['id']}/approve", {"version": rejected["version"]}, 409
    )
    assert await on_hand(client, pump) == {"FG1": "45"}
    assert await stock_actions() == [
        "stock.approval_requested",
        "stock.approved",
        "stock.approval_requested",
        "stock.approval_requested",
        "stock.approval_requested",
        "stock.approved",
        "stock.rejected",
    ]


async def test_a_posted_entry_is_reversed_once_by_a_counter_entry(
    client: AsyncClient, stores: dict
) -> None:
    pump, w1 = stores["pump"], stores["w1"]
    received = await enter(client, w1, pump, "receipt", "10")
    assert received["can_reverse"] is True
    path = f"/stock/movements/{received['id']}/reverse"
    body = {"version": received["version"], "submission_key": str(uuid.uuid4()), "reason": "x"}
    await post(client, path, body, expect=422)  # a reason of at least 3 characters
    body["reason"] = "Wrong item booked"
    reversal = await post(client, path, body)
    assert (reversal["kind"], reversal["quantity"], reversal["balance_after"]) == (
        "reversal",
        "-10",
        "0",
    )
    assert (await post(client, path, body, expect=200))["id"] == reversal["id"]  # replayed
    again = await post(client, path, {**body, "submission_key": str(uuid.uuid4())}, expect=409)
    assert "already been reversed" in again["detail"]
    await post(
        client,
        f"/stock/movements/{reversal['id']}/reverse",
        {"version": reversal["version"], "submission_key": str(uuid.uuid4()), "reason": "Undo"},
        expect=409,
    )
    history = (await client.get(f"{API}/stock/movements?item_id={pump}")).json()
    assert [(m["kind"], m["reversed"]) for m in history] == [
        ("reversal", False),
        ("receipt", True),
    ]
    # Reversing an entry that needed approval needs approval too.
    opening = await enter(client, w1, pump, "opening", "3")
    async with app.state.session_factory() as db:
        movement = await db.get(StockMovement, uuid.UUID(opening["id"]))
        movement.status = "posted"  # as if a colleague had approved it
        await db.commit()
    opening = (await client.get(f"{API}/stock/movements?item_id={pump}")).json()[0]
    pending = await post(
        client,
        f"/stock/movements/{opening['id']}/reverse",
        {"version": opening["version"], "submission_key": str(uuid.uuid4()), "reason": "Typo"},
    )
    assert pending["status"] == "pending_approval"


async def test_a_repeated_entry_is_recorded_once(client: AsyncClient, stores: dict) -> None:
    body = {
        "submission_key": str(uuid.uuid4()),
        "warehouse_id": stores["w1"],
        "item_id": stores["pump"],
        "kind": "receipt",
        "quantity": "4",
        "movement_date": day(0),
    }
    first = await post(client, "/stock/movements", body)
    second = await post(client, "/stock/movements", body, expect=200)
    assert first["id"] == second["id"]
    assert await on_hand(client, stores["pump"]) == {"FG1": "4"}


async def test_stock_is_limited_to_the_users_sites(
    client: AsyncClient, stores: dict, add_member: AddMember, workspace_records: dict
) -> None:
    second = await post(client, "/organization/sites", {"name": "Hosur Plant"})
    far = await warehouse(client, second["id"], "HSR")
    await enter(client, far, stores["pump"], "receipt", "7")
    await enter(client, stores["w1"], stores["pump"], "receipt", "3")
    await add_member("stores@example.com", "stores", site_ids=[workspace_records["site_id"]])
    await add_member("qc@example.com", "quality", site_ids=[workspace_records["site_id"]])

    await sign_in_as(client, "stores@example.com")
    assert await on_hand(client, stores["pump"]) == {"FG1": "3"}
    assert len((await client.get(f"{API}/stock/movements")).json()) == 1
    hidden = await enter(client, far, stores["pump"], "receipt", "1", expect=404)
    assert hidden["detail"] == "Warehouse not found"
    await sign_in_as(client, "qc@example.com")
    await enter(client, stores["w1"], stores["pump"], "receipt", "1", expect=403)


# Delivery risk ------------------------------------------------------------------------


async def test_finished_goods_stock_covers_lines_in_promise_order(
    client: AsyncClient, stores: dict
) -> None:
    await calendar(client, stores["site"])
    early, late = (
        await order_risk(client, stores["early"]),
        await order_risk(client, stores["late"]),
    )
    assert early["stock_tracked"] is False  # nothing entered for the pump yet
    await enter(client, stores["w1"], stores["pump"], "receipt", "30")
    await enter(client, stores["w2"], stores["pump"], "receipt", "20")

    early = await order_risk(client, stores["early"])
    assert (early["stock_tracked"], early["from_stock"], early["headline"]) == (True, "40", "ready")
    assert early["components"][0]["required"] == "0"  # nothing left to build
    assert early["projected_date"] == day(0)
    late = await order_risk(client, stores["late"])
    assert (late["from_stock"], late["stock_ahead"]) == ("10", [stores["early"]["number"] + "/1"])
    assert late["components"][0]["required"] == "50"  # 60 open, 10 from stock


async def test_component_stock_limits_risk_and_dispatch_and_comes_back_on_cancel(
    client: AsyncClient, stores: dict
) -> None:
    units = (await client.get(f"{API}/master-data/units")).json()["items"]
    pcs = next(u for u in units if u["code"] == "PCS")
    motor = await post(
        client,
        "/master-data/items",
        {"code": "MOTOR", "name": "Motor", "item_type": "component", "base_unit_id": pcs["id"]},
    )
    early = stores["early"]
    order = (await client.get(f"{API}/orders/{early['id']}")).json()
    await put(
        client,
        f"/orders/{early['id']}/lines/{line_of(early)}/dependencies",
        {
            "order_version": order["version"],
            "components": [
                {
                    "item_id": stores["casting"],
                    "qty_per_unit": "1",
                    "outsourced_operation": "Powder coating",
                },
                {"item_id": motor["id"], "qty_per_unit": "1"},
            ],
            "operations": [{"name": "Assembly", "kind": "in_house", "duration_minutes": 480}],
        },
    )
    risk = await order_risk(client, early)
    assert [c["stock_tracked"] for c in risk["components"]] == [False, False]  # assumed

    await enter(client, stores["w1"], motor["id"], "receipt", "30")
    risk = await order_risk(client, early)
    motor_view = risk["components"][1]
    assert (motor_view["stock_tracked"], motor_view["in_stock"], motor_view["usable_now"]) == (
        True,
        "30",
        "30",
    )
    assert risk["headline"] == "quantity_shortage"
    assert any("Only 30 of the 40 PCS MOTOR" in i["message"] for i in risk["issues"])

    await accept(client, stores, accepted="100", held="0")
    ready = await readiness(client, early)
    assert ready["shippable"] == "30"  # castings for 40, motors for 30
    assert [c["source"] for c in ready["components"]] == ["batch", "stock"]
    note = await post(client, "/dispatch", dispatch_body(early, (line_of(early), "30")))
    assert await on_hand(client, motor["id"]) == {"FG1": "0"}
    [used] = (await client.get(f"{API}/stock/movements?item_id={motor['id']}")).json()[:1]
    assert (used["kind"], used["quantity"], used["dispatch_number"], used["can_reverse"]) == (
        "dispatch",
        "-30",
        note["number"],
        False,
    )
    await act(
        client,
        f"/dispatch/{note['id']}/cancel",
        {"version": note["version"], "reason": "Truck turned back"},
    )
    assert await on_hand(client, motor["id"]) == {"FG1": "30"}
    assert (await readiness(client, early))["shippable"] == "30"


async def test_dispatch_uses_finished_goods_first_from_the_fullest_warehouse(
    client: AsyncClient, stores: dict
) -> None:
    pump = stores["pump"]
    await enter(client, stores["w1"], pump, "receipt", "15")
    await enter(client, stores["w2"], pump, "receipt", "10")
    # Castings in stock never count for a component that needs an outsourced step.
    await enter(client, stores["w1"], stores["casting"], "receipt", "500")
    await accept(client, stores, accepted="20", held="80")
    early = stores["early"]
    ready = await readiness(client, early)
    assert (ready["finished_stock"], ready["shippable"]) == ("25", "40")  # 25 stock + 15 built
    assert [c["source"] for c in ready["components"]] == ["batch"]
    assert (await order_risk(client, early))["components"][0]["stock_tracked"] is False
    first = await post(client, "/dispatch", dispatch_body(early, (line_of(early), "5")))
    assert await on_hand(client, pump) == {"FG1": "10", "FG2": "10"}  # fullest warehouse first
    await act(
        client, f"/dispatch/{first['id']}/cancel", {"version": first["version"], "reason": "Wrong"}
    )
    over = await post(client, "/dispatch", dispatch_body(early, (line_of(early), "40")))
    assert over["status"] == "posted"
    assert await on_hand(client, pump) == {"FG1": "0", "FG2": "0"}
    batch = (await client.get(f"{API}/outsourcing/batches/{stores['batch']['id']}")).json()
    early_share = next(a for a in batch["allocations"] if a["order_number"] == early["number"])
    assert early_share["quantity"] == "15"  # only the 15 castings built into pumps were used
    late = await order_risk(client, stores["late"])
    assert (late["stock_tracked"], late["from_stock"]) == (True, "0")
    await act(
        client, f"/dispatch/{over['id']}/cancel", {"version": over["version"], "reason": "Wrong"}
    )
    assert await on_hand(client, pump) == {"FG1": "15", "FG2": "10"}
