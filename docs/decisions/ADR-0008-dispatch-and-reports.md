# ADR-0008: Dispatch against orders and the first operational reports

- **Status:** Proposed. Implemented in slice F8 as reversible defaults; product owner to confirm.
- **Date:** 2026-10-17

## Context

The first release must close the loop from commitment to dispatch outcome and show whether the team is finding risk earlier and chasing less (plan §5.10, §5.12; backlog §14, §15). The plan requires that "shipped quantity cannot exceed releasable accepted quantity unless an explicitly configured exception is approved and audited". There is no finished-goods stock yet (backlog §9).

## Decision

**Dispatch notes.**
- A dispatch note is numbered from the `dispatch` sequence (DN-) and belongs to one confirmed order at its site.
- It records the date, transporter, vehicle and LR/delivery-note reference, and one quantity per order line.
- The dispatch date cannot be in the future or before the order date.
- Posting raises each line's shipped quantity at once. A line with nothing left to ship becomes fulfilled, and an order with no open lines closes.
- A client submission key stops a repeated submission from posting twice.
- Each line keeps the promised date in force when it shipped, and whether it shipped on time.

**Releasable quantity.**
- There is no finished-goods stock record yet. A line's releasable quantity is therefore what can be built from the accepted outsourced material available to it, using the delivery-risk sharing rules of ADR-0006.
- The limit is the minimum, over its outsourced components, of accepted material ÷ quantity per unit, rounded down to the line's unit.
- Lines with no outsourced components are not checked, and the screen says so.

**Consumption.**
- Shipping uses up the accepted material behind it. The batch allocation's consumed quantity rises, so the same castings can never be counted for another order.
- When a line is fulfilled, whatever it still had earmarked in batches is released for other orders.

**Exceptions.**
- Shipping more than the releasable quantity needs an owner or administrator and a written reason. The reason is stored on the dispatch line and in the audit log.
- Only accepted material is consumed, even under an exception.

**Cancelling.**
- A posted dispatch is never edited. It can be cancelled with a reason by anyone who may dispatch.
- Cancelling reverses exactly what posting did: shipped quantities, consumption, released allocations, and line and order status.
- It is refused if a line was short-closed or cancelled since the dispatch.

**Who dispatches.** Owner, administrator, dispatch and stores roles (`dispatch:manage`).

**Reports.** One fulfilment report, limited to the user's sites, recalculated on request, with a written definition returned for every figure:
- on-time rate and days late (from dispatch lines against the promise in force);
- delivery by customer;
- open lines by risk headline now;
- stale supplier information, with the number of orders waiting;
- action ageing, closed actions and the median time to close;
- early warning: days between the first recovery action and the promised date, for lines shipped in the period.

The period defaults to the last 30 days, in the time zone of the user's first site.

## Assumptions to confirm

- The "releasable from accepted outsourced material" rule stands in for finished-goods stock until inventory exists.
- Overrides belong to owners and administrators. A separate dispatch-exception approver could replace this once approval limits (D8) are decided.
- Early warning uses the first recovery action as the moment the team knew. Risk history is not stored. If a true "first flagged" date is needed, risk snapshots would have to be kept.
- Delivery documents (e-way bill, tax invoice) are out of scope until finance and GST scope (D5) is decided.
