"""Two-step sign-in endpoints (ADR-0015)."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_any_session, get_auth_session, require_csrf_any
from app.api.session_support import build_session_response, open_session
from app.core import two_step as totp
from app.core.audit import record_event
from app.core.config import get_settings
from app.core.i18n import N_, tr
from app.db.session import get_db
from app.models.identity import AuthSession, User
from app.schemas.auth import (
    BackupCodes,
    SessionResponse,
    TwoStepCode,
    TwoStepEnabled,
    TwoStepSetup,
)
from app.services import two_step
from app.services.two_step import aware

router = APIRouter(
    prefix="/auth/two-step", tags=["authentication"], dependencies=[Depends(require_csrf_any)]
)

WRONG_CODE = N_("That code is not right. Check the time on your phone and try again.")


async def active_user(db: AsyncSession, session: AuthSession) -> User:
    user = await db.get(User, session.user_id)
    if user is None or user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=tr("Authentication required")
        )
    return user


def in_stage(session: AuthSession, *stages: str) -> None:
    if session.stage not in stages:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=tr("This step does not apply to your sign-in now"),
        )


async def finish_sign_in(
    db: AsyncSession,
    request: Request,
    response: Response,
    user: User,
    partial: AuthSession,
    method: str,
) -> AuthSession:
    """Replace a partly signed-in session with a full one (a new token, never the old one)."""
    partial.revoked_at = datetime.now(UTC)
    session = await open_session(db, request, response, user, "full")
    record_event(
        db,
        request,
        "auth.login_succeeded",
        tenant_id=session.active_tenant_id,
        actor=user,
        details={
            "session_id": str(session.id),
            "replaces_session_id": str(partial.id),
            "two_step": method,
        },
    )
    return session


@router.post("/verify", response_model=SessionResponse)
async def verify(
    payload: TwoStepCode,
    request: Request,
    response: Response,
    partial: AuthSession = Depends(get_any_session),
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Second step of signing in: an authenticator code or an unused backup code."""
    in_stage(partial, "verify")
    user = await active_user(db, partial)
    now = datetime.now(UTC)
    locked_until = aware(user.two_step_locked_until)
    minutes = get_settings().login_lockout_minutes
    if locked_until is not None and locked_until > now:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=tr("Too many wrong codes. Try again in {minutes} minutes.", minutes=minutes),
        )
    method = await two_step.check_code(db, user, payload.code)
    if method is None:
        user.two_step_failures += 1
        locked = user.two_step_failures >= two_step.WRONG_CODE_LIMIT
        if locked:
            user.two_step_failures = 0
            user.two_step_locked_until = now + timedelta(minutes=minutes)
            partial.revoked_at = now
        record_event(
            db,
            request,
            "auth.two_step_failed",
            tenant_id=None,
            actor=user,
            details={"session_id": str(partial.id), "locked": locked},
        ).actor_type = "anonymous"  # nobody has proved who they are yet
        await db.commit()
        if locked:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=tr("Too many wrong codes. Try again in {minutes} minutes.", minutes=minutes),
            )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=tr(WRONG_CODE))
    user.two_step_failures = 0
    user.two_step_locked_until = None
    session = await finish_sign_in(db, request, response, user, partial, method)
    if method == "backup_code":
        record_event(
            db,
            request,
            "auth.backup_code_used",
            tenant_id=session.active_tenant_id,
            actor=user,
            details={"codes_left": await two_step.backup_codes_left(db, user.id)},
        )
    await db.commit()
    return await build_session_response(db, user, session)


