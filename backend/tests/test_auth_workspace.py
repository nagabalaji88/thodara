from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import token_digest
from app.main import app
from app.models import AuditEvent, AuthSession, TenantMembership, User


async def sign_in(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "a-secure-test-password"},
        headers={"Origin": "http://localhost:5173"},
    )
    assert response.status_code == 200
    assert "thodara_session" in client.cookies
    assert "thodara_csrf" in client.cookies


async def test_login_scope_and_revocable_csrf_protected_session(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    await sign_in(client)
    session = await client.get("/api/v1/auth/session")
    assert session.status_code == 200
    assert session.json()["active_tenant"]["tenant_name"] == "Acme Pumps"

    dashboard = await client.get("/api/v1/workspace/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["company_name"] == "Acme Pumps"
    assert all(site["name"] != "Other Plant" for site in dashboard.json()["sites"])

    cross_tenant = await client.post(
        "/api/v1/auth/select-tenant",
        json={"tenant_id": str(workspace_records["other_tenant_id"])},
        headers={"Origin": "http://localhost:5173", "X-CSRF-Token": client.cookies["thodara_csrf"]},
    )
    assert cross_tenant.status_code == 403

    missing_csrf = await client.post(
        "/api/v1/auth/logout", headers={"Origin": "http://localhost:5173"}
    )
    assert missing_csrf.status_code == 403

    logout = await client.post(
        "/api/v1/auth/logout",
        headers={"Origin": "http://localhost:5173", "X-CSRF-Token": client.cookies["thodara_csrf"]},
    )
    assert logout.status_code == 204
    assert (await client.get("/api/v1/auth/session")).status_code == 401


async def test_workspace_setup_is_audited_and_requires_owner_permission(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    await sign_in(client)
    response = await client.put(
        "/api/v1/onboarding/workspace",
        headers={"Origin": "http://localhost:5173", "X-CSRF-Token": client.cookies["thodara_csrf"]},
        json={
            "company_name": "Acme Pumps India",
            "country_code": "IN",
            "base_currency": "INR",
            "site_name": "Coimbatore Plant",
            "city": "Coimbatore",
            "time_zone": "Asia/Kolkata",
        },
    )
    assert response.status_code == 200
    assert response.json()["setup_complete"] is True
    assert response.json()["sites"][0]["city"] == "Coimbatore"
    async with app.state.session_factory() as db:
        event = await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "tenant.setup_completed")
        )
        assert event is not None
        assert event.tenant_id == workspace_records["tenant_id"]


async def test_read_only_membership_cannot_change_workspace(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    async with app.state.session_factory() as db:
        membership = await db.scalar(
            select(TenantMembership).where(TenantMembership.user_id == workspace_records["user_id"])
        )
        assert membership is not None
        membership.role = "read_only"
        await db.commit()
    await sign_in(client)
    response = await client.put(
        "/api/v1/onboarding/workspace",
        headers={"Origin": "http://localhost:5173", "X-CSRF-Token": client.cookies["thodara_csrf"]},
        json={
            "company_name": "Acme Pumps India",
            "country_code": "IN",
            "base_currency": "INR",
            "site_name": "Coimbatore Plant",
            "city": "Coimbatore",
            "time_zone": "Asia/Kolkata",
        },
    )
    assert response.status_code == 403


async def test_expired_session_and_health_endpoints(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    assert (await client.get("/api/v1/workspace/dashboard")).status_code == 401
    assert (await client.get("/health/live")).json() == {"status": "alive"}
    assert (await client.get("/health/ready")).json() == {"status": "ready"}
    await sign_in(client)
    async with app.state.session_factory() as db:
        session = await db.scalar(
            select(AuthSession).where(
                AuthSession.token_hash == token_digest(client.cookies["thodara_session"])
            )
        )
        assert session is not None
        session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    assert (await client.get("/api/v1/auth/session")).status_code == 401


async def test_failed_login_uses_same_message_for_unknown_and_wrong_password(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    unknown = await client.post(
        "/api/v1/auth/login",
        json={"email": "missing@example.com", "password": "not-the-password"},
        headers={"Origin": "http://localhost:5173"},
    )
    wrong = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "not-the-password"},
        headers={"Origin": "http://localhost:5173"},
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]
    assert "thodara_session" not in client.cookies


async def test_lockout_does_not_extend_and_valid_password_still_works(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    headers = {"Origin": "http://localhost:5173"}
    for _ in range(5):
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.com", "password": "wrong-password"},
            headers=headers,
        )
        assert response.status_code == 401

    async with app.state.session_factory() as db:
        user = await db.get(User, workspace_records["user_id"])
        assert user is not None
        assert user.locked_until is not None
        first_lock_expiry = user.locked_until

    locked_attempt = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "wrong-password"},
        headers=headers,
    )
    assert locked_attempt.status_code == 401

    async with app.state.session_factory() as db:
        user = await db.get(User, workspace_records["user_id"])
        assert user is not None
        assert user.locked_until == first_lock_expiry

    valid = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "a-secure-test-password"},
        headers=headers,
    )
    assert valid.status_code == 200
    async with app.state.session_factory() as db:
        user = await db.get(User, workspace_records["user_id"])
        assert user is not None
        assert user.locked_until is None
        assert user.failed_login_count == 0


async def test_suspended_user_gets_generic_login_failure(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    async with app.state.session_factory() as db:
        user = await db.get(User, workspace_records["user_id"])
        assert user is not None
        user.status = "suspended"
        await db.commit()
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "a-secure-test-password"},
        headers={"Origin": "http://localhost:5173"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Email or password is incorrect"


async def test_unsafe_request_rejects_untrusted_origin(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "any-password"},
        headers={"Origin": "https://attacker.example"},
    )
    assert response.status_code == 403
