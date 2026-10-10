from decimal import Decimal

import pytest
from conftest import AddMember, csrf_headers, sign_in_as
from httpx import AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import AuditEvent

API = "/api/v1"


async def post(client: AsyncClient, path: str, body: dict, expect: int = 201) -> dict:
    response = await client.post(f"{API}{path}", headers=csrf_headers(client), json=body)
    assert response.status_code == expect, response.text
    return response.json()


@pytest.fixture
async def data(client: AsyncClient, workspace_records: dict[str, object]) -> dict[str, str]:
    """Owner signed in, with units, items and customers."""
    await sign_in_as(client, "owner@example.com")
    pcs = await post(
        client,
        "/master-data/units",
        {"code": "PCS", "name": "Pieces", "dimension": "count", "decimal_places": 0},
    )
    kg = await post(
        client,
        "/master-data/units",
        {"code": "KG", "name": "Kilogram", "dimension": "mass", "decimal_places": 3},
    )
    pump = await post(
        client,
        "/master-data/items",
        {
            "code": "PUMP-5HP",
            "name": "Pump",
            "item_type": "finished_good",
            "base_unit_id": pcs["id"],
        },
    )
    resin = await post(
        client,
        "/master-data/items",
        {"code": "RESIN", "name": "Resin", "item_type": "raw_material", "base_unit_id": kg["id"]},
    )
    acme = await post(client, "/master-data/customers", {"code": "ACME", "name": "Acme"})
    bharat = await post(client, "/master-data/customers", {"code": "BHARAT", "name": "Bharat"})
    return {
        "site": str(workspace_records["site_id"]),
        "pump": pump["id"],
        "resin": resin["id"],
        "acme": acme["id"],
        "bharat": bharat["id"],
    }


def order_body(data: dict[str, str], **overrides) -> dict:
    body = {
        "site_id": data["site"],
        "customer_id": data["acme"],
        "customer_reference": "PO-7781",
        "lines": [
            {"item_id": data["pump"], "quantity": "40", "requested_date": "2026-11-10"},
            {
                "item_id": data["resin"],
                "quantity": "12.5",
                "requested_date": "2026-11-20",
                "promised_date": "2026-11-25",
            },
        ],
    }
    body.update(overrides)
    return body


async def act(client: AsyncClient, path: str, body: dict, expect: int = 200) -> dict:
    return await post(client, path, body, expect)


async def patch(client: AsyncClient, path: str, body: dict, expect: int = 200) -> dict:
    response = await client.patch(f"{API}{path}", headers=csrf_headers(client), json=body)
    assert response.status_code == expect, response.text
    return response.json()


def reconciles(line: dict) -> bool:
    parts = ("shipped_qty", "cancelled_qty", "short_closed_qty", "remaining_qty")
    return Decimal(line["ordered_qty"]) == sum(Decimal(line[p]) for p in parts)


async def confirmed_order(
    client: AsyncClient, data: dict[str, str], reference: str = "PO-C1"
) -> dict:
    order = await post(client, "/orders", order_body(data, customer_reference=reference))
    line = order["lines"][0]
    order = await patch(
        client,
        f"/orders/{order['id']}/lines/{line['id']}",
        {"version": line["version"], "promised_date": "2026-11-15"},
    )
    return await act(client, f"/orders/{order['id']}/confirm", {"version": order["version"]})


# Creating and numbering


async def test_create_draft_order_with_number_and_reconciled_lines(
    client: AsyncClient, data: dict[str, str]
) -> None:
    order = await post(client, "/orders", order_body(data))

    assert (order["number"], order["status"], order["customer_code"]) == (
        "SO-00001",
        "draft",
        "ACME",
    )
    assert [line["line_no"] for line in order["lines"]] == [1, 2]
    assert order["lines"][1]["unit_code"] == "KG"
    assert (order["lines"][0]["ordered_qty"], order["lines"][1]["ordered_qty"]) == ("40", "12.500")
    assert all(
        reconciles(line) and line["remaining_qty"] == line["ordered_qty"] for line in order["lines"]
    )
    second = await post(client, "/orders", order_body(data, customer_reference="PO-7782"))
    assert second["number"] == "SO-00002"
    async with app.state.session_factory() as db:
        event = await db.scalar(select(AuditEvent).where(AuditEvent.action == "orders.created"))
    assert event.details["number"] == "SO-00001"
    assert len(event.details["lines"]) == 2


