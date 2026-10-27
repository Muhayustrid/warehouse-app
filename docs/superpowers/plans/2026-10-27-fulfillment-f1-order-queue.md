# Fulfillment F1 — Order Queue and Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a read-only, SO-centric Fulfillment Order Queue with Dry/Frozen classification, backed by native ERPNext documents, on a separate test site.

**Architecture:** Add a minimal profile DocType and two read-only Frappe endpoints. The SPA renders a queue and a drawer; it never creates or mutates native documents in F1. Native Sales Order, Pick List, Delivery Note, and Packing Slip remain the source of truth.

**Tech Stack:** Frappe/ERPNext v16, Python 3.14, Vue 3 SPA, existing `gudang.css` design tokens, native Frappe query/permission APIs.

**Spec:** `docs/superpowers/specs/2026-10-27-fulfillment-f1-order-queue-design.md`

## Global Constraints

- F1 has no stock-moving code and no POST endpoints.
- Do not use `ignore_permissions` in the two endpoints.
- Do not edit core Frappe/ERPNext.
- Do not hardcode Company, Item Group, Warehouse, Customer, or document names.
- All acceptance work happens on `fulfillment.localhost`; never mutate `erp.localhost` or the `1oktober2026` stack.
- Use the existing `callGet` helper; do not add a new HTTP library.
- Every task ends with a concrete verification command and evidence.
- Commit steps below are proposals gated by explicit user approval; never push.

## Review Focus

1. **Missing profile / missing Item Group:** the row must become `unclassified` and `exception`, never silently Dry.
2. **Permission boundary:** a user without Company/SO read permission must receive an error, not an empty success.
3. **Stage contradictions:** draft PL, draft DN, submitted PL, submitted DN, and partial delivery must resolve by the documented priority.
4. **Mixed UOM:** no sum across Nos/Box/Kg; queue counts are item-row counts, detail quantities stay in SO UOM.
5. **Stale/empty frontend state:** errors and filters must not leave an empty table that looks successful; request races must be ignored.

---

### Task 1: Test site, host routing, and base fixtures

**Files:**
- Create: `warehouse_app/tests/w49_f1_fixture.py`
- Environment: `fulfillment.localhost` site and frontend host config (outside the repo)

**Interfaces:**
- Produces:
  - `bootstrap_base() -> dict[str, str]` — idempotent; returns company, warehouse, item, customer, and item-group names.
  - `guard_site() -> None` — raises unless `frappe.local.site == "fulfillment.localhost"`.
- Consumes: local `frappe16` Docker stack only.

- [ ] **Step 1: Create the site and install the same apps**

Run from `C:\Users\LENOVO\frappe16`. Use the local stack's DB root password; do not write it into a file or commit it.

```powershell
docker compose exec -T backend bench new-site fulfillment.localhost --admin-password "<local-test-admin>" --db-root-password "<local-db-root>"
docker compose exec -T backend bench --site fulfillment.localhost install-app erpnext
docker compose exec -T backend bench --site fulfillment.localhost install-app warehouse_app
docker compose exec -T backend bench --site fulfillment.localhost migrate
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.upgrade.apply
```

Expected: `bench --site fulfillment.localhost list-apps` shows `frappe`, `erpnext`, and `warehouse_app`.

- [ ] **Step 2: Add the frontend host route**

Create `/etc/nginx/conf.d/fulfillment.localhost.conf` inside the frontend container by copying `frappe.conf` and changing only:

```nginx
server_name fulfillment.localhost;
proxy_set_header X-Frappe-Site-Name fulfillment.localhost;
try_files /fulfillment.localhost/public/$uri @webserver;
```

Keep `/assets` shared, and keep the existing `erp.localhost` server block untouched. Reload nginx. If the frontend container is later recreated, reapply this host config (or bind-mount it).

Expected:

```powershell
curl.exe -s -o NUL -w "%{http_code}`n" http://fulfillment.localhost:8080/api/method/ping
```

returns `200`.

- [ ] **Step 3: Write the failing bootstrap check**

Add `w49_f1_fixture.py` with `guard_site()` and a `bootstrap_base()` skeleton that raises `NotImplementedError`. Run:

```powershell
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_f1_fixture.bootstrap_base
```

Expected: FAIL with `NotImplementedError`.

- [ ] **Step 4: Implement the idempotent base bootstrap**

Implement `bootstrap_base()` with the minimum native fixture:

- set `System Settings.language` and `frappe.local.lang` to English;
- ensure UOMs `Nos`, `Box`, `Kg`; Warehouse Type `Transit`;
- ensure Item Groups:
  - dry group `ZZTEST W49 Dry`;
  - frozen parent `ZZTEST W49 Frozen`;
  - frozen child `ZZTEST W49 Frozen Child` under the parent;
- ensure Currency `IDR`;
- create Company `ZZTEST W49` with abbr `W49`, country Indonesia, default currency IDR, if missing;
- set the company's stock adjustment account, `Stock Settings.item_naming_by = "Item Code"`, current Fiscal Year, and Global Defaults;
- mark `Installed Application.is_setup_complete` and `System Settings.setup_complete`;
- create warehouse `Stores - W49` if the company auto-creation did not;
- create Item `ZZTEST-W49-DRY` in the dry group, stock UOM `Nos`, alternate UOM `Box` factor 12;
- create Item `ZZTEST-W49-FROZEN` in the frozen child group, stock UOM `Nos`, alternate UOM `Box` factor 12;
- create Customer `ZZTEST-W49 Customer`;
- create and submit a Material Receipt to `Stores - W49` with sufficient stock for both items;
- return all names as a dict.

Use `frappe.get_doc(...).insert(ignore_permissions=True)` only inside this test fixture, never in product endpoints.

- [ ] **Step 5: Run to pass and verify the base**

```powershell
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_f1_fixture.bootstrap_base
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_f1_fixture.bootstrap_base
```

Expected: second run is idempotent and returns the same names; no duplicate Company, Item, or Material Receipt.

- [ ] **Step 6: Commit the fixture support**

```bash
git add warehouse_app/tests/w49_f1_fixture.py
git commit -m "test(fulfillment): tambah fixture site F1"
```

### Task 2: Warehouse Fulfillment Profile DocType

**Files:**
- Create: `warehouse_app/warehouse_app/doctype/warehouse_fulfillment_profile/warehouse_fulfillment_profile.json`
- Create: `warehouse_app/warehouse_app/doctype/warehouse_fulfillment_profile/warehouse_fulfillment_profile.py`
- Create: `warehouse_app/warehouse_app/doctype/warehouse_fulfillment_profile/__init__.py`
- Create: `warehouse_app/tests/w49_f1_profile_gate.py`

**Interfaces:**
- Produces: DocType `Warehouse Fulfillment Profile`; controller validation uses `warehouse_app.warehouse_app.fulfillment.classification.validate_profile_config`.
- Consumes: Task 1's company and Item Groups.

- [ ] **Step 1: Write the failing profile gate**

Add `w49_f1_profile_gate.run_gate()` with checks:

- DocType exists;
- a valid profile for `ZZTEST W49` saves with the frozen parent and `include_child_item_groups = 1`;
- a profile with `include_child_item_groups = 0` on a parent group with children raises `ValidationError`;
- a second profile for the same company raises a validation/duplicate error;
- cleanup deletes the profile and prints exactly one `GATE_JSON:{...}` line.

Run:

```powershell
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_f1_profile_gate.run_gate
```

Expected: FAIL because the DocType or gate is missing.

- [ ] **Step 2: Add the DocType JSON and controller**

DocType fields:

```text
company                  Link/Company, required, unique
enabled                  Check, default 0
frozen_item_group        Link/Item Group
include_child_item_groups Check, default 1
```

Permissions:

```text
Stock User:       read
Stock Manager:    read
System Manager:   read, write, create, delete
```

Controller `validate()`:

- require `company`;
- reject duplicate company;
- if enabled, require `frozen_item_group`;
- load the Item Group and its child count;
- call `validate_profile_config(...)`, convert `ClassificationError` to `frappe.throw`;
- save changes only through normal DocType save.

- [ ] **Step 3: Migrate and run the gate**

```powershell
docker compose exec -T backend bench --site fulfillment.localhost migrate
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_f1_profile_gate.run_gate
```

Expected: `GATE_JSON:{"ok": true, ...}`.

- [ ] **Step 4: Commit**

```bash
git add warehouse_app/warehouse_app/doctype/warehouse_fulfillment_profile warehouse_app/tests/w49_f1_profile_gate.py
git commit -m "feat(fulfillment): tambah profile Dry/Frozen"
```

### Task 3: Full fixture chain for queue and preview

**Files:**
- Modify: `warehouse_app/tests/w49_f1_fixture.py`

**Interfaces:**
- Produces:
  - `seed() -> dict[str, list[str]]` — creates/returns Sales Orders and native documents for the five queue states;
  - `cleanup_documents() -> dict[str, int]` — cancels/deletes only `ZZTEST-W49` documents.
  - `verify_seed() -> dict[str, object]` — counts and names used by the API gate.
- Consumes: Task 1 base fixtures and Task 2 profile DocType.

- [ ] **Step 1: Write the failing seed check**

Add `seed()` skeleton raising `NotImplementedError`. Run:

```powershell
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_f1_fixture.seed
```

Expected: FAIL with `NotImplementedError`.

- [ ] **Step 2: Implement the seed**

Ensure the `Warehouse Fulfillment Profile` for `ZZTEST W49` exists and is enabled with the frozen parent group and `include_child_item_groups = 1` (create or update it idempotently).

Create synthetic Sales Orders and native documents:

- `SO-OPEN`: no PL, no DN, no PS.
- `SO-PICKING`: one draft Pick List created via native `create_pick_list` and saved.
- `SO-PACKING`: one submitted Pick List; set explicit picked qty equal to stock qty; no DN.
- `SO-READY`: submitted Pick List, a Draft DN created via `create_dn_for_pick_lists`, and one submitted Packing Slip created via native `make_packing_slip` with package numbers `1`–`1`.
- `SO-PARTIAL`: optional; create a submitted DN only after Task 5 is green, because it changes test stock.

Use native controllers and native field names. Do not hand-build DN items. Set `scan_mode = 0` for Pick Lists. Sales Orders use `price_list = "Standard Selling"`, the test customer, IDR currency, item rates, and a delivery date. All fixture names use the `ZZTEST-W49` or `ZZTEST W49` prefix.

`seed()` must be idempotent: if a previous seed exists, call `cleanup_documents()` first, then recreate. `cleanup_documents()` runs in reverse dependency order (Packing Slip, DN, PL, SO) and skips already-deleted documents.

- [ ] **Step 3: Run seed twice and verify**

```powershell
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_f1_fixture.seed
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_f1_fixture.seed
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_f1_fixture.verify_seed
```

Expected: the second run recreates cleanly; `verify_seed()` returns one SO per state and the expected native document counts.

- [ ] **Step 4: Commit**

```bash
git add warehouse_app/tests/w49_f1_fixture.py
git commit -m "test(fulfillment): tambah fixture rantai native F1"
```

### Task 4: Pure queue domain logic

**Files:**
- Create: `warehouse_app/warehouse_app/fulfillment/queue.py`
- Create: `warehouse_app/tests/test_fulfillment_queue.py`

**Interfaces:**
- Produces:
  - `derive_stage(profile_ok: bool, has_unclassified: bool, has_draft_pick_list: bool, has_draft_delivery_note: bool, dn_fully_packed: bool, has_submitted_pick_list: bool, has_submitted_delivery_note: bool, has_outstanding: bool) -> str`
  - `group_counts(items: Iterable[Mapping]) -> dict[str, int]`
  - `is_eligible(docstatus: int, status: str, per_delivered: float, outstanding_qty: float) -> bool`
  - `safe_classify(item_group: str | None, frozen: set[str] | None) -> tuple[str, str | None]`
- No Frappe imports in this module.

- [ ] **Step 1: Write failing unit tests**

Add `test_fulfillment_queue.py` with:

```python
def test_missing_profile_is_exception():
    assert derive_stage(False, False, True, False, False, True, False, True) == "exception"

