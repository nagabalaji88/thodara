import re
import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
)

CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._/-]{0,39}$")
PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9 ()-]{5,30}$")


def _normalize_code(value: object) -> object:
    return value.strip().upper() if isinstance(value, str) else value


def _check_code(value: str) -> str:
    if not CODE_PATTERN.fullmatch(value):
        raise ValueError(
            "Use 1–40 letters, digits, '.', '_', '/' or '-', starting with a letter or digit"
        )
    return value


def _collapse_spaces(value: object) -> object:
    return re.sub(r"\s+", " ", value).strip() if isinstance(value, str) else value


def _blank_to_none(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _check_phone(value: str | None) -> str | None:
    if value is not None and not PHONE_PATTERN.fullmatch(value):
        raise ValueError("Enter a phone number with digits, spaces, '+', '-' or brackets")
    return value


Code = Annotated[str, BeforeValidator(_normalize_code), AfterValidator(_check_code)]
Name = Annotated[str, BeforeValidator(_collapse_spaces), Field(min_length=1, max_length=160)]
OptionalText = Annotated[str | None, BeforeValidator(_blank_to_none), Field(max_length=120)]
OptionalEmail = Annotated[EmailStr | None, BeforeValidator(_blank_to_none)]
OptionalPhone = Annotated[
    str | None, BeforeValidator(_blank_to_none), AfterValidator(_check_phone)
]
Status = Literal["active", "inactive"]
Dimension = Literal["count", "mass", "length", "area", "volume", "time"]
ItemType = Literal[
    "raw_material",
    "component",
    "intermediate",
    "finished_good",
    "packaging",
    "consumable",
    "service",
]
Tracking = Literal["none", "lot", "serial"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VersionedUpdate(StrictModel):
    version: int = Field(ge=1)


class RecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


class Page[T](BaseModel):
    items: list[T]
    total: int


# Units


class UnitCreate(StrictModel):
    code: Code
    name: Name
    dimension: Dimension
    decimal_places: int = Field(ge=0, le=6)


class UnitUpdate(VersionedUpdate):
    name: Name | None = None
    decimal_places: int | None = Field(default=None, ge=0, le=6)
    status: Status | None = None


class UnitOut(RecordOut):
    dimension: str
    decimal_places: int


class ConversionCreate(StrictModel):
    from_unit_id: uuid.UUID
    to_unit_id: uuid.UUID
    factor: Decimal = Field(gt=0, max_digits=24, decimal_places=12)


class ConversionOut(BaseModel):
    id: uuid.UUID
    from_unit_id: uuid.UUID
    from_unit_code: str
    to_unit_id: uuid.UUID
    to_unit_code: str
    factor: Decimal
    created_at: datetime


# Parties


class CustomerCreate(StrictModel):
    code: Code
    name: Name
    contact_email: OptionalEmail = None
    contact_phone: OptionalPhone = None
    city: OptionalText = None


class CustomerUpdate(VersionedUpdate):
    name: Name | None = None
    contact_email: OptionalEmail = None
    contact_phone: OptionalPhone = None
    city: OptionalText = None
    status: Status | None = None


class CustomerOut(RecordOut):
    contact_email: str | None
    contact_phone: str | None
    city: str | None


class SupplierCreate(CustomerCreate):
    provides_job_work: bool = False


class SupplierUpdate(CustomerUpdate):
    provides_job_work: bool | None = None


class SupplierOut(CustomerOut):
    provides_job_work: bool


# Items


class ItemCreate(StrictModel):
    code: Code
    name: Name
    item_type: ItemType
    base_unit_id: uuid.UUID
    tracking: Tracking = "none"
    description: Annotated[
        str | None, BeforeValidator(_blank_to_none), Field(max_length=500)
    ] = None


class ItemUpdate(VersionedUpdate):
    name: Name | None = None
    item_type: ItemType | None = None
    base_unit_id: uuid.UUID | None = None
    tracking: Tracking | None = None
    description: Annotated[
        str | None, BeforeValidator(_blank_to_none), Field(max_length=500)
    ] = None
    status: Status | None = None


class ItemOut(RecordOut):
    item_type: str
    base_unit_id: uuid.UUID
    tracking: str
    description: str | None


# Warehouses


class WarehouseCreate(StrictModel):
    code: Code
    name: Name
    site_id: uuid.UUID


class WarehouseUpdate(VersionedUpdate):
    name: Name | None = None
    status: Status | None = None


class WarehouseOut(RecordOut):
    site_id: uuid.UUID


# Organization


class SiteCreate(StrictModel):
    name: Annotated[str, BeforeValidator(_collapse_spaces), Field(min_length=2, max_length=120)]
    city: OptionalText = None
    time_zone: str = Field(default="Asia/Kolkata", min_length=1, max_length=64)

    @field_validator("time_zone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Choose a valid IANA time zone") from exc
        return value


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    city: str | None
    time_zone: str
    status: str


class MemberOut(BaseModel):
    membership_id: uuid.UUID
    user_id: uuid.UUID
    email: str
    display_name: str
    role: str
    status: str
    site_scope: str
    site_ids: list[uuid.UUID]


class SiteAccessUpdate(StrictModel):
    site_scope: Literal["all", "selected"]
    site_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)


# Imports

ImportEntity = Literal["customers", "suppliers", "items"]


class ImportRequest(StrictModel):
    csv_text: str = Field(min_length=1, max_length=512_000)
    commit: bool = False


class ImportIssue(BaseModel):
    row: int
    field: str | None
    message: str


class ImportReport(BaseModel):
    entity: ImportEntity
    total_rows: int
    to_create: int
    unchanged: int
    errors: list[ImportIssue]
    committed: bool


# Calendars and numbering


class CalendarUpdate(StrictModel):
    working_days: list[int] = Field(min_length=1, max_length=7)
    shift_start: time
    shift_end: time
    version: int | None = Field(default=None, ge=1)

    @field_validator("working_days")
    @classmethod
    def validate_days(cls, value: list[int]) -> list[int]:
        if len(set(value)) != len(value) or any(day < 1 or day > 7 for day in value):
            raise ValueError("Use distinct weekdays from 1 (Monday) to 7 (Sunday)")
        return sorted(value)

    @field_validator("shift_start", "shift_end")
    @classmethod
    def whole_minutes(cls, value: time) -> time:
        if value.second or value.microsecond or value.tzinfo:
            raise ValueError("Use a local time in whole minutes, e.g. 09:00")
        return value


class HolidayCreate(StrictModel):
    holiday_date: date
    name: Name

    @field_validator("holiday_date")
    @classmethod
    def sensible_year(cls, value: date) -> date:
        if not 2000 <= value.year <= 2100:
            raise ValueError("Choose a date between 2000 and 2100")
        return value


class HolidayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    holiday_date: date
    name: str


class CalendarDay(BaseModel):
    day: date
    working: bool
    reason: str | None


class CalendarOut(BaseModel):
    site_id: uuid.UUID
    configured: bool
    working_days: list[int] | None
    shift_start: time | None
    shift_end: time | None
    minutes_per_day: int | None
    version: int | None
    holidays: list[HolidayOut]
    upcoming: list[CalendarDay]


class SequenceOut(BaseModel):
    document_type: str
    prefix: str
    next_number: int
    padding: int
    version: int
    preview: str


class SequenceUpdate(StrictModel):
    prefix: Annotated[str, BeforeValidator(_normalize_code), Field(max_length=12)]
    padding: int = Field(ge=1, le=10)
    next_number: int = Field(ge=1, le=10**12)
    version: int = Field(ge=1)

    @field_validator("prefix")
    @classmethod
    def prefix_characters(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Z0-9/-]*", value):
            raise ValueError("Use letters, digits, '/' or '-' only")
        return value
