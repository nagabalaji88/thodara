# Manufacturing ERP SaaS — Product and Implementation Plan

**Purpose:** A complete, implementation-ready plan for an India-first, hosted SaaS ERP for manufacturing businesses. The system is designed around a configurable shared core rather than one factory type. The first differentiating workflow is end-to-end customer-order fulfillment visibility, including outsourced operations, supplier updates, risk, and recovery actions.

**Decisions confirmed by the product owner**

- Product direction: full ERP, not only an ERP overlay.
- Customer scope: manufacturing businesses broadly; shared core first, with workflows configurable or added as modules.
- Deployment: hosted SaaS.
- Launch market: India first.
- Stack-selection approach: choose for simplicity and scale; do not inherit a stack by default.

**Decisions still open:** supported manufacturing models in the first paid release; self-service or sales-assisted tenant creation; authentication options and identity provider; initial cloud provider and data-residency requirements; accounting/GST/e-invoice scope and compliance integrations; supported languages; billing/pricing; and first pilot segment. Do not implement these as hidden assumptions. Use the decision gates in this plan.

---

## 1. Product definition

### 1.1 Product promise

Give a manufacturer one reliable operating system for turning customer demand into completed, inspected, and dispatched orders. The system must answer:

1. What is promised, in what quantity, and by when?
2. What has been planned, purchased, issued, produced, outsourced, inspected, and dispatched?
3. Which materials, operations, suppliers, machines, approvals, or quality holds threaten the commitment?
4. What is the next action, who owns it, and by when?
5. What is confirmed, what is estimated, and when was the source last confirmed?

The first product advantage to test is a dependable order-to-dispatch view that joins internal progress and supplier-reported progress to customer commitments, then drives owned recovery actions. Do not claim this is a market gap until customer discovery and pilots prove it.

### 1.2 Product boundary

This is a full ERP roadmap, but it must ship in releases. Its system of record eventually includes customer/supplier masters, sales, procurement, inventory, manufacturing, quality, dispatch, and finance. The first release should not pretend to provide complete accounting, statutory compliance, finite-capacity planning, or every manufacturing model before those requirements are validated.

### 1.3 Product principles

- One business event should be entered once and reused by connected modules.
- Quantities, dates, and status must retain their source, timestamp, unit, and audit history.
- “Unknown” or “stale” must not be silently converted to “late,” “complete,” or “accepted.”
- Suppliers should be able to report progress with low friction and see only their own assigned work.
- Users must be able to understand why the system shows a shortage, delay, or risk.
- The customer configures process differences; code should not hard-code a pump factory’s routing.
- Human approval is required for material state changes with commercial, quality, or supplier consequences.
- Use deterministic business rules for quantities, accounting, access, approvals, and date calculations. AI may assist with drafts and summaries but never silently post transactions.

---

## 2. Users, organizations, and permissions

### 2.1 Tenant hierarchy

Use the following hierarchy from the beginning:

`SaaS platform → tenant/company → legal entity → plant/site → warehouse/location → department/team`

A small customer may have one company, one plant, and one warehouse. The data model must still support multiple legal entities and sites without duplicating users. Supplier accounts are external identities associated with one or more supplier records and are not members of the buyer’s tenant.

### 2.2 User types

- **Platform operator:** manages SaaS service health and support access; no routine access to customer business data.
- **Tenant owner:** owns subscription and tenant configuration; can appoint tenant administrators.
- **Tenant administrator:** manages users, sites, master data, policies, integrations, and imports.
- **Business roles:** sales, production planning, procurement, stores, shop floor, quality, dispatch, finance, and management.
- **Approver:** approves configured transactions or exceptions within assigned limits and sites.
- **Read-only/auditor:** sees authorized records and history without changing them.
- **Supplier user:** sees and updates only explicitly shared purchase orders/batches and supplier-facing documents.

### 2.3 Authorization model

Use role-based access control with scope attributes. A permission check must include:

`user + tenant + role + action + module + record/site scope + record state + approval limit`

Support at least `view`, `create`, `edit`, `submit`, `approve`, `cancel/reopen`, `export`, and `admin` separately. A user who can enter a purchase order should not automatically be able to approve it. Configure amount/quantity limits and site scope. Deny by default.

Provide role templates, then let tenant administrators customize them. Keep immutable platform-level protection for tenant boundaries and security settings.

### 2.4 Minimum role templates

