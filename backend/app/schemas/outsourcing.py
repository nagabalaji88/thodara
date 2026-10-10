import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.masterdata import StrictModel
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
