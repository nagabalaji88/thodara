# Delivery backlog

This is the tracked roadmap from the base to launch. It complements [`manufacturing-erp-product-plan.md`](manufacturing-erp-product-plan.md) (what and why) and [`production-build-plan.md`](production-build-plan.md) (how). Work proceeds one bounded slice at a time (AGENTS.md, plan §14). Update the status column in the same pull request that changes it.

**Status key:** ✅ done · 🟡 partial · ⬜ not started · ⛔ blocked by an open decision (see the end of this file)

## First release focus

The full ERP ambition stands, but the first release must prove one thing:

> **Will this customer order ship on time, and what should my team fix today when work is outside our factory?**

Differentiation comes from timely, trustworthy supplier information and effective recovery actions, not from breadth of ERP modules. Everything below is ordered by that question.

### The journey the first release must support

Customer commitment → required components/operations → outsourced batch → confirmed supplier update → receipt/quality status → delivery risk → approved recovery action → dispatch outcome.

### Capabilities that directly serve the question

| Capability | Why | Backlog section | Status |
|---|---|---|---|
| Customer orders and delivery commitments | Required quantity and promised date | §2 | ⬜ |
| Component and operation dependencies | Which outsourced work can block each order | §3 (minimal) | ⬜ |
| Outsourced batches and material movements | What was sent, where it is, what has returned | §7 | ⬜ |
| Simple supplier updates | Current quantities, blockers, revised dates | §7, §8 | ⬜ (portal ⛔ D2) |
| Receipt and quality acceptance | "Supplier finished" is not usable material | §10 (minimal) | ⬜ |
| Remaining operation times and calendars | Can coating, assembly, testing and transport finish in time | §1 calendars, §11 | ⬜ |
| Explainable delivery-risk calculation | Affected orders, shortages, dates, evidence, unknowns | §11 | ⬜ |
| Daily actions and recovery approvals | Who collects, expedites, reworks or evaluates alternatives | §12, §13 (minimal) | ⬜ |
| Freshness and audit history | When a status was confirmed, and by whom | §1 audit | 🟡 audit ✅, freshness with §7 |
| Operational reports | Earlier risk discovery, less chasing | §15 (reports only) | ⬜ |

### Focused base (only what the first release needs)

| Item | Status |
|---|---|
| Login, tenant and site permissions, user roles | ✅ (fixed role map; custom roles later) |
| Company and site configuration | ✅ |
| Customers, suppliers, items, units | ✅ |
| Working calendars | ✅ slice B2 (per site; a site without one reports dates as unknown) |
| Document numbering | ✅ slice B2 |
| Order and batch imports | ⬜ with F1 and F3 (import framework ✅) |
| Attachments | ⬜ local storage adapter first; production storage ⛔ D4 |
| Audit history and controlled changes | ✅ (before/after, provenance, version checks) |
| Reliable deployment, backups, monitoring | ⬜ ⛔ D4 |

### Slice order to the first release

| Slice | Delivers | Status |
|---|---|---|
| B2 | Working calendars per site (working days, shift hours, holidays) with deterministic date arithmetic; document numbering sequences | ✅ |
| F1 | Customer orders and lines: quantities, units, requested and promised dates, promise changes with reasons and history, confirm/cancel/short-close, CSV import | ⬜ |
| F2 | Fulfillment dependencies per order line: required components (quantity per unit) and operations (in-house or outsourced, supplier, duration), frozen per order line when confirmed | ⬜ |
| F3 | Outsourced batches: supplier, operation, quantity, expected return, material issue with challan reference, custody and movement history, CSV import | ⬜ |
| F4 | Supplier updates: completed / rejected / pending with reconciliation to batch quantity, blockers, revised dates, source label (manufacturer-entered until the portal), last-confirmed freshness | ⬜ (portal ⛔ D2) |
| F5 | Receipt against a batch and quality outcome (accepted / rejected / held / rework), kept separate from supplier-reported quantities | ⬜ |
| F6 | Explainable delivery risk per order line: usable quantity, shortage, remaining operation time on the site calendar, classification (confirmed late, at risk, unknown/stale, quantity shortage, quality hold, ready), shared-batch impact | ⬜ |
| F7 | Daily action inbox: owner, due time, recovery type, approval, supplier acknowledgement, outcome and follow-up | ⬜ |
| F8 | Dispatch outcome against the order and first operational reports (risk found early, stale updates, action ageing, on-time delivery) | ⬜ |
| R1 | Deployment, encrypted backups with a restore drill, monitoring and alerts | ⬜ ⛔ D4 |

### Acceptance scenario for the first release

