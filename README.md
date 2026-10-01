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

The full roadmap, with the status of every item and the decisions that block some of them, is in [`docs/delivery-backlog.md`](docs/delivery-backlog.md).

This is not a completed or production-ready ERP. The dashboard does not contain mock order or factory KPIs. Orders, work orders, outsourcing batches, supplier updates, receiving, quality, dispatch, invitations, password reset, email delivery, MFA, tax fields, deployment, and operational monitoring remain future work.

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
