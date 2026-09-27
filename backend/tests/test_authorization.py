import re
import uuid
from types import SimpleNamespace

import pytest
from conftest import ORIGIN, AddMember, csrf_headers, sign_in_as
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select

from app.api.dependencies import ROLE_PERMISSIONS, AuthContext, require_permission
from app.core.security import token_digest
from app.main import app
from app.models import AuthSession, Site, Tenant, TenantMembership, User

ALL_ROLES = sorted(ROLE_PERMISSIONS)
# Written out independently of ROLE_PERMISSIONS so a permission-map change must update tests.
ROLES_ALLOWED_TO_CONFIGURE = {"owner", "administrator"}

SETUP_PAYLOAD = {
    "company_name": "Changed Name",
    "country_code": "IN",
    "base_currency": "INR",
    "site_name": "Changed Plant",
    "city": "Pune",
    "time_zone": "Asia/Kolkata",
}


async def current_session(client: AsyncClient) -> AuthSession:
    async with app.state.session_factory() as db:
        session = await db.scalar(
            select(AuthSession).where(
                AuthSession.token_hash == token_digest(client.cookies["thodara_session"])
            )
        )
        assert session is not None
        return session


async def tenant_name(tenant_id: uuid.UUID) -> str:
    async with app.state.session_factory() as db:
        tenant = await db.get(Tenant, tenant_id)
        assert tenant is not None
        return tenant.display_name


def test_role_list_matches_database_constraint() -> None:
    constraint_sql = next(
        str(c.sqltext)
        for c in TenantMembership.__table__.constraints
        if str(getattr(c, "sqltext", "")).startswith("role in")
    )
    assert set(re.findall(r"'([a-z_]+)'", constraint_sql)) == set(ALL_ROLES)


@pytest.mark.parametrize("role", ALL_ROLES)
async def test_workspace_setup_permission_by_role(
    client: AsyncClient, workspace_records: dict[str, object], add_member: AddMember, role: str
) -> None:
    await add_member(f"{role}.member@example.com", role, home_site_id=workspace_records["site_id"])
    await sign_in_as(client, f"{role}.member@example.com")

    response = await client.put(
        "/api/v1/onboarding/workspace", headers=csrf_headers(client), json=SETUP_PAYLOAD
    )

    if role in ROLES_ALLOWED_TO_CONFIGURE:
        assert response.status_code == 200
        assert await tenant_name(workspace_records["tenant_id"]) == "Changed Name"
    else:
        assert response.status_code == 403
        assert await tenant_name(workspace_records["tenant_id"]) == "Acme Pumps"


@pytest.mark.parametrize("role", ALL_ROLES)
async def test_every_role_can_read_only_its_own_dashboard(
    client: AsyncClient, workspace_records: dict[str, object], add_member: AddMember, role: str
) -> None:
    await add_member(f"{role}.member@example.com", role, site_scope="all")
    await sign_in_as(client, f"{role}.member@example.com")

    response = await client.get("/api/v1/workspace/dashboard")

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == str(workspace_records["tenant_id"])
    assert [site["name"] for site in body["sites"]] == ["Main Plant"]


def context_with_role(role: str) -> AuthContext:
    return AuthContext(
        session=None, user=None, tenant=None, membership=SimpleNamespace(role=role), site=None
    )


async def test_unknown_role_is_denied_by_default() -> None:
    dependency = require_permission("workspace:read")
    context = context_with_role("not_a_real_role")
    with pytest.raises(HTTPException) as denied:
        await dependency(context=context)
    assert denied.value.status_code == 403


async def test_unknown_permission_is_denied_even_for_owner() -> None:
    dependency = require_permission("orders:delete_everything")
    context = context_with_role("owner")
    with pytest.raises(HTTPException) as denied:
        await dependency(context=context)
    assert denied.value.status_code == 403