@router.post("/setup", response_model=TwoStepSetup)
async def setup(
    request: Request,
    session: AuthSession = Depends(get_any_session),
    db: AsyncSession = Depends(get_db),
) -> TwoStepSetup:
    """Start setting up an authenticator: a new secret to scan. Nothing changes until enable."""
    in_stage(session, "full", "enrol")
    user = await active_user(db, session)
    if user.totp_enabled_at is not None:
        raise HTTPException(status_code=409, detail=tr("Two-step sign-in is already on"))
    secret = totp.new_secret()
    user.totp_pending_secret = totp.encrypt_secret(secret, user.id)
    await db.commit()
    uri = totp.otpauth_uri(secret, user.email)
    return TwoStepSetup(secret=secret, otpauth_uri=uri, qr_svg=totp.qr_svg(uri))


@router.post("/enable", response_model=TwoStepEnabled)
async def enable(
    payload: TwoStepCode,
    request: Request,
    response: Response,
    session: AuthSession = Depends(get_any_session),
    db: AsyncSession = Depends(get_db),
) -> TwoStepEnabled:
    """Confirm the authenticator with a code from it; returns ten backup codes, shown once."""
    in_stage(session, "full", "enrol")
    user = await active_user(db, session)
    if user.totp_enabled_at is not None:
        raise HTTPException(status_code=409, detail=tr("Two-step sign-in is already on"))
    if user.totp_pending_secret is None:
        raise HTTPException(status_code=409, detail=tr("Start the set-up first"))
    secret = totp.decrypt_secret(user.totp_pending_secret, user.id)
    if not two_step.authenticator_ok(user, secret, payload.code):
        raise HTTPException(status_code=422, detail=tr(WRONG_CODE))
    user.totp_secret = user.totp_pending_secret
    user.totp_pending_secret = None
    user.totp_enabled_at = datetime.now(UTC)
    user.two_step_due_at = None
    codes = await two_step.issue_backup_codes(db, user)
    record_event(
        db,
        request,
        "auth.two_step_enabled",
        tenant_id=session.active_tenant_id,
        actor=user,
        details={"session_id": str(session.id)},
    )
    if session.stage == "enrol":
        session = await finish_sign_in(db, request, response, user, session, "enrolled")
    await db.commit()
    return TwoStepEnabled(
        backup_codes=codes, session=await build_session_response(db, user, session)
    )


@router.post("/backup-codes", response_model=BackupCodes)
async def replace_backup_codes(
    payload: TwoStepCode,
    request: Request,
    session: AuthSession = Depends(get_auth_session),
    db: AsyncSession = Depends(get_db),
) -> BackupCodes:
    """Ten new backup codes; the old ones stop working. Needs a code from the authenticator."""
    user = await active_user(db, session)
    if user.totp_secret is None:
        raise HTTPException(status_code=409, detail=tr("Two-step sign-in is not on"))
    secret = totp.decrypt_secret(user.totp_secret, user.id)
    if not two_step.authenticator_ok(user, secret, payload.code):
        raise HTTPException(status_code=422, detail=tr(WRONG_CODE))
    codes = await two_step.issue_backup_codes(db, user)
    record_event(
        db,
        request,
        "auth.backup_codes_replaced",
        tenant_id=session.active_tenant_id,
        actor=user,
        details={},
    )
    await db.commit()
    return BackupCodes(backup_codes=codes)


@router.post("/disable", response_model=SessionResponse)
async def disable(
    payload: TwoStepCode,
    request: Request,
    session: AuthSession = Depends(get_auth_session),
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Turn two-step sign-in off; not allowed for owners and administrators."""
    user = await active_user(db, session)
    if user.totp_secret is None:
        raise HTTPException(status_code=409, detail=tr("Two-step sign-in is not on"))
    if await two_step.is_required(db, user.id):
        raise HTTPException(
            status_code=409,
            detail=tr("Owners and administrators must keep two-step sign-in on"),
        )
    if await two_step.check_code(db, user, payload.code) is None:
        raise HTTPException(status_code=422, detail=tr(WRONG_CODE))
    await two_step.clear(db, user)
    record_event(
        db,
        request,
        "auth.two_step_disabled",
        tenant_id=session.active_tenant_id,
        actor=user,
        details={},
    )
    await db.commit()
    return await build_session_response(db, user, session)
