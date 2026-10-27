# Fulfillment Module Implementation Plan (Post-R0)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a safe, feature-flagged Fulfillment foundation by 2026-11-01: R0 evidence, decision baseline, classification core, and a read-only Order Queue. No stock-moving action in this window.

**Architecture:** Extend the existing `warehouse_app` custom app. Keep ERPNext native documents as the source of truth. Use a thin adapter over native `create_pick_list`, `create_dn_for_pick_lists`, and `make_packing_slip`; do not rebuild financial mapping. The SPA is a read-only client for the first release.

**Tech Stack:** Frappe/ERPNext v16, Python 3.14, Vue 3 SPA under `frontend/`, native Pick List / Delivery Note / Packing Slip, W31 UOM hooks.

**Spec:** `FULFILLMENT_R0_DISCOVERY.md` plus `PRD_Warehouse_Fulfillment_ERPNext_v16.md`.

**Current status (2026-10-26):** R0 static documents complete; classification core + 17 unit tests PASS. R0 runtime gate and all stock-moving tasks remain blocked on a disposable ERPNext v16 + W31 site.

## Global Constraints

- Do not edit core Frappe/ERPNext.
- Do not use `ignore_permissions=True` on user-facing endpoints.
- Custom fields go through `warehouse_app/upgrade.py`, idempotent, optional on native doctypes.
- Do not change W31 `custom_picked_qty` or existing client scripts without a W31 gate run.
- `commit` on local `main` only; push/merge only on explicit user request.
- No stock-moving code (Pick List creation, DN creation, Packing Slip, DN submit) before the R0 runtime gate passes.
- Feature flag: `Warehouse Fulfillment Profile.enabled`; start with no profile in production.

## Deadline Scope — 2026-11-01

**In scope and safe:**

1. R0 static discovery and decision baseline (this document set).
2. R0 runtime gate **only if** a disposable v16 + W31 site is available.
3. Classification core as pure Python with unit tests.
4. Profile DocType + validation, feature-flagged off.
5. Read-only Order Queue API and SPA page, no mutation endpoints.

**Out of scope before 2026-11-01:**

- Generate Pick Lists.
- Save picking progress.
- Create Delivery Note Draft.
- Create/submit Packing Slip.
- Submit Delivery Note.
- Any production deploy.

If the runtime gate cannot run, stop after item 3 and keep the rest as a reviewed plan.

## Review Focus

- A parent Frozen Item Group with children but `include_child_item_groups = 0`: must fail closed, not classify everything Dry.
- A missing/renamed Item Group on an SO row: must block the row, not silently skip.
- A Dry-only or Frozen-only SO: must not create an empty group.
- A short pick with `scan_mode = 0`: must persist an explicit qty; zero means "not picked".
- A short pick with `scan_mode = 1`: must be rejected by native validation, not bypassed.
- Two Pick Lists from one SO: no row may appear in both; per-SO-item references must stay distinct.
- A second Generate call with the same key: must return the same Run/PL, never a duplicate.

---

### Task 1: R0 runtime gate

**Files:**
- Create: `warehouse_app/tests/w49_r0_gate.py`
- Reference: `warehouse_app/tests/w31_gate.py`, `warehouse_app/tests/guard.py`

**Interfaces:**
- Consumes: native `create_pick_list`, `create_dn_for_pick_lists`, `make_packing_slip`.
- Produces: `run_gate() -> None` printing exactly one `GATE_JSON:{...}` line, following the W31 gate convention.

- [ ] **Step 1: Write the failing gate**

Create a Frappe gate that builds a mixed SO, creates one native Pick List template, splits it into Dry/Frozen, submits both, creates one DN via `create_dn_for_pick_lists`, creates two Packing Slips, submits the DN, and asserts stock/SO/PL/DN/PS quantities.

- [ ] **Step 2: Run the gate on a disposable site**

Run:

```bash
bench --site <test-site> execute warehouse_app.tests.w49_r0_gate.run_gate
```

Expected: `GATE_JSON:{"ok": true, ...}`. If it fails, fix the adapter assumptions in `FULFILLMENT_R0_DISCOVERY.md` before writing production code.

- [ ] **Step 3: Run W31 regression**

```bash
bench --site <test-site> execute warehouse_app.tests.w31_gate.run_gate
```

Expected: `ok: true`.

- [ ] **Step 4: Record evidence**

Append the command, site name, result, and any deviation to `TASKS.md` W49. Do not mark runtime done if the gate was not executed.

- [ ] **Step 5: Commit**

```bash
git add warehouse_app/tests/w49_r0_gate.py TASKS.md
git commit -m "test(fulfillment): add R0 native v16 flow gate"
```

