import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import imports, masterdata, orders, organization
from app.api.dependencies import (
    AuthContext,
    get_auth_session,
    require_csrf,
    require_permission,
)
from app.core.audit import record_event
from app.core.config import get_settings
from app.core.security import new_opaque_token, session_expiry, token_digest, verify_password
from app.db.session import get_db
from app.models.identity import AuthSession, Site, Tenant, TenantMembership, User
from app.schemas.auth import (
    LoginRequest,
    SelectTenantRequest,
    SessionInfo,
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
    if user is None or not password_ok or user.status != "active" or user.email_verified_at is None:
        locked_until = user.locked_until if user is not None else None
        if locked_until is not None and locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=UTC)
        is_locked = locked_until is not None and locked_until > now
        if user is not None and not is_locked:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.login_lockout_attempts:
                user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
                user.failed_login_count = 0
        failed = record_event(
            db,
            request,
            "auth.login_failed",
            tenant_id=None,
            actor=user,
            details={"reason": "invalid_or_unavailable_account"},
        )
        # The account is the subject, but nobody proved they own it.
        failed.actor_type = "anonymous"
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
        id=uuid.uuid4(),
        user_id=user.id,
        active_tenant_id=active_tenant_id,
        token_hash=token_digest(raw_session),
        csrf_hash=token_digest(raw_csrf),
        expires_at=session_expiry(settings.session_ttl_hours),
        user_agent=(request.headers.get("user-agent") or "")[:255] or None,
        last_seen_at=datetime.now(UTC),
    )
    db.add(auth_session)
    record_event(
        db,
        request,
        "auth.login_succeeded",
        tenant_id=active_tenant_id,
        actor=user,
        details={"membership_count": len(memberships), "session_id": str(auth_session.id)},
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
    request: Request,
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
    previous = auth_session.active_tenant_id
    auth_session.active_tenant_id = payload.tenant_id
    user = await db.get(User, auth_session.user_id)
    record_event(
        db,
        request,
        "auth.tenant_selected",
        tenant_id=payload.tenant_id,
        actor=user,
        details={
            "session_id": str(auth_session.id),
            "from_tenant_id": str(previous) if previous else None,
        },
    )
    await db.commit()
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
    record_event(
        db,
        request,
        "auth.logout",
        tenant_id=auth_session.active_tenant_id,
        actor=await db.get(User, auth_session.user_id),
        details={"session_id": str(auth_session.id)},
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
    query = select(Site).where(Site.tenant_id == context.tenant.id, Site.status == "active")
    if context.site_ids is not None:
        query = query.where(Site.id.in_(context.site_ids))
    sites_result = await db.execute(query.order_by(Site.name))
    return WorkspaceSummary(
        tenant_id=context.tenant.id,
        company_name=context.tenant.display_name,
        country_code=context.tenant.country_code,
        base_currency=context.tenant.base_currency,
        setup_complete=context.tenant.setup_complete,
        sites=[WorkspaceSite.model_validate(site) for site in sites_result.scalars()],
        module_state="not_configured",
        permissions=sorted(context.permissions),
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
    if context.site is None:
        raise HTTPException(
            status_code=409, detail="A site must be provisioned before setup can be completed"
        )
    before = _setup_snapshot(context.tenant, context.site)
    context.tenant.display_name = payload.company_name.strip()
    context.tenant.country_code = payload.country_code
    context.tenant.base_currency = payload.base_currency
    context.tenant.setup_complete = True
    context.site.name = payload.site_name.strip()
    context.site.normalized_name = payload.site_name.strip().casefold()
    context.site.city = payload.city.strip() if payload.city and payload.city.strip() else None
    context.site.time_zone = payload.time_zone
    record_event(
        db,
        request,
        "tenant.setup_completed",
        tenant_id=context.tenant.id,
        actor=context.user,
        details={
            "site_id": str(context.site.id),
            "before": before,
            "after": _setup_snapshot(context.tenant, context.site),
        },
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
        permissions=sorted(context.permissions),
    )


def _setup_snapshot(tenant: Tenant, site: Site) -> dict[str, str | None]:
    return {
        "company_name": tenant.display_name,
        "country_code": tenant.country_code,
        "base_currency": tenant.base_currency,
        "site_name": site.name,
        "city": site.city,
        "time_zone": site.time_zone,
    }


@auth_router.get("/sessions", response_model=list[SessionInfo])
async def list_sessions(
    auth_session: AuthSession = Depends(get_auth_session),
    db: AsyncSession = Depends(get_db),
) -> list[SessionInfo]:
    rows = await db.scalars(
        select(AuthSession)
        .where(
            AuthSession.user_id == auth_session.user_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(UTC),
        )
        .order_by(AuthSession.created_at.desc())
    )
    return [
        SessionInfo(
            id=row.id,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            expires_at=row.expires_at,
            user_agent=row.user_agent,
            current=row.id == auth_session.id,
        )
        for row in rows
    ]


@auth_router.post(
    "/sessions/{session_id}/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def revoke_session(
    session_id: uuid.UUID,
    request: Request,
    auth_session: AuthSession = Depends(get_auth_session),
    db: AsyncSession = Depends(get_db),
) -> Response:
    target = await db.scalar(
        select(AuthSession).where(
            AuthSession.id == session_id,
            AuthSession.user_id == auth_session.user_id,
            AuthSession.revoked_at.is_(None),
        )
    )
    if target is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if target.id == auth_session.id:
        raise HTTPException(status_code=409, detail="Use sign out to end this session")
    target.revoked_at = datetime.now(UTC)
    record_event(
        db,
        request,
        "auth.session_revoked",
        tenant_id=auth_session.active_tenant_id,
        actor=await db.get(User, auth_session.user_id),
        details={"session_id": str(target.id)},
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@auth_router.post("/sessions/revoke-others", dependencies=[Depends(require_csrf)])
async def revoke_other_sessions(
    request: Request,
    auth_session: AuthSession = Depends(get_auth_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    others = (
        await db.scalars(
            select(AuthSession).where(
                AuthSession.user_id == auth_session.user_id,
                AuthSession.id != auth_session.id,
                AuthSession.revoked_at.is_(None),
            )
        )
    ).all()
    now = datetime.now(UTC)
    for other in others:
        other.revoked_at = now
    record_event(
        db,
        request,
        "auth.other_sessions_revoked",
        tenant_id=auth_session.active_tenant_id,
        actor=await db.get(User, auth_session.user_id),
        details={"count": len(others), "session_ids": [str(o.id) for o in others][:100]},
    )
    await db.commit()
    return {"revoked": len(others)}


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
api_router.include_router(masterdata.router)
api_router.include_router(imports.router)
api_router.include_router(organization.router)
api_router.include_router(orders.router)
