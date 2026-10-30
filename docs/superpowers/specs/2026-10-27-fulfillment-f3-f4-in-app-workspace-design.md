# F3/F4 — In-App Picking, One DN from Two Pick Lists, Packing, and DN Submit

**Status:** revision 3, MVP scope confirmed for user review, 2026-10-27 (flexible action hub; packing correction; existing print reuse; PRD compliance snapshot)

**Extends:** F2 Generate (`2026-10-27-fulfillment-f2-settings-run-generate-design.md`)

**Binding sources:** `PRD_Warehouse_Fulfillment_ERPNext_v16.md`, F1/F2 specs, native ERPNext 16 behavior verified on `fulfillment.localhost`, and the user decisions below.

## 1. Decisions

1. The happy path stays inside `/gudang`; the user must not be sent to Desk for picking, DN creation, packing, or DN submit.
2. The first end-to-end target is Sales Order `SAL-ORD-2026-00073`: one Dry Pick List and one Frozen Pick List become **one native Delivery Note**.
3. The DN is **review-only** in the SPA. The app uses native Sales Order → DN mapping for commercial fields; it does not provide a full tax/address/rate editor.
4. The first release creates **one Packing Slip for the whole DN**. Native support for multiple Packing Slips exists, but multi-package UI is deferred.
5. Short pick is configurable through the existing Profile field `short_pick_approval_required`:
   - **Off = Block.** A short qty may be saved as progress, but the Pick List cannot be submitted.
   - **On = Require approval.** A short qty may be saved; submission and DN creation wait for approval.
6. The short-pick approver is **System Manager**, or **Stock Manager paired with Stock User** for native read access. This is fixed for this phase; the configured role fields are not used for approval yet.
7. DN submit is performed by **System Manager**, or **Stock Manager paired with Stock User**. There is no separate checker or dispatch role in this phase.
8. The workspace is a dedicated route, `/gudang/fulfillment/<run>`, with one prominent **Next action** and freely reachable tabs. It is an action hub, not a locked wizard; the queue drawer remains the entry point for Generate.
9. Packing is mandatory but fast: one click **Pack all** fills the whole DN. Until the DN is submitted, an authorized user can **reset packing** (cancel the native Packing Slip) to correct a wrong package quantity.
10. Existing Dry/Frozen Pick List print formats are reused; the workspace adds print buttons, not a new Print Center or new print format.
11. All work remains on the disposable `fulfillment.localhost` demo. `erp.localhost`, `1oktober2026`, production data, and the production stack are out of scope.
12. No commit or push without explicit user approval.
13. The confirmed MVP chain is: Dry/Frozen picking for one outlet Sales Order → one Delivery Note Draft → one Packing Slip → native DN Submit. Full PRD P0 items outside this chain are deferred and recorded in §16; this MVP is not production-complete until those are closed.

## 2. Goal and non-goals

### Goal

An authorized warehouse user can open an active Fulfillment Run from the Order Queue, record Dry/Frozen picked quantities, handle short picks through the configured policy, submit both native Pick Lists with one **Finish picking** action, create one native Delivery Note from both lists, pack the DN with one **Pack all** action, and submit the Delivery Note. The result is auditable native documents and stock movement only at DN submit. The quantity chain is Sales Order demand → actual picked qty → DN qty → packed qty; the app never silently substitutes SO qty for actual stock.

### Non-goals for this phase

- Full DN editor, tax/address/rate editing, or custom financial mapping.
- Multi-package Packing Slip UI; the endpoint may remain extensible, but the accepted scope is one package per DN.
- Editable packing allocation; **Pack all** is the primary action. A submitted package can be reset and recreated before DN submit.
- Batch/serial scanning, barcode mode, expiry warnings, and shelf-life policy.
- Separate checker verification or dispatch roles.
- New Print Center, new print formats, assignment, and activity log. Existing PL print formats remain usable from the workspace.
- Partial shipments across multiple Runs, DN cancellation/amendment, returns, or reconciliation workflows.
- Product Bundle, drop-ship, supplier-delivered, non-stock, or cross-company DN cases; these fail closed with a clear error.
- Actual-data restore from the 20 October `stream` backup; the missing `product_qr`/16.52 stack remains a separate blocker.
- Changes to core Frappe/ERPNext or native DocPerms.

## 3. Current baseline and gaps

