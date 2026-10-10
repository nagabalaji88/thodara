import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
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
from app.models.orders import QTY, _in

BATCH_STATUSES = ("planned", "at_supplier", "closed", "cancelled")
MOVEMENT_KINDS = ("sent_to_supplier",)
UPDATE_SOURCES = ("manufacturer_entered",)
CONTACT_METHODS = ("phone", "whatsapp", "email", "visit", "other")
CONFIRMATION_STATES = ("supplier_confirmation_pending",)


class OutsourcedBatch(Base):
    """One item sent to one job-work supplier for one operation."""

    __tablename__ = "outsourced_batches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_outsourced_batches_number"),
        UniqueConstraint("tenant_id", "id", name="uq_outsourced_batches_tenant_id_id"),
        Index("ix_outsourced_batches_tenant_status", "tenant_id", "status"),
        CheckConstraint(_in("status", BATCH_STATUSES), name="status"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["tenant_id", "site_id"],
            ["sites.tenant_id", "sites.id"],
            ondelete="RESTRICT",
            name="fk_outsourced_batches_site",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["suppliers.tenant_id", "suppliers.id"],
            ondelete="RESTRICT",
            name="fk_outsourced_batches_supplier",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "item_id"],
            ["items.tenant_id", "items.id"],
            ondelete="RESTRICT",
            name="fk_outsourced_batches_item",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "unit_id"],
            ["units_of_measure.tenant_id", "units_of_measure.id"],
            ondelete="RESTRICT",
            name="fk_outsourced_batches_unit",
        ),
        ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    number: Mapped[str] = mapped_column(String(40), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    # Snapshot of the item's base unit when the batch was created.
    unit_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    expected_return_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    sent_date: Mapped[date | None] = mapped_column(Date)
    challan_reference: Mapped[str | None] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)
    status_reason: Mapped[str | None] = mapped_column(String(500))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __mapper_args__ = {"version_id_col": version}


class BatchMovement(Base):
    """Immutable custody history: what physically moved, when, on which document."""

    __tablename__ = "batch_movements"
    __table_args__ = (
        CheckConstraint(_in("kind", MOVEMENT_KINDS), name="kind"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["outsourced_batches.tenant_id", "outsourced_batches.id"],
            ondelete="CASCADE",
            name="fk_batch_movements_batch",
        ),
        ForeignKeyConstraint(["recorded_by"], ["users.id"], ondelete="SET NULL"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    movement_date: Mapped[date] = mapped_column(Date, nullable=False)
    document_reference: Mapped[str | None] = mapped_column(String(80))
    note: Mapped[str | None] = mapped_column(String(500))
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    recorded_by_label: Mapped[str | None] = mapped_column(String(400))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BatchAllocation(Base):
    """How much of a batch is earmarked for one order-line component."""

    __tablename__ = "batch_allocations"
    __table_args__ = (
        UniqueConstraint("batch_id", "component_id", name="uq_batch_allocations_component"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["outsourced_batches.tenant_id", "outsourced_batches.id"],
            ondelete="CASCADE",
            name="fk_batch_allocations_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "component_id"],
            ["order_line_components.tenant_id", "order_line_components.id"],
            ondelete="RESTRICT",
            name="fk_batch_allocations_component",
        ),
        ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    component_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SupplierUpdate(Base):
    """What a supplier reported about a batch. Never a receipt; never edited, only corrected."""

    __tablename__ = "supplier_updates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "submission_key", name="uq_supplier_updates_submission"),
        UniqueConstraint("tenant_id", "id", name="uq_supplier_updates_tenant_id_id"),
        CheckConstraint(
            "completed_qty >= 0 AND rejected_qty >= 0 AND pending_qty >= 0", name="quantities"
        ),
        CheckConstraint(_in("source", UPDATE_SOURCES), name="source"),
        CheckConstraint(_in("contact_method", CONTACT_METHODS), name="contact_method"),
        CheckConstraint(_in("confirmation_state", CONFIRMATION_STATES), name="confirmation_state"),
        CheckConstraint(
            "(corrects_id IS NULL) = (correction_reason IS NULL)", name="correction_reason"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["outsourced_batches.tenant_id", "outsourced_batches.id"],
            ondelete="CASCADE",
            name="fk_supplier_updates_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "corrects_id"],
            ["supplier_updates.tenant_id", "supplier_updates.id"],
            # Updates are never deleted on their own; they go only with their batch.
            ondelete="CASCADE",
            name="fk_supplier_updates_corrects",
        ),
        ForeignKeyConstraint(["recorded_by"], ["users.id"], ondelete="SET NULL"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    completed_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    rejected_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    pending_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    revised_return_date: Mapped[date | None] = mapped_column(Date)
    blocker: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    contact_method: Mapped[str] = mapped_column(String(20), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(120))
    # When the supplier gave the information, which may be before it was typed in.
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmation_state: Mapped[str] = mapped_column(String(40), nullable=False)
    corrects_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    correction_reason: Mapped[str | None] = mapped_column(String(500))
    submission_key: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    recorded_by_label: Mapped[str | None] = mapped_column(String(400))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