@pytest.mark.parametrize(
    ("item_key", "quantity"),
    [("pump", "2.5"), ("resin", "1.2345"), ("pump", "0"), ("pump", "-3")],
)
async def test_quantity_must_be_positive_and_respect_unit_precision(
    client: AsyncClient, data: dict[str, str], item_key: str, quantity: str
) -> None:
    body = order_body(
        data,
        lines=[{"item_id": data[item_key], "quantity": quantity, "requested_date": "2026-11-10"}],
    )
    await post(client, "/orders", body, expect=422)


async def test_unknown_or_inactive_references_are_rejected(
    client: AsyncClient, data: dict[str, str], workspace_records: dict[str, object]
) -> None:
    await patch(
        client, f"/master-data/customers/{data['bharat']}", {"version": 1, "status": "inactive"}
    )
    await post(client, "/orders", order_body(data, customer_id=data["bharat"]), expect=422)
    await post(
        client,
        "/orders",
        order_body(data, site_id=str(workspace_records["other_site_id"])),
        expect=422,
    )
    await post(
        client,
        "/orders",
        order_body(
            data, lines=[{"item_id": data["acme"], "quantity": "1", "requested_date": "2026-11-10"}]
        ),
        expect=422,
    )
    await post(client, "/orders", order_body(data, lines=[]), expect=422)


async def test_customer_reference_is_unique_per_customer(
    client: AsyncClient, data: dict[str, str]
) -> None:
    await post(client, "/orders", order_body(data))
    await post(client, "/orders", order_body(data), expect=409)
    await post(client, "/orders", order_body(data, customer_id=data["bharat"]))
    await post(client, "/orders", order_body(data, customer_reference=None))
    await post(client, "/orders", order_body(data, customer_reference=None))


# Confirming and promises


async def test_confirm_requires_a_promise_on_every_line(
    client: AsyncClient, data: dict[str, str]
) -> None:
    order = await post(client, "/orders", order_body(data))
    refused = await client.post(
        f"{API}/orders/{order['id']}/confirm",
        headers=csrf_headers(client),
        json={"version": order["version"]},
    )
    assert refused.status_code == 422
    assert "line 1" in refused.json()["detail"]

    order = await confirmed_order(client, data)
    assert order["status"] == "confirmed" and order["confirmed_at"]
    histories = [line["promise_history"] for line in order["lines"]]
    assert [(h[0]["reason_code"], h[0]["previous_date"], h[0]["new_date"]) for h in histories] == [
        ("initial", None, "2026-11-15"),
        ("initial", None, "2026-11-25"),
    ]
    assert histories[0][0]["changed_by_label"] == "A. Owner <owner@example.com>"


async def test_promise_changes_need_a_reason_and_keep_history(
    client: AsyncClient, data: dict[str, str]
) -> None:
    order = await confirmed_order(client, data)
    line = order["lines"][0]
    path = f"/orders/{order['id']}/lines/{line['id']}"

    await patch(
        client, path, {"version": line["version"], "promised_date": "2026-12-01"}, expect=409
    )
    await act(
        client,
        f"{path}/promise",
        {"version": line["version"], "new_date": "2026-12-01", "reason_code": "initial"},
        expect=422,
    )
    await act(
        client,
        f"{path}/promise",
        {"version": line["version"], "new_date": "2026-11-15", "reason_code": "supplier_delay"},
        expect=422,
    )
    changed = await act(
        client,
        f"{path}/promise",
        {
            "version": line["version"],
            "new_date": "2026-12-01",
            "reason_code": "supplier_delay",
            "note": "Coating batch OB-00007 returned short",
        },
    )
    stale = await client.post(
        f"{API}{path}/promise",
        headers=csrf_headers(client),
        json={"version": line["version"], "new_date": "2026-12-05", "reason_code": "capacity"},
    )

    new_line = changed["lines"][0]
    assert new_line["promised_date"] == "2026-12-01"
    assert [
        (h["previous_date"], h["new_date"], h["reason_code"]) for h in new_line["promise_history"]
    ] == [(None, "2026-11-15", "initial"), ("2026-11-15", "2026-12-01", "supplier_delay")]
    assert new_line["promise_history"][1]["note"] == "Coating batch OB-00007 returned short"
    assert stale.status_code == 409
    async with app.state.session_factory() as db:
        event = await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "orders.promise_changed")
        )
    assert (event.details["from"], event.details["to"]) == ("2026-11-15", "2026-12-01")


