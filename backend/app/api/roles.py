"""Company-customisable roles and members' roles (slice G3, ADR-0011).

Standard roles can be changed and reset; companies can add their own. The administrator role
is locked with every permission. No change may leave the company without anyone who can
manage roles, and only an administrator can appoint or remove administrators.
"""

import re
import uuid
from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, BeforeValidator, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    TENANT_WIDE_ROLES,
    AuthContext,
    get_auth_context,
    require_csrf,
    require_permission,
)
from app.api.masterdata import STALE, audit, commit_or_conflict
from app.db.session import get_db
from app.models.identity import TenantMembership, User
from app.models.roles import TenantRole
from app.schemas.masterdata import StrictModel
from app.services.roles import (
    ALL_PERMISSIONS,
    ALWAYS,
    LOCKED_ROLE,
    PERMISSION_CATALOGUE,
    ROLE_PERMISSIONS,
    STANDARD_ROLE_NAMES,
    company_roles,
)

router = APIRouter(prefix="/organization", tags=["roles"])
MANAGE_ROLES = require_permission("roles:manage")
MANAGE_USERS = require_permission("users:manage")
CSRF = [Depends(require_csrf)]

RoleName = Annotated[
    str,
    BeforeValidator(lambda v: " ".join(v.split()) if isinstance(v, str) else v),
    Field(min_length=2, max_length=60),
]
RoleDescription = Annotated[
    Annotated[str, Field(max_length=300)] | None,
    BeforeValidator(lambda v: (v.strip() or None) if isinstance(v, str) else v),
]


class PermissionOut(BaseModel):
    key: str
    group: str
    label: str


class RoleOut(BaseModel):
    key: str
    name: str
    description: str | None
    permissions: list[str]
    standard: bool
    changed: bool
    locked: bool
    members: int
    version: int | None


class RolesOut(BaseModel):
    catalogue: list[PermissionOut]
    roles: list[RoleOut]


class RoleIn(StrictModel):
    name: RoleName
    description: RoleDescription = None
    permissions: list[str] = Field(max_length=len(PERMISSION_CATALOGUE))


class RoleUpdate(RoleIn):
    # None when changing a standard role that still follows the default template.
    version: int | None = Field(default=None, ge=1)


class MemberRoleIn(StrictModel):
    role: str = Field(min_length=2, max_length=32)


class MemberRoleOut(BaseModel):
    membership_id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    role: str


async def read_roles_context(context: AuthContext = Depends(get_auth_context)) -> AuthContext:
    """People who manage roles or members both need the list of roles."""
    if not {"roles:manage", "users:manage"} & context.permissions:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
    return context


def checked_permissions(requested: list[str]) -> list[str]:
    unknown = sorted(set(requested) - ALL_PERMISSIONS)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown permission: {', '.join(unknown)}")
    return sorted(set(requested) | ALWAYS)


async def active_roles(db: AsyncSession, tenant_id: uuid.UUID) -> list[TenantMembership]:
    return list(
        await db.scalars(
            select(TenantMembership)
            .join(User, User.id == TenantMembership.user_id)
            .where(
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.status == "active",
                User.status == "active",
            )
        )
    )


async def keep_someone_managing_roles(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    roles: dict[str, frozenset[str]],
    member_roles: dict[uuid.UUID, str] | None = None,
) -> None:
    """Refuse a change after which no active member could manage roles."""
    members = await active_roles(db, tenant_id)
    for membership in members:
        role = (member_roles or {}).get(membership.id, membership.role)
        if "roles:manage" in roles.get(role, frozenset()):
            return
    raise HTTPException(
        status_code=409,
        detail="Nobody would be left who can manage roles. Keep the permission on a role an "
        "active member holds, or appoint an administrator first.",
    )


