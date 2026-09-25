# Thodara production build plan

## Purpose and scope

This document turns the existing product plan into an ordered, LLM-executable build sequence. Thodara is a hosted, India-first manufacturing ERP with a configurable shared core. Its first differentiating workflow is order-to-dispatch visibility across in-house and outsourced operations. This is a plan for a real application; it does not claim the current prototype or the initial foundation is production-ready for customer data.

The first implementation slice establishes the application boundary, identity/session base, tenant and site scope, migrations, health endpoints, and a responsive React workspace. The rest of the ERP will ship as small, tested domain slices. Product Phase 0 is customer validation; this implementation plan starts at Product Phase 1 (SaaS foundation), then keeps subsequent phase numbers aligned with the product plan.

## Product and design constraints

- Cover customer orders, planning, purchasing, in-house and outsourced production, inventory, quality, dispatch, reporting, and later finance behind explicit scope decisions.
- Make each order’s promised quantity/date, current material/operation state, delivery risk, next owner/action, and status freshness traceable.
- Distinguish supplier-reported, physically received, and inspection-accepted quantities. Stale or missing status is not a confirmed delay.
- Keep supplier participation narrowly scoped, simple, and separate from buyer-tenant access.
- Enforce tenant and site scope on every server-side query and mutation. Deny access by default.
- Use deterministic rules for quantities, permissions, approvals, and date/dependency calculations. AI output remains an uncommitted draft.
- Require human authorization for quality disposition, supplier changes, commercial exceptions, and other consequential transitions.
- Treat the two supplied images as visual references only: cool pale canvas, warm off-white surfaces, dark ink/navy, thin warm yellow/amber accents, compact metrics, rounded cards, restrained shadow, and simple line icons. Do not reproduce their layout or retail/HR concepts. Do not show a profile photo; use initials or a neutral account control where useful.
- Keep the application responsive and usable by suppliers and shop-floor staff on mobile. Honor reduced motion, keyboard operation, and accessible contrast.

## Proposed architecture

| Layer | Choice | Reason / boundary |
|---|---|---|
| Web | React 19.3 + TypeScript + Vite 8.3 | Typed component UI, responsive build, fast local development. Add React Router as the screen set grows; use TanStack Query for server state. |
| API | Python 3.12+ + FastAPI + Pydantic v2 | Typed request/response boundaries, OpenAPI, async request handling. Keep domain rules independent from transport code. |
| Persistence | PostgreSQL 18 stable | ACID transactions, constraints, JSONB only for genuinely variable metadata, mature backup/replication options, indexes and row-level security as defense in depth. PostgreSQL remains the system of record. Avoid PostgreSQL 19 beta for production. |
| ORM/migrations | SQLAlchemy 2 async + Alembic | Explicit transactions, typed models, reviewed schema evolution. Migrations run as a release job, never as an unreviewed web-worker side effect. |
| Session | Opaque random server-side session token in Secure, HttpOnly, SameSite cookie; persist only a hash | Revocable sessions, no browser-stored bearer token. Protect unsafe requests with CSRF token and origin checks. |
| Passwords | Argon2id through a maintained password-hashing library | No custom cryptography; configurable work factor and secure reset flow. |
| Local runtime | Docker Compose for API, web, PostgreSQL; optional mail catcher for development | Reproducible developer/test environment. Do not infer a cloud vendor from local container choices. |
| Production topology | Stateless API/web containers; managed PostgreSQL with HA, encrypted backups and point-in-time recovery; object storage for documents; centralized secrets/metrics/logs | Cloud provider and region remain open until selected. Scale API horizontally; scale database vertically first, then add read replicas for measured read load. |

Redis, a queue, search service, and read replicas are added only when specific workload needs are established. They are not sources of truth. Use an outbox for reliable asynchronous side effects once domain events/notifications are introduced.

### PostgreSQL reliability and scaling policy

- Use UUID primary keys, UTC timestamps, explicit decimal quantities plus unit-of-measure identifiers, foreign keys, unique constraints, and tenant-scoped indexes.
- Every tenant-owned record carries `tenant_id`; site-owned records also carry `site_id`. Query through an authorized tenant/site context. Consider PostgreSQL row-level security as a second boundary after the application policy is implemented and tested.
- Use short transactions and bounded connection pools. Configure statement/idle transaction timeouts, health checks, TLS, least-privilege database roles, and a migration-only role.
- Production requires automated encrypted backups, point-in-time recovery, restore drills, defined RPO/RTO, monitoring for replication lag/storage/connection saturation, and a documented failover procedure.
- Introduce partitions for high-volume immutable audit/event tables only after measured growth. Do not partition core transactional tables prematurely.