| Area | Current state | Gap this phase resolves |
|---|---|---|
| Queue | F1 read-only stage and drawer | In Picking is only a label; no picking screen or write action |
| Pick List | F2 creates draft Dry/Frozen PLs | No save progress, short-pick policy, approval, or submit |
| Delivery Note | Related documents are links only | No one-DN consolidation from Dry + Frozen PLs |
| Packing Slip | Related documents are links only | No package creation, packed-qty gate, or submit flow |
| DN submit | Not implemented | No in-app gate or stock movement |
| Short pick | Profile field exists but is hidden | No UI, approval state, or guard |
| Run | `delivery_note` field absent; status limited to PLANNING | No DN lineage or workflow status |
| DN/PS lineage | No app link fields | Cannot audit which Run produced them |

Native capabilities already verified in the repository:

- `erpnext.stock.doctype.pick_list.pick_list.create_dn_for_pick_lists(source_name, target_doc)` maps a second Pick List into an existing DN.
- `Pick List.validate_picked_items()` permits a short picked quantity when `scan_mode = 0`; F2 creates PLs with `scan_mode = 0`.
- `Delivery Note.make_packing_slip()` creates a native Packing Slip for the remaining DN quantity.
- `Packing Slip` validates `dn_detail` and remaining `qty - packed_qty`, and updates `packed_qty` on submit.
- The existing W31 `custom_picked_qty`/`picked_qty` synchronization remains authoritative for Pick List UOM.

## 4. Architecture

### 4.1 Components

| Component | Responsibility |
|---|---|
| `fulfillment/picking.py` | Load picking rows, save progress, short-pick policy, fingerprint, native PL submit |
| `fulfillment/approval.py` | Request, approve, reject, and validate short-pick approval |
| `fulfillment/delivery.py` | Validate two PLs, call native `create_dn_for_pick_lists`, link DN to Run |
| `fulfillment/packing.py` | Pack all from DN remaining quantity, assign case number, submit PS, reset/recreate before DN submit |
| `fulfillment/dispatch.py` | Final gates and native DN submit |
| `fulfillment/workspace.py` | Read model for the workspace: documents, rows, gates, permissions, next action, status |
| `fulfillment/api.py` | Whitelisted endpoint wrappers and error mapping |
| `frontend/src/pages/FulfillmentWorkspacePage.vue` | Route, action hub, loading/error states |
| `frontend/src/components/fulfillment/*` | Picking, delivery, packing, review panels |
| `frontend/src/data/fulfillment.js` | Typed API calls; no business rules |

The queue page remains `/gudang/fulfillment`. A row with an active Run opens `/gudang/fulfillment/<run>`. A row without a Run continues to use the existing drawer and Generate action. After Generate succeeds, the drawer opens the new workspace.

### 4.2 Native-first boundary

The app writes only orchestration records, approvals, and links. Pick List, Delivery Note, Packing Slip, Stock Ledger Entry, taxes, addresses, and financial fields remain native. The app must not write stock or reconstruct DN financial data from item codes.

## 5. Data model

### 5.1 Profile

No new Profile field is required. The existing `short_pick_approval_required` Check is the short-pick policy:

- `0` → Block short pick submission.
- `1` → Require approval before submission.
- Default is `1`, matching the existing Profile default.

The Settings UI exposes this as **Short pick handling** with help text:

> If enabled, a short pick is held for System Manager/Stock Manager approval. If disabled, a short pick cannot be submitted.

The field is snapshotted into the Run at creation. Existing hidden policy fields are preserved; this phase does not enforce `allow_partial_delivery`, `require_checker_approval`, or `allow_cross_group_packing`. The one-package trial may contain Dry and Frozen lines; cross-group packing enforcement is a deferred policy.

### 5.2 Warehouse Fulfillment Run additions

| Field | Type | Rules |
|---|---|---|
| `delivery_note` | Link Delivery Note | 0–1; set only by the Delivery service |
| `short_pick_approval_required_snapshot` | Check | Copied from Profile at Generate |
| `short_pick_status` | Select | `None`, `Pending`, `Approved`, `Rejected`; default `None` |
| `short_pick_reason` | Small Text | Required when any short qty is pending/approved |
| `short_pick_rejection_reason` | Small Text | Reason from the approver when rejected |
| `short_pick_fingerprint` | Data | Hash of short PL rows at request/approval time |
| `short_pick_requested_by` | Link User | Set on request |
| `short_pick_requested_on` | Datetime | Set on request |
| `short_pick_approved_by` | Link User | Set on approve/reject |
| `short_pick_approved_on` | Datetime | Set on approve/reject |
| `dn_created_at` | Datetime | Set when DN is created |
| `dispatched_at` | Datetime | Set when native DN submit succeeds |