async def test_amending_a_confirmed_order_is_audited(
    client: AsyncClient, data: dict[str, str]
) -> None:
    order = await confirmed_order(client, data)
    line = order["lines"][0]
    amended = await patch(
        client,
        f"/orders/{order['id']}/lines/{line['id']}",
        {"version": line["version"], "quantity": "45"},
    )
    without_promise = await client.post(
        f"{API}/orders/{order['id']}/lines",
        headers=csrf_headers(client),
        json={
            "order_version": amended["version"],
            "item_id": data["pump"],
            "quantity": "5",
            "requested_date": "2026-12-01",
        },
    )
    added = await post(
        client,
        f"/orders/{order['id']}/lines",
        {
            "order_version": amended["version"],
            "item_id": data["pump"],
            "quantity": "5",
            "requested_date": "2026-12-01",
            "promised_date": "2026-12-03",
        },
    )

    assert amended["lines"][0]["ordered_qty"] == "45"
    assert without_promise.status_code == 422
    assert added["lines"][2]["promise_history"][0]["reason_code"] == "initial"
    async with app.state.session_factory() as db:
        events = (
            await db.scalars(select(AuditEvent).where(AuditEvent.action == "orders.line_updated"))
        ).all()
    assert [e.details["amendment"] for e in events] == [False, True]
    event = events[-1]
    assert (event.details["before"]["quantity"], event.details["after"]["quantity"]) == ("40", "45")


# Closing


async def test_short_close_reconciles_and_closes_the_order(
    client: AsyncClient, data: dict[str, str]
) -> None:
    order = await confirmed_order(client, data)
    first, second = order["lines"]
    await act(
        client,
        f"/orders/{order['id']}/lines/{first['id']}/short-close",
        {"version": first["version"], "reason": "x"},
        expect=422,
    )
    partly = await act(
        client,
        f"/orders/{order['id']}/lines/{first['id']}/short-close",
        {"version": first["version"], "reason": "Customer reduced the call-off"},
    )
    assert partly["status"] == "confirmed"
    line = partly["lines"][0]
    assert (line["status"], line["short_closed_qty"], line["remaining_qty"]) == (
        "short_closed",
        "40",
        "0",
    )
    assert reconciles(line)

    await patch(
        client,
        f"/orders/{order['id']}/lines/{first['id']}",
        {"version": line["version"], "quantity": "50"},
        expect=409,
    )
    done = await act(
        client,
        f"/orders/{order['id']}/lines/{second['id']}/short-close",
        {"version": second["version"], "reason": "Material discontinued"},
    )
    assert done["status"] == "closed"
    await act(
        client,
        f"/orders/{order['id']}/cancel",
        {"version": done["version"], "reason": "Too late"},
        expect=409,
    )


async def test_cancel_moves_open_quantity_to_cancelled(
    client: AsyncClient, data: dict[str, str]
) -> None:
    draft = await post(client, "/orders", order_body(data))
    cancelled = await act(
        client,
        f"/orders/{draft['id']}/cancel",
        {"version": draft["version"], "reason": "Entered twice"},
    )
    assert cancelled["status"] == "cancelled"
    assert cancelled["status_reason"] == "Entered twice"
    assert all(
        line["status"] == "cancelled" and Decimal(line["remaining_qty"]) == 0 and reconciles(line)
        for line in cancelled["lines"]
    )

    confirmed = await confirmed_order(client, {**data, "acme": data["bharat"]})
    after = await act(
        client,
        f"/orders/{confirmed['id']}/cancel",
        {"version": confirmed["version"], "reason": "Customer withdrew"},
    )
    assert after["status"] == "cancelled"


