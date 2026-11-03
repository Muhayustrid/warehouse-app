# SR UOM Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One module owns Stock Reconciliation per-UOM math so untouched rows never shift native `qty`/`valuation_rate`, and grid, Fetch Items, import, and submit agree.

**Architecture:** New `warehouse_app/sr_uom.py` (pure `compute_row` + doc-level `apply_to_doc`). A class extension (`extend_doctype_class`) calls it from `remove_items_with_no_change()` after posting time is final, replacing the `before_validate` hook. `get_items`, `sr_import`, and a new whitelisted endpoint reuse it; the W23 client script becomes a thin caller of that endpoint.

**Tech Stack:** Frappe/ERPNext v16 (Python 3), Desk client script (JS in a Python string in `upgrade.py`), host-side `unittest` with `production_app/production_app/tests/frappe_stub.py`, Node 22 `node:test` for the client script.

**Spec:** `docs/specs/2026-11-03-sr-uom-consolidation-design.md`

## Global Constraints

- All paths are relative to the warehouse_app repo root (`development/frappe-bench/apps/warehouse_app`).
- **Do not install, migrate, rebuild, or run anything against `dev.localhost`, `erp.localhost`, or any Docker stack.** Another agent is using them. Verification is host-side unit/functional tests only. Gate scripts (`tests/w*_gate.py`) are not run; they only need to compile (`python3 -m py_compile`).
- Spec §7 step 1 (reproduce on dev) and §4 (read-only draft query) are replaced by unit tests and a query written to the proof doc for the user to run later.
- **Do not commit.** Each task ends by reporting its diff; the orchestrator proposes commit messages to the user and commits only after approval. Commit format: `type(scope): deskripsi dalam bahasa Indonesia`.
- No new dependencies (Python or npm).
- Code comments in English; user-facing messages keep the existing English strings (W23 invalid-UOM message is Indonesian — keep it verbatim).
- `QTY_UOM_DECIMALS = 3`.
- Field names: `custom_uom`, `custom_conversion_factor`, `custom_qty_before`, `custom_qty_after`, `custom_valuation_rate_per_uom`, `custom_qty_difference_per_uom` (constants `SR_UOM_FIELD`, `SR_FACTOR_FIELD`, `SR_BEFORE_FIELD`, `SR_AFTER_FIELD`, `SR_RATE_FIELD`, `SR_DIFF_FIELD`).
- Do not touch pos_next. `HANDOFF_POS_NEXT_SR_UOM.md` documents its follow-up.
- Unit test run command (from repo root): `python3 -m unittest <module> -v`. Tests that need real rounding patch `warehouse_app.sr_uom.flt` with `lambda v, p=None: round(float(v or 0), p) if p is not None else float(v or 0)` (the stub `flt` ignores precision).

## Review Focus