### Task 2: Classification core

**Files:**
- Create: `warehouse_app/warehouse_app/fulfillment/__init__.py`
- Create: `warehouse_app/warehouse_app/fulfillment/classification.py`
- Create: `warehouse_app/tests/test_fulfillment_classification.py`

**Interfaces:**
- Produces:
  - `validate_profile_config(configured_group: str, group_is_group: bool, has_children: bool, include_children: bool) -> None`
  - `frozen_groups(configured_group: str, descendants: list[str], include_children: bool) -> set[str]`
  - `classify(item_group: str, frozen: set[str]) -> str` returning exactly `"dry"` or `"frozen"`.

- [x] **Step 1: Write failing tests**

Cover:
- exact Frozen group → `frozen`;
- child group with `include_children = true` → `frozen`;
- child group with `include_children = false` → `dry`;
- parent group with children and flag false → raises configuration error;
- empty configured group → raises;
- missing item group → raises.

- [x] **Step 2: Run the tests to verify they fail**

```bash
py -m unittest warehouse_app.tests.test_fulfillment_classification -v
```

Expected: import/attribute failure.

- [x] **Step 3: Implement the pure functions**

Keep this module free of `frappe` imports so it can run outside a bench. Do not add caching or database access here.

- [x] **Step 4: Run the tests to verify they pass**

```bash
py -m unittest warehouse_app.tests.test_fulfillment_classification -v
```

Expected: all tests PASS.

**Evidence (2026-10-26):** 17 tests, all PASS.

- [ ] **Step 5: Commit**

```bash
git add warehouse_app/warehouse_app/fulfillment/__init__.py warehouse_app/warehouse_app/fulfillment/classification.py warehouse_app/tests/test_fulfillment_classification.py
git commit -m "feat(fulfillment): add fail-closed item group classification"
```

### Task 3: Profile DocType and validation

**Files:**
- Create: `warehouse_app/warehouse_app/doctype/warehouse_fulfillment_profile/warehouse_fulfillment_profile.json`
- Create: `warehouse_app/warehouse_app/doctype/warehouse_fulfillment_profile/warehouse_fulfillment_profile.py`
- Create: `warehouse_app/warehouse_app/doctype/warehouse_fulfillment_profile/__init__.py`
- Modify: `warehouse_app/upgrade.py` only if a custom field is required (none expected).

**Interfaces:**
- Consumes: `classification.validate_profile_config`.
- Produces: one Profile per company, `enabled`, `frozen_item_group`, display names, warehouse scopes, print formats, policy flags, role links, `config_revision`.

- [ ] **Step 1: Write the failing validation test**

Add a gate assertion: saving a Profile whose `frozen_item_group` is a parent group with children and `include_child_item_groups = 0` raises `ValidationError`.

- [ ] **Step 2: Run the test to verify it fails**

```bash
bench --site <test-site> execute warehouse_app.tests.w49_r0_gate.run_gate
```

Expected: missing DocType or validation failure.

- [ ] **Step 3: Implement the DocType and controller**

Validation:
- company required and unique;
- frozen group exists;
- parent group + children + flag false → throw;
- print format DocType is Pick List;
- warehouse belongs to company;
- roles exist;
- `enabled` does not change historical Runs.

- [ ] **Step 4: Migrate and run the test**

```bash
bench --site <test-site> migrate
bench --site <test-site> execute warehouse_app.tests.w49_r0_gate.run_gate
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add warehouse_app/warehouse_app/doctype/warehouse_fulfillment_profile warehouse_app/upgrade.py
git commit -m "feat(fulfillment): add profile doctype with fail-closed validation"
```

### Task 4: Request Key and idempotency helper

**Files:**
- Create: `warehouse_app/warehouse_app/doctype/warehouse_fulfillment_request_key/...`
- Create: `warehouse_app/warehouse_app/fulfillment/idempotency.py`
- Test: `warehouse_app/tests/w49_r0_gate.py`

**Interfaces:**
- Produces:
  - `begin_request(actor, company, request_type, key, request_hash) -> RequestKey`
  - `complete_request(key, doc_refs: list[str]) -> None`
  - `get_existing_result(key) -> dict | None`

- [ ] **Step 1: Write failing test**

Two calls with the same key must return the same result reference and create no second document. A different key must create a new request.

- [ ] **Step 2: Run to fail**

```bash
bench --site <test-site> execute warehouse_app.tests.w49_r0_gate.run_gate
```

Expected: missing DocType/helper.

- [ ] **Step 3: Implement DocType and helper**