A customer order depends on housing castings sent as one outsourced batch of 200 for coating. The supplier reports **120 completed, 20 rejected, 60 pending**. The application must answer, with visible inputs and sources:

1. **Which orders depend on that batch?** Every order line whose dependencies include the batch, with the quantity each needs.
2. **How much material is actually usable?** Only quantity physically received and accepted by quality. Reported-complete is not usable until then; the 20 rejected are never usable without an authorized rework outcome.
3. **What downstream work remains?** Remaining in-house operations (for example assembly and testing) and transport, with durations on the site's working calendar.
4. **Which commitments are threatened?** Each affected order line classified (at risk, quantity shortage, unknown/stale, confirmed late, ready), with the calculation shown. Missing information is shown as unknown, never as a confirmed delay.
5. **Who must act, by when?** A recovery action (collect the 120, expedite the 60, rework the 20, evaluate an alternative supplier) with an owner, due time and approval where required.
6. **Did the action improve the outcome?** The action's outcome is recorded, the risk is recalculated, and the report shows whether the order shipped on time.

### Deliberately later

General ledger, payroll, bank reconciliation, GST filing, subscription billing, advanced capacity optimisation, broad CRM, full purchasing (RFQs, PO approval chains), full inventory (bins, counts, valuation), legal entities, tenant-customisable roles, and the remaining ERP modules below. Build them when customers need them.

## Wider ERP roadmap

The sections below are the complete roadmap. Items already pulled into the first release are marked there as well.

## 1. Base (complete list)

The focused base above is what the first release needs; the rest of this table follows later.

| Area | Item | Status | Notes |
|---|---|---|---|
| Identity | Email/password sign-in, lockout, generic errors | ✅ | Foundation scaffold only (ADR-0001) |
| Identity | Invitations, email verification, password reset | ⛔ D3 | Needs login method, identity provider and email provider |
| Identity | Production login methods, MFA policy | ⛔ D3 | |
| Sessions | Opaque revocable sessions, CSRF, expiry | ✅ | |
| Sessions | Session/device list, revoke one, revoke all others | ✅ | Base slice B1 |
| Authorization | Fixed role map with deny-by-default | ✅ | ADR-0003 (proposed) |
| Authorization | Site scope for site-owned records | ✅ | Warehouses and sites today; every later site-owned record must use it |
| Authorization | Tenant-customisable role templates and permissions | ⬜ | Plan §2.3–2.4; adds sales, planner and shop-floor roles |
| Authorization | Approval limits | ⛔ D8 | Framework in §13; limits need owner policy |
| Authorization | Permission-based navigation | 🟡 | Actions hidden by permission; nav shows only built modules |
| Company setup | Company, plants/sites, warehouses, units | ✅ | Slice 1 |
| Company setup | Legal entities | ⬜ | Hierarchy in plan §2.1 |
| Company setup | Working calendars and holidays | ✅ | Slice B2. No default pattern is imposed; default holiday lists ⛔ D6. Breaks and overnight shifts not modelled yet |
| Company setup | Document numbering sequences | ✅ | Slice B2: sales orders, outsourced batches, dispatch notes; gap-free on commit, never backwards |
| Company setup | Locale settings (date/number format, language) | ⬜ | Languages ⛔ D6 |
| Audit | Audit events with request ID | ✅ | |
| Audit | Before/after values on master-data edits | ✅ | Slice 1 |
| Audit | Actor type, source channel, retained attribution for departed users | ✅ | Base slice B1. IP addresses are not stored; that needs a privacy/retention decision (D9) |
| Audit | Workspace switch and setup before/after audited | ✅ | Base slice B1 (former strict xfails) |
| Concurrency | Version checks against stale overwrites | ✅ | Master data; every later editable record must use it |
| Master data | Customers, suppliers, items, units, warehouses | ✅ | Slice 1 |
| Master data | Work centers / machines / resources | ⬜ | Needed by routings (§3) |
| Imports | Preview, row errors, all-or-nothing, safe re-run | ✅ | Customers, suppliers, items |
| Imports | Field mapping, downloadable error file, import history | ⬜ | Plan §8.4 |

## 2. Customer orders and delivery commitments — ⬜

Order list/search/detail; manual entry and validated import; customer reference, product revision, quantities, units, delivery address, attachments; requested and confirmed promise dates; shipment schedules and partial-delivery commitments; confirm, cancel, amend, authorized short-close; promise-date changes with reasons and history; links to production, procurement, quality and dispatch; outstanding quantity from actual transactions.

**Done when:** promised, fulfilled, cancelled and remaining quantities reconcile, and every promise change is attributable.

## 3. BOMs, routings and manufacturing configuration — ⬜