def test_unclassified_is_exception():
    assert derive_stage(True, True, False, False, False, False, False, True) == "exception"

def test_draft_pick_list_is_picking():
    assert derive_stage(True, False, True, False, False, True, False, True) == "picking"

def test_draft_pick_list_wins_over_draft_dn():
    assert derive_stage(True, False, True, True, True, False, False, True) == "picking"

def test_draft_dn_fully_packed_is_ready():
    assert derive_stage(True, False, False, True, True, True, False, True) == "ready"

def test_draft_dn_not_packed_is_packing():
    assert derive_stage(True, False, False, True, False, True, False, True) == "packing"

def test_submitted_pl_without_dn_is_packing():
    assert derive_stage(True, False, False, False, False, True, False, True) == "packing"

def test_partial_delivery_without_active_drafts_is_partially_delivered():
    assert derive_stage(True, False, False, False, False, False, True, True) == "partially_delivered"

def test_partial_delivery_with_draft_pl_is_picking():
    assert derive_stage(True, False, True, False, False, False, True, True) == "picking"

def test_no_documents_is_open():
    assert derive_stage(True, False, False, False, False, False, False, True) == "open"

def test_counts_do_not_merge_duplicate_item_codes():
    items = [
        {"sales_order_item": "SO-1", "classification": "dry"},
        {"sales_order_item": "SO-2", "classification": "dry"},
        {"sales_order_item": "SO-3", "classification": "frozen"},
    ]
    assert group_counts(items) == {"dry": 2, "frozen": 1, "unclassified": 0}

