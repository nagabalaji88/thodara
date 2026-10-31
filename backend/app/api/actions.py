"""Daily recovery actions with owners, due times and approvals (slice F7)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    TENANT_WIDE_ROLES,
    AuthContext,
    require_csrf,
    require_permission,
)
from app.api.masterdata import STALE, audit, commit_or_conflict
from app.api.orders import require_version
from app.core.audit import actor_label
from app.core.i18n import N_, tr
from app.db.session import get_db
from app.models import MembershipSite, TenantMembership, User
from app.models.actions import APPROVAL_KINDS, ActionEvent, RecoveryAction
from app.models.masterdata import Customer, Item, Supplier
from app.models.orders import OrderLineComponent, SalesOrder, SalesOrderLine
from app.models.outsourcing import BatchAllocation, OutsourcedBatch
from app.schemas.actions import (
    ActionCreate,
    ActionOut,
    ActionPage,
    ApproveIn,
    Assignee,
    CancelIn,
    CompleteIn,
    EventOut,
    ReassignIn,
    RejectIn,
    SubjectBatch,
    SubjectLine,
    SupplierAckIn,
)
from app.services.risk_loader import assess_lines
from app.services.roles import role_permissions, roles_with

router = APIRouter(prefix="/actions", tags=["recovery actions"])
READ = require_permission("actions:read")
MANAGE = require_permission("actions:manage")
APPROVE = require_permission("actions:approve")
CSRF = [Depends(require_csrf)]
ACTIVE = ("awaiting_approval", "open")
MAX_AHEAD = timedelta(days=366)


def now() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


# Loading ------------------------------------------------------------------------


async def get_action(db: AsyncSession, context: AuthContext, action_id: uuid.UUID):
    action = await db.scalar(
        select(RecoveryAction).where(
            RecoveryAction.tenant_id == context.tenant.id, RecoveryAction.id == action_id
        )
    )
    if action is None or not context.can_access_site(action.site_id):
        raise HTTPException(status_code=404, detail=tr("Action not found"))
    return action


async def subjects(db: AsyncSession, actions: list[RecoveryAction]):
    line_ids = {a.line_id for a in actions if a.line_id}
    batch_ids = {a.batch_id for a in actions if a.batch_id}
    lines: dict[uuid.UUID, SubjectLine] = {}
    if line_ids:
        for line, order, customer, item in await db.execute(
            select(SalesOrderLine, SalesOrder, Customer.name, Item.code)
            .join(SalesOrder, SalesOrder.id == SalesOrderLine.order_id)
            .join(Customer, Customer.id == SalesOrder.customer_id)
            .join(Item, Item.id == SalesOrderLine.item_id)
            .where(SalesOrderLine.id.in_(line_ids))
        ):
            lines[line.id] = SubjectLine(
                line_id=line.id,
                order_id=order.id,
                order_number=order.number,
                line_no=line.line_no,
                customer_name=customer,
                item_code=item,
            )
    batches: dict[uuid.UUID, SubjectBatch] = {}
    if batch_ids:
        for batch, supplier in await db.execute(
            select(OutsourcedBatch, Supplier.name)
            .join(Supplier, Supplier.id == OutsourcedBatch.supplier_id)
            .where(OutsourcedBatch.id.in_(batch_ids))
        ):
            batches[batch.id] = SubjectBatch(
                batch_id=batch.id, number=batch.number, supplier_name=supplier
            )
    return lines, batches


def self_approved(context: AuthContext, action: RecoveryAction) -> dict | None:
    """Marks a decision someone made on their own proposal (allowed by company setting)."""
    return {"self_approved": True} if action.created_by == context.user.id else None


def can_approve(context: AuthContext, action: RecoveryAction) -> bool:
    return (
        action.status == "awaiting_approval"
        and "actions:approve" in context.permissions
        and not context.blocks_self(action.created_by)
    )


async def outs(
    db: AsyncSession, context: AuthContext, actions: list[RecoveryAction], events: bool = False
) -> list[ActionOut]:
    lines, batches = await subjects(db, actions)
    history: dict[uuid.UUID, list[EventOut]] = {a.id: [] for a in actions}
    if events and actions:
        for event in await db.scalars(
            select(ActionEvent)
            .where(ActionEvent.action_id.in_(history))
            .order_by(ActionEvent.created_at, ActionEvent.id)
        ):
            history[event.action_id].append(
                EventOut(
                    kind=event.kind,
                    note=event.note,
                    details=event.details,
                    actor_label=event.actor_label,
                    created_at=event.created_at,
                )
            )
    moment = now()
    return [
        ActionOut(
            id=a.id,
            kind=a.kind,
            title=a.title,
            details=a.details,
            status=a.status,
            requires_approval=a.kind in APPROVAL_KINDS,
            site_id=a.site_id,
            line=lines.get(a.line_id) if a.line_id else None,
            batch=batches.get(a.batch_id) if a.batch_id else None,
            owner_id=a.owner_id,
            owner_label=a.owner_label,
            due_at=a.due_at,
            overdue=a.status in ACTIVE and as_utc(a.due_at) < moment,
            created_by_label=a.created_by_label,
            created_at=a.created_at,
            approved_at=a.approved_at,
            acknowledged_at=a.acknowledged_at,
            supplier_acknowledged_at=a.supplier_acknowledged_at,
            outcome=a.outcome,
            outcome_note=a.outcome_note,
            closed_at=a.closed_at,
            risk_before=a.risk_before,
            risk_after=a.risk_after,
            version=a.version,
            is_mine=a.owner_id == context.user.id,
            can_approve=can_approve(context, a),
            events=history[a.id],
        )
        for a in actions
    ]


async def one_out(db: AsyncSession, context: AuthContext, action: RecoveryAction) -> ActionOut:
    return (await outs(db, context, [action], events=True))[0]


def record(
    db: AsyncSession,
    context: AuthContext,
    action: RecoveryAction,
    kind: str,
    note: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        ActionEvent(
            id=uuid.uuid4(),
            tenant_id=action.tenant_id,
            action_id=action.id,
            kind=kind,
            note=note,
            details=details,
            actor_id=context.user.id,
            actor_label=actor_label(context.user),
            created_at=now(),
        )
    )


async def line_risk(db: AsyncSession, context: AuthContext, line_id: uuid.UUID | None):
    """A small, stored summary of the line's current risk, for before/after follow-up."""
    if line_id is None:
        return None
    order_id = await db.scalar(select(SalesOrderLine.order_id).where(SalesOrderLine.id == line_id))
    moment = now()
    for risk in await assess_lines(db, context.tenant.id, None, order_id, moment):
        if risk.line_id == line_id:
            return {
                "headline": risk.headline,
                "projected_date": risk.projected_date.isoformat() if risk.projected_date else None,
                "promised_date": risk.promised_date.isoformat() if risk.promised_date else None,
                "issues": [i.message for i in risk.issues[:3]],
                "computed_at": moment.isoformat(),
            }
    return {"headline": "closed", "computed_at": moment.isoformat()}


