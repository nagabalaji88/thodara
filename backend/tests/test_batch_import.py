"""Slice G6: importing outsourced batches; batch reference and material owner (ADR-0014)."""

# ruff: noqa: F811  (pytest fixtures are imported and then used as parameters)

import pytest
from conftest import AddMember, sign_in_as
from httpx import AsyncClient
from sqlalchemy import select
from test_orders import API, data, patch, post  # noqa: F401
from test_risk import confirmed, day, scene  # noqa: F401

from app.main import app
from app.models import AuditEvent, OutsourcedBatch

HEADER = (
    "supplier_code,item_code,operation,quantity,expected_return_date,sent_date,"
    "challan_reference,batch_reference,material_owner,owner_customer_code,order_number,"
    "line_no,allocate_qty"
)


def csv_text(*rows: str) -> str:
    return "\n".join([HEADER, *rows]) + "\n"


async def run(client: AsyncClient, site: str, text: str, commit: bool, expect: int = 200):
    return await post(
        client,
        "/outsourcing/batches/import",
        {"site_id": site, "csv_text": text, "commit": commit},
        expect=expect,
    )


async def batch_count() -> int:
    async with app.state.session_factory() as db:
        return len(list(await db.scalars(select(OutsourcedBatch))))


@pytest.fixture
async def third(client: AsyncClient, scene: dict) -> dict:
    """A third confirmed order (30 pumps) whose casting is not yet covered by any batch."""
    return await confirmed(client, scene, "acme", "PO-THIRD", "30", 20)


async def test_preview_then_import_creates_sent_and_planned_batches_linked_to_orders(
    client: AsyncClient, scene: dict, third: dict
) -> None:
    text = csv_text(
        f"COAT,HSG-CAST,Powder coating,50,{day(10)},{day(-1)},DC-9001,,,,{third['number']},1,20",
        f"COAT,HSG-CAST,Powder coating,50,{day(10)},{day(-1)},DC-9001,,,,,,",
        f"COAT,HSG-CAST,Powder coating,25,{day(12)},,,PLAN-7,customer,ACME,,,",
    )
    before = await batch_count()
    preview = await run(client, scene["site"], text, commit=False)
    assert preview["errors"] == [], preview
    assert (preview["batches_to_create"], preview["sent_batches"]) == (2, 1)
    assert (preview["allocations_to_create"], preview["committed"]) == (1, False)
    assert await batch_count() == before  # a preview creates nothing

    done = await run(client, scene["site"], text, commit=True)
    assert done["committed"] is True and len(done["created_numbers"]) == 2
    batches = (await client.get(f"{API}/outsourcing/batches?limit=50")).json()["items"]
    sent = next(b for b in batches if b["number"] == done["created_numbers"][0])
    planned = next(b for b in batches if b["number"] == done["created_numbers"][1])
    sent = (await client.get(f"{API}/outsourcing/batches/{sent['id']}")).json()
    planned = (await client.get(f"{API}/outsourcing/batches/{planned['id']}")).json()
    assert (sent["status"], sent["challan_reference"], sent["sent_date"]) == (
        "at_supplier",
        "DC-9001",
        day(-1),
    )
    assert [m["kind"] for m in sent["movements"]] == ["sent_to_supplier"]
    assert [a["quantity"] for a in sent["allocations"]] == ["20"]
    assert (planned["status"], planned["reference"], planned["material_owner"]) == (
        "planned",
        "PLAN-7",
        "customer",
    )
    assert planned["owner_customer_name"] == "Acme"

    again = await run(client, scene["site"], text, commit=True)
    assert (again["batches_to_create"], again["unchanged_batches"], again["created_numbers"]) == (
        0,
        2,
        [],
    )
    async with app.state.session_factory() as db:
        events = [e for e in await db.scalars(select(AuditEvent)) if "outsourcing." in e.action]
    created = [e for e in events if e.action == "outsourcing.batch_created"]
    imported = [e for e in created if e.details.get("source") == "import"]
    assert len(imported) == 2
    assert [e.details.get("source") for e in events if e.action == "outsourcing.batch_sent"] == [
        None,
        "import",
    ]
    assert len([e for e in events if e.action == "outsourcing.batches_imported"]) == 2


