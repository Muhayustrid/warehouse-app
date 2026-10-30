# F3/F4 In-App Fulfillment Workspace MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let warehouse staff complete the happy path without opening ERPNext Desk: Dry/Frozen picking for one outlet Sales Order (SO), Finish picking, create one Delivery Note (DN) Draft from the submitted Pick Lists (PLs), Pack all into one Packing Slip, and submit the native DN.

**Architecture:** Extend the existing `warehouse_app` app with thin service modules over native ERPNext PL/DN/Packing Slip documents. The existing `/gudang` SPA gets a `/fulfillment/:run` workspace that is an action hub, not a locked wizard. The Run DocType stores orchestration and short-pick approval state only; stock, prices, taxes, UOM, batch/serial, and document status remain native. One Run has 0–2 PLs, at most one DN, and at most one Packing Slip in this MVP.

**Tech Stack:** Frappe/ERPNext v16.51/16.50, Python services in `warehouse_app/`, Vue 3.5 SPA in `frontend/`, native Pick List, Delivery Note, Packing Slip, and W31 UOM hooks.

**Spec:** `docs/superpowers/specs/2026-10-27-fulfillment-f3-f4-in-app-workspace-design.md` (revision 3, MVP scope confirmed)

## Global Constraints

- All mutations happen on `fulfillment.localhost` only. Never mutate `erp.localhost` or `1oktober2026`.
- Do not edit core Frappe/ERPNext. Do not add a new DocType for business data already owned by PL/DN/Packing Slip.
- Do not use `ignore_permissions=True` in user-facing endpoints.
- Native first: PL submit, DN creation, DN submit, and Packing Slip submit are native calls. No stock moves before DN submit.
- One Run → one DN → one Packing Slip in this MVP. Multi-package is explicitly deferred by the spec.
- One DN is built from every submitted PL in the Run, using `create_dn_for_pick_lists()` and `target_doc`; do not build a custom DN mapper.
- Short-pick policy comes from `Warehouse Fulfillment Profile.short_pick_approval_required` and is snapshotted on the Run:
  - `0` = `Block`: short qty cannot finish picking.
  - `1` = `Require approval`: short qty requires an approved fingerprint.
- Approver is System Manager, or Stock Manager paired with Stock User. Stock User alone is read-only.
- Reuse the existing Dry/Frozen print formats. Do not add a Print Center or new print formats.
- Do not change F2 classification/split rules, F1 queue shape, W31 `custom_picked_qty` behavior, or existing print formats.
- Use existing patterns: idempotent `upgrade.py` custom fields, `FulfillmentError`, Request Key table, `GATE_JSON`, `guard_site`, `frontend/src/lib/api.js`, and existing CSS tokens.
- No new frontend dependency. No commit or push without explicit user approval. A direct commit request still requires showing the proposed message and waiting for approval.
- Test commands below use the current test stack containers: `frappe16-backend-1` and `frappe16-frontend-1`. Do not substitute the production containers.
- Execution method and workspace approval are required before implementation. The local stack bind-mounts this repo; re-point mounts before using a separate worktree.

## Review Focus

1. **Stale short-pick approval:** changing any short row after approval must invalidate the fingerprint and block Finish picking; the old approval must never submit a different qty.
2. **Packing rollback:** Pack all must create exactly one submitted Packing Slip, Reset packing must cancel it before DN submit, and no reset may run after DN submit.
3. **Duplicate clicks:** Finish picking, Create DN, Pack all, and Submit DN must be safe to click twice; no second PL/DN/Packing document and no duplicate stock movement.
4. **One group / one PL:** an SO with only Dry or only Frozen must create and finish one PL, then create a DN and Packing Slip without an empty group.
5. **Native failure:** a failed native PL/DN/Packing call must leave no half-created app state, no partially submitted documents, and no stock movement.
6. **Print failure:** missing print format or a draft PL must show a clear error and must not silently fall back to a different format.
7. **Zero pick:** native PL auto-fills `picked_qty = stock_qty` when `scan_mode=0` and `picked_qty=0`; the app must reject zero with `PICKED_QTY_ZERO_UNSUPPORTED` instead of silently delivering the full quantity.

---

## File Structure

**New backend**
- `warehouse_app/warehouse_app/fulfillment/short_pick.py` — pure short-row selection, fingerprint, and finish blocker.
- `warehouse_app/warehouse_app/fulfillment/permissions.py` — pure role predicates and Frappe role gates.
- `warehouse_app/warehouse_app/fulfillment/workspace.py` — Run read model, next action, gates.
- `warehouse_app/warehouse_app/fulfillment/picking.py` — save picking, per-group submit, Finish picking.
- `warehouse_app/warehouse_app/fulfillment/approval.py` — request/approve/reject short pick.
- `warehouse_app/warehouse_app/fulfillment/delivery.py` — one native DN from submitted PLs.
- `warehouse_app/warehouse_app/fulfillment/packing.py` — Pack all and Reset packing.
- `warehouse_app/warehouse_app/fulfillment/dispatch.py` — native DN submit and Run finalization.
- `warehouse_app/tests/test_fulfillment_short_pick.py` — pure short-pick tests.
- `warehouse_app/tests/test_fulfillment_permissions.py` — pure role matrix tests.
- `warehouse_app/tests/test_fulfillment_workspace.py` — pure next-action tests.
- `warehouse_app/tests/w54_schema_gate.py` — Run/DN/Packing schema gate.
- `warehouse_app/tests/w54_f3_f4_gate.py` — integration gate for the whole chain.

**Modified backend**
- `warehouse_app/warehouse_app/doctype/warehouse_fulfillment_run/warehouse_fulfillment_run.json` — DN, short-pick, timestamps, statuses.
- `warehouse_app/warehouse_app/fulfillment/generate.py` — snapshot `short_pick_approval_required`.
- `warehouse_app/warehouse_app/fulfillment/api.py` — GET workspace and write endpoints.
- `warehouse_app/warehouse_app/fulfillment/loader.py` — include the active Run in queue rows.
- `warehouse_app/warehouse_app/fulfillment/idempotency.py` — generic request-payload hash.
- `warehouse_app/upgrade.py` — DN/Packing Slip lineage custom fields; snapshot backfill.
- `warehouse_app/tests/test_fulfillment_idempotency.py` — generic hash regression tests.