1. Barcode scan bumps native `qty` by +1 → `custom_qty_after` resyncs and the endpoint reply does not change `qty` back (no ping-pong) — test in Task 5.
2. Stored `custom_valuation_rate_per_uom = 0.0` (silent zero) with `allow_zero_valuation_rate = 0` is treated as empty: `valuation_rate` untouched, display rate backfilled — test in Task 1.
3. One row with an invalid UOM among valid rows → `apply_to_doc` throws before any row is mutated — test in Task 1.
4. Posting time reset by native `validate_posting_time()` → Qty Before uses the final time because conversion runs inside `remove_items_with_no_change()` — test in Task 2.
5. Native `qty` empty on a new row whose `qty_after` rounds equal to ledger → `qty` is computed, not left empty — test in Task 1.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `warehouse_app/sr_uom.py` (new) | Constants, factor resolution, row math, doc-level apply | 1 |
| `warehouse_app/tests/test_sr_uom.py` (new) | Unit tests for `sr_uom` | 1 |
| `warehouse_app/inventory_uom.py` | Remove W23 block (`SR_*`, `_ledger_qty`, `apply_sr_inventory_uom`) | 1 (constants), 2 (function) |
| `warehouse_app/upgrade.py` | Import `SR_*` from `sr_uom` (Task 1); thin client script (Task 5) | 1, 5 |
| `warehouse_app/tests/w23_gate.py`, `w25_gate.py`, `w31_gate.py` | Import paths / direct hook call | 1, 2 |
| `warehouse_app/overrides/stock_reconciliation.py` (new) | `StockReconciliationUOM` class extension | 2 |
| `warehouse_app/hooks.py` | `extend_doctype_class`; drop SR doc event | 2 |
| `warehouse_app/tests/test_sr_class.py` (new) | Class extension tests | 2 |
| `warehouse_app/warehouse_app/stock_reconciliation.py` | `get_items` via `sr_uom`; endpoint `compute_row` | 3 |
| `warehouse_app/tests/test_sr_endpoints.py` (new) | `get_items` + endpoint tests | 3 |
| `warehouse_app/warehouse_app/sr_import.py` | `validate_count_rows` via `sr_uom` | 4 |
| `warehouse_app/tests/test_sr_import_uom.py` (new) | Import conversion tests | 4 |
| `warehouse_app/tests/sr_client_script.test.mjs` + `test_sr_client_script.py` (new) | Node functional test of the client script | 5 |
| `docs/proofs/2026-11-03-sr-uom-consolidation.md` (new), `PROJECT_STATE.md` | Proof + state | 6 |

**Execution order:** Task 1 alone → Tasks 2, 3, 4, 5 in parallel (disjoint files) → Task 6.

---

### Task 1: `sr_uom` module

**Files:**
- Create: `warehouse_app/sr_uom.py`, `warehouse_app/tests/test_sr_uom.py`
- Modify: `warehouse_app/inventory_uom.py:70-75` (delete `SR_*` constants; `apply_sr_inventory_uom` imports them from `sr_uom` until Task 2 deletes it), `warehouse_app/upgrade.py:366-371` (replace literals with `from warehouse_app.sr_uom import SR_...`), `warehouse_app/warehouse_app/stock_reconciliation.py:10-18` and `warehouse_app/warehouse_app/sr_import.py:54-62` (import `SR_*` from `warehouse_app.sr_uom`; `ITEM_UOM_FIELD` stays in `inventory_uom`), `tests/w23_gate.py:53`, `tests/w25_gate.py:61`, `tests/w31_gate.py:53` (same import move)

**Interfaces:**
- Produces (all in `warehouse_app.sr_uom`):
  - Constants `SR_UOM_FIELD … SR_DIFF_FIELD`, `QTY_UOM_DECIMALS = 3`.
  - `is_convertible(row) -> bool` — `item_code` and `custom_uom` set, `custom_qty_after not in (None, "")`, no `serial_no`, no `serial_and_batch_bundle`. `batch_no`/`use_serial_batch_fields` ignored.
  - `resolve_factors(pairs: Iterable[tuple[str, str, str]]) -> dict[tuple[str, str], float | None]` — pairs are `(item_code, uom, stock_uom)`; `1.0` when `uom == stock_uom`; else `conversion_factor` from one `frappe.get_all("UOM Conversion Detail", filters={"parent": ("in", items)}, fields=["parent","uom","conversion_factor"])`; `None` when missing or `<= 0`.
  - `ledger_qty(item_code, warehouse, posting_date, posting_time, cache: dict) -> float` — moved `_ledger_qty` (lazy `from erpnext.stock.stock_ledger import get_previous_sle`).
  - `precisions(row=None) -> dict[str, int]` — keys `qty`, `valuation_rate`, `rate_per_uom`; from `row.precision(...)` when given, else from `frappe.new_doc("Stock Reconciliation Item")`.
  - `compute_row(*, factor, ledger_qty, qty_after=None, rate_per_uom=None, qty=None, valuation_rate=None, allow_zero_valuation_rate=False, prec: dict) -> dict` with keys `custom_conversion_factor, custom_qty_before, custom_qty_after, custom_qty_difference_per_uom, custom_valuation_rate_per_uom, qty, valuation_rate`.
  - `apply_to_doc(doc) -> None` — converts every `is_convertible` row of `doc.items` in place using `doc.posting_date/posting_time`; throws the W23 invalid-UOM message (verbatim from `inventory_uom.py:159-163`) before mutating any row.