Status options:

`PLANNING`, `PICKING`, `PICKED`, `DN_DRAFT`, `PACKING`, `READY`, `DISPATCHED`, `NEEDS_RECONCILIATION`.

`status` is derived/reconciled from native documents after each write. It is never set optimistically before the native action succeeds.

Existing Runs created before this phase receive `short_pick_approval_required_snapshot` from their current Profile during migration; if no Profile value is available, use `1`. They remain otherwise readable and can enter the workspace without a new Generate.

### 5.3 Delivery Note and Packing Slip links

- Delivery Note custom field `custom_fulfillment_run` → Link Run.
- Packing Slip custom field `custom_fulfillment_run` → Link Run.
- The Run `delivery_note` is the primary 0–1 link; the DN custom field is the reverse audit link.
- Pick List already has `custom_fulfillment_run` and `custom_fulfillment_group`.
- All fields are installed through the app's idempotent `upgrade.py`/migrate path. No core DocType edits.

### 5.4 Short-pick details

The short-pick lines are derived from the native PL rows where:

```text
0 < custom_picked_qty < qty
```

A zero-picked line is **not** supported in this MVP: native `Pick List.validate_picked_items()` auto-fills `picked_qty = stock_qty` when `scan_mode = 0` and `picked_qty = 0`. Allowing zero would silently turn a zero pick into a full pick. The app rejects `picked_qty = 0` with `PICKED_QTY_ZERO_UNSUPPORTED`; a skip/cancel flow is deferred. A positive short pick (for example 35 of 40) remains fully supported.

The fingerprint is a deterministic hash of:

```text
pick_list, pick_list_item, item_code, qty, custom_picked_qty
```

The approval is one status per Run and one reason for the Run. Per-line reasons are not in this phase. If any short row changes, the fingerprint changes and a previous approval is invalid.

### 5.5 Quantity authority

- Sales Order qty is demand, not physical stock.
- Pick List `qty` is the target; `custom_picked_qty` / `picked_qty` is what is physically available and picked.
- A short pick is allowed only through the configured policy:
  - Block: the PL cannot submit while picked qty is short.
  - Approval: the PL can submit only after the short pick is approved.
- The DN is built from picked quantities, never from SO demand. If 12 were ordered and 10 were approved as short-picked, the DN line carries 10; the remaining 2 stay outstanding on the SO.
- Packing uses DN remaining qty, never SO qty. **Pack all** therefore packs exactly what the DN says.
- Packing reset changes only the Packing Slip allocation, not picked qty or DN qty. If picked/DN qty is wrong, it must be corrected before PL submit; after PL/DN submit is outside this phase.

## 6. State machine

```text
PLANNING
  → PICKING          (draft PL exists)
  → PICKED           (all applicable PLs submitted)
  → DN_DRAFT         (one native DN Draft exists)
  → PACKING          (Packing Slip draft/submitted)
  → READY            (all DN qty packed)
  → DISPATCHED       (DN native docstatus=1)
```

Exception overlay:

- `short_pick_status = Pending` blocks submit of the Pick List that has short rows, and blocks DN creation and DN submit. The other group's PL may still be submitted.
- `short_pick_status = Rejected` blocks that PL's submission and DN creation until the qty is corrected or a new request is approved.
- `short_pick_status = Approved` is valid only while the fingerprint matches.
- Packing reset moves `READY`/`PACKING` back to `PACKING`; it is allowed only while the DN is Draft.
- Native inconsistency moves the Run to `NEEDS_RECONCILIATION`; the UI shows the native error and offers reload, not a bypass.

## 7. Flow

### 7.1 Picking

1. Load the Run, its SO, and the 0–2 native PLs.
2. Show Dry and Frozen tabs separately; a missing group is shown as not applicable, not as an empty PL.
3. For each PL row show item, warehouse, target qty, picked qty, UOM, batch/serial if present, and status.
4. User edits picked qty. Save writes `custom_picked_qty` and synchronizes native `picked_qty` (`custom_picked_qty * conversion_factor`); the W31 hook remains idempotent for converted rows, while stock-UOM rows bypass it. Zero is rejected with `PICKED_QTY_ZERO_UNSUPPORTED` before saving.
5. **Print Dry** and **Print Frozen** open the existing Pick List print formats in a new tab. The service does not generate a new print format or PDF. Print uses the saved PL, so save first if the qty changed.
6. Save does not submit, does not move stock, and does not change SO delivered qty.
7. If there is no short row: **Finish picking** submits all applicable draft PLs in one action. A per-group submit remains available for exceptions. Any draft row with zero picked qty fails `PICKED_QTY_ZERO_UNSUPPORTED`; the app never lets native auto-fill an untouched row to full.
8. If there is a short row and the snapshot policy is Block: save is allowed; **Finish picking** returns `SHORT_PICK_BLOCKED`.
9. If there is a short row and the snapshot policy is Approval:
   - Save may store the short progress.
   - Request approval requires a non-empty reason.
   - The Run becomes Pending and stores a fingerprint.
   - **Finish picking** returns `SHORT_PICK_APPROVAL_PENDING` until approval.