async def test_lines_are_removed_only_from_drafts(
    client: AsyncClient, data: dict[str, str]
) -> None:
    order = await post(client, "/orders", order_body(data))
    first, second = order["lines"]
    removed = await client.delete(
        f"{API}/orders/{order['id']}/lines/{second['id']}",
        params={"version": second["version"]},
        headers=csrf_headers(client),
    )
    last = await client.delete(
        f"{API}/orders/{order['id']}/lines/{first['id']}",
        params={"version": first["version"]},
        headers=csrf_headers(client),
    )
    assert removed.status_code == 200 and len(removed.json()["lines"]) == 1
    assert last.status_code == 409

    confirmed = await confirmed_order(client, {**data, "acme": data["bharat"]})
    line = confirmed["lines"][1]
    blocked = await client.delete(
        f"{API}/orders/{confirmed['id']}/lines/{line['id']}",
        params={"version": line["version"]},
        headers=csrf_headers(client),
    )
    assert blocked.status_code == 409


# Listing, scope and permissions


async def test_list_search_and_status_filter(client: AsyncClient, data: dict[str, str]) -> None:
    await post(client, "/orders", order_body(data))
    await confirmed_order(client, {**data, "acme": data["bharat"]})

    everything = (await client.get(f"{API}/orders")).json()
    by_ref = (await client.get(f"{API}/orders", params={"q": "PO-"})).json()
    one_ref = (await client.get(f"{API}/orders", params={"q": "7781"})).json()
    by_customer = (await client.get(f"{API}/orders", params={"q": "bharat"})).json()
    confirmed = (await client.get(f"{API}/orders", params={"status": "confirmed"})).json()

    assert everything["total"] == 2
    assert by_ref["total"] == 2
    assert one_ref["total"] == 1
    assert [o["customer_code"] for o in by_customer["items"]] == ["BHARAT"]
    summary = confirmed["items"][0]
    assert (summary["line_count"], summary["open_lines"], summary["next_promised_date"]) == (
        2,
        2,
        "2026-11-15",
    )


async def test_site_scope_and_permissions(
    client: AsyncClient,
    data: dict[str, str],
    add_member: AddMember,
    workspace_records: dict[str, object],
) -> None:
    hosur = await post(client, "/organization/sites", {"name": "Hosur Plant"})
    main_order = await post(client, "/orders", order_body(data))
    hosur_order = await post(
        client, "/orders", order_body(data, site_id=hosur["id"], customer_reference="PO-H1")
    )
    await add_member("viewer@example.com", "read_only", site_ids=[workspace_records["site_id"]])
    await sign_in_as(client, "viewer@example.com")

    listing = (await client.get(f"{API}/orders")).json()
    assert [o["number"] for o in listing["items"]] == [main_order["number"]]
    assert (await client.get(f"{API}/orders/{hosur_order['id']}")).status_code == 404
    assert (await client.get(f"{API}/orders/{main_order['id']}")).status_code == 200
    await post(client, "/orders", order_body(data, customer_reference="PO-X"), expect=403)
    await act(
        client,
        f"/orders/{main_order['id']}/cancel",
        {"version": main_order["version"], "reason": "Not mine"},
        expect=403,
    )


async def test_other_tenant_cannot_reach_orders(
    client: AsyncClient,
    data: dict[str, str],
    add_member: AddMember,
    workspace_records: dict[str, object],
) -> None:
    order = await post(client, "/orders", order_body(data))
    await add_member(
        "rival@example.com",
        "owner",
        tenant_id=workspace_records["other_tenant_id"],
        home_site_id=workspace_records["other_site_id"],
    )
    await sign_in_as(client, "rival@example.com")

    assert (await client.get(f"{API}/orders")).json()["total"] == 0
    assert (await client.get(f"{API}/orders/{order['id']}")).status_code == 404
    await act(
        client,
        f"/orders/{order['id']}/cancel",
        {"version": order["version"], "reason": "Sabotage"},
        expect=404,
    )


