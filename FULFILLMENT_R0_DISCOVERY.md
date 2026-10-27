# Fulfillment R0 — Native v16 / W31 Discovery

**Status:** static discovery complete, 2026-10-26. Runtime spike pending a disposable ERPNext v16 + W31 site.
**Repo:** `callmevan1120/warehouse-app` (fork), base `main` `a69511d`.
**Scope:** read-only source audit. No runtime code, no migration, no deploy.
**Spec:** `PRD_Warehouse_Fulfillment_ERPNext_v16.md`.

## 1. Executive summary

1. ERPNext v16 already has a native path from Sales Order to Pick List, and from **multiple Pick Lists to one Delivery Note** via `create_dn_for_pick_lists(source_name, target_doc)`. The PRD's highest-risk custom merge can be a thin adapter around native code, not a new financial mapper.
2. The hard part is splitting one Sales Order into two disjoint Pick Lists (Dry/Frozen) without losing SO row references. `create_pick_list` maps **all** eligible SO rows; the app must split, not call the mapper blindly twice.
3. Short pick is possible natively when `scan_mode = 0` and `picked_qty` is explicitly set below `stock_qty`. If `scan_mode = 1`, native validation blocks a short pick. If `picked_qty = 0` and `scan_mode = 0`, native auto-fills the full `stock_qty` on submit. W31's `custom_picked_qty` must stay in lockstep.
4. `create_pick_list` and Pick List submit both reject a Sales Order that has `stock_reserved_qty > 0`. Stock reservation must be off for the pilot, or the flow must reconcile reservations first.
5. Packing Slip is submittable and requires a Draft Delivery Note. `packed_qty` is updated natively on submit/cancel. Package-number overlap is validated only across submitted Packing Slips.
6. Runtime verification is blocked on this host: Docker daemon, `bench`, and a Frappe site are not available. A disposable v16 + W31 site is required before any PL/DN mutation code is merged.

## 2. Baseline repo

- Fork: `callmevan1120/warehouse-app`, `origin/main` = `a69511d`.
- Upstream: `Muhayustrid/warehouse-app`, `upstream/main` = `a69511d`.
- Existing app conventions:
  - custom fields through `warehouse_app/upgrade.py` idempotent upsert;
  - W31 hooks in `warehouse_app/hooks.py`;
  - gates in `warehouse_app/tests/w*_gate.py`;
  - SPA build output committed in `warehouse_app/public/gudang/` + `www/gudang.html`;
  - no core ERPNext edits, no global native behaviour changes.
- Reference source cloned for this audit only: `_ref/erpnext-v16` at `version-16`, sparse checkout of the relevant doctypes. It is not part of the app repo.

## 3. Native v16 contract

### 3.1 Sales Order → Pick List

`erpnext/selling/doctype/sales_order/sales_order.py:2057 create_pick_list(source_name, target_doc=None)`.

- Validates the Sales Order through `get_mapped_doc` with `docstatus = 1`.
- Rejects creation when any SO Item has `stock_reserved_qty > 0` (`sales_order.py:2060-2068`).
- Maps every eligible SO Item: `delivered_qty < qty`, not `delivered_by_supplier`, not a Product Bundle (`sales_order.py:2091-2096`).
- Pending qty per row: `qty - max(picked_qty, delivered_qty)` (`sales_order.py:2070-2075`).
- Sets `purpose = "Delivery"` (`sales_order.py:2130`).
- If `pick_manually = 0`, calls `set_item_locations()` before returning (`sales_order.py:2132-2133`).

**Implication for Dry/Frozen split**

- One native `create_pick_list` call produces one Pick List template containing all eligible SO rows and their native locations.
- The app must split that template into two documents by Item Group classification and remove the rows that do not belong to the group.
- Do **not** call the mapper twice and leave both documents with all rows: that creates duplicate picking demand.
- `Pick List.before_save` calls `set_item_locations()` again when `pick_manually = 0` (`pick_list.py:142-145`). `set_item_locations` removes rows with `picked_qty = 0` and rebuilds locations from the current rows (`pick_list.py:640-708`). The split must therefore be done before the first save, and the result must be verified after save.
- `pick_manually = 1` skips automatic location rewriting, but the app must then supply and validate locations itself. MVP should keep the native default `0` unless runtime tests prove manual mode is safer for batch selection.

