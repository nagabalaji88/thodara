"""Session responses, cookies and session start-up shared by sign-in and two-step sign-in."""

import uuid
from datetime import UTC, datetime

from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import new_opaque_token, session_expiry, token_digest
from app.models.identity import AuthSession, Tenant, TenantMembership, User
from app.schemas.auth import SessionResponse, SessionUser, TenantChoice
from app.services import two_step


async def memberships_for_user(
    db: AsyncSession, user_id: uuid.UUID
) -> list[tuple[TenantMembership, Tenant]]:
    result = await db.execute(
        select(TenantMembership, Tenant)
        .join(Tenant, Tenant.id == TenantMembership.tenant_id)
        .where(
            TenantMembership.user_id == user_id,
            TenantMembership.status == "active",
            Tenant.status == "active",
        )
        .order_by(Tenant.display_name)
    )
    return list(result.all())


async def build_session_response(
    db: AsyncSession, user: User, session: AuthSession
) -> SessionResponse:
    # Until two-step sign-in is finished, the session reveals no companies (ADR-0015).
    memberships = await memberships_for_user(db, user.id) if session.stage == "full" else []
    choices = [
        TenantChoice(tenant_id=tenant.id, tenant_name=tenant.display_name, role=membership.role)
        for membership, tenant in memberships
    ]
    active = next(
        (choice for choice in choices if choice.tenant_id == session.active_tenant_id),
        None,
    )
    return SessionResponse(
        user=SessionUser(
            id=user.id, email=user.email, display_name=user.display_name, language=user.language
        ),
        active_tenant=active,
        memberships=choices,
        expires_at=session.expires_at,
        two_step=await two_step.state_for(db, user, session),
    )


async def open_session(
    db: AsyncSession, request: Request, response: Response, user: User, stage: str
) -> AuthSession:
    """Create a session, set its cookies and return it (not yet committed)."""
    settings = get_settings()
    active_tenant_id = None
    if stage == "full":
        memberships = await memberships_for_user(db, user.id)
        active_tenant_id = memberships[0][0].tenant_id if len(memberships) == 1 else None
        expires_at = session_expiry(settings.session_ttl_hours)
    else:
        expires_at = datetime.now(UTC) + two_step.PARTIAL_SESSION
    raw_session = new_opaque_token()
    raw_csrf = new_opaque_token()
    auth_session = AuthSession(
        id=uuid.uuid4(),
        user_id=user.id,
        active_tenant_id=active_tenant_id,
        token_hash=token_digest(raw_session),
        csrf_hash=token_digest(raw_csrf),
        stage=stage,
        expires_at=expires_at,
        user_agent=(request.headers.get("user-agent") or "")[:255] or None,
        last_seen_at=datetime.now(UTC),
    )
    db.add(auth_session)
    set_auth_cookies(response, raw_session, raw_csrf, settings.session_ttl_hours)
    return auth_session


def set_auth_cookies(
    response: Response, session_token: str, csrf_token: str, ttl_hours: int
) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        max_age=ttl_hours * 3600,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        max_age=ttl_hours * 3600,
        httponly=False,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        settings.csrf_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=False,
        samesite="lax",
    )
