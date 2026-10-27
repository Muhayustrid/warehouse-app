# F2 Settings + Fulfillment Run + Generate Pick Lists Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Configure the full per-Company Fulfillment Profile in `/gudang/settings`, then generate one Fulfillment Run with 0–1 native Draft Dry Pick List and 0–1 native Draft Frozen Pick List for an eligible Sales Order, idempotently and without stock movement.

**Architecture:** Extend the existing `warehouse_app` app. Native Sales Order/Pick List remain the source of truth. A thin service calls `create_pick_list` once, splits the unsaved template by SO Item group, inserts draft native PLs, and records Run/Request Key orchestration records. Profile configuration is exposed through the existing SPA Settings page and the existing Desk form remains a fallback. R0 runtime proof is a blocking prerequisite.

**Tech Stack:** Frappe/ERPNext v16, Python 3.14, Vue 3 SPA under `frontend/`, native Pick List, W31 server hooks.

**Spec:** `docs/superpowers/specs/2026-10-27-fulfillment-f2-settings-run-generate-design.md`

## Global Constraints

- Do not edit core Frappe/ERPNext.
- No `ignore_permissions=True` in user-facing endpoints.
- No stock-moving product code until the R0 runtime gate is green on `fulfillment.localhost`.
- F2 product code creates **draft** Pick Lists only; never set picked qty, submit PL, create DN/Packing, or submit stock.
- Do not change W31 `custom_picked_qty`, `inventory_uom.py`, or existing client scripts.
- Do not hardcode Company, Item Group, Warehouse, Customer, Role, Print Format, or document names.
- All configuration is per Company; Dry is every valid Item Group outside the configured Frozen group family.
- All test/mutation work happens on `fulfillment.localhost`; `erp.localhost` and `1oktober2026` are forbidden.
- Commit locally only with explicit user approval; push/merge is separate.
- Reuse existing project patterns: `warehouse_app/tests/*_gate.py`, `GATE_JSON`, `guard_site`, `upgrade.py` idempotent custom fields, `frontend/src/lib/api.js`, existing Settings CSS.
- Execution method and workspace approval are required before implementation. The local stack bind-mounts this repo, so a separate worktree needs its mounts re-pointed first.

## Review Focus

1. **Missing/invalid profile or Item Group:** Generate must fail closed with a row-level error, never silently classify as Dry.
2. **Split lineage:** every eligible SO Item must appear in exactly one group and one draft PL; no duplicate, missing, or cross-group row after save/reload.
3. **Idempotency:** same request key/payload replays the same Run/PL; mismatched payload and concurrent duplicate keys create no second document.
4. **Settings integrity:** all PRD fields save atomically, revisioned, Company-scoped, and writable only by the authorized role; invalid links cannot be persisted.
5. **No stock mutation in F2:** PLs stay draft, picked fields stay zero, and no SLE is created; only the R0 test fixture may move stock.

---

## File Structure

**New backend**
- `warehouse_app/tests/w49_f2_fixture.py` — disposable F2/R0 fixtures, stock/batch setup, cleanup.
- `warehouse_app/tests/w49_r0_gate.py` — native v16 R0 gate.
- `warehouse_app/tests/w49_f2_profile_gate.py` — full Profile schema/validation gate.
- `warehouse_app/tests/w49_f2_settings_gate.py` — Settings API/permission/revision gate.
- `warehouse_app/tests/w49_f2_schema_gate.py` — Run/Key/custom-field schema gate.
- `warehouse_app/tests/w49_f2_gate.py` — Generate acceptance gate.
- `warehouse_app/warehouse_app/fulfillment/settings_api.py` — profile read/save/options API.
- `warehouse_app/warehouse_app/fulfillment/generation.py` — pure pending qty, classification plan, split, snapshot; no Frappe.
- `warehouse_app/warehouse_app/fulfillment/idempotency.py` — scope/hash and Request Key lifecycle.
- `warehouse_app/warehouse_app/fulfillment/generate.py` — native adapter and Generate transaction.
- DocTypes: `warehouse_fulfillment_run`, `warehouse_fulfillment_run_item`, `warehouse_fulfillment_run_allocation`, `warehouse_fulfillment_request_key`.

