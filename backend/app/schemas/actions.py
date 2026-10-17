import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, BeforeValidator, Field

from app.schemas.masterdata import StrictModel, _blank_to_none
from app.schemas.orders import Reason

Kind = Literal[
    "chase_update",
    "collect",
    "expedite",
    "overtime",
    "resequence",
    "rework",
    "alternate_supplier",
    "promise_review",
    "other",
]
Title = Annotated[
    str,
    BeforeValidator(lambda v: " ".join(v.split()) if isinstance(v, str) else v),
    Field(min_length=3, max_length=160),
]
Details = Annotated[Annotated[str, Field(max_length=2000)] | None, BeforeValidator(_blank_to_none)]
Note = Annotated[Annotated[str, Field(max_length=1000)] | None, BeforeValidator(_blank_to_none)]
Contact = Annotated[Annotated[str, Field(max_length=120)] | None, BeforeValidator(_blank_to_none)]
LongReason = Annotated[
    str,
    BeforeValidator(lambda v: v.strip() if isinstance(v, str) else v),
    Field(min_length=3, max_length=1000),
]


class ActionCreate(StrictModel):
    submission_key: uuid.UUID
    kind: Kind
    title: Title
    details: Details = None
    line_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    owner_id: uuid.UUID
    due_at: AwareDatetime


class Versioned(StrictModel):
    version: int = Field(ge=1)


class ApproveIn(Versioned):
    note: Note = None


class RejectIn(Versioned):
    reason: Reason


class SupplierAckIn(Versioned):
    contact_method: Literal["phone", "whatsapp", "email", "visit", "other"]
    contact_name: Contact = None
    acknowledged_at: AwareDatetime
    note: Note = None


class ReassignIn(Versioned):
    owner_id: uuid.UUID
    due_at: AwareDatetime | None = None
    reason: Reason


class CompleteIn(Versioned):
    outcome: Literal["resolved", "partly_resolved", "not_resolved"]
    note: LongReason


class CancelIn(Versioned):
    reason: Reason


class EventOut(BaseModel):
    kind: str
    note: str | None
    details: dict | None
    actor_label: str | None
    created_at: datetime


class SubjectLine(BaseModel):
    line_id: uuid.UUID
    order_id: uuid.UUID
    order_number: str
    line_no: int
    customer_name: str
    item_code: str


class SubjectBatch(BaseModel):
    batch_id: uuid.UUID
    number: str
    supplier_name: str


class ActionOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    details: str | None
    status: str
    requires_approval: bool
    site_id: uuid.UUID
    line: SubjectLine | None
    batch: SubjectBatch | None
    owner_id: uuid.UUID
    owner_label: str
    due_at: datetime
    overdue: bool
    created_by_label: str | None
    created_at: datetime
    approved_at: datetime | None
    acknowledged_at: datetime | None
    supplier_acknowledged_at: datetime | None
    outcome: str | None
    outcome_note: str | None
    closed_at: datetime | None
    risk_before: dict | None
    risk_after: dict | None
    version: int
    is_mine: bool
    can_approve: bool
    events: list[EventOut] = []


class ActionPage(BaseModel):
    items: list[ActionOut]
    total: int
    counts: dict[str, int]


class Assignee(BaseModel):
    user_id: uuid.UUID
    display_name: str
    role: str
