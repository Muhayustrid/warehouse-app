# Fulfillment F1 — Order Queue and Profile Design

**Status:** Draft for review  
**Date:** 2026-10-27  
**App:** `warehouse_app`  
**Site for acceptance:** `fulfillment.localhost` (separate test site, same app code)  
**Related:** `PRD_Warehouse_Fulfillment_ERPNext_v16.md`, `FULFILLMENT_R0_DISCOVERY.md`, `IMPLEMENTATION_PLAN_FULFILLMENT.md`

## 1. Context

The repository currently contains the fulfillment classification core and 17 passing unit tests. There is no fulfillment UI, no Order Queue, no profile configuration, and no stock-moving code. The existing SPA at `/gudang` has Requests, Inventory, and Settings only.

The user wants the full PRD eventually. The work is split into phases so that each phase is reviewable and testable. F1 is the first phase:

- A real, read-only Order Queue in the existing SPA.
- Dry/Frozen classification using a configured profile.
- Native Sales Order, Pick List, Delivery Note, and Packing Slip remain the source of truth.
- No create, update, cancel, submit, or stock movement in F1.
- The only write in F1 is the admin-owned profile configuration through the native Desk form.

The test site is separate only at the database/site level. It installs the same `warehouse_app` code and exposes the same SPA. Production-like data in `erp.localhost` is not used for F1 acceptance or later stock-moving tests.

## 2. Goal and non-goals

### Goal

Give warehouse users one SO-centric page where they can see which sales orders are open, how much work is Dry versus Frozen, and which native fulfillment documents already exist.

### Non-goals

F1 does not:

- generate Pick Lists;
- edit picked quantities;
- create Delivery Notes or Packing Slips;
- submit or cancel any native document;
- move stock;
- add Fulfillment Run, request keys, assignments, print formats, or SPA profile settings;
- change native ERPNext or W31 behavior.

Read-only dashboards may link to native forms. Opening a native form is outside the SPA's write behavior.

## 3. Users and permissions

Target users are warehouse operators and supervisors with one of:

- `Stock User`
- `Stock Manager`
- `System Manager`

The existing `/gudang` page gate already enforces those roles. F1 endpoints enforce the same roles and then rely on native document permissions.

The `Warehouse Fulfillment Profile` DocType is:

- readable by `Stock User`, `Stock Manager`, and `System Manager`;
- writable by `System Manager` only in F1.

No endpoint uses `ignore_permissions`.

## 4. UX

### 4.1 Navigation

Add one section to the existing sidebar:

- Section: `Fulfillment`
- Item: `Order Queue`
- Route: `/fulfillment` (full URL `/gudang/fulfillment`)
- Icon: an existing Lucide package/queue icon.

Add a fourth item to the mobile bottom navigation: `Fulfillment`, pointing to the same route. The existing Requests, Inventory, and Settings routes remain unchanged.

### 4.2 Page header

- Title: `Fulfillment`
- Compact company selector, populated from companies the user can read.
- Refresh button.

If the user has one company, the selector shows that company and can be disabled.

### 4.3 Summary filters

Clickable chips with counts across the currently filtered queue:

- `Open`
- `In Picking`
- `In Packing`
- `Ready`
- `Partially Delivered`
- `Exceptions`

`All` is the default. Selecting a chip filters the table without a page reload. Counts are computed after company, search, and date filters but before the stage filter, so the chips stay stable while a stage is selected; `total` reflects the rows after the stage filter.

### 4.4 Toolbar

- Search by Sales Order name or customer name.
- SO date range.
- Clear filters.
- Refresh.

Pagination sizes: 20, 50, 100. Default 20. Sorting is earliest delivery date first, with null delivery dates after dated rows and a stable name tiebreaker.

### 4.5 Queue table

Columns:

1. `SO / Customer`
2. `SO Date`
3. `Delivery Date`
4. `Dry / Frozen`
5. `Pick Lists`
6. `DN Draft`
7. `Packing Slips`
8. `Stage`
9. `Open` chevron

Rules:

- Each row is keyboard-focusable and opens with Enter.
- Clicking the row opens the detail drawer.
- Dry/Frozen column shows item counts, not mixed-UOM quantities.
- Unclassified items show a warning marker and count.
- Document columns show count and a compact status summary.
- Stage is a badge, not the only status indicator; the document counts are always visible.
- At widths at or below the existing mobile breakpoint, the table becomes stacked cards.
- No horizontal overflow at 1440 px, 1024 px, or 390 px.