Unique key on `idempotency_key`; scope includes actor/company/request type; TTL 24h; completed keys store document refs.

- [ ] **Step 4: Run to pass**

Expected: PASS; duplicate key returns the same reference.

- [ ] **Step 5: Commit**

```bash
git add warehouse_app/warehouse_app/doctype/warehouse_fulfillment_request_key warehouse_app/warehouse_app/fulfillment/idempotency.py warehouse_app/tests/w49_r0_gate.py
git commit -m "feat(fulfillment): add database-backed request idempotency"
```

### Task 5: Read-only Order Queue API

**Files:**
- Create: `warehouse_app/warehouse_app/fulfillment/eligibility.py`
- Create: `warehouse_app/warehouse_app/fulfillment/api.py`
- Test: `warehouse_app/tests/w49_r0_gate.py`

**Interfaces:**
- Produces:
  - `get_order_queue(company: str | None, filters: dict, page: int, page_length: int) -> dict`
  - `get_order_preview(sales_order: str) -> dict`

- [ ] **Step 1: Write failing test**

Create a mixed SO; assert the preview returns one row per SO Item with `picking_group`, outstanding qty, and no duplicate item-code aggregation. Assert a user without Company permission gets 403/404.

- [ ] **Step 2: Run to fail**

Expected: endpoint missing.

- [ ] **Step 3: Implement the read-only endpoints**

Use `frappe.get_list` / `frappe.qb` with user permissions. Reuse `classification.classify`. No writes.

- [ ] **Step 4: Run to pass**

Expected: PASS; `GET` works; no document created.

- [ ] **Step 5: Commit**

```bash
git add warehouse_app/warehouse_app/fulfillment/eligibility.py warehouse_app/warehouse_app/fulfillment/api.py warehouse_app/tests/w49_r0_gate.py
git commit -m "feat(fulfillment): add read-only order queue and preview"
```

### Task 6: Read-only SPA Order Queue

**Files:**
- Create: `frontend/src/pages/fulfillment/FulfillmentQueue.vue`
- Create: `frontend/src/pages/fulfillment/FulfillmentDetail.vue`
- Create: `frontend/src/data/fulfillment.js`
- Modify: `frontend/src/router.js`
- Modify: navigation component used by the existing SPA.

**Interfaces:**
- Consumes: `get_order_queue`, `get_order_preview` via `call`/`callGet` from `@/lib/api`.
- Produces: queue list, filters, detail preview; no action buttons that mutate.

- [ ] **Step 1: Write the failing browser check**

Add a Playwright check with stubbed `get_order_queue`: route `/gudang/fulfillment` renders the queue, filter, and detail preview; no console errors.

- [ ] **Step 2: Run to fail**

```bash
npm.cmd run build
```

Expected: route/page missing.

- [ ] **Step 3: Implement the pages and data layer**

Use the existing SPA design tokens and table patterns. Add the route in `frontend/src/router.js`; keep Requests/Inventory routing unchanged.

- [ ] **Step 4: Build and verify**

```bash
npm.cmd run build
```

Expected: build succeeds; stubbed browser check passes; no horizontal overflow at 1440px and 390px.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/fulfillment frontend/src/data/fulfillment.js frontend/src/router.js warehouse_app/public/gudang www/gudang.html
git commit -m "feat(fulfillment): add read-only order queue spa"
```

### Task 7: Gate, review, and release note

**Files:**
- Modify: `TASKS.md`, `PROJECT_STATE.md`
- Optionally: `README.md`

- [ ] **Step 1: Run all relevant gates**

```bash
bench --site <test-site> execute warehouse_app.tests.w31_gate.run_gate
bench --site <test-site> execute warehouse_app.tests.w49_r0_gate.run_gate
```

Expected: both `ok: true`.

- [ ] **Step 2: Run frontend build**

```bash
npm.cmd run build
```

Expected: success.

- [ ] **Step 3: Review the diff**

Check permissions, no `ignore_permissions`, no stock mutation endpoint, no core edits, no hardcoded Item Group/company/warehouse.

- [ ] **Step 4: Update state**

Record evidence in `TASKS.md` W49 and `PROJECT_STATE.md`. Mark only what was actually executed.

- [ ] **Step 5: Commit**

```bash
git add TASKS.md PROJECT_STATE.md
git commit -m "docs(fulfillment): record read-only foundation evidence"
```

## Deferred After 2026-11-01

R3 Generate Pick Lists, R4 picking mutations, R5 DN consolidation, R6 Packing Slip, R7 verification/submit. Each must start only after the R0 runtime gate is green and a test site is available.