async def member_for(
    db: AsyncSession, context: AuthContext, user_id: uuid.UUID, site_id: uuid.UUID
) -> User:
    """The proposed owner must be an active member who can work on actions at this site."""
    row = (
        await db.execute(
            select(TenantMembership, User)
            .join(User, User.id == TenantMembership.user_id)
            .where(
                TenantMembership.tenant_id == context.tenant.id,
                TenantMembership.user_id == user_id,
                TenantMembership.status == "active",
                User.status == "active",
            )
        )
    ).first()
    if row is None or "actions:manage" not in await role_permissions(
        db, context.tenant.id, row[0].role
    ):
        raise HTTPException(
            status_code=422, detail=tr("Choose an active colleague who can own actions")
        )
    membership, user = row
    if membership.role not in TENANT_WIDE_ROLES and membership.site_scope != "all":
        granted = await db.scalar(
            select(MembershipSite.id).where(
                MembershipSite.membership_id == membership.id, MembershipSite.site_id == site_id
            )
        )
        if granted is None:
            raise HTTPException(
                status_code=422,
                detail=tr(
                    "{user_display_name} has no access to this site",
                    user_display_name=user.display_name,
                ),
            )
    return user


def check_due(due_at: datetime) -> datetime:
    due = due_at.astimezone(UTC)
    if due <= now():
        raise HTTPException(status_code=422, detail=tr("The due time must be in the future"))
    if due > now() + MAX_AHEAD:
        raise HTTPException(status_code=422, detail=tr("Set a due time within a year"))
    return due


# Endpoints ------------------------------------------------------------------------