**Frontend**
- `frontend/src/data/fulfillment.js` — workspace and action calls.
- `frontend/src/router.js` — `/fulfillment/:run` route.
- `frontend/src/pages/FulfillmentPage.vue` — queue → workspace navigation; post-generate navigation.
- `frontend/src/components/FulfillmentDrawer.vue` — workspace link instead of Desk for the happy path.
- `frontend/src/pages/FulfillmentWorkspacePage.vue` — action hub, tabs, action feedback.
- `frontend/src/components/fulfillment/PickingPanel.vue` — Dry/Frozen tables, print, save, short pick, finish.
- `frontend/src/components/fulfillment/DeliveryPanel.vue` — DN create/review.
- `frontend/src/components/fulfillment/PackingPanel.vue` — Pack all and Reset packing.
- `frontend/src/components/fulfillment/ReviewPanel.vue` — native DN submit.
- `frontend/src/pages/SettingsPage.vue` — short-pick policy checkbox.

**Runtime commands**
```text
BENCH=docker exec frappe16-backend-1 bench --site fulfillment.localhost
${BENCH} migrate
${BENCH} clear-cache
${BENCH} run-tests --app warehouse_app
${BENCH} execute warehouse_app.tests.w54_schema_gate.run_gate
${BENCH} execute warehouse_app.tests.w54_f3_f4_gate.run_gate
```

---

### Task 1: Pure short-pick rules and tests

**Files**
- Create: `warehouse_app/warehouse_app/fulfillment/short_pick.py`
- Test: `warehouse_app/tests/test_fulfillment_short_pick.py`

**Interfaces**
- `short_rows(rows: Iterable[Mapping]) -> list[dict]`
- `short_fingerprint(rows: Iterable[Mapping]) -> str`
- `finish_blocker(short: list[dict], approval_required: bool, status: str | None, fingerprint: str | None) -> str | None`

A short row is a PL location whose `custom_picked_qty` is greater than zero and less than `qty` (`0 < custom_picked_qty < qty`). Zero is a separate unsupported state rejected before save/submit. The fingerprint is SHA-256 over sorted, rounded values of `pick_list`, `row`, `item_code`, `qty`, and `custom_picked_qty`. Empty short rows produce the SHA-256 of `[]`.

- [ ] **Step 1: Write the failing unit tests**

```python
class TestShortPickRules(unittest.TestCase):
	def test_empty_short_rows(self):
		self.assertEqual(short_rows([]), [])
		self.assertEqual(len(short_fingerprint([])), 64)

	def test_short_row_uses_custom_picked_qty(self):
		rows = [
			{"pick_list": "PL-1", "row": "r1", "item_code": "A", "qty": 10, "custom_picked_qty": 7},
			{"pick_list": "PL-1", "row": "r2", "item_code": "B", "qty": 5, "custom_picked_qty": 5},
		]
		self.assertEqual([row["row"] for row in short_rows(rows)], ["r1"])

	def test_zero_is_not_a_short_row(self):
		rows = [{"pick_list": "PL-1", "row": "r1", "item_code": "A", "qty": 10, "custom_picked_qty": 0}]
		self.assertEqual(short_rows(rows), [])

	def test_fingerprint_changes_when_short_qty_changes(self):
		base = [{"pick_list": "PL-1", "row": "r1", "item_code": "A", "qty": 10, "custom_picked_qty": 7}]
		changed = [{**base[0], "custom_picked_qty": 6}]
		self.assertNotEqual(short_fingerprint(base), short_fingerprint(changed))

	def test_fingerprint_is_order_independent(self):
		a = {"pick_list": "PL-1", "row": "r1", "item_code": "A", "qty": 10, "custom_picked_qty": 7}
		b = {"pick_list": "PL-2", "row": "r2", "item_code": "B", "qty": 8, "custom_picked_qty": 3}
		self.assertEqual(short_fingerprint([a, b]), short_fingerprint([b, a]))

	def test_block_policy_blocks_any_short(self):
		short = [{"pick_list": "PL-1", "row": "r1", "item_code": "A", "qty": 10, "custom_picked_qty": 7}]
		self.assertEqual(finish_blocker(short, False, None, None), "SHORT_PICK_BLOCKED")

	def test_approval_requires_matching_fingerprint(self):
		short = [{"pick_list": "PL-1", "row": "r1", "item_code": "A", "qty": 10, "custom_picked_qty": 7}]
		fp = short_fingerprint(short)
		self.assertEqual(finish_blocker(short, True, "None", fp), "SHORT_PICK_APPROVAL_PENDING")
		self.assertEqual(finish_blocker(short, True, "Rejected", fp), "SHORT_PICK_APPROVAL_REJECTED")
		self.assertEqual(finish_blocker(short, True, "Approved", "wrong"), "SHORT_PICK_STALE_APPROVAL")
		self.assertIsNone(finish_blocker(short, True, "Approved", fp))
```

- [ ] **Step 2: Run the tests and confirm failure**

```text
${BENCH} run-tests --app warehouse_app
```

Expected: missing module or missing functions; no other test should be changed.

- [ ] **Step 3: Implement the pure module**

Use no Frappe imports. Normalize values with a small local float helper and round to 6 decimals before hashing. Return dicts with keys `pick_list`, `row`, `item_code`, `qty`, and `custom_picked_qty`.

- [ ] **Step 4: Run the tests and confirm pass**

```text
${BENCH} run-tests --app warehouse_app
```

Expected: all tests pass, including the existing F2 suite.

- [ ] **Step 5: Checkpoint (no commit)**

Record the test output. Do not commit until the user approves the proposed message `feat(fulfillment): add short-pick rules`.

---

### Task 2: Run fields, native lineage fields, and policy snapshot

**Files**
- Modify: `warehouse_app/warehouse_app/doctype/warehouse_fulfillment_run/warehouse_fulfillment_run.json`
- Modify: `warehouse_app/warehouse_app/fulfillment/generate.py`
- Modify: `warehouse_app/upgrade.py`
- Test: `warehouse_app/tests/w54_schema_gate.py`

