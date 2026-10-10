# ADR-0004: Fulfillment dependencies, outsourced batches and supplier-update rules

- **Status:** Proposed. Implemented in slices F2–F4 as reversible defaults; product owner to confirm.
- **Date:** 2026-10-10

## Context

The first release must answer whether a customer order will ship on time when part of the work happens at a supplier. Slices F2–F4 record what each order line depends on, the outsourced batches that serve it, and what suppliers report about those batches. The product plan (§5.6, §6.2, §6.3, §8) sets the direction: supplier-reported, received and inspection-accepted quantities stay separate; manufacturer-entered updates are labelled; missing information stays unknown. It does not set the exact defaults below.

## Decision

**Permissions (fixed role map, ADR-0003).**

| Permission | Roles |
|---|---|
| Read orders, dependencies, batches and supplier updates | every role, limited to the user's sites |
| Create, confirm, amend, short-close and cancel orders (F1) | owner, administrator |
| Edit an order line's dependencies (`orders:plan`) | owner, administrator, production manager |
| Create, allocate, send, close and cancel batches (`outsourcing:manage`) | owner, administrator, production manager, procurement |
| Record supplier updates (`supplier_updates:record`) | owner, administrator, production manager, procurement, production coordinator |

**Dependencies (F2).**
- There are no BOM or routing masters yet. Dependencies are entered per order line. They can be copied from the most recent line for the same item.
- A component states a quantity per unit of the line item. The quantity needed is that figure times the line's open quantity, rounded **up** to the component unit's precision.
- A component may name the outsourced step it needs (for example "Powder coating").
- The work that remains once components are ready (in-house steps and transport) is an ordered list of durations in working minutes on the site calendar.
- Dependencies can change on open lines of draft and confirmed orders. Every change is audited with before/after values.
- A component that a batch is allocated to cannot be removed until the allocation is removed.

**Outsourced batches (F3).**
- A batch is one item, one outsourced step, one job-work supplier and one quantity, at one site. It is numbered from the `outsourced_batch` sequence.
- The supplier must be active and marked as providing job work.
- Lifecycle: `planned` → `at_supplier` (sending records the challan reference and date as a custody movement) → `closed` or `cancelled`. Only planned batches can be cancelled. Closing a batch at the supplier needs a reason. Closing through receipts comes with F5.
- Allocations link a batch to the order-line components it serves.
  - The batch must be at the same site, and the component must be the same item.
  - The batch's allocations cannot exceed the batch quantity.
  - A component's allocations cannot exceed the quantity it still needs.
  - Batches are not shared silently: one batch can serve several order lines only through explicit allocations.

**Supplier updates (F4).**
- Until the supplier portal exists (decision D2), updates are entered by staff. They are stored with the source `manufacturer_entered`, the contact method and person, the time the supplier gave the information, and the state *supplier confirmation pending*.
- Every update states completed, rejected and pending quantities. Their sum must equal the batch quantity. Tolerances for over- or under-delivery are a later decision.
- A normal update cannot reduce the completed or rejected quantity reported earlier. Doing that requires a correction, which needs a reason and points to the update it corrects. History is never edited.
- A revised return date is the supplier's estimate. It does not overwrite the batch's planned return date, and it does not change any customer promise.
- Each submission carries a client-generated key. Repeating the same key returns the first result instead of recording a duplicate.
- Supplier-reported quantities are never treated as received or usable. Only receipts (F5) and quality acceptance make material usable.

## Consequences

- When BOM/routing masters arrive (backlog §3), order-line dependencies should be created from the released version and keep that version, as the plan requires for work orders.
- The supplier portal (§8) will add the source `supplier_portal` and confirmed states. It must not reuse the internal permission path.
- Freshness thresholds for stale updates are a tenant setting introduced with the risk calculation (F6). F4 shows only the age of the last update.