10. A System Manager or Stock Manager may approve or reject inline in the workspace. Approval does not submit the PL.
11. After approval, **Finish picking** submits the remaining draft PLs. Submit uses native PL submit with `scan_mode = 0`. The native short-pick behavior is trusted; the app does not fake `picked_qty`.
12. If one group was already submitted, the action submits only the remaining group. After both applicable groups are submitted, the Run becomes PICKED.
13. Picking tabs do not enforce a required order; the Next action bar decides what is currently valid. Picking is complete only after native submit.

### 7.2 Delivery Note

1. **Create DN** is enabled only when every applicable PL is submitted and the Run has no Pending/Rejected approval.
2. The service loads the Dry PL, calls native `create_dn_for_pick_lists`; if a Frozen PL exists, calls the same function with the Dry result as `target_doc`.
3. The native mapper supplies SO header, customer, currency, taxes, addresses, payment terms, and item financial fields.
4. The service sets `custom_fulfillment_run` on the DN and inserts it as `docstatus = 0`.
5. The service stores the DN name on the Run and sets status `DN_DRAFT`.
6. No stock movement happens here. The DN remains editable only through native correction paths outside this phase; the SPA does not expose a financial editor.
7. The review tab is available but not mandatory. The Next action becomes **Pack all** after the DN exists.
8. If the Run already has a DN, the call returns it and does not create a second document.

### 7.3 Packing

1. Packing is mandatory and available only when the DN is Draft.
2. Show DN item rows with `qty`, `packed_qty`, and remaining. All quantities come from DN remaining, never SO demand.
3. **Pack all** creates one native Packing Slip for the whole remaining DN quantity in one action.
4. The service calls `make_packing_slip(dn.name)`, sets `from_case_no = 1` and `to_case_no = 1`, inserts, and submits the PS.
5. Native validation enforces `qty <= DN remaining` and Packing Slip Draft-only rules.
6. If the package qty is wrong and the DN is still Draft, **Reset packing** cancels the native Packing Slip and clears `packed_qty`; the user can then **Pack all** again. Reset requires confirmation and never changes picked qty or DN qty.
7. Reset is not allowed after DN submit. Native DN cancellation/amendment is outside this phase.
8. On PS submit, native `packed_qty` is updated. No stock movement happens here.
9. If all DN rows have `packed_qty >= qty`, the Run becomes READY.
10. Multi-package creation is deferred; the service signature must not assume only one package forever.

### 7.4 Review and DN submit

1. The review panel shows the gate checklist:
   - all applicable PLs submitted;
   - short pick absent or Approved with matching fingerprint;
   - one DN Draft exists;
   - every DN row fully packed;
   - native permissions pass.
2. Review is available but not a mandatory step. The Next action is **Submit DN**.
3. Submit asks for one confirmation with the DN qty and then calls native `dn.submit()`.
4. Only a successful native submit may set Run `DISPATCHED` and `dispatched_at`; the app reads back native `docstatus` and stock effects rather than assuming success.
5. The SPA shows the resulting DN, Run status, and that stock has moved. There is no redirect to Desk.
6. If native validation fails, the transaction rolls back and the UI shows the native error plus a correlation id.

## 8. API

All endpoints are whitelisted POST except the workspace read. Errors use stable codes.