async def test_a_file_with_any_problem_creates_nothing(
    client: AsyncClient, scene: dict, third: dict
) -> None:
    order = third["number"]
    rows = [
        f"NOPE,HSG-CAST,Powder coating,10,{day(10)},,,R1,,,,,",  # unknown supplier
        f"COAT,HSG-CAST,Powder coating,10,{day(10)},,,,,,,,",  # cannot be recognised again
        f"COAT,HSG-CAST,Powder coating,10,{day(10)},{day(-1)},,R2,,,,,",  # sent, no challan
        f"COAT,HSG-CAST,Powder coating,10,{day(10)},{day(3)},DC-1,,,,,,",  # sent in the future
        f"COAT,HSG-CAST,Powder coating,10,{day(10)},,,R3,customer,,,,",  # owner not named
        f"COAT,HSG-CAST,Powder coating,10,{day(10)},,,R4,,,{order},1,",  # partial link
        f"COAT,HSG-CAST,Powder coating,10.5,{day(10)},,,R5,,,,,",  # PCS are whole
        f"COAT,HSG-CAST,Powder coating,10,{day(10)},,,R6,,,,,",
        f"COAT,HSG-CAST,Powder coating,12,{day(10)},,,R6,,,,,",  # same batch, other details
    ]
    before = await batch_count()
    report = await run(client, scene["site"], csv_text(*rows), commit=True, expect=422)
    problems = {(e["row"], e["field"]) for e in report["errors"]}
    assert problems == {
        (2, "supplier_code"),
        (3, "batch_reference"),
        (4, "challan_reference"),
        (5, "sent_date"),
        (6, "owner_customer_code"),
        (7, "order_number"),
        (8, "quantity"),
        (10, None),
    }
    by_row = {e["row"]: e["message"] for e in report["errors"]}
    assert "can be recognised again" in by_row[3]
    assert await batch_count() == before

    # Allocation checks are the screen's: the line needs only 30 castings.
    over = csv_text(f"COAT,HSG-CAST,Powder coating,50,{day(10)},,,R9,,,{order},1,40")
    report = await run(client, scene["site"], over, commit=False)
    assert report["errors"][0]["field"] == "allocate_qty"
    assert "needs only 30 PCS more" in report["errors"][0]["message"]
    missing = csv_text(f"COAT,HSG-CAST,Powder coating,50,{day(10)},,,R9,,,{order},2,5")
    report = await run(client, scene["site"], missing, commit=False)
    assert "has no component HSG-CAST" in report["errors"][0]["message"]
    assert await batch_count() == before


async def test_a_reimport_with_different_details_is_refused(
    client: AsyncClient, scene: dict
) -> None:
    first = csv_text(f"COAT,HSG-CAST,Powder coating,10,{day(10)},,,KEEP-1,,,,,")
    await run(client, scene["site"], first, commit=True)
    changed = csv_text(f"COAT,HSG-CAST,Powder coating,11,{day(10)},,,KEEP-1,,,,,")
    report = await run(client, scene["site"], changed, commit=False)
    assert "is already batch" in report["errors"][0]["message"]


async def test_material_owner_on_screen(client: AsyncClient, scene: dict) -> None:
    customers = (await client.get(f"{API}/master-data/customers")).json()["items"]
    acme = next(c for c in customers if c["code"] == "ACME")
    body = {
        "site_id": scene["site"],
        "supplier_id": scene["batch"]["supplier_id"],
        "item_id": scene["casting"],
        "operation": "Powder coating",
        "quantity": "5",
        "expected_return_date": day(5),
        "reference": "FREE-1",
    }
    await post(client, "/outsourcing/batches", {**body, "material_owner": "customer"}, 422)
    await post(
        client, "/outsourcing/batches", {**body, "owner_customer_id": acme["id"]}, 422
    )  # our own material names no customer
    batch = await post(
        client,
        "/outsourcing/batches",
        {**body, "material_owner": "customer", "owner_customer_id": acme["id"]},
    )
    assert (batch["reference"], batch["owner_customer_name"]) == ("FREE-1", "Acme")
    changed = await patch(
        client,
        f"/outsourcing/batches/{batch['id']}",
        {"version": batch["version"], "material_owner": "own"},
    )
    assert (changed["material_owner"], changed["owner_customer_id"]) == ("own", None)
    async with app.state.session_factory() as db:
        event = await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "outsourcing.batch_updated")
        )
    assert event.details["before"]["material_owner"] == "customer"
    assert event.details["after"]["material_owner"] == "own"


async def test_import_needs_permission_and_site_access(
    client: AsyncClient, scene: dict, add_member: AddMember, workspace_records: dict
) -> None:
    text = csv_text(f"COAT,HSG-CAST,Powder coating,10,{day(10)},,,R1,,,,,")
    await add_member("qc@example.com", "quality", site_ids=[workspace_records["site_id"]])
    await add_member("buyer@example.com", "procurement", site_ids=[])
    await sign_in_as(client, "qc@example.com")
    await run(client, scene["site"], text, commit=False, expect=403)
    await sign_in_as(client, "buyer@example.com")  # may manage batches, but not at this site
    await run(client, scene["site"], text, commit=False, expect=422)
