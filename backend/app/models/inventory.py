"""Basic stock per warehouse (slice G2, ADR-0010).

Stock changes only through movements, which are never edited. The balance row per warehouse
and item is the running total of posted movements; a check keeps it from going below zero.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
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

STOCK_KINDS = ("opening", "receipt", "issue", "adjustment", "dispatch", "reversal")
STOCK_STATUSES = ("pending_approval", "posted", "rejected")
# Entered by stores but counted only after someone else approves them (ADR-0010).
NEEDS_APPROVAL = frozenset({"opening", "adjustment"})


def _site_item_warehouse(table: str) -> tuple[ForeignKeyConstraint, ...]:
    return (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["tenant_id", "site_id"],
            ["sites.tenant_id", "sites.id"],
            ondelete="RESTRICT",
            name=f"fk_{table}_site",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "warehouse_id"],
            ["warehouses.tenant_id", "warehouses.id"],
            ondelete="RESTRICT",
            name=f"fk_{table}_warehouse",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "item_id"],
            ["items.tenant_id", "items.id"],
            ondelete="RESTRICT",
            name=f"fk_{table}_item",
        ),
    )


class StockBalance(Base):
    __tablename__ = "stock_balances"
    __table_args__ = (
        UniqueConstraint("tenant_id", "warehouse_id", "item_id", name="uq_stock_balances_place"),
        CheckConstraint("on_hand >= 0", name="not_negative"),
        *_site_item_warehouse("stock_balances"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    on_hand: Mapped[Decimal] = mapped_column(QTY, nullable=False, default=Decimal(0))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    __mapper_args__ = {"version_id_col": version}


class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_stock_movements_tenant_id_id"),
        UniqueConstraint("tenant_id", "submission_key", name="uq_stock_movements_submission"),
        CheckConstraint(_in("kind", STOCK_KINDS), name="kind"),
        CheckConstraint(_in("status", STOCK_STATUSES), name="status"),
        CheckConstraint("quantity <> 0", name="quantity_nonzero"),
        *_site_item_warehouse("stock_movements"),
        ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        ForeignKeyConstraint(["decided_by"], ["users.id"], ondelete="SET NULL"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # Signed, in the item's base unit: positive adds stock, negative takes it away.
    quantity: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    movement_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    reference: Mapped[str | None] = mapped_column(String(80))
    balance_after: Mapped[Decimal | None] = mapped_column(QTY)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The movement this one reverses, and the dispatch note that used the stock.
    reverses_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("stock_movements.id", ondelete="CASCADE"), index=True
    )
    dispatch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("dispatch_notes.id", ondelete="RESTRICT"), index=True
    )
    submission_key: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_by_label: Mapped[str | None] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    decided_by_label: Mapped[str | None] = mapped_column(String(400))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(String(500))
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    __mapper_args__ = {"version_id_col": version}