| Role | Typical access | Restricted actions by default |
|---|---|---|
| Tenant owner/admin | Company setup, users, configuration, all tenant modules | Cannot read another tenant; support access is separately controlled and audited |
| Sales | Customers, quotations, sales orders, order status | Cannot post inventory or approve own discounts above limit |
| Production planner | Demand, BOM/routing, production plans, work orders, capacity and exceptions | Cannot change posted finance or quality dispositions |
| Procurement | Supplier records, RFQs, POs, outsourced operations, supplier follow-up | Cannot approve own high-value PO unless policy allows |
| Stores | Receipts, issues, transfers, stock counts, batch/serial data | Cannot alter submitted source documents without amendment flow |
| Shop-floor operator | Assigned operations, start/stop, good/reject quantities, downtime | Cannot see cost, customer pricing, unrelated orders, or edit routing |
| Quality inspector | Inspection plans, results, holds, release/reject/rework decisions | Cannot release a hold without required checks and authority |
| Dispatch | Packing, shipment, delivery notes, dispatch confirmation | Cannot change order price or inspection results |
| Finance | Bills, invoices, payments, ledgers, tax reports | Cannot alter production history or quality disposition |
| Manager/approver | Dashboards and approval queues for assigned sites/limits | No blanket edit access unless granted |
| Supplier user | Shared PO/batch status and supplier response | No internal cost, other suppliers, customer details beyond what is needed, or tenant-wide search |

### 2.5 Login and account security

Provide a secure login flow with:

- Email or username plus password; verified email before activation.
- Password reset using a single-use, short-lived token; do not reveal whether an account exists.
- Optional MFA at initial release, and mandatory MFA for tenant administrators/finance approvers before production launch.
- Session expiration, revocation of all sessions, device/session list, CSRF protection for cookie sessions, rate limiting, and brute-force controls.
- Secure password hashing using a current, maintained password-hashing algorithm and library; no custom cryptography.
- Login, logout, failed-login, password-reset, MFA, invitation, and role-change audit events.
- Generic error messages, accessible forms, and no secrets in URLs, browser storage, logs, or analytics.
- Optional SSO as a later capability; choose identity providers only after customer discovery.

### 2.6 Supplier authentication

Do not use an unrestricted permanent bearer link. For low-friction supplier updates, issue a short-lived, revocable, narrowly scoped link or OTP challenge tied to a supplier, batch, and permitted actions. Rate-limit and audit it. Do not expose the buyer’s tenant dashboard or unrelated commercial information. An internal user may record a phone update, but the system must label it **manufacturer-entered, supplier confirmation pending** until acknowledged.

---

## 3. Sign-up, tenant creation, and onboarding

### 3.1 Public entry and tenant creation

The public entry points are `Sign in`, `Create account/request access`, and `Supplier update`. Keep them distinct so supplier users cannot accidentally create buyer tenants.

Tenant creation should support two configurable modes:

1. **Self-service trial:** email verification, owner account, tenant creation, terms/privacy consent, and guided setup.
2. **Sales-assisted onboarding:** platform operator provisions a tenant and sends a single-use owner invitation.

Which mode launches first is an open business decision. Both modes must call the same tenant-provisioning service and audit trail.

### 3.2 Guided first-run setup

Show a resumable checklist with progress and a way to skip nonessential items:

1. **Company:** legal/display name, address, country, default language, time zone, fiscal year, base currency.
2. **Legal entity and tax:** registration identifiers and tax settings only after the required compliance scope is confirmed. Never infer tax registrations.
3. **Plant/site:** site name, address, operating hours, working week, holidays, and escalation contacts.
4. **Units and numbering:** units of measure, conversion rules, document prefixes/sequences, date/number formatting.
5. **People and roles:** invite users, assign role templates, set site scope and approval limits.
6. **Master data:** import items, customers, suppliers, BOMs/routings, warehouses, and opening balances using validated templates.
7. **Workflow configuration:** select enabled manufacturing capabilities and configure statuses, approval rules, and alert cadence.
8. **Integrations:** configure approved import/export or ERP connectors; secrets must be stored in a secrets manager.
9. **Sample walkthrough:** use clearly marked sample records in a sandbox; never insert demo data into live company transactions.
10. **Go-live checks:** reconcile balances and open orders, validate permissions, confirm backups and notification routing, then record go-live approval.

The user can leave and resume onboarding. Each step should explain its impact, validate fields inline, save drafts safely, and show unresolved blockers before enabling production use.