**Interfaces**
- Run fields: `delivery_note`, `short_pick_approval_required_snapshot`, `short_pick_status`, `short_pick_reason`, `short_pick_rejection_reason`, `short_pick_fingerprint`, `short_pick_requested_by`, `short_pick_requested_on`, `short_pick_approved_by`, `short_pick_approved_on`, `dn_created_at`, `dispatched_at`.
- Status options: `PLANNING`, `PICKING`, `PICKED`, `DN_DRAFT`, `PACKING`, `READY`, `DISPATCHED`, `NEEDS_RECONCILIATION`.
- `short_pick_status` options: `None`, `Pending`, `Approved`, `Rejected`; default `None`.
- Native custom fields: `Delivery Note.custom_fulfillment_run` and `Packing Slip.custom_fulfillment_run` (Link → Warehouse Fulfillment Run, read-only).
- `generate._create_run()` sets `short_pick_approval_required_snapshot` from `profile.short_pick_approval_required` (1/0).
- `upgrade.ensure_fulfillment_lineage_fields()` is called from `upgrade.apply()`.
- `upgrade.backfill_run_short_pick_snapshot()` fills missing/snapshot-zero PLANNING runs from their profile; call it after field installation.

- [ ] **Step 1: Write the failing schema gate**

Create `w54_schema_gate.py` with a `run_gate()` that prints exactly one `GATE_JSON:{...}` line and checks:

```python
meta = frappe.get_meta("Warehouse Fulfillment Run")
check("run_delivery_note", bool(meta.get_field("delivery_note")))
check("run_short_snapshot", bool(meta.get_field("short_pick_approval_required_snapshot")))
check("run_short_status", "Approved" in (meta.get_field("short_pick_status").options or ""))
check("dn_lineage", bool(frappe.get_meta("Delivery Note").get_field("custom_fulfillment_run")))
check("ps_lineage", bool(frappe.get_meta("Packing Slip").get_field("custom_fulfillment_run")))
```

Add a check that `generate` creates a Run whose snapshot equals the profile value. Initially fail because fields and snapshot are absent.

- [ ] **Step 2: Run the gate and confirm failure**

```text
${BENCH} execute warehouse_app.tests.w54_schema_gate.run_gate
```

Expected: `GATE_JSON` with a failed check or a missing field error.

- [ ] **Step 3: Add the fields and snapshot**

Update the Run JSON in both `field_order` and `fields`. Add the custom-field specs in `upgrade.py` using the existing `_ensure_custom_field` pattern. Use `insert_after` only for new-field placement:

```python
DN_RUN_FIELD_SPEC = {
	"dt": "Delivery Note",
	"fieldname": "custom_fulfillment_run",
	"fieldtype": "Link",
	"label": "Fulfillment Run",
	"options": "Warehouse Fulfillment Run",
	"read_only": 1,
	"insert_after": "customer",
}
PS_RUN_FIELD_SPEC = {
	"dt": "Packing Slip",
	"fieldname": "custom_fulfillment_run",
	"fieldtype": "Link",
	"label": "Fulfillment Run",
	"options": "Warehouse Fulfillment Run",
	"read_only": 1,
	"insert_after": "delivery_note",
}
```

Add `"short_pick_approval_required_snapshot": 1 if profile.short_pick_approval_required else 0` to `_create_run()`.

Add `backfill_run_short_pick_snapshot()` with a single idempotent SQL update joining Run → Profile, only for `status = 'PLANNING'` and snapshot `0`. Do not overwrite `Approved`, `Rejected`, `DISPATCHED`, or reviewed runs.

- [ ] **Step 4: Migrate and run the schema gate**

```text
${BENCH} migrate
${BENCH} execute warehouse_app.tests.w54_schema_gate.run_gate
```

Expected: `GATE_JSON` ok true; no residual test documents.

- [ ] **Step 5: Checkpoint (no commit)**

Proposed message: `feat(fulfillment): add run and native lineage fields`.

---

### Task 3: Permissions and workspace read model

**Files**
- Create: `warehouse_app/warehouse_app/fulfillment/permissions.py`
- Create: `warehouse_app/warehouse_app/fulfillment/workspace.py`
- Modify: `warehouse_app/warehouse_app/fulfillment/api.py`
- Modify: `warehouse_app/warehouse_app/fulfillment/loader.py`
- Test: `warehouse_app/tests/test_fulfillment_permissions.py`
- Test: `warehouse_app/tests/test_fulfillment_workspace.py`
- Test: `warehouse_app/tests/w54_f3_f4_gate.py`

**Interfaces**
- `has_write_roles(roles: set[str]) -> bool`: System Manager, or both Stock Manager and Stock User.
- `has_approver_roles(roles: set[str]) -> bool`: same matrix in MVP.
- `require_read() -> None`, `require_write() -> None`, `require_approver() -> None`.
- `get_run_workspace(run: str) -> dict`.
- `api.get_run_workspace(run)` is a GET endpoint.
- Queue rows gain `"run": {"name", "status", "dry_pick_list", "frozen_pick_list"} | None`; `loader.load_order_queue()` calls `_active_run_summary()`.

Workspace response shape:

```json
{
  "run": {
    "name": "WFR-...", "status": "PLANNING", "sales_order": "SAL-ORD-...",
    "customer": "CUST-...", "company": "...", "delivery_date": "...",
    "short_pick_approval_required": 1, "short_pick_status": "None",
    "short_pick_reason": "", "short_pick_rejection_reason": "",
    "short_pick_fingerprint": "", "short_pick_requested_by": "",
    "short_pick_approved_by": "", "delivery_note": null
  },
  "sales_order": {"name": "...", "customer_name": "...", "delivery_date": "...", "modified": "..."},
  "profile": {"dry_display_name": "Dry", "frozen_display_name": "Frozen",
              "dry_print_format": "...", "frozen_print_format": "..."},
  "groups": {
    "dry": {"pick_list": null, "docstatus": null, "modified": null, "rows": []},
    "frozen": {"pick_list": null, "docstatus": null, "modified": null, "rows": []}
  },
  "short_pick": {"rows": [], "fingerprint": "", "blocker": null},
  "delivery_note": null,
  "packing": {"submitted": [], "fully_packed": false, "dn_qty": 0, "packed_qty": 0},
  "permissions": {"can_write": true, "can_approve": true},
  "next_action": {"key": "finish_picking", "label": "Finish picking", "enabled": true, "reason": null}
}
```

Each group row includes `name` (PL location row), `item_code`, `item_name`, `warehouse`, `qty`, `custom_picked_qty`, `stock_qty`, `conversion_factor`, `uom`, `batch_no`, and `serial_and_batch_bundle`.

`next_action` rules, in order:
- `review_short_pick` when a short-pick blocker exists.
- `finish_picking` when any PL is draft and no blocker exists.
- `create_delivery_note` when no DN and all Run PLs are submitted.
- `pack_all` when DN is draft and not fully packed.
- `submit_delivery_note` when DN is draft and fully packed.
- `done` when DN is submitted.

