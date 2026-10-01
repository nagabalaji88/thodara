import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, Field

from app.schemas.masterdata import StrictModel, _blank_to_none

Quantity = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=6)]
Reference = Annotated[Annotated[str, Field(max_length=80)] | None, BeforeValidator(_blank_to_none)]
Notes = Annotated[Annotated[str, Field(max_length=2000)] | None, BeforeValidator(_blank_to_none)]
ShortNote = Annotated[Annotated[str, Field(max_length=500)] | None, BeforeValidator(_blank_to_none)]
Reason = Annotated[
    str,
    BeforeValidator(lambda v: v.strip() if isinstance(v, str) else v),
    Field(min_length=3, max_length=500),
]
ChangeReason = Literal[
    "customer_request",
    "supplier_delay",
    "material_shortage",
    "capacity",
    "quality",
    "transport",
    "other",
]


def _sensible(value: date) -> date:
    if not 2000 <= value.year <= 2100:
        raise ValueError("Choose a date between 2000 and 2100")
    return value


SensibleDate = Annotated[date, AfterValidator(_sensible)]


class LineIn(StrictModel):
    item_id: uuid.UUID
    quantity: Quantity
    requested_date: SensibleDate
    promised_date: SensibleDate | None = None


class OrderCreate(StrictModel):
    site_id: uuid.UUID
    customer_id: uuid.UUID
    customer_reference: Reference = None
    order_date: SensibleDate | None = None
    notes: Notes = None
    lines: list[LineIn] = Field(min_length=1, max_length=200)


class OrderUpdate(StrictModel):
    version: int = Field(ge=1)
    customer_reference: Reference = None
    notes: Notes = None


class LineAdd(LineIn):
    order_version: int = Field(ge=1)


class LineUpdate(StrictModel):
    version: int = Field(ge=1)
    quantity: Quantity | None = None
    requested_date: SensibleDate | None = None
    promised_date: SensibleDate | None = None


class VersionOnly(StrictModel):
    version: int = Field(ge=1)


class ReasonedAction(StrictModel):
    version: int = Field(ge=1)
    reason: Reason


class PromiseChangeIn(StrictModel):
    version: int = Field(ge=1)
    new_date: SensibleDate
    reason_code: ChangeReason
    note: ShortNote = None


class PromiseOut(BaseModel):
    previous_date: date | None
    new_date: date
    reason_code: str
    note: str | None
    changed_by_label: str | None
    changed_at: datetime


class LineOut(BaseModel):
    id: uuid.UUID
    line_no: int
    item_id: uuid.UUID
    item_code: str
    item_name: str
    unit_code: str
    ordered_qty: Decimal
    shipped_qty: Decimal
    cancelled_qty: Decimal
    short_closed_qty: Decimal
    remaining_qty: Decimal
    requested_date: date
    promised_date: date | None
    status: str
    status_reason: str | None
    version: int
    promise_history: list[PromiseOut]


class OrderOut(BaseModel):
    id: uuid.UUID
    number: str
    site_id: uuid.UUID
    site_name: str
    customer_id: uuid.UUID
    customer_code: str
    customer_name: str
    customer_reference: str | None
    order_date: date
    status: str
    status_reason: str | None
    notes: str | None
    confirmed_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime
    lines: list[LineOut]


class OrderSummary(BaseModel):
    id: uuid.UUID
    number: str
    customer_code: str
    customer_name: str
    customer_reference: str | None
    site_name: str
    order_date: date
    status: str
    line_count: int
    open_lines: int
    next_promised_date: date | None


class OrderPage(BaseModel):
    items: list[OrderSummary]
    total: int


class OrderImportRequest(StrictModel):
    site_id: uuid.UUID
    csv_text: str = Field(min_length=1, max_length=512_000)
    commit: bool = False


class OrderImportIssue(BaseModel):
    row: int
    field: str | None
    message: str


class OrderImportReport(BaseModel):
    total_rows: int
    orders_to_create: int
    lines_to_create: int
    unchanged_orders: int
    errors: list[OrderImportIssue]
    committed: bool
    created_numbers: list[str] = []
