"""Slice G3: company-customisable roles and the self-approval setting (ADR-0011)."""

# ruff: noqa: F811  (pytest fixtures are imported and then used as parameters)

import uuid

import pytest
from conftest import AddMember, csrf_headers, sign_in_as
from httpx import AsyncClient
from sqlalchemy import select
from test_orders import API, data, post  # noqa: F401
from test_risk import day, put

from app.main import app
from app.models import AuditEvent, TenantRole


async def roles(client: AsyncClient) -> dict[str, dict]:
    body = (await client.get(f"{API}/organization/roles")).json()
    return {r["key"]: r for r in body["roles"]}


async def member_id(client: AsyncClient, email: str) -> str:
    members = (await client.get(f"{API}/organization/members")).json()
    return next(m["membership_id"] for m in members if m["email"] == email)


async def set_role(client: AsyncClient, email: str, role: str, expect: int = 200) -> dict:
    return await put(
        client,
        f"/organization/members/{await member_id(client, email)}/role",
        {"role": role},
        expect,
    )


async def delete(client: AsyncClient, path: str, expect: int = 200) -> dict:
    response = await client.delete(f"{API}{path}", headers=csrf_headers(client))
    assert response.status_code == expect, response.text
    return response.json()


async def stock_entry(client: AsyncClient, data: dict, kind: str = "receipt", expect: int = 201):
    return await post(
        client,
        "/stock/movements",
        {
            "submission_key": str(uuid.uuid4()),
            "warehouse_id": data["warehouse"],
            "item_id": data["pump"],
            "kind": kind,
            "quantity": "5",
            "movement_date": day(0),
        },
        expect=expect,
    )


@pytest.fixture
async def stocked(client: AsyncClient, data: dict) -> dict:
    """The owner's workspace data plus one warehouse at the site."""
    warehouse = await post(
        client, "/master-data/warehouses", {"code": "FG1", "name": "Store", "site_id": data["site"]}
    )
    return {**data, "warehouse": warehouse["id"]}


async def audit_actions(prefix: str) -> list[AuditEvent]:
    async with app.state.session_factory() as db:
        events = await db.scalars(select(AuditEvent).order_by(AuditEvent.created_at))
        return [e for e in events if e.action.startswith(prefix)]


async def test_roles_start_from_the_template_with_administrator_locked(
    client: AsyncClient, data: dict, add_member: AddMember, workspace_records: dict
) -> None:
    body = (await client.get(f"{API}/organization/roles")).json()
    by_key = {r["key"]: r for r in body["roles"]}
    catalogue = {p["key"] for p in body["catalogue"]}
    assert len(by_key) == 11 and "roles:manage" in catalogue
    admin = by_key["administrator"]
    assert (admin["locked"], set(admin["permissions"])) == (True, catalogue)
    assert (
        by_key["stores"]["changed"] is False and "stock:record" in by_key["stores"]["permissions"]
    )
    assert by_key["owner"]["members"] == 1
    await put(
        client,
        "/organization/roles/administrator",
        {"name": "Admin", "permissions": []},
        expect=409,
    )

    await add_member("viewer@example.com", "read_only", site_ids=[workspace_records["site_id"]])
    await sign_in_as(client, "viewer@example.com")
    assert (await client.get(f"{API}/organization/roles")).status_code == 403


async def test_a_changed_role_applies_at_once_and_can_be_reset(
    client: AsyncClient, stocked: dict, add_member: AddMember, workspace_records: dict
) -> None:
    await add_member("qc@example.com", "quality", site_ids=[workspace_records["site_id"]])
    quality = (await roles(client))["quality"]
    await sign_in_as(client, "qc@example.com")
    await stock_entry(client, stocked, expect=403)

    await sign_in_as(client, "owner@example.com")
    body = {"name": "Quality and stores", "permissions": [*quality["permissions"], "x:y"]}
    bad = await put(client, "/organization/roles/quality", body, expect=422)
    assert "Unknown permission: x:y" in bad["detail"]
    body["permissions"] = [*quality["permissions"], "stock:record"]
    await put(client, "/organization/roles/quality", {**body, "version": 3}, expect=409)
    changed = {
        r["key"]: r for r in (await put(client, "/organization/roles/quality", body))["roles"]
    }
    assert (changed["quality"]["name"], changed["quality"]["changed"]) == (
        "Quality and stores",
        True,
    )

    await sign_in_as(client, "qc@example.com")  # same member, no new grant needed
    await stock_entry(client, stocked)

    await sign_in_as(client, "owner@example.com")
    version = changed["quality"]["version"]
    reset = {
        r["key"]: r
        for r in (await delete(client, f"/organization/roles/quality?version={version}"))["roles"]
    }
    assert reset["quality"]["changed"] is False
    await sign_in_as(client, "qc@example.com")
    await stock_entry(client, stocked, expect=403)
    events = await audit_actions("roles.")
    assert [e.action for e in events] == ["roles.changed", "roles.reset"]
    assert "stock:record" not in events[0].details["before"]["permissions"]
    assert "stock:record" in events[0].details["after"]["permissions"]