`compute_row` rules (spec §3.1):
- `before = flt(ledger_qty / factor, 3)`; `qty_after` empty → `qty_after = before` and, if `qty` empty, `qty = ledger_qty`.
- `qty` kept when not empty and `round(qty / factor, 3) == round(qty_after, 3)`; else `qty = flt(qty_after * factor, prec["qty"])`.
- `diff = flt(qty_after - before, 3)`.
- Rate is "set" when not empty and (`!= 0` or `allow_zero_valuation_rate`). Not set → `valuation_rate` unchanged; if `valuation_rate > 0`, `custom_valuation_rate_per_uom = flt(valuation_rate * factor, prec["rate_per_uom"])`, else returned as given. Set → keep `valuation_rate` when not empty and `round(valuation_rate * factor, prec["rate_per_uom"]) == round(rate_per_uom, prec["rate_per_uom"])`, else `valuation_rate = flt(rate_per_uom / factor, prec["valuation_rate"])`.

- [ ] **Step 1: Write failing tests** in `tests/test_sr_uom.py` (stub harness copied from `tests/test_inventory_company.py:25-45`; register `erpnext.stock.stock_ledger` stub with `get_previous_sle = MagicMock`; patch `sr_uom.flt` with real rounding; `P = {"qty": 6, "valuation_rate": 6, "rate_per_uom": 2}`):
  - `test_untouched_row_keeps_native_qty`: `compute_row(factor=12, ledger_qty=10, qty_after=0.833, qty=10, prec=P)["qty"] == 10`.
  - `test_changed_after_recomputes_qty`: `qty_after=1, qty=10` → `qty == 12`.
  - `test_empty_qty_is_computed`: `ledger_qty=10, qty_after=0.833, qty=None` → `qty == 9.996` (Review Focus 5).
  - `test_empty_after_prefills_from_ledger`: `qty_after=None, qty=None, ledger_qty=10` → `custom_qty_after == 0.833`, `qty == 10`, `custom_qty_difference_per_uom == 0`.
  - `test_rate_round_trip_kept`: `valuation_rate=1234.5678, rate_per_uom=14814.81` → `valuation_rate == 1234.5678`.
  - `test_rate_changed_recomputes`: `valuation_rate=1234.5678, rate_per_uom=1200` → `valuation_rate == 100`.
  - `test_silent_zero_rate_is_empty`: `rate_per_uom=0.0, allow_zero_valuation_rate=False, valuation_rate=100` → `valuation_rate == 100`, `custom_valuation_rate_per_uom == 1200` (Review Focus 2).
  - `test_explicit_zero_rate_allowed`: same with `allow_zero_valuation_rate=True` → `valuation_rate == 0`.
  - `test_before_and_diff`: `ledger_qty=84, factor=12, qty_after=2.5` → `custom_qty_before == 7`, `custom_qty_difference_per_uom == -4.5`, `qty == 30`.
  - `test_is_convertible`: serial_no → False; serial_and_batch_bundle → False; batch_no only → True; custom_uom empty → False; `custom_qty_after = None` → False; `0.0` → True.
  - `test_resolve_factors`: stock UOM → 1.0; table hit → value; missing → None; factor 0 → None; `frappe.get_all` called once.
  - `test_apply_to_doc_invalid_uom_atomic`: doc with a valid row and an invalid-UOM row → raises `frappe.ValidationError`; the valid row's `qty` is unchanged (Review Focus 3).
  - `test_apply_to_doc_uses_doc_posting_time`: `get_previous_sle` called with the doc's `posting_date`/`posting_time` at call time.

