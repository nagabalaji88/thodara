# ADR-0014: Importing outsourced batches, batch reference and material owner

- **Status:** Accepted (product owner, 2026-10-31). Implemented in slice G6.
- **Date:** 2026-10-31

## Context

The first-release plan (F3) asked for a CSV import of outsourced batches and for recording the material owner. A factory starting with Thodara already has material out at job-work suppliers; typing each batch by hand is slow and error-prone. ADR-0004 covers batches entered on screen.

## Decisions (product owner, 2026-10-31)

| Question | Decision |
|---|---|
| State of imported batches | **Planned, or already at the supplier.** A row with a sent date and our challan number becomes a batch at the supplier, with the custody movement recorded; a row without them becomes a planned batch. |
| Recognising a re-imported row | **Supplier + our challan number.** Planned rows without a challan use the factory's own batch reference instead. A batch already present with the same details is skipped; with different details the row is refused. |
| Linking to customer orders | **Yes, by order number and line**, with the same checks as the screen. |
| Material owner | **Recorded per batch:** our material, or customer-supplied (free issue) with the customer named. No tax treatment yet (D5). |

## Rules

- A batch may carry a **reference** (the factory's own batch number, up to 80 characters). It can be set on screen and in the import.
- **Material owner** is `own` (default) or `customer`; `customer` requires an active customer. It can be changed on screen while the batch is planned or at the supplier, and changes are audited.
- **Import file.** One row per batch, or several rows for one batch that serves several order lines.
  - Required columns: `supplier_code`, `item_code`, `operation`, `quantity`, `expected_return_date`.
  - Optional columns: `sent_date`, `challan_reference`, `batch_reference`, `material_owner`, `owner_customer_code`, `order_number`, `line_no`, `allocate_qty`, `notes`.
  - `sent_date` and `challan_reference` are given together or not at all; every row needs a challan or a batch reference so it can be recognised again.
  - Rows for the same supplier and challan (or reference) are one batch; their batch columns must agree.
  - `order_number`, `line_no` and `allocate_qty` are given together; the line must be an open line of a confirmed order at the chosen site whose component is the batch's item.
- **Preview first, all or nothing.** The file is checked in full, including the allocation checks, inside a transaction that is rolled back for a preview. A file with any problem creates nothing. Up to 2,000 rows and 500 KB.
- Only people with `outsourcing:manage` can import, at sites they can access. Each created batch is audited as created (and sent) with the source `import`.

## Consequences

- Supplier updates and receipts for imported batches are still entered on screen.
- Material owner is informational until finance and GST rules for job work (D5) are designed.
