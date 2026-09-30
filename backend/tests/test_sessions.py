from datetime import UTC, datetime, timedelta

from conftest import ORIGIN, TEST_PASSWORD, AddMember, csrf_headers, sign_in_as
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.security import token_digest
from app.main import app
from app.models import AuditEvent, AuthSession, TenantMembership, User


def second_client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url=ORIGIN,
        headers={"User-Agent": "Mozilla/5.0 (iPhone) Mobile Safari"},
    )


async def session_row(client: AsyncClient) -> AuthSession:
    async with app.state.session_factory() as db:
        row = await db.scalar(
            select(AuthSession).where(
                AuthSession.token_hash == token_digest(client.cookies["thodara_session"])
            )
        )
        assert row is not None
        return row


async def test_session_list_shows_own_active_sessions_and_marks_current(
    client: AsyncClient, workspace_records: dict[str, object], add_member: AddMember
) -> None:
    await add_member("other@example.com", "read_only")
    async with second_client() as phone, second_client() as stranger:
        await sign_in_as(phone, "owner@example.com")
        await sign_in_as(stranger, "other@example.com")
        await sign_in_as(client, "owner@example.com")

        sessions = (await client.get("/api/v1/auth/sessions")).json()

    assert len(sessions) == 2
    assert [s["current"] for s in sessions].count(True) == 1
    assert any("iPhone" in (s["user_agent"] or "") for s in sessions)
    assert all(s["last_seen_at"] for s in sessions)


async def test_revoking_another_session_signs_that_device_out(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    async with second_client() as phone:
        await sign_in_as(phone, "owner@example.com")
        await sign_in_as(client, "owner@example.com")
        phone_session = await session_row(phone)

        response = await client.post(
            f"/api/v1/auth/sessions/{phone_session.id}/revoke", headers=csrf_headers(client)
        )

        assert response.status_code == 204
        assert (await phone.get("/api/v1/auth/session")).status_code == 401
        assert (await client.get("/api/v1/auth/session")).status_code == 200

    async with app.state.session_factory() as db:
        event = await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "auth.session_revoked")
        )
    assert event.details == {"session_id": str(phone_session.id)}
    assert event.actor_user_id == workspace_records["user_id"]


async def test_cannot_revoke_current_or_someone_elses_session(
    client: AsyncClient, workspace_records: dict[str, object], add_member: AddMember
) -> None:
    await add_member("other@example.com", "owner")
    async with second_client() as stranger:
        await sign_in_as(stranger, "other@example.com")
        await sign_in_as(client, "owner@example.com")
        mine = await session_row(client)
        theirs = await session_row(stranger)

        own = await client.post(
            f"/api/v1/auth/sessions/{mine.id}/revoke", headers=csrf_headers(client)
        )
        foreign = await client.post(
            f"/api/v1/auth/sessions/{theirs.id}/revoke", headers=csrf_headers(client)
        )
        no_csrf = await client.post(
            f"/api/v1/auth/sessions/{theirs.id}/revoke", headers={"Origin": ORIGIN}
        )

        assert own.status_code == 409
        assert foreign.status_code == 404
        assert no_csrf.status_code == 403
        assert (await stranger.get("/api/v1/auth/session")).status_code == 200


async def test_revoke_all_other_sessions_keeps_the_current_one(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    async with second_client() as phone, second_client() as tablet:
        await sign_in_as(phone, "owner@example.com")
        await sign_in_as(tablet, "owner@example.com")
        await sign_in_as(client, "owner@example.com")

        response = await client.post(
            "/api/v1/auth/sessions/revoke-others", headers=csrf_headers(client)
        )

        assert response.json() == {"revoked": 2}
        assert (await phone.get("/api/v1/auth/session")).status_code == 401
        assert (await tablet.get("/api/v1/auth/session")).status_code == 401
        assert (await client.get("/api/v1/auth/session")).status_code == 200
        assert len((await client.get("/api/v1/auth/sessions")).json()) == 1


async def test_last_seen_is_refreshed_only_after_the_interval(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    await sign_in_as(client, "owner@example.com")
    first = (await session_row(client)).last_seen_at

    await client.get("/api/v1/auth/session")
    assert (await session_row(client)).last_seen_at == first

    async with app.state.session_factory() as db:
        row = await db.get(AuthSession, (await session_row(client)).id)
        row.last_seen_at = datetime.now(UTC) - timedelta(minutes=10)
        await db.commit()
    await client.get("/api/v1/auth/session")
    refreshed = (await session_row(client)).last_seen_at
    if refreshed.tzinfo is None:
        refreshed = refreshed.replace(tzinfo=UTC)
    assert datetime.now(UTC) - refreshed < timedelta(minutes=1)


async def test_audit_events_record_actor_type_source_and_label(
    client: AsyncClient, workspace_records: dict[str, object]
) -> None:
    await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "guess-password"},
        headers={"Origin": ORIGIN},
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as script:
        await script.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.com", "password": TEST_PASSWORD},
        )
    await sign_in_as(client, "owner@example.com")

    async with app.state.session_factory() as db:
        events = (
            await db.scalars(select(AuditEvent).order_by(AuditEvent.created_at))
        ).all()
    failed = next(e for e in events if e.action == "auth.login_failed")
    logins = [e for e in events if e.action == "auth.login_succeeded"]

    assert (failed.actor_type, failed.actor_label, failed.source_channel) == (
        "anonymous",
        None,
        "web",
    )
    assert {e.source_channel for e in logins} == {"api", "web"}
    assert all(e.actor_type == "user" for e in logins)
    assert all(e.actor_label == "A. Owner <owner@example.com>" for e in logins)


async def test_attribution_survives_user_removal(
    client: AsyncClient, workspace_records: dict[str, object], add_member: AddMember
) -> None:
    await add_member("leaver@example.com", "owner")
    await sign_in_as(client, "leaver@example.com")
    await client.post(
        "/api/v1/master-data/customers",
        headers=csrf_headers(client),
        json={"code": "ACME", "name": "Acme"},
    )
    async with app.state.session_factory() as db:
        leaver = await db.scalar(select(User).where(User.email == "leaver@example.com"))
        await db.execute(delete(TenantMembership).where(TenantMembership.user_id == leaver.id))
        await db.execute(delete(AuthSession).where(AuthSession.user_id == leaver.id))
        await db.delete(leaver)
        await db.commit()

    async with app.state.session_factory() as db:
        event = await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "masterdata.customer.created")
        )
    assert event.actor_user_id is None
    assert event.actor_label == "leaver <leaver@example.com>"
