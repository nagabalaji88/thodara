import uuid

import pytest
from conftest import AddMember, csrf_headers, sign_in_as
from httpx import AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import AuditEvent, TenantMembership

BASE = "/api/v1"


@pytest.fixture
async def two_sites(
    client: AsyncClient, workspace_records: dict[str, object], add_member: AddMember
) -> dict[str, str]:
    """Main Plant (existing) and Hosur Plant, each with one warehouse; a stores user on Main."""
    await sign_in_as(client, "owner@example.com")
    second = await client.post(
        f"{BASE}/organization/sites",
        headers=csrf_headers(client),
        json={"name": "Hosur Plant", "city": "Hosur"},
    )
    assert second.status_code == 201, second.text
    main_id = str(workspace_records["site_id"])
    hosur_id = second.json()["id"]
    ids = {"main": main_id, "hosur": hosur_id}
    for key, site_id in list(ids.items()):
        response = await client.post(
            f"{BASE}/master-data/warehouses",
            headers=csrf_headers(client),
            json={"code": f"WH-{key.upper()}", "name": f"{key} stores", "site_id": site_id},
        )
        assert response.status_code == 201
        ids[f"wh_{key}"] = response.json()["id"]
    await add_member("stores@example.com", "stores", site_ids=[uuid.UUID(main_id)])
    return ids


async def membership_id_for(email: str) -> uuid.UUID:
    members = await _members()
    return next(member.id for member, user_email in members if user_email == email)


async def _members():
    from app.models import User

    async with app.state.session_factory() as db:
        rows = await db.execute(
            select(TenantMembership, User.email).join(User, User.id == TenantMembership.user_id)
        )
        return rows.all()


async def test_site_restricted_user_sees_only_granted_sites(
    client: AsyncClient, two_sites: dict[str, str]
) -> None:
    await sign_in_as(client, "stores@example.com")

    sites = (await client.get(f"{BASE}/organization/sites")).json()
    dashboard = (await client.get(f"{BASE}/workspace/dashboard")).json()
    warehouses = (await client.get(f"{BASE}/master-data/warehouses")).json()

    assert [site["name"] for site in sites] == ["Main Plant"]
    assert [site["name"] for site in dashboard["sites"]] == ["Main Plant"]
    assert [row["code"] for row in warehouses["items"]] == ["WH-MAIN"]
    assert warehouses["total"] == 1


async def test_site_restricted_user_cannot_act_on_other_sites(
    client: AsyncClient, two_sites: dict[str, str]
) -> None:
    await sign_in_as(client, "stores@example.com")

    create = await client.post(
        f"{BASE}/master-data/warehouses",
        headers=csrf_headers(client),
        json={"code": "WH-2", "name": "Sneaky", "site_id": two_sites["hosur"]},
    )
    edit = await client.patch(
        f"{BASE}/master-data/warehouses/{two_sites['wh_hosur']}",
        headers=csrf_headers(client),
        json={"version": 1, "name": "Renamed"},
    )
    own = await client.patch(
        f"{BASE}/master-data/warehouses/{two_sites['wh_main']}",
        headers=csrf_headers(client),
        json={"version": 1, "name": "Main stores renamed"},
    )

    assert create.status_code == 404
    assert edit.status_code == 404
    assert own.status_code == 200


async def test_user_with_no_granted_sites_sees_no_site_data(
    client: AsyncClient, two_sites: dict[str, str], add_member: AddMember
) -> None:
    await add_member("nosite@example.com", "stores")
    await sign_in_as(client, "nosite@example.com")

    assert (await client.get(f"{BASE}/organization/sites")).json() == []
    assert (await client.get(f"{BASE}/master-data/warehouses")).json()["total"] == 0


