# ADR-0003: Master data permissions, site scope and import policy

- **Status:** Proposed. Implemented in slice 1 as reversible defaults; product owner to confirm.
- **Date:** 2026-09-25

## Context

Slice 1 adds customers, suppliers, items, units, warehouses and CSV import. It needs default role permissions, a site-access rule and an import duplicate policy. The product plan (§2.3, §2.4, §5.1, §8.4) sets the direction (deny by default, role templates, site scope, preview/dry-run/idempotent imports) but not the exact defaults.

## Decision

**Role defaults.** All roles can read master data. Management rights follow plan §2.4:

| Permission | Roles |
|---|---|
| customers, units, sites, members, company settings | owner, administrator |
| suppliers | owner, administrator, procurement |
| items | owner, administrator, production manager |
| warehouses | owner, administrator, stores |

The plan's `sales` and `shop-floor` roles do not exist yet. Until the role-customisation story adds them, customer records are managed by owners and administrators.

**Site scope.** Owners and administrators always act on every site. Every other membership has a site scope of `all` or `selected`. With `selected`, the user sees and changes only site-owned records (currently warehouses and the site list) at granted sites. With no granted sites they see no site data. The migration gave existing non-admin memberships access to their home site only. Customers, suppliers, items and units are company-wide, not site-owned. A lost site grant takes effect on the next request.

**Record lifecycle.**
- Codes are uppercase and unique per company.
- Records are deactivated, never deleted. Unit conversions are configuration and may be deleted, with an audit event.
- Every edit must quote the record's version, and a mismatch is rejected.
- Every change writes an audit event with before/after values.

**Import policy.**
- Import covers customers, suppliers and items, as CSV up to 500 KB and 2,000 rows.
- Preview never writes. Commit is all-or-nothing: any error rejects the whole file.
- A row whose code already exists with identical values counts as "already present", so re-running a file is harmless.
- A row whose code exists with different values is an error. Imports never overwrite; edits happen in the app, where they are versioned and audited.
- Tax columns (GSTIN, HSN) are rejected as unknown until tax scope (plan §15 question 5) is decided.

## Consequences

- Changing the role defaults is a code change today. Tenant-customisable roles (plan §14 story 3) should replace the fixed map.
- Transactional records in later slices (orders, stock, work orders) must carry a site and use the same scope check.
- An import that updates existing records would need its own review and approval design.
