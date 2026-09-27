import uuid
from decimal import Decimal

import pytest
from conftest import ORIGIN, AddMember, csrf_headers, sign_in_as
from httpx import AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import AuditEvent, Customer

BASE = "/api/v1/master-data"


async def post(client: AsyncClient, path: str, body: dict) -> dict:
    response = await client.post(f"{BASE}/{path}", headers=csrf_headers(client), json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def make_unit(client: AsyncClient, code: str, dimension: str = "count", places: int = 0):
    return await post(
        client,
        "units",
        {"code": code, "name": code.title(), "dimension": dimension, "decimal_places": places},
    )


@pytest.fixture
async def owner(client: AsyncClient, workspace_records: dict[str, object]) -> AsyncClient:
    await sign_in_as(client, "owner@example.com")
    return client


# Units and conversions


async def test_unit_codes_are_normalised_and_unique_per_tenant(owner: AsyncClient) -> None:
    unit = await make_unit(owner, " kg ", "mass", 3)
    assert unit["code"] == "KG"
    assert unit["version"] == 1

    duplicate = await owner.post(
        f"{BASE}/units",
        headers=csrf_headers(owner),
        json={"code": "Kg", "name": "Again", "dimension": "mass", "decimal_places": 3},
    )
    assert duplicate.status_code == 409


@pytest.mark.parametrize("code", ["", "-KG", "HAS SPACE", "A" * 41, "KG%"])
async def test_invalid_codes_are_rejected(owner: AsyncClient, code: str) -> None:
    response = await owner.post(
        f"{BASE}/units",
        headers=csrf_headers(owner),
        json={"code": code, "name": "X", "dimension": "count", "decimal_places": 0},
    )
    assert response.status_code == 422


async def test_conversion_keeps_exact_decimal_factor(owner: AsyncClient) -> None:
    kg = await make_unit(owner, "KG", "mass", 3)
    g = await make_unit(owner, "G", "mass", 0)

    conversion = await post(
        owner,
        "unit-conversions",
        {"from_unit_id": kg["id"], "to_unit_id": g["id"], "factor": "1000.000000000001"},
    )

    assert Decimal(conversion["factor"]) == Decimal("1000.000000000001")
    assert (conversion["from_unit_code"], conversion["to_unit_code"]) == ("KG", "G")


async def test_conversion_between_unlike_units_is_rejected(owner: AsyncClient) -> None:
    kg = await make_unit(owner, "KG", "mass")
    pcs = await make_unit(owner, "PCS", "count")

    response = await owner.post(
        f"{BASE}/unit-conversions",
        headers=csrf_headers(owner),
        json={"from_unit_id": kg["id"], "to_unit_id": pcs["id"], "factor": "4"},
    )

    assert response.status_code == 422
    assert "same kind" in response.json()["detail"]


@pytest.mark.parametrize("factor", ["0", "-1", "0.0000000000001", 1e30])
async def test_conversion_factor_must_be_positive_and_bounded(
    owner: AsyncClient, factor: object
) -> None:
    kg = await make_unit(owner, "KG", "mass")
    g = await make_unit(owner, "G", "mass")
    response = await owner.post(
        f"{BASE}/unit-conversions",
        headers=csrf_headers(owner),
        json={"from_unit_id": kg["id"], "to_unit_id": g["id"], "factor": factor},
    )
    assert response.status_code == 422


async def test_conversion_cannot_be_defined_twice_in_either_direction(owner: AsyncClient) -> None:
    box = await make_unit(owner, "BOX")
    pcs = await make_unit(owner, "PCS")
    await post(
        owner,
        "unit-conversions",
        {"from_unit_id": box["id"], "to_unit_id": pcs["id"], "factor": 12},
    )

    reverse = await owner.post(
        f"{BASE}/unit-conversions",
        headers=csrf_headers(owner),
        json={"from_unit_id": pcs["id"], "to_unit_id": box["id"], "factor": "0.083333333333"},
    )
    assert reverse.status_code == 409


async def test_unit_in_use_by_active_item_cannot_be_deactivated(owner: AsyncClient) -> None:
    pcs = await make_unit(owner, "PCS")
    item = await post(
        owner,
        "items",
        {"code": "SHAFT-01", "name": "Shaft", "item_type": "component", "base_unit_id": pcs["id"]},
    )

    blocked = await owner.patch(
        f"{BASE}/units/{pcs['id']}",
        headers=csrf_headers(owner),
        json={"version": pcs["version"], "status": "inactive"},
    )
    assert blocked.status_code == 409

    await owner.patch(
        f"{BASE}/items/{item['id']}",
        headers=csrf_headers(owner),
        json={"version": item["version"], "status": "inactive"},
    )
    allowed = await owner.patch(
        f"{BASE}/units/{pcs['id']}",
        headers=csrf_headers(owner),
        json={"version": pcs["version"], "status": "inactive"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "inactive"


async def test_item_requires_an_active_unit(owner: AsyncClient) -> None:
    pcs = await make_unit(owner, "PCS")
    await owner.patch(
        f"{BASE}/units/{pcs['id']}",
        headers=csrf_headers(owner),
        json={"version": 1, "status": "inactive"},
    )
    response = await owner.post(
        f"{BASE}/items",
        headers=csrf_headers(owner),
        json={"code": "X1", "name": "X", "item_type": "component", "base_unit_id": pcs["id"]},
    )
    assert response.status_code == 422


async def test_items_cover_discrete_and_process_models(owner: AsyncClient) -> None:
    kg = await make_unit(owner, "KG", "mass", 3)
    pcs = await make_unit(owner, "PCS")
    resin = await post(
        owner,
        "items",
        {"code": "RESIN", "name": "Resin", "item_type": "raw_material",
         "base_unit_id": kg["id"], "tracking": "lot"},
    )
    pump = await post(
        owner,
        "items",
        {"code": "PUMP-5HP", "name": "5HP pump", "item_type": "finished_good",
         "base_unit_id": pcs["id"], "tracking": "serial"},
    )
    assert (resin["tracking"], pump["tracking"]) == ("lot", "serial")

    bad_type = await owner.post(
        f"{BASE}/items",
        headers=csrf_headers(owner),
        json={"code": "Z", "name": "Z", "item_type": "widget", "base_unit_id": pcs["id"]},
    )
    assert bad_type.status_code == 422


# Customers: edits, versions and audit


async def test_update_requires_current_version_and_records_before_after(
    owner: AsyncClient,
) -> None:
    customer = await post(
        owner, "customers", {"code": "ACME", "name": "Acme Ltd", "contact_email": "a@acme.in"}
    )

    updated = await owner.patch(
        f"{BASE}/customers/{customer['id']}",
        headers=csrf_headers(owner),
        json={"version": 1, "name": "Acme Private Ltd", "contact_email": ""},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["contact_email"] is None

    stale = await owner.patch(
        f"{BASE}/customers/{customer['id']}",
        headers=csrf_headers(owner),
        json={"version": 1, "name": "Overwritten"},
    )
    assert stale.status_code == 409

    async with app.state.session_factory() as db:
        record = await db.get(Customer, uuid.UUID(customer["id"]))
        assert record.name == "Acme Private Ltd"
        event = await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "masterdata.customer.updated")
        )
    assert event.details["changes"] == {
        "name": {"from": "Acme Ltd", "to": "Acme Private Ltd"},
        "contact_email": {"from": "a@acme.in", "to": None},
    }
    assert event.request_id == updated.headers["X-Request-ID"]


async def test_no_op_update_writes_no_audit_and_keeps_version(owner: AsyncClient) -> None:
    customer = await post(owner, "customers", {"code": "ACME", "name": "Acme"})
    response = await owner.patch(
        f"{BASE}/customers/{customer['id']}",
        headers=csrf_headers(owner),
        json={"version": 1, "name": "Acme"},
    )
    assert response.json()["version"] == 1
    async with app.state.session_factory() as db:
        events = await db.scalars(
            select(AuditEvent).where(AuditEvent.action == "masterdata.customer.updated")
        )
        assert events.all() == []


@pytest.mark.parametrize(
    "body",
    [
        {"version": 1, "name": None},
        {"version": 1, "status": "deleted"},
        {"version": 1, "tenant_id": "00000000-0000-0000-0000-000000000000"},
        {"version": 1, "code": "RENAMED"},
        {"version": 1, "contact_email": "not-an-email"},
        {"version": 1, "contact_phone": "call me"},
        {"name": "No version"},
    ],
)
async def test_invalid_customer_updates_are_rejected(owner: AsyncClient, body: dict) -> None:
    customer = await post(owner, "customers", {"code": "ACME", "name": "Acme"})
    response = await owner.patch(
        f"{BASE}/customers/{customer['id']}", headers=csrf_headers(owner), json=body
    )
    assert response.status_code == 422


async def test_list_search_paginates_and_treats_wildcards_literally(owner: AsyncClient) -> None:
    for index in range(5):
        await post(owner, "customers", {"code": f"C{index}", "name": f"Customer {index}"})
    await post(owner, "customers", {"code": "PCT", "name": "100% Motors"})

    page = (await owner.get(f"{BASE}/customers", params={"limit": 2, "offset": 2})).json()
    assert page["total"] == 6
    assert [row["code"] for row in page["items"]] == ["C2", "C3"]

    literal = (await owner.get(f"{BASE}/customers", params={"q": "%"})).json()
    assert [row["code"] for row in literal["items"]] == ["PCT"]


async def test_mutations_require_csrf(owner: AsyncClient) -> None:
    response = await owner.post(
        f"{BASE}/customers", headers={"Origin": ORIGIN}, json={"code": "A", "name": "A"}
    )
    assert response.status_code == 403


# Tenant isolation


async def test_other_tenant_cannot_see_or_use_records(
    client: AsyncClient, workspace_records: dict[str, object], add_member: AddMember
) -> None:
    await sign_in_as(client, "owner@example.com")
    customer = await post(client, "customers", {"code": "ACME", "name": "Acme"})
    unit = await make_unit(client, "PCS")

    await add_member(
        "rival@example.com",
        "owner",
        tenant_id=workspace_records["other_tenant_id"],
        home_site_id=workspace_records["other_site_id"],
    )
    await sign_in_as(client, "rival@example.com")

    assert (await client.get(f"{BASE}/customers")).json() == {"items": [], "total": 0}
    patch = await client.patch(
        f"{BASE}/customers/{customer['id']}",
        headers=csrf_headers(client),
        json={"version": 1, "name": "Hijacked"},
    )
    assert patch.status_code == 404
    item = await client.post(
        f"{BASE}/items",
        headers=csrf_headers(client),
        json={"code": "X", "name": "X", "item_type": "component", "base_unit_id": unit["id"]},
    )
    assert item.status_code == 422
    same_code = await client.post(
        f"{BASE}/customers", headers=csrf_headers(client), json={"code": "ACME", "name": "Mine"}
    )
    assert same_code.status_code == 201


# Role permissions (written out independently of ROLE_PERMISSIONS)

CAN_CREATE = {
    "customers": {"owner", "administrator"},
    "suppliers": {"owner", "administrator", "procurement"},
    "items": {"owner", "administrator", "production_manager"},
    "units": {"owner", "administrator"},
    "warehouses": {"owner", "administrator", "stores"},
}
ROLES = [
    "owner", "administrator", "production_manager", "production_coordinator", "procurement",
    "stores", "quality", "dispatch", "finance", "approver", "read_only",
]


@pytest.mark.parametrize("role", ROLES)
async def test_create_permissions_by_role(
    client: AsyncClient, workspace_records: dict[str, object], add_member: AddMember, role: str
) -> None:
    await sign_in_as(client, "owner@example.com")
    pcs = await make_unit(client, "PCS")
    await add_member(f"{role}.member@example.com", role, site_scope="all")
    await sign_in_as(client, f"{role}.member@example.com")

    bodies = {
        "customers": {"code": "N1", "name": "New"},
        "suppliers": {"code": "N1", "name": "New"},
        "items": {"code": "N1", "name": "New", "item_type": "component",
                  "base_unit_id": pcs["id"]},
        "units": {"code": "N1", "name": "New", "dimension": "count", "decimal_places": 0},
        "warehouses": {"code": "N1", "name": "New", "site_id": str(workspace_records["site_id"])},
    }
    for entity, body in bodies.items():
        listing = await client.get(f"{BASE}/{entity}")
        assert listing.status_code == 200, entity
        created = await client.post(f"{BASE}/{entity}", headers=csrf_headers(client), json=body)
        expected = 201 if role in CAN_CREATE[entity] else 403
        assert created.status_code == expected, (entity, created.text)
