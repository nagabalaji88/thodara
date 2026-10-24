# Thodara

**Keep every order moving.**

Thodara is a manufacturing ERP foundation for connecting customer commitments to factory and supplier progress. The product plan and staged delivery remain in [`docs/manufacturing-erp-product-plan.md`](docs/manufacturing-erp-product-plan.md) and [`docs/production-build-plan.md`](docs/production-build-plan.md). The stack decision is recorded in [`docs/decisions/ADR-0001-platform-stack.md`](docs/decisions/ADR-0001-platform-stack.md).

## What is implemented now

This first runnable slice establishes the application foundation:

- Responsive React/TypeScript sign-in, workspace selection, company/site setup, and a truthful empty-state dashboard.
- FastAPI login, logout, session lookup, tenant selection, workspace summary, and setup endpoints.
- PostgreSQL 18 schema and Alembic migration for tenants, sites, users, memberships, sessions, and audit events.
- Argon2 password hashes, opaque revocable cookie sessions, CSRF/origin checks, temporary failed-login throttling and edge IP rate limiting, request IDs, and server-side tenant permission checks.
- Development-only CLI provisioning for the first workspace owner; public signup is not enabled.

Slice 1 (master data) adds:

- Units of measure with exact decimal conversions between units of the same kind, customers, suppliers (with a job-work flag), items for both discrete and process manufacturing, warehouses per site, and additional sites.
- Site-level access: non-admin members see and change only the sites granted to them; administrators manage this under **Company & sites**.
- CSV import for customers, suppliers and items with preview, row-level errors, all-or-nothing commit and safe re-runs.
- Versioned edits (stale edits are rejected), deactivate instead of delete, and audit events with before/after values for every change.
- Decisions are recorded in [ADR-0002](docs/decisions/ADR-0002-manufacturing-model.md) (manufacturing model) and [ADR-0003](docs/decisions/ADR-0003-master-data-access.md) (permissions, site scope, import policy).

Base slice B1 adds a **Sessions & security** page (see and sign out signed-in devices) and richer audit events: actor type, source channel, a name-and-email snapshot that survives user removal, workspace switches, and before/after values for company setup.

Base slice B2 adds a **working calendar** per site (working days, shift hours, holidays, with a 14-day preview) and **document numbering** for sales orders, outsourced batches and dispatch notes, both under Company & sites. Delivery-risk dates in later slices are calculated on these calendars.

Fulfillment slice F1 adds **customer orders**. An order belongs to one fulfilling site and is numbered from that site's sequence. Each line snapshots the item's base unit and checks the quantity against the unit's decimal places. Orders start as drafts and can be confirmed only when every open line has a promised date. After confirmation, a promised date changes only through *Change promise*, which needs a reason code and keeps a history of who changed it and when. Owners and administrators can amend quantities, short-close lines (with a reason) and cancel orders that have shipped nothing. Every change writes an audit event. Orders can also be imported from CSV: rows sharing a customer and PO reference become one draft order, a file with any problem is rejected as a whole, and re-importing the same PO creates nothing new. Other roles see orders read-only, and only for the sites they are assigned to. Shipped quantity stays 0 until dispatch (F8).

Fulfillment slice F2 records **what each order line needs**:
- **Components:** quantity per unit, and the outsourced step a supplier performs on them, if any (for example 1 housing casting per pump, powder coated). The quantity needed follows the line's open quantity and is rounded up to the component's unit.
- **Remaining work:** in-house and transport steps, with working hours, once the components are ready.

Owners, administrators and production managers can edit dependencies. Every change is audited, and a new order can copy the dependencies from the last order for the same item. Fulfillment slice F3 adds **outsourced batches** under Outsourcing:
- **What a batch is:** one item, one operation, one quantity, sent to one job-work supplier from one site, numbered from the OB sequence.
- **Links to orders:** a batch is linked explicitly to the order lines it serves, so the batch page shows every customer order waiting on it. The order page shows every batch serving each component, plus any quantity no batch covers yet. Links can never exceed the batch quantity or the quantity the line still needs.
- **Custody:** "Record sent to supplier" stores the date and delivery challan as a custody movement. From then on the plan is frozen; later changes come only from supplier updates.
- **Ending a batch:** a planned batch can be cancelled. A batch at the supplier can be closed only with a reason. Both unlink the orders.
- **Order changes:** cancelling an order or short-closing a line releases its batch links.