### 3.3 User invitations and lifecycle

An admin invites by email with tenant, role, site scope, and expiry. The invitee verifies email, sets credentials/MFA as policy requires, reviews their assigned access, and accepts. Admins can suspend/reactivate accounts, revoke sessions, change roles, and review access history. Terminated users must lose active sessions immediately; their authored transactions remain attributable.

---

## 4. Application navigation and screen inventory

### 4.1 Main navigation

Use a responsive desktop-first ERP shell that remains usable on tablets and mobile:

- **Home / My work**
- **Sales**
- **Planning & production**
- **Procurement & suppliers**
- **Inventory & stores**
- **Quality**
- **Dispatch**
- **Finance** (released only when accounting scope is implemented and validated)
- **Reports**
- **Approvals**
- **Administration**

Show only permitted modules. Include global search over authorized records, site/company switcher where applicable, notification center, help, profile, and keyboard-accessible navigation.

### 4.2 Required screens

1. Sign-in, forgot/reset password, MFA setup/challenge, invitation accept, access-denied.
2. Tenant request/create, email verification, first-run setup wizard, onboarding checklist.
3. My work/action inbox, daily order-risk board, alert/exception detail.
4. Customer and supplier lists/details; item/product and unit masters.
5. Sales order list/detail with promise dates, line quantities, shipment schedule, documents, and timeline.
6. Production plan, BOM/routing editor, work-order list/detail, operation board, shop-floor tablet/mobile operation view.
7. Purchase request/RFQ/PO list/detail; supplier confirmation and outsourced-batch detail/update view.
8. Inventory availability, warehouse/bin, receipts, issues, transfers, stock count, lot/batch/serial trace.
9. Quality plans/checklists, inspection entry, nonconformance, hold/rework/release history.
10. Packing, dispatch/delivery note, shipment status and proof of delivery where required.
11. Approval queue and transaction comparison view before approval.
12. Reports and saved filters.
13. Admin: users/roles, sites, calendars, workflow configuration, import/export, integrations, notifications, audit search, subscription/account settings.
14. Supplier mobile view: request context, quantity/status form, blocker/revised-date fields, attachment, acknowledgement, confirmation result.

### 4.3 Core user experience rules

- Every list has search, filters, sort, saved views, pagination, export permission checks, and clear empty/loading/error states.
- Every detail page shows current status, next action, owner, date, related records, documents, and chronological history.
- Destructive or irreversible actions require an explicit confirmation and reason; submitted records use amendment/reversal workflows, not silent edits.
- Show units alongside every quantity and currencies alongside every amount.
- Use plain status labels, text plus color, keyboard support, responsive tables/cards, and accessible contrast.
- Mobile screens prioritize supplier updates, approvals, receipts, shop-floor operations, and dispatch confirmations.

---

## 5. ERP functional modules

### 5.1 Shared foundation and master data

Master records include tenant, legal entity, site, department, user, role, customer, supplier, item/product, service, unit of measure, warehouse/bin, work center/resource, calendar, currency, document type, attachment, and configurable code/number sequence.

Requirements:

- Unique codes within configured scopes; duplicate detection; active/inactive lifecycle.
- Unit conversions with precision and rounding policies; never add unlike units.
- Effective dates/versioning for BOMs, routings, supplier approvals, and product revisions.
- Import preview, field mapping, validation report, duplicate policy, dry-run, idempotent re-run, and rollback strategy.
- Opening balance entry must preserve source date, unit, location, lot, and approval.

### 5.2 Sales and customer commitments

Workflow: lead/quotation (optional early release) → customer order → confirmation/approval → fulfillment planning → shipment schedule → delivery → closure.

Sales order lines include product/service, revision, ordered quantity, unit, requested/promised dates, price/discount where in scope, customer reference, delivery location, shipment splits, and documents. Support partial deliveries and revised promise dates with reasons and history. Do not let production risk silently alter a customer promise. Report order status based on linked supply/production/quality/dispatch records.

### 5.3 Planning and manufacturing configuration

The shared core must allow configurable products, BOMs/recipes, routings, operation dependencies, in-house/outsource/buy classifications, expected yields/scrap, lead times, and inspection checkpoints. Version and approve changes; existing released work orders must retain the version used.

Planning creates demand and proposed work/purchase/subcontract actions. Before release, show material shortages, capacity limitations if capacity data exists, due-date feasibility, and assumptions. Early scheduling may be finite/basic depending on validated pilot needs; do not present rough lead-time math as optimized scheduling.

