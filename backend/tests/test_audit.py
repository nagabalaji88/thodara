import json

import pytest
from conftest import ORIGIN, TEST_PASSWORD, csrf_headers, sign_in_as
from httpx import AsyncClient, Response
from sqlalchemy import select

from app.main import app
from app.models import AuditEvent, TenantMembership

SETUP_PAYLOAD = {
    "company_name": "Acme Pumps India",
    "country_code": "IN",
    "base_currency": "INR",
    "site_name": "Coimbatore Plant",
    "city": "Coimbatore",
    "time_zone": "Asia/Kolkata",
}


async def events(action: str | None = None) -> list[AuditEvent]:
    async with app.state.session_factory() as db:
        query = select(AuditEvent).order_by(AuditEvent.created_at)
        if action is not None:
            query = query.where(AuditEvent.action == action)
        return list((await db.scalars(query)).all())


async def only_event(action: str) -> AuditEvent:
    found = await events(action)
    assert len(found) == 1, [event.action for event in found]
    return found[0]


def assert_traceable(event: AuditEvent, response: Response) -> None:
    assert event.request_id == response.headers["X-Request-ID"]
    assert event.created_at is not None


async def test_failed_login_for_unknown_email_is_audited_without_actor(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "guessed-password"},
        headers={"Origin": ORIGIN},
    )

    assert response.status_code == 401
    event = await only_event("auth.login_failed")
    assert event.actor_user_id is None
    assert event.tenant_id is None
    assert event.details == {"reason": "invalid_or_unavailable_account"}
    assert_traceable(event, response)


async def test_failed_login_for_known_user_names_the_account(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "guessed-password"},
        headers={"Origin": ORIGIN},
    )

    event = await only_event("auth.login_failed")
    assert event.actor_user_id == workspace_records["user_id"]
    assert_traceable(event, response)


async def test_successful_login_and_logout_are_audited_in_the_workspace(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": TEST_PASSWORD},
        headers={"Origin": ORIGIN},
    )
    logout = await client.post("/api/v1/auth/logout", headers=csrf_headers(client))

    login_event = await only_event("auth.login_succeeded")
    assert login_event.actor_user_id == workspace_records["user_id"]
    assert login_event.tenant_id == workspace_records["tenant_id"]
    assert login_event.details == {"membership_count": 1}
    assert_traceable(login_event, login)

    logout_event = await only_event("auth.logout")
    assert logout_event.actor_user_id == workspace_records["user_id"]
    assert logout_event.tenant_id == workspace_records["tenant_id"]
    assert_traceable(logout_event, logout)


async def test_workspace_setup_event_is_attributed_and_traceable(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    await sign_in_as(client, "owner@example.com")
    response = await client.put(
        "/api/v1/onboarding/workspace", headers=csrf_headers(client), json=SETUP_PAYLOAD
    )

    assert response.status_code == 200
    event = await only_event("tenant.setup_completed")
    assert event.actor_user_id == workspace_records["user_id"]
    assert event.tenant_id == workspace_records["tenant_id"]
    assert event.details["site_id"] == str(workspace_records["site_id"])
    assert_traceable(event, response)


async def test_denied_setup_writes_no_setup_event(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    async with app.state.session_factory() as db:
        membership = await db.scalar(
            select(TenantMembership).where(
                TenantMembership.user_id == workspace_records["user_id"]
            )
        )
        membership.role = "read_only"
        await db.commit()
    await sign_in_as(client, "owner@example.com")

    forbidden = await client.put(
        "/api/v1/onboarding/workspace", headers=csrf_headers(client), json=SETUP_PAYLOAD
    )
    no_csrf = await client.put(
        "/api/v1/onboarding/workspace", headers={"Origin": ORIGIN}, json=SETUP_PAYLOAD
    )

    assert forbidden.status_code == no_csrf.status_code == 403
    assert await events("tenant.setup_completed") == []


async def test_invalid_setup_payload_writes_no_setup_event(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    await sign_in_as(client, "owner@example.com")

    response = await client.put(
        "/api/v1/onboarding/workspace",
        headers=csrf_headers(client),
        json={**SETUP_PAYLOAD, "time_zone": "Not/AZone"},
    )

    assert response.status_code == 422
    assert await events("tenant.setup_completed") == []


async def test_audit_events_never_store_secrets(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "wrong-password-value"},
        headers={"Origin": ORIGIN},
    )
    await sign_in_as(client, "owner@example.com")
    secrets = {
        "wrong-password-value",
        TEST_PASSWORD,
        client.cookies["thodara_session"],
        client.cookies["thodara_csrf"],
    }
    await client.put(
        "/api/v1/onboarding/workspace", headers=csrf_headers(client), json=SETUP_PAYLOAD
    )
    await client.post("/api/v1/auth/logout", headers=csrf_headers(client))

    recorded = await events()
    assert {event.action for event in recorded} >= {
        "auth.login_failed",
        "auth.login_succeeded",
        "tenant.setup_completed",
        "auth.logout",
    }
    serialized = json.dumps([event.details for event in recorded])
    for secret in secrets:
        assert secret not in serialized


@pytest.mark.xfail(strict=True, reason="Known gap: switching workspace is not audited yet")
async def test_workspace_switch_is_audited(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    async with app.state.session_factory() as db:
        db.add(
            TenantMembership(
                tenant_id=workspace_records["other_tenant_id"],
                user_id=workspace_records["user_id"],
                role="read_only",
            )
        )
        await db.commit()
    await sign_in_as(client, "owner@example.com")
    await client.post(
        "/api/v1/auth/select-tenant",
        headers=csrf_headers(client),
        json={"tenant_id": str(workspace_records["other_tenant_id"])},
    )

    event = await only_event("auth.tenant_selected")
    assert event.tenant_id == workspace_records["other_tenant_id"]


@pytest.mark.xfail(
    strict=True, reason="Known gap: setup changes do not record previous and new values yet"
)
async def test_workspace_setup_records_before_and_after_values(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    await sign_in_as(client, "owner@example.com")
    await client.put(
        "/api/v1/onboarding/workspace", headers=csrf_headers(client), json=SETUP_PAYLOAD
    )

    event = await only_event("tenant.setup_completed")
    assert event.details["before"]["company_name"] == "Acme Pumps"
    assert event.details["after"]["company_name"] == "Acme Pumps India"