Fulfillment slice F4 records **what suppliers tell us**:
- **Entering an update:** staff enter the supplier's completed, rejected and pending figures, plus a revised return date and a blocker, from a phone call, WhatsApp, email or visit. Each update is labelled *entered by staff, supplier confirmation pending* and keeps who said it and when.
- **Reconciliation:** the three figures must add up to the quantity sent.
- **Corrections:** a figure lower than the earlier report needs an explicit correction with a reason. History is never edited.
- **Duplicates:** submitting the same form twice records it once.
- **Kept separate:** the batch page shows supplier-reported, received and accepted quantities side by side. Reported completion is never treated as received or usable, and it never changes a customer promise.
- **Where it shows:** every dependent order shows the latest report and how old it is. A batch with no update since it was sent is marked unknown, not late.

Fulfillment slice F5 records **what physically came back and what quality accepted**:
- **Receipts:** stores record each receipt against a batch, with the supplier's document number, as a custody movement. Receipts can never exceed what was sent.
- **Inspection:** quality splits each receipt into accepted, on hold, rework and rejected, with findings for anything not accepted.
- **Holds:** held material is released later with a reason.
- **What counts as usable:** only accepted quantity. The batch page shows how much is still at the supplier, awaiting inspection, accepted, held, in rework and rejected. Every dependent order shows how much is back and how much is usable.

Rules are in [ADR-0005](docs/decisions/ADR-0005-receipts-and-quality.md).

Fulfillment slice F6 answers **"will this order ship on time?"**:
- **Delivery risk page:** classifies every open line of a confirmed order as late, short, at risk, on quality hold, unknown, on track or ready, most severe first, with the reason.
- **Each order:** shows the full calculation:
  - how much of each outsourced component is usable now;
  - what is still expected from which batch, and by when (with the source of that date);
  - which other orders are served first from a shared batch;
  - the remaining working hours on the site calendar;
  - the projected ready date against the promise.
- **Stale or missing information:** shown as unknown, never as late. The stale threshold (default 48 hours) is set under Company & sites.
- **My work:** the dashboard now shows these live figures and the lines that need attention.

Rules are in [ADR-0006](docs/decisions/ADR-0006-delivery-risk-rules.md).

Fulfillment slice F7 turns risk into **who fixes what, by when**:
- **Suggestions:** each order's risk panel suggests next steps from fixed rules (chase a stale supplier, collect what is complete, expedite, rework, try another supplier, plan overtime, review the promise). They stay suggestions until someone creates an action with an owner and a due time.
- **Approvals:** rework, a supplier change or a promise review needs approval by someone else with approval rights.
- **Working an action:** owners acknowledge, record the supplier's acknowledgement (entered by staff) and close with an outcome. The risk when the action was raised and when it was closed are shown side by side.
- **Where they show:** My work lists your actions, and the Actions page shows all open, yours, overdue, waiting for your approval, and closed.

Rules are in [ADR-0007](docs/decisions/ADR-0007-recovery-actions.md).

Fulfillment slice F8 closes the loop with **dispatch and reports**:
- **Dispatch notes:** each order shows what can ship now. That is only what can be built from accepted, usable outsourced material; anything beyond needs a reason and, since G1, someone else's approval. A posted dispatch note (DN-) raises shipped quantities, uses up the batch material behind them, and closes fulfilled lines and orders. Cancelling one reverses it exactly.
- **Reports:** on-time delivery, delivery by customer, open risk, stale supplier information, action ageing and early warning, each with a written definition.

Rules are in [ADR-0008](docs/decisions/ADR-0008-dispatch-and-reports.md).

With F8, the first-release journey is in place: customer commitment → dependencies → outsourced batch → supplier update → receipt and quality → delivery risk → approved recovery action → dispatch outcome. It is not production-ready: hosting, backups and monitoring wait on decision D4, and identity and notifications on D3.

