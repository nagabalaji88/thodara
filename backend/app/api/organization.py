import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    TENANT_WIDE_ROLES,
    AuthContext,
    require_csrf,
    require_permission,
)
from app.api.masterdata import audit
from app.db.session import get_db
from app.models.identity import Site, TenantMembership, User
from app.models.masterdata import MembershipSite
from app.schemas.masterdata import MemberOut, SiteAccessUpdate, SiteCreate, SiteOut

router = APIRouter(prefix="/organization", tags=["organization"])


@router.get("/sites", response_model=list[SiteOut])
async def list_sites(
    context: AuthContext = Depends(require_permission("workspace:read")),
    db: AsyncSession = Depends(get_db),
):
    query = select(Site).where(Site.tenant_id == context.tenant.id)
    if context.site_ids is not None:
        query = query.where(Site.id.in_(context.site_ids))
    return (await db.scalars(query.order_by(Site.name))).all()


@router.post(
    "/sites", response_model=SiteOut, status_code=201, dependencies=[Depends(require_csrf)]
)
async def create_site(
    payload: SiteCreate,
    request: Request,
    context: AuthContext = Depends(require_permission("sites:manage")),
    db: AsyncSession = Depends(get_db),
):
    site = Site(
        tenant_id=context.tenant.id,
        name=payload.name,
        normalized_name=payload.name.casefold(),
        city=payload.city,
        time_zone=payload.time_zone,
    )
    db.add(site)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A site with this name already exists") from exc
    audit(
        db,
        context,
        request,
        "organization.site.created",
        {"site_id": str(site.id), "name": site.name, "time_zone": site.time_zone},
    )
    await db.commit()
    await db.refresh(site)
    return site


async def _site_ids_by_membership(
    db: AsyncSession, tenant_id: uuid.UUID
) -> dict[uuid.UUID, list[uuid.UUID]]:
    rows = await db.execute(
        select(MembershipSite.membership_id, MembershipSite.site_id).where(
            MembershipSite.tenant_id == tenant_id
        )
    )
    grouped: dict[uuid.UUID, list[uuid.UUID]] = {}
    for membership_id, site_id in rows:
        grouped.setdefault(membership_id, []).append(site_id)
    return grouped


def _member_out(
    membership: TenantMembership, user: User, site_ids: list[uuid.UUID]
) -> MemberOut:
    tenant_wide = membership.role in TENANT_WIDE_ROLES
    return MemberOut(
        membership_id=membership.id,
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=membership.role,
        status=membership.status,
        site_scope="all" if tenant_wide else membership.site_scope,
        site_ids=[] if tenant_wide or membership.site_scope == "all" else sorted(site_ids),
    )


@router.get("/members", response_model=list[MemberOut])
async def list_members(
    context: AuthContext = Depends(require_permission("users:manage")),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(TenantMembership, User)
        .join(User, User.id == TenantMembership.user_id)
        .where(TenantMembership.tenant_id == context.tenant.id)
        .order_by(User.display_name)
    )
    site_ids = await _site_ids_by_membership(db, context.tenant.id)
    return [_member_out(m, u, site_ids.get(m.id, [])) for m, u in rows]


@router.put(
    "/members/{membership_id}/site-access",
    response_model=MemberOut,
    dependencies=[Depends(require_csrf)],
)
async def update_site_access(
    membership_id: uuid.UUID,
    payload: SiteAccessUpdate,
    request: Request,
    context: AuthContext = Depends(require_permission("users:manage")),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(TenantMembership, User)
            .join(User, User.id == TenantMembership.user_id)
            .where(
                TenantMembership.tenant_id == context.tenant.id,
                TenantMembership.id == membership_id,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Member not found")
    membership, user = row
    if membership.role in TENANT_WIDE_ROLES:
        raise HTTPException(
            status_code=409, detail="Owners and administrators always have access to every site"
        )
    requested = set(payload.site_ids) if payload.site_scope == "selected" else set()
    if payload.site_scope == "all" and payload.site_ids:
        raise HTTPException(status_code=422, detail="Leave site_ids empty when granting all sites")
    if requested:
        found = set(
            (
                await db.scalars(
                    select(Site.id).where(
                        Site.tenant_id == context.tenant.id, Site.id.in_(requested)
                    )
                )
            ).all()
        )
        if found != requested:
            raise HTTPException(status_code=422, detail="One or more sites were not found")

    before_ids = (await _site_ids_by_membership(db, context.tenant.id)).get(membership.id, [])
    before = {"site_scope": membership.site_scope, "site_ids": sorted(map(str, before_ids))}
    await db.execute(
        delete(MembershipSite).where(
            MembershipSite.tenant_id == context.tenant.id,
            MembershipSite.membership_id == membership.id,
        )
    )
    membership.site_scope = payload.site_scope
    db.add_all(
        MembershipSite(tenant_id=context.tenant.id, membership_id=membership.id, site_id=site_id)
        for site_id in requested
    )
    after = {"site_scope": payload.site_scope, "site_ids": sorted(map(str, requested))}
    if before != after:
        audit(
            db,
            context,
            request,
            "organization.member.site_access_changed",
            {"membership_id": str(membership.id), "user_id": str(user.id),
             "before": before, "after": after},
        )
    await db.commit()
    return _member_out(membership, user, sorted(requested))