# Import

IMPORT = (
    "customer_reference,customer_code,item_code,quantity,requested_date,promised_date\n"
    "PO-1,acme,PUMP-5HP,40,2026-11-10,2026-11-15\n"
    "PO-1,ACME,RESIN,12.5,2026-11-20,\n"
    "PO-2,BHARAT,PUMP-5HP,10,2026-12-01,2026-12-05\n"
)


async def run_import(client, data, text, commit, expect=200):
    response = await client.post(
        f"{API}/orders/import",
        headers=csrf_headers(client),
        json={"site_id": data["site"], "csv_text": text, "commit": commit},
    )
    assert response.status_code == expect, response.text
    return response.json()


async def test_import_groups_rows_into_draft_orders_and_reruns_safely(
    client: AsyncClient, data: dict[str, str]
) -> None:
    preview = await run_import(client, data, IMPORT, commit=False)
    assert (preview["orders_to_create"], preview["lines_to_create"], preview["errors"]) == (
        2,
        3,
        [],
    )
    assert (await client.get(f"{API}/orders")).json()["total"] == 0

    first = await run_import(client, data, IMPORT, commit=True)
    again = await run_import(client, data, IMPORT, commit=True)

    assert first["created_numbers"] == ["SO-00001", "SO-00002"]
    assert (again["orders_to_create"], again["unchanged_orders"]) == (0, 2)
    orders = (await client.get(f"{API}/orders", params={"status": "draft"})).json()
    assert orders["total"] == 2
    detail = (await client.get(f"{API}/orders/{orders['items'][-1]['id']}")).json()
    assert [line["item_code"] for line in detail["lines"]] == ["PUMP-5HP", "RESIN"]


async def test_import_errors_block_the_whole_file(
    client: AsyncClient, data: dict[str, str]
) -> None:
    bad = (
        "customer_reference,customer_code,item_code,quantity,requested_date,order_date\n"
        "PO-9,ACME,PUMP-5HP,40,2026-11-10,2026-10-01\n"
        "PO-9,ACME,PUMP-5HP,2.5,2026-11-10,2026-10-02\n"
        "PO-8,NOBODY,PUMP-5HP,1,2026-11-10,\n"
        "PO-7,ACME,GHOST,1,2026-11-10,\n"
        "PO-6,ACME,PUMP-5HP,many,10/11/2026,\n"
        ",ACME,PUMP-5HP,1,2026-11-10,\n"
    )
    report = await run_import(client, data, bad, commit=True, expect=422)
    fields = {(e["row"], e["field"]) for e in report["errors"]}
    assert {
        (3, "quantity"),
        (4, "customer_code"),
        (5, "item_code"),
        (6, "quantity"),
        (6, "requested_date"),
        (7, "customer_reference"),
    } <= fields
    assert (await client.get(f"{API}/orders")).json()["total"] == 0

    conflicting = (
        "customer_reference,customer_code,item_code,quantity,requested_date,order_date\n"
        "PO-9,ACME,PUMP-5HP,40,2026-11-10,2026-10-01\n"
        "PO-9,ACME,PUMP-5HP,4,2026-11-10,2026-10-02\n"
    )
    report = await run_import(client, data, conflicting, commit=False)
    assert report["errors"][0]["field"] == "order_date"


async def test_import_refuses_to_change_an_existing_order(
    client: AsyncClient, data: dict[str, str]
) -> None:
    await run_import(client, data, IMPORT, commit=True)
    changed = IMPORT.replace("PO-2,BHARAT,PUMP-5HP,10", "PO-2,BHARAT,PUMP-5HP,11")
    report = await run_import(client, data, changed, commit=False)
    assert report["errors"][0]["field"] == "customer_reference"
    assert "SO-00002" in report["errors"][0]["message"]