async def roles_out(db: AsyncSession, tenant_id: uuid.UUID) -> RolesOut:
    rows = {
        r.key: r
        for r in await db.scalars(select(TenantRole).where(TenantRole.tenant_id == tenant_id))
    }
    counts = Counter(m.role for m in await active_roles(db, tenant_id))
    roles = []
    for key, name in STANDARD_ROLE_NAMES.items():
        row = rows.get(key)
        permissions = (
            ALL_PERMISSIONS
            if key == LOCKED_ROLE
            else frozenset(row.permissions) | ALWAYS
            if row
            else ROLE_PERMISSIONS[key]
        )
        roles.append(
            RoleOut(
                key=key,
                name=row.name if row else name,
                description=row.description if row else None,
                permissions=sorted(permissions),
                standard=True,
                changed=row is not None,
                locked=key == LOCKED_ROLE,
                members=counts[key],
                version=row.version if row else None,
            )
        )
    for row in sorted(rows.values(), key=lambda r: r.name):
        if row.is_standard:
            continue
        roles.append(
            RoleOut(
                key=row.key,
                name=row.name,
                description=row.description,
                permissions=sorted(frozenset(row.permissions) | ALWAYS),
                standard=False,
                changed=False,
                locked=False,
                members=counts[row.key],
                version=row.version,
            )
        )
    return RolesOut(
        catalogue=[
            PermissionOut(key=key, group=group, label=label)
            for key, (group, label) in PERMISSION_CATALOGUE.items()
        ],
        roles=roles,
    )


@router.get("/roles", response_model=RolesOut)
async def list_roles(
    context: AuthContext = Depends(read_roles_context), db: AsyncSession = Depends(get_db)
):
    return await roles_out(db, context.tenant.id)


@router.post("/roles", response_model=RolesOut, status_code=201, dependencies=CSRF)
async def create_role(
    payload: RoleIn,
    request: Request,
    context: AuthContext = Depends(MANAGE_ROLES),
    db: AsyncSession = Depends(get_db),
):
    key = re.sub(r"[^a-z0-9]+", "_", payload.name.lower()).strip("_")[:32].strip("_")
    if len(key) < 2:
        raise HTTPException(status_code=422, detail="Use letters or numbers in the role name")
    existing = await company_roles(db, context.tenant.id)
    names = {r.name.lower() for r in (await roles_out(db, context.tenant.id)).roles}
    if key in existing or payload.name.lower() in names:
        raise HTTPException(status_code=409, detail="A role with this name already exists")
    permissions = checked_permissions(payload.permissions)
    db.add(
        TenantRole(
            id=uuid.uuid4(),
            tenant_id=context.tenant.id,
            key=key,
            name=payload.name,
            description=payload.description,
            permissions=permissions,
            is_standard=False,
            created_by=context.user.id,
            updated_by=context.user.id,
        )
    )
    audit(
        db,
        context,
        request,
        "roles.created",
        {"key": key, "name": payload.name, "permissions": permissions},
    )
    await commit_or_conflict(db, "A role with this name already exists")
    return await roles_out(db, context.tenant.id)


@router.put("/roles/{key}", response_model=RolesOut, dependencies=CSRF)
async def update_role(
    key: str,
    payload: RoleUpdate,
    request: Request,
    context: AuthContext = Depends(MANAGE_ROLES),
    db: AsyncSession = Depends(get_db),
):
    if key == LOCKED_ROLE:
        raise HTTPException(
            status_code=409, detail="The administrator role always has every permission"
        )
    row = await db.scalar(
        select(TenantRole).where(TenantRole.tenant_id == context.tenant.id, TenantRole.key == key)
    )
    standard = key in STANDARD_ROLE_NAMES
    if row is None and not standard:
        raise HTTPException(status_code=404, detail="Role not found")
    if (row.version if row else None) != payload.version:
        raise HTTPException(status_code=409, detail=STALE)
    permissions = checked_permissions(payload.permissions)
    roles = await company_roles(db, context.tenant.id)
    before = {
        "name": row.name if row else STANDARD_ROLE_NAMES[key],
        "description": row.description if row else None,
        "permissions": sorted(roles[key]),
    }
    await keep_someone_managing_roles(db, context.tenant.id, {**roles, key: frozenset(permissions)})
    if row is None:
        row = TenantRole(
            id=uuid.uuid4(),
            tenant_id=context.tenant.id,
            key=key,
            is_standard=True,
            created_by=context.user.id,
        )
        db.add(row)
    row.name = payload.name
    row.description = payload.description
    row.permissions = permissions
    row.updated_by = context.user.id
    after = {"name": payload.name, "description": payload.description, "permissions": permissions}
    audit(db, context, request, "roles.changed", {"key": key, "before": before, "after": after})
    await commit_or_conflict(db, STALE)
    return await roles_out(db, context.tenant.id)


