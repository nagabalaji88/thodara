# Thodara

**Keep every order moving.**

Thodara is a manufacturing ERP foundation for connecting customer commitments to factory and supplier progress. The product plan and staged delivery remain in [`manufacturing-erp-product-plan.md`](manufacturing-erp-product-plan.md) and [`docs/production-build-plan.md`](docs/production-build-plan.md). The stack decision is recorded in [`docs/decisions/ADR-0001-platform-stack.md`](docs/decisions/ADR-0001-platform-stack.md).

## What is implemented now

This first runnable slice establishes the application foundation:

- Responsive React/TypeScript sign-in, workspace selection, company/site setup, and a truthful empty-state dashboard.
- FastAPI login, logout, session lookup, tenant selection, workspace summary, and setup endpoints.
- PostgreSQL 18 schema and Alembic migration for tenants, sites, users, memberships, sessions, and audit events.
- Argon2 password hashes, opaque revocable cookie sessions, CSRF/origin checks, basic login lockout, request IDs, and server-side tenant permission checks.
- Development-only CLI provisioning for the first workspace owner; public signup is not enabled.

This is a foundation, not a completed or production-ready ERP. The dashboard does not contain mock order or factory KPIs. Orders, outsourcing batches, receiving, quality, dispatch, invitations, password reset, email delivery, MFA, deployment, and operational monitoring remain future work.

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

SQLite is used only for fast API tests. The migration and local Compose stack target PostgreSQL; before a customer release, run integration tests against PostgreSQL and complete the security, backup/restore, observability, and deployment work listed in the production build plan.

## Design references

`prototype/index.html` and `designs/` are visual/product references only. The application uses their restrained amber, warm white, and navy tone without copying their layouts or using profile photography. Supplier and shop-floor experiences will need their own mobile-first workflow design.