async def test_a_company_role_is_created_assigned_and_deleted(
    client: AsyncClient, stocked: dict, add_member: AddMember, workspace_records: dict
) -> None:
    site = workspace_records["site_id"]
    await add_member("lead@example.com", "read_only", site_ids=[site])
    body = {
        "name": "Shift supervisor",
        "description": "Runs a shift",
        "permissions": ["orders:read", "stock:read", "stock:record"],
    }
    created = {r["key"]: r for r in (await post(client, "/organization/roles", body))["roles"]}
    role = created["shift_supervisor"]
    assert (role["standard"], role["members"]) == (False, 0)
    assert "workspace:read" in role["permissions"]  # always on
    await post(client, "/organization/roles", body, expect=409)
    await post(client, "/organization/roles", {**body, "name": "Stores"}, expect=409)

    await set_role(client, "lead@example.com", "not_a_role", expect=422)
    changed = await set_role(client, "lead@example.com", "shift_supervisor")
    assert changed["role"] == "shift_supervisor"
    await sign_in_as(client, "lead@example.com")
    workspace = (await client.get(f"{API}/workspace/dashboard")).json()
    assert "stock:record" in workspace["permissions"]
    assert "orders:manage" not in workspace["permissions"]
    await stock_entry(client, stocked)

    await sign_in_as(client, "owner@example.com")
    version = (await roles(client))["shift_supervisor"]["version"]
    blocked = await delete(client, f"/organization/roles/shift_supervisor?version={version}", 409)
    assert "another role" in blocked["detail"]
    await set_role(client, "lead@example.com", "read_only")
    await delete(client, f"/organization/roles/shift_supervisor?version={version}")
    assert "shift_supervisor" not in await roles(client)
    assert [e.action for e in await audit_actions("roles.")] == ["roles.created", "roles.deleted"]
    changes = await audit_actions("organization.member.role_changed")
    assert [(e.details["before"], e.details["after"]) for e in changes] == [
        ("read_only", "shift_supervisor"),
        ("shift_supervisor", "read_only"),
    ]


async def test_only_administrators_appoint_administrators(
    client: AsyncClient, data: dict, add_member: AddMember, workspace_records: dict
) -> None:
    site = workspace_records["site_id"]
    await add_member("first.admin@example.com", "read_only", site_ids=[site])
    await add_member("second@example.com", "read_only", site_ids=[site])
    await add_member("co.owner@example.com", "owner")

    # With no administrator yet, an owner may appoint the first one.
    await set_role(client, "first.admin@example.com", "administrator")
    denied = await set_role(client, "second@example.com", "administrator", expect=403)
    assert "Only an administrator" in denied["detail"]
    await set_role(client, "first.admin@example.com", "read_only", expect=403)
    mine = await set_role(client, "owner@example.com", "read_only", expect=403)
    assert "your own role" in mine["detail"]

    # Even a stored row for the administrator role cannot take its permissions away.
    async with app.state.session_factory() as db:
        db.add(
            TenantRole(
                tenant_id=workspace_records["tenant_id"],
                key="administrator",
                name="Administrator",
                permissions=["workspace:read"],
                is_standard=True,
            )
        )
        await db.commit()
    await sign_in_as(client, "first.admin@example.com")
    workspace = (await client.get(f"{API}/workspace/dashboard")).json()
    assert {"roles:manage", "users:manage", "stock:approve"} <= set(workspace["permissions"])
    await set_role(client, "second@example.com", "administrator")
    # Administrators can take role management away from owners.
    owner = (await roles(client))["owner"]
    without = [p for p in owner["permissions"] if p != "roles:manage"]
    await put(client, "/organization/roles/owner", {"name": "Owner", "permissions": without})
    await sign_in_as(client, "co.owner@example.com")
    assert (await client.get(f"{API}/organization/roles")).status_code == 200  # users:manage
    await put(
        client,
        "/organization/roles/stores",
        {"name": "Stores", "permissions": ["stock:read"]},
        expect=403,
    )


async def test_nobody_can_remove_the_last_way_to_manage_roles(
    client: AsyncClient, data: dict
) -> None:
    owner = (await roles(client))["owner"]
    without = [p for p in owner["permissions"] if p != "roles:manage"]
    refused = await put(
        client, "/organization/roles/owner", {"name": "Owner", "permissions": without}, expect=409
    )
    assert "Nobody would be left who can manage roles" in refused["detail"]


async def test_a_company_may_allow_people_to_approve_their_own_entries(
    client: AsyncClient, stocked: dict, add_member: AddMember, workspace_records: dict
) -> None:
    opening = await stock_entry(client, stocked, kind="opening")
    assert opening["can_decide"] is False
    path = f"/stock/movements/{opening['id']}/approve"
    await post(client, path, {"version": opening["version"]}, expect=403)

    await add_member("stores@example.com", "stores", site_ids=[workspace_records["site_id"]])
    await sign_in_as(client, "stores@example.com")
    await put(client, "/fulfillment/settings", {"allow_self_approval": True}, expect=403)

    await sign_in_as(client, "owner@example.com")
    saved = await put(client, "/fulfillment/settings", {"allow_self_approval": True})
    assert saved["allow_self_approval"] is True
    [listed] = (await client.get(f"{API}/stock/movements?status=pending_approval")).json()
    assert listed["can_decide"] is True
    approved = await post(client, path, {"version": opening["version"]}, expect=200)
    assert approved["status"] == "posted"
    [event] = await audit_actions("stock.approved")
    assert event.details["self_approved"] is True
    [setting] = await audit_actions("fulfillment.settings_changed")
    assert setting.details == {
        "before": {"allow_self_approval": False},
        "after": {"allow_self_approval": True},
    }