- [ ] **Step 1: Write failing pure and gate tests**

`test_fulfillment_permissions.py` checks Stock User alone is false, Stock Manager without Stock User is false, System Manager is true, and Stock Manager + Stock User is true.

`test_fulfillment_workspace.py` checks the next-action order for: no PL, draft PL, submitted PL, draft unpacked DN, packed DN, submitted DN.

`w54_f3_f4_gate.py` creates the gate scaffold with `seed_r0()`, `cleanup_r0()`, a `_check()` helper, and a workspace check. It must print one `GATE_JSON` line and always clean up in `finally`.

- [ ] **Step 2: Run the failing tests**

```text
${BENCH} run-tests --app warehouse_app
${BENCH} execute warehouse_app.tests.w54_f3_f4_gate.run_gate
```

Expected: missing permissions/workspace module, and/or an empty workspace JSON.

- [ ] **Step 3: Implement permissions and read-only workspace**

Use `frappe.get_roles()` only after `read` permission on the Run. Do not trust the `run` query parameter for company scope; resolve the Run and check `frappe.has_permission("Warehouse Fulfillment Run", doc=run, ptype="read")`.

Load PL rows from the native documents, not from Run child tables. Treat `custom_picked_qty` as the row-UOM value and `picked_qty` as the native stock-UOM value. Include print formats from the profile but do not generate print URLs server-side.

- [ ] **Step 4: Expose the endpoint and queue run**

Add `get_run_workspace(run)` to `api.py`. Add `run` to queue rows in `loader.py`; keep the existing preview shape unchanged.

- [ ] **Step 5: Run the tests and gate**

```text
${BENCH} run-tests --app warehouse_app
${BENCH} execute warehouse_app.tests.w54_f3_f4_gate.run_gate
```

Expected: all pure tests pass; gate workspace checks pass; cleanup leaves no `ZZTEST-W` Run.

- [ ] **Step 6: Checkpoint (no commit)**

Proposed message: `feat(fulfillment): add run workspace read model`.

---

### Task 4: Save picking quantities

**Files**
- Create: `warehouse_app/warehouse_app/fulfillment/picking.py`
- Modify: `warehouse_app/warehouse_app/fulfillment/api.py`
- Modify: `warehouse_app/tests/w54_f3_f4_gate.py`

**Interfaces**
- `save_picking(run: str, rows: list[dict], expected_modified: dict[str, str], actor: str | None = None) -> dict`
- `rows` entries: `{"pick_list": "PL-...", "row": "PLI-...", "picked_qty": 7.5}` where `picked_qty` is in the PL row UOM.
- `expected_modified` maps PL name → `modified` string.
- `api.save_picking(run, rows, expected_modified)` accepts JSON strings, parses them, and returns the refreshed workspace.

Behavior:
- Only System Manager or Stock Manager + Stock User may save.
- Run must have at least one draft PL and no DN.
- Every row must belong to one of the Run’s PLs; duplicates and unknown rows fail with `WRONG_PL_ROW`.
- `picked_qty` must be `> 0` and `<= row.qty`; over-pick fails with `PICKED_QTY_INVALID`; zero fails with `PICKED_QTY_ZERO_UNSUPPORTED` (native would auto-fill zero to full at submit).
- Compare each PL’s `modified` to `expected_modified`; mismatch fails with `STALE_PL`.
- Set `row.custom_picked_qty` to the row-UOM value, and set native `row.picked_qty = custom_picked_qty * conversion_factor` (rounded to the row precision). The W31 hook is idempotent for converted rows, but stock-UOM rows bypass it; both values must be synchronized so native submit never sees an accidental zero. Save the native PL.
- If the saved short set or fingerprint changes, clear any previous approval: `short_pick_status = None`, `short_pick_fingerprint = ""`, `short_pick_approved_by = ""`, `short_pick_approved_on = None`.
- Set `Run.status = PICKING`; save; return workspace.
- No stock movement.

- [ ] **Step 1: Add failing gate checks**

Add `_check_save_picking(data)` to `w54_f3_f4_gate.py`:
- Save full quantities on the mixed Run.
- Assert no SLE changed.
- Reload both PLs; assert `custom_picked_qty` and native `picked_qty` match UOM conversion.
- Save a partial quantity on the frozen Run; assert workspace `short_pick.rows` contains it.
- Attempt zero picked qty; expect `PICKED_QTY_ZERO_UNSUPPORTED` and no native mutation.
- Attempt a stale PL modified; expect `STALE_PL`.
- Attempt a row from another Run; expect `WRONG_PL_ROW`.

- [ ] **Step 2: Run the gate and confirm failure**

```text
${BENCH} execute warehouse_app.tests.w54_f3_f4_gate.run_gate
```

Expected: `save_picking` import/call failure.

- [ ] **Step 3: Implement `save_picking` and the endpoint**

Use `frappe.get_doc("Pick List", name)` and native `save()`. Do not set `picked_qty` directly. Use `flt()` comparisons with a `0.0001` tolerance.

- [ ] **Step 4: Run the gate**

```text
${BENCH} execute warehouse_app.tests.w54_f3_f4_gate.run_gate
```

Expected: save checks pass; no stock movement; no residual documents on failure.

- [ ] **Step 5: Checkpoint (no commit)**

Proposed message: `feat(fulfillment): save picking quantities`.

---

### Task 5: Short-pick request, approval, and rejection

**Files**
- Create: `warehouse_app/warehouse_app/fulfillment/approval.py`
- Modify: `warehouse_app/warehouse_app/fulfillment/api.py`
- Modify: `warehouse_app/tests/w54_f3_f4_gate.py`

**Interfaces**
- `request_short_pick_approval(run: str, reason: str, actor: str | None = None) -> dict`
- `approve_short_pick(run: str, expected_fingerprint: str, actor: str | None = None) -> dict`
- `reject_short_pick(run: str, reason: str, actor: str | None = None) -> dict`
- API endpoints use the same names and return refreshed workspace.