### 5.4 Work orders and shop-floor progress

Each work order links demand, product revision, quantity, planned dates, BOM/routing version, site, and owner. Each operation has sequence/dependencies, resource/vendor, planned and actual quantities, planned and actual dates, status, reason codes, and evidence.

Shop-floor users need a fast assigned-task view to start/stop, report good/rejected/scrap quantities, record downtime/reason, request materials, attach evidence, and hand off to the next operation. Enforce allowed transitions and quantity bounds. Support partial completion and split/merge batches through explicit transactions.

### 5.5 Procurement and supplier management

Supplier records include contacts, approved scope/capabilities, lead-time assumptions, certifications/expiry if required, payment/commercial details under restricted roles, performance history, and site-specific preferences.

Workflow: purchase request → optional RFQ/quotes → comparison → approval → PO → supplier confirmation/change request → receipt/service completion → invoice matching (later finance scope).

Supplier changes to dates/quantities/prices are proposals until accepted/approved according to policy. Keep acknowledgements and document versions.

### 5.6 Outsourced operations and job work

An outsourced batch is a tracked operation tied to a work order and customer demand. Track material issued, challan/document references, dispatch to supplier, supplier-reported quantities, rejected/pending quantities, revised completion/return dates, received quantities, inspection outcome, rework, and closure.

Support multiple partial updates and receipts; reconcile cumulative quantities against the batch quantity and configured over/under tolerances. Do not equate completed by supplier with received or inspection-accepted. Show supplier, material owner, operation, sent/returned quantities, last confirmed time, document evidence, downstream dependencies, and action history.

### 5.7 Inventory and stores

Provide item availability by site/warehouse/bin and distinguish on-hand, reserved, expected, in-transit, supplier-held, quality-held, and usable quantity. Track lots/batches/serials when configured. Support receipts, issues, transfers, returns, scrap, adjustments, cycle/stock counts, reservations, and traceability.

Each stock-impacting transaction must be atomic, permission checked, idempotent where integration retries are possible, and linked to a source document. Enforce negative-stock policy per tenant/site; default should be disallow pending customer validation. Inventory value/accounting treatment requires accounting design and must not be approximated.

### 5.8 Quality management

Support configurable inspection plans by product, supplier, operation, and receipt; sampling rules; measurement/unit/tolerance; result/evidence; inspector; decision; and timestamp. Outcomes include accepted, rejected, partial acceptance, hold, rework, and concession if policy allows. A hold blocks downstream consumption/dispatch until authorized release. Link nonconformance to source batch/order/supplier and corrective action.

### 5.9 Order risk, alerts, and recovery actions

The system evaluates an order against required quantities and remaining dependency steps. Classify issues separately:

- **Confirmed late:** a trusted confirmed date or event breaches the required-by date.
- **At risk:** current estimates leave insufficient time or quantity for downstream steps.
- **Unknown/stale:** required update is missing or past freshness threshold.
- **Quantity short:** projected accepted quantity is below required quantity.
- **Quality hold:** usable quantity is withheld pending decision.
- **Ready to move:** accepted material/work is waiting for pickup or next operation.

Each issue shows evidence, calculation inputs, confidence/unknown fields, affected customer orders, next action, owner, deadline, approval requirement, acknowledgement, and closure result. Alert cadence and escalation are tenant configurable and must prevent notification storms. Every alert links to an actionable record.

Recovery proposals can include partial shipment/collection, expedite, rework, overtime, resequence, approved alternate supplier, or customer promise review. The system records a proposal; authorized humans decide. It must not switch vendors, promise dates, release holds, or alter committed quantities autonomously.

### 5.10 Dispatch and delivery

Support pick/pack readiness, shortages/holds, shipment splits, packaging/serial/lot references, delivery note, carrier/reference and dispatch time, proof of delivery if needed, and delivery closure. Ensure shipped quantity cannot exceed releasable accepted quantity unless an explicitly configured exception is approved and audited.

### 5.11 Finance and India localization

“Full ERP” requires accounting design, but statutory behavior is high risk and needs dedicated validation before implementation. The plan must explicitly decide whether first release includes general ledger, chart of accounts, AP/AR, bank reconciliation, inventory valuation, GST returns, e-invoicing, e-way bills, TDS, payroll, or integrations with existing accounting tools.

