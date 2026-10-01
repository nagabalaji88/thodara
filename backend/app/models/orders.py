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
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

ORDER_STATUSES = ("draft", "confirmed", "cancelled", "closed")
LINE_STATUSES = ("open", "fulfilled", "short_closed", "cancelled")
PROMISE_REASONS = (
    "initial",
    "customer_request",
    "supplier_delay",
    "material_shortage",
    "capacity",
    "quality",
    "transport",
    "other",
)
QTY = Numeric(18, 6)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} in (" + ", ".join(f"'{v}'" for v in values) + ")"


class SalesOrder(Base):
    __tablename__ = "sales_orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_sales_orders_number"),
        UniqueConstraint("tenant_id", "id", name="uq_sales_orders_tenant_id_id"),
        # Re-importing the same customer PO must not create a second order.
        Index(
            "uq_sales_orders_customer_reference",
            "tenant_id",
            "customer_id",
            "customer_reference",
            unique=True,
            postgresql_where=text("customer_reference IS NOT NULL"),
            sqlite_where=text("customer_reference IS NOT NULL"),
        ),
        Index("ix_sales_orders_tenant_status", "tenant_id", "status"),
        CheckConstraint(_in("status", ORDER_STATUSES), name="status"),
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["tenant_id", "site_id"],
            ["sites.tenant_id", "sites.id"],
            ondelete="RESTRICT",
            name="fk_sales_orders_site",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            ondelete="RESTRICT",
            name="fk_sales_orders_customer",
        ),
        ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    number: Mapped[str] = mapped_column(String(40), nullable=False)
    customer_reference: Mapped[str | None] = mapped_column(String(80))
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    notes: Mapped[str | None] = mapped_column(Text)
    status_reason: Mapped[str | None] = mapped_column(String(500))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __mapper_args__ = {"version_id_col": version}


class SalesOrderLine(Base):
    __tablename__ = "sales_order_lines"
    __table_args__ = (
        UniqueConstraint("order_id", "line_no", name="uq_sales_order_lines_line_no"),
        UniqueConstraint("tenant_id", "id", name="uq_sales_order_lines_tenant_id_id"),
        CheckConstraint(_in("status", LINE_STATUSES), name="status"),
        CheckConstraint("ordered_qty > 0", name="ordered_positive"),
        CheckConstraint("cancelled_qty >= 0 AND short_closed_qty >= 0", name="closed_nonneg"),
        CheckConstraint(
            "cancelled_qty + short_closed_qty <= ordered_qty", name="closed_within_ordered"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "order_id"],
            ["sales_orders.tenant_id", "sales_orders.id"],
            ondelete="CASCADE",
            name="fk_sales_order_lines_order",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "item_id"],
            ["items.tenant_id", "items.id"],
            ondelete="RESTRICT",
            name="fk_sales_order_lines_item",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "unit_id"],
            ["units_of_measure.tenant_id", "units_of_measure.id"],
            ondelete="RESTRICT",
            name="fk_sales_order_lines_unit",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    # Snapshot of the item's base unit when the line was entered.
    unit_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ordered_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    cancelled_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False, default=Decimal(0))
    short_closed_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False, default=Decimal(0))
    requested_date: Mapped[date] = mapped_column(Date, nullable=False)
    promised_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    status_reason: Mapped[str | None] = mapped_column(String(500))
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    __mapper_args__ = {"version_id_col": version}


class PromiseChange(Base):
    """Immutable history of promised dates for an order line."""

    __tablename__ = "promise_changes"
    __table_args__ = (
        CheckConstraint(_in("reason_code", PROMISE_REASONS), name="reason_code"),
        ForeignKeyConstraint(
            ["tenant_id", "line_id"],
            ["sales_order_lines.tenant_id", "sales_order_lines.id"],
            ondelete="CASCADE",
            name="fk_promise_changes_line",
        ),
        ForeignKeyConstraint(["changed_by"], ["users.id"], ondelete="SET NULL"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    line_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    previous_date: Mapped[date | None] = mapped_column(Date)
    new_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(30), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    changed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    changed_by_label: Mapped[str | None] = mapped_column(String(400))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
