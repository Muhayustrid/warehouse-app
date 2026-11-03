# Handoff for the pos_next agent: align with the new Stock Reconciliation UOM flow

Date: 2026-11-03 · Audience: AI agent working in `apps/pos_next`
Source design: `warehouse_app` repo, [`docs/specs/2026-11-03-sr-uom-consolidation-design.md`](docs/specs/2026-11-03-sr-uom-consolidation-design.md)
(Indonesian; this handoff is self-contained).

## What changes in warehouse_app

1. The per-UOM math for Stock Reconciliation rows moves into one module,
   `warehouse_app/sr_uom.py` (`compute_row`, `resolve_factors`,
   `is_convertible`, `ledger_qty`, constants `SR_*`, `QTY_UOM_DECIMALS = 3`).
2. The doc event `before_validate: warehouse_app.inventory_uom.apply_sr_inventory_uom`
   is **removed**. Conversion now runs inside the document class via
   `extend_doctype_class` (`StockReconciliationUOM`), in
   `validate_posting_time()`, immediately **after** calling
   `super().validate_posting_time()`.
   - Seam rationale: `validate_posting_time()` finalizes `posting_date` and
     `posting_time` when not manually specified. Running conversion here ensures
     posting time is final and conversion completes *before* batch bundle
     creation (`create_serial_and_batch_bundle`) and native
     `remove_items_with_no_change()` consume native `qty`.
   - Resulting MRO: `StockReconciliationUOM → pos_next CustomStockReconciliation
     → ERPNext StockReconciliation`. pos_next keeps `override_doctype_class`.
   - **`ignore_validate=True` compatibility limitation**: Conversion runs inside
     `validate_posting_time()` during `validate()`. Any call executing
     `doc.save(ignore_validate=True)` bypasses `validate()` entirely, so
     per-UOM conversion will not execute. No callers across `warehouse_app` or
     `pos_next` use `ignore_validate=True` on Stock Reconciliation, but this is
     an architectural compatibility limitation, not proof of safety. External
     scripts and integrations must not bypass validation if conversion is
     expected.
3. Consistency rule with `flt` rounding consistency:
   - Native `qty` is kept when `flt(qty / factor, 3) == flt(custom_qty_after, 3)`;
     otherwise `qty = flt(custom_qty_after * factor, precision(qty))`.
   - Native `valuation_rate` is kept when
     `flt(valuation_rate * factor, p) == flt(custom_valuation_rate_per_uom, p)`
     where `p = precision(custom_valuation_rate_per_uom)`; otherwise
     `valuation_rate = flt(flt(rate_per_uom, p) / factor, precision(valuation_rate))`.
   - Rounding comparison uses Frappe's `flt` consistently rather than Python
     `round()`. When rate is changed, `rate_per_uom` is first normalized to its
     display field precision `p` before deriving native `valuation_rate` to
     guarantee fixed-point round-trip stability.
   - Empty rate = untouched; rate 0 only with `allow_zero_valuation_rate`.
4. `custom_qty_before` and `custom_qty_difference_per_uom` are always
   recomputed from the ledger at the final posting date/time, on every save
   (drafts included). For rows with `batch_no`, `sr_uom.ledger_qty` uses ERPNext's
   authoritative `get_batch_qty` at the posting timestamp, rather than total warehouse balance.
5. New whitelisted endpoint
   `warehouse_app.warehouse_app.stock_reconciliation.compute_row`
   (requires `Stock Reconciliation` write permission) returns the derived
   columns for one row, accepting optional `batch_no`. Client script syncs rows
   with stale-response invalidation, omits display rate on UOM change to preserve
   native rate, and resets obsolete metadata on item change.

## Required pos_next changes

### 1. Blind count leak (MANDATORY coordination before any deployment)

`pos_next/overrides/stock_reconciliation.py::CustomStockReconciliation.validate`
blanks `custom_qty_before` / `custom_qty_difference_per_uom` **before**
`super().validate()`. Because warehouse_app now runs conversion in
`StockReconciliationUOM.validate_posting_time()` inside `super().validate()`,
warehouse_app refills them from the ledger, leaking system stock quantities to
outlet users on draft opname documents!

Fix: move that blanking into the existing post-`super().validate()` draft
block (where `current_qty` etc. are already blanked), under the same
condition `self.docstatus == 0 and self._action != "submit"`.

Mandatory coordination: deploying warehouse_app without pos_next's fix will
immediately expose system stock quantities in outlet drafts. Both changes must
be coordinated and deployed simultaneously.

Test: a draft opname with a `custom_uom` row saved by an outlet user has
`custom_qty_before == 0` and `custom_qty_difference_per_uom == 0` in the DB.

### 2. Drop the duplicate per-UOM math

- `pos_next/api/stock_opname.py::_validated_rows`: stop computing
  `qty = custom_after × factor` (lines ~437, ~464) for `custom_uom` rows and
  stop resolving the factor with `_uom_factor`. Send `custom_uom` and
  `custom_qty_after` only; leave `qty` unset for those rows. The class
  computes `qty`, `custom_conversion_factor`, and rejects invalid UOMs with a
  `ValidationError`. Keep pos_next-specific validation (serial items cannot
  use a custom UOM, counted qty parsing).
- `CustomStockReconciliation._fill_per_uom_valuation_rate`: remove it. It
  rounds `valuation_rate × factor`, which warehouse_app then divides back —
  the same rate round-trip bug this redesign fixes. If the Desk still needs
  the per-UOM rate displayed for outlet drafts, call
  `warehouse_app.sr_uom.compute_row` instead of re-implementing it.
- `public/js/stock_reconciliation.js::fill_live_differences`: the inline
  per-UOM formulas are display-only and may stay; optionally replace them
  with the `compute_row` endpoint for exact parity.

### 3. Tests to update

- `pos_next/tests/test_stock_opname_override.py::test_draft_fills_per_uom_valuation_rate`
  — remove or rewrite against the new behaviour.
- `pos_next/api/test_stock_opname.py` cases that assert `qty` computed by
  `_validated_rows` for `custom_uom` rows.
- Add the blind-count test from §1.

## Guard rails

- pos_next must keep working when warehouse_app is not installed:
  guard on `frappe.get_meta("Stock Reconciliation Item").has_field("custom_uom")`
  as today, and import `warehouse_app.sr_uom` lazily inside that guard.
- Do not add a second `override_doctype_class` or move pos_next to
  `extend_doctype_class` as part of this change.
- Release: both apps are baked into the same image (`docker/erp rebuild`);
  deploy the pos_next change in the exact same rebuild as the warehouse_app
  change. Deploying warehouse_app alone will leak system stock quantities on
  outlet drafts due to the blind-count leak described in §1. Simultaneous
  deployment is mandatory.
