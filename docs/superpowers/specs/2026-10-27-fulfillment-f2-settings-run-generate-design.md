# F2 — Settings Profile, Fulfillment Run, and Generate Dry/Frozen Pick Lists

**Status:** proposed for user review, 2026-10-27

**Extends:** F1 read-only Order Queue (`2026-10-27-fulfillment-f1-order-queue-design.md`)

**Binding sources:** `PRD_Warehouse_Fulfillment_ERPNext_v16.md`, `FULFILLMENT_R0_DISCOVERY.md`, and the user decisions below.

## 1. Decisions

1. F2 is the first write phase, but writes only **orchestration records and draft Pick Lists**. It does not pick, submit a Pick List, create a Delivery Note, create a Packing Slip, or move stock.
2. Dry/Frozen classification uses **one configured Frozen Item Group** plus optional child groups. Every other valid Item Group is Dry. There is no second explicit Dry Item Group.
3. Configuration is exposed in the existing **`/gudang/settings`** page, not in a new Settings route and not only in the Desk form. The Desk Profile form remains an admin fallback.
4. All fields in PRD §19.1 are represented in the Profile schema and Settings UI. Fields whose feature belongs to F3–F5 are stored and validated when set, but are not made blocking for F2 activation. This is a deliberate phase boundary, not a silent omission.
5. F2 must not start write/stock-moving code until the R0 runtime gate is green on `fulfillment.localhost`.
6. All work stays on the disposable test site. `erp.localhost` and the `1oktober2026` production stack are out of scope.
7. Commit locally only with explicit approval; no push.

## 2. Goal and non-goals

### Goal

An authorized user can configure a Company Fulfillment Profile in `/gudang/settings`, then generate a Fulfillment Run for an eligible Sales Order and receive 0–1 native Draft Pick List Dry plus 0–1 native Draft Pick List Frozen. Repeating the request is idempotent and never duplicates documents.

### Non-goals for F2

- Picking quantities, scanning, batch/serial capture, short-pick approval.
- Pick List submit or cancel workflow.
- Delivery Note creation, Packing Slip creation, DN submit.
- Print, Print Center, assignment, checker verification.
- Multiple active Runs per Sales Order, partial delivery orchestration, Run close/rebuild.
- Changes to W31 `custom_picked_qty` behavior or client scripts.
- Production deployment.

## 3. Current baseline and gaps F2 resolves

F1 provides the read-only queue, preview, profile DocType, and classification core. F2 must also correct these consistency gaps:

| Gap | Resolution in F2 |
|---|---|
| F1 preview uses the SO row Item Group first; native PL uses current Item master Item Group | Generate resolves Item Group from the current Item master. Preview/queue are aligned to that source. |
| F1 eligibility uses `qty - delivered_qty`; native pending uses `qty - max(picked/conversion_factor, delivered_qty)` | F2 introduces a shared pending-quantity helper and uses it for eligibility, preview, and Run items. |
| F1 can show an SO that native will reject due `per_picked=100`, On Hold, reservation, non-stock, or bundle rows | F2 adds explicit preflight errors and marks preview `can_generate=false` with reason codes. |
| R0 runtime gate does not exist | It is the blocking first task; no F2 product write code before it passes. |
| Profile schema only has four fields | F2 expands it to the full PRD profile; existing profiles receive deterministic defaults. |
| Request Key and Run do not exist | F2 adds both, with DB uniqueness. |
| No Pick List lineage fields | F2 adds optional `custom_fulfillment_run` and `custom_fulfillment_group`. |

## 4. Profile schema

The existing `Warehouse Fulfillment Profile` remains one record per Company. `company` stays the document name and is unique.

### 4.1 Fields