## Identity, tenant, and onboarding decisions

- Keep tenant creation policy behind a provisioning service so self-service and sales-assisted creation can call the same audited workflow.
- The product plan has not selected public self-service versus sales-assisted provisioning. Keep that as a release flag/adapter decision; do not expose a public tenant-creation flow until selected.
- Start with users, tenants, legal entities/sites, memberships, role templates, permission checks, and revocable sessions. Use role plus resource scope (tenant/site/record) and deny by default.
- Support invitation, email verification, reset, suspension, session revocation, and audit trails before external production use. MFA is required for tenant admins and finance approvers before production finance access.
- No identity provider, mail/SMS vendor, cloud provider, region, accounting/tax scope, or pilot manufacturing model is selected in this implementation. Record these choices as open ADRs when a feature needs them.

## Delivery phases

### Phase 1 — SaaS foundation (current implementation slice)

1. Record stack and design decisions; preserve unresolved choices explicitly.
2. Create React/TypeScript and FastAPI service boundaries, configuration validation, containerized local PostgreSQL, and health/readiness endpoints.
3. Create initial PostgreSQL models and Alembic migration for tenants, sites, users, memberships, and sessions; add a safe provisioning CLI for local development.
4. Add login/logout/current-user endpoints with Argon2id, hashed opaque sessions, CSRF/origin checks, generic auth failures, session revocation, and tenant membership scope.
5. Build responsive sign-in, workspace onboarding shell, and dashboard shell using the supplied color/shape language without copying either reference layout or using profile photography.
6. Add unit/integration tests for tenant isolation, permissions, session expiry/revocation, and health checks; add CI checks and local run documentation.

### Phase 2 — Company setup and master data

Company/site settings, units and conversions, document numbering, users/roles/site scope, customers, suppliers, items, warehouses, validated spreadsheet imports, and audit events. Tax fields remain gated on confirmed compliance needs.

**Slice 1 status (implemented):** sites, units and conversions, customers, suppliers, items, warehouses, member site scope, CSV import for customers/suppliers/items, versioned edits and before/after audit events (ADR-0002, ADR-0003). **Not yet:** document numbering, calendars, invitations, tenant-customisable roles, item-specific packaging conversions, legal entities, tax fields.

### Phase 3 — Order fulfillment control

Customer orders and promise dates; BOM/routing versions; work orders and operation dependencies; internal/external operation classification; outsourced batches and challans; supplier progress portal/OTP; quantity reconciliation; receipts and inspection separation; deterministic promise-risk rules; daily action ownership and approvals.

### Phase 4 — Core ERP transactions

Purchasing, inventory ledger and reservations, receiving/issues/transfers, planning and production execution, quality plans/dispositions, dispatch and partial shipment, document storage, and transactional audit history.

### Phase 5 — Reporting, integrations, and commercial readiness

Delivery/status freshness/chasing-time reports; notification outbox; imports/connectors; subscription/billing decision; customer support, observability, tenant migration, backup/restore and DR drills, security review, load testing, and operational runbooks.

## Definition of done for each implementation story

- Acceptance criteria and affected tenant/site scope are explicit before coding.
- API contracts, schema migration, domain validation, authorization and audit events are implemented together.
- Tests cover happy path, invalid state/quantity, tenant/site boundary, and permission denial where applicable.
- React forms have labels, keyboard focus, loading/error/empty states, and responsive layouts; server validation remains authoritative.
- Logs are structured and contain correlation IDs, but never passwords, session tokens, supplier links, or unnecessary personal data.
- Migrations are reversible where practical and tested against PostgreSQL; deployment/rollback notes are updated.
- CI and local checks pass. Demo data is clearly marked and isolated from any real tenant.

## Open product-owner decisions before corresponding release gates

1. First paid-pilot manufacturing model and segment.
2. Self-service tenant signup, sales-assisted onboarding, or both at launch.
3. Supported login methods and identity provider; email/OTP delivery provider; MFA rollout.
4. Cloud provider, deployment region/data residency, managed PostgreSQL offering, and budget.
5. Accounting, GST/e-invoice, payroll, and statutory scope.
6. Supported UI/supplier languages and local calendar/holiday rules.
7. Pricing/billing and pilot success measures.
8. Initial workflow/status configuration and approval limits for the selected segment.

These decisions do not block a provider-neutral local foundation, domain model boundaries, or the responsive app shell. They must be resolved before enabling the affected external or statutory capabilities.