### 3.2 Pick List submit and short pick

`Pick List.validate_picked_items` (`pick_list.py:295-307`):

```text
if scan_mode and picked_qty < stock_qty:
    throw "Pick List Incomplete"
if not scan_mode and not picked_qty:
    picked_qty = stock_qty          # auto-fill on submit
```

- `scan_mode` default is `0` (`pick_list.json:167-171`).
- With `scan_mode = 0` and an explicit `picked_qty` between 0 and `stock_qty`, native submit allows a short pick. This is the only safe native short-pick mode.
- With `scan_mode = 1`, native submit blocks any qty below `stock_qty`. The PRD's "revise target" flow is required if scan mode must stay on.
- Leaving `picked_qty = 0` is never a short pick: native overwrites it with `stock_qty` before submit.
- `validate_stock_qty` checks Bin/batch availability before submit (`pick_list.py:151-193`).
- `on_submit` updates status, bundles, SO Item `picked_qty`, and previous-document status (`pick_list.py:309-316`).
- Pick List submit does **not** deduct stock. Stock is posted only by Delivery Note submit.
- In this source path, Pick List submit does **not** call `create_stock_reservation_entries()`; it is a separate whitelisted method (`pick_list.py:539-565`). Site-level hooks or automation must still be checked at runtime.

**W31 interaction**

- Custom field `custom_picked_qty` on Pick List Item, label "Picked Qty (as per UOM)" (`warehouse_app/upgrade.py:922-933`).
- `before_validate` hook `apply_pl_inventory_uom` (`warehouse_app/hooks.py:205-208`, `warehouse_app/inventory_uom.py:199-238`):
  - `custom > 0` → `picked_qty = custom × conversion_factor`, clamped to row `qty` when `pick_manually = 0`;
  - `custom = 0` and `picked > 0` → `custom = picked ÷ conversion_factor` (backfill);
  - both zero → no-op;
  - `conversion_factor <= 0` → throw.
- `on_submit` hook `_pl_backfill` covers the native auto-fill path (`inventory_uom.py:241-259`).
- W31 client scripts are role-gated to Stock Manager / Stock User / System Manager. The SPA cannot rely on the Desk client script; it must implement its own scanner and UOM input, then send the row-UOM qty to the server.

**Canonical API rule**

- If `row.uom == row.stock_uom`: write native `picked_qty` directly.
- Otherwise: write `custom_picked_qty` in the row UOM and let the W31 `before_validate` hook compute `picked_qty`.
- Never write only `custom_picked_qty = 0` for a short pick; that means "not picked yet" to native.

### 3.3 Pick List → Delivery Note

Relevant native functions:

- `pick_list.py:1418 create_delivery_note(source_name, target_doc=None)` → `create_delivery`.
- `pick_list.py:1566 create_dn_for_pick_lists(source_name, target_doc=None, kwargs=None)`.
- `pick_list.py:1638 create_delivery_from_so(...)`.
- `pick_list.py:1675 map_pl_locations(...)`.

What the source proves:

- `create_delivery_note` groups Sales Orders by customer/header fields and creates one Delivery Note per group (`pick_list.py:1435-1450`). It is not a multi-PL merge by itself.
- `create_dn_for_pick_lists` builds a Delivery Note from the Pick List's Sales Order using the native `make_delivery_note` mapper with `skip_item_mapping=True`, then maps the Pick List locations into the target (`pick_list.py:1645-1672`).
- Passing the existing Delivery Note as `target_doc` accumulates a second Pick List into the same document. The native test `test_multiple_pick_lists_delivery_note` (`test_pick_list.py:2468-2516`) creates two Pick Lists, calls `create_dn_for_pick_lists` twice with the second target, sets a partial qty, submits, and verifies both Pick List statuses.
- `map_pl_locations` sets `against_pick_list`, `pick_list_item`, warehouse, qty, batch/serial fields, and skips rows with no remaining picked qty (`pick_list.py:1681-1723`).
- `Delivery Note Item` already has native `against_pick_list` and `pick_list_item` fields (`delivery_note_item.json:953,785`). No custom field is required for this lineage.
- The native mapper preserves commercial header fields: customer, addresses, currency, price list, taxes, terms, payment terms (`pick_list.py:1453-1531`).
- `create_dn_for_pick_lists` checks `read` permission on the source Pick List and validates that locations exist (`pick_list.py:1576-1578`).