@router.get("", response_model=ActionPage)
async def list_actions(
    status: str | None = Query(default=None, pattern="^(active|awaiting_approval|open|closed)$"),
    mine: bool = False,
    overdue: bool = False,
    order_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    context: AuthContext = Depends(READ),
    db: AsyncSession = Depends(get_db),
):
    base = select(RecoveryAction).where(RecoveryAction.tenant_id == context.tenant.id)
    if context.site_ids is not None:
        base = base.where(RecoveryAction.site_id.in_(context.site_ids))
    counts = {
        "open": 0,
        "awaiting_approval": 0,
        "overdue": 0,
        "mine": 0,
        "to_approve": 0,
    }
    for action in await db.scalars(base.where(RecoveryAction.status.in_(ACTIVE))):
        counts[action.status] += 1
        counts["overdue"] += as_utc(action.due_at) < now()
        counts["mine"] += action.owner_id == context.user.id
        counts["to_approve"] += can_approve(context, action)
    query = base
    if status == "active":
        query = query.where(RecoveryAction.status.in_(ACTIVE))
    elif status == "closed":
        query = query.where(RecoveryAction.status.not_in(ACTIVE))
    elif status:
        query = query.where(RecoveryAction.status == status)
    if mine:
        query = query.where(RecoveryAction.owner_id == context.user.id)
    if overdue:
        query = query.where(RecoveryAction.status.in_(ACTIVE), RecoveryAction.due_at < now())
    if order_id:
        query = query.where(
            RecoveryAction.line_id.in_(
                select(SalesOrderLine.id).where(SalesOrderLine.order_id == order_id)
            )
        )
    if batch_id:
        query = query.where(RecoveryAction.batch_id == batch_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(
        await db.scalars(
            query.order_by(RecoveryAction.status.not_in(ACTIVE), RecoveryAction.due_at).limit(limit)
        )
    )
    return ActionPage(items=await outs(db, context, rows), total=total, counts=counts)


@router.get("/assignees", response_model=list[Assignee])
async def assignees(
    site_id: uuid.UUID,
    context: AuthContext = Depends(READ),
    db: AsyncSession = Depends(get_db),
):
    """Colleagues who can own an action at this site."""
    if not context.can_access_site(site_id):
        return []
    granted = select(MembershipSite.membership_id).where(MembershipSite.site_id == site_id)
    rows = await db.execute(
        select(TenantMembership, User)
        .join(User, User.id == TenantMembership.user_id)
        .where(
            TenantMembership.tenant_id == context.tenant.id,
            TenantMembership.status == "active",
            User.status == "active",
            or_(
                TenantMembership.role.in_(TENANT_WIDE_ROLES),
                TenantMembership.site_scope == "all",
                TenantMembership.id.in_(granted),
            ),
        )
        .order_by(User.display_name)
    )
    owners = await roles_with(db, context.tenant.id, "actions:manage")
    return [
        Assignee(user_id=user.id, display_name=user.display_name, role=membership.role)
        for membership, user in rows
        if membership.role in owners
    ]


@router.post("", response_model=ActionOut, status_code=201, dependencies=CSRF)
async def create_action(
    payload: ActionCreate,
    request: Request,
    response: Response,
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    replay = await db.scalar(
        select(RecoveryAction).where(
            RecoveryAction.tenant_id == context.tenant.id,
            RecoveryAction.submission_key == payload.submission_key,
        )
    )
    if replay is not None:
        response.status_code = 200
        return await one_out(db, context, await get_action(db, context, replay.id))
    if payload.line_id is None and payload.batch_id is None:
        raise HTTPException(
            status_code=422, detail=tr("Link the action to an order line or a batch")
        )
    site_id = None
    if payload.line_id is not None:
        row = (
            await db.execute(
                select(SalesOrderLine, SalesOrder)
                .join(SalesOrder, SalesOrder.id == SalesOrderLine.order_id)
                .where(
                    SalesOrderLine.tenant_id == context.tenant.id,
                    SalesOrderLine.id == payload.line_id,
                )
            )
        ).first()
        if row is None or not context.can_access_site(row[1].site_id):
            raise HTTPException(status_code=422, detail=tr("Choose an order line you can access"))
        line, order = row
        if order.status != "confirmed" or line.status != "open":
            raise HTTPException(
                status_code=409, detail=tr("Actions are for open lines of confirmed orders")
            )
        site_id = order.site_id
    if payload.batch_id is not None:
        batch = await db.scalar(
            select(OutsourcedBatch).where(
                OutsourcedBatch.tenant_id == context.tenant.id,
                OutsourcedBatch.id == payload.batch_id,
            )
        )
        if batch is None or not context.can_access_site(batch.site_id):
            raise HTTPException(status_code=422, detail=tr("Choose a batch you can access"))
        if batch.status not in ("planned", "at_supplier"):
            raise HTTPException(
                status_code=409,
                detail=tr(
                    "Batch {batch_number} is {batch_status}",
                    batch_number=batch.number,
                    batch_status=batch.status,
                ),
            )
        if payload.line_id is not None:
            linked = await db.scalar(
                select(BatchAllocation.id)
                .join(OrderLineComponent, OrderLineComponent.id == BatchAllocation.component_id)
                .where(
                    BatchAllocation.batch_id == batch.id,
                    OrderLineComponent.line_id == payload.line_id,
                )
            )
            if linked is None:
                raise HTTPException(
                    status_code=422,
                    detail=tr(
                        "{batch_number} does not serve this order line", batch_number=batch.number
                    ),
                )
        site_id = batch.site_id
    owner = await member_for(db, context, payload.owner_id, site_id)
    action = RecoveryAction(
        id=uuid.uuid4(),
        tenant_id=context.tenant.id,
        site_id=site_id,
        line_id=payload.line_id,
        batch_id=payload.batch_id,
        kind=payload.kind,
        title=payload.title,
        details=payload.details,
        status="awaiting_approval" if payload.kind in APPROVAL_KINDS else "open",
        owner_id=owner.id,
        owner_label=actor_label(owner),
        due_at=check_due(payload.due_at),
        risk_before=await line_risk(db, context, payload.line_id),
        submission_key=payload.submission_key,
        created_by=context.user.id,
        created_by_label=actor_label(context.user),
        created_at=now(),
    )
    db.add(action)
    await db.flush()
    record(db, context, action, "created", details={"owner": action.owner_label})
    audit(
        db,
        context,
        request,
        "actions.created",
        {
            "action_id": str(action.id),
            "kind": action.kind,
            "title": action.title,
            "owner": action.owner_label,
            "due_at": action.due_at.isoformat(),
            "line_id": str(action.line_id) if action.line_id else None,
            "batch_id": str(action.batch_id) if action.batch_id else None,
            "requires_approval": action.status == "awaiting_approval",
            "risk_before": action.risk_before,
        },
    )
    await commit_or_conflict(db, N_("This action could not be saved; reload and try again"))
    return await one_out(db, context, action)


@router.get("/{action_id}", response_model=ActionOut)
async def read_action(
    action_id: uuid.UUID,
    context: AuthContext = Depends(READ),
    db: AsyncSession = Depends(get_db),
):
    return await one_out(db, context, await get_action(db, context, action_id))


async def transition(
    db: AsyncSession,
    context: AuthContext,
    request: Request,
    action: RecoveryAction,
    event: str,
    note: str | None,
    details: dict[str, Any] | None = None,
) -> ActionOut:
    record(db, context, action, event, note, details)
    audit(
        db,
        context,
        request,
        f"actions.{event}",
        {"action_id": str(action.id), "title": action.title, "note": note, **(details or {})},
    )
    await commit_or_conflict(db, STALE)
    return await one_out(db, context, action)


@router.post("/{action_id}/approve", response_model=ActionOut, dependencies=CSRF)
async def approve_action(
    action_id: uuid.UUID,
    payload: ApproveIn,
    request: Request,
    context: AuthContext = Depends(APPROVE),
    db: AsyncSession = Depends(get_db),
):
    action = await get_action(db, context, action_id)
    require_version(action.version, payload.version)
    if action.status != "awaiting_approval":
        raise HTTPException(status_code=409, detail=tr("This action is not waiting for approval"))
    if context.blocks_self(action.created_by):
        raise HTTPException(status_code=403, detail=tr("You cannot approve an action you proposed"))
    action.status = "open"
    action.approved_by = context.user.id
    action.approved_at = now()
    return await transition(
        db, context, request, action, "approved", payload.note, self_approved(context, action)
    )


@router.post("/{action_id}/reject", response_model=ActionOut, dependencies=CSRF)
async def reject_action(
    action_id: uuid.UUID,
    payload: RejectIn,
    request: Request,
    context: AuthContext = Depends(APPROVE),
    db: AsyncSession = Depends(get_db),
):
    action = await get_action(db, context, action_id)
    require_version(action.version, payload.version)
    if action.status != "awaiting_approval":
        raise HTTPException(status_code=409, detail=tr("This action is not waiting for approval"))
    if context.blocks_self(action.created_by):
        raise HTTPException(
            status_code=403, detail=tr("You cannot decide on an action you proposed")
        )
    action.status = "rejected"
    action.closed_at = now()
    return await transition(
        db, context, request, action, "rejected", payload.reason, self_approved(context, action)
    )


@router.post("/{action_id}/acknowledge", response_model=ActionOut, dependencies=CSRF)
async def acknowledge_action(
    action_id: uuid.UUID,
    payload: ApproveIn,
    request: Request,
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    action = await get_action(db, context, action_id)
    require_version(action.version, payload.version)
    if action.owner_id != context.user.id:
        raise HTTPException(status_code=403, detail=tr("Only the owner can acknowledge an action"))
    if action.status != "open" or action.acknowledged_at is not None:
        raise HTTPException(status_code=409, detail=tr("This action cannot be acknowledged now"))
    action.acknowledged_at = now()
    return await transition(db, context, request, action, "acknowledged", payload.note)


@router.post("/{action_id}/supplier-acknowledgement", response_model=ActionOut, dependencies=CSRF)
async def supplier_acknowledgement(
    action_id: uuid.UUID,
    payload: SupplierAckIn,
    request: Request,
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    action = await get_action(db, context, action_id)
    require_version(action.version, payload.version)
    if action.batch_id is None:
        raise HTTPException(
            status_code=422, detail=tr("This action is not linked to a supplier batch")
        )
    if action.status != "open":
        raise HTTPException(status_code=409, detail=tr("Only open actions take acknowledgements"))
    said_at = payload.acknowledged_at.astimezone(UTC)
    if said_at > now() + timedelta(minutes=5):
        raise HTTPException(status_code=422, detail=tr("The acknowledgement time is in the future"))
    action.supplier_acknowledged_at = said_at
    return await transition(
        db,
        context,
        request,
        action,
        "supplier_acknowledged",
        payload.note,
        {
            # Entered by staff until suppliers can confirm for themselves (decision D2).
            "source": "manufacturer_entered",
            "contact_method": payload.contact_method,
            "contact_name": payload.contact_name,
            "acknowledged_at": said_at.isoformat(),
        },
    )


@router.post("/{action_id}/reassign", response_model=ActionOut, dependencies=CSRF)
async def reassign_action(
    action_id: uuid.UUID,
    payload: ReassignIn,
    request: Request,
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    action = await get_action(db, context, action_id)
    require_version(action.version, payload.version)
    if action.status not in ACTIVE:
        raise HTTPException(status_code=409, detail=tr("A closed action cannot be reassigned"))
    owner = await member_for(db, context, payload.owner_id, action.site_id)
    before = {"owner": action.owner_label, "due_at": as_utc(action.due_at).isoformat()}
    action.owner_id = owner.id
    action.owner_label = actor_label(owner)
    action.acknowledged_at = None
    if payload.due_at is not None:
        action.due_at = check_due(payload.due_at)
    after = {"owner": action.owner_label, "due_at": as_utc(action.due_at).isoformat()}
    return await transition(
        db,
        context,
        request,
        action,
        "reassigned",
        payload.reason,
        {"before": before, "after": after},
    )


def may_close(context: AuthContext, action: RecoveryAction) -> bool:
    return (
        action.owner_id == context.user.id
        or action.created_by == context.user.id
        or context.membership.role in TENANT_WIDE_ROLES
    )


@router.post("/{action_id}/complete", response_model=ActionOut, dependencies=CSRF)
async def complete_action(
    action_id: uuid.UUID,
    payload: CompleteIn,
    request: Request,
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    action = await get_action(db, context, action_id)
    require_version(action.version, payload.version)
    if not may_close(context, action):
        raise HTTPException(
            status_code=403, detail=tr("Only the owner or the person who raised it can close it")
        )
    if action.status == "awaiting_approval":
        raise HTTPException(status_code=409, detail=tr("This action is still waiting for approval"))
    if action.status != "open":
        raise HTTPException(status_code=409, detail=tr("This action is already closed"))
    action.status = "done"
    action.outcome = payload.outcome
    action.outcome_note = payload.note
    action.closed_at = now()
    action.risk_after = await line_risk(db, context, action.line_id)
    return await transition(
        db,
        context,
        request,
        action,
        "completed",
        payload.note,
        {
            "outcome": payload.outcome,
            "risk_before": action.risk_before,
            "risk_after": action.risk_after,
        },
    )


@router.post("/{action_id}/cancel", response_model=ActionOut, dependencies=CSRF)
async def cancel_action(
    action_id: uuid.UUID,
    payload: CancelIn,
    request: Request,
    context: AuthContext = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
):
    action = await get_action(db, context, action_id)
    require_version(action.version, payload.version)
    if not may_close(context, action):
        raise HTTPException(
            status_code=403, detail=tr("Only the owner or the person who raised it can cancel it")
        )
    if action.status not in ACTIVE:
        raise HTTPException(status_code=409, detail=tr("This action is already closed"))
    action.status = "cancelled"
    action.closed_at = now()
    return await transition(db, context, request, action, "cancelled", payload.reason)