| Field | Type | F2 behavior | Validation / default |
|---|---|---|---|
| `company` | Link Company | Required | Readable Company; unique; cannot change while Runs exist |
| `enabled` | Check | Required | Default 0; disabled blocks Generate |
| `frozen_item_group` | Link Item Group | Required when enabled | Exists; parent with children + include off is invalid |
| `dry_display_name` | Data | Used in UI now | Default `Dry`; non-empty |
| `frozen_display_name` | Data | Used in UI now | Default `Frozen`; non-empty |
| `include_child_item_groups` | Check | Used now | Default 1 |
| `dry_parent_warehouse` | Link Warehouse | Stored; F3 scope | Optional; must belong to Company; group or leaf allowed |
| `frozen_parent_warehouse` | Link Warehouse | Stored; F3 scope | Optional; same rule |
| `dry_print_format` | Link Print Format | Stored; F5 use | Optional in F2; if set, `doc_type = Pick List` |
| `frozen_print_format` | Link Print Format | Stored; F5 use | Optional in F2; if set, `doc_type = Pick List` |
| `print_paper_size` | Select | Stored; F5 use | Optional; allowed values `A4`, `A5`, `Letter`, `Thermal 80mm` |
| `dry_print_copies` | Int | Stored; F5 use | Default 1; if set, >= 1 |
| `frozen_print_copies` | Int | Stored; F5 use | Default 1; if set, >= 1 |
| `allow_partial_delivery` | Check | Snapshot | Default 0 |
| `short_pick_approval_required` | Check | Snapshot | Default 1 |
| `require_all_packed` | Check | Snapshot | Default 1 |
| `require_checker_approval` | Check | Snapshot | Default 1 |
| `allow_cross_group_packing` | Check | Stored; F4 use | Default 0 |
| `allow_draft_print` | Check | Stored; F5 use | Default 1 |
| `barcode_mode_enabled` | Check | Stored; F3/F5 use | Default 0 |
| `minimum_shelf_life_days` | Int | Stored; F3 use | Default 0; >= 0 |
| `role_order_coordinator` | Link Role | Stored; F3 use | Optional; Role exists |
| `role_picker_dry` | Link Role | Stored; F3 use | Optional; Role exists |
| `role_picker_frozen` | Link Role | Stored; F3 use | Optional; Role exists |
| `role_packer` | Link Role | Stored; F4 use | Optional; Role exists |
| `role_checker` | Link Role | Stored; F4 use | Optional; Role exists |
| `role_dispatch` | Link Role | Stored; F4 use | Optional; Role exists |
| `config_revision` | Int | Internal | Starts at 1; read-only; increments on every save |

### 4.2 Required-now policy

Required for activation/save: `company`, `enabled`, `frozen_item_group` when enabled, display names, `include_child_item_groups`, policy flags and `config_revision`. Print formats, warehouse scopes, role links, paper size, copies, barcode, and shelf life are optional for F2 and are enforced when their phase uses them.

This is a deliberate deviation from PRD “Required” markers for print formats/display/policy fields so that a F2 profile can be activated before F3–F5 exist. The spec must not claim those later behaviors are implemented.

### 4.3 Validation

- Company must be readable by the session user; one profile per Company.
- Changing `company` is rejected if any Fulfillment Run references the profile.
- Enabled profile requires a valid `frozen_item_group`; the parent-with-children/include-off rule calls `validate_profile_config`.
- Item Group must exist; classification remains fail-closed.
- Profile changes increment `config_revision` in `before_save` (or an equivalent server-side hook) and never rewrite existing Run snapshots.
- Warehouse links validate Company ownership and disabled state; group warehouses are allowed for scope fields.
- Print Format links validate `doc_type = Pick List` server-side; client filtering is not sufficient.
- Role links validate Role existence and non-disabled state.
- `minimum_shelf_life_days`, copies, and revision are non-negative/positive as appropriate.
- All writes are one transaction. A validation failure returns a clear `ValidationError`; no partial save.

### 4.4 Permissions

- Read: `System Manager`, `Stock Manager`, `Stock User` (consistent with the Settings page and Profile read permission).
- Write: `System Manager` only. The Settings panel returns `can_edit=false` for other roles and disables Save server-side and client-side.
- Generate in F2: `System Manager` and `Stock Manager`. `role_order_coordinator` is stored for the F3 role matrix; a custom configured role does not bypass DocPerm checks in F2. A Stock User can view the queue but cannot generate.
- Run, Run Item, Run Allocation, and Request Key DocPerm: create/read/write for `System Manager` and `Stock Manager`; read for `Stock User`. No `ignore_permissions` in the settings or generate endpoints.