- [ ] **Step 2: Run** `python3 -m unittest warehouse_app.tests.test_sr_uom -v` → FAIL (`ModuleNotFoundError: warehouse_app.sr_uom`).
- [ ] **Step 3: Implement** `warehouse_app/sr_uom.py` per the interfaces above; move constants and update imports listed under Files.
- [ ] **Step 4: Run** the test module → all PASS; `python3 -m unittest warehouse_app.tests.test_inventory_company` → OK; `python3 -m py_compile warehouse_app/upgrade.py warehouse_app/inventory_uom.py warehouse_app/warehouse_app/*.py warehouse_app/tests/w2*_gate.py warehouse_app/tests/w31_gate.py` → no output.
- [ ] **Step 5: Report diff** (no commit). Proposed message: `refactor(stock-reconciliation): pusatkan matematika baris SR di modul sr_uom`.

---

### Task 2: Class extension replaces the doc event

**Files:**
- Create: `warehouse_app/overrides/stock_reconciliation.py`, `warehouse_app/tests/test_sr_class.py`
- Modify: `warehouse_app/hooks.py:201-203` (delete SR doc event), `hooks.py:241` area (add `extend_doctype_class = {"Stock Reconciliation": ["warehouse_app.overrides.stock_reconciliation.StockReconciliationUOM"]}`), `warehouse_app/inventory_uom.py:57-184` (delete W23 block: comment, `_ledger_qty`, `apply_sr_inventory_uom`), `warehouse_app/tests/w31_gate.py:58,523` (call `sr_uom.apply_to_doc(sr)` instead). Comment references to `apply_sr_inventory_uom` in `sr_import.py` and `upgrade.py` are updated by Tasks 4 and 5 (file ownership for parallel runs).

**Interfaces:**
- Consumes: `sr_uom.apply_to_doc(doc)`.
- Produces: `class StockReconciliationUOM(StockReconciliation)` (base imported from `erpnext.stock.doctype.stock_reconciliation.stock_reconciliation`) overriding only `remove_items_with_no_change(self)`: `apply_to_doc(self)` then `super().remove_items_with_no_change()`.

- [ ] **Step 1: Write failing tests** in `tests/test_sr_class.py` (stub module `erpnext.stock.doctype.stock_reconciliation.stock_reconciliation` with a fake `StockReconciliation` whose `validate()` sets `posting_time = "NOW"` then calls `self.remove_items_with_no_change()`, and whose `remove_items_with_no_change` records a call; fake `PosNextSR(StockReconciliation)` overriding `remove_items_with_no_change` to record and return without `super()` for drafts):
  - `test_converts_before_native_filter`: with `apply_to_doc` patched to record, calls order is `[apply_to_doc, native]`.
  - `test_uses_final_posting_time`: `apply_to_doc` sees `doc.posting_time == "NOW"` (Review Focus 4).
  - `test_mro_with_pos_next_override`: `type("X", (StockReconciliationUOM, PosNextSR), {})` (how Frappe composes it: extensions first, then the override class — `frappe/model/base_document.py:208,224`) — `remove_items_with_no_change()` calls `apply_to_doc` then PosNextSR's method.
  - `test_hooks_registration`: `warehouse_app.hooks.extend_doctype_class["Stock Reconciliation"] == ["warehouse_app.overrides.stock_reconciliation.StockReconciliationUOM"]` and `"Stock Reconciliation" not in warehouse_app.hooks.doc_events`.
  - `test_old_hook_removed`: `not hasattr(warehouse_app.inventory_uom, "apply_sr_inventory_uom")`.
- [ ] **Step 2: Run** `python3 -m unittest warehouse_app.tests.test_sr_class -v` → FAIL (module missing).
- [ ] **Step 3: Implement** the class and the hooks/inventory_uom/w31_gate edits listed under Files.
- [ ] **Step 4: Run** `test_sr_class`, `test_sr_uom`, `test_inventory_company` → PASS; py_compile `hooks.py`, `inventory_uom.py`, `tests/w31_gate.py` → no output.
- [ ] **Step 5: Report diff.** Proposed message: `fix(stock-reconciliation): konversi UOM lewat class extension setelah posting time final`.

