# ADR-0005: Receipts from suppliers and quality decisions

- **Status:** Proposed. Implemented in slice F5 as reversible defaults; product owner to confirm.
- **Date:** 2026-10-10

## Context

A supplier saying work is complete does not make material usable (plan §5.6, §5.8, §10). The first release needs to know how much of an outsourced batch is physically back and how much quality has accepted, so that delivery risk (F6) can be calculated from usable quantities only. Inspection plans, sampling, measurements and nonconformance records (backlog §10) are larger than this first step.

## Decision

**Permissions (fixed role map, ADR-0003).**

| Permission | Roles |
|---|---|
| Record a receipt (`receipts:record`) | owner, administrator, stores |
| Record an inspection or release a hold (`quality:decide`) | owner, administrator, quality |

**Receipts.**
- A receipt is recorded only against a batch at the supplier.
- It states the quantity, the date and the supplier's document number.
- It adds a "received from supplier" custody movement.
- Receipts across a batch cannot exceed the quantity sent.
- The date cannot be in the future or before the batch was sent.
- A client submission key stops a repeated submission from creating a second receipt.

**Quality.**
- Each receipt is inspected once.
- The inspection splits the received quantity into accepted, rejected, on hold and rework, and the four must add up to the received quantity.
- Anything not accepted needs findings.
- Held material can be released, in part or in full, into accepted, rejected or rework, with a reason.
- Every inspection and release is kept as an immutable decision with the person and time.

**Usable quantity.**
- Only accepted quantity is usable.
- Received material awaiting inspection is not usable, nor is material on hold, in rework or rejected.
- Supplier-reported figures (F4) stay alongside, unchanged.

## Open points

- Nothing prevents the person who recorded a receipt from also inspecting it when they hold both roles (owner/administrator). Separation of duties belongs to the approvals framework (backlog §13, decision D8).
- What happens to rework (returned to the same supplier, a new batch, or in-house) is a recovery action for F7. Rework quantity is not usable until then.
- Inspection plans, sampling, measurements and nonconformance records remain backlog §10.
- Stock postings to warehouses wait for the inventory design (backlog §9). Receipts here record custody and quality, not stock balances.
