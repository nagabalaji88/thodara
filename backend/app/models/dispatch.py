import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.orders import QTY, _in

DISPATCH_STATUSES = ("pending_approval", "posted", "rejected", "cancelled")


class DispatchNote(Base):
    """Goods that left the site for a customer order. Posted at once; reversed only by cancel."""

    __tablename__ = "dispatch_notes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_dispatch_notes_number"),
        UniqueConstraint("tenant_id", "id", name="uq_dispatch_notes_tenant_id_id"),
        UniqueConstraint("tenant_id", "submission_key", name="uq_dispatch_notes_submission"),
        CheckConstraint(_in("status", DISPATCH_STATUSES), name="status"),
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["tenant_id", "site_id"],
            ["sites.tenant_id", "sites.id"],
            ondelete="RESTRICT",
            name="fk_dispatch_notes_site",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "order_id"],
            ["sales_orders.tenant_id", "sales_orders.id"],
            ondelete="RESTRICT",
            name="fk_dispatch_notes_order",
        ),
        ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        ForeignKeyConstraint(["cancelled_by"], ["users.id"], ondelete="SET NULL"),
        ForeignKeyConstraint(["decided_by"], ["users.id"], ondelete="SET NULL"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    number: Mapped[str] = mapped_column(String(40), nullable=False)
    dispatch_date: Mapped[date] = mapped_column(Date, nullable=False)
    carrier: Mapped[str | None] = mapped_column(String(120))
    vehicle_reference: Mapped[str | None] = mapped_column(String(80))
    document_reference: Mapped[str | None] = mapped_column(String(80))
    note: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="posted")
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    # Shipping beyond accepted material is requested, then approved by someone else (G1).
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    decided_by_label: Mapped[str | None] = mapped_column(String(400))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(String(500))
    submission_key: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_by_label: Mapped[str | None] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    cancelled_by_label: Mapped[str | None] = mapped_column(String(400))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    __mapper_args__ = {"version_id_col": version}


class DispatchLine(Base):
    __tablename__ = "dispatch_lines"
    __table_args__ = (
        UniqueConstraint("dispatch_id", "line_id", name="uq_dispatch_lines_line"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        ForeignKeyConstraint(
            ["tenant_id", "dispatch_id"],
            ["dispatch_notes.tenant_id", "dispatch_notes.id"],
            ondelete="CASCADE",
            name="fk_dispatch_lines_dispatch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "line_id"],
            ["sales_order_lines.tenant_id", "sales_order_lines.id"],
            ondelete="RESTRICT",
            name="fk_dispatch_lines_line",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    dispatch_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    line_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    # Promise in force when it shipped, so on-time delivery is judged against it.
    promised_date: Mapped[date | None] = mapped_column(Date)
    on_time: Mapped[bool | None] = mapped_column(Boolean)
    exception_reason: Mapped[str | None] = mapped_column(String(500))
    # Which batch allocations supplied it, so a cancelled dispatch can be reversed exactly.
    consumption: Mapped[list | None] = mapped_column(JSON)
