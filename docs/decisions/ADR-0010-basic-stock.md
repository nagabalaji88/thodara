# ADR-0010: Basic stock per warehouse, used by delivery risk and dispatch

- **Status:** Accepted (product owner, 2026-10-24). Implemented in slice G2.
- **Date:** 2026-10-24

## Context

ADR-0009 decided to build basic stock next, so that delivery risk and dispatch use real on-hand quantities instead of assuming non-outsourced components are available (ADR-0006) and limiting shipments only by accepted batch material (ADR-0008). The product plan (§5.7) asks for stock-impacting transactions that are atomic, permission checked, idempotent and linked to a source, and for negative stock to be disallowed by default. Lots, serials, bins, transfers, reservations, counts, unit conversion and valuation are out of scope for this slice.

## Decisions (product owner, 2026-10-24)

| Question | Decision |
|---|---|
| Where stock is held | **Per warehouse.** Screens and delivery risk add warehouses up per site. |
| Who approves entries | **A second person approves opening balances and adjustments.** Receipts and issues post straight away. Everything is audited and reversed only by a counter-entry. |
| How dispatch uses stock | **Finished goods first, then components.** Ship from finished-goods stock of the line's item; beyond that, allow what can be built from component stock plus accepted batch material, and use those components up when it ships. |
| Negative stock | **Never.** An entry, approval or dispatch that would take a warehouse below zero is refused. |

## Rules

**Ledger.**
- Every change is a stock movement: `opening`, `receipt`, `issue`, `adjustment`, `dispatch` or `reversal`. It records the warehouse, its site, the item, a signed quantity in the item's base unit (checked against that unit's decimal places), the date, a reason and reference, who entered it and when, and the balance after posting.
- Movements are never edited or deleted. A posted opening, receipt, issue or adjustment can be reversed with a reason, which creates an opposite `reversal` movement. A movement can be reversed once. Dispatch movements are reversed only by cancelling the dispatch.
- The current balance per warehouse and item is kept in a balance row that is updated with each posting under optimistic locking. A database check stops it going below zero.
- Each entry carries a client-generated submission key; repeating it returns the first result.

**Approval.**
- Opening balances and adjustments (and reversals of them) wait for approval. Someone with `stock:approve` who did not enter it approves it, with an optional note, or rejects it, with a reason. Only approved entries count.
- Approval re-checks the balance at that moment, so an approval that would take stock below zero is refused.
- An item can have one opening balance per warehouse (pending or posted).

**Permissions (default roles; G3 makes them customisable).**

| Permission | Roles |
|---|---|
| See balances and movements (`stock:read`) | every role, limited to the user's sites |
| Enter receipts, issues, opening balances, adjustments, reversals (`stock:record`) | owner, administrator, stores |
| Approve or reject opening balances and adjustments (`stock:approve`) | owner, administrator, approver; never one's own entry |

**Which items are tracked.**
- An item is stock-tracked at a site once a movement for it has been posted at any warehouse of that site. Until then, Thodara has no stock figure for it, and delivery risk keeps assuming it is available and says so. This lets a company start with the items that matter without every other line turning into a shortage.

**Delivery risk (changes to ADR-0006).**
- Stock is not reserved. Each site's on-hand quantity of an item is shared among open lines of confirmed orders at that site, in order of promised date, then order number and line number.
- First, finished-goods stock of the line's item covers what it can of the line's remaining quantity.
- The rest of the line must be built. Component needs are worked out on that rest only (quantity per unit × rest, rounded up).
- Components without an outsourced step or batch allocation are then covered from the site's stock of the component item, in the same order. A tracked component with too little stock is a quantity shortage, naming the lines served first.
- Outsourced components keep using batch allocations only; stock of the same item is not counted for them, because the stock may not have had the outsourced step.
- A line fully covered by finished goods needs only its transport steps, and is ready.

**Dispatch (changes to ADR-0008).**
- A line can ship its share of finished-goods stock plus what can be built from its tracked components (accepted batch material and component stock). Lines with nothing tracked are not checked, as before.
- Posting uses up finished-goods stock first, then the components for the rest, from the warehouses of the dispatch site with the most stock first. Each use is a `dispatch` movement linked to the dispatch note.
- An exception (approved by someone else, ADR-0009) can ship beyond that, but uses up only what is there; stock never goes below zero.
- Cancelling a dispatch posts reversals that put back exactly what it used.

## Consequences

- Purchase receipts, production output and transfers will post through the same ledger when those modules arrive.
- Reservations can replace the promised-date sharing once planning needs them.
- Inventory valuation waits on the finance design (D5: Tally / Zoho).
