import pytest
from conftest import AddMember, csrf_headers, sign_in_as
from httpx import AsyncClient
from sqlalchemy import func, select

from app.api import imports
from app.main import app
from app.models import AuditEvent, Customer, Item

URL = "/api/v1/master-data/imports"

CUSTOMERS = (
    "code,name,contact_email,city\n"
    "acme,Acme Pumps,buyer@acme.in,Coimbatore\n"
    "BHARAT,Bharat Motors,,Pune\n"
)


@pytest.fixture
async def owner(client: AsyncClient, workspace_records: dict[str, object]) -> AsyncClient:
    await sign_in_as(client, "owner@example.com")
    return client


async def run(client: AsyncClient, entity: str, csv_text: str, commit: bool):
    return await client.post(
        f"{URL}/{entity}",
        headers=csrf_headers(client),
        json={"csv_text": csv_text, "commit": commit},
    )


async def count(model) -> int:
    async with app.state.session_factory() as db:
        return await db.scalar(select(func.count()).select_from(model))


async def test_preview_writes_nothing(owner: AsyncClient) -> None:
    response = await run(owner, "customers", CUSTOMERS, commit=False)

    assert response.status_code == 200
    report = response.json()
    assert (report["total_rows"], report["to_create"], report["committed"]) == (2, 2, False)
    assert report["errors"] == []
    assert await count(Customer) == 0


async def test_commit_creates_records_and_rerun_is_idempotent(owner: AsyncClient) -> None:
    first = (await run(owner, "customers", CUSTOMERS, commit=True)).json()
    second = (await run(owner, "customers", CUSTOMERS, commit=True)).json()

    assert (first["to_create"], first["committed"]) == (2, True)
    assert (second["to_create"], second["unchanged"], second["committed"]) == (0, 2, True)
    assert await count(Customer) == 2
    async with app.state.session_factory() as db:
        acme = await db.scalar(select(Customer).where(Customer.code == "ACME"))
        created = (
            await db.scalars(
                select(AuditEvent).where(AuditEvent.action == "masterdata.customer.created")
            )
        ).all()
        summaries = (
            await db.scalars(
                select(AuditEvent).where(AuditEvent.action == "masterdata.import.committed")
            )
        ).all()
    assert (acme.contact_email, acme.city) == ("buyer@acme.in", "Coimbatore")
    assert len(created) == 2
    assert {event.details["source"] for event in created} == {"import"}
    assert [event.details["created"] for event in summaries] == [2, 0]


async def test_any_error_blocks_the_whole_file(owner: AsyncClient) -> None:
    csv_text = (
        "code,name,contact_email\n"
        "GOOD,Good Customer,\n"
        "BAD,Bad Email,not-an-email\n"
        "good,Duplicate In File,\n"
        ",Missing Code,\n"
    )

    preview = (await run(owner, "customers", csv_text, commit=False)).json()
    commit = await run(owner, "customers", csv_text, commit=True)

    issues = {(issue["row"], issue["field"]) for issue in preview["errors"]}
    assert issues == {(3, "contact_email"), (4, "code"), (5, "code")}
    assert commit.status_code == 422
    assert commit.json()["committed"] is False
    assert await count(Customer) == 0


async def test_duplicate_code_is_reported_even_when_first_row_is_invalid(
    owner: AsyncClient,
) -> None:
    csv_text = "code,name,contact_email\nDUP,First,broken\n dup ,Second,\n"
    report = (await run(owner, "customers", csv_text, commit=False)).json()
    issues = {(issue["row"], issue["field"]) for issue in report["errors"]}
    assert issues == {(2, "contact_email"), (3, "code")}


async def test_existing_code_with_different_values_is_not_overwritten(owner: AsyncClient) -> None:
    await run(owner, "customers", CUSTOMERS, commit=True)
    changed = CUSTOMERS.replace("Acme Pumps", "Acme Renamed")

    report = (await run(owner, "customers", changed, commit=True)).json()

    assert report["committed"] is False
    assert report["errors"][0]["row"] == 2
    assert "name" in report["errors"][0]["message"]
    async with app.state.session_factory() as db:
        acme = await db.scalar(select(Customer).where(Customer.code == "ACME"))
    assert acme.name == "Acme Pumps"


@pytest.mark.parametrize(
    ("csv_text", "message"),
    [
        ("name,city\nAcme,Pune\n", "Missing column(s): code"),
        ("code,name,gstin\nA,Acme,29ABCDE1234F1Z5\n", "Unknown column(s): gstin"),
        ("code,name\n", "The file has no data rows"),
        ("code,name,name\nA,B,C\n", "Each column may appear only once"),
    ],
)
async def test_header_problems_are_reported(
    owner: AsyncClient, csv_text: str, message: str
) -> None:
    report = (await run(owner, "customers", csv_text, commit=False)).json()
    assert message in [issue["message"] for issue in report["errors"]]


async def test_header_is_case_and_space_tolerant_and_bom_is_ignored(owner: AsyncClient) -> None:
    report = (
        await run(owner, "customers", "﻿ Code , NAME \nA1,Alpha\n", commit=True)
    ).json()
    assert report["committed"] is True


async def test_row_limit(owner: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(imports, "MAX_ROWS", 2)
    csv_text = "code,name\nA,A\nB,B\nC,C\n"
    report = (await run(owner, "customers", csv_text, commit=False)).json()
    assert report["errors"][-1]["message"] == "A file may contain at most 2 rows"


async def test_item_import_resolves_units_by_code(owner: AsyncClient) -> None:
    await owner.post(
        "/api/v1/master-data/units",
        headers=csrf_headers(owner),
        json={"code": "KG", "name": "Kilogram", "dimension": "mass", "decimal_places": 3},
    )
    csv_text = (
        "code,name,item_type,base_unit_code,tracking\n"
        "RESIN,Resin,raw_material,kg,lot\n"
        "BOLT,Bolt,component,PCS,none\n"
    )
    preview = (await run(owner, "items", csv_text, commit=False)).json()
    assert preview["errors"] == [
        {"row": 3, "field": "base_unit_code", "message": "No active unit with code PCS"}
    ]

    ok = (await run(owner, "items", csv_text.splitlines()[0] + "\n"
                    + csv_text.splitlines()[1] + "\n", commit=True)).json()
    assert ok["committed"] is True
    async with app.state.session_factory() as db:
        resin = await db.scalar(select(Item).where(Item.code == "RESIN"))
    assert resin.tracking == "lot"


async def test_supplier_job_work_flag_parsing(owner: AsyncClient) -> None:
    csv_text = "code,name,provides_job_work\nPLT,Platers,yes\nCST,Casters,no\nX,X,maybe\n"
    report = (await run(owner, "suppliers", csv_text, commit=False)).json()
    assert report["errors"] == [
        {"row": 4, "field": "provides_job_work", "message": "Use yes or no"}
    ]


async def test_import_needs_the_entity_permission(
    client: AsyncClient, workspace_records: dict[str, object], add_member: AddMember
) -> None:
    await add_member("buyer@example.com", "procurement")
    await sign_in_as(client, "buyer@example.com")

    suppliers = await run(client, "suppliers", "code,name\nS1,Supplier\n", commit=True)
    customers = await run(client, "customers", "code,name\nC1,Customer\n", commit=False)
    unknown = await run(client, "orders", "code,name\nC1,Customer\n", commit=False)

    assert suppliers.status_code == 200
    assert customers.status_code == 403
    assert unknown.status_code == 422