Keep tax rules, document formats, fiscal periods, rounding, and compliance integrations localized and versioned. Obtain review from qualified India accounting/tax professionals and validate against current official requirements before claiming compliance. Do not hard-code a tax rate or represent a report as statutory-ready without that review.

### 5.12 Reports and dashboards

Start with operational reports: order fulfillment status, promised versus projected delivery, open shortages, outsourced work by supplier/age, stale update list, quantity variance, inspection holds/rejections, action ageing, on-time delivery, and stock availability. Provide filters by date/site/product/customer/supplier and role. Every metric must have a documented definition, timezone, and source; show the timestamp of the data refresh.

---

## 6. End-to-end workflows

### 6.1 Customer order to dispatch

1. Sales records and confirms order quantity, product revision, and promised date.
2. Planner creates/links a production plan and checks materials, operations, dependencies, and due-date feasibility.
3. Planner releases work and purchase/subcontract actions under approval rules.
4. Stores issues available material; quantities are reserved and traced.
5. Internal operators and suppliers report progress against assigned work.
6. System reconciles quantities and refreshes affected order risks.
7. Quality inspects returns/in-process/final product and applies holds/dispositions.
8. Team assigns, acknowledges, and closes recovery actions when exceptions arise.
9. Dispatch packs and ships only releasable quantity, recording split shipments and evidence.
10. Order closes when quantities are delivered or an authorized cancellation/short-closure is recorded.

### 6.2 Supplier reports a short batch

Supplier link presents only the batch and fields required. Supplier submits completed, rejected, pending quantities, blocker, and revised date. Server validates batch scope, token/OTP, units, quantities, dates, and duplicate submission key. Update is stored as a supplier-reported event, not a stock receipt. Affected customer orders are recalculated. The board creates or updates a risk/action. Manufacturer reviews and records the recovery decision. Supplier acknowledgement is captured. Material is only treated as received after a receipt transaction; it is only treated as usable after applicable quality disposition.

### 6.3 Manual/phone status

Employee selects batch → enters supplier-reported details and contact method/time → marks confirmation state accurately → system records user and source → supplier can later acknowledge/correct → all corrections remain in history.

### 6.4 Quality failure/rework

Receipt or operation output is held → inspector records sample/results → disposition is authorized → accepted/rejected/rework quantities are split → downstream supply and order risks recalculate → rework action is assigned and linked → closure preserves original inspection and disposition history.

### 6.5 Order/date change

Authorized user proposes revised quantity/date → system shows changed downstream dependencies and conflicts → approval rules run → old promise/version remains in history → affected owners/suppliers are notified only after configured approval/communication gates.

---

## 7. Core domain model and data integrity

### 7.1 Core entities

`Tenant`, `LegalEntity`, `Site`, `Warehouse`, `User`, `Role`, `Permission`, `Customer`, `Supplier`, `Item`, `UnitOfMeasure`, `BOM/Recipe`, `Routing`, `Resource`, `Calendar`, `SalesOrder`, `SalesOrderLine`, `ShipmentSchedule`, `ProductionPlan`, `WorkOrder`, `Operation`, `Batch/Lot`, `MaterialReservation`, `StockTransaction`, `PurchaseRequest`, `RFQ`, `PurchaseOrder`, `SubcontractBatch`, `SupplierUpdate`, `Receipt`, `InspectionPlan`, `InspectionResult`, `Nonconformance`, `Dispatch`, `RecoveryAction`, `Approval`, `Attachment`, `Notification`, `AuditEvent`, `IntegrationJob`.

### 7.2 Integrity rules

- Every tenant-owned row has a tenant scope; relevant rows also have legal entity/site scope.
- Quantities are decimal numeric values with explicit unit and precision; use decimal arithmetic, never binary floating point for inventory or finance.
- Immutable transaction/event history for submitted/posted changes. Corrections are new events or amendment/reversal transactions.
- Use optimistic concurrency/version checks on edits to prevent stale overwrites.
- Use database transactions for multi-row postings and enforce unique/idempotency keys for integrations and supplier form retries.
- Use referential integrity and soft-delete/archive policy appropriate to audit retention; never cascade-delete posted business events.
- Every document has stable ID, human-readable number, status, created/updated actor/time, tenant, and version.
- Store UTC timestamps and preserve tenant/site timezone for display and business-date calculations.
- Maintain event provenance: actor type, actor ID, source channel, timestamp, linked source document, and confidence/confirmation state where applicable.

