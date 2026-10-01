import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Time,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

DOCUMENT_TYPES = ("sales_order", "outsourced_batch", "dispatch")


class SiteCalendar(Base):
    """Working pattern for one site. Absent until an administrator saves it."""

    __tablename__ = "site_calendars"
    __table_args__ = (
        UniqueConstraint("site_id", name="uq_site_calendars_site"),
        CheckConstraint("shift_end > shift_start", name="shift_order"),
        ForeignKeyConstraint(
            ["tenant_id", "site_id"], ["sites.tenant_id", "sites.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    # ISO weekday digits in ascending order, e.g. "123456" for Monday to Saturday.
    working_days: Mapped[str] = mapped_column(String(7), nullable=False)
    shift_start: Mapped[time] = mapped_column(Time, nullable=False)
    shift_end: Mapped[time] = mapped_column(Time, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __mapper_args__ = {"version_id_col": version}


class SiteHoliday(Base):
    __tablename__ = "site_holidays"
    __table_args__ = (
        UniqueConstraint("site_id", "holiday_date", name="uq_site_holidays_site_date"),
        ForeignKeyConstraint(
            ["tenant_id", "site_id"], ["sites.tenant_id", "sites.id"], ondelete="CASCADE"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class DocumentSequence(Base):
    __tablename__ = "document_sequences"
    __table_args__ = (
        UniqueConstraint("tenant_id", "document_type", name="uq_document_sequences_type"),
        CheckConstraint(
            "document_type in (" + ", ".join(f"'{t}'" for t in DOCUMENT_TYPES) + ")",
            name="document_type",
        ),
        CheckConstraint("next_number >= 1", name="next_number_positive"),
        CheckConstraint("padding between 1 and 10", name="padding_range"),
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    document_type: Mapped[str] = mapped_column(String(30), nullable=False)
    prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    next_number: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    padding: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    __mapper_args__ = {"version_id_col": version}