def test_counts_ignore_mixed_uom_quantities():
    items = [
        {"sales_order_item": "SO-1", "classification": "dry", "qty": 10, "uom": "Kg"},
        {"sales_order_item": "SO-2", "classification": "dry", "qty": 5, "uom": "Pcs"},
    ]
    assert group_counts(items) == {"dry": 2, "frozen": 0, "unclassified": 0}

def test_missing_group_is_unclassified():
    assert safe_classify(None, {"Frozen"}) == ("unclassified", "item_group_missing")

def test_missing_profile_is_unclassified():
    assert safe_classify("Dry", None) == ("unclassified", "profile_missing")

def test_ineligible_when_fully_delivered():
    assert is_eligible(1, "To Deliver", 100.0, 0.0) is False
```

- [ ] **Step 2: Run to fail**

```powershell
docker compose exec -T backend sh -lc "cd /home/frappe/frappe-bench/apps/warehouse_app && /home/frappe/frappe-bench/env/bin/python -m unittest warehouse_app.tests.test_fulfillment_queue -v"
```

Expected: import failure for `fulfillment.queue`.

- [ ] **Step 3: Implement the pure functions**

`derive_stage()` priority:

```text
exception
picking (draft PL)
ready (draft DN fully packed)
packing (draft DN not fully packed, or submitted PL with no DN)
partially_delivered (submitted DN, outstanding, no active draft)
open
```

`is_eligible()` returns false for non-submitted/closed/cancelled/fully-delivered/no-outstanding rows.

`safe_classify()` catches `ClassificationError` and returns the stable reason strings.

- [ ] **Step 4: Run to pass**

Run the same unittest command. Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add warehouse_app/warehouse_app/fulfillment/queue.py warehouse_app/tests/test_fulfillment_queue.py
git commit -m "feat(fulfillment): tambah logika queue read-only"
```

### Task 5: Read-only API and gate

**Files:**
- Create: `warehouse_app/warehouse_app/fulfillment/profile.py`
- Create: `warehouse_app/warehouse_app/fulfillment/loader.py`
- Create: `warehouse_app/warehouse_app/fulfillment/api.py`
- Create: `warehouse_app/tests/w49_f1_readonly_gate.py`

**Interfaces:**
- Produces:
  - `get_order_queue(company=None, search=None, stage=None, from_date=None, to_date=None, page=1, page_length=20) -> dict`
  - `get_order_preview(sales_order: str) -> dict`
  - Internal `load_order_queue(...)`, `load_order_preview(...)`, `get_profile(company)`, `resolve_frozen(profile)`.
- Consumes: Task 3 seed, Task 4 pure functions.

- [ ] **Step 1: Write the failing API gate**

Add `w49_f1_readonly_gate.run_gate()` with checks:

- queue returns rows and counts with the expected shape;
- search by `ZZTEST-W49 Customer` returns at least one row; a date range outside the fixture dates returns no rows; the stage filter returns only rows with that stage;
- `page=1&page_length=2` returns at most two rows with the correct `total`;
- preview of `SO-READY` contains dry and frozen groups; with the profile disabled, the same items become unclassified and the stage becomes exception;
- preview of an unknown Sales Order raises `DoesNotExistError`/404-equivalent;
- a user without roles/company access raises `PermissionError`;
- disabling the profile produces `profile.configured = false` / warnings, not silent Dry;
- snapshots `modified` timestamps and document counts before/after both calls and asserts no writes;
- deletes the temporary user, sessions, and activity log in `finally`;
- prints exactly one `GATE_JSON:{...}` line.

Run:

```powershell
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_f1_readonly_gate.run_gate
```

Expected: FAIL because the endpoint does not exist.

- [ ] **Step 2: Implement profile and loader helpers**

`profile.py`:

- `get_profile(company)` uses permission-aware `frappe.get_all` and returns name, enabled, frozen group, include-children;
- `resolve_frozen(profile)` uses the native Item Group `lft`/`rgt` range for descendants, then calls `frozen_groups`;
- never throws for a missing profile; return `None` and let the caller warn.

`loader.py`:

- validate roles with `frappe.only_for(("Stock Manager", "Stock User", "System Manager"))`;
- resolve companies with `frappe.get_list("Company", fields=["name"], order_by="name")`;
- if `company` is not readable, raise `frappe.PermissionError`;
- query eligible SOs with `frappe.get_list`, parameterized search/date/company filters;
- batch-load SO Items, Pick List Items/parents, DN Items/parents, Packing Slips, and Draft DN packed quantities;
- classify rows with `safe_classify` and count by classification;
- compute stage with `derive_stage`;
- paginate after counts; `total` after stage filter;
- return the exact response shape from the spec.

`api.py`:

```python
@frappe.whitelist()
def get_order_queue(company=None, search=None, stage=None, from_date=None, to_date=None, page=1, page_length=20):
    return load_order_queue(...)

@frappe.whitelist()
def get_order_preview(sales_order):
    return load_order_preview(sales_order)
```

- [ ] **Step 3: Run the gate to pass**

```powershell
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_f1_readonly_gate.run_gate
```

Expected: `GATE_JSON:{"ok": true, ...}`.

- [ ] **Step 4: Run regressions**

```powershell
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_f1_profile_gate.run_gate
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w31_gate.run_gate
docker compose exec -T backend sh -lc "cd /home/frappe/frappe-bench/apps/warehouse_app && /home/frappe/frappe-bench/env/bin/python -m unittest warehouse_app.tests.test_fulfillment_classification warehouse_app.tests.test_fulfillment_queue -v"
```

Expected: both gates `ok: true`; all unit tests PASS.

- [ ] **Step 5: Commit**

```bash
git add warehouse_app/warehouse_app/fulfillment/profile.py warehouse_app/warehouse_app/fulfillment/loader.py warehouse_app/warehouse_app/fulfillment/api.py warehouse_app/tests/w49_f1_readonly_gate.py
git commit -m "feat(fulfillment): tambah Order Queue read-only"
```

### Task 6: SPA page, drawer, and navigation

**Files:**
- Create: `frontend/src/data/fulfillment.js`
- Create: `frontend/src/pages/FulfillmentPage.vue`
- Create: `frontend/src/components/FulfillmentDrawer.vue`
- Modify: `frontend/src/router.js`
- Modify: `frontend/src/components/SideNav.vue`
- Modify: `frontend/src/App.vue`

**Interfaces:**
- Consumes: `callGet`, existing toast/format helpers, existing `gudang.css` classes.
- Produces: `/fulfillment` route, queue page, detail drawer, sidebar and bottom-nav entry.

- [ ] **Step 1: Add the data layer**

`frontend/src/data/fulfillment.js`:

```js
import { callGet } from '@/lib/api'

export function fetchOrderQueue(params = {}) {
	return callGet('warehouse_app.warehouse_app.fulfillment.api.get_order_queue', params)
}

export function fetchOrderPreview(salesOrder) {
	return callGet('warehouse_app.warehouse_app.fulfillment.api.get_order_preview', {
		sales_order: salesOrder,
	})
}
```

- [ ] **Step 2: Add the page and route**

`FulfillmentPage.vue` state:

```text
company, companies, profile, counts, rows, total, page, pageLength,
stage, search, fromDate, toDate, loading, error, selectedSO
```