### 4.6 Detail drawer

Desktop: right-side drawer, approximately 720 px wide, with the queue still visible.  
Mobile: full-screen sheet.

Contents:

1. Header: SO name, customer, stage badge, close button.
2. Summary: company, SO date, delivery date, native SO status, total.
3. Grouped item table:
   - Group headers `Dry`, `Frozen`, and `Needs attention`.
   - Columns: Item, Group, UOM, Ordered, Delivered, Outstanding.
   - Quantities remain in the Sales Order row UOM. No cross-UOM totals.
   - `Needs attention` contains unclassified rows and explains why.
4. Related documents:
   - Pick Lists: name, native status, date, native link.
   - Delivery Notes: name, native status, date, native link.
   - Packing Slips: name, native status, date, parent DN, native link.
5. Small read-only notice: no actions in F1.

Links open native forms in a new browser tab. The SPA does not edit them.

### 4.7 States

- Loading: skeleton rows, not a blank page.
- Empty: clear message with active filters and a clear-filter action.
- Error: human-readable message, retry action, and no silent empty state.
- Missing/invalid profile: banner with a link to `/app/warehouse-fulfillment-profile` in Desk. Queue still renders native data; classification is marked unavailable or needs attention.
- Unclassified item: visible warning in the row and drawer, never silently treated as Dry.

## 5. Data model

### 5.1 `Warehouse Fulfillment Profile`

New DocType. Not a custom field on a native DocType.

| Field | Type | Required | Notes |
|---|---|---|---|
| `company` | Link Company | Yes | Unique per profile |
| `enabled` | Check | Yes | Default off |
| `frozen_item_group` | Link Item Group | When enabled | No hardcoded group |
| `include_child_item_groups` | Check | Yes | Default on |

Validation on save:

- Company is required and unique.
- Enabled profile requires an existing Item Group.
- If the configured group is a parent with children and `include_child_item_groups` is off, reject with a clear validation error.
- Use the existing pure functions in `fulfillment/classification.py`; do not duplicate the classification rules.

No profile is created automatically in production. The test site creates one only for acceptance.

## 6. Backend API

Two whitelisted GET endpoints. No POST endpoints in F1.

### 6.1 `get_order_queue`

Dotted path: `warehouse_app.warehouse_app.fulfillment.api.get_order_queue`.

Parameters:

- `company` (optional; if omitted, use the user's default company when readable, otherwise the first readable company by name; if none, HTTP 404)
- `search` (optional)
- `stage` (optional; one of the stage values or `all`)
- `from_date`, `to_date` (optional; filters `Sales Order.transaction_date`)
- `page` (default 1)
- `page_length` (default 20; max 100)

Returns:

```json
{
  "company": "Company A",
  "companies": [{"name": "Company A"}],
  "profile": {
    "configured": true,
    "enabled": true,
    "frozen_item_group": "Produk Jadi Pabrik"
  },
  "counts": {
    "all": 24,
    "open": 10,
    "picking": 5,
    "packing": 3,
    "ready": 2,
    "partially_delivered": 3,
    "exception": 1
  },
  "rows": [
    {
      "sales_order": "SO-00091",
      "customer": "CUST-0001",
      "customer_name": "Outlet Solo",
      "transaction_date": "2026-10-20",
      "delivery_date": "2026-10-22",
      "stage": "picking",
      "dry_count": 8,
      "frozen_count": 4,
      "unclassified_count": 0,
      "pick_lists": {"total": 2, "draft": 1, "submitted": 1},
      "delivery_notes": {"total": 0, "draft": 0, "submitted": 0},
      "packing_slips": {"total": 0, "draft": 0, "submitted": 0},
      "warnings": []
    }
  ],
  "total": 24,
  "page": 1,
  "page_length": 20,
  "warnings": []
}
```

`dry_count`, `frozen_count`, and `unclassified_count` count Sales Order item rows, not unique item codes.

### 6.2 `get_order_preview`

Dotted path: `warehouse_app.warehouse_app.fulfillment.api.get_order_preview`.

Parameter: `sales_order`.

Returns:

```json
{
  "sales_order": {
    "name": "SO-00091",
    "customer": "CUST-0001",
    "customer_name": "Outlet Solo",
    "company": "Company A",
    "transaction_date": "2026-10-20",
    "delivery_date": "2026-10-22",
    "status": "To Deliver",
    "docstatus": 1
  },
  "profile": {
    "configured": true,
    "enabled": true,
    "frozen_item_group": "Produk Jadi Pabrik"
  },
  "stage": "picking",
  "groups": {
    "dry": [],
    "frozen": [],
    "unclassified": []
  },
  "items": [
    {
      "sales_order_item": "SO-00091-item-1",
      "item_code": "ITEM-001",
      "item_name": "Item A",
      "item_group": "Dry Goods",
      "classification": "dry",
      "uom": "Nos",
      "conversion_factor": 1.0,
      "ordered": 24.0,
      "delivered": 0.0,
      "outstanding": 24.0
    }
  ],
  "documents": {
    "pick_lists": [
      {
        "name": "PL-00001",
        "docstatus": 1,
        "status": "Submitted",
        "date": "2026-10-21"
      }
    ],
    "delivery_notes": [],
    "packing_slips": []
  },
  "warnings": []
}
```

The exact `groups` membership mirrors `items`; it is a convenience for rendering. `items` is the source of truth for row lineage.

Each document object contains `name`, `docstatus`, `status`, and `date`. Packing Slip objects also contain `delivery_note`.

## 7. Eligibility, classification, and stage

### 7.1 Eligible Sales Orders

A Sales Order is in the queue when all are true:

- `docstatus = 1`;
- native status is not `Closed` or `Cancelled`;
- it is not fully delivered (`per_delivered < 100` or equivalent native outstanding check);
- at least one item has outstanding quantity (`qty > delivered_qty`, with native precision);
- it belongs to the selected company and passes native user permissions.

Do not use `per_picked` as the eligibility source. Picked quantity is not delivered quantity.

### 7.2 Classification

For each SO item:

- Resolve the profile for the SO company.
- If no profile exists, the profile is disabled, or it is not readable by the current user, `classification = "unclassified"` with reason `profile_missing`.
- Read the item group from the SO item or the Item master fallback.
- Missing/renamed Item Group: `classification = "unclassified"` with reason `item_group_missing`. Do not throw away the row.
- Build the frozen set from the configured group and descendants when `include_child_item_groups` is on.
- Use the existing pure `classify()` function.
- A configured parent group with children and `include_child_item_groups = 0` is invalid at profile save and produces an exception at read time if it exists from old data.

### 7.3 Stage rules

Priority, highest first:

1. `exception` — profile missing/invalid, any unclassified item, or inconsistent linked document ownership/lineage.
2. `picking` — at least one linked Pick List is Draft (`docstatus = 0`).
3. `ready` — a Draft Delivery Note exists and every DN item is fully packed (`packed_qty >= qty` within native precision).
4. `packing` — any Draft Delivery Note exists but is not fully packed, **or** a submitted Pick List exists with no Delivery Note yet.
5. `partially_delivered` — at least one submitted Delivery Note exists, the SO still has outstanding quantity, and there is no active draft PL/DN to show a nearer stage.
6. `open` — no linked Pick List, Delivery Note, or Packing Slip.

Fully delivered Sales Orders are excluded before staging. `Partially Delivered` is a normal queue state, not an error.

## 8. Query plan and performance

F1 targets normal warehouse volumes and must avoid N+1 queries.

1. Query the filtered eligible Sales Orders.
2. Batch-load linked `Pick List Item` rows for the SO set, then batch-load their parent `Pick List` documents.
3. Batch-load `Delivery Note Item` rows by `against_sales_order`, then parent Delivery Notes.
4. Batch-load Packing Slips by parent Delivery Note names.
5. For the `ready` calculation, batch-load the Draft DN item `qty`/`packed_qty` pairs.
6. Classify and aggregate in Python with pure functions.
7. Paginate after stage counts are computed.

If production later has more than about 2,000 open Sales Orders, add a server-side aggregate query. F1 does not prematurely optimize.

Search must use parameterized filters, not string interpolation. All queries go through Frappe permission-aware APIs.

## 9. Error handling

- Missing permission on SO/company: HTTP 403 or the native permission error; never an empty success response.
- Unknown SO in preview: HTTP 404.
- No profile: HTTP 200 with `profile.configured = false` and a warning; the queue remains usable.
- Invalid/unclassified item: row stays visible with a warning; stage becomes `exception`.
- Query error: HTTP 500 with a correlation id in the server log; the UI shows a retry state. Do not show a green success or an empty list.
- No writes or side effects in either endpoint.

## 10. Implementation files

Backend:

- `warehouse_app/warehouse_app/doctype/warehouse_fulfillment_profile/` — DocType JSON, controller, `__init__.py`.
- `warehouse_app/warehouse_app/fulfillment/profile.py` — profile lookup and validation helpers.
- `warehouse_app/warehouse_app/fulfillment/queue.py` — pure eligibility, aggregation, and stage derivation.
- `warehouse_app/warehouse_app/fulfillment/loader.py` — permission-aware Frappe queries for queue and preview.
- `warehouse_app/warehouse_app/fulfillment/api.py` — two whitelisted GET endpoints.
- `warehouse_app/tests/w49_f1_readonly_gate.py` — read-only acceptance gate.
- `warehouse_app/tests/test_fulfillment_queue.py` — pure tests.

Frontend:

- `frontend/src/pages/FulfillmentPage.vue` — page, filters, table, drawer orchestration.
- `frontend/src/components/FulfillmentDrawer.vue` — SO detail.
- `frontend/src/data/fulfillment.js` — `callGet` wrappers and response normalization.
- `frontend/src/router.js` — add `/fulfillment` before the catch-all.
- `frontend/src/components/SideNav.vue` — new Fulfillment section.
- Existing CSS tokens and table patterns from `BoardPage.vue` and `gudang.css`.

Reuse `callGet` from `@/lib/api`. Do not add a new HTTP library or UI framework.

Vue escapes text by default. Native document names used in links must come from the backend and be encoded in the route.

## 11. Test plan

### 11.1 Unit tests

- Stage derivation priority and edge cases.
- Eligibility rules.
- Dry/Frozen/unclassified aggregation.
- Missing profile and missing item group.
- Batch grouping without cross-UOM quantity totals.

### 11.2 Backend read-only gate

Create a gate that runs on the test site and:

- asserts both endpoints return valid shapes;
- asserts no document is created or modified (compare modified timestamps and relevant counts before/after);
- asserts a user without Company/SO access is rejected;
- asserts missing profile produces warnings, not silent Dry;
- runs classification unit tests and the existing W31 gate as regression after the app is installed on the test site.

### 11.3 Frontend build and browser

- `npm.cmd run build` succeeds.
- New assets are served through the frontend container.
- Browser checks: queue renders, filter chips work, search works, row opens drawer, Escape closes, no console errors, no horizontal overflow at 1440/1024/390 px.
- Use a temporary test user on the test site; remove the user, sessions, and activity log after the test.

### 11.4 Manual acceptance

The user logs in to `fulfillment.localhost`, opens `/gudang/fulfillment`, and verifies the queue and drawer against synthetic SO/PL/DN/Packing Slip fixtures.

## 12. Test site and rollout

- Create `fulfillment.localhost` in the local `frappe16` Docker stack.
- Install the same `erpnext` and `warehouse_app` code.
- Add a host-based frontend route for `fulfillment.localhost`.
- Seed only synthetic companies, warehouses, items, customers, SOs, and documents needed for F1.
- Do not copy production data from `erp.localhost`.
- Do not touch the production stack `1oktober2026`.
- F1 is feature-flagged by the profile; no profile means no classification.
- No production deployment in F1.

## 13. Future phases

- F2: Fulfillment Run, request keys, Generate Pick List Dry/Frozen.
- F3: Picking workspace, W31 quantities, batch/serial, short-pick approval, PL submit.
- F4: One DN from two PLs, Packing Slips, verification, DN submit.
- F5: Print Center, assignments, SPA settings, audit, full regression.

F1 must not depend on F2 internals. The queue API may later add Run fields without breaking the F1 response contract.

## 14. Acceptance criteria

- `/gudang/fulfillment` exists in the SPA and is reachable from the sidebar.
- Dry/Frozen counts are correct for classified items.
- Unclassified items are visible and never counted as Dry.
- Queue and drawer use native documents and enforce permissions.
- No write or stock movement occurs in F1 endpoints.
- Missing profile is explicit and recoverable via the profile Desk form.
- Build, unit tests, read-only gate, and browser checks pass on `fulfillment.localhost`.
- No residue from test users or fixtures after verification.
- No changes to `erp.localhost` data or the production stack.