| Endpoint | Input | Output | Notes |
|---|---|---|---|
| `get_run_workspace` | `run` | SO, profile, PL groups, rows, short policy/status, DN, PS, gates, permissions | Read-only |
| `save_picking` | `run`, `rows`, `reason`, `expected_modified` per PL | updated rows, short state, status | Revision/expected modified required |
| `request_short_pick_approval` | `run`, `reason` | pending status, fingerprint | Reason required |
| `approve_short_pick` | `run`, `expected_fingerprint` | approved status | System Manager/Stock Manager |
| `reject_short_pick` | `run`, `reason` | rejected status | Reason required |
| `submit_pick_list` | `run`, `group`, `expected_pl_modified` | PL status, Run status | Per-group exception path |
| `complete_picking` | `run`, `expected_modified` per PL | PL statuses, Run status | One-click submit of all applicable draft PLs |
| `create_delivery_note` | `run`, `idempotency_key` | DN name/status, Run status | Native one-DN consolidation |
| `pack_all` | `run`, `expected_dn_modified` | PS name/status, packed progress | One package in this phase |
| `reset_packing` | `run`, `expected_dn_modified` | cleared packing, Pack all available | Cancels submitted PS while DN is Draft |
| `submit_delivery_note` | `run`, `idempotency_key`, `expected_dn_modified` | DN status, Run status | Native DN submit |

### 8.1 Request and concurrency rules

- Every write checks the Run's company and the user's permissions.
- `save_picking` accepts only rows belonging to the Run's PLs.
- `submit_pick_list` requires the expected PL `modified` value; stale values return `STALE_PL`.
- `complete_picking` requires the expected `modified` value for every applicable draft PL; stale values return `STALE_PL`. Already-submitted PLs are skipped.
- `create_delivery_note` requires a request key and the expected PL versions.
- `pack_all` requires the expected DN `modified` value; stale values return `STALE_DN`. If one submitted Packing Slip already exists for the Run, return it instead of creating a second.
- `reset_packing` requires the expected DN `modified` value and the DN must still be Draft; otherwise `PACKING_RESET_NOT_ALLOWED`. If no PS exists, it is a no-op.
- `submit_delivery_note` requires a request key and the expected DN `modified` value.
- Native calls run in one transaction; an error rolls back the app fields and the native document.
- No `ignore_permissions` in these endpoints.

## 9. UI

### 9.1 Entry point

- Queue row with an active Run → open workspace.
- Queue row without a Run → existing Generate drawer.
- After Generate → open the workspace for the returned Run.
- The drawer keeps native document links for audit, but the happy-path primary action goes to the workspace.

### 9.2 Workspace

Header:

- SO, customer, company, delivery date.
- Current stage and short-pick banner.
- Profile/company context.
- Refresh and back-to-queue.

**Next action bar** (always visible, above the tabs):

- One primary button that reflects the next valid action:
  - Draft picking → **Finish picking**, or **Request approval** when a short pick needs it.
  - PLs submitted, no DN → **Create DN**.
  - DN Draft, not packed → **Pack all**.
  - DN Draft, fully packed → **Submit DN**.
  - DN submitted → **Done** (read-only success).
- Secondary buttons: **Print Dry**, **Print Frozen**, **Save**, **Reset packing**, **Refresh**. Only applicable secondary buttons are shown.

**Tabs** (freely reachable when unlocked; no forced order):

1. **Picking**
   - Dry/Frozen tabs.
   - Table rows: item, warehouse, target, picked, UOM, batch/serial, status.
   - Save progress; Print Dry/Print Frozen; Request approval when short; Approve/Reject inline for authorized users.
   - **Finish picking** submits all applicable draft PLs in one action. A per-group submit remains as an exception path.
   - Disabled with an explicit reason when short policy blocks or approval is pending.

2. **Delivery**
   - Readiness checklist.
   - **Create DN**.
   - DN review: header, line items, quantities, warehouse, batch, SO references.
   - No tax/address/rate editor; show a read-only summary.

3. **Packing**
   - DN remaining quantities, never SO qty.
   - Package 1 card; quantity prefilled to DN remaining.
   - **Pack all** creates and submits the Packing Slip in one action.
   - **Reset packing** is visible only while the DN is Draft; it cancels the PS and returns to Pack all.
   - Packed progress; READY when complete.

4. **Review & Submit**
   - Final checklist.
   - **Submit DN** with one confirmation.
   - Success state with Run status and stock-movement notice.

### 9.3 UX rules

- One prominent primary action at a time; the Next action button is always visible on desktop and tablet.
- No locked wizard. Unlocked tabs can be opened in any order; prerequisites are enforced by disabled states and the server.
- One-click bulk actions: **Finish picking**, **Pack all**, and **Submit DN**; only DN submit and packing reset ask for confirmation.
- **Print Dry** and **Print Frozen** open the existing Pick List print format in a new tab. No new print builder; save the PL first if qty changed.
- Short-pick approval is inline in the workspace; no separate approval page.
- Buttons disabled with a visible reason, not silent.
- Native errors shown in the SPA with correlation id.
- No permanent focus trap except modal dialogs.
- Keyboard Enter submits the active quantity row; Escape closes dialogs only.
- Mobile/tablet: tabs remain reachable; picking table becomes cards; primary action stays visible.
- No offline editing.
- Loading, empty, error, stale, and success states are explicit.

