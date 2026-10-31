"""Rule-based recovery suggestions from a line's risk (slice F7).

Deterministic and explainable: each suggestion follows from one fact in the risk calculation.
Suggestions are drafts; nothing happens until a person creates an action from one.
"""

import uuid
from dataclasses import dataclass

from app.core.i18n import tr
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
                tr(
                    "Source {component_uncovered} {unit} {component_item_code} for {ref}",
                    component_uncovered=_q(component.uncovered),
                    unit=unit,
                    component_item_code=component.item_code,
                    ref=ref,
                ),
                tr(
                    (
                        "No batch covers {component_uncovered} {unit} of {component_item_code} "
                        "needed for {value}."
                    ),
                    component_uncovered=_q(component.uncovered),
                    unit=unit,
                    component_item_code=component.item_code,
                    value=component.outsourced_operation or "this line",
                ),
            )
        for a in component.allocations:
            if a.stale or (a.estimate_date is None and a.from_supplier > 0):
                add(
                    "chase_update",
                    tr(
                        "Get a fresh update from {a_supplier_name} on {a_batch_number}",
                        a_supplier_name=a.supplier_name,
                        a_batch_number=a.batch_number,
                    ),
                    tr(
                        (
                            "{ref} needs {a_from_supplier} {unit} still at the supplier; the "
                            "information we have is stale or its date has passed."
                        ),
                        ref=ref,
                        a_from_supplier=_q(a.from_supplier),
                        unit=unit,
                    ),
                    a.batch_id,
                )
            if a.ready_to_collect > 0 and a.from_supplier > 0:
                add(
                    "collect",
                    tr(
                        "Collect the {a_ready_to_collect} {unit} completed at {a_supplier_name}",
                        a_ready_to_collect=_q(a.ready_to_collect),
                        unit=unit,
                        a_supplier_name=a.supplier_name,
                    ),
                    tr(
                        (
                            "{a_supplier_name} reports {a_ready_to_collect} {unit} of "
                            "{a_batch_number} complete but not yet received. Collecting part of "
                            "the batch now brings material for {ref} forward."
                        ),
                        a_supplier_name=a.supplier_name,
                        a_ready_to_collect=_q(a.ready_to_collect),
                        unit=unit,
                        a_batch_number=a.batch_number,
                        ref=ref,
                    ),
                    a.batch_id,
                )
            if a.short > 0:
                add(
                    "rework",
                    tr(
                        "Rework rejected {component_item_code} from {a_batch_number}",
                        component_item_code=component.item_code,
                        a_batch_number=a.batch_number,
                    ),
                    tr(
                        (
                            "{a_batch_number} is expected to deliver {a_short} {unit} less than "
                            "{ref} needs because of rejections. Rework needs quality approval."
                        ),
                        a_batch_number=a.batch_number,
                        a_short=_q(a.short),
                        unit=unit,
                        ref=ref,
                    ),
                    a.batch_id,
                )
                add(
                    "alternate_supplier",
                    tr(
                        "Evaluate another supplier for {a_short} {unit} {component_item_code}",
                        a_short=_q(a.short),
                        unit=unit,
                        component_item_code=component.item_code,
                    ),
                    tr(
                        (
                            "Short by {a_short} {unit} on {a_batch_number}. A supplier change "
                            "needs approval."
                        ),
                        a_short=_q(a.short),
                        unit=unit,
                        a_batch_number=a.batch_number,
                    ),
                    a.batch_id,
                )
            if a.held > 0:
                add(
                    "other",
                    tr(
                        "Get a quality decision on {a_held} {unit} held in {a_batch_number}",
                        a_held=_q(a.held),
                        unit=unit,
                        a_batch_number=a.batch_number,
                    ),
                    tr(
                        "{ref} needs {a_held} {unit} that quality has on hold.",
                        ref=ref,
                        a_held=_q(a.held),
                        unit=unit,
                    ),
                    a.batch_id,
                )
            if late and a.from_supplier > 0:
                add(
                    "expedite",
                    tr(
                        "Ask {a_supplier_name} to expedite {a_batch_number}",
                        a_supplier_name=a.supplier_name,
                        a_batch_number=a.batch_number,
                    ),
                    tr(
                        (
                            "{ref} is projected late; {a_from_supplier} {unit} is still to come "
                            "from {a_supplier_name}."
                        ),
                        ref=ref,
                        a_from_supplier=_q(a.from_supplier),
                        unit=unit,
                        a_supplier_name=a.supplier_name,
                    ),
                    a.batch_id,
                )
    if late and risk.operation_minutes > 0:
        add(
            "overtime",
            tr("Plan overtime or resequence in-house work for {ref}", ref=ref),
            tr(
                "{value} h of in-house work remains after the material arrives.",
                value=risk.operation_minutes // 60,
            ),
        )
    if late:
        state = (
            tr("past its promise") if risk.headline == "confirmed_late" else tr("projected late")
        )
        add(
            "promise_review",
            tr(
                "Review the promised date with {risk_customer_name}",
                risk_customer_name=risk.customer_name,
            ),
            tr(
                (
                    "{ref} is {state}. Changing the promise needs approval and is recorded "
                    "with a reason on the order."
                ),
                ref=ref,
                state=state,
            ),
        )
    return out