---

### Task 3: `get_items` and the per-edit endpoint

**Files:**
- Modify: `warehouse_app/warehouse_app/stock_reconciliation.py`
- Create: `warehouse_app/tests/test_sr_endpoints.py`

**Interfaces:**
- Consumes: `sr_uom.resolve_factors`, `sr_uom.compute_row`, `sr_uom.precisions`, `sr_uom.ledger_qty`, constants.
- Produces:
  - `get_items(...)` — signature unchanged. For each row from native: skip serial/bundle rows (`serial_no`, `current_serial_no`, `serial_and_batch_bundle`) and items with `has_serial_no`; **batch rows are filled** (spec §3.3). UOM = item's `custom_default_inventory_unit_of_measure` or stock UOM; invalid factor → stock UOM, factor 1. Columns from `compute_row(factor, ledger_qty=row["qty"], qty_after=None, qty=row["qty"], valuation_rate=row["valuation_rate"], prec=precisions())`; native `qty`/`valuation_rate` in the row are not changed.
  - `@frappe.whitelist(methods=["POST"]) compute_row(item_code, warehouse, posting_date, posting_time, uom, qty_after=None, rate_per_uom=None, qty=None, valuation_rate=None, allow_zero_valuation_rate=0) -> dict` — `frappe.has_permission("Stock Reconciliation", "write", throw=True)`; factor via `resolve_factors`; `None` → `frappe.throw` with the W23 invalid-UOM message; ledger via `ledger_qty`; numeric args coerced with `flt` only when not `None`/`""`; returns `sr_uom.compute_row(...)` plus `custom_uom`. Import the module as `from warehouse_app import sr_uom` to avoid the name clash.

- [ ] **Step 1: Write failing tests** (`native_get_items` patched to return rows; `frappe.get_all` patched for Item and UOM Conversion Detail; real-rounding `flt`):
  - `test_fetch_round_trip_stable`: native row `qty=10, valuation_rate=1234.5678`, Pack=12 → row `custom_qty_after == 0.833`, `qty == 10`, `valuation_rate == 1234.5678`, `custom_valuation_rate_per_uom == 14814.81`; then `sr_uom.compute_row` on those stored values keeps `qty == 10` and `valuation_rate == 1234.5678`.
  - `test_fetch_fills_batch_rows`: row with `batch_no="B1"` gets `custom_uom`.
  - `test_fetch_skips_serial`: row with `serial_no` untouched.
  - `test_fetch_invalid_default_uom_falls_back`: default UOM missing from table → `custom_uom == stock_uom`, factor 1.
  - `test_endpoint_permission`: `frappe.has_permission` raising → endpoint raises, no ledger read.
  - `test_endpoint_invalid_uom_throws`.
  - `test_endpoint_prefill_and_change`: `qty_after=None` → `custom_qty_after == before`, `qty == ledger`; `qty_after="2.5"` → `qty == 30` (factor 12).
- [ ] **Step 2: Run** `python3 -m unittest warehouse_app.tests.test_sr_endpoints -v` → FAIL.
- [ ] **Step 3: Implement** both functions.
- [ ] **Step 4: Run** the module + `test_sr_uom` → PASS.
- [ ] **Step 5: Report diff.** Proposed message: `fix(stock-reconciliation): Fetch Items dan endpoint per-baris memakai sr_uom`.

---

### Task 4: Import Stock Count uses `sr_uom`

**Files:**
- Modify: `warehouse_app/warehouse_app/sr_import.py:453-716` (`validate_count_rows` only, plus comments at lines ~18/463 that name `apply_sr_inventory_uom` → `sr_uom.apply_to_doc`; `build_count_rows` keeps its own factor lookup — it only prefills the template)
- Create: `warehouse_app/tests/test_sr_import_uom.py`