async def test_session_pointing_at_foreign_tenant_is_denied(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    await sign_in_as(client, "owner@example.com")
    session = await current_session(client)
    async with app.state.session_factory() as db:
        stored = await db.get(AuthSession, session.id)
        stored.active_tenant_id = workspace_records["other_tenant_id"]
        await db.commit()

    dashboard = await client.get("/api/v1/workspace/dashboard")
    setup = await client.put(
        "/api/v1/onboarding/workspace", headers=csrf_headers(client), json=SETUP_PAYLOAD
    )

    assert dashboard.status_code == 403
    assert "Other" not in dashboard.text
    assert setup.status_code == 403
    assert await tenant_name(workspace_records["other_tenant_id"]) == "Other Factory"


async def test_workspace_setup_never_touches_another_tenant(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    await sign_in_as(client, "owner@example.com")
    payload = {**SETUP_PAYLOAD, "tenant_id": str(workspace_records["other_tenant_id"])}

    response = await client.put(
        "/api/v1/onboarding/workspace", headers=csrf_headers(client), json=payload
    )

    assert response.status_code == 200
    assert response.json()["tenant_id"] == str(workspace_records["tenant_id"])
    assert await tenant_name(workspace_records["other_tenant_id"]) == "Other Factory"
    async with app.state.session_factory() as db:
        other_site = await db.get(Site, workspace_records["other_site_id"])
        assert other_site.name == "Other Plant"


async def test_multi_workspace_user_must_choose_and_sees_only_chosen_tenant(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    async with app.state.session_factory() as db:
        db.add(
            TenantMembership(
                tenant_id=workspace_records["other_tenant_id"],
                user_id=workspace_records["user_id"],
                role="read_only",
                site_scope="all",
            )
        )
        await db.commit()
    await sign_in_as(client, "owner@example.com")

    assert (await client.get("/api/v1/auth/session")).json()["active_tenant"] is None
    assert (await client.get("/api/v1/workspace/dashboard")).status_code == 409

    selected = await client.post(
        "/api/v1/auth/select-tenant",
        headers=csrf_headers(client),
        json={"tenant_id": str(workspace_records["other_tenant_id"])},
    )
    assert selected.status_code == 200
    dashboard = (await client.get("/api/v1/workspace/dashboard")).json()
    assert dashboard["company_name"] == "Other Factory"
    assert [site["name"] for site in dashboard["sites"]] == ["Other Plant"]

    # Role is per workspace: owner of Acme, read-only in Other Factory.
    setup = await client.put(
        "/api/v1/onboarding/workspace", headers=csrf_headers(client), json=SETUP_PAYLOAD
    )
    assert setup.status_code == 403


async def test_select_tenant_rejects_suspended_membership(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    async with app.state.session_factory() as db:
        db.add(
            TenantMembership(
                tenant_id=workspace_records["other_tenant_id"],
                user_id=workspace_records["user_id"],
                role="owner",
                status="suspended",
            )
        )
        await db.commit()
    await sign_in_as(client, "owner@example.com")

    response = await client.post(
        "/api/v1/auth/select-tenant",
        headers=csrf_headers(client),
        json={"tenant_id": str(workspace_records["other_tenant_id"])},
    )

    assert response.status_code == 403
    assert (await current_session(client)).active_tenant_id == workspace_records["tenant_id"]


async def test_membership_suspended_mid_session_loses_access(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    await sign_in_as(client, "owner@example.com")
    async with app.state.session_factory() as db:
        membership = await db.scalar(
            select(TenantMembership).where(
                TenantMembership.user_id == workspace_records["user_id"]
            )
        )
        membership.status = "suspended"
        await db.commit()

    assert (await client.get("/api/v1/workspace/dashboard")).status_code == 403
    setup = await client.put(
        "/api/v1/onboarding/workspace", headers=csrf_headers(client), json=SETUP_PAYLOAD
    )
    assert setup.status_code == 403
    assert await tenant_name(workspace_records["tenant_id"]) == "Acme Pumps"


async def test_tenant_suspended_mid_session_loses_access(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    await sign_in_as(client, "owner@example.com")
    async with app.state.session_factory() as db:
        tenant = await db.get(Tenant, workspace_records["tenant_id"])
        tenant.status = "suspended"
        await db.commit()

    assert (await client.get("/api/v1/workspace/dashboard")).status_code == 403
    session = (await client.get("/api/v1/auth/session")).json()
    assert session["memberships"] == []
    assert session["active_tenant"] is None


async def test_user_suspended_mid_session_loses_access(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    await sign_in_as(client, "owner@example.com")
    async with app.state.session_factory() as db:
        user = await db.get(User, workspace_records["user_id"])
        user.status = "suspended"
        await db.commit()

    assert (await client.get("/api/v1/auth/session")).status_code == 401
    assert (await client.get("/api/v1/workspace/dashboard")).status_code == 403


async def test_revoked_session_cookie_cannot_be_replayed(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    await sign_in_as(client, "owner@example.com")
    stolen_session = client.cookies["thodara_session"]
    stolen_csrf = client.cookies["thodara_csrf"]
    logout = await client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    assert logout.status_code == 204

    client.cookies.set("thodara_session", stolen_session)
    client.cookies.set("thodara_csrf", stolen_csrf)

    assert (await client.get("/api/v1/workspace/dashboard")).status_code == 401
    replay = await client.put(
        "/api/v1/onboarding/workspace",
        headers={"Origin": ORIGIN, "X-CSRF-Token": stolen_csrf},
        json=SETUP_PAYLOAD,
    )
    assert replay.status_code == 401
    assert await tenant_name(workspace_records["tenant_id"]) == "Acme Pumps"


async def test_csrf_token_must_match_the_session(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    await sign_in_as(client, "owner@example.com")
    first_csrf = client.cookies["thodara_csrf"]
    await sign_in_as(client, "owner@example.com")
    assert client.cookies["thodara_csrf"] != first_csrf

    cases = [
        {"Origin": ORIGIN},
        {"Origin": ORIGIN, "X-CSRF-Token": "forged-token"},
        {"Origin": ORIGIN, "X-CSRF-Token": first_csrf},
    ]
    for headers in cases:
        response = await client.put(
            "/api/v1/onboarding/workspace", headers=headers, json=SETUP_PAYLOAD
        )
        assert response.status_code == 403, headers
    assert await tenant_name(workspace_records["tenant_id"]) == "Acme Pumps"


async def test_csrf_header_without_matching_cookie_is_rejected(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    await sign_in_as(client, "owner@example.com")
    csrf = client.cookies["thodara_csrf"]
    client.cookies.delete("thodara_csrf")

    response = await client.put(
        "/api/v1/onboarding/workspace",
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
        json=SETUP_PAYLOAD,
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/auth/session"),
        ("GET", "/api/v1/workspace/dashboard"),
        ("POST", "/api/v1/auth/logout"),
        ("POST", "/api/v1/auth/select-tenant"),
        ("PUT", "/api/v1/onboarding/workspace"),
    ],
)
async def test_protected_endpoints_require_a_session(
    client: AsyncClient, workspace_records: dict[str, object], method: str, path: str
) -> None:
    client.cookies.set("thodara_session", "not-a-real-session-token")
    response = await client.request(method, path, headers={"Origin": ORIGIN}, json={})
    assert response.status_code == 401
