import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.schemas.masterdata import StrictModel

# Quantities without trailing zeros or exponents: 40.000000 -> "40".
Qty = Annotated[Decimal, PlainSerializer(lambda d: format(d.normalize(), "f"), return_type=str)]


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class IssueOut(Out):
    code: str
    message: str


class AllocationRiskOut(Out):
    batch_number: str
    batch_id: uuid.UUID
    supplier_name: str
    batch_status: str
    allocated: Qty
    accepted: Qty
    awaiting: Qty
    held: Qty
    from_supplier: Qty
    short: Qty
    estimate_date: date | None
    estimate_source: str | None
    last_update_at: datetime | None
    stale: bool
    ahead: list[str]


class ComponentRiskOut(Out):
    item_code: str
    unit_code: str
    required: Qty
    outsourced_operation: str | None
    uncovered: Qty
    usable_now: Qty
    allocations: list[AllocationRiskOut]


class LineRiskOut(Out):
    line_id: uuid.UUID
    order_id: uuid.UUID
    order_number: str
    customer_name: str
    line_no: int
    item_code: str
    unit_code: str
    remaining: Qty
    promised_date: date | None
    headline: str
    issues: list[IssueOut]
    notes: list[str]
    components_ready_date: date | None
    projected_finish: datetime | None
    projected_date: date | None
    slack_days: int | None
    operation_minutes: int
    components: list[ComponentRiskOut]
    time_zone: str | None


class RiskReport(BaseModel):
    computed_at: datetime
    stale_after_hours: int
    counts: dict[str, int]
    lines: list[LineRiskOut]


class FulfillmentSettingsOut(BaseModel):
    supplier_update_stale_hours: int
    is_default: bool
    version: int | None


class FulfillmentSettingsIn(StrictModel):
    version: int | None = Field(default=None, ge=1)
    supplier_update_stale_hours: int = Field(ge=1, le=720)
