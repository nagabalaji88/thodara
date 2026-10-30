import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.actions import Contact
from app.schemas.masterdata import StrictModel
from app.schemas.orders import Quantity, Reason, Reference, SensibleDate, ShortNote


class DispatchLineIn(StrictModel):
    line_id: uuid.UUID
    quantity: Quantity
    # Shipping more than accepted, usable material needs a reason and approval by someone else.
    exception_reason: ShortNote = None


class DispatchCreate(StrictModel):
    submission_key: uuid.UUID
    order_id: uuid.UUID
    dispatch_date: SensibleDate
    carrier: Contact = None
    vehicle_reference: Reference = None
    document_reference: Reference = None
    note: ShortNote = None
    lines: list[DispatchLineIn] = Field(min_length=1, max_length=200)


class DispatchDecision(StrictModel):
    version: int = Field(ge=1)
    note: ShortNote = None


class DispatchCancel(StrictModel):
    version: int = Field(ge=1)
    reason: Reason


class DispatchLineOut(BaseModel):
    line_id: uuid.UUID
    line_no: int
    item_code: str
    unit_code: str
    quantity: Decimal
    promised_date: date | None
    on_time: bool | None
    exception_reason: str | None


class DispatchOut(BaseModel):
    id: uuid.UUID
    number: str
    order_id: uuid.UUID
    order_number: str
    customer_name: str
    site_name: str
    dispatch_date: date
    carrier: str | None
    vehicle_reference: str | None
    document_reference: str | None
    note: str | None
    status: str
    cancel_reason: str | None
    created_by_label: str | None
    created_at: datetime
    cancelled_by_label: str | None
    cancelled_at: datetime | None
    decided_by_label: str | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None
    can_decide: bool = False
    version: int
    lines: list[DispatchLineOut]


class ReadinessComponent(BaseModel):
    item_code: str
    unit_code: str
    qty_per_unit: Decimal
    usable_for_line: Decimal
    source: str = "batch"  # accepted batch material, or site stock (G2)


class LineReadiness(BaseModel):
    line_id: uuid.UUID
    line_no: int
    item_code: str
    unit_code: str
    remaining: Decimal
    promised_date: date | None
    # None when no component of the line is tracked (outsourced or in stock).
    shippable: Decimal | None
    # This line's share of finished-goods stock; None when the item has no stock record here.
    finished_stock: Decimal | None = None
    components: list[ReadinessComponent]


class Readiness(BaseModel):
    order_id: uuid.UUID
    lines: list[LineReadiness]
