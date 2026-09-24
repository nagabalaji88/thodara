# ADR-0001: Initial application stack and relational database

- **Status:** Accepted for the application foundation
- **Date:** 2026-09-24

## Context

Thodara is a multi-tenant manufacturing ERP. Its records include orders, operation dependencies, supplier updates, inventory movements, quality decisions, approvals, and audit history. These need relational integrity, transactional updates, a clear tenant boundary, and reliable backup/restore. The requested application stack is React on the frontend and FastAPI/Python on the backend.

## Decision

- React + TypeScript + Vite for the web client.
- FastAPI + Pydantic v2 for the API.
- PostgreSQL 18 stable as the authoritative transactional database.
- SQLAlchemy 2 async for persistence and Alembic for reviewed migrations.
- Local development uses a pinned PostgreSQL container. Production will use a managed PostgreSQL service with high availability, encrypted backups, point-in-time recovery, and restore tests. The cloud provider and region remain undecided.
- The API is stateless apart from opaque, revocable session records stored in PostgreSQL. Session cookies are Secure/HttpOnly/SameSite in HTTPS deployments; unsafe requests require CSRF and origin validation.

## Rationale

PostgreSQL supports transactional workflow state, foreign-key/unique constraints, decimal values, JSONB for limited flexible metadata, mature replication/backups, and predictable indexing. Those capabilities match ERP transaction and tenant-isolation needs better than a document-first database. Horizontal API scaling is independent of the database; read replicas, caching, partitions, or queues are introduced only after measured demand.

## Consequences

- Schema changes are explicit Alembic migrations with deployment review.
- Tenant-owned tables include tenant scope and use scoped repository/query helpers; row-level security may be added as defense in depth after policy tests exist.
- Production readiness requires a cloud-provider decision, managed PostgreSQL configuration, secrets, email delivery, monitoring, backup/restore drills, and declared RPO/RTO. This ADR does not select those services.
- Public tenant signup, SSO, tax/accounting, and first pilot workflow remain separate product decisions.

## Alternatives considered

- **MongoDB/document store:** rejected as the primary system of record because the core relies on relational constraints and multi-record transactional workflows. It may be considered later for a separately justified workload.
- **SQLite:** rejected for production; it remains suitable only for fast isolated tests if PostgreSQL integration tests also run.
- **MySQL:** capable, but PostgreSQL’s constraint, indexing, JSONB, and ecosystem fit the chosen domain and team stack better for this project.
- **PostgreSQL plus Redis as the primary session/cache store:** deferred. PostgreSQL is sufficient for initial sessions and avoids adding an unneeded production dependency; Redis can be introduced for measured rate limiting/cache/queue needs.