---

## 8. Recommended technical architecture

### 8.1 Stack recommendation

Choose a **TypeScript modular monolith** for the first implementation:

- Frontend: React + TypeScript + Vite, a maintained component library, responsive design system, generated API client.
- Backend: NestJS + TypeScript as a modular monolith with explicit module boundaries and REST API documented with OpenAPI.
- Data: PostgreSQL as the authoritative transactional database; Prisma ORM with explicit SQL migrations and review of generated schema changes.
- Background work: start with a Postgres-backed job/outbox pattern; add Redis/queue infrastructure only when measured workload justifies it.
- Files: private object storage with signed, short-lived download URLs and malware/type/size checks.
- Identity: managed identity provider or well-maintained OIDC implementation; choose vendor after cloud and pricing review. Do not build password/MFA crypto yourself.
- Deployment: containerized application on a managed container platform; managed PostgreSQL, object storage, centralized logs/metrics, secrets manager, managed backups.

Why: one primary language improves LLM code consistency and shared validation types; PostgreSQL handles transactional ERP data; a modular monolith avoids premature microservices while allowing modules to be separated later. Cloud provider, exact identity product, and queue technology remain open choices.

### 8.2 Architecture boundaries

Modules own their business logic and tables: Identity/Tenant, Master Data, Sales, Planning, Manufacturing, Procurement, Inventory, Quality, Dispatch, Finance, Notifications, Reporting, Integrations, Audit. Modules communicate through application services and domain events/outbox records, not direct cross-module table mutation. Keep database in one cluster initially, but enforce module ownership in code.

### 8.3 Tenant isolation

Use tenant ID in all tenant-owned records and enforce it on every query and mutation. Add PostgreSQL row-level security as defense in depth if it can be operated safely with pooled connections; set/reset tenant context per transaction and test connection reuse. Never rely only on frontend hiding. Supplier access requires a separate authorization path with resource-scoped claims.

### 8.4 API and integration design

- REST APIs with OpenAPI schemas, consistent error envelope, pagination, filtering, sorting, request IDs, and idempotency keys for posting endpoints.
- API versioning and deprecation policy.
- Webhook delivery with signing, retries, replay protection, event IDs, and delivery logs.
- Import/export CSV/XLSX must validate columns, types, units, duplicates, references, and permissions; provide preview and downloadable error file.
- Connectors are adapters around a canonical internal domain model; do not expose an ERP vendor’s schema throughout the application.
- ERP connector roadmap begins only after identifying pilot systems; do not promise integration breadth before testing each connector.

### 8.5 Reliability, monitoring, and operations

- Structured logs with request/tenant correlation IDs, but no passwords, access tokens, or unnecessary sensitive payloads.
- Metrics for API latency/error rate, DB saturation, jobs, notifications, imports, and supplier link completion.
- Traces across API/database/jobs for critical workflows.
- Alerts for service failure, backups, failed migrations, queue/outbox backlog, and security events.
- Automated backups with tested point-in-time recovery; define and test recovery point/time objectives before production.
- Separate dev, test, staging, and production environments. Production data is not copied to lower environments without approved masking.
- Feature flags for gradual rollout, not to bypass authorization.

---

## 9. Security, privacy, and compliance requirements

- Threat model the tenant boundary, supplier links, imports, attachments, approvals, and administrative/support access.
- TLS in transit; encryption at rest through managed services; secrets manager for API keys and credentials.
- Validate every input server-side; parameterized queries; output encoding; CSRF/XSS/SSRF/SQL injection defenses; secure CORS; upload scanning and private storage.
- Rate limit login, reset, OTP, imports, webhooks, and supplier update endpoints.
- Protect against IDOR by checking tenant, site, role, and record-level scope on every read/write/export.
- Audit role changes, permission changes, exports, support access, approvals, posting/reversal, tax setting changes, and supplier updates.
- Provide tenant data export/deletion policy, data retention configuration, legal hold if required, and documented subprocessors.
- Restrict platform support access to time-bound, approved, reason-recorded, audited sessions; customer data is not available to support by default.
- Security review and penetration test before broad production launch. Maintain dependency scanning, patch process, incident runbook, and vulnerability reporting path.
- Have India legal/privacy experts determine applicable obligations before launch; do not claim compliance by checklist alone.

---

## 10. AI use policy

AI is optional and subordinate to deterministic ERP state:

Allowed with user review: extract fields from challans/POs, draft supplier follow-ups, translate Tamil/English notes, summarize delay evidence, suggest likely reason codes, natural-language report filters.

Not allowed to autonomously: post stock, approve purchase/price changes, release quality holds, modify promised delivery dates, alter accounting/tax entries, assign an alternate supplier, or bypass permissions. AI outputs must be drafts with source evidence, confidence/uncertainty, and explicit confirmation. Never send tenant data to a model provider without customer consent, data-processing terms, and a configurable policy.

---

## 11. Delivery roadmap and release gates

### Phase 0 — Customer validation and workflow specification

- Interview manufacturers across more than one subsegment; observe actual order, PO, stock, job-work, inspection, and dispatch records.
- Map one real order journey and exceptions; identify current ERP/spreadsheet/channel and duplicate entry.
- Select the first pilot segment and supported manufacturing model.
- Agree baseline metrics and willingness-to-pay tests before build commitment.
- Resolve product decisions listed at the top, especially statutory scope, onboarding model, and first release.

**Exit:** repeated workflow evidence, named pilot users, source data access, and at least two businesses willing to test/purchase a defined pilot.

### Phase 1 — SaaS foundation

Tenant provisioning, secure login, roles/scopes, invitation, audit, company/site configuration, item/customer/supplier masters, import framework, responsive shell, backup/monitoring, and test environment.

**Exit:** tenant isolation tests pass; a new tenant can onboard without developer database edits; user permission tests pass.

### Phase 2 — Order fulfillment control

Sales order import/entry, order lines and promised dates, configurable production milestones, work orders at tracking depth, outsourced batches, supplier mobile update, partial quantities, freshness/provenance, risk/action board, approval and audit history.

**Exit:** pilot order can be followed from commitment through dispatch milestone; update impact and quantity math reconcile; stale vs late status is distinct; actions have owners and closure.

### Phase 3 — Operational ERP core

Inventory transactions, purchase requests/POs, receipts/issues/transfers, basic production execution, BOM/routing versioning, quality holds/inspection, dispatch documents, and operational reports.

**Exit:** end-to-end stock and production transactions are auditable, traceable, reversible via controlled process, and do not allow unauthorized posting.

### Phase 4 — Finance/localization

Accounting design, AP/AR, ledger, GST/tax/invoice integrations, valuation, and statutory reporting only after professional review and scope lock.

**Exit:** reconciled accounting and tax scenarios pass qualified reviewer test packs for supported workflows and jurisdictions.

### Phase 5 — General availability and expansion

Additional manufacturing models, ERP connectors, multi-site controls, localization, subscription billing, advanced scheduling, supplier scorecards, and optional AI assistance driven by evidence.

**Exit:** operational support, SLOs, recovery tests, security review, customer onboarding/support playbooks, pricing validation, and upgrade/migration runbooks exist.

---

## 12. Acceptance criteria for the first paid pilot

The pilot is not production-ready until all of the following are true:

1. A tenant admin creates a company/site, configures users/roles, and imports validated master/order data without direct DB access.
2. A user with access can link a customer order to internal operations and outsourced batches; another tenant cannot see it by guessing an ID or changing a request.
3. A supplier can securely submit a batch update on mobile without seeing unrelated customer or supplier records.
4. Completed + rejected + pending quantities reconcile to batch total or produce a visible validation error; partial updates are idempotent and auditable.
5. “Reported complete,” “received,” and “inspection accepted” remain separate quantities/statuses.
6. A revised supplier date or short quantity recalculates affected order risks and shows the calculation inputs and unknowns.
7. Missing confirmation remains “unknown/stale,” not a false late event.
8. Recovery action records owner, due time, decision, approval state, supplier acknowledgement, and closure.
9. Unauthorized actions are denied server-side; edits to submitted/posted records follow controlled amend/reversal rules.
10. Backup restoration, monitoring, error reporting, import retry, and deployment rollback have been exercised.
11. Pilot metrics are measured against a baseline: time spent chasing, update freshness, time from risk first-known to action, late material receipts, and customer deliveries affected.

---

## 13. Test strategy

### Automated tests

- Unit tests for quantity reconciliation, status transitions, due-date logic, role checks, and tax calculations only after reviewed specifications.
- Integration tests against real PostgreSQL for transaction boundaries, constraints, idempotency, tenant scoping, imports, and audit events.
- API contract tests generated from OpenAPI.
- End-to-end tests for signup/invite, onboarding, order creation/import, subcontract update, quality hold/release, approval, receipt, and dispatch.
- Authorization matrix tests for every role/action and tenant/site scope.
- Migration tests from supported prior schema versions with backup/restore verification.
- Load tests for realistic concurrent operations, imports, dashboards, and notification bursts.

