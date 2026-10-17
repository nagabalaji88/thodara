import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.orders import _in

ACTION_KINDS = (
    "chase_update",
    "collect",
    "expedite",
    "overtime",
    "resequence",
    "rework",
    "alternate_supplier",
    "promise_review",
    "other",
)
# Consequential kinds: quality, supplier-change and commercial decisions need approval.
APPROVAL_KINDS = ("rework", "alternate_supplier", "promise_review")
ACTION_STATUSES = ("awaiting_approval", "open", "done", "rejected", "cancelled")
OUTCOMES = ("resolved", "partly_resolved", "not_resolved")
EVENT_KINDS = (
    "created",
    "approved",
    "rejected",
    "acknowledged",
    "supplier_acknowledged",
    "reassigned",
    "completed",
    "cancelled",
)


class RecoveryAction(Base):
    """Something a named person must do, by a time, to protect a customer commitment."""

    __tablename__ = "recovery_actions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_recovery_actions_tenant_id_id"),
        UniqueConstraint("tenant_id", "submission_key", name="uq_recovery_actions_submission"),
        Index("ix_recovery_actions_tenant_status", "tenant_id", "status"),
        CheckConstraint(_in("kind", ACTION_KINDS), name="kind"),
        CheckConstraint(_in("status", ACTION_STATUSES), name="status"),
        CheckConstraint(f"outcome IS NULL OR {_in('outcome', OUTCOMES)}", name="outcome"),
        CheckConstraint("line_id IS NOT NULL OR batch_id IS NOT NULL", name="has_subject"),
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["tenant_id", "site_id"],
            ["sites.tenant_id", "sites.id"],
            ondelete="RESTRICT",
            name="fk_recovery_actions_site",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "line_id"],
            ["sales_order_lines.tenant_id", "sales_order_lines.id"],
            ondelete="RESTRICT",
            name="fk_recovery_actions_line",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["outsourced_batches.tenant_id", "outsourced_batches.id"],
            ondelete="RESTRICT",
            name="fk_recovery_actions_batch",
        ),
        ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="SET NULL"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    line_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    details: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    owner_label: Mapped[str] = mapped_column(String(400), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # The risk that prompted the action, and the risk when it was closed, for follow-up.
    risk_before: Mapped[dict | None] = mapped_column(JSON)
    risk_after: Mapped[dict | None] = mapped_column(JSON)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supplier_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(20))
    outcome_note: Mapped[str | None] = mapped_column(String(1000))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submission_key: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_by_label: Mapped[str | None] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    __mapper_args__ = {"version_id_col": version}


class ActionEvent(Base):
    """Immutable history of an action: who did what, when, and why."""

    __tablename__ = "action_events"
    __table_args__ = (
        CheckConstraint(_in("kind", EVENT_KINDS), name="kind"),
        ForeignKeyConstraint(
            ["tenant_id", "action_id"],
            ["recovery_actions.tenant_id", "recovery_actions.id"],
            ondelete="CASCADE",
            name="fk_action_events_action",
        ),
        ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    action_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    note: Mapped[str | None] = mapped_column(String(1000))
    details: Mapped[dict | None] = mapped_column(JSON)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    actor_label: Mapped[str | None] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
