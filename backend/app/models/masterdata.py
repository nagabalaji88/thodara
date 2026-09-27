import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.db.base import Base

UNIT_DIMENSIONS = ("count", "mass", "length", "area", "volume", "time")
ITEM_TYPES = (
    "raw_material",
    "component",
    "intermediate",
    "finished_good",
    "packaging",
    "consumable",
    "service",
)
TRACKING_MODES = ("none", "lot", "serial")
RECORD_STATUSES = ("active", "inactive")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} in (" + ", ".join(f"'{value}'" for value in values) + ")"


class MasterRecord:
    """Columns shared by tenant-owned master records."""

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, object]:
        return {"version_id_col": cls.version}


def _master_table_args(table: str, *extra: object) -> tuple[object, ...]:
    return (
        UniqueConstraint("tenant_id", "code", name=f"uq_{table}_tenant_code"),
        UniqueConstraint("tenant_id", "id", name=f"uq_{table}_tenant_id_id"),
        CheckConstraint(_in("status", RECORD_STATUSES), name="status"),
        CheckConstraint("code = upper(code)", name="code_uppercase"),
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        *extra,
    )


class UnitOfMeasure(MasterRecord, Base):
    __tablename__ = "units_of_measure"
    __table_args__ = _master_table_args(
        "units_of_measure",
        CheckConstraint(_in("dimension", UNIT_DIMENSIONS), name="dimension"),
        CheckConstraint("decimal_places between 0 and 6", name="decimal_places_range"),
    )

    dimension: Mapped[str] = mapped_column(String(20), nullable=False)
    decimal_places: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class UnitConversion(Base):
    __tablename__ = "unit_conversions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "from_unit_id", "to_unit_id", name="uq_unit_conversions_pair"
        ),
        CheckConstraint("factor > 0", name="factor_positive"),
        CheckConstraint("from_unit_id <> to_unit_id", name="distinct_units"),
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["tenant_id", "from_unit_id"],
            ["units_of_measure.tenant_id", "units_of_measure.id"],
            ondelete="RESTRICT",
            name="fk_unit_conversions_from_unit",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "to_unit_id"],
            ["units_of_measure.tenant_id", "units_of_measure.id"],
            ondelete="RESTRICT",
            name="fk_unit_conversions_to_unit",
        ),
        ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    from_unit_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    to_unit_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    # 1 from_unit = factor × to_unit
    factor: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Customer(MasterRecord, Base):
    __tablename__ = "customers"
    __table_args__ = _master_table_args("customers")

    contact_email: Mapped[str | None] = mapped_column(String(254))
    contact_phone: Mapped[str | None] = mapped_column(String(32))
    city: Mapped[str | None] = mapped_column(String(120))


class Supplier(MasterRecord, Base):
    __tablename__ = "suppliers"
    __table_args__ = _master_table_args("suppliers")

    contact_email: Mapped[str | None] = mapped_column(String(254))
    contact_phone: Mapped[str | None] = mapped_column(String(32))
    city: Mapped[str | None] = mapped_column(String(120))
    provides_job_work: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Item(MasterRecord, Base):
    __tablename__ = "items"
    __table_args__ = _master_table_args(
        "items",
        CheckConstraint(_in("item_type", ITEM_TYPES), name="item_type"),
        CheckConstraint(_in("tracking", TRACKING_MODES), name="tracking"),
        ForeignKeyConstraint(
            ["tenant_id", "base_unit_id"],
            ["units_of_measure.tenant_id", "units_of_measure.id"],
            ondelete="RESTRICT",
        ),
    )

    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    base_unit_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tracking: Mapped[str] = mapped_column(String(10), nullable=False, default="none")
    description: Mapped[str | None] = mapped_column(String(500))


class Warehouse(MasterRecord, Base):
    __tablename__ = "warehouses"
    __table_args__ = _master_table_args(
        "warehouses",
        ForeignKeyConstraint(
            ["tenant_id", "site_id"], ["sites.tenant_id", "sites.id"], ondelete="RESTRICT"
        ),
    )

    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)


class MembershipSite(Base):
    """Sites a non-admin membership may act on when its site_scope is 'selected'."""

    __tablename__ = "membership_sites"
    __table_args__ = (
        UniqueConstraint("membership_id", "site_id", name="uq_membership_sites_pair"),
        ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "site_id"], ["sites.tenant_id", "sites.id"], ondelete="CASCADE"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    membership_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