**Modified backend**
- `warehouse_app/warehouse_app/doctype/warehouse_fulfillment_profile/warehouse_fulfillment_profile.json` and `.py` — full fields and validation.
- `warehouse_app/warehouse_app/fulfillment/api.py` — settings, generate, and read endpoints.
- `warehouse_app/warehouse_app/fulfillment/loader.py` — pending qty, Item master classification source, `can_generate`, Run summary, display names.
- `warehouse_app/warehouse_app/fulfillment/queue.py` — eligibility/helpers if needed; keep pure.
- `warehouse_app/warehouse_app/fulfillment/profile.py` — display names/profile payload.
- `warehouse_app/upgrade.py` — optional Pick List fulfillment custom fields.
- `warehouse_app/tests/w49_f1_fixture.py` — seed data for browser/generate acceptance.
- `TASKS.md`, `PROJECT_STATE.md`.

**Frontend**
- `frontend/src/data/settings.js` — settings fetch/save/options/link search.
- `frontend/src/pages/SettingsPage.vue` — Fulfillment panel with all fields.
- `frontend/src/data/fulfillment.js` — generate call.
- `frontend/src/components/FulfillmentDrawer.vue` — Generate button, result/links, errors.
- `frontend/src/pages/FulfillmentPage.vue` — display names and regenerated profile state.

**Tests**
- `warehouse_app/tests/test_fulfillment_generation.py` — pure generation rules.
- `warehouse_app/tests/test_fulfillment_idempotency.py` — pure scope/hash behavior.
- Existing F1 unit/gates remain regressions.

---

### Task 1: R0 runtime gate and fixtures

**Files:**
- Create: `warehouse_app/tests/w49_f2_fixture.py`
- Create: `warehouse_app/tests/w49_r0_gate.py`

**Interfaces:**
- Produces `seed_r0() -> dict`, `cleanup_r0() -> dict`, and `guard_site() -> None` in the fixture.
- Produces `run_gate() -> None`, printing exactly one `GATE_JSON:{...}` line.

- [ ] **Step 1: Write the failing R0 gate**

Create `w49_r0_gate.py` with `run_gate()` checking the following, initially failing because the fixture/native setup is absent:

- mixed SO: Dry + Frozen, batch item, UOM-conversion item, same item on two SO rows;
- one native template split into disjoint Dry/Frozen rows before first save;
- no row overlap, union equals expected eligible rows;
- Dry-only and Frozen-only produce one PL, never an empty PL;
- save/reload does not reintroduce cross-group rows;
- a mixed-warehouse/scope fixture proves the group either allocates correctly or is blocked explicitly; zero-location/shortage is not silent;
- full PL submit, short pick with `scan_mode=0`, one DN Draft from two PLs, two Packing Slips, DN submit, stock/SO assertions;
- `scan_mode=1` short pick rejected;
- teardown residue 0.

Run:
```powershell
cd C:\Users\LENOVO\frappe16
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_r0_gate.run_gate
```
Expected: FAIL / `ok: false` because the fixture is missing.

- [ ] **Step 2: Implement the fixture**

Use `w49_f1_fixture.bootstrap_base()` for the company/warehouse/UOM/customer base. Add dedicated `ZZTEST-W...` items, a Frozen child group, stock in the existing warehouse, at least one batch item, and a Box→Nos item. Track every created name in a module-level mapping. Implement `cleanup_r0()` in reverse dependency order and call `guard_site()` on every entry point. Do not reuse F1 items whose stock is needed by F1 acceptance.

- [ ] **Step 3: Implement the native gate**

Implement the gate using native `create_pick_list`, `pick_manually` variants, `submit`, `create_dn_for_pick_lists`, `make_packing_slip`, and W31 hooks. Split the unsaved template before the first insert. Assert the exact row sets with `sales_order_item`, not item-code sums. Print one final `GATE_JSON` and no raw fixture dump.

- [ ] **Step 4: Run R0 and W31**

Run the R0 gate and:
```powershell
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w31_gate.run_gate
```
Expected: both `GATE_JSON:{"ok": true, ...}`; teardown residue 0. If mixed warehouse or zero-stock behavior fails, fix the fixture/test assumptions before Task 2; do not write F2 product code.