**Implication for consolidation**

- The app's consolidation service should be a thin, validated adapter:
  1. both Pick Lists submitted and belong to the same Run/SO/customer/company;
  2. call `create_dn_for_pick_lists(dry_pl)` to create the draft;
  3. call `create_dn_for_pick_lists(frozen_pl, target_doc=draft)` to append;
  4. assert exactly one Delivery Note;
  5. save as `docstatus = 0` and link it to the Run.
- Do not rebuild the DN from `item_code + qty`; that would lose pricing, taxes, addresses, and payment terms.
- `create_dn_for_pick_lists` returns an unsaved document; the app must save it and handle native validation errors.

**Open runtime checks**

- `create_dn_for_pick_lists` returns one DN for one SO/customer in the tested path. What happens with two PLs from the same SO but different header groups must be tested.
- `map_pl_locations` copies `batch_no` / `serial_no` / `use_serial_batch_fields`, not `serial_and_batch_bundle`. Delivery Note validate calls `set_serial_and_batch_bundle_from_pick_list()` (`delivery_note.py:315`); the implementation is outside the sparse checkout and must be tested with real Serial and Batch Bundles.
- The native mapper may merge or split rows differently when the same item appears on two SO rows. Tests must assert per `sales_order_item`, not per item code.

### 3.4 Delivery Note → Packing Slip

Relevant native functions:

- `delivery_note.py:1205 make_packing_slip(source_name, target_doc=None)`.
- `packing_slip.py:59 validate`, `72 on_submit`, `86 on_cancel`.

What the source proves:

- Packing Slip is submittable (`packing_slip.json:178 is_submittable = 1`).
- Packing Slip can only be created for a Draft Delivery Note (`packing_slip.py:89-95`).
- `make_packing_slip` maps DN Items to Packing Slip Items with `dn_detail`, and qty = `qty - packed_qty` (`delivery_note.py:1209-1237`).
- Packing Slip validates:
  - qty > 0;
  - `dn_detail` or `pi_detail` required;
  - reference row belongs to the same DN and item;
  - total packed qty per reference ≤ remaining qty (`packing_slip.py:131-194`).
- Package numbers overlap only across submitted Packing Slips (`packing_slip.py:97-129`). A draft package does not block another draft.
- `on_submit` / `on_cancel` update the previous document status, which updates DN Item `packed_qty` (`packing_slip.py:72-87`).
- A Packing Slip cannot be cancelled after its Delivery Note is submitted (`packing_slip.py:75-84`).

**Implication**

- One Packing Slip per package (or per package range) is native-compatible. Set `from_case_no` and `to_case_no` explicitly.
- Use the native mapper, then remove rows or reduce qty to match the physical package. Do not insert Packing Slip Items manually without `dn_detail`.
- `require_all_packed` is an app-level gate; native only enforces each Packing Slip's remaining qty.

## 4. W31 / inventory UOM contract

- `custom_picked_qty` is a Float on Pick List Item, no default (`warehouse_app/upgrade.py:922-933`).
- The server hook is authoritative. The SPA must not compute `picked_qty` itself; it sends row-UOM qty and lets `apply_pl_inventory_uom` convert.
- W31 gate `warehouse_app/tests/w31_gate.py` covers:
  - field/client-script spec;
  - Box 12 → Nos 24 conversion;
  - draft reload/resave idempotence;
  - native backfill;
  - `pick_manually = 0` clamp;
  - on-submit backfill;
  - batch vs serial passthrough;
  - partial pick;
  - idempotent field/script ensure.
- The gate must be extended with:
  - Dry/Frozen split from one SO;
  - short pick with `scan_mode = 0`;
  - short pick rejection with `scan_mode = 1`;
  - two submitted PLs → one DN via `create_dn_for_pick_lists`;
  - multi-batch/multi-warehouse row lineage;
  - Packing Slip submit/cancel updating `packed_qty`.

## 5. Proposed adapter contract

These are design signatures, not implemented code.