## 10. Permissions and security

| Action | Allowed |
|---|---|
| View queue/workspace | System Manager, Stock Manager, Stock User |
| Save picking | System Manager, or Stock Manager with Stock User |
| Submit Pick List / Finish picking | System Manager, or Stock Manager with Stock User |
| Request short pick | Same as Save picking |
| Approve/reject short pick | System Manager, or Stock Manager with Stock User |
| Create DN | System Manager, or Stock Manager with Stock User |
| Pack all | System Manager, or Stock Manager with Stock User |
| Reset packing | System Manager, or Stock Manager with Stock User |
| Submit DN | System Manager, or Stock Manager with Stock User |

Server checks roles and native DocPerms. Client-side visibility is not security. A Stock Manager without Stock User may read the app record but cannot perform native document actions unless the native permissions independently allow it.

## 11. Errors, idempotency, and recovery

Stable error codes:

- `PROFILE_INVALID`, `PROFILE_DISABLED`
- `RUN_NOT_FOUND`, `RUN_ALREADY_DISPATCHED`
- `PL_NOT_DRAFT`, `PL_NOT_SUBMITTED`, `STALE_PL`
- `SHORT_PICK_BLOCKED`, `SHORT_PICK_APPROVAL_PENDING`, `SHORT_PICK_APPROVAL_REJECTED`, `SHORT_PICK_STALE_APPROVAL`
- `PICKED_QTY_ZERO_UNSUPPORTED` (native zero auto-fill guard)
- `DN_EXISTS`, `DN_NOT_DRAFT`, `DN_NOT_FULLY_PACKED`, `STALE_DN`
- `PACKING_NOT_AVAILABLE`, `PACKING_INCOMPLETE`
- `PACKING_RESET_NOT_ALLOWED`, `PACKING_ALREADY_SUBMITTED`
- `NATIVE_ERROR`, `PERMISSION_DENIED`

Each error response carries a human message and a correlation id. The client shows the message, not a generic success. A failed write leaves no partial DN/PS; the app reloads the workspace.

Idempotency:

- Reuse `Warehouse Fulfillment Request Key`; do not add a second request-key DocType.
- Add request types `CreateDeliveryNote` and `SubmitDeliveryNote`, scoped to the Run's Sales Order and actor.
- Extend the request-hash helper with a canonical payload hash for DN/PS operations; keep the existing Generate hash behavior unchanged.
- Store the resulting DN/PS names in `result_doc_refs`.
- A repeated request with the same key returns the same result.
- A request with the same key but different payload returns `IDEMPOTENCY_MISMATCH`.

## 12. Native integration details

### 12.1 Pick List

- Load rows from `Pick List` and `Pick List Item`.
- Save `custom_picked_qty` and synchronize native `picked_qty`; the W31 hook remains idempotent for converted rows. Reject zero before saving.
- Submit through the native document method; do not call `db_set` for docstatus.
- **Finish picking** calls native submit for every applicable draft PL in one transaction; per-group submit uses the same path.
- `scan_mode` stays 0; short submit is validated by native `validate_picked_items`.
- No stock movement on PL submit.
- Print opens the existing `dry_print_format`/`frozen_print_format`; the service does not generate a new print format.

### 12.2 Delivery Note

- Use `create_dn_for_pick_lists` for the Dry PL, then with `target_doc` for the Frozen PL.
- Validate same SO, company, customer before calling.
- Call `insert` only when the returned DN has no name; preserve the native mapper's header/financial fields.
- Do not use a hand-built minimal DN.
- Do not submit in this step.

### 12.3 Packing Slip

- Use `make_packing_slip(dn.name)` to get remaining qty; use DN qty, never SO qty.
- Set one case number; insert and submit.
- Let native validation enforce remaining qty and Draft-only DN.
- Update UI progress from `packed_qty` after reload.
- If one submitted Packing Slip already exists for the Run, **Pack all** returns it; do not create a second PS.
- **Reset packing** cancels the submitted Packing Slip only while the DN is Draft, then reloads the DN so `packed_qty` returns to zero. It does not modify picked qty or DN qty.
- After DN submit, reset is rejected; no native DN cancel/amend shortcut in this phase.