- [ ] **Step 5: Commit**

```bash
git add warehouse_app/tests/w49_f2_fixture.py warehouse_app/tests/w49_r0_gate.py
git commit -m "test(fulfillment): add F2 R0 native gate"
```

---

### Task 2: Full Profile schema and validation

**Files:**
- Modify: `warehouse_app/warehouse_app/doctype/warehouse_fulfillment_profile/warehouse_fulfillment_profile.json`
- Modify: `warehouse_app/warehouse_app/doctype/warehouse_fulfillment_profile/warehouse_fulfillment_profile.py`
- Create: `warehouse_app/tests/w49_f2_profile_gate.py`

**Interfaces:**
- Produces the complete Profile field set from spec §4.1, including `config_revision`.
- Consumes `classification.validate_profile_config`.
- No new public Python function is required; validation lives on the controller.

- [ ] **Step 1: Write the failing profile gate**

Create `w49_f2_profile_gate.run_gate()` with checks:
- a full profile saves with all fields, defaults, `config_revision=1`;
- saving again increments revision to 2;
- blank display names rejected;
- enabled without Frozen Item Group rejected;
- parent group with children + include off rejected;
- Print Format not for Pick List rejected;
- warehouse from another company rejected;
- unknown Role rejected;
- duplicate Company rejected;
- `config_revision` is not accepted from client input.

Run:
```powershell
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_f2_profile_gate.run_gate
```
Expected: FAIL because fields/validation are missing.

- [ ] **Step 2: Add the DocType fields**

Add all fields and defaults from spec §4.1. Keep `company` as the unique auto-name. Add `config_revision` as read-only Int. Keep the existing Profile permissions; do not add write access for Stock User.

- [ ] **Step 3: Implement controller validation and revisioning**

Extend `validate()` for display names, print-format `doc_type`, company-scoped warehouses, roles, paper size, copies, shelf life, and existing Frozen group rules. Increment `config_revision` in a save hook: new record starts at 1, existing record increments by 1. Do not allow client values to set the revision. Preserve existing duplicate-company and fail-closed behavior.

- [ ] **Step 4: Migrate and run the gate**

```powershell
docker compose exec -T backend bench --site fulfillment.localhost migrate
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_f2_profile_gate.run_gate
```
Expected: `GATE_JSON:{"ok": true, ...}`.

- [ ] **Step 5: Commit**

```bash
git add warehouse_app/warehouse_app/doctype/warehouse_fulfillment_profile warehouse_app/tests/w49_f2_profile_gate.py
git commit -m "feat(fulfillment): expand profile settings schema"
```

---

### Task 3: Settings backend API

**Files:**
- Create: `warehouse_app/warehouse_app/fulfillment/settings_api.py`
- Modify: `warehouse_app/warehouse_app/fulfillment/api.py`
- Create: `warehouse_app/tests/w49_f2_settings_gate.py`

**Interfaces:**
- Produces:
  - `get_fulfillment_settings(company=None) -> dict`
  - `save_fulfillment_settings(payload) -> dict`
  - `fulfillment_settings_options(company=None) -> dict`
- `payload` is a dict or JSON string containing all editable Profile fields plus `expected_modified` (or `expected_revision`).
- Whitelisted wrappers live in `fulfillment/api.py`; writes are POST-only.

- [ ] **Step 1: Write the failing settings gate**

Create `w49_f2_settings_gate.run_gate()` with a temporary full profile and temporary Stock User:
- System Manager can read/save all fields;
- returned `config_revision` increments;
- stale `expected_modified` returns a clear conflict and does not save;
- Stock User can read but gets `PermissionError` on save;
- invalid Print Format/warehouse/role is rejected;
- options are Company-scoped and Print Formats are filtered to `Pick List`;
- Company selector contains only readable Companies;
- no `ignore_permissions` is needed for the endpoint.

Run:
```powershell
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_f2_settings_gate.run_gate
```
Expected: FAIL because the API is missing.

- [ ] **Step 2: Implement the settings API**