**Interfaces:**
- Consumes: `sr_uom.resolve_factors`, `sr_uom.compute_row`, `sr_uom.precisions`, `sr_uom.ledger_qty`.
- Produces: `validate_count_rows(parsed, company, posting_date=None, posting_time=None)` — signature, error messages, matched-row tolerance `0.0005`, warnings, and returned keys unchanged. Invalid UOM = `resolve_factors(...)` returns `None` → existing per-row error. Grid row values come from `compute_row(factor, ledger_qty=current, qty_after=counted, rate_per_uom=rate, qty=None, valuation_rate=(None if rate is not None else (system_rate or None)), prec=precisions())`. `current_qty`/`current_valuation_rate`/`use_serial_batch_fields` stay as today. The `system_rate` snapshot (`get_previous_sle(...).valuation_rate`) stays local to this module.

- [ ] **Step 1: Write failing tests** (patch `frappe.get_all`/`frappe.get_cached_doc` as the existing function needs; `get_previous_sle` returns `{"qty_after_transaction": 10, "valuation_rate": 100}`):
  - `test_import_row_matches_class_math`: counted 1 Pack (12) → row `qty == 12`; feeding the row back through `sr_uom.compute_row` with stored `qty`/`valuation_rate` changes nothing.
  - `test_import_explicit_rate`: rate 1200 → `valuation_rate == 100`, `custom_valuation_rate_per_uom == 1200`.
  - `test_import_no_rate_uses_system_rate`: rate blank → `valuation_rate == 100`.
  - `test_import_invalid_uom_error_message`: unchanged message text `"Row {0}: UOM {1} is not valid for Item {2}…"`.
  - `test_import_matched_row_stripped`: counted 0.833 Pack vs ledger 10 → `matched == 1`, no rows.
- [ ] **Step 2: Run** `python3 -m unittest warehouse_app.tests.test_sr_import_uom -v` → FAIL on the new-math assertions.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the module + `test_sr_uom` → PASS; py_compile `tests/w25_gate.py`.
- [ ] **Step 5: Report diff.** Proposed message: `fix(stock-reconciliation): Import Stock Count memakai matematika sr_uom`.

---

### Task 5: Thin W23 client script

**Files:**
- Modify: `warehouse_app/upgrade.py:444-698` (`CLIENT_SCRIPT_STOCK_RECONCILIATION`), comment block `upgrade.py:356-363` (replace `apply_sr_inventory_uom` references with `sr_uom.apply_to_doc`)
- Create: `warehouse_app/tests/sr_client_script.test.mjs`, `warehouse_app/tests/test_sr_client_script.py`

**Interfaces:**
- Consumes: endpoint `warehouse_app.warehouse_app.stock_reconciliation.compute_row` (Task 3 signature) — called with `frappe.xcall(method, args)`.
- Produces: script keeping `SR_SCRIPT_MARKER`, role gate, `skip_row`, `apply_default_uom`, `apply_defaults`, `hide_native_qty_columns`, form `refresh`/`items_on_form_rendered`. New `sync_row(frm, cdt, cdn)`: sends `{item_code, warehouse, posting_date: frm.doc.posting_date, posting_time: frm.doc.posting_time, uom: custom_uom, qty_after: custom_qty_after, rate_per_uom: custom_valuation_rate_per_uom, qty, valuation_rate: valuation_rate || current_valuation_rate, allow_zero_valuation_rate}`; on reply, drops it if the row's `custom_uom`/`custom_qty_after`/`custom_valuation_rate_per_uom`/`warehouse` changed since the request; otherwise sets each returned field whose value differs. On rejection: `custom_uom = ""` (server message already shown by `xcall`).
- Child handlers: `custom_uom` (empty → existing clear behaviour from `upgrade.py:523-535`, else `sync_row` with `qty_after` omitted so the server prefills), `custom_qty_after`, `custom_valuation_rate_per_uom`, `warehouse` → `sync_row`; `qty` → if `round(qty / factor, 3) !== round(custom_qty_after, 3)` set `custom_qty_after = round(qty / factor, 3)` (its handler syncs). Removed: `allowed_uoms`/`UOM_CACHE`, `apply_uom` math, `current_qty` handler, epsilon guard, `get_conversion_factor` call.

