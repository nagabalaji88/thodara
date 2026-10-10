import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, BeforeValidator, Field

from app.schemas.masterdata import StrictModel, _blank_to_none
from app.schemas.orders import (
    Notes,
    OperationName,
    Quantity,
    Reason,
    Reference,
    SensibleDate,
)


class AllocationIn(StrictModel):
    component_id: uuid.UUID
    quantity: Quantity


class BatchCreate(StrictModel):
    site_id: uuid.UUID
    supplier_id: uuid.UUID
    item_id: uuid.UUID
    operation: OperationName
    quantity: Quantity
    expected_return_date: SensibleDate
    notes: Notes = None
    allocations: list[AllocationIn] = Field(default=[], max_length=50)


class BatchUpdate(StrictModel):
    version: int = Field(ge=1)
    operation: OperationName | None = None
    quantity: Quantity | None = None
    expected_return_date: SensibleDate | None = None
    notes: Notes = None


class BatchSend(StrictModel):
    version: int = Field(ge=1)
    sent_date: SensibleDate
    challan_reference: Reference = None


class BatchReasoned(StrictModel):
    version: int = Field(ge=1)
    reason: Reason


NonNegative = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=6)]
ShortText = Annotated[Annotated[str, Field(max_length=500)] | None, BeforeValidator(_blank_to_none)]
ContactName = Annotated[
    Annotated[str, Field(max_length=120)] | None, BeforeValidator(_blank_to_none)
]


class SupplierUpdateIn(StrictModel):
    version: int = Field(ge=1)
    submission_key: uuid.UUID
    completed_qty: NonNegative
    rejected_qty: NonNegative
    pending_qty: NonNegative
    revised_return_date: SensibleDate | None = None
    blocker: ShortText = None
    contact_method: Literal["phone", "whatsapp", "email", "visit", "other"]
    contact_name: ContactName = None
    reported_at: AwareDatetime
    corrects_id: uuid.UUID | None = None
    correction_reason: ShortText = None


class SupplierUpdateOut(BaseModel):
    id: uuid.UUID
    completed_qty: Decimal
    rejected_qty: Decimal
    pending_qty: Decimal
    revised_return_date: date | None
    blocker: str | None
    source: str
    contact_method: str
    contact_name: str | None
    reported_at: datetime
    confirmation_state: str
    corrects_id: uuid.UUID | None
    correction_reason: str | None
    superseded: bool
    recorded_by_label: str | None
    recorded_at: datetime


class QuantityPicture(BaseModel):
    """Supplier-reported, received and accepted quantities, deliberately kept apart."""

    sent: Decimal
    reported_completed: Decimal | None
    reported_rejected: Decimal | None
    reported_pending: Decimal | None
    received: Decimal
    accepted: Decimal


class AllocationAdd(AllocationIn):
    version: int = Field(ge=1)


class BatchAllocationOut(BaseModel):
    id: uuid.UUID
    component_id: uuid.UUID
    quantity: Decimal
    order_id: uuid.UUID
    order_number: str
    order_status: str
    customer_name: str
    line_no: int
    line_item_code: str
    line_status: str
    promised_date: date | None
    component_required_qty: Decimal


class MovementOut(BaseModel):
    kind: str
    quantity: Decimal
    movement_date: date
    document_reference: str | None
    note: str | None
    recorded_by_label: str | None
    recorded_at: datetime


class BatchOut(BaseModel):
    id: uuid.UUID
    number: str
    site_id: uuid.UUID
    site_name: str
    supplier_id: uuid.UUID
    supplier_code: str
    supplier_name: str
    item_id: uuid.UUID
    item_code: str
    item_name: str
    unit_code: str
    operation: str
    quantity: Decimal
    allocated_qty: Decimal
    expected_return_date: date
    status: str
    status_reason: str | None
    sent_date: date | None
    challan_reference: str | None
    notes: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    allocations: list[BatchAllocationOut]
    movements: list[MovementOut]
    quantities: QuantityPicture
    latest_update: SupplierUpdateOut | None
    updates: list[SupplierUpdateOut]


class BatchSummary(BaseModel):
    id: uuid.UUID
    number: str
    site_name: str
    supplier_name: str
    item_code: str
    item_name: str
    unit_code: str
    operation: str
    quantity: Decimal
    allocated_qty: Decimal
    order_count: int
    expected_return_date: date
    sent_date: date | None
    status: str
    last_reported_at: datetime | None = None
    reported_completed: Decimal | None = None
    reported_rejected: Decimal | None = None
    reported_pending: Decimal | None = None
    revised_return_date: date | None = None
    blocker: str | None = None


class BatchPage(BaseModel):
    items: list[BatchSummary]
    total: int


class Candidate(BaseModel):
    component_id: uuid.UUID
    order_id: uuid.UUID
    order_number: str
    customer_name: str
    line_no: int
    line_item_code: str
    promised_date: date | None
    outsourced_operation: str | None
    required_qty: Decimal
    allocated_qty: Decimal
    open_qty: Decimal