Parse a JSON string safely, reject unknown fields, require System Manager for writes, compare expected revision/modified, set only whitelisted fields, call `doc.save()`, commit, and return a serialized profile with the new revision. Use `frappe.get_doc` and permission enforcement; do not use `frappe.db.set_value` for validated fields or `ignore_permissions`.

- [ ] **Step 3: Add options endpoint**

Return Company-scoped warehouses (group and leaf), enabled Roles, and Print Formats with `doc_type = Pick List`. Item Group selection uses native link search in the UI; the server still validates the saved link.

- [ ] **Step 4: Run the gate**

Expected: `GATE_JSON:{"ok": true, ...}`; no temporary user/session/activity residue.

- [ ] **Step 5: Commit**

```bash
git add warehouse_app/warehouse_app/fulfillment/settings_api.py warehouse_app/warehouse_app/fulfillment/api.py warehouse_app/tests/w49_f2_settings_gate.py
git commit -m "feat(fulfillment): add profile settings API"
```

---

### Task 4: Settings SPA panel

**Files:**
- Modify: `frontend/src/data/settings.js`
- Modify: `frontend/src/pages/SettingsPage.vue`

**Interfaces:**
- Consumes the three settings endpoints from Task 3.
- Produces a Fulfillment panel in the existing `/gudang/settings` page; no new route.

- [ ] **Step 1: Add data-layer calls**

Add `fetchFulfillmentSettings(company)`, `saveFulfillmentSettings(payload)`, `fetchFulfillmentOptions(company)`, and a generic `searchLink(doctype, txt)` using the existing `callGet`; keep the existing handover functions.

- [ ] **Step 2: Implement the panel**

Add sections from spec §5: Context, Classification, Warehouses, Print, Policies, Roles. Show all fields from spec §4.1, including later-phase help text. Use a Company selector, Frozen Item Group link search, and options for warehouses/roles/print formats. Display `config_revision` read-only. Disable editing when `can_edit=false`. Save in one profile request and keep the existing handover panel/save behavior independent.

- [ ] **Step 3: Build**