## 5. Settings UI

The existing `SettingsPage.vue` gains one **Fulfillment** panel below the handover panel. The page remains `/gudang/settings`; no new route.

### Layout

1. **Context:** company selector, profile status, `config_revision`, `can_edit`, “applies to new Runs only” notice.
2. **Classification:** enabled, Frozen Item Group, include child groups, Dry/Frozen display names.
3. **Warehouses:** Dry and Frozen parent scope.
4. **Print:** Dry/Frozen print format, paper size, copies, allow draft print.
5. **Policies:** partial delivery, short-pick approval, require all packed, checker approval, cross-group packing, barcode mode, minimum shelf life.
6. **Roles:** coordinator, dry picker, frozen picker, packer, checker, dispatch.

Fields for later phases are visible but marked “Used from F3/F4/F5” in help text. Link inputs use native link search or server-filtered options. The panel saves with one Save button and one transaction. The page must not use the existing `Promise.all` save pattern for the profile; handover and profile can be separate save actions or one orchestrated action with independent error reporting.

If the selected Company has no profile, the panel shows an empty form with `enabled=0` and a Create/Save action. If the profile is disabled or invalid, the Fulfillment Queue banner links to `/gudang/settings` instead of the Desk form.

### Settings API

`get_fulfillment_settings(company=None)` (GET):
- Resolves a readable Company (default: user default, else first readable).
- Returns `{company, companies, profile, can_edit}`.
- `profile` is null when absent; otherwise all fields plus `modified`.

`save_fulfillment_settings(payload)` (POST):
- System Manager only.
- Accepts all Profile fields except `config_revision`, `modified`, and document name.
- Requires `expected_modified` (or `expected_revision`) for optimistic concurrency; mismatch returns `CONFLICT_STALE_PROFILE`.
- Returns the saved profile, including the new revision.

`fulfillment_settings_options(company)` (GET):
- Returns company-scoped warehouse options (group and leaf), roles, and Print Formats filtered to `Pick List`; Item Group uses native link search to avoid loading a large tree.
- Does not bypass DocPerm for the options themselves; unknown/invalid selections are rejected on save.

## 6. Data model

### 6.1 `Warehouse Fulfillment Run`

Orchestration only; no stock balance.

| Field | Type | Notes |
|---|---|---|
| `name` | naming/hash | Run identifier |
| `company` | Link Company | From SO/Profile |
| `sales_order` | Link Sales Order | Source |
| `customer` | Link Customer | Snapshot |
| `profile` | Link Profile | Config source |
| `profile_revision` | Int | Snapshot |
| `frozen_item_group_snapshot` | Data | Snapshot |
| `include_child_groups_snapshot` | Check | Snapshot |
| `policy_snapshot` | JSON/Small Text | Classification + policy flags + warehouse scopes |
| `status` | Select | `PLANNING`, `NEEDS_RECONCILIATION` (F2 normally only PLANNING) |
| `dry_pick_list` | Link Pick List | Nullable |
| `frozen_pick_list` | Link Pick List | Nullable |
| `active_so_key` | Data unique, nullable | Set to Sales Order while Run is active; clear (NULL) on close so later partial Runs are possible |
| `request_key` | Data | Last request key, for recovery |
| `run_revision` | Int | Starts at 1 |
| `error_code` / `error_message` | Data/Small Text | Safe error summary |
| `last_reconciled_at` | Datetime | Optional in F2 |

### 6.2 `Warehouse Fulfillment Run Item`

One row per SO Item, **not** one row per PL location.

`sales_order_item`, `item_code`, `item_group_snapshot`, `picking_group` (`dry`/`frozen` enum), `required_stock_qty`, `allocated_stock_qty`, `stock_uom`, `conversion_factor`.