Behavior:
- `request`: write role; short rows must exist; `short_pick_approval_required` snapshot must be 1; non-empty reason required; status must not be `Approved`; set `short_pick_status = Pending`, store reason, current fingerprint, requester, timestamp; clear rejection reason; save.
- `approve`: approver role; status must be `Pending`; `expected_fingerprint` must equal the stored and current fingerprint; set `Approved`, approver, timestamp; save.
- `reject`: approver role; status must be `Pending`; non-empty reason required; set `Rejected`, store `short_pick_rejection_reason`, clear approver/timestamp; save.
- No stock movement.
- Any subsequent picking save that changes the short set clears the approval and fingerprint.

- [ ] **Step 1: Add failing gate checks**

Add `_check_short_pick_approval(data)`:
- Block Run: policy 0; request must fail with `SHORT_PICK_APPROVAL_NOT_REQUIRED`; Finish must later fail with `SHORT_PICK_BLOCKED`.
- Approval Run: policy 1; request without reason fails; request with reason sets Pending.
- Approve with a wrong fingerprint fails with `SHORT_PICK_STALE_APPROVAL`.
- Approve with the correct fingerprint sets Approved.
- Change a short qty after approval; assert status returns to `None` and old fingerprint is gone.
- Reject with reason sets Rejected and stores the rejection reason; Finish returns `SHORT_PICK_APPROVAL_REJECTED`.
- No SLE changes.

- [ ] **Step 2: Run the gate and confirm failure**

```text
${BENCH} execute warehouse_app.tests.w54_f3_f4_gate.run_gate
```

- [ ] **Step 3: Implement approval services and endpoints**

Use `short_rows()` and `short_fingerprint()` from Task 1. Never trust a client-supplied fingerprint as the current state; compare it to a freshly computed one. Raise `frappe.PermissionError` for unauthorized approvers.

- [ ] **Step 4: Run the gate**

```text
${BENCH} execute warehouse_app.tests.w54_f3_f4_gate.run_gate
```

Expected: all short-pick state transitions pass; no stock.

- [ ] **Step 5: Checkpoint (no commit)**

Proposed message: `feat(fulfillment): add short-pick approval`.

---

### Task 6: Finish picking and native PL submit

**Files**
- Modify: `warehouse_app/warehouse_app/fulfillment/picking.py`
- Modify: `warehouse_app/warehouse_app/fulfillment/api.py`
- Modify: `warehouse_app/tests/w54_f3_f4_gate.py`

**Interfaces**
- `submit_pick_list(run: str, group: str, expected_pl_modified: str, actor: str | None = None) -> dict`
- `complete_picking(run: str, expected_modified: dict[str, str], actor: str | None = None) -> dict`
- API endpoints: `submit_pick_list`, `complete_picking`; both return refreshed workspace.

Behavior:
- `complete_picking` requires write role, a Run with no DN, and at least one PL.
- Reject any draft PL row with `custom_picked_qty <= 0` with `PICKED_QTY_ZERO_UNSUPPORTED`; native would auto-fill a zero to full. Do not silently treat an untouched row as full.
- Compute current short rows and `finish_blocker(short, approval_required, status, fingerprint)`.
- If the blocker is not empty, raise `FulfillmentError` with that code; leave all PLs draft.
- For each draft PL, compare `modified`; submit the native PL with `scan_mode=0`; do not change `picked_qty` or `custom_picked_qty`.
- If a PL is already submitted, skip it and verify it belongs to the Run.
- After all PLs are submitted, set `Run.status = PICKED`; save; return workspace.
- `submit_pick_list` is the per-group primitive used by tests and exceptions. It applies the same short-pick blocker for that group’s rows and submits one PL.
- On native submit failure, rollback the transaction and raise `NATIVE_ERROR` with the original message; leave no Run status advance.

- [ ] **Step 1: Add failing gate checks**

Add `_check_finish_picking(data)`:
- Full Run: Finish picking submits both PLs; no SLE; `Run.status == "PICKED"`.
- Untouched zero row: Finish fails with `PICKED_QTY_ZERO_UNSUPPORTED` even when the Run has no short rows.
- Short Run with policy 1 and Pending: Finish fails with `SHORT_PICK_APPROVAL_PENDING`.
- Short Run with policy 1 and Approved: Finish submits the native short PL; no SLE; picked qty remains short.
- Block Run: Finish fails with `SHORT_PICK_BLOCKED`.
- One-group Run: Finish submits one PL and does not create an empty PL.
- Stale PL modified fails with `STALE_PL`.

- [ ] **Step 2: Run the gate and confirm failure**

```text
${BENCH} execute warehouse_app.tests.w54_f3_f4_gate.run_gate
```

- [ ] **Step 3: Implement finish and submit**

Do not use `scan_mode=1`; that would reject allowed short picks. Do not fake `picked_qty`. Preserve W31 conversion values exactly.

- [ ] **Step 4: Run the gate**

```text
${BENCH} execute warehouse_app.tests.w54_f3_f4_gate.run_gate
```

Expected: full/short/block/one-group checks pass; no stock.

- [ ] **Step 5: Checkpoint (no commit)**

Proposed message: `feat(fulfillment): finish picking with native PL submit`.

---

### Task 7: Create one native Delivery Note Draft

**Files**
- Create: `warehouse_app/warehouse_app/fulfillment/delivery.py`
- Modify: `warehouse_app/warehouse_app/fulfillment/idempotency.py`
- Test: `warehouse_app/tests/test_fulfillment_idempotency.py`
- Modify: `warehouse_app/warehouse_app/fulfillment/api.py`
- Modify: `warehouse_app/tests/w54_f3_f4_gate.py`

**Interfaces**
- `request_hash_payload(payload: dict, request_type: str) -> str`: stable SHA-256 over sorted JSON; request type included.
- `create_delivery_note(run: str, idempotency_key: str, actor: str | None = None) -> dict`
- API endpoint `create_delivery_note` returns refreshed workspace.

Behavior:
- Requires write role and a Run with all PLs submitted.
- If `run.delivery_note` already exists, return the workspace without a new request.
- Recompute the short-pick blocker; pending/rejected/blocked short picks fail with the blocker code.
- Start an idempotent `CreateDeliveryNote` request using the Run’s sales order and payload `{"run": run.name, "pls": [dry, frozen]}`.
- Replay returns the existing DN; mismatch fails `IDEMPOTENCY_MISMATCH`; in-progress fails `REQUEST_IN_PROGRESS`.
- Native call:
  1. `create_dn_for_pick_lists(dry_pl)` if present; otherwise start with frozen.
  2. `create_dn_for_pick_lists(next_pl, target_doc=dn)` for the other PL.
  3. If the returned document has no name, `dn.insert()`; otherwise set `custom_fulfillment_run` and save.
  4. Verify `dn.docstatus == 0` and `against_pick_list` covers every Run PL exactly once.
