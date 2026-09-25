# ADR-0002: Support discrete and process manufacturing in one configurable model

- **Status:** Accepted (product owner, 2026-09-25)
- **Date:** 2026-09-25

## Context

Product plan §15 question 1 asks which manufacturing types the first paid release supports. The answer shapes items, bills of materials/recipes, work orders and quantity tracking. The product owner chose **both discrete/job-shop and process/batch manufacturing, configurable**, rather than one model first.

## Decision

- One shared item master serves both models. Item types cover both worlds: `raw_material`, `component`, `intermediate`, `finished_good`, `packaging`, `consumable`, `service`.
- Each item states how it is tracked: `none`, `lot` (batches: common in process manufacturing and for heat numbers or plating lots) or `serial` (common for discrete finished goods).
- Units of measure are tenant-defined, carry a kind of measure (count, mass, length, area, volume, time) and a decimal precision (0–6). Conversions are exact decimals and only allowed between units of the same kind. Item-specific conversions across kinds (for example 1 bag = 25 kg for one item) are deferred to the item-packaging story.
- Later slices will add a production definition per item that is either a routing with operations (discrete) or a recipe with batch size and yield (process). Work orders will reference that definition. This ADR does not implement either yet.

## Consequences

- Slice 1 (master data) needs no model switch; the same records work for both.
- The BOM/recipe and work-order slices must support both definitions behind one work-order and quantity ledger, which is more work than picking one model.
- A tenant-level setting to hide the model a company does not use may be added for simplicity. It must not change stored data.
- Pilot selection (§15 question 7) should still name one lead segment so acceptance tests use real workflows.