- [ ] **Step 1: Write failing functional test.** `test_sr_client_script.py` writes `upgrade.CLIENT_SCRIPT_STOCK_RECONCILIATION` to a temp file and runs `node --test warehouse_app/tests/sr_client_script.test.mjs` with `SR_SCRIPT=<path>`; asserts exit code 0 (skip with `unittest.skipUnless(shutil.which("node"))`). The `.mjs` harness evaluates the script with mocks for `frappe` (`user.has_role → true`, `ui.form.on` captures handlers, `model.set_value` mutates `locals` and fires the captured child handler, `xcall` resolves a scripted reply, `after_ajax(fn) → fn()`, `db.get_value`), `locals`, `flt`, `__`. Cases:
  - `qty_after edit calls endpoint once and applies reply` (args include `posting_time` and `uom`).
  - `stale reply is ignored` (change `custom_qty_after` before the promise resolves).
  - `barcode +1 resyncs without ping-pong` (Review Focus 1): `qty` 12→13 with factor 12 → `custom_qty_after` 1.083, one endpoint call, reply `qty: 13` produces no further `set_value("qty")`.
  - `endpoint rejection clears custom_uom`.
  - `cleared UOM blanks derived fields and unsets qty/valuation_rate`.
  - `serial row is skipped` (no xcall).
- [ ] **Step 2: Run** `python3 -m unittest warehouse_app.tests.test_sr_client_script -v` → FAIL.
- [ ] **Step 3: Rewrite the script string** per the interface above; `node --check` on the dumped script passes.
- [ ] **Step 4: Run** the test → PASS.
- [ ] **Step 5: Report diff.** Proposed message: `refactor(stock-reconciliation): client script SR jadi pemanggil tipis endpoint server`.

---

### Task 6: Integration check, proof, state

**Files:**
- Create: `docs/proofs/2026-11-03-sr-uom-consolidation.md`
- Modify: `PROJECT_STATE.md` (head entry), `HANDOFF_POS_NEXT_SR_UOM.md` (only if implemented names differ from the handoff)

- [ ] **Step 1: Run everything:** `python3 -m unittest warehouse_app.tests.test_sr_uom warehouse_app.tests.test_sr_class warehouse_app.tests.test_sr_endpoints warehouse_app.tests.test_sr_import_uom warehouse_app.tests.test_sr_client_script warehouse_app.tests.test_inventory_company -v` → all OK; `python3 -m py_compile` on every changed `.py` → no output; `rg -n "apply_sr_inventory_uom|_ledger_qty" warehouse_app` → only historical comments, no code references.
- [ ] **Step 2: Cross-check handoff:** names/paths in `HANDOFF_POS_NEXT_SR_UOM.md` (`sr_uom.compute_row`, endpoint path, class name, consistency rule) match the code.
- [ ] **Step 3: Write proof doc** (Indonesian): test output, the 9.996 and 1234.5675 cases as passing tests, what was not verified (no site install, gates not run, Desk E2E pending), and the read-only SQL for spec §4 for the user to run later:
  ```sql
  select p.name, i.idx, i.item_code, i.qty, i.custom_qty_after, i.custom_conversion_factor
  from `tabStock Reconciliation Item` i join `tabStock Reconciliation` p on p.name = i.parent
  where p.docstatus = 0 and i.custom_uom is not null and i.custom_conversion_factor > 0
    and abs(i.qty - i.custom_qty_after * i.custom_conversion_factor) > 0;
  ```
- [ ] **Step 4: Update `PROJECT_STATE.md`** head entry (English, ≤ 80 lines total): what changed, tests, pending (deploy + gates + E2E, pos_next handoff must ship in the same image rebuild).
- [ ] **Step 5: Whole-branch review** with a fresh reviewer (`opus-xhigh`) against the spec; fix findings; report diff. Proposed message: `docs(stock-reconciliation): bukti konsolidasi UOM SR dan perbarui state`.