### 12.4 DN submit

- Reload the DN after packing; verify `packed_qty`.
- Verify short approval fingerprint.
- Call native `dn.submit()`.
- Reload and read `docstatus`; only then mark Run DISPATCHED.

## 13. Testing

### 13.1 New integration gate `w54_f3_f4_gate.py`

Required scenarios on `fulfillment.localhost`:

1. Full pick: save Dry/Frozen, call **Finish picking** once, assert both applicable PLs submitted; create one DN; assert one DN, both `against_pick_list` values, no stock movement yet.
2. **Pack all** one package: create/submit one Packing Slip, assert all DN rows fully packed; submit DN; assert stock movement and Run DISPATCHED.
3. Packing mandatory: without a Packing Slip, DN submit is rejected `PACKING_INCOMPLETE`.
4. Packing reset: after Pack all, **Reset packing** cancels the PS, `packed_qty` returns to 0, Pack all again, then DN submit; assert stock moves only on DN submit and reset is rejected after DN submit.
5. Finish picking partial groups: one group already submitted, the other still draft; Finish picking submits only the remaining group.
6. Double-click Finish picking, Create DN, Pack all, and Submit DN; assert no second PL/DN/PS and idempotent result.
7. Short pick with policy Block: save short allowed, Finish picking rejected `SHORT_PICK_BLOCKED`, no DN.
8. Short pick with policy Approval: request pending, Finish picking blocked, approve, Finish picking submits, DN uses short qty, remaining SO outstanding.
9. Change short qty after approval: approval stale, submit blocked, reapproval required.
10. Unauthorized user cannot approve, reset packing, or submit DN.
11. Native validation failure leaves no partial document.
12. Regression: F1 queue, F2 generate, W31 UOM, profile/settings, permissions.
13. Cleanup: no leftover test Run, PL, DN, PS, request key, or test user.

### 13.2 Browser checks

- Queue row opens the workspace for the active Run.
- Action hub shows one Next action; tabs unlock without forcing a wizard order.
- Finish picking → Create DN → Pack all → Submit works without `/app` navigation.
- Print Dry/Print Frozen opens the existing Pick List print format in a new tab.
- Long/short policy messages and the inline approval are visible.
- Reset packing confirmation works; Pack all is available again.
- Desktop 1440 and tablet 1024 layouts have no horizontal overflow.
- Console errors 0.
- Refresh/deep link on the workspace reloads the same Run.
- Native error path shows a readable SPA error.

### 13.3 Manual acceptance

Use SO73 demo:
- Dry PL `STO-PICK-2026-00006`, Frozen PL `STO-PICK-2026-00007`.
- Print Dry and Print Frozen; full pick; Finish picking; one DN; Pack all; submit DN.
- The gate creates fresh PLs for the short-pick Block and Approval cases.
- Reset packing on a wrong package before DN submit; verify stock ledger moves only at DN submit.

## 14. Rollout and risks

### 14.1 Rollout order

1. **F3**: action-hub read model, save picking, short-pick policy/inline approval, Finish picking, print buttons.
2. **F4a**: one DN from both PLs, review-only DN.
3. **F4b**: one-package Pack all, packing reset, native DN submit.
4. Browser verification on the demo.
5. No production/erp deployment.

### 14.2 Risks and mitigations

| Risk | Mitigation |
|---|---|
| Native `create_dn_for_pick_lists` behavior differs for the local v16.50 build | Gate R0 pattern reused; integration test asserts both PL links and one DN |
| Short pick native validation changes | Test `scan_mode=0`; fail closed with native error; do not fake qty |
| Approval stale after qty change | Fingerprint check on every approval and submit |
| Double DN/PS from double click | Request keys, expected modified, unique Run `delivery_note` |
| Packing Slip over-allocation | Native remaining-qty validation; reload after PS submit |
| Wrong package quantity after Pack all | Reset packing cancels the PS while DN is Draft; repack and verify packed_qty |
| Hidden Profile policy fields are not enforced | Explicitly out of scope; one package may mix groups; settings UI only exposes short pick |
| Print format missing or inaccessible | Reuse configured Dry/Frozen formats; surface native error in SPA; no new print builder |
| Actual data mismatch | Demo only; actual-data restore remains blocked on `product_qr`/16.52 |

## 15. Acceptance criteria