async def test_admin_grants_all_sites_and_change_is_audited(
    client: AsyncClient, two_sites: dict[str, str]
) -> None:
    membership_id = await membership_id_for("stores@example.com")
    await sign_in_as(client, "owner@example.com")

    members = (await client.get(f"{BASE}/organization/members")).json()
    stores = next(m for m in members if m["email"] == "stores@example.com")
    assert (stores["site_scope"], stores["site_ids"]) == ("selected", [two_sites["main"]])

    response = await client.put(
        f"{BASE}/organization/members/{membership_id}/site-access",
        headers=csrf_headers(client),
        json={"site_scope": "all"},
    )
    assert response.status_code == 200

    await sign_in_as(client, "stores@example.com")
    warehouses = (await client.get(f"{BASE}/master-data/warehouses")).json()
    assert warehouses["total"] == 2

    async with app.state.session_factory() as db:
        event = await db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "organization.member.site_access_changed"
            )
        )
    assert event.details["before"] == {"site_scope": "selected", "site_ids": [two_sites["main"]]}
    assert event.details["after"] == {"site_scope": "all", "site_ids": []}


async def test_revoking_a_site_takes_effect_immediately(
    client: AsyncClient, two_sites: dict[str, str]
) -> None:
    membership_id = await membership_id_for("stores@example.com")
    await sign_in_as(client, "stores@example.com")
    stores_client_cookies = dict(client.cookies)

    await sign_in_as(client, "owner@example.com")
    await client.put(
        f"{BASE}/organization/members/{membership_id}/site-access",
        headers=csrf_headers(client),
        json={"site_scope": "selected", "site_ids": [two_sites["hosur"]]},
    )

    client.cookies.clear()
    for name, value in stores_client_cookies.items():
        client.cookies.set(name, value)
    warehouses = (await client.get(f"{BASE}/master-data/warehouses")).json()
    assert [row["code"] for row in warehouses["items"]] == ["WH-HOSUR"]


async def test_site_access_rules(
    client: AsyncClient, two_sites: dict[str, str], workspace_records: dict[str, object]
) -> None:
    stores_id = await membership_id_for("stores@example.com")
    owner_id = await membership_id_for("owner@example.com")
    await sign_in_as(client, "owner@example.com")

    def put(membership_id, body):
        return client.put(
            f"{BASE}/organization/members/{membership_id}/site-access",
            headers=csrf_headers(client),
            json=body,
        )

    assert (await put(owner_id, {"site_scope": "selected", "site_ids": []})).status_code == 409
    foreign_site = str(workspace_records["other_site_id"])
    assert (
        await put(stores_id, {"site_scope": "selected", "site_ids": [foreign_site]})
    ).status_code == 422
    assert (
        await put(stores_id, {"site_scope": "all", "site_ids": [two_sites["main"]]})
    ).status_code == 422
    assert (await put(uuid.uuid4(), {"site_scope": "all"})).status_code == 404


async def test_only_admins_manage_sites_and_members(
    client: AsyncClient, two_sites: dict[str, str]
) -> None:
    membership_id = await membership_id_for("stores@example.com")
    await sign_in_as(client, "stores@example.com")

    assert (await client.get(f"{BASE}/organization/members")).status_code == 403
    assert (
        await client.put(
            f"{BASE}/organization/members/{membership_id}/site-access",
            headers=csrf_headers(client),
            json={"site_scope": "all"},
        )
    ).status_code == 403
    assert (
        await client.post(
            f"{BASE}/organization/sites",
            headers=csrf_headers(client),
            json={"name": "Rogue Plant"},
        )
    ).status_code == 403


async def test_site_names_are_unique_and_time_zone_is_validated(
    client: AsyncClient, two_sites: dict[str, str]
) -> None:
    duplicate = await client.post(
        f"{BASE}/organization/sites",
        headers=csrf_headers(client),
        json={"name": "  hosur   plant "},
    )
    bad_zone = await client.post(
        f"{BASE}/organization/sites",
        headers=csrf_headers(client),
        json={"name": "Pune Plant", "time_zone": "Mars/Base"},
    )
    assert duplicate.status_code == 409
    assert bad_zone.status_code == 422
