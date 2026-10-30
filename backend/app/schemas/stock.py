import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.masterdata import StrictModel
from app.schemas.orders import Quantity, Reason, Reference, SensibleDate, ShortNote
from app.schemas.risk import Qty


class StockMovementCreate(StrictModel):
    submission_key: uuid.UUID
    warehouse_id: uuid.UUID
    item_id: uuid.UUID
    kind: Literal["opening", "receipt", "issue", "adjustment"]
    # Adjustments say which way they go; the other kinds have a fixed direction.
    direction: Literal["in", "out"] | None = None
    quantity: Quantity
    movement_date: SensibleDate
    reason: ShortNote = None
    reference: Reference = None


class StockDecision(StrictModel):
    version: int = Field(ge=1)
    note: ShortNote = None


class StockReject(StrictModel):
    version: int = Field(ge=1)
    reason: Reason


class StockReverse(StrictModel):
    version: int = Field(ge=1)
    submission_key: uuid.UUID
    reason: Reason


class StockMovementOut(BaseModel):
    id: uuid.UUID
    site_id: uuid.UUID
    site_name: str
    warehouse_id: uuid.UUID
    warehouse_code: str
    item_id: uuid.UUID
    item_code: str
    item_name: str
    unit_code: str
    kind: str
    quantity: Qty
    status: str
    movement_date: date
    reason: str | None
    reference: str | None
    balance_after: Qty | None
    dispatch_id: uuid.UUID | None
    dispatch_number: str | None
    reverses_id: uuid.UUID | None
    reversed: bool
    created_by_label: str | None
    created_at: datetime
    decided_by_label: str | None
    decided_at: datetime | None
    decision_note: str | None
    can_decide: bool
    can_reverse: bool
    version: int


class StockBalanceOut(BaseModel):
    site_id: uuid.UUID
    site_name: str
    warehouse_id: uuid.UUID
    warehouse_code: str
    warehouse_name: str
    item_id: uuid.UUID
    item_code: str
    item_name: str
    item_type: str
    unit_code: str
    on_hand: Qty
    pending: int


class StockSummary(BaseModel):
    balances: list[StockBalanceOut]
    pending_for_me: int
