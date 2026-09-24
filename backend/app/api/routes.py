import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    AuthContext,
    get_auth_session,
    require_csrf,
    require_permission,
)
from app.core.config import get_settings
from app.core.security import new_opaque_token, session_expiry, token_digest, verify_password
from app.db.session import get_db
from app.models.identity import AuditEvent, AuthSession, Site, Tenant, TenantMembership, User
from app.schemas.auth import (
    LoginRequest,
    SelectTenantRequest,
    SessionResponse,
    SessionUser,
    TenantChoice,
    WorkspaceSetupRequest,
    WorkspaceSite,
    WorkspaceSummary,
)

api_router = APIRouter(prefix="/api/v1")
health_router = APIRouter(tags=["health"])
auth_router = APIRouter(prefix="/auth", tags=["authentication"])
workspace_router = APIRouter(prefix="/workspace", tags=["workspace"])
onboarding_router = APIRouter(prefix="/onboarding", tags=["onboarding"])
settings = get_settings()


def session_response(
    user: User,
    session: AuthSession,
    memberships: list[tuple[TenantMembership, Tenant]],
) -> SessionResponse:
    choices = [
        TenantChoice(tenant_id=tenant.id, tenant_name=tenant.display_name, role=membership.role)
        for membership, tenant in memberships
    ]
    active = next(
        (choice for choice in choices if choice.tenant_id == session.active_tenant_id),
        None,
    )
    return SessionResponse(
        user=SessionUser(id=user.id, email=user.email, display_name=user.display_name),
        active_tenant=active,
        memberships=choices,
        expires_at=session.expires_at,
    )


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


@health_router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "alive"}


@health_router.get("/health/ready")
async def ready(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    from sqlalchemy import text

    await db.execute(text("SELECT 1"))
    return {"status": "ready"}


@auth_router.post("/login", response_model=SessionResponse)
async def login(
    payload: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> SessionResponse:
    email = str(payload.email).strip()
    normalized_email = email.casefold()
    result = await db.execute(
        select(User).where(User.email_normalized == normalized_email).with_for_update()
    )
    user = result.scalar_one_or_none()
    password_ok = verify_password(payload.password, user.password_hash if user else None)
    now = datetime.now(UTC)
    if (
        user is None
        or not password_ok
        or user.status != "active"
        or user.email_verified_at is None
        or (user.locked_until is not None and user.locked_until > now)
    ):
        locked_until = user.locked_until if user is not None else None
        if locked_until is not None and locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=UTC)
        is_locked = locked_until is not None and locked_until > now
        if user is not None and not is_locked:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.login_lockout_attempts:
                user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
                user.failed_login_count = 0
        db.add(
            AuditEvent(
                tenant_id=None,
                actor_user_id=user.id if user else None,
                action="auth.login_failed",
                request_id=request.state.request_id,
                details={"reason": "invalid_or_unavailable_account"},
            )
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Email or password is incorrect"
        )

    user.failed_login_count = 0
    user.locked_until = None
    memberships = await memberships_for_user(db, user.id)
    active_tenant_id = memberships[0][0].tenant_id if len(memberships) == 1 else None
    raw_session = new_opaque_token()
    raw_csrf = new_opaque_token()
    auth_session = AuthSession(
        user_id=user.id,
        active_tenant_id=active_tenant_id,
        token_hash=token_digest(raw_session),
        csrf_hash=token_digest(raw_csrf),
        expires_at=session_expiry(settings.session_ttl_hours),
    )
    db.add(auth_session)
    db.add(
        AuditEvent(
            tenant_id=active_tenant_id,
            actor_user_id=user.id,
            action="auth.login_succeeded",
            request_id=request.state.request_id,
            details={"membership_count": len(memberships)},
        )
    )
    await db.commit()
    _set_auth_cookies(response, raw_session, raw_csrf, settings.session_ttl_hours)
    return session_response(user, auth_session, memberships)


@auth_router.get("/session", response_model=SessionResponse)
async def current_session(
    auth_session: AuthSession = Depends(get_auth_session),
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    user = await db.get(User, auth_session.user_id)
    if user is None or user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    memberships = await memberships_for_user(db, user.id)
    return session_response(user, auth_session, memberships)


@auth_router.post(
    "/select-tenant", response_model=SessionResponse, dependencies=[Depends(require_csrf)]
)
async def select_tenant(
    payload: SelectTenantRequest,
    auth_session: AuthSession = Depends(get_auth_session),
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    result = await db.execute(
        select(TenantMembership, Tenant)
        .join(Tenant, Tenant.id == TenantMembership.tenant_id)
        .where(
            TenantMembership.user_id == auth_session.user_id,
            TenantMembership.tenant_id == payload.tenant_id,
            TenantMembership.status == "active",
            Tenant.status == "active",
        )
    )
    if result.first() is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace access denied")
    auth_session.active_tenant_id = payload.tenant_id
    await db.commit()
    user = await db.get(User, auth_session.user_id)
    memberships = await memberships_for_user(db, auth_session.user_id)
    return session_response(user, auth_session, memberships)


@auth_router.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)]
)
async def logout(
    request: Request,
    response: Response,
    auth_session: AuthSession = Depends(get_auth_session),
    db: AsyncSession = Depends(get_db),
) -> Response:
    auth_session.revoked_at = datetime.now(UTC)
    db.add(
        AuditEvent(
            tenant_id=auth_session.active_tenant_id,
            actor_user_id=auth_session.user_id,
            action="auth.logout",
            request_id=request.state.request_id,
            details={},
        )
    )
    await db.commit()
    _clear_auth_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@workspace_router.get("/dashboard", response_model=WorkspaceSummary)