- User can complete SO73 Dry + Frozen picking from `/gudang` without opening `/app`.
- Finish picking submits applicable PLs in one action; Print Dry/Print Frozen use the existing formats.
- Two submitted PLs produce exactly one DN Draft.
- The DN is review-only and carries native header, tax, address, and item financial data.
- The DN qty follows approved picked qty, never SO demand; remaining SO stays outstanding after a short pick.
- Pack all is mandatory and packs DN remaining qty in one action; no SO qty is used.
- Reset packing can correct a wrong package before DN submit; it is blocked after DN submit.
- DN submit is blocked until all qty is packed and short pick is approved when policy requires it.
- DN submit moves stock and sets Run DISPATCHED.
- Short-pick Block and Approval modes behave as specified.
- No double DN, double PS, or partial app/native state on failure.
- Existing F1/F2/W31 behavior remains green.
- No changes to `erp.localhost`, `1oktober2026`, or production.

## 16. PRD compliance snapshot (MVP)

The MVP deliberately implements the shortest complete native chain, not every PRD P0 item. This table is the source of truth for scope decisions.

| PRD area | MVP status | Notes |
|---|---|---|
| SPA route `/gudang/fulfillment/:run`; no Desk on happy path | Aligned | Existing queue/drawer remains entry |
| Dry/Frozen classification per SO item and separate native PLs | Aligned | Reuses F2 split; no regrouping |
| Print Dry / Print Frozen using configured formats | Aligned | Existing formats reused; no new print builder |
| Picking rows: warehouse, target, picked, UOM, batch/serial display | Aligned | W31 UOM behavior preserved |
| Short pick with reason + approval; no fake picked qty | Partial | Native short submit with `scan_mode=0`; target-revision flow not implemented |
| Zero-picked line (0 of target) | Deferred | Rejected with `PICKED_QTY_ZERO_UNSUPPORTED`; native auto-fill would otherwise make it a full pick. A skip/cancel flow is not in MVP |
| One native DN Draft from two submitted PLs | Aligned | Native `create_dn_for_pick_lists` + `target_doc` |
| Native DN financial/header mapping | Aligned | No bespoke financial mapper |
| One native Packing Slip from DN Draft | Aligned | One package; Pack all + reset |
| Packing completeness before DN submit | Aligned | All DN qty packed |
| Native DN submit is the only stock movement | Aligned | Read-back after submit |
| Idempotency and stale guards | Aligned | Existing request-key table + expected modified |
| Multi-package Packing Slip, weights, cross-group policy | Deferred P0 | PRD FR-502/503/506/508 |
| Checker verification, re-verify, dispatch role | Deferred P0 | PRD FR-601–605, AC-19; DN submit currently SM/Stock Manager |
| Configurable stage roles | Deferred P0 | PRD §19.1/§21.2; role fields not enforced yet |
| `allow_partial_delivery`, `require_checker_approval`, `allow_cross_group_packing` | Deferred P0 | Stored but not enforced in MVP |
| Barcode/scan, batch/serial correction, expiry warnings | Deferred P0/P1 | Display/native pass-through only |
| `Print All`, reprint audit, print security | Deferred P0 | Per-group print buttons only |
| Run Item/Document Link/Event audit and reconciliation table | Deferred P0 | Minimal Run fields; native links only |
| Verification hash and immutable approval across material changes | Deferred P0 | Packing reset exists; checker verification not in MVP |
| Short-pick native target revision | Deferred decision | MVP uses native short submit after approval; revisit for production |
| Multi-company isolation, fail-closed native errors, no core edits | Aligned | Enforced server-side |

**Production gate:** do not deploy this MVP to `1oktober2026`/production until the deferred P0 rows are implemented or explicitly accepted by the user.

## 17. Spec self-review

- Placeholder scan: no TBD/TODO sections.
- Internal consistency: one DN per Run; one package in the first release; short-pick policy uses the existing Profile field; approver and DN submit roles are fixed; action hub is not a locked stepper.
- Quantity consistency: SO demand ≠ picked qty; DN uses picked qty; packing uses DN qty; short pick policy is the only way to proceed with less.
- Scope check: one implementation plan can cover the confirmed MVP chain F3 + F4a + F4b; multi-package, new print formats, assignment, checker verification, and other deferred P0 items are listed in §16.
- Production check: §16 explicitly says this MVP is not production-complete until deferred P0 items are closed or accepted.
- Recovery check: packing reset is limited to DN Draft; no stock movement and no DN qty change.
- Ambiguity check: short-pick Off means Block (not “allow without approval”); this is stated in the Settings help and API behavior.