- Set `run.delivery_note`, `run.dn_created_at`, `run.status = "DN_DRAFT"`; save; complete the request; commit.
- No stock movement. DN prices/taxes/addresses come from the native mapper.
- On failure: rollback, fail the request with the code, and leave `run.delivery_note` empty.

- [ ] **Step 1: Write failing idempotency and gate checks**

`test_fulfillment_idempotency.py`: same payload/request type produces the same hash; different payload produces a different hash; key order does not matter.

`w54_f3_f4_gate.py` `_check_delivery_note`:
- Mixed Run: create one DN; assert both PLs appear in `against_pick_list`; no SLE; `Run.status == "DN_DRAFT"`.
- Call twice with the same key; assert the same DN name and no second DN for the Run.
- Call with a different payload under the same key; expect `IDEMPOTENCY_MISMATCH`.
- One-group Run: create a DN from one PL.
- Pending short Run: expect `SHORT_PICK_APPROVAL_PENDING` and no DN.
- Attempt DN creation with a draft PL: expect `PICKING_NOT_COMPLETE`.

- [ ] **Step 2: Run the tests and gate; confirm failure**

```text
${BENCH} run-tests --app warehouse_app
${BENCH} execute warehouse_app.tests.w54_f3_f4_gate.run_gate
```

- [ ] **Step 3: Implement the generic hash and delivery service**

Use `begin_request`, `complete_request`, and `fail_request` from `idempotency.py`. Do not invent a second idempotency table. Use `frappe.db.commit()` only after the DN and Run are consistent, following the F2 Generate pattern.

- [ ] **Step 4: Run the tests and gate**

```text
${BENCH} run-tests --app warehouse_app
${BENCH} execute warehouse_app.tests.w54_f3_f4_gate.run_gate
```

Expected: one native DN, no stock, idempotent replay, one-group support.

- [ ] **Step 5: Checkpoint (no commit)**

Proposed message: `feat(fulfillment): create one delivery note from run`.

---

### Task 8: Pack all and Reset packing

**Files**
- Create: `warehouse_app/warehouse_app/fulfillment/packing.py`
- Modify: `warehouse_app/warehouse_app/fulfillment/api.py`
- Modify: `warehouse_app/tests/w54_f3_f4_gate.py`

**Interfaces**
- `pack_all(run: str, expected_dn_modified: str, actor: str | None = None) -> dict`
- `reset_packing(run: str, expected_dn_modified: str, actor: str | None = None) -> dict`
- API endpoints `pack_all` and `reset_packing` return refreshed workspace.

Behavior:
- `pack_all` requires write role, a Run with a draft DN, and the short-pick blocker cleared.
- Compare DN `modified` to `expected_dn_modified`; mismatch fails `STALE_DN`.
- If a submitted Packing Slip already belongs to the Run, return the workspace (idempotent).
- If a draft Packing Slip belongs to the Run, set its `custom_fulfillment_run` and submit it.
- Otherwise call native `make_packing_slip(dn)`, set `custom_fulfillment_run = run.name`, insert, and submit. Use the native default case; do not create multiple packages.
- Reload the DN; require all item rows `packed_qty >= qty`. Set `Run.status = "PACKING"` while partially packed and `"READY"` when fully packed.
- No stock movement.
- `reset_packing` requires a draft DN, finds the submitted Packing Slip for this Run, and calls native `ps.cancel()`. Reject if DN is already submitted with `DN_ALREADY_SUBMITTED`. Reload DN; require packed qty is zero (or below DN qty) and set Run status `"PACKING"`.
- If no submitted PS exists, return the workspace without creating one.

- [ ] **Step 1: Add failing gate checks**

Add `_check_packing(data)`:
- Pack all on the mixed Run; assert exactly one submitted Packing Slip, all DN rows packed, no SLE.
- Call Pack all again; assert the same PS and no duplicate.
- Reset packing; assert the PS is cancelled and packed qty is zero.
- Pack all again; assert one new submitted PS and DN still has no SLE.
- Try Reset packing after DN submit; expect `DN_ALREADY_SUBMITTED` and no change.
- Try Pack all with a stale DN modified; expect `STALE_DN`.

- [ ] **Step 2: Run the gate and confirm failure**

```text
${BENCH} execute warehouse_app.tests.w54_f3_f4_gate.run_gate
```

- [ ] **Step 3: Implement Pack all and Reset**

Use `from erpnext.stock.doctype.delivery_note.delivery_note import make_packing_slip`. Set the Run custom field before submit, not after. Never move stock from this service.

- [ ] **Step 4: Run the gate**

```text
${BENCH} execute warehouse_app.tests.w54_f3_f4_gate.run_gate
```

Expected: one PS, reset works, no stock, double clicks safe.

- [ ] **Step 5: Checkpoint (no commit)**

Proposed message: `feat(fulfillment): add one-package packing flow`.

---

### Task 9: Native DN submit and Run finalization

**Files**
- Create: `warehouse_app/warehouse_app/fulfillment/dispatch.py`
- Modify: `warehouse_app/warehouse_app/fulfillment/api.py`
- Modify: `warehouse_app/tests/w54_f3_f4_gate.py`

**Interfaces**
- `submit_delivery_note(run: str, idempotency_key: str, expected_dn_modified: str, actor: str | None = None) -> dict`
- API endpoint `submit_delivery_note` returns refreshed workspace.

Behavior:
- Requires write role, a draft DN, a cleared short-pick blocker, and every DN row `packed_qty >= qty`.
- If Run status is already `DISPATCHED`, return the workspace without another submit.
- Compare DN modified; mismatch fails `STALE_DN`.
- Start an idempotent `SubmitDeliveryNote` request; replay returns the existing submitted DN; mismatch fails.
- Call native `dn.submit()`, reload, verify `docstatus == 1`, set `Run.status = "DISPATCHED"`, `dispatched_at = now_datetime()`, save; complete request; commit.
- Native DN submit is the only place stock moves in this plan.
- On failure: rollback, fail request, leave DN draft and Run not dispatched.

- [ ] **Step 1: Add failing gate checks**

