"""Slice G7: two-step sign-in with an authenticator app (ADR-0015)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from conftest import ORIGIN, TEST_PASSWORD, AddMember, csrf_headers, sign_in_as
from httpx import AsyncClient
from sqlalchemy import select

from app.core import two_step as totp
from app.core.config import DEV_TWO_STEP_KEY, Settings
from app.core.security import token_digest
from app.main import app
from app.models import AuditEvent, AuthSession, User

API = "/api/v1"
OWNER = "owner@example.com"


class Clock:
    """Authenticator codes depend on the time; tests move this clock in 30-second steps."""

    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def time(self) -> float:
        return self.now

    def tick(self) -> None:
        self.now += totp.STEP_SECONDS


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(totp, "time", fake)
    return fake


def code(secret: str, clock: Clock) -> str:
    return totp.code_at(secret, totp.current_step(clock.now))


async def login(client: AsyncClient, email: str = OWNER, expect: int = 200) -> dict:
    response = await client.post(
        f"{API}/auth/login",
        json={"email": email, "password": TEST_PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == expect, response.text
    return response.json()


async def call(client: AsyncClient, path: str, body: dict | None = None, expect: int = 200):
    response = await client.post(f"{API}{path}", json=body or {}, headers=csrf_headers(client))
    assert response.status_code == expect, response.text
    return response.json() if response.content else None


async def logout(client: AsyncClient) -> None:
    await call(client, "/auth/logout", expect=204)


async def turn_on(client: AsyncClient, clock: Clock) -> tuple[str, list[str]]:
    setup = await call(client, "/auth/two-step/setup")
    enabled = await call(client, "/auth/two-step/enable", {"code": code(setup["secret"], clock)})
    clock.tick()
    return setup["secret"], enabled["backup_codes"]


async def user_row(email: str) -> User:
    async with app.state.session_factory() as db:
        return await db.scalar(select(User).where(User.email_normalized == email))


async def update_user(email: str, **values: object) -> None:
    async with app.state.session_factory() as db:
        user = await db.scalar(select(User).where(User.email_normalized == email))
        for key, value in values.items():
            setattr(user, key, value)
        await db.commit()


async def actions() -> list[AuditEvent]:
    async with app.state.session_factory() as db:
        return list(await db.scalars(select(AuditEvent).order_by(AuditEvent.created_at)))


async def test_owner_sets_up_and_then_needs_a_code_at_every_sign_in(
    client: AsyncClient, workspace_records: dict, clock: Clock
) -> None:
    first = await login(client)
    state = first["two_step"]
    assert (state["stage"], state["required"], state["enabled"]) == ("full", True, False)
    due = datetime.fromisoformat(state["due_at"])
    assert timedelta(days=6, hours=23) < due - datetime.now(UTC) <= timedelta(days=7)

    setup = await call(client, "/auth/two-step/setup")
    assert setup["otpauth_uri"].startswith("otpauth://totp/Thodara:owner%40example.com?")
    assert f"secret={setup['secret']}" in setup["otpauth_uri"]
    assert setup["qr_svg"].startswith("<svg")
    stored = await user_row(OWNER)
    assert stored.totp_pending_secret and setup["secret"] not in stored.totp_pending_secret
    assert stored.totp_enabled_at is None  # nothing changes until a code confirms it

    await call(client, "/auth/two-step/enable", {"code": "000000"}, expect=422)
    enabled = await call(client, "/auth/two-step/enable", {"code": code(setup["secret"], clock)})
    assert len(set(enabled["backup_codes"])) == 10
    assert enabled["session"]["two_step"]["enabled"] is True
    assert enabled["session"]["two_step"]["due_at"] is None
    assert enabled["session"]["two_step"]["backup_codes_left"] == 10
    await logout(client)

    # The password alone opens nothing.
    partial = await login(client)
    assert partial["two_step"]["stage"] == "verify"
    assert partial["memberships"] == [] and partial["active_tenant"] is None
    for path in ("/workspace/dashboard", "/auth/sessions", "/organization/members"):
        assert (await client.get(f"{API}{path}")).status_code == 401
    await call(
        client,
        "/auth/select-tenant",
        {"tenant_id": str(workspace_records["tenant_id"])},
        expect=401,
    )
    session = (await client.get(f"{API}/auth/session")).json()
    assert session["two_step"]["stage"] == "verify"

    # The code used to turn it on cannot be used again, even within its time window.
    await call(
        client, "/auth/two-step/verify", {"code": code(setup["secret"], Clock())}, expect=401
    )
    clock.tick()
    partial_token = client.cookies["thodara_session"]
    done = await call(client, "/auth/two-step/verify", {"code": code(setup["secret"], clock)})
    assert done["two_step"]["stage"] == "full" and done["active_tenant"] is not None
    assert client.cookies["thodara_session"] != partial_token  # a new session, not upgraded
    async with app.state.session_factory() as db:
        old_session = await db.scalar(
            select(AuthSession).where(AuthSession.token_hash == token_digest(partial_token))
        )
    assert old_session.revoked_at is not None  # the password-only session is over
    assert (await client.get(f"{API}/workspace/dashboard")).status_code == 200
    await call(client, "/auth/two-step/verify", {"code": "123456"}, expect=409)

    events = await actions()
    names = [e.action for e in events]
    assert "auth.two_step_enabled" in names and "auth.password_accepted" in names
    succeeded = [e for e in events if e.action == "auth.login_succeeded"]
    assert succeeded[-1].details["two_step"] == "authenticator"
    failed = [e for e in events if e.action == "auth.two_step_failed"]
    assert len(failed) == 1 and failed[0].actor_type == "anonymous"


async def test_backup_codes_work_once_and_can_be_replaced(
    client: AsyncClient, workspace_records: dict, clock: Clock
) -> None:
    await login(client)
    secret, backups = await turn_on(client, clock)
    await logout(client)

    await login(client)
    done = await call(client, "/auth/two-step/verify", {"code": backups[0].lower()})
    assert done["two_step"]["backup_codes_left"] == 9
    await logout(client)
    await login(client)
    await call(client, "/auth/two-step/verify", {"code": backups[0]}, expect=401)
    await call(client, "/auth/two-step/verify", {"code": code(secret, clock)})
    clock.tick()

    # New codes need the authenticator, not a backup code; old codes stop working.
    await call(client, "/auth/two-step/backup-codes", {"code": backups[1]}, expect=422)
    fresh = (await call(client, "/auth/two-step/backup-codes", {"code": code(secret, clock)}))[
        "backup_codes"
    ]
    assert not set(fresh) & set(backups)
    await logout(client)
    await login(client)
    await call(client, "/auth/two-step/verify", {"code": backups[1]}, expect=401)
    await call(client, "/auth/two-step/verify", {"code": fresh[0].replace("-", "")})
    names = [e.action for e in await actions()]
    assert "auth.backup_code_used" in names and "auth.backup_codes_replaced" in names


async def test_five_wrong_codes_pause_code_entry(
    client: AsyncClient, workspace_records: dict, clock: Clock
) -> None:
    await login(client)
    secret, _ = await turn_on(client, clock)
    await logout(client)
    await login(client)
    for _ in range(4):
        await call(client, "/auth/two-step/verify", {"code": "000000"}, expect=401)
    tired = await call(client, "/auth/two-step/verify", {"code": "000000"}, expect=429)
    assert "15 minutes" in tired["detail"]
    # That session is over; a new password sign-in still cannot enter codes for now.
    assert (await client.get(f"{API}/auth/session")).status_code == 401
    await login(client)
    await call(client, "/auth/two-step/verify", {"code": code(secret, clock)}, expect=429)
    await update_user(OWNER, two_step_locked_until=datetime.now(UTC) - timedelta(seconds=1))
    await call(client, "/auth/two-step/verify", {"code": code(secret, clock)})
    assert (await user_row(OWNER)).two_step_failures == 0


async def test_after_the_grace_period_set_up_comes_first(
    client: AsyncClient, workspace_records: dict, clock: Clock
) -> None:
    await login(client)
    await logout(client)
    first_due = (await user_row(OWNER)).two_step_due_at
    await login(client)
    assert (await user_row(OWNER)).two_step_due_at == first_due  # the clock does not restart
    await logout(client)

    await update_user(OWNER, two_step_due_at=datetime.now(UTC) - timedelta(minutes=1))
    gate = await login(client)
    assert gate["two_step"]["stage"] == "enrol" and gate["memberships"] == []
    assert (await client.get(f"{API}/workspace/dashboard")).status_code == 401
    secret = (await call(client, "/auth/two-step/setup"))["secret"]
    enabled = await call(client, "/auth/two-step/enable", {"code": code(secret, clock)})
    assert enabled["session"]["two_step"]["stage"] == "full"
    assert enabled["session"]["active_tenant"] is not None
    assert (await client.get(f"{API}/workspace/dashboard")).status_code == 200
    succeeded = [e for e in await actions() if e.action == "auth.login_succeeded"]
    assert succeeded[-1].details["two_step"] == "enrolled"


async def test_optional_for_others_who_may_turn_it_off(
    client: AsyncClient, workspace_records: dict, add_member: AddMember, clock: Clock
) -> None:
    await add_member("qc@example.com", "quality", site_ids=[workspace_records["site_id"]])
    signed_in = await login(client, "qc@example.com")
    assert signed_in["two_step"] == {
        "stage": "full",
        "enabled": False,
        "required": False,
        "due_at": None,
        "backup_codes_left": 0,
    }
    assert (await user_row("qc@example.com")).two_step_due_at is None
    secret, _ = await turn_on(client, clock)
    await call(client, "/auth/two-step/disable", {"code": "000000"}, expect=422)
    off = await call(client, "/auth/two-step/disable", {"code": code(secret, clock)})
    assert off["two_step"]["enabled"] is False
    await logout(client)
    assert (await login(client, "qc@example.com"))["two_step"]["stage"] == "full"

    await logout(client)
    await login(client)
    owner_secret, _ = await turn_on(client, clock)
    refused = await call(
        client, "/auth/two-step/disable", {"code": code(owner_secret, clock)}, expect=409
    )
    assert "must keep two-step" in refused["detail"]


async def test_an_administrator_resets_someone_who_lost_their_phone(
    client: AsyncClient, workspace_records: dict, add_member: AddMember, clock: Clock
) -> None:
    await login(client)
    await turn_on(client, clock)
    await logout(client)
    await add_member("admin@example.com", "administrator")
    await add_member("admin2@example.com", "administrator")
    other = await add_member(
        "elsewhere@example.com", "quality", tenant_id=workspace_records["other_tenant_id"]
    )
    await login(client, "admin@example.com")
    members = (await client.get(f"{API}/organization/members")).json()
    by_email = {m["email"]: m for m in members}
    assert by_email[OWNER]["two_step_enabled"] is True
    owner_membership = by_email[OWNER]["membership_id"]

    path = "/organization/members/{}/reset-two-step"
    await call(client, path.format(by_email["admin@example.com"]["membership_id"]), expect=409)
    async with app.state.session_factory() as db:
        from app.models import TenantMembership

        elsewhere = await db.scalar(
            select(TenantMembership.id).where(TenantMembership.user_id == other)
        )
    await call(client, path.format(elsewhere), expect=404)
    await call(client, path.format(uuid.uuid4()), expect=404)
    reset = await call(client, path.format(owner_membership))
    assert reset["two_step_enabled"] is False

    owner = await user_row(OWNER)
    assert owner.totp_secret is None and owner.totp_enabled_at is None
    async with app.state.session_factory() as db:
        live = await db.scalars(
            select(AuthSession).where(
                AuthSession.user_id == owner.id, AuthSession.revoked_at.is_(None)
            )
        )
        assert list(live) == []  # signed out everywhere
    event = next(e for e in await actions() if e.action == "organization.member.two_step_reset")
    assert event.details["was_enabled"] is True
    assert event.tenant_id == workspace_records["tenant_id"]
    await logout(client)

    # No grace the second time: set-up comes first.
    assert (await login(client))["two_step"]["stage"] == "enrol"
    await turn_on(client, clock)
    # The owner (not an administrator) cannot reset anyone.
    await call(client, path.format(by_email["admin2@example.com"]["membership_id"]), expect=403)


def test_authenticator_codes_match_rfc_6238() -> None:
    import base64

    secret = base64.b32encode(b"12345678901234567890").decode()
    # RFC 6238 appendix B (SHA-1), last six digits.
    assert totp.code_at(secret, 59 // 30) == "287082"
    assert totp.code_at(secret, 1111111109 // 30) == "081804"
    assert totp.code_at(secret, 2000000000 // 30) == "279037"
    assert totp.matching_step(secret, "287082", now=59) == 1
    assert totp.matching_step(secret, "287082", now=59 + 30) == 1  # one step of clock drift
    assert totp.matching_step(secret, "287082", now=59 + 60) is None
    assert totp.matching_step(secret, "28708", now=59) is None


def test_secrets_are_sealed_per_user() -> None:
    alice, bob = uuid.uuid4(), uuid.uuid4()
    sealed = totp.encrypt_secret("JBSWY3DPEHPK3PXP", alice)
    assert "JBSWY3DP" not in sealed
    assert totp.decrypt_secret(sealed, alice) == "JBSWY3DPEHPK3PXP"
    with pytest.raises(ValueError):
        totp.decrypt_secret(sealed, bob)  # copying a secret to another account fails
    assert totp.backup_code_hash("abcde-fghjk", alice) == totp.backup_code_hash("ABCDEFGHJK", alice)
    assert totp.backup_code_hash("ABCDEFGHJK", alice) != totp.backup_code_hash("ABCDEFGHJK", bob)


def test_production_needs_its_own_two_step_key() -> None:
    production = {
        "app_env": "production",
        "session_cookie_secure": True,
        "allowed_hosts": ["erp.example.in"],
        "allowed_origins": ["https://erp.example.in"],
        "database_url": "postgresql+asyncpg://u:p@db.internal/thodara",
    }
    with pytest.raises(ValueError, match="THODARA_TWO_STEP_KEY"):
        Settings(**production, two_step_key=DEV_TWO_STEP_KEY)
    with pytest.raises(ValueError, match="32 bytes"):
        Settings(two_step_key="c2hvcnQ=")
    assert Settings(**production, two_step_key="A" * 43 + "=").app_env == "production"


async def test_a_partly_signed_in_session_can_sign_out(
    client: AsyncClient, workspace_records: dict, clock: Clock
) -> None:
    await login(client)
    await turn_on(client, clock)
    await logout(client)
    await login(client)
    await call(client, "/auth/logout", expect=204)
    assert (await client.get(f"{API}/auth/session")).status_code == 401
    await sign_in_as(client, OWNER)  # the shared helper still works: it stops at "verify"


async def test_support_reset_from_the_command_line(
    client: AsyncClient,
    workspace_records: dict,
    add_member: AddMember,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import argparse

    from app import cli

    class NoEngine:
        async def dispose(self) -> None:
            return None

    monkeypatch.setattr(cli, "SessionFactory", app.state.session_factory)
    monkeypatch.setattr(cli, "engine", NoEngine())
    await add_member("qc@example.com", "quality", site_ids=[workspace_records["site_id"]])
    await login(client, "qc@example.com")
    await turn_on(client, clock)
    await logout(client)
    await login(client)
    await turn_on(client, clock)

    with pytest.raises(SystemExit, match="reason"):
        await cli.reset_two_step(argparse.Namespace(email=OWNER, reason="lost"))
    await cli.reset_two_step(argparse.Namespace(email=OWNER, reason="Ticket 42: phone stolen"))
    await cli.reset_two_step(
        argparse.Namespace(email="QC@example.com", reason="Ticket 43: new phone")
    )
    assert (await client.get(f"{API}/auth/session")).status_code == 401
    owner, qc = await user_row(OWNER), await user_row("qc@example.com")
    assert owner.totp_secret is None and owner.two_step_due_at is not None
    assert qc.totp_secret is None and qc.two_step_due_at is None  # optional for them
    events = [e for e in await actions() if e.action == "support.two_step_reset"]
    assert [(e.actor_type, e.source_channel) for e in events] == [("system", "cli")] * 2
    assert events[0].details["reason"] == "Ticket 42: phone stolen"
    assert events[0].tenant_id == workspace_records["tenant_id"]
    assert (await login(client))["two_step"]["stage"] == "enrol"
    assert (await login(client, "qc@example.com"))["two_step"]["stage"] == "full"
