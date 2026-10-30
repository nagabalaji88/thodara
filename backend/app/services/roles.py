"""Roles and permissions (ADR-0003, ADR-0011).

The fixed map below is the default template. A company can change a standard role or add its
own; those are stored in tenant_roles and read on every request. The administrator role is
locked: it always holds every permission, so a company can never lock itself out.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.roles import TenantRole

_BASE = frozenset(
    {
        "workspace:read",
        "masterdata:read",
        "orders:read",
        "outsourcing:read",
        "actions:read",
        "stock:read",
    }
)
# Raising, assigning and closing recovery actions: everyone who runs operations.
_ACT = frozenset({"actions:manage"})
# Planning order dependencies, running outsourced batches and recording supplier updates.
_PLAN = frozenset({"orders:plan", "outsourcing:manage", "supplier_updates:record"})
_ADMIN = (
    _BASE
    | _PLAN
    | _ACT
    | {
        "actions:approve",
        "dispatch:manage",
        # Approve shipping beyond accepted material; never one's own request (ADR-0009).
        "dispatch:approve",
        # Stock entries; opening balances and adjustments need someone else's approval.
        "stock:record",
        "stock:approve",
        "orders:manage",
        "receipts:record",
        "quality:decide",
        "tenant:configure",
        "users:manage",
        # Change roles and their permissions (ADR-0011).
        "roles:manage",
        "sites:manage",
        "units:manage",
        "items:manage",
        "customers:manage",
        "suppliers:manage",
        "warehouses:manage",
    }
)

# Default role templates (ADR-0003). Companies can change them and add their own (ADR-0011).
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "owner": _ADMIN,
    "administrator": _ADMIN,
    "production_manager": _BASE | _PLAN | _ACT | {"items:manage"},
    "production_coordinator": _BASE | _ACT | {"supplier_updates:record"},
    "procurement": _BASE
    | _ACT
    | {"suppliers:manage", "outsourcing:manage", "supplier_updates:record"},
    "stores": _BASE
    | _ACT
    | {"warehouses:manage", "receipts:record", "dispatch:manage", "stock:record"},
    "quality": _BASE | _ACT | {"quality:decide"},
    "dispatch": _BASE | _ACT | {"dispatch:manage"},
    "finance": _BASE,
    # Approves consequential recovery actions; never their own (ADR-0007).
    "approver": _BASE | {"actions:approve", "dispatch:approve", "stock:approve"},
    "read_only": _BASE,
}


LOCKED_ROLE = "administrator"
# Always granted: without it no screen loads.
ALWAYS = frozenset({"workspace:read"})

STANDARD_ROLE_NAMES = {
    "owner": "Owner",
    "administrator": "Administrator",
    "production_manager": "Production manager",
    "production_coordinator": "Production coordinator",
    "procurement": "Procurement",
    "stores": "Stores",
    "quality": "Quality",
    "dispatch": "Dispatch",
    "finance": "Finance",
    "approver": "Approver",
    "read_only": "Read only",
}

# Every permission a role can hold, grouped and labelled for the roles screen.
PERMISSION_CATALOGUE: dict[str, tuple[str, str]] = {
    "workspace:read": ("See", "Open the workspace (always on)"),
    "masterdata:read": ("See", "See master data"),
    "orders:read": ("See", "See orders, delivery risk, dispatch and reports"),
    "outsourcing:read": ("See", "See outsourced batches"),
    "actions:read": ("See", "See recovery actions"),
    "stock:read": ("See", "See stock"),
    "orders:manage": ("Orders", "Create, confirm, amend and cancel orders"),
    "orders:plan": ("Orders", "Plan dependencies and batch priority"),
    "outsourcing:manage": ("Outsourcing", "Create, send, close and cancel batches"),
    "supplier_updates:record": ("Outsourcing", "Record supplier updates"),
    "receipts:record": ("Stores and quality", "Record receipts from suppliers"),
    "quality:decide": ("Stores and quality", "Inspect and release quality holds"),
    "stock:record": ("Stores and quality", "Record stock entries"),
    "stock:approve": ("Approvals", "Approve opening balances and stock adjustments"),
    "actions:manage": ("Actions", "Raise, assign and close recovery actions"),
    "actions:approve": ("Approvals", "Approve consequential recovery actions"),
    "dispatch:manage": ("Dispatch", "Record and cancel dispatches"),
    "dispatch:approve": ("Approvals", "Approve shipping beyond accepted material"),
    "items:manage": ("Master data", "Manage items"),
    "units:manage": ("Master data", "Manage units"),
    "customers:manage": ("Master data", "Manage customers"),
    "suppliers:manage": ("Master data", "Manage suppliers"),
    "warehouses:manage": ("Master data", "Manage warehouses"),
    "sites:manage": ("Company", "Manage sites and calendars"),
    "tenant:configure": ("Company", "Change company settings"),
    "users:manage": ("Company", "Manage members and their site access"),
    "roles:manage": ("Company", "Change roles and permissions"),
}
ALL_PERMISSIONS = frozenset(PERMISSION_CATALOGUE)


async def company_roles(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, frozenset[str]]:
    """Every role key the company can assign, with its permissions."""
    roles = dict(ROLE_PERMISSIONS)
    for row in await db.scalars(select(TenantRole).where(TenantRole.tenant_id == tenant_id)):
        roles[row.key] = frozenset(row.permissions) | ALWAYS
    roles[LOCKED_ROLE] = ALL_PERMISSIONS
    return roles


async def role_permissions(db: AsyncSession, tenant_id: uuid.UUID, key: str) -> frozenset[str]:
    if key == LOCKED_ROLE:
        return ALL_PERMISSIONS
    row = await db.scalar(
        select(TenantRole).where(TenantRole.tenant_id == tenant_id, TenantRole.key == key)
    )
    if row is not None:
        return frozenset(row.permissions) | ALWAYS
    return ROLE_PERMISSIONS.get(key, frozenset())


async def roles_with(db: AsyncSession, tenant_id: uuid.UUID, permission: str) -> set[str]:
    return {
        key for key, perms in (await company_roles(db, tenant_id)).items() if permission in perms
    }