async def dashboard(
    context: AuthContext = Depends(require_permission("workspace:read")),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceSummary:
    sites_result = await db.execute(
        select(Site)
        .where(Site.tenant_id == context.tenant.id, Site.status == "active")
        .order_by(Site.name)
    )
    return WorkspaceSummary(
        tenant_id=context.tenant.id,
        company_name=context.tenant.display_name,
        country_code=context.tenant.country_code,
        base_currency=context.tenant.base_currency,
        setup_complete=context.tenant.setup_complete,
        sites=[WorkspaceSite.model_validate(site) for site in sites_result.scalars()],
        module_state="not_configured",
    )


@onboarding_router.put(
    "/workspace", response_model=WorkspaceSummary, dependencies=[Depends(require_csrf)]
)
async def complete_workspace_setup(
    payload: WorkspaceSetupRequest,
    request: Request,
    context: AuthContext = Depends(require_permission("tenant:configure")),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceSummary:
    context.tenant.display_name = payload.company_name.strip()
    context.tenant.country_code = payload.country_code
    context.tenant.base_currency = payload.base_currency
    context.tenant.setup_complete = True
    if context.site is None:
        raise HTTPException(
            status_code=409, detail="A site must be provisioned before setup can be completed"
        )
    context.site.name = payload.site_name.strip()
    context.site.normalized_name = payload.site_name.strip().casefold()
    context.site.city = payload.city.strip() if payload.city and payload.city.strip() else None
    context.site.time_zone = payload.time_zone
    db.add(
        AuditEvent(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            action="tenant.setup_completed",
            request_id=request.state.request_id,
            details={"site_id": str(context.site.id)},
        )
    )
    await db.commit()
    await db.refresh(context.tenant)
    await db.refresh(context.site)
    return WorkspaceSummary(
        tenant_id=context.tenant.id,
        company_name=context.tenant.display_name,
        country_code=context.tenant.country_code,
        base_currency=context.tenant.base_currency,
        setup_complete=context.tenant.setup_complete,
        sites=[WorkspaceSite.model_validate(context.site)],
    )


def _set_auth_cookies(
    response: Response, session_token: str, csrf_token: str, ttl_hours: int
) -> None:
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


def _clear_auth_cookies(response: Response) -> None:
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


api_router.include_router(auth_router)
api_router.include_router(workspace_router)
api_router.include_router(onboarding_router)
