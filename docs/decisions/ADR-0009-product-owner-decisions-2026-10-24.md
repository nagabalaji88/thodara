# ADR-0009: Product owner decisions on the open questions (D1–D9) and the proposed rules

- **Status:** Accepted (product owner, 2026-10-24)
- **Date:** 2026-10-24

## Context

After the first-release journey (F1–F8) was merged, the product owner answered the open decisions in the delivery backlog and the proposed defaults in ADR-0003 to ADR-0008, one question at a time. This record keeps those answers so later slices follow them. Where an answer was "later", the item stays open and is listed as such.

## Decisions

| Topic | Decision | Effect |
|---|---|---|
| D1 Onboarding | **Both:** sales-assisted set-up for pilots now; self-service trial sign-up later. | Public sign-up waits; pilots are created by us. |
| D2 Supplier sign-in | Preferred method: **short-lived link + one-time code**. No paid SMS/WhatsApp channel is approved, and the zero-cost alternative (staff share the link and a PIN) was **deferred**. | Staff keep entering supplier updates (ADR-0004). The supplier portal stays open until a delivery channel is chosen. |
| D3 Staff sign-in | **Email + password for everyone, plus Google / Microsoft sign-in** for companies that want it. | The identity slice adds OAuth/OIDC sign-in alongside passwords. |
| D3 Two-step verification | **Required for owners and administrators**, optional for others, using a **free authenticator app (TOTP)**; nothing is sent by SMS or email. | MFA slice uses TOTP; no paid provider. |
| D3 Notifications | **In-app only for now.** | No email, SMS or WhatsApp provider yet; My work and Actions remain the notification surface. |
| D4 Hosting | **Decide later**, before a real pilot. Zero-cost options considered: Oracle Cloud Always Free (India region), an office PC, cloud trial credits. | R1 stays blocked; demos run locally. |
| D5 Finance / GST | **Connect to Tally / Zoho Books**; Thodara stays the operations system. | No ledger or GST returns in Thodara; a later export connector. |
| D6 Languages | **English and Tamil, on every screen**, chosen per user. | A localisation slice translates the whole interface; new screens must carry Tamil text. |
| D6 Holidays | **Each site's administrator enters its own holidays** (as built). | No default holiday lists. |
| D7 Pilot segment | **Auto parts / engineering and pumps / motors assembly.** | Acceptance tests follow outsourced coating, plating, heat treatment, machining and castings for assembled products. |
| D7 Pilot systems | **Open.** | Connectors wait. CSV import remains the way in. |
| D8 Receive and inspect | **One person may do both, but it is flagged** in history and reports. | Small rules slice. |
| D8 Approval limits | **One approver (never the proposer) is enough** for the pilot. Amount or quantity limits come later. | ADR-0007 stands. |
| D9 Recovery targets | **Decide together with hosting.** | Open with D4. |
| D9 Retention | **Keep records for 8 years.** | No deletion of business records or audit history before 8 years; archiving is a later feature. |

## Changes to the proposed rules

| Rule | Was | Now |
|---|---|---|
| Supplier figures must reconcile (ADR-0004) | Completed + rejected + pending must equal the quantity sent exactly. | **Tolerance of ±2% by default, set per company**; any difference is shown as unaccounted. |
| Sharing a batch (ADR-0006) | Earliest promised date first. | Earliest promise first, **plus a planner's manual priority with a reason, audited**. |
| Stale threshold (ADR-0006) | 48 hours default, per company. | **Confirmed.** |
| Components not outsourced (ADR-0006/0008) | Assumed available. | **Build basic stock next**, so risk and dispatch can use real on-hand quantities. |
| Shipping beyond accepted material (ADR-0008) | Owner or administrator with a reason. | **Requested by the dispatcher and approved by someone else** before shipping. |
| Role permissions (ADR-0003–0007) | Fixed role map. | **Companies can customise roles before the pilot.** The fixed map becomes the default template. |

## Agreed order of work

1. **Rules slice:** the ±2% tolerance, manual batch priority, approval for shipping exceptions, and the "received and inspected by the same person" flag.
2. **Basic stock** per item and site, used by risk and dispatch.
3. **Company-customisable roles.**
4. **Tamil** for every screen.

## Still open

- D2 delivery channel for supplier links and codes.
- D4 hosting.
- D7 pilot systems.
- D9 recovery targets.
- Approval limits.
- Notifications beyond in-app.