Run from `frontend/`:
```powershell
npm.cmd run build
```
Expected: exit 0, output in `warehouse_app/public/gudang/` and `www/gudang.html`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/data/settings.js frontend/src/pages/SettingsPage.vue warehouse_app/public/gudang warehouse_app/www/gudang.html
git commit -m "feat(fulfillment): add profile settings panel"
```

---

### Task 5: Run, Request Key, and custom-field schema

**Files:**
- Create: `warehouse_app/warehouse_app/doctype/warehouse_fulfillment_run/`
- Create: `warehouse_app/warehouse_app/doctype/warehouse_fulfillment_run_item/`
- Create: `warehouse_app/warehouse_app/doctype/warehouse_fulfillment_run_allocation/`
- Create: `warehouse_app/warehouse_app/doctype/warehouse_fulfillment_request_key/`
- Modify: `warehouse_app/upgrade.py`
- Create: `warehouse_app/tests/w49_f2_schema_gate.py`

**Interfaces:**
- Produces the DocTypes and child table fields from spec §6.1–§6.4.
- Produces optional Pick List custom fields `custom_fulfillment_run` and `custom_fulfillment_group` through executable `upgrade.py` specs.

- [ ] **Step 1: Write the failing schema gate**

Create `w49_f2_schema_gate.run_gate()` that checks:
- all four DocTypes exist with required fields;
- `active_so_key` and `scope_key` are unique fields;
- Run Item/Allocation are child tables;
- DocPerms allow System Manager/Stock Manager create/read and Stock User read;
- Pick List custom fields exist, are optional, and `custom_fulfillment_group` has `Dry`/`Frozen`;
- W31 `custom_picked_qty` is still present and unchanged.

Run:
```powershell
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_f2_schema_gate.run_gate
```
Expected: FAIL because the schema is missing.

- [ ] **Step 2: Add DocTypes**

Create the four DocTypes with fields exactly from spec §6.1–§6.4. Use non-submittable orchestration DocTypes. Add no stock/accounting fields. Set `active_so_key` nullable unique and `scope_key` unique. Keep Run/Key permissions least-privilege as specified. After the Run DocType exists, update the Profile controller to reject changing `company` when any Run references the profile; add this assertion to the schema gate using a temporary Run fixture.

- [ ] **Step 3: Add custom fields idempotently**

Add two `Custom Field` specs to `upgrade.py`, using `_ensure_custom_field` and a new `ensure_pl_fulfillment_fields()` called from `apply()`. The fields are optional, placed sensibly on Pick List, and must not affect W31. Clear Pick List caches after creation/update.

- [ ] **Step 4: Migrate and run the schema gate**

```powershell
docker compose exec -T backend bench --site fulfillment.localhost migrate
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_f2_schema_gate.run_gate
```
Expected: `GATE_JSON:{"ok": true, ...}`.

- [ ] **Step 5: Commit**

```bash
git add warehouse_app/warehouse_app/doctype/warehouse_fulfillment_run* warehouse_app/warehouse_app/doctype/warehouse_fulfillment_request_key warehouse_app/upgrade.py warehouse_app/tests/w49_f2_schema_gate.py
git commit -m "feat(fulfillment): add Run and request-key schema"
```

---

### Task 6: Pure generation rules

**Files:**
- Create: `warehouse_app/warehouse_app/fulfillment/generation.py`
- Create: `warehouse_app/tests/test_fulfillment_generation.py`

**Interfaces:**
- Produces:
  - `pending_stock_qty(qty, picked_qty, delivered_qty, conversion_factor) -> float`
  - `build_generation_plan(items: Iterable[Mapping], frozen: set[str]) -> dict`
  - `split_locations(locations: Iterable[Mapping], group_by_so_item: Mapping[str, str]) -> dict[str, list[dict]]`
  - `profile_policy_snapshot(profile: Mapping) -> dict`
- No Frappe imports. `build_generation_plan` returns `{"items": [...], "groups": {"dry": [...], "frozen": [...]}}`; raises `GenerationError(code, row)` for missing Item Group, missing SO Item reference, or invalid conversion.
- `split_locations` returns group keyed lists; raises on a location whose `sales_order_item` is not in the group map.

- [ ] **Step 1: Write failing unit tests**

Add tests for:
- native pending formula with picked/delivered/conversion combinations;
- one item on two SO rows stays two plan rows;
- Dry/Frozen assignment from current Item master group;
- missing Item Group raises, never Dry;
- Dry-only/Frozen-only/empty group shapes;
- split has no overlap and preserves multiple locations per SO Item;
- unknown location row raises;
- policy snapshot includes classification, policy flags, warehouse scopes, and profile revision.

Run:
```powershell
docker compose exec -T backend sh -lc "cd /home/frappe/frappe-bench/apps/warehouse_app && /home/frappe/frappe-bench/env/bin/python -m unittest warehouse_app.tests.test_fulfillment_generation -v"
```
Expected: import failure.

- [ ] **Step 2: Implement the pure module**

Implement the signatures above. Keep the module free of Frappe imports and document failures with stable codes. Do not aggregate by item code. Do not use item group names as prefixes.

- [ ] **Step 3: Run unit tests**

Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add warehouse_app/warehouse_app/fulfillment/generation.py warehouse_app/tests/test_fulfillment_generation.py
git commit -m "feat(fulfillment): add pure generate planning"
```

---

### Task 7: Idempotency lifecycle

**Files:**
- Create: `warehouse_app/warehouse_app/fulfillment/idempotency.py`
- Create: `warehouse_app/tests/test_fulfillment_idempotency.py`
- Modify: `warehouse_app/tests/w49_f2_gate.py` (integration later; this task adds the helper contract)

**Interfaces:**
- Produces:
  - `scope_key(actor, company, sales_order, request_type, idempotency_key) -> str`
  - `request_hash(sales_order, expected_so_modified, request_type) -> str`
  - `begin_request(actor, company, sales_order, request_type, key, request_hash) -> dict`
  - `complete_request(scope, result_refs: list[str]) -> None`
  - `fail_request(scope, code: str, message: str) -> None`
  - `get_request(scope) -> dict | None`
- `begin_request` returns `{"state": "new"|"replay"|"in_progress"|"mismatch", "run": ..., "request": ...}` and uses the DB-unique `scope_key`.