Product revisions with effective dates; BOM editor (components, quantities, units, conversions), approval and history; routing editor with sequence and dependencies; in-house / outsourced / purchased classification; yield, scrap, lead times; inspection checkpoints; work centers and calendars; approved suppliers per operation; version comparison and controlled amendment. Discrete routings and process recipes per ADR-0002.

**Rule:** a released work order keeps the BOM and routing version it was released with.
**Done when:** changing a current BOM or routing cannot silently change released work.

## 4. Production planning — ⬜

Demand view; material requirements from approved BOMs; available / reserved / expected / usable stock; shortages; proposed work orders, purchase requests and outsourced operations; planned dates from dependencies and calendars; required-by dates; feasibility with visible assumptions; planner review and release; replanning. Start with explainable lead-time planning, not finite-capacity optimisation.

**Done when:** a planner can explain why an order is feasible or at risk from the underlying requirements.

## 5. Work orders and shop-floor execution — ⬜

Work order list/detail and operation board; operator task view; mobile/tablet screen; start, pause, resume, complete, authorized reopen; good / rejected / scrap / pending quantities; downtime reasons; material requests and consumption; partial completion; controlled batch split/merge; handoffs; evidence; actual vs planned.

**Done when:** partial completion and rejection correctly affect downstream availability and customer-order progress.

## 6. Procurement and supplier management — ⬜

Purchase requests and approval; optional RFQs; PO creation, approval, amendment; supplier acknowledgement; supplier change proposals; approved capabilities; contacts and restricted commercial data; receipt schedules; partial receipts and balances; returns; history and performance.

**Rule:** a supplier's proposed change becomes a commitment only after the required acceptance.
**Done when:** every PO has a traceable commitment, received balance and change history.

## 7. Outsourced operations and job work — ⬜

Batch list/detail linked to work orders and customer orders; supplier, operation, quantity, material owner, expected return; material issue and outward challan references; transport and handover; supplier-reported completed / rejected / pending; revised dates; partial collection and return; receipt and inspection links; rework, shortages, authorized closure; custody history; last-confirmed time and source; approved alternative-supplier proposals.

**Rule:** supplier-reported completion, physical receipt and inspection-accepted quantity stay distinct.
**Done when:** every issued quantity is traceable through custody, return, inspection, rework or an authorized exception.

## 8. Supplier mobile portal — ⛔ D2

Short-lived, revocable, narrowly scoped access; only shared batches and permitted actions; mobile status/quantity form; blockers and revised dates; attachments; confirm before submit; acknowledgement and correction history; priorities and collection arrangements; manufacturer-entered phone updates labelled as such; duplicate-submission protection; expiry, replay, denial and rate-limit handling.

**Done when:** a supplier can update its assigned batch but cannot reach another supplier's work or the buyer's dashboard.

## 9. Inventory and stores — ⬜

Availability by item, site, warehouse, bin; on-hand / reserved / expected / in-transit / supplier-held / quality-held / usable; receipts, issues, transfers, returns, scrap, adjustments; reservations; counts and reconciliation; lot/batch/serial tracking; approved opening balances; ledger history; controlled reversal; negative-stock policy; unit conversion and precision.

**Rules:** postings are atomic; retries never post twice; posted history stays traceable; valuation waits for the accounting design.
**Done when:** balances reconcile to the ledger and cannot change through unaudited edits.

## 10. Receiving and quality management — ⬜

Receipt against PO or outsourced batch; partial receipt and discrepancies; inspection plans; measurements, tolerances, sampling, evidence; accepted / rejected / held / rework / partial outcomes; authorized hold release; nonconformances; corrective actions; rework and reinspection; supplier rejection history.

**Rule:** quality-held material never becomes usable or dispatchable through a normal progress update.
**Done when:** a quality decision updates usable supply and order risk while preserving inspection history.

## 11. Delivery-risk calculation — ⬜

Order-line dependencies; required accepted quantities; remaining processing, inspection, collection and transport time; working calendars; recalculation on updates, receipts, rejections and date changes; explainable inputs; classifications: confirmed late, at risk, unknown/stale, quantity shortage, quality hold, ready to move; shared-batch impact; partial-delivery feasibility.

**Done when:** the user can see why a risk exists, and missing information never becomes a fabricated confirmed delay.

## 12. Daily actions and recovery workflow — ⬜

Action inbox with priorities; affected orders and impact; owner, deadline, acknowledgement; recovery proposals (partial collection, expedite, overtime, rework, resequencing, approved alternatives); approval; supplier acknowledgement; escalation; closure evidence and outcome; history; follow-up on whether recovery worked.

