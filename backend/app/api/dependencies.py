import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.i18n import tr
from app.core.security import constant_time_token_match, token_digest
from app.db.session import get_db
from app.models.identity import AuthSession, Site, Tenant, TenantMembership, User
from app.models.masterdata import MembershipSite
from app.models.organization import FulfillmentSettings
from app.services.roles import ROLE_PERMISSIONS, role_permissions  # noqa: F401

TENANT_WIDE_ROLES = frozenset({"owner", "administrator"})
LAST_SEEN_INTERVAL = timedelta(minutes=5)


@dataclass(frozen=True)
class AuthContext:
    session: AuthSession
    user: User
    tenant: Tenant
    membership: TenantMembership
    site: Site | None
    # None means every site in the tenant; otherwise the only sites this user may act on.
    site_ids: frozenset[uuid.UUID] | None = None
    # Read from the company's roles on each request (ADR-0011).
    permissions: frozenset[str] = frozenset()
    # Whether the company lets people approve what they entered themselves (ADR-0011).
    allow_self_approval: bool = False

    def can_access_site(self, site_id: uuid.UUID) -> bool:
        return self.site_ids is None or site_id in self.site_ids

    def blocks_self(self, creator_id: uuid.UUID | None) -> bool:
        """True when this user made the thing and may not decide on it themselves."""
        return creator_id == self.user.id and not self.allow_self_approval


async def get_auth_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AuthSession:
    raw_token = request.cookies.get(get_settings().session_cookie_name)
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=tr("Authentication required")
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
            status_code=status.HTTP_401_UNAUTHORIZED, detail=tr("Authentication required")
        )
    last_seen = session.last_seen_at
    if last_seen is not None and last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    if last_seen is None or now - last_seen > LAST_SEEN_INTERVAL:
        session.last_seen_at = now
        await db.commit()
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
            status_code=status.HTTP_403_FORBIDDEN, detail=tr("Request validation failed")
        )


async def get_auth_context(
    auth_session: AuthSession = Depends(get_auth_session),
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    if auth_session.active_tenant_id is None:
        raise HTTPException(status_code=409, detail=tr("Select a workspace before continuing"))
    membership_result = await db.execute(
        select(TenantMembership).where(
            TenantMembership.tenant_id == auth_session.active_tenant_id,
            TenantMembership.user_id == auth_session.user_id,
            TenantMembership.status == "active",
        )
    )
    membership = membership_result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=tr("Workspace access denied")
        )
    user = await db.get(User, auth_session.user_id)
    tenant = await db.get(Tenant, auth_session.active_tenant_id)
    site = await db.get(Site, membership.home_site_id) if membership.home_site_id else None
    if user is None or user.status != "active" or tenant is None or tenant.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=tr("Workspace access denied")
        )
    site_ids: frozenset[uuid.UUID] | None = None
    if membership.role not in TENANT_WIDE_ROLES and membership.site_scope != "all":
        rows = await db.scalars(
            select(MembershipSite.site_id).where(
                MembershipSite.tenant_id == tenant.id,
                MembershipSite.membership_id == membership.id,
            )
        )
        site_ids = frozenset(rows.all())
    allow_self = await db.scalar(
        select(FulfillmentSettings.allow_self_approval).where(
            FulfillmentSettings.tenant_id == tenant.id
        )
    )
    return AuthContext(
        auth_session,
        user,
        tenant,
        membership,
        site,
        site_ids,
        permissions=await role_permissions(db, tenant.id, membership.role),
        allow_self_approval=bool(allow_self),
    )


def require_permission(permission: str) -> Callable[..., AuthContext]:
    async def dependency(context: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if permission not in context.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=tr("Permission denied")
            )
        return context

    return dependency
