from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import constant_time_token_match, token_digest
from app.db.session import get_db
from app.models.identity import AuthSession, Site, Tenant, TenantMembership, User


@dataclass(frozen=True)
class AuthContext:
    session: AuthSession
    user: User
    tenant: Tenant
    membership: TenantMembership
    site: Site | None


ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "owner": frozenset({"workspace:read", "tenant:configure", "users:manage"}),
    "administrator": frozenset({"workspace:read", "tenant:configure", "users:manage"}),
    "production_manager": frozenset({"workspace:read"}),
    "production_coordinator": frozenset({"workspace:read"}),
    "procurement": frozenset({"workspace:read"}),
    "stores": frozenset({"workspace:read"}),
    "quality": frozenset({"workspace:read"}),
    "dispatch": frozenset({"workspace:read"}),
    "finance": frozenset({"workspace:read"}),
    "approver": frozenset({"workspace:read"}),
    "read_only": frozenset({"workspace:read"}),
}


async def get_auth_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AuthSession:
    raw_token = request.cookies.get(get_settings().session_cookie_name)
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    result = await db.execute(
        select(AuthSession).where(AuthSession.token_hash == token_digest(raw_token))
    )
    session = result.scalar_one_or_none()
    now = datetime.now(UTC)
    expires_at = session.expires_at if session is not None else None
    if expires_at is not None and expires_at.tzinfo is None:
        # SQLite-based tests return naive timestamps even for timezone-aware columns.
        expires_at = expires_at.replace(tzinfo=UTC)
    if session is None or session.revoked_at is not None or expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    return session


async def require_csrf(
    request: Request,
    auth_session: AuthSession = Depends(get_auth_session),
) -> None:
    settings = get_settings()
    cookie_token = request.cookies.get(settings.csrf_cookie_name, "")
    header_token = request.headers.get("X-CSRF-Token", "")
    if (
        not cookie_token
        or not header_token
        or not constant_time_token_match(cookie_token, auth_session.csrf_hash)
        or not constant_time_token_match(header_token, auth_session.csrf_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Request validation failed"
        )


async def get_auth_context(
    auth_session: AuthSession = Depends(get_auth_session),
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    if auth_session.active_tenant_id is None:
        raise HTTPException(status_code=409, detail="Select a workspace before continuing")
    membership_result = await db.execute(
        select(TenantMembership).where(
            TenantMembership.tenant_id == auth_session.active_tenant_id,
            TenantMembership.user_id == auth_session.user_id,
            TenantMembership.status == "active",
        )
    )
    membership = membership_result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace access denied")
    user = await db.get(User, auth_session.user_id)
    tenant = await db.get(Tenant, auth_session.active_tenant_id)
    site = await db.get(Site, membership.home_site_id) if membership.home_site_id else None
    if user is None or user.status != "active" or tenant is None or tenant.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace access denied")
    return AuthContext(auth_session, user, tenant, membership, site)


def require_permission(permission: str) -> Callable[..., AuthContext]:
    async def dependency(context: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if permission not in ROLE_PERMISSIONS.get(context.membership.role, frozenset()):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
        return context

    return dependency