Add `_check_submit_dn(data)`:
- Submit the mixed Run DN; assert `DN.docstatus == 1`, `Run.status == "DISPATCHED"`, stock ledger changed, and later Packing/Reset attempts fail.
- Call submit twice with the same key; assert one DN and one stock movement.
- Try submit with a pending short pick; expect `SHORT_PICK_APPROVAL_PENDING`.
- Try submit with a partially packed DN; expect `DN_NOT_FULLY_PACKED`.
- Try submit with stale DN modified; expect `STALE_DN`.

- [ ] **Step 2: Run the gate and confirm failure**

```text
${BENCH} execute warehouse_app.tests.w54_f3_f4_gate.run_gate
```

- [ ] **Step 3: Implement native submit**

Use `dn.submit()`; do not call `frappe.db.commit()` before the native document is valid. Use the existing `FulfillmentError` codes and wrap unexpected native exceptions as `NATIVE_ERROR`.

- [ ] **Step 4: Run the gate**

```text
${BENCH} execute warehouse_app.tests.w54_f3_f4_gate.run_gate
```

Expected: one DN, one stock movement, idempotent replay, no partial native docs after failures.

- [ ] **Step 5: Checkpoint (no commit)**

Proposed message: `feat(fulfillment): submit delivery note natively`.

---

### Task 10: Frontend API client, route, and queue/drawer navigation

**Files**
- Modify: `frontend/src/data/fulfillment.js`
- Modify: `frontend/src/router.js`
- Create: `frontend/src/pages/FulfillmentWorkspacePage.vue`
- Modify: `frontend/src/pages/FulfillmentPage.vue`
- Modify: `frontend/src/components/FulfillmentDrawer.vue`

**Interfaces**
- `fetchRunWorkspace(run)`
- `savePicking(run, rows, expectedModified)`
- `requestShortPickApproval(run, reason)`
- `approveShortPick(run, expectedFingerprint)`
- `rejectShortPick(run, reason)`
- `completePicking(run, expectedModified)`
- `createDeliveryNote(run, idempotencyKey)`
- `packAll(run, expectedDnModified)`
- `resetPacking(run, expectedDnModified)`
- `submitDeliveryNote(run, idempotencyKey, expectedDnModified)`

All calls use `callGet`/`call` from `@/lib/api`; JSON arrays/objects are sent as `JSON.stringify(...)`.

Queue navigation:
- `FulfillmentPage` uses `useRouter()`.
- `openRow(row)` pushes `{ name: 'fulfillment-run', params: { run: row.run.name } }` when `row.run` exists; otherwise opens the existing drawer.
- `@generated="onGenerated"` closes the drawer and pushes to the returned `result.run`.
- `FulfillmentDrawer` active Run link becomes `/gudang/fulfillment/<run>` (no `/app`). Keep native PL links only as secondary audit links; the happy path uses the workspace.
- Router path `/fulfillment/:run`, name `fulfillment-run`, `meta: { wide: true }`.

Workspace page:
- Fetch on mount and on `run` change.
- Header: SO, customer, Run status, Dry/Frozen labels.
- Action hub: prominent next action; free tabs (Picking, Delivery, Packing, Review).
- Loading/error/retry states.
- No new data fetching on tab switch; reuse the fetched workspace.

- [ ] **Step 1: Add the failing build check**

```text
cd frontend
npm run build
```

Expected before implementation: route/page/data functions absent or build unchanged.

- [ ] **Step 2: Implement data client, route, and page shell**

Use the existing `call`/`callGet` patterns. Do not add a store or dependency. Keep the page shell narrow; panels are added in Tasks 11–12.

- [ ] **Step 3: Build and browser-check navigation**

```text
cd frontend
npm run build
```

Open `http://fulfillment.localhost:8080/gudang/fulfillment`, click an SO with an active Run, and confirm the URL becomes `/gudang/fulfillment/<run>` and the page loads without console errors. Confirm an SO without a Run still opens the existing drawer.

- [ ] **Step 4: Checkpoint (no commit)**

Proposed message: `feat(fulfillment): add in-app run workspace route`.

---

### Task 11: Picking UI, print, short-pick approval, and Finish picking

**Files**
- Create: `frontend/src/components/fulfillment/PickingPanel.vue`
- Modify: `frontend/src/pages/FulfillmentWorkspacePage.vue`

**Interfaces**
- Props: `workspace`, `busy`.
- Emits: `refresh`, `save-picking`, `finish-picking`, `request-approval`, `approve-short-pick`, `reject-short-pick`, `print`.
- The panel renders Dry and Frozen groups only when their PL exists.
- Each row shows item, warehouse, target qty, picked qty, UOM, batch/serial hint.
- Picked qty input rejects zero client-side and displays “Enter a positive quantity. Zero is not supported.” The server still enforces `PICKED_QTY_ZERO_UNSUPPORTED`.
- Print button opens `/printview?doctype=Pick List&name=<PL>&format=<profile format>` in a new tab. If `print_format` is blank, show `Print format is not configured.`
- Save sends all editable rows with the PL modified timestamps.
- Short-pick banner appears when `short_pick.rows.length > 0`:
  - Block: “Short pick is blocked by policy. Correct the quantity.”
  - Approval / status None: reason input + “Request approval”.
  - Pending: “Waiting for approval”; approvers see Approve/Reject.
  - Rejected: show rejection reason and allow Request again.
  - Approved: show approver and fingerprint-valid state.
- Finish picking is disabled while a request is busy or a blocker exists; it calls `completePicking(run, expectedModified)`.

- [ ] **Step 1: Build the panel and wire page events**

Use `fmtQty` and existing form/button CSS. Do not add a date picker, scanner, or barcode UI. Print is a new tab, not an ERPNext Desk navigation.

- [ ] **Step 2: Browser-check the picking flow**

On the disposable test site:
- Generate/open a mixed Run.
- Print Dry and Frozen; both print previews use the configured formats.
- Enter a short qty; save; confirm the short banner.
- Request/approve; confirm the status; Finish picking; confirm the PLs are submitted in native read-back.
- Confirm no stock ledger entry is created.
- Confirm no console errors.

- [ ] **Step 3: Checkpoint (no commit)**

Proposed message: `feat(fulfillment): add picking workspace UI`.

---

### Task 12: Delivery, packing, and review UI

**Files**
- Create: `frontend/src/components/fulfillment/DeliveryPanel.vue`
- Create: `frontend/src/components/fulfillment/PackingPanel.vue`
- Create: `frontend/src/components/fulfillment/ReviewPanel.vue`
- Modify: `frontend/src/pages/FulfillmentWorkspacePage.vue`