### Critical negative cases

Cross-tenant ID access; supplier token replay/expiry; duplicate form submission; malformed or negative quantities; mismatched units; stale concurrent edit; date/time-zone boundary; DST irrelevant to India but timezone must remain configurable; partial receipt with rejection; quality hold during dispatch; deleted/inactive user with pending approval; repeated webhook; import retry; over-shipment; unapproved supplier change; rollback after failed posting.

Tests must validate business behavior and boundaries, not merely mirror implementation.

---

## 14. LLM-assisted development contract

Use the following rules for every coding model/task:

1. Read this plan, repository instructions, architecture decisions, and current module state before editing.
2. Implement one bounded phase/story per task. Do not generate the whole ERP in one prompt.
3. Before coding, list affected modules, data migration impact, authorization implications, and unresolved questions. Stop and ask instead of guessing where a business rule is unspecified.
4. Follow modular monolith boundaries, shared API contracts, and naming conventions. Reuse existing components and services; do not duplicate screens or validation logic.
5. Put business rules on the server. The frontend is not an authority for tenant scope, pricing, quantity, approval, or state transitions.
6. Include database migrations, meaningful tests, error handling, audit events, and documentation with each story.
7. Never use sample data, mocks, or AI output to silently satisfy production workflows. Label demo data clearly.
8. Do not add a dependency, external API, model provider, or cloud product without explaining why and updating the dependency/security record.
9. After implementation, run the relevant tests, type checks, lint, migration checks, and build; report results and known gaps accurately.
10. Review generated code for IDOR, SQL injection, unsafe file access, missing tenant filters, secret leakage, race conditions, and transaction errors.
11. Keep architecture decision records for stack, tenant isolation, identity, accounting, integration, and workflow choices.
12. No model may self-approve its code or execute production migrations/deployments without the project’s release controls.

### Suggested first implementation stories

1. Repository baseline: lint/typecheck/test/build/CI/container, app shell, API health check.
2. Tenant and identity model with secure invitation/login and tenant-scope enforcement.
3. Role/scope policy service and authorization test matrix.
4. Company/site/calendar/document-number setup wizard.
5. Customer, supplier, item, and unit masters with validated CSV import.
6. Sales order and order line workflow with promised dates/history.
7. Work order, routing, and operation dependency tracking.
8. Outsourced batch + secure supplier update + quantity ledger.
9. Risk calculation + action inbox + approvals.
10. Receipts, quality inspection/hold, dispatch milestones, and pilot reports.

---

## 15. Decisions required before implementation begins

These choices affect schema and legal claims. Record the answers in an ADR or product decision log; until then, implement only behind configurable boundaries:

1. Which manufacturing types are included in the first paid release: discrete/job shop, process/batch, or another defined subset?
2. Is tenant creation self-service, sales-assisted, or both at launch?
3. Which login methods are required: email/password, email OTP, Google/Microsoft SSO, or customer SAML/OIDC?
4. Which cloud provider, region, data-residency requirements, and support-access model apply?
5. Which India finance/tax workflows are in scope for release one versus integration with existing accounting software?
6. Which languages are required at launch (English, Tamil, Hindi, others), including supplier voice/text workflows?
7. What is the first paid pilot segment and which ERP/accounting systems must be imported from or connected to?
8. What are subscription, trial, usage, and supplier-user pricing constraints?
9. What are the customer’s required availability, recovery, data-retention, and export expectations?

Do not ask all these questions before useful work can start. Phases 0–2 can validate the workflow and build the secure tenant/order/outsourced-progress foundation, while finance, cloud-vendor, pricing, and broader manufacturing-model decisions are resolved before their respective modules.

---

## 16. Immediate next action

Start Phase 0 and the Phase 1 foundation in parallel only where no business decision is blocked: interview manufacturers and inspect real documents; meanwhile create the repository, architecture decision log, tenant-aware identity model, authorization test matrix, and onboarding skeleton. Do not begin finance or statutory modules until their requirements are confirmed by qualified reviewers. The first demonstrable workflow should be one customer order moving through internal steps and an outsourced batch, with trustworthy progress, explainable risk, and an assigned recovery action.