```python
# warehouse_app/warehouse_app/fulfillment/classification.py
def classify_so_items(so_name: str, profile: dict) -> list[dict]:
    """Return [{sales_order_item, item_code, item_group, picking_group, qty, stock_uom}]."""

def validate_frozen_group(profile: dict) -> None:
    """Fail closed on missing group, parent group with children + flag off, or invalid link."""

# warehouse_app/warehouse_app/fulfillment/generation.py
def generate_pick_lists(so_name: str, profile_name: str, idempotency_key: str) -> dict:
    """Create 0-1 Dry PL and 0-1 Frozen PL from one native create_pick_list template."""

# warehouse_app/warehouse_app/fulfillment/picking.py
def save_picking_progress(pl_name: str, row_name: str, uom_qty: float,
                          batch_no: str | None, serial_nos: list[str] | None,
                          expected_modified: str, idempotency_key: str) -> dict:
    """Write row-UOM qty through W31; never write native picked_qty directly for converted rows."""

# warehouse_app/warehouse_app/fulfillment/delivery.py
def create_delivery_note_draft(run_name: str, idempotency_key: str) -> str:
    """Thin adapter over create_dn_for_pick_lists; return one Draft DN name."""

# warehouse_app/warehouse_app/fulfillment/packing.py
def create_packing_slip(run_name: str, package_no: int,
                        allocations: list[dict], idempotency_key: str) -> str:
    """Native make_packing_slip + per-package allocation; return Draft/Submitted PS name."""

# warehouse_app/warehouse_app/fulfillment/verification.py
def verify_run(run_name: str, expected_revision: int) -> dict:
    """Recompute SO → PL → DN → PS matrix and store a canonical hash."""

# warehouse_app/warehouse_app/fulfillment/printing.py
def print_pick_lists(run_name: str, group: str | None) -> bytes:
    """Return one PDF or a ZIP of the configured group formats; enforce lineage/permission."""
```

## 6. Decision baseline

| ID | Decision | Resolution for MVP |
|---|---|---|
| B1 | Idempotency storage | `Warehouse Fulfillment Request Key` is **mandatory**, with a DB unique key. Scope: actor + company + SO + request type + key. TTL 24h; completed keys keep the result reference and cannot create a second document. |
| B2 | Lineage schema | `Run Item` = one row per SO Item (required qty, group snapshot). `Run Allocation` child = one row per source allocation (PL row, warehouse, batch/bundle, qty, DN row). `Document Link` remains optional audit metadata. The current singular `source_warehouse` / `pick_list_item` / `delivery_note_item` fields on Run Item are removed. |
| B3 | Split DN | Remove FR-411 from MVP. One Run → one DN. If native returns more than one DN, mark `NEEDS_RECONCILIATION`; do not merge silently. |
| B4 | Policy snapshot | Snapshot at Generate: classification config, `allow_partial_delivery`, `require_all_packed`, `short_pick_approval_required`, `require_checker_approval`, warehouse scope, and profile revision. Live: print formats, roles, barcode mode. Store a JSON snapshot + revision on the Run. |
| B5 | Short pick granularity | New child table `Warehouse Fulfillment Short Pick` with SO Item, PL row, original target, approved qty, reason, approver, approved_at. Run-level fields are summary only. |
| B6 | Verification hash | SHA-256 over canonical JSON of: Run revision, policy snapshot revision, DN name/modified/docstatus and item rows (item, qty, warehouse, batch/bundle), PL names/docstatus, PS names/docstatus and qty. Recompute at Verify and Submit; any change invalidates approval. |
| B7 | Non-stock items | Block Generate when any SO row is non-stock for MVP. Error lists the rows. Support later with an explicit DN-only exception flow. |
| B8 | Warehouse scope | `dry_parent_warehouse` / `frozen_parent_warehouse` are fallback scopes, not overrides. If the SO Item has a warehouse and it is outside the scope, block with a clear exception. If the SO Item warehouse is empty, use the profile scope. |
| B9 | Parent Item Group | Validate at Profile save and Generate: if the configured group is a group node with children and `include_child_item_groups = 0`, block with a message; preview Frozen/Dry counts before save. |
| B10 | Assignment and row scope | Add `Warehouse Fulfillment Assignment` (Run, group, user, assigned_by, assigned_at) or use `_assign` with one documented convention. Queue visibility is assignment-based. Add a "Submit PL" permission row. App endpoints enforce lineage; Desk access remains native DocPerm only. |

