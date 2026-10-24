# ADR-0007: Recovery actions, approvals and follow-up

- **Status:** Accepted with changes in ADR-0009 (2026-10-24). Originally proposed. Implemented in slice F7. Approval limits remain open (ADR-0009).
- **Date:** 2026-10-17

## Context

Once delivery risk is visible (F6), the team must decide who does what, by when, and whether it worked (plan §5.9, §12, §13). AGENTS.md requires authorized human approval for quality, commercial and supplier-change decisions, and requires AI or automatic suggestions to stay drafts until a person confirms them. Approval limits by amount or quantity are decision D8 and are not decided here.

## Decision

**Actions.**
- An action is linked to an open line of a confirmed order, or to an active batch, or both. When both are given, the batch must serve that line.
- It has a kind:

  | Kinds | What they cover |
  |---|---|
  | chase update, collect, expedite | supplier follow-up |
  | overtime, resequence | in-house work |
  | rework, alternate supplier, promise review | consequential decisions (see Approval) |
  | other | anything else |

- It also has a title, details, one owner and a due time. The due time must be in the future and within a year.
- The line's risk is stored as it was when the action was raised, and again when the action is closed. The before/after comparison shows whether recovery worked.

**Suggestions.**
- Rules derive suggested actions from the risk calculation:
  - stale or past-date batch → chase the supplier;
  - completed at the supplier but not received → collect;
  - a batch short because of rejections → rework or an alternate supplier;
  - an uncovered need → an alternate supplier;
  - material on hold → a quality decision;
  - projected or confirmed late → expedite, overtime, or a promise review.
- Suggestions are drafts. Nothing is created until a person creates the action.

**Who.**

| Permission | Roles |
|---|---|
| See actions (site-scoped) | every role |
| Create, reassign, record supplier acknowledgement (`actions:manage`) | owner, administrator, production manager, production coordinator, procurement, stores, quality, dispatch |
| Approve or reject (`actions:approve`) | owner, administrator, approver |

- The owner must be an active colleague who has `actions:manage` and access to the action's site.
- Only the owner can acknowledge.
- Only the owner, the person who raised the action, or an owner/administrator can close or cancel it.

**Approval.**
- Rework (a quality decision), alternate supplier (a supplier change) and promise review (a commercial decision) start as *awaiting approval*.
- They can be approved or rejected only by someone else with approval rights. Nobody approves their own proposal.
- They cannot be closed until approved.
- Approving an action records the decision only. It does not change suppliers, promises or quality outcomes. Those changes are still made through their own audited screens: change promise with a reason, a new batch, or a quality release.

**Supplier acknowledgement.** Recorded by staff with the contact method and person, labelled as entered by staff, until suppliers can confirm for themselves (decision D2).

**History.** Every step is kept as an immutable event and also written to the audit log: created, approved, rejected, acknowledged, supplier acknowledged, reassigned, completed, cancelled.

## Open points

- **D8:** approval limits by amount or quantity, multi-step approvals, and escalation of overdue actions.
- Notifications (email, WhatsApp, push) for new, overdue or approval-pending actions wait on D3/D4. For now, actions are visible on My work and the Actions page.
- Closing an action does not move material or change any record. Receipts, promise changes and supplier changes stay in their own screens.