Behavior:

- load on mount; company selector; search/date/stage chips;
- request sequence guard so stale responses do not overwrite newer filters;
- clickable/keyboard rows; open drawer;
- stage badge and document count chips;
- skeleton, empty, error/retry, and profile banner states;
- scoped styles with a `ff-` prefix; reuse `gudang.css` tokens;
- mobile card layout at the existing 820 px breakpoint;
- no horizontal overflow at 1440, 1024, or 390 px.

`FulfillmentDrawer.vue`:

- props `open`, `salesOrder`; emits `close`;
- loads preview when opened; ignores stale responses;
- shows the grouped item table and native document sections;
- opens native forms in new tabs using `/app/<doctype>/<encoded-name>`;
- Escape closes; close button receives initial focus;
- read-only notice.

Route:

```js
{
	path: '/fulfillment',
	name: 'fulfillment',
	component: () => import('@/pages/FulfillmentPage.vue'),
	meta: { wide: true },
}
```

Add the sidebar section and a fourth bottom-nav item. Active state must also work for `/fulfillment`.

- [ ] **Step 3: Build to verify syntax**

```powershell
cd D:\Warehouse Fulfillment\warehouse-app\frontend
npm.cmd run build
```

Expected: build succeeds; output updates `warehouse_app/public/gudang/` and `www/gudang.html`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/data/fulfillment.js frontend/src/pages/FulfillmentPage.vue frontend/src/components/FulfillmentDrawer.vue frontend/src/router.js frontend/src/components/SideNav.vue frontend/src/App.vue warehouse_app/public/gudang www/gudang.html
git commit -m "feat(fulfillment): tambah Order Queue SPA"
```

### Task 7: Deploy to test site and browser acceptance

**Files:**
- Environment: `fulfillment.localhost`
- Modify: `TASKS.md`, `PROJECT_STATE.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: verified test site evidence and updated project state.

- [ ] **Step 1: Migrate, build, clear cache**

```powershell
cd C:\Users\LENOVO\frappe16
docker compose exec -T backend bench --site fulfillment.localhost migrate
docker compose exec -T backend bench --site fulfillment.localhost clear-cache
docker compose exec -T backend bench build --app warehouse_app
```

Expected: all commands exit 0.

- [ ] **Step 2: Verify HTTP and assets**

```powershell
curl.exe -s -o NUL -w "ping=%{http_code}`n" http://fulfillment.localhost:8080/api/method/ping
curl.exe -s -o NUL -w "gudang=%{http_code} redirect=%{redirect_url}`n" http://fulfillment.localhost:8080/gudang/fulfillment
```

Expected: `ping=200`; `/gudang/fulfillment` redirects to login (`301` or `302`) when unauthenticated.

- [ ] **Step 3: Browser acceptance**

Log in to `http://fulfillment.localhost:8080/gudang/fulfillment` as a fixture user with `System Manager`, `Stock Manager`, or `Stock User`:

- one row per seeded state appears;
- stage chips filter correctly;
- search and date filter work;
- drawer shows Dry, Frozen, and Needs attention groups;
- PL/DN/Packing Slip links open native forms;
- blocking the queue request in DevTools shows the error/retry state, not an empty success;
- an unmatched search shows the empty state with a clear-filter action;
- no console errors; no horizontal overflow at 1440, 1024, 390 px;
- hard refresh serves the newly built bundle.

Use a temporary user; delete it, its Sessions, and Activity Log entries after the check.

- [ ] **Step 4: Run the final gate set**

```powershell
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_f1_profile_gate.run_gate
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w49_f1_readonly_gate.run_gate
docker compose exec -T backend bench --site fulfillment.localhost execute warehouse_app.tests.w31_gate.run_gate
```

Expected: all `ok: true`; no fixture user residue; seeded acceptance documents remain only on the disposable test site.

- [ ] **Step 5: Update state and commit**

Record in `TASKS.md` W49:

- F1 scope and test site;
- gate outputs;
- browser evidence;
- known limits (read-only; no stock movement).

Update `PROJECT_STATE.md` with the current F1 head.

```bash
git add TASKS.md PROJECT_STATE.md
git commit -m "docs(fulfillment): catat bukti F1 Order Queue"
```