- [ ] **Step 1: Write failing unit tests**

Test deterministic scope/hash output and mismatch behavior. Run:
```powershell
docker compose exec -T backend sh -lc "cd /home/frappe/frappe-bench/apps/warehouse_app && /home/frappe/frappe-bench/env/bin/python -m unittest warehouse_app.tests.test_fulfillment_idempotency -v"
```
Expected: import failure.

- [ ] **Step 2: Implement scope/hash and DB lifecycle**

Use stable SHA-256 over normalized strings. Reserve the Request Key with a separate commit, store `PENDING`, handle duplicate scope by returning replay/in-progress/mismatch, and never use a Redis-only lock. Completed results are immutable; pending keys expire after 24 hours.

- [ ] **Step 3: Run tests**

Expected: all PASS. Add integration assertions to `w49_f2_gate` in Task 8.

- [ ] **Step 4: Commit**

```bash
git add warehouse_app/warehouse_app/fulfillment/idempotency.py warehouse_app/tests/test_fulfillment_idempotency.py
git commit -m "feat(fulfillment): add request-key idempotency"
```

---

### Task 8: Native Generate service, endpoint, and F1 alignment

**Files:**
- Create: `warehouse_app/warehouse_app/fulfillment/generate.py`
- Modify: `warehouse_app/warehouse_app/fulfillment/api.py`
- Modify: `warehouse_app/warehouse_app/fulfillment/loader.py`
- Modify: `warehouse_app/warehouse_app/fulfillment/queue.py` only if a pure helper is needed
- Modify: `warehouse_app/warehouse_app/fulfillment/profile.py`
- Modify: `warehouse_app/tests/w49_f2_fixture.py`
- Create: `warehouse_app/tests/w49_f2_gate.py`

**Interfaces:**
- Produces `generate_fulfillment_run(sales_order, idempotency_key, expected_so_modified, actor=None) -> dict`.
- Wholly whitelisted POST: `generate_fulfillment_run` in `fulfillment/api.py`.
- `get_order_preview` adds `can_generate`, `can_generate_reason`, `run`, and `modified`.
- `get_order_queue` adds profile display names and `can_generate`/reason.
- Consumes Tasks 5–7 and F1 classification.

- [ ] **Step 1: Write the failing F2 gate**

Add `w49_f2_gate.run_gate()` covering:
- full-profile Generate happy path: one Run, correct Dry/Frozen draft PLs, no picked qty, no stock movement;
- Dry-only and Frozen-only: one PL and one null group;
- same key/payload replay returns same Run/PL; different payload 409; active Run reuse; duplicate bypass attempt rejected by DB;
- stale SO, reservation, non-stock/bundle, missing Item Group, stock shortage, invalid profile, and insufficient permissions;
- rollback when the second PL insert is forced to fail (monkeypatch only inside the gate);
- F1 preview `can_generate` and display names;
- no stock/SLE changes from Generate;
- teardown residue 0.

Run:
```powershell
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_f2_gate.run_gate
```
Expected: FAIL because the service/endpoint is missing.

- [ ] **Step 2: Implement preflight and native split**

Implement `generate.py` with the preflight from spec §7.1. Resolve Item Groups from current Item master; use `pending_stock_qty`; call `create_pick_list` once; split before first insert; copy the native template per group; preserve headers; set optional custom fields; block on missing/insufficient locations; never set picked quantities or submit. Use normal permissions.

- [ ] **Step 3: Implement Run/Key transaction**

Use `idempotency.begin_request`, `active_so_key` uniqueness, and one transaction for Run, Run Items, Allocations, and PLs. Complete the key only after all documents exist. On failure mark the key failed and return a safe error. Return `reused=true` for active/replayed Runs.

- [ ] **Step 4: Align F1 preview/queue**

Use the native pending formula, current Item master Item Group, On Hold/`per_picked` preflight reasons, and profile display names. Add `can_generate=false` with a reason for any preflight blocker. Preserve F1 stage priorities and read-only behavior.

- [ ] **Step 5: Run F2 gate**

Expected: `GATE_JSON:{"ok": true, ...}`; no residue.