**Done when:** an exception has an accountable owner and a recorded outcome.

## 13. Shared approvals framework — ⬜ (limits ⛔ D8)

Queue and detail; rules by transaction type, role, site, amount, quantity or exception; configurable limits; entry/approval separation; before/after comparison; approve / reject / return; reasons and history; reapproval after material amendment; no unauthorized self-approval.

**Done when:** no consequential transaction bypasses its approval rules through an API call or amendment.

## 14. Dispatch and delivery — ⬜

Readiness and shortages; pick and pack; lot/serial and packaging references; partial shipments; delivery notes and documents; carrier and dispatch time; delivery confirmation and proof; returns; remaining balance and closure.

**Rule:** shipped quantity stays within releasable accepted quantity unless an explicit exception is authorized.
**Done when:** an order is traceable from commitment through production and inspection to its shipments.

## 15. Documents, notifications and reports — ⬜

Documents: private storage, permitted access, validation, scanning, versions, short-lived links (storage provider ⛔ D4). Notifications: channels and providers ⛔ D3/D4, templates, history, retries, reminders, escalation, preferences, de-duplication. Reports: fulfillment, promised vs projected dates, shortages, batch ageing, stale updates, quality holds, action ageing, delivery performance, stock availability; authorized filters and exports, metric definitions, timezone handling, refresh timestamps.

**Done when:** each notification opens an actionable record and every reported number has a defined source.

## 16. Imports, exports and integrations — ⬜

Templates and field mapping; preview and dry run; downloadable error reports; duplicate handling and safe reruns; import history and job status; permission-controlled exports; external identifiers; connectors for pilot systems ⛔ D7; signed webhooks with retries, replay protection and delivery history; reconciliation.

**Done when:** a failed or repeated integration cannot create duplicate orders, receipts or stock postings.

## 17. Finance and India localization — ⛔ D5

Possible scope: chart of accounts and ledger, AP/AR, bills and invoices, payments and bank reconciliation, inventory valuation and costing, fiscal periods, GST / e-invoice / e-way bill / TDS, payroll. Decide what Thodara owns versus connects to; accounting and statutory scenarios need qualified review.

## 18. SaaS administration and commercial operations — ⛔ D1, D7

Tenant provisioning by the chosen onboarding model; plans and entitlements; trial, renewal, billing, cancellation; suspension and reactivation; export and retention; audited support access; support tooling and runbooks; tenant migration and upgrades.

**Done when:** a customer can be onboarded, supported, upgraded and offboarded through controlled workflows.

## 19. Production readiness — 🟡 (runs throughout)

| Item | Status |
|---|---|
| PostgreSQL integration tests in CI | ✅ |
| Role, tenant and site authorization tests | ✅ for built features; supplier tests with §8 |
| End-to-end order-to-dispatch tests | ⬜ |
| Concurrent-edit and transaction-failure tests | 🟡 version checks tested; failure injection not yet |
| Supplier link expiry/replay and duplicate-submission tests | ⬜ with §8 |
| Migration upgrade/downgrade checks in CI | ✅ |
| Dependency scanning and release controls | ⬜ |
| Structured logs, metrics, alerts, error reporting | ⬜ ⛔ D4 |
| Encrypted backups and restore drills, RPO/RTO, incident procedures | ⬜ ⛔ D4, D9 |
| Load tests | ⬜ |
| Mobile usability and accessibility checks | 🟡 layouts checked at phone width; no formal audit |

## 20. Later capabilities — ⬜

Advanced capacity scheduling, more manufacturing models, supplier scorecards, more connectors, more languages, AI document extraction / voice-to-draft / summaries / drafting. AI output stays a draft until a person confirms it; quantities, permissions, dates and approvals stay deterministic.

## Open decisions that block items above

| ID | Decision (plan §15 / build plan) | Blocks |
|---|---|---|
| D1 | Self-service vs sales-assisted onboarding | Public signup, §18 |
| D2 | Supplier authentication method (signed link + OTP, accounts, other) | §8 |
| D3 | Login methods, identity provider, email/OTP provider, MFA rollout | Invitations, reset, MFA, notifications |
| D4 | Cloud provider, region, data residency, budget | Hosting, storage, monitoring, backups |
| D5 | Finance / GST / e-invoice scope; own vs integrate | §17, tax fields |
| D6 | Languages, local calendar and holiday rules | Locale, default calendars |
| D7 | Pilot segment and systems to import from or connect to | Connectors, pricing validation |
| D8 | Workflow statuses and approval limits for the pilot | §13 limits, §12 |
| D9 | Availability, recovery, retention and export expectations | §19 recovery objectives |