@router.delete("/roles/{key}", response_model=RolesOut, dependencies=CSRF)
async def reset_or_delete_role(
    key: str,
    request: Request,
    version: int = Query(ge=1),
    context: AuthContext = Depends(MANAGE_ROLES),
    db: AsyncSession = Depends(get_db),
):
    """A changed standard role goes back to the template; a company's own role is deleted."""
    row = await db.scalar(
        select(TenantRole).where(TenantRole.tenant_id == context.tenant.id, TenantRole.key == key)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Role not found or not changed")
    if row.version != version:
        raise HTTPException(status_code=409, detail=STALE)
    roles = await company_roles(db, context.tenant.id)
    if row.is_standard:
        await keep_someone_managing_roles(
            db, context.tenant.id, {**roles, key: ROLE_PERMISSIONS[key]}
        )
        action = "roles.reset"
    else:
        holders = [m for m in await active_roles(db, context.tenant.id) if m.role == key]
        suspended = await db.scalar(
            select(TenantMembership.id).where(
                TenantMembership.tenant_id == context.tenant.id, TenantMembership.role == key
            )
        )
        if holders or suspended is not None:
            raise HTTPException(
                status_code=409, detail="Give its members another role before deleting it"
            )
        action = "roles.deleted"
    audit(
        db,
        context,
        request,
        action,
        {"key": key, "name": row.name, "permissions": sorted(roles[key])},
    )
    await db.delete(row)
    await commit_or_conflict(db, STALE)
    return await roles_out(db, context.tenant.id)


@router.put("/members/{membership_id}/role", response_model=MemberRoleOut, dependencies=CSRF)
async def change_member_role(
    membership_id: uuid.UUID,
    payload: MemberRoleIn,
    request: Request,
    context: AuthContext = Depends(MANAGE_USERS),
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
    if membership.user_id == context.user.id:
        raise HTTPException(status_code=403, detail="You cannot change your own role")
    roles = await company_roles(db, context.tenant.id)
    if payload.role not in roles:
        raise HTTPException(status_code=422, detail="Choose one of the company's roles")
    if payload.role == membership.role:
        return MemberRoleOut(
            membership_id=membership.id,
            user_id=user.id,
            display_name=user.display_name,
            role=membership.role,
        )
    if LOCKED_ROLE in (payload.role, membership.role) and context.membership.role != LOCKED_ROLE:
        has_admin = any(m.role == LOCKED_ROLE for m in await active_roles(db, context.tenant.id))
        # An owner may appoint the first administrator; after that only administrators decide.
        if has_admin or context.membership.role != "owner" or payload.role != LOCKED_ROLE:
            raise HTTPException(
                status_code=403, detail="Only an administrator can appoint or change administrators"
            )
    await keep_someone_managing_roles(db, context.tenant.id, roles, {membership.id: payload.role})
    before = membership.role
    membership.role = payload.role
    audit(
        db,
        context,
        request,
        "organization.member.role_changed",
        {
            "membership_id": str(membership.id),
            "user_id": str(user.id),
            "before": before,
            "after": payload.role,
            "site_scope": "all" if payload.role in TENANT_WIDE_ROLES else membership.site_scope,
        },
    )
    await commit_or_conflict(db, STALE)
    return MemberRoleOut(
        membership_id=membership.id,
        user_id=user.id,
        display_name=user.display_name,
        role=membership.role,
    )