### 6.3 `Warehouse Fulfillment Run Allocation`

One row per PL source location, added in F2 to preserve lineage for F3/F4.

`sales_order_item`, `item_code`, `picking_group`, `pick_list`, `pick_list_item`, `warehouse`, `batch_no`, `serial_and_batch_bundle`, `allocated_stock_qty`.

### 6.4 `Warehouse Fulfillment Request Key`

DB-unique idempotency guard, not a Redis-only lock.

`scope_key` (unique, computed), `idempotency_key`, `actor`, `company`, `sales_order`, `request_type`, `request_hash`, `status` (`PENDING`, `COMPLETED`, `FAILED`), `result_doc_refs`, `created_at`, `expiry_at`, `completed_at`, `error_code`, `error_message`.

### 6.5 Pick List custom fields

Added idempotently through `upgrade.py` / `after_migrate`, optional:
- `custom_fulfillment_run` — Link `Warehouse Fulfillment Run`
- `custom_fulfillment_group` — Select `Dry` / `Frozen`

No required field is added to native Pick List. W31 fields and scripts remain untouched.

## 7. Generate flow

### 7.1 Preflight

All checks are server-side and fail closed:

1. Session user is permitted to generate for the resolved Company.
2. Sales Order exists, is readable, `docstatus=1`, status not `Closed`/`Cancelled`/`On Hold`.
3. `per_delivered < 100`; `per_picked < 100`; native pending quantity > 0 on at least one row.
4. No row has `stock_reserved_qty > 0`; stock reservation must be off.
5. No non-stock, Product Bundle/Packed Item, or `delivered_by_supplier` demand.
6. Every item is enabled; every Item Group exists; every conversion factor > 0.
7. Profile exists, is enabled, belongs to the SO Company, and its Frozen Item Group resolves.
8. `expected_so_modified` matches current Sales Order `modified`; otherwise `SO_CHANGED`.
9. Request key is valid and not replayed with a different payload.
10. No active Run for the SO; if one exists, return it as a replay/resume instead of creating another.

### 7.2 Native split

1. Build the classification map from **current Item master** Item Group, not only the stale SO child row.
2. Call `erpnext.selling.doctype.sales_order.sales_order.create_pick_list(so)` exactly once, with `target_doc=None`.
3. The returned Pick List is unsaved. Split its `locations` by the SO Item → group map **before the first save**.
4. Never split by item code or current Item Group alone; always use `sales_order_item`.
5. For each non-empty group, copy the native template, preserve header fields, set `locations` to that group, and set the two custom fields. Leave `picked_qty` and W31 `custom_picked_qty` empty/zero. Leave `scan_mode=0`.
6. Insert only non-empty groups. Dry-only and Frozen-only produce one PL and one null Run link.
7. If a group has SO demand but no native locations, or allocated quantity is less than required native pending quantity, block with `STOCK_SHORTAGE` and create no Run/PL. F2 does not silently create a short or empty PL.
8. After insert, reload and assert: every expected `sales_order_item` appears in exactly one PL, no row appears in the wrong group, no empty PL exists, and no picked quantity changed.

### 7.3 Transaction and idempotency

- Compute `scope_key = sha256(actor | company | sales_order | request_type | idempotency_key)`.
- Request hash covers `sales_order`, `expected_so_modified`, and the Generate request type. Same key + same hash returns the same Run/PL result. Same key + different hash returns `IDEMPOTENCY_MISMATCH`.
- Reserve the key in a separate committed step so the unique guard is visible across workers. If the key is already `COMPLETED`, replay its result. If it is `PENDING`, return `REQUEST_IN_PROGRESS`.
- Set `active_so_key` to the SO and rely on its unique index to prevent two active Runs. If an active Run already exists, return it with `reused=true`; record the supplied key as `COMPLETED` with that Run/PL reference so the key stays replay-safe. If the key already has a different request hash, return `IDEMPOTENCY_MISMATCH` before reuse.
- Create Run, Run Items, Allocations, and both PLs in one transaction. If the second PL fails, roll back both PLs and the Run; mark the key `FAILED` with a safe error, leave no orphan draft.
- A crash after key reservation but before completion is recoverable by `request_key`/`active_so_key`; the key expires after 24 hours only for pending/failed work. Completed keys do not expire into duplicate work.
- Commit only after all result references are stored. Never mark the key completed before the native documents exist.