- [ ] **Step 6: Commit**

```bash
git add warehouse_app/warehouse_app/fulfillment/generate.py warehouse_app/warehouse_app/fulfillment/api.py warehouse_app/warehouse_app/fulfillment/loader.py warehouse_app/warehouse_app/fulfillment/queue.py warehouse_app/warehouse_app/fulfillment/profile.py warehouse_app/tests/w49_f2_fixture.py warehouse_app/tests/w49_f2_gate.py
git commit -m "feat(fulfillment): generate draft dry/frozen pick lists"
```

---

### Task 9: Generate UI, final gates, and evidence

**Files:**
- Modify: `frontend/src/data/fulfillment.js`
- Modify: `frontend/src/components/FulfillmentDrawer.vue`
- Modify: `frontend/src/pages/FulfillmentPage.vue` if display names/can_generate require it
- Modify: `TASKS.md`, `PROJECT_STATE.md`

**Interfaces:**
- Consumes `generate_fulfillment_run`, preview `can_generate`/`run`, and profile display names.
- Produces the visible Generate action and result links; no picking/submit actions.

- [ ] **Step 1: Add the Generate client call**

Add `generateFulfillmentRun({ salesOrder, idempotencyKey, expectedSoModified })` using `call` (POST). Keep the key stable for the current attempt and reuse it on network retry.

- [ ] **Step 2: Wire the drawer**

Show Generate only when preview says it is allowed and the profile is enabled. Disable while running, show a confirmation/result state with Run and PL links, handle `reused=true`, and render each safe error code as an actionable message. Reload the preview after success. Link the Run to `/app/warehouse-fulfillment-run/<name>` and each PL to its native Desk form; do not add picking or submit controls.

- [ ] **Step 3: Build**

```powershell
cd frontend
npm.cmd run build
```
Expected: exit 0.

- [ ] **Step 4: Browser acceptance**

Use a temporary Stock Manager/System Manager session on `fulfillment.localhost`; verify:
- Settings panel loads all sections, saves all fields, revision changes, and non-admin is read-only;
- queue drawer shows Generate only when allowed;
- Generate produces Run + Dry/Frozen draft PL links and no stock change;
- replay/error/disabled states;
- F1 queue/drawer/search/date/stage regressions;
- no horizontal overflow at 1440/1024/390; console errors 0;
- test user/session/activity residue 0.

- [ ] **Step 5: Run final gates**

```powershell
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_r0_gate.run_gate
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_f2_profile_gate.run_gate
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_f2_settings_gate.run_gate
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_f2_schema_gate.run_gate
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_f2_gate.run_gate
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w31_gate.run_gate
docker compose exec -T backend sh -lc "cd /home/frappe/frappe-bench/apps/warehouse_app && /home/frappe/frappe-bench/env/bin/python -m unittest warehouse_app.tests.test_fulfillment_classification warehouse_app.tests.test_fulfillment_queue warehouse_app.tests.test_fulfillment_generation warehouse_app.tests.test_fulfillment_idempotency -v"
```
Expected: all gates `ok: true`, 0 test failures, teardown 0.

- [ ] **Step 6: Update docs and commit**

Record only executed evidence in `TASKS.md` W50 and `PROJECT_STATE.md`. Mark F2 DONE only after every gate above is green. Commit:
```bash
git add frontend/src/data/fulfillment.js frontend/src/components/FulfillmentDrawer.vue frontend/src/pages/FulfillmentPage.vue warehouse_app/public/gudang warehouse_app/www/gudang.html TASKS.md PROJECT_STATE.md
git commit -m "feat(fulfillment): add generate pick lists action"
```

## Self-Review Notes

- The spec’s later-phase fields are present but explicitly optional-now; no task claims their behavior is implemented.
- Task 1 is the only stock-moving test path; all product F2 paths remain draft-only.
- Task 8 owns the native split and transaction; Task 6’s pure tests pin the same row-level rules without Frappe.
- Task 9 is the only browser gate; Task 4 only builds the Settings panel. The final gate re-runs all earlier gates.
- Execution method/workspace approval remains required because the repo is bind-mounted into the test stack.