**Interfaces**
- `DeliveryPanel` shows DN state, customer, SO link text, and “Create DN” / native DN reference.
- `PackingPanel` shows DN qty, packed qty, Packing Slip state, and buttons `Pack all`, `Reset packing`.
- `ReviewPanel` shows the final checklist: PLs submitted, short pick approved/clear, DN draft, all qty packed, native submit warning. Button `Submit DN`.
- All write actions use the Task 10 client functions and refresh workspace after success.
- “Open native DN” is a secondary link only; no Desk link in the primary action path.

- [ ] **Step 1: Implement the panels and action hub**

Keep the next-action button prominent. Disable actions when `next_action.enabled` is false; show `next_action.reason` inline. `Reset packing` requires a confirmation dialog because it cancels the native PS.

- [ ] **Step 2: Browser-check the full chain**

On the disposable test site:
- Finish picking.
- Create DN; confirm one DN and both PL references.
- Pack all; confirm one Packing Slip and packed qty.
- Reset packing; confirm cancelled PS and zero packed qty; Pack all again.
- Submit DN; confirm stock movement and Run DISPATCHED.
- Confirm the happy path never opens `/app`.

- [ ] **Step 3: Checkpoint (no commit)**

Proposed message: `feat(fulfillment): add delivery and packing UI`.

---

### Task 13: Short-pick policy in Settings

**Files**
- Modify: `frontend/src/pages/SettingsPage.vue`

**Interfaces**
- Add a checkbox bound to `ffProfile.short_pick_approval_required`.
- Label: “Require approval for short picks”.
- Help text: “Off blocks short picks. On requires an approver before Finish picking.”
- Existing save payload already includes the field via `ffProfile`; do not change the Settings API.

- [ ] **Step 1: Add the control and save check**

Use the existing fulfillment panel/checkbox classes. Keep the control disabled when `ffLocked` or `!ffCanEdit`.

- [ ] **Step 2: Build and browser-check**

```text
cd frontend
npm run build
```

Open Settings, toggle the checkbox, save, reload, and confirm the value persists. Generate a new Run and confirm its snapshot matches the new value.

- [ ] **Step 3: Checkpoint (no commit)**

Proposed message: `feat(fulfillment): expose short-pick policy`.

---

### Task 14: Full acceptance gate, browser regression, and cleanup

**Files**
- Modify: `warehouse_app/tests/w54_f3_f4_gate.py` as needed
- No production files

**Gate coverage**
- Workspace read/next action.
- Save full/partial; W31 UOM; stock-UOM rows; zero rejected; no stock.
- Block vs approval; stale fingerprint; rejection.
- Finish one group and both groups; native short submit.
- One DN from one/two PLs; native header mapping; idempotent.
- Pack all; reset; re-pack; one PS; no stock before DN submit.
- DN submit; stock movement; double-click idempotency.
- Cleanup: no `ZZTEST-W` Run, PL, DN, PS, SLE, Request Key, or test user residue.

- [ ] **Step 1: Run the full backend suite and gates**

```text
${BENCH} migrate
${BENCH} clear-cache
${BENCH} execute warehouse_app.tests.w54_schema_gate.run_gate
${BENCH} execute warehouse_app.tests.w54_f3_f4_gate.run_gate
${BENCH} run-tests --app warehouse_app
${BENCH} execute warehouse_app.tests.w49_r0_gate.run_gate
${BENCH} execute warehouse_app.tests.w49_f2_gate.run_gate
${BENCH} execute warehouse_app.tests.w49_f1_readonly_gate.run_gate
```

Expected: all `GATE_JSON` lines ok; unit suite pass; no residual fixture.

- [ ] **Step 2: Build and sync the SPA assets**

```text
cd frontend
npm run build
docker exec frappe16-frontend-1 mkdir -p /home/frappe/frappe-bench/sites/assets/warehouse_app/gudang
docker cp warehouse_app/public/gudang/. frappe16-frontend-1:/home/frappe/frappe-bench/sites/assets/warehouse_app/gudang/
${BENCH} clear-cache
```

Restart `frappe16-backend-1` only if Python modules remain stale in the browser session.

- [ ] **Step 3: Browser acceptance on the disposable site**

Record evidence for:
- Queue → workspace route; no `/app`.
- Print Dry/Frozen previews.
- Save partial; Block mode and Approval mode.
- Finish picking; no SLE.
- Create one DN; Pack all; Reset; Pack all; Submit DN.
- Stock exists only after DN submit; Run DISPATCHED.
- No console errors; mobile 390/360 no horizontal overflow.
- No fixture residue after cleanup.

- [ ] **Step 4: Regression check**

Confirm F1 queue, F2 Generate, and W31 UOM behavior are unchanged. Re-run the existing gates listed in Step 1. Do not touch `erp.localhost` or `1oktober2026`.

- [ ] **Step 5: Final checkpoint (no commit)**

Proposed message: `feat(fulfillment): complete in-app picking to delivery flow`.

Stop, show the diff summary, test evidence, and proposed commit message. Wait for explicit user approval before committing. Do not push.

---

## Self-Review

- [ ] Spec coverage: the plan covers Dry/Frozen picking, short-pick Block/Approval, one DN from submitted PLs, one-package Pack all/reset, native DN submit, existing print reuse, workspace route, and no Desk happy path.
- [ ] Placeholder scan: no `TBD`, `TODO`, “similar to”, or unresolved function names. All new functions and fields are named.
- [ ] Type consistency: `picked_qty` input is row UOM; `custom_picked_qty` is the persisted row-UOM value; native `picked_qty` remains stock UOM and is synchronized on every save. `expected_modified` is a map keyed by native document name. Zero is rejected before native auto-fill.
- [ ] Failure consistency: every write service raises `FulfillmentError` with a stable code; API converts to `frappe.ValidationError`; native permissions remain native.
- [ ] Scope consistency: multi-package, checker/dispatch, configurable roles, Print All, barcode, and audit remain deferred per spec §16.
- [ ] Test ordering: every task has a failing test/gate before implementation; Task 14 re-runs the entire regression set.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-10-28-fulfillment-f3-f4-in-app-workspace-mvp.md`.

Two execution options:

1. **Subagent-Driven (recommended):** dispatch one fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution:** execute tasks in this session using `executing-plans`, with checkpoints for review.

No coding starts until the user chooses an execution method and approves the plan. No commit or push without explicit approval.