### 7.4 Run status and snapshots

F2 creates `PLANNING`. `NEEDS_RECONCILIATION` is reserved for a detected native mismatch and must not be used as a success shortcut. Snapshot the profile revision, Frozen group/include flag, policy flags, and warehouse scopes on the Run. Run Items snapshot `item_group_snapshot` and `picking_group`; later profile/item-group changes cannot reclassify historical Runs.

## 8. API contracts

### Generate

`POST /api/method/warehouse_app.warehouse_app.fulfillment.api.generate_fulfillment_run`

Parameters: `sales_order`, `idempotency_key`, `expected_so_modified`.

Success:
```json
{
  "run": "WFR-...",
  "reused": false,
  "status": "PLANNING",
  "dry_pick_list": {"name": "...", "docstatus": 0},
  "frozen_pick_list": {"name": "...", "docstatus": 0},
  "warnings": []
}
```

Errors are structured safe codes: `PROFILE_MISSING`, `PROFILE_DISABLED`, `PROFILE_INVALID`, `SO_CHANGED`, `SO_NOT_ELIGIBLE`, `STOCK_RESERVED`, `ITEM_GROUP_MISSING`, `ITEM_NOT_PICKABLE`, `STOCK_SHORTAGE`, `IDEMPOTENCY_MISMATCH`, `REQUEST_IN_PROGRESS`, `RUN_EXISTS`, `CONFLICT_STALE_PROFILE`. No raw SQL or sensitive stack traces in the response.

### Preview/queue additions

- `get_order_preview` returns `can_generate`, `can_generate_reason`, `run` (active Run summary if any), and current `modified`.
- `get_order_queue` returns profile display names plus row `can_generate`/reason; stage remains F1-compatible. F1 page/drawer use the configured display names with `Dry`/`Frozen` fallback.
- F1 classification source is aligned to current Item master at preview/queue time.

### Settings

`get_fulfillment_settings`, `save_fulfillment_settings`, and `fulfillment_settings_options` are GET/POST as described in §5. Settings writes are System Manager only.

## 9. UI behavior

### Settings

- Add the Fulfillment panel with sections and help text for later-phase fields.
- Company selector loads readable companies; changing Company loads that profile.
- All PRD fields are visible. Frozen group is a link search; include-child is a checkbox; warehouses/roles/print formats use filtered options.
- `config_revision` is read-only. Save shows a success toast and the new revision.
- Non-admin users see the profile read-only and no Save button.
- Disabled/invalid profile shows the same actionable banner used by the queue, but links to `/gudang/settings`.
- Do not remove or rewrite the existing handover settings panel.

### Queue/drawer

- The drawer gets a `Generate Pick Lists` button only when `can_generate` and the profile is enabled.
- Generate uses a client-generated idempotency key, sends `expected_so_modified`, disables while in flight, and on success reloads the preview and shows links to the Run and both draft PLs. The key is retained for the current attempt and reused on a network retry until a definitive success/error or page refresh, so a timeout cannot create a second Run.
- `reused=true` shows “Existing Run reused” rather than a duplicate success.
- Generate errors render actionable messages: fix Settings, fix stock/master data, refresh SO, or retry.
- No picking, submit, DN, Packing, or print buttons in F2.

## 10. R0 runtime gate

Create `warehouse_app/tests/w49_r0_gate.py` before product write code. It must run on `fulfillment.localhost`, print exactly one `GATE_JSON` line, and clean up.

Minimum assertions:

1. Mixed SO with Dry and Frozen, a batch item, a UOM-conversion item, and same item on two SO rows.
2. One native `create_pick_list` template split before first save into disjoint Dry/Frozen PLs.
3. Every SO Item appears in exactly one group; union equals expected eligible rows; no duplicate/missing row.
4. Dry-only and Frozen-only each produce one PL, never an empty PL.
5. `pick_manually=0` and `1` paths survive save/reload without cross-group contamination.
6. Submit Dry full; submit Frozen short with `scan_mode=0` and explicit qty; assert picked fields, SO progress, and no SLE from PL submit.
7. Two submitted PLs → one DN Draft; repeated native DN call reuses the target and does not duplicate; taxes/addresses/currency preserved.
8. Two Packing Slips; packed qty and cancel/revert verified.
9. Submit DN; stock ledger and SO delivered qty verified; no double posting.
10. `scan_mode=1` short pick is rejected by native validation.
11. W31 gate green; teardown residue 0.

F2 product code starts only after this gate is green. The gate fixture may move stock, but product F2 does not.

## 11. F2 tests

### Pure/unit

- Native pending quantity formula.
- Classification source = current Item master; missing/renamed group fails closed.
- Split planner: group map, disjointness, zero-group, ordering, no item-code aggregation.
- Request hash/scope, replay, mismatch.
- Profile validation/defaults/revision.

### Site gate

- Settings save/read as System Manager; Stock User read-only; invalid role/warehouse/print format rejected.
- Generate happy path: one Run, 0–1 PL per group, all draft, no stock mutation, custom fields set.
- Same key + same payload returns same Run/PL; same key + different payload 409; concurrent/duplicate scope rejected; active Run reuse.
- Stale SO, reservation, non-stock/bundle, missing Item Group, stock shortage, rollback on second-PL failure.
- Preview `can_generate` and Run link after generation.
- F1 queue/preview regression; W31 gate; residue 0.

### Browser

- Settings panel loads all sections, saves all fields, read-only for non-admin, company switch.
- Queue drawer disabled/enabled Generate states; successful generation shows Run and PL links; replay state; error state.
- No horizontal overflow at 1440/1024/390; no console errors.

## 12. Migration and rollout

- Add Profile fields via DocType JSON/migrate; existing F1 profile receives defaults, `config_revision=1`.
- Add Run/Allocation/Request Key DocTypes and Pick List custom fields through normal app migration/`upgrade.py`; idempotent.
- No data backfill for historical Runs (none exist).
- Feature flag remains `Profile.enabled`; disabled blocks Generate.
- Test site only. Production deployment, if ever approved, will follow the project’s existing app deploy pipeline and a separate acceptance gate.

## 13. Acceptance criteria

- [ ] R0 runtime gate green on `fulfillment.localhost`, W31 green, teardown residue 0.
- [ ] All PRD Profile fields are visible in the existing Settings page; writes are System Manager-only and revisioned.
- [ ] Frozen Item Group + child rule classifies correctly; missing/invalid data blocks Generate.
- [ ] Generate creates one Run and only non-empty native Draft PLs, one per group; no stock movement and no picked quantities.
- [ ] Same request key replays the same result; mismatch and duplicate active Run are safe.
- [ ] Shortage/ineligible/rollback paths leave no partial Run/PL.
- [ ] F1 queue/preview, profile display names, and `can_generate` remain consistent.
- [ ] Browser Settings and Generate acceptance passes; no overflow/console errors.
- [ ] Docs/state updated only with executed evidence; no push.

## 14. Deferred

F3 picking workspace and W31 quantities, PL submit/short-pick, batch/serial, F4 DN consolidation/Packing/verification, F5 print/assignment/settings hardening, partial delivery execution, Run rebuild/close, role-scoped picker enforcement, and any production deploy.

## 15. Open deviations to confirm at review

- Later-phase profile fields are optional until their phase, despite PRD “Required” markers.
- `role_order_coordinator` is stored from F2 but Generate permission in F2 is System Manager/Stock Manager; custom role enforcement can be completed when the full role matrix arrives.
- F2 blocks generation on any shortage rather than creating a partially allocated draft PL. Partial allocation is deferred to the controlled short-pick workflow.