Slice G1 applies the product owner's rule changes (ADR-0009):
- Supplier figures may differ from the quantity sent by a company tolerance (±2% by default, set under Company & sites). The difference is shown as unaccounted and delivery risk does not expect it back.
- Planners can give a batch allocation a manual priority with a reason; usable material goes to it first.
- Shipping beyond accepted material is a request that someone other than the requester must approve before anything ships. Approvers see pending requests on the Actions page.
- A quality decision made by the person who also received the material is allowed but flagged, and counted in Reports.

Slice G2 adds **basic stock** per warehouse (ADR-0010):
- A Stock page shows on-hand quantities per item and warehouse, and the ledger of each item.
- Stores post receipts and issues straight away. Opening balances and adjustments count only after someone else approves them. Mistakes are reversed by a counter-entry. Stock never goes below zero.
- Delivery risk and dispatch use finished-goods stock first, then component stock and accepted batch material. Items with no stock entered at a site are still assumed available, and the screen says so. Dispatch uses the stock, and cancelling a dispatch puts it back.

A self-service supplier portal waits on decision D2 (how suppliers sign in).

Rules and permissions for F2–F4 are in [ADR-0004](docs/decisions/ADR-0004-fulfillment-tracking-rules.md).

The full roadmap, with the status of every item and the decisions that block some of them, is in [`docs/delivery-backlog.md`](docs/delivery-backlog.md).

This is not a completed or production-ready ERP. The dashboard does not contain mock order or factory KPIs. Work orders, warehouse stock, inspection plans, delivery documents, invitations, password reset, email delivery, MFA, tax fields, deployment, and operational monitoring remain future work. Notifications wait on decisions D3/D4.

## Quick start on Windows

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or let the script offer to install it with `winget`).
2. Download this repository (Code → Download ZIP, or `git clone`) and double-click `start-thodara.bat`.

On the first run it creates `.env` with a random database password, builds and starts the database, API and web app, applies the database schema, asks you for the first owner account, and opens <http://localhost:8080>. Later runs just start the app and open it. `stop-thodara.bat` stops it and keeps your data. This is for trying Thodara on one computer, not for hosting it.

## Run with Docker Compose

Requirements: Docker Engine with the Compose plugin.

```bash
cp .env.example .env
# Change POSTGRES_PASSWORD and the matching THODARA_DATABASE_URL password for local use.
docker compose up -d db
docker compose run --rm migrate
docker compose up -d api web
```

Open <http://localhost:8080>. The local API health endpoints are <http://localhost:8000/health/live> and <http://localhost:8000/health/ready>.

Create the initial development account after the API and database are running:

```bash
docker compose exec api /app/.venv/bin/thodara-api provision-owner \
  --email owner@example.com --name "Workspace Owner" \
  --tenant "Example Pumps" --site "Main Plant"
```

The command prompts for a password and is disabled outside `development`. Never use the example password or local credentials in a hosted environment. For a clean local reset, `docker compose down -v` removes the local database volume and all data in it.

## Run services directly

Requirements: Python 3.12+, `uv`, Node 24+, npm, and PostgreSQL 18.

```bash
cp .env.example .env
cd backend
uv sync --dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd frontend
npm ci
npm run dev
```

Vite serves the UI on <http://localhost:5173> and proxies `/api` to the local FastAPI service. Provision a development owner with `cd backend && uv run thodara-api provision-owner ...`.

## Checks

```bash
cd backend && uv run pytest && uv run ruff check .
cd frontend && npm ci && npm run build
```

By default the API tests use in-memory SQLite. To run the same suite against PostgreSQL, point `THODARA_TEST_DATABASE_URL` at a disposable database; the tests drop every application table in it after each test:

```bash
cd backend && THODARA_TEST_DATABASE_URL=postgresql+asyncpg://thodara:<password>@localhost:5432/thodara_test uv run pytest
```

CI runs the suite on both SQLite and PostgreSQL. Tests marked `xfail(strict=True)` record known authorization and audit gaps; when a gap is closed, remove the marker. Before a customer release, also complete the security, backup/restore, observability, and deployment work listed in the production build plan.

## Design references

`prototype/index.html` and `designs/` are visual/product references only. The application uses their restrained amber, warm white, and navy tone without copying their layouts or using profile photography. Supplier and shop-floor experiences will need their own mobile-first workflow design.
