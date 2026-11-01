"""Two-step sign-in rules (ADR-0015).

- Owners and administrators must use an authenticator app; anyone else may turn it on.
- People who must use it get 7 days from the first sign-in where it applies; after that, or
  after an administrator resets it, they set it up before they can continue.
- A code is needed at every password sign-in. Each authenticator code works once; backup codes
  are one-time and stored only as keyed hashes.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import two_step as totp
from app.models.identity import AuthSession, BackupCode, Tenant, TenantMembership, User
from app.schemas.auth import TwoStepState

REQUIRED_ROLES = frozenset({"owner", "administrator"})
GRACE = timedelta(days=7)
# A session waiting for a code (or for set-up) lasts only this long.
PARTIAL_SESSION = timedelta(minutes=15)
WRONG_CODE_LIMIT = 5

Method = Literal["authenticator", "backup_code"]


def aware(value: datetime | None) -> datetime | None:
    # SQLite-based tests return naive timestamps even for timezone-aware columns.
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


async def is_required(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """True when the user is an active owner or administrator of any active company."""
    found = await db.scalar(
        select(TenantMembership.id)
        .join(Tenant, Tenant.id == TenantMembership.tenant_id)
        .where(
            TenantMembership.user_id == user_id,
            TenantMembership.status == "active",
            TenantMembership.role.in_(REQUIRED_ROLES),
            Tenant.status == "active",
        )
        .limit(1)
    )
    return found is not None


async def backup_codes_left(db: AsyncSession, user_id: uuid.UUID) -> int:
    return int(
        await db.scalar(
            select(func.count(BackupCode.id)).where(
                BackupCode.user_id == user_id, BackupCode.used_at.is_(None)
            )
        )
        or 0
    )


async def state_for(db: AsyncSession, user: User, session: AuthSession) -> TwoStepState:
    enabled = user.totp_enabled_at is not None
    required = await is_required(db, user.id)
    return TwoStepState(
        stage=session.stage,  # type: ignore[arg-type]
        enabled=enabled,
        required=required,
        due_at=None if enabled or not required else aware(user.two_step_due_at),
        backup_codes_left=await backup_codes_left(db, user.id) if enabled else 0,
    )


async def stage_after_password(db: AsyncSession, user: User, now: datetime) -> str:
    """Decide what a correct password leads to. May start the grace period."""
    if user.totp_enabled_at is not None:
        return "verify"
    if not await is_required(db, user.id):
        return "full"
    if user.two_step_due_at is None:
        user.two_step_due_at = now + GRACE
    due = aware(user.two_step_due_at)
    return "enrol" if due is not None and due <= now else "full"


async def issue_backup_codes(db: AsyncSession, user: User) -> list[str]:
    """Replace every backup code the user has with ten new ones; returns them once."""
    await db.execute(delete(BackupCode).where(BackupCode.user_id == user.id))
    codes = totp.new_backup_codes()
    db.add_all(
        BackupCode(user_id=user.id, code_hash=totp.backup_code_hash(code, user.id))
        for code in codes
    )
    return codes


def authenticator_ok(user: User, secret: str, code: str) -> bool:
    """Checks a code and remembers its time step so it cannot be used again."""
    step = totp.matching_step(secret, code)
    if step is None or (user.totp_last_step is not None and step <= user.totp_last_step):
        return False
    user.totp_last_step = step
    return True


async def check_code(db: AsyncSession, user: User, code: str) -> Method | None:
    """An authenticator code or an unused backup code; marks either as used."""
    if user.totp_secret is None:
        return None
    if totp.looks_like_backup_code(code):
        backup = await db.scalar(
            select(BackupCode).where(
                BackupCode.user_id == user.id,
                BackupCode.code_hash == totp.backup_code_hash(code, user.id),
                BackupCode.used_at.is_(None),
            )
        )
        if backup is None:
            return None
        backup.used_at = datetime.now(UTC)
        return "backup_code"
    secret = totp.decrypt_secret(user.totp_secret, user.id)
    return "authenticator" if authenticator_ok(user, secret, code) else None


async def clear(db: AsyncSession, user: User) -> None:
    """Remove the authenticator and backup codes (turning off, or an administrator reset)."""
    user.totp_secret = None
    user.totp_pending_secret = None
    user.totp_enabled_at = None
    user.totp_last_step = None
    await db.execute(delete(BackupCode).where(BackupCode.user_id == user.id))


async def reset(db: AsyncSession, user: User, now: datetime) -> tuple[bool, int]:
    """Lost phone and backup codes: remove two-step and sign the person out everywhere.

    Owners and administrators get no new grace period. Returns (was it on, sessions ended).
    """
    was_enabled = user.totp_enabled_at is not None
    await clear(db, user)
    user.two_step_due_at = now if await is_required(db, user.id) else None
    user.two_step_failures = 0
    user.two_step_locked_until = None
    sessions = (
        await db.scalars(
            select(AuthSession).where(
                AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)
            )
        )
    ).all()
    for session in sessions:
        session.revoked_at = now
    return was_enabled, len(sessions)
