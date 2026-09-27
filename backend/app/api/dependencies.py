import uuid
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
from app.models.masterdata import MembershipSite

TENANT_WIDE_ROLES = frozenset({"owner", "administrator"})


@dataclass(frozen=True)
class AuthContext:
    session: AuthSession
    user: User
    tenant: Tenant
    membership: TenantMembership
    site: Site | None
    # None means every site in the tenant; otherwise the only sites this user may act on.
    site_ids: frozenset[uuid.UUID] | None = None

    def can_access_site(self, site_id: uuid.UUID) -> bool:
        return self.site_ids is None or site_id in self.site_ids

    @property
    def permissions(self) -> frozenset[str]:
        return ROLE_PERMISSIONS.get(self.membership.role, frozenset())


_BASE = frozenset({"workspace:read", "masterdata:read"})
_ADMIN = _BASE | {
    "tenant:configure",
    "users:manage",
    "sites:manage",
    "units:manage",
    "items:manage",
    "customers:manage",
    "suppliers:manage",
    "warehouses:manage",
}

# Default role templates (ADR-0003). Tenant-customisable roles are a later story.
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "owner": _ADMIN,
    "administrator": _ADMIN,
    "production_manager": _BASE | {"items:manage"},
    "production_coordinator": _BASE,
    "procurement": _BASE | {"suppliers:manage"},
    "stores": _BASE | {"warehouses:manage"},
    "quality": _BASE,
    "dispatch": _BASE,
    "finance": _BASE,
    "approver": _BASE,
    "read_only": _BASE,
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
    site_ids: frozenset[uuid.UUID] | None = None
    if membership.role not in TENANT_WIDE_ROLES and membership.site_scope != "all":
        rows = await db.scalars(
            select(MembershipSite.site_id).where(
                MembershipSite.tenant_id == tenant.id,
                MembershipSite.membership_id == membership.id,
            )
        )
        site_ids = frozenset(rows.all())
    return AuthContext(auth_session, user, tenant, membership, site, site_ids)


def require_permission(permission: str) -> Callable[..., AuthContext]:
    async def dependency(context: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if permission not in context.permissions:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
        return context

    return dependency