### Business policy defaults (from PRD DEC-01..14)

- DEC-01 child groups: `true`, with B9 validation.
- DEC-02 partial delivery: `false` at pilot.
- DEC-03 short-pick approval: `true`.
- DEC-04 cross-group packing: `false`.
- DEC-05 draft print: `true`, with a DRAFT watermark.
- DEC-06 barcode: configurable; default `false` until hardware is confirmed.
- DEC-07 auto-create DN: `false`; operator clicks Create DN Draft.
- DEC-08 auto-submit DN: `false`; checker + dispatcher.
- DEC-09 print format per group.
- DEC-10 stock reservation: `off` for pilot; verify the installed site setting.
- DEC-11 Product Bundle: explicit exception until tested; non-stock blocked per B7.
- DEC-12 one SO per Run.
- DEC-13 direct print: out of MVP.
- DEC-14 Logistics handoff: read/event only.

## 7. Risks and open questions

| ID | Risk / question | Status |
|---|---|---|
| R0-01 | Splitting one native Pick List template into two disjoint PLs after `set_item_locations` may re-add rows on save. | Must prove in R0 runtime spike. |
| R0-02 | `create_dn_for_pick_lists` multi-PL path is proven by ERPNext tests, but not on the installed site with W31 and the app's user permissions. | Runtime spike. |
| R0-03 | Serial and Batch Bundle propagation from PL to DN is handled by a native method outside the sparse checkout. | Runtime spike with batch and serial fixtures. |
| R0-04 | `scan_mode = 1` blocks short pick; `scan_mode = 0` auto-fills zero picked qty. | Decision B5 + tests. |
| R0-05 | SO with `stock_reserved_qty > 0` blocks PL creation and submit. | Verify site setting; fail closed. |
| R0-06 | `create_dn_for_pick_lists` may return multiple DNs for different header groups. | Assert one; exception otherwise. |
| R0-07 | Packing Slip draft package state is not persisted by native; UI refresh loses in-progress package composition. | Design decision: ephemeral UI or persisted draft. |
| R0-08 | No Docker/bench/site on this host. | Blocks runtime gate and any mutation code merge. |

## 8. R0 runtime gate (must pass before R1 mutation code)

Run on a disposable ERPNext v16 site with `warehouse_app` and W31 installed, never on production:

1. Create a mixed SO (Dry + Frozen, at least one batch item, one UOM conversion item).
2. Generate two disjoint PLs from one `create_pick_list` template; assert no row overlap and correct `sales_order_item` / `item_group`.
3. Submit Dry PL with a full pick; submit Frozen PL with a short pick (`scan_mode = 0`, explicit qty); assert `picked_qty`, `custom_picked_qty`, SO `per_picked`, and no SLE.
4. Create one DN Draft via `create_dn_for_pick_lists` twice; assert one DN, one row per PL source, correct `against_pick_list` / `pick_list_item`, tax/address/currency fields preserved.
5. Create two Packing Slips from the DN Draft; assert `packed_qty` after submit; cancel one; assert `packed_qty` reverts.
6. Submit DN; assert SLE/stock ledger and SO `per_delivered`; assert no double posting.
7. Repeat with `scan_mode = 1` to confirm the short pick is rejected.
8. Run `w31_gate`, plus the new Dry/Frozen gate; teardown residue = 0.

## 9. Sources inspected

- ERPNext v16 `sales_order.py:2057-2135` (`create_pick_list`).
- ERPNext v16 `pick_list.py:100-316`, `492-728`, `994-1034`, `1418-1723`.
- ERPNext v16 `pick_list_item.json:50-293`.
- ERPNext v16 `delivery_note.py:1205-1256`, `315`.
- ERPNext v16 `delivery_note_item.json:623-956`.
- ERPNext v16 `packing_slip.py:50-263`; `packing_slip.json:178`.
- ERPNext v16 `test_pick_list.py:2468-2516` (`test_multiple_pick_lists_delivery_note`).
- `warehouse_app/hooks.py:198-209`.
- `warehouse_app/inventory_uom.py:187-259`.
- `warehouse_app/upgrade.py:908-1439`.
- `warehouse_app/tests/w31_gate.py`.
