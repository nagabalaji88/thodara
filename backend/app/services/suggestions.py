"""Rule-based recovery suggestions from a line's risk (slice F7).

Deterministic and explainable: each suggestion follows from one fact in the risk calculation.
Suggestions are drafts; nothing happens until a person creates an action from one.
"""

import uuid
from dataclasses import dataclass

from app.models.actions import APPROVAL_KINDS
from app.services.risk import LineRisk


@dataclass
class Suggestion:
    kind: str
    title: str
    details: str
    line_id: uuid.UUID
    batch_id: uuid.UUID | None

    @property
    def requires_approval(self) -> bool:
        return self.kind in APPROVAL_KINDS


def _q(value) -> str:
    return format(value.normalize(), "f")


def suggest(risk: LineRisk) -> list[Suggestion]:
    if risk.headline in ("on_track", "ready") and not any(
        a.ready_to_collect > 0 for c in risk.components for a in c.allocations
    ):
        return []
    out: list[Suggestion] = []
    seen: set[tuple[str, uuid.UUID | None]] = set()
    ref = f"{risk.order_number}/{risk.line_no}"

    def add(kind: str, title: str, details: str, batch_id: uuid.UUID | None = None) -> None:
        if (kind, batch_id) not in seen:
            seen.add((kind, batch_id))
            out.append(Suggestion(kind, title[:160], details, risk.line_id, batch_id))

    late = risk.headline == "confirmed_late" or (
        risk.slack_days is not None and risk.slack_days < 0
    )
    for component in risk.components:
        unit = component.unit_code
        if component.uncovered > 0:
            add(
                "alternate_supplier",
                f"Source {_q(component.uncovered)} {unit} {component.item_code} for {ref}",
                f"No batch covers {_q(component.uncovered)} {unit} of {component.item_code}"
                f" needed for {component.outsourced_operation or 'this line'}.",
            )
        for a in component.allocations:
            if a.stale or (a.estimate_date is None and a.from_supplier > 0):
                add(
                    "chase_update",
                    f"Get a fresh update from {a.supplier_name} on {a.batch_number}",
                    f"{ref} needs {_q(a.from_supplier)} {unit} still at the supplier; "
                    "the information we have is stale or its date has passed.",
                    a.batch_id,
                )
            if a.ready_to_collect > 0 and a.from_supplier > 0:
                add(
                    "collect",
                    f"Collect the {_q(a.ready_to_collect)} {unit} completed at {a.supplier_name}",
                    f"{a.supplier_name} reports {_q(a.ready_to_collect)} {unit} of "
                    f"{a.batch_number} complete but not yet received. Collecting part of the batch"
                    f" now brings material for {ref} forward.",
                    a.batch_id,
                )
            if a.short > 0:
                add(
                    "rework",
                    f"Rework rejected {component.item_code} from {a.batch_number}",
                    f"{a.batch_number} is expected to deliver {_q(a.short)} {unit} less than "
                    f"{ref} needs because of rejections. Rework needs quality approval.",
                    a.batch_id,
                )
                add(
                    "alternate_supplier",
                    f"Evaluate another supplier for {_q(a.short)} {unit} {component.item_code}",
                    f"Short by {_q(a.short)} {unit} on {a.batch_number}. A supplier change needs "
                    "approval.",
                    a.batch_id,
                )
            if a.held > 0:
                add(
                    "other",
                    f"Get a quality decision on {_q(a.held)} {unit} held in {a.batch_number}",
                    f"{ref} needs {_q(a.held)} {unit} that quality has on hold.",
                    a.batch_id,
                )
            if late and a.from_supplier > 0:
                add(
                    "expedite",
                    f"Ask {a.supplier_name} to expedite {a.batch_number}",
                    f"{ref} is projected late; {_q(a.from_supplier)} {unit} is still to come "
                    f"from {a.supplier_name}.",
                    a.batch_id,
                )
    if late and risk.operation_minutes > 0:
        add(
            "overtime",
            f"Plan overtime or resequence in-house work for {ref}",
            f"{risk.operation_minutes // 60} h of in-house work remains after the material "
            "arrives.",
        )
    if late:
        state = "past its promise" if risk.headline == "confirmed_late" else "projected late"
        add(
            "promise_review",
            f"Review the promised date with {risk.customer_name}",
            f"{ref} is {state}. "
            "Changing the promise needs approval and is recorded with a reason on the order.",
        )
    return out
