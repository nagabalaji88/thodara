# ADR-0006: How delivery risk is calculated

- **Status:** Proposed. Implemented in slice F6 as reversible defaults; product owner to confirm.
- **Date:** 2026-10-17

## Context

The first release must answer "will this customer order ship on time?" with the calculation visible (plan §5.9, backlog §11). Missing information must never become a fabricated delay. The plan names six classifications but leaves the calculation rules, the order in which shared material is given out, and the stale-update threshold open.

## Decision

**Calculated on read, never stored.**
- Risk is recomputed on every request from orders, dependencies, batch allocations, supplier updates, receipts, quality decisions and the site calendar. It therefore cannot drift from those records, and changing any of them changes the answer immediately.
- Nothing about risk is written back. A risk never changes a promise, an allocation or a batch.

**Scope.** Risk covers open lines of confirmed orders at the sites the user can access.

**Sharing a batch.**
- The lines allocated to a batch are served in order of promised date, then order number, then line number.
- Each line takes from the batch in this order:
  1. accepted material;
  2. material awaiting inspection;
  3. material on quality hold;
  4. what is still expected from the supplier.
- "Still expected from the supplier" is the quantity sent, minus what has been received, minus what the supplier reported as rejected. Supplier-rejected material is assumed not to come back usable.

**When material is expected.**
- The estimate for a batch, in order of preference:
  1. the supplier's latest revised date, which is labelled as entered by staff and not confirmed;
  2. otherwise the batch's planned return date;
  3. for a batch not yet sent, its planned return date, labelled as such.
- If the estimate is in the past and material is still outstanding, the date is unknown and nothing is projected.
- A line's material-ready date is the latest estimate among the parts it still needs. It is today when everything it needs is already accepted.

**Remaining work.** The line's remaining operations are added on the fulfilling site's calendar from the material-ready date. A site with no calendar gives an unknown projection.

**Classifications.** A line can carry several issues. Its headline is the most severe, in this order:

| Headline | When |
|---|---|
| Confirmed late | Today is after the promised date and the line is still open. This is a fact, not an estimate. |
| Quantity shortage | An outsourced need is not covered by any batch, or the batch is not expected to deliver enough. |
| At risk | The projected ready date is after the promised date. |
| Quality hold | Material the line depends on is on hold. |
| Unknown | No dependencies recorded; no site calendar; the supplier is stale; or an expected date has passed. |
| On track | Projected to finish by the promised date. |
| Ready | Every outsourced component the line needs is accepted and usable now. |

**Unknown is never late.** Stale or missing information produces "unknown". A projected date that relies on a stale update is still shown, so people can see the reasoning, but the headline stays "unknown". Supplier blockers are shown as evidence; free text never changes a classification.

**Stale threshold.**
- A batch at a supplier with no update for longer than the company's threshold is stale. The default is 48 hours, and owners and administrators can change it (1–720 hours) under Company & sites.
- With no update at all, the clock starts at the date the batch was sent.

## Assumptions to confirm

- Components that are not outsourced are not tracked, because there is no stock module yet (backlog §9). They are assumed available, and the screen says so.
- No time is added for inspection, collection from the supplier, or transport back. Only the remaining operations entered on the line are scheduled.
- Allocation priority is by promised date. Customer priority or manual overrides would be a later rule.
- Risk is computed for every open line on every request. This is fine at pilot scale but will need caching or incremental recalculation for large tenants.
