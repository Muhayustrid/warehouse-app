# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""F3/F4 read-only workspace gate. Runs only on fulfillment.localhost."""

from __future__ import annotations

import json

import frappe
from frappe.utils import flt

from warehouse_app.tests.w49_f1_fixture import COMPANY, WAREHOUSE, guard_site
from warehouse_app.tests.w49_f2_fixture import (
	R0_BOX,
	R0_DRY,
	R0_FROZEN,
	SO_MARKERS,
	cleanup_r0,
	seed_r0,
)
from warehouse_app.warehouse_app.fulfillment.generate import generate_fulfillment_run
from warehouse_app.warehouse_app.fulfillment.loader import load_order_queue

RUN = "Warehouse Fulfillment Run"
KEY = "Warehouse Fulfillment Request Key"
REQUEST_PREFIX = "ZZTEST-W54-F3-F4"
ROW_FIELDS = {
	"name",
	"item_code",
	"item_name",
	"warehouse",
	"qty",
	"custom_picked_qty",
	"stock_qty",
	"conversion_factor",
	"uom",
	"batch_no",
	"serial_and_batch_bundle",
}


def run_gate() -> None:
	guard_site()
	checks: dict[str, str] = {}
	ok = True

	try:
		_cleanup_generated()
		data = seed_r0()
		_cleanup_generated()
		sales_order = data["sales_orders"]["mixed"]
		so = frappe.get_doc("Sales Order", sales_order)
		before_stock = _stock()
		result = generate_fulfillment_run(
			sales_order=sales_order,
			idempotency_key=f"{REQUEST_PREFIX}-GENERATE",
			expected_so_modified=str(so.modified),
			actor="Administrator",
		)

		from warehouse_app.warehouse_app.fulfillment.api import get_run_workspace

		workspace = get_run_workspace(result["run"])
		ok = _check(checks, "run", workspace["run"]["name"] == result["run"], workspace.get("run")) and ok
		ok = _check(
			checks,
			"permissions",
			workspace["permissions"] == {"can_write": True, "can_approve": True},
			workspace.get("permissions"),
		) and ok
		ok = _check(
			checks,
			"next_action",
			workspace["next_action"]["key"] == "finish_picking"
			and workspace["next_action"]["enabled"] is True,
			workspace.get("next_action"),
		) and ok
		ok = _check(
			checks,
			"profile_print_formats",
			set(workspace["profile"])
			== {"dry_display_name", "frozen_display_name", "dry_print_format", "frozen_print_format"},
			workspace.get("profile"),
		) and ok

		for group, result_key in (("dry", "dry_pick_list"), ("frozen", "frozen_pick_list")):
			actual = workspace["groups"][group]
			expected_name = result[result_key]["name"]
			native_rows = frappe.get_doc("Pick List", expected_name).locations
			ok = _check(
				checks,
				f"{group}_group",
				actual["pick_list"] == expected_name
				and actual["docstatus"] == 0
				and bool(actual["modified"])
				and {row["name"] for row in actual["rows"]} == {row.name for row in native_rows}
				and all(ROW_FIELDS <= set(row) for row in actual["rows"]),
				actual,
			) and ok

		ok = _check(
			checks,
			"short_pick",
			workspace["short_pick"]["rows"] == []
			and len(workspace["short_pick"]["fingerprint"]) == 64
			and workspace["short_pick"]["blocker"] is None,
			workspace.get("short_pick"),
		) and ok
		ok = _check(
			checks,
			"delivery_and_packing_empty",
			workspace["delivery_note"] is None
			and workspace["packing"]
			== {"submitted": [], "fully_packed": False, "dn_qty": 0, "packed_qty": 0},
			{"delivery_note": workspace.get("delivery_note"), "packing": workspace.get("packing")},
		) and ok

		queue = load_order_queue(company=COMPANY, stage="picking", page_length=100)
		queue_row = next((row for row in queue["rows"] if row["sales_order"] == sales_order), None)
		ok = _check(
			checks,
			"queue_active_run",
			bool(queue_row)
			and queue_row["run"]
			== {
				"name": result["run"],
				"status": "PLANNING",
				"dry_pick_list": result["dry_pick_list"]["name"],
				"frozen_pick_list": result["frozen_pick_list"]["name"],
			},
			queue_row and queue_row.get("run"),
		) and ok
		ok = _check(checks, "no_stock_movement", _stock() == before_stock, _stock()) and ok
		ok = _check_save_picking(data, checks) and ok
		ok = _check_short_pick_approval(data, checks) and ok
		ok = _check_finish_picking(data, checks) and ok
		ok = _check_delivery_note(data, checks) and ok
		ok = _check_packing(data, checks) and ok
		ok = _check_submit_dn(data, checks) and ok
	except Exception as exc:
		ok = False
		checks["exception"] = f"{type(exc).__name__}: {exc}"
		checks["traceback"] = frappe.get_traceback()
	finally:
		frappe.set_user("Administrator")
		try:
			_cleanup_generated()
			cleanup = cleanup_r0()
			checks["cleanup"] = str(cleanup)
			residual_runs = frappe.get_all(RUN, filters={"request_key": ("like", f"{REQUEST_PREFIX}%")}, pluck="name")
			residual_keys = frappe.get_all(KEY, filters={"idempotency_key": ("like", f"{REQUEST_PREFIX}%")}, pluck="name")
			ok = _check(checks, "teardown_runs", not residual_runs, residual_runs) and ok
			ok = _check(checks, "teardown_keys", not residual_keys, residual_keys) and ok
		except Exception as exc:
			ok = False
			checks["cleanup_exception"] = f"{type(exc).__name__}: {exc}"
			checks["cleanup_traceback"] = frappe.get_traceback()

	print("GATE_JSON:" + json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, default=str))


def _check(checks: dict[str, str], name: str, passed: bool, evidence: object) -> bool:
	checks[name] = str(evidence) if passed else f"FAIL: {evidence}"
	return passed


def _stock() -> dict[str, float]:
	return {
		code: flt(frappe.db.get_value("Bin", {"item_code": code, "warehouse": WAREHOUSE}, "actual_qty"))
		for code in (R0_DRY, R0_FROZEN, R0_BOX)
	}


def _cleanup_generated() -> None:
	so_names = frappe.get_all(
		"Sales Order", filters={"po_no": ("in", list(SO_MARKERS.values()))}, pluck="name"
	)
	run_names = set(frappe.get_all(RUN, filters={"request_key": ("like", f"{REQUEST_PREFIX}%")}, pluck="name"))
	key_names = set(frappe.get_all(KEY, filters={"idempotency_key": ("like", f"{REQUEST_PREFIX}%")}, pluck="name"))
	if so_names:
		run_names.update(frappe.get_all(RUN, filters={"sales_order": ("in", so_names)}, pluck="name"))
		key_names.update(frappe.get_all(KEY, filters={"sales_order": ("in", so_names)}, pluck="name"))

	# Delivery Notes and Packing Slips
	dn_names = set()
	if run_names:
		dn_names.update(frappe.get_all("Delivery Note", filters={"custom_fulfillment_run": ("in", list(run_names))}, pluck="name"))
		for r_name in run_names:
			dn_ref = frappe.db.get_value(RUN, r_name, "delivery_note")
			if dn_ref:
				dn_names.add(dn_ref)
	if so_names:
		dn_names.update(frappe.get_all("Delivery Note Item", filters={"against_sales_order": ("in", so_names)}, pluck="parent", distinct=True))

	ps_names = set()
	for dn_name in dn_names:
		ps_names.update(frappe.get_all("Packing Slip", filters={"delivery_note": dn_name}, pluck="name"))
	if run_names:
		ps_names.update(frappe.get_all("Packing Slip", filters={"custom_fulfillment_run": ("in", list(run_names))}, pluck="name"))

	for ps_name in ps_names:
		if frappe.db.exists("Packing Slip", ps_name):
			ps = frappe.get_doc("Packing Slip", ps_name)
			if ps.docstatus == 1:
				ps.cancel()
			frappe.delete_doc("Packing Slip", ps_name, force=1, ignore_permissions=True, ignore_missing=True)

	for dn_name in dn_names:

		if frappe.db.exists("Delivery Note", dn_name):
			dn = frappe.get_doc("Delivery Note", dn_name)
			if dn.docstatus == 1:
				dn.cancel()
			frappe.delete_doc("Delivery Note", dn_name, force=1, ignore_permissions=True, ignore_missing=True)

	pl_names = set()
	if run_names:
		pl_names.update(frappe.get_all("Pick List", filters={"custom_fulfillment_run": ("in", list(run_names))}, pluck="name"))
	if so_names:
		pl_names.update(frappe.get_all("Pick List Item", filters={"sales_order": ("in", so_names)}, pluck="parent", distinct=True))
	for name in pl_names:
		if frappe.db.exists("Pick List", name):
			pl = frappe.get_doc("Pick List", name)
			if pl.docstatus == 1:
				pl.cancel()
			frappe.delete_doc("Pick List", name, force=1, ignore_permissions=True, ignore_missing=True)
	for name in run_names:
		frappe.delete_doc(RUN, name, force=1, ignore_permissions=True, ignore_missing=True)
	for name in key_names:
		frappe.delete_doc(KEY, name, force=1, ignore_permissions=True, ignore_missing=True)
	frappe.db.commit()


def _check_save_picking(data: dict, checks: dict[str, str] | None = None) -> bool:
	if checks is None:
		checks = {}
	ok = True
	from warehouse_app.warehouse_app.fulfillment.api import get_run_workspace, save_picking

	mixed_so = frappe.get_doc("Sales Order", data["sales_orders"]["mixed"])
	mixed_run = frappe.db.get_value(RUN, {"sales_order": mixed_so.name}, "name")
	ws = get_run_workspace(mixed_run)

	before_stock = _stock()
	before_sle_count = frappe.db.count("Stock Ledger Entry")

	# 1. Save full quantities on the mixed Run (testing JSON string inputs as well)
	save_rows = []
	expected_modified = {}
	for group in ("dry", "frozen"):
		g = ws["groups"][group]
		if g["pick_list"]:
			expected_modified[g["pick_list"]] = g["modified"]
			for r in g["rows"]:
				save_rows.append({
					"pick_list": g["pick_list"],
					"row": r["name"],
					"picked_qty": r["qty"],
				})

	ws_after = save_picking(
		run=mixed_run,
		rows=json.dumps(save_rows),
		expected_modified=json.dumps(expected_modified),
	)
	ok = _check(
		checks,
		"save_full_status",
		ws_after["run"]["status"] == "PICKING",
		ws_after["run"]["status"],
	) and ok
	ok = _check(
		checks,
		"save_full_short_rows_empty",
		ws_after["short_pick"]["rows"] == [],
		ws_after["short_pick"]["rows"],
	) and ok

	# 2. Assert no SLE changed
	after_sle_count = frappe.db.count("Stock Ledger Entry")
	ok = _check(
		checks,
		"save_picking_no_sle",
		_stock() == before_stock and after_sle_count == before_sle_count,
		{"stock": _stock(), "sle_count": after_sle_count},
	) and ok

	# 3. Reload both PLs; assert custom_picked_qty and native picked_qty match UOM conversion
	uom_ok = True
	box_checked = False
	for group in ("dry", "frozen"):
		pl_name = ws["groups"][group]["pick_list"]
		if not pl_name:
			continue
		pl_doc = frappe.get_doc("Pick List", pl_name)
		for loc in pl_doc.locations:
			factor = flt(loc.conversion_factor) or 1.0
			expected_native = flt(loc.qty * factor, loc.precision("picked_qty"))
			if flt(loc.custom_picked_qty) != flt(loc.qty) or flt(loc.picked_qty) != expected_native:
				uom_ok = False
			if loc.item_code == R0_BOX:
				box_checked = (flt(loc.custom_picked_qty) == 2.0 and flt(loc.picked_qty) == 24.0)
	ok = _check(
		checks,
		"save_full_uom_conversion",
		uom_ok and box_checked,
		{"uom_ok": uom_ok, "box_checked": box_checked},
	) and ok

	# 4. Save a partial quantity on the frozen Run; assert workspace short_pick.rows contains it
	frozen_so = frappe.get_doc("Sales Order", data["sales_orders"]["frozen"])
	frozen_res = generate_fulfillment_run(
		sales_order=frozen_so.name,
		idempotency_key=f"{REQUEST_PREFIX}-FROZEN-GEN",
		expected_so_modified=str(frozen_so.modified),
		actor="Administrator",
	)
	frozen_run = frozen_res["run"]
	f_ws = get_run_workspace(frozen_run)
	frozen_pl = f_ws["groups"]["frozen"]["pick_list"]
	frozen_row = f_ws["groups"]["frozen"]["rows"][0]
	f_expected_modified = {frozen_pl: f_ws["groups"]["frozen"]["modified"]}

	partial_rows = [{
		"pick_list": frozen_pl,
		"row": frozen_row["name"],
		"picked_qty": 3.0,
	}]
	f_ws_after = save_picking(run=frozen_run, rows=partial_rows, expected_modified=f_expected_modified)
	ok = _check(
		checks,
		"save_partial_status",
		f_ws_after["run"]["status"] == "PICKING",
		f_ws_after["run"]["status"],
	) and ok
	ok = _check(
		checks,
		"save_partial_short_rows",
		len(f_ws_after["short_pick"]["rows"]) == 1
		and f_ws_after["short_pick"]["rows"][0]["custom_picked_qty"] == 3.0
		and f_ws_after["short_pick"]["rows"][0]["qty"] == 5.0
		and f_ws_after["short_pick"]["rows"][0]["row"] == frozen_row["name"],
		f_ws_after["short_pick"]["rows"],
	) and ok

	# 5. Attempt zero picked qty; expect PICKED_QTY_ZERO_UNSUPPORTED and no native mutation
	zero_failed = False
	pl_fresh = frappe.get_doc("Pick List", frozen_pl)
	try:
		save_picking(
			run=frozen_run,
			rows=[{"pick_list": frozen_pl, "row": frozen_row["name"], "picked_qty": 0.0}],
			expected_modified={frozen_pl: str(pl_fresh.modified)},
		)
	except Exception as exc:
		if "PICKED_QTY_ZERO_UNSUPPORTED" in str(exc):
			zero_failed = True
	pl_reloaded = frappe.get_doc("Pick List", frozen_pl)
	no_mutation = (
		flt(pl_reloaded.locations[0].custom_picked_qty) == 3.0
		and flt(pl_reloaded.locations[0].picked_qty) == 3.0
	)
	ok = _check(
		checks,
		"zero_rejected_no_mutation",
		zero_failed and no_mutation,
		{"zero_failed": zero_failed, "no_mutation": no_mutation},
	) and ok

	# 6. Attempt a stale PL modified; expect STALE_PL
	stale_failed = False
	try:
		save_picking(
			run=frozen_run,
			rows=partial_rows,
			expected_modified={frozen_pl: "2020-01-01 00:00:00.000000"},
		)
	except Exception as exc:
		if "STALE_PL" in str(exc):
			stale_failed = True
	ok = _check(checks, "stale_pl_rejected", stale_failed, stale_failed) and ok

	# 7. Attempt a row from another Run; expect WRONG_PL_ROW
	wrong_row_failed = False
	dry_pl_name = ws["groups"]["dry"]["pick_list"]
	dry_row = ws["groups"]["dry"]["rows"][0]
	try:
		save_picking(
			run=frozen_run,
			rows=[{"pick_list": dry_pl_name, "row": dry_row["name"], "picked_qty": 1.0}],
			expected_modified={frozen_pl: str(pl_reloaded.modified)},
		)
	except Exception as exc:
		if "WRONG_PL_ROW" in str(exc):
			wrong_row_failed = True
	ok = _check(checks, "wrong_row_rejected", wrong_row_failed, wrong_row_failed) and ok

	# 8. Attempt over-pick (picked_qty > qty); expect PICKED_QTY_INVALID
	overpick_failed = False
	try:
		save_picking(
			run=frozen_run,
			rows=[{"pick_list": frozen_pl, "row": frozen_row["name"], "picked_qty": 99.0}],
			expected_modified={frozen_pl: str(pl_reloaded.modified)},
		)
	except Exception as exc:
		if "PICKED_QTY_INVALID" in str(exc):
			overpick_failed = True
	ok = _check(checks, "overpick_rejected", overpick_failed, overpick_failed) and ok

	# 9. Attempt duplicate row; expect WRONG_PL_ROW
	dup_row_failed = False
	try:
		save_picking(
			run=frozen_run,
			rows=[
				{"pick_list": frozen_pl, "row": frozen_row["name"], "picked_qty": 2.0},
				{"pick_list": frozen_pl, "row": frozen_row["name"], "picked_qty": 3.0},
			],
			expected_modified={frozen_pl: str(pl_reloaded.modified)},
		)
	except Exception as exc:
		if "WRONG_PL_ROW" in str(exc):
			dup_row_failed = True
	ok = _check(checks, "dup_row_rejected", dup_row_failed, dup_row_failed) and ok

	# 10. Invalidate previous approval when short fingerprint changes
	f_run_doc = frappe.get_doc(RUN, frozen_run)
	f_run_doc.short_pick_status = "Approved"
	f_run_doc.short_pick_fingerprint = "dummy_fingerprint"
	f_run_doc.short_pick_approved_by = "Administrator"
	f_run_doc.short_pick_approved_on = frappe.utils.now_datetime()
	f_run_doc.save()

	f_pl_fresh = frappe.get_doc("Pick List", frozen_pl)
	f_ws_repicked = save_picking(
		run=frozen_run,
		rows=[{"pick_list": frozen_pl, "row": frozen_row["name"], "picked_qty": 4.0}],
		expected_modified={frozen_pl: str(f_pl_fresh.modified)},
	)
	approval_cleared = (
		f_ws_repicked["run"]["short_pick_status"] == "None"
		and f_ws_repicked["run"]["short_pick_fingerprint"] == ""
		and f_ws_repicked["run"]["short_pick_approved_by"] == ""
	)
	ok = _check(
		checks,
		"approval_cleared_on_qty_change",
		approval_cleared,
		f_ws_repicked["run"],
	) and ok

	return ok


def _check_short_pick_approval(data: dict, checks: dict[str, str] | None = None) -> bool:
	if checks is None:
		checks = {}
	ok = True
	from warehouse_app.warehouse_app.fulfillment.api import (
		approve_short_pick,
		get_run_workspace,
		reject_short_pick,
		request_short_pick_approval,
		save_picking,
	)

	before_stock = _stock()
	before_sle_count = frappe.db.count("Stock Ledger Entry")

	# 1. Block Run (snapshot 0): request fails SHORT_PICK_APPROVAL_NOT_REQUIRED
	dry_so = frappe.get_doc("Sales Order", data["sales_orders"]["dry"])
	dry_res = generate_fulfillment_run(
		sales_order=dry_so.name,
		idempotency_key=f"{REQUEST_PREFIX}-BLOCK-GEN",
		expected_so_modified=str(dry_so.modified),
		actor="Administrator",
	)
	block_run = dry_res["run"]
	b_ws = get_run_workspace(block_run)
	b_pl = b_ws["groups"]["dry"]["pick_list"]
	b_row = b_ws["groups"]["dry"]["rows"][0]
	save_picking(
		run=block_run,
		rows=[{"pick_list": b_pl, "row": b_row["name"], "picked_qty": 2.0}],
		expected_modified={b_pl: b_ws["groups"]["dry"]["modified"]},
	)
	b_run_doc = frappe.get_doc(RUN, block_run)
	b_run_doc.short_pick_approval_required_snapshot = 0
	b_run_doc.save()

	block_request_failed = False
	try:
		request_short_pick_approval(run=block_run, reason="Need approval for dry goods")
	except Exception as exc:
		if "SHORT_PICK_APPROVAL_NOT_REQUIRED" in str(exc):
			block_request_failed = True
	ok = _check(checks, "block_request_fails_not_required", block_request_failed, block_request_failed) and ok

	# 2. Approval Run (snapshot 1): frozen run from previous check has 1 short row and snapshot 1
	frozen_so_name = data["sales_orders"]["frozen"]
	app_run = frappe.db.get_value(RUN, {"sales_order": frozen_so_name}, "name")
	app_ws = get_run_workspace(app_run)
	frozen_pl = app_ws["groups"]["frozen"]["pick_list"]
	frozen_row = app_ws["groups"]["frozen"]["rows"][0]

	no_reason_failed = False
	try:
		request_short_pick_approval(run=app_run, reason="")
	except Exception as exc:
		if "SHORT_PICK_REASON_REQUIRED" in str(exc):
			no_reason_failed = True
	whitespace_failed = False
	try:
		request_short_pick_approval(run=app_run, reason="   ")
	except Exception as exc:
		if "SHORT_PICK_REASON_REQUIRED" in str(exc):
			whitespace_failed = True
	ok = _check(
		checks,
		"request_no_reason_fails",
		no_reason_failed and whitespace_failed,
		{"no_reason": no_reason_failed, "whitespace": whitespace_failed},
	) and ok

	# 3. Request with reason sets Pending status and current fingerprint
	ws_pending = request_short_pick_approval(
		run=app_run,
		reason="Physical count short in freezer",
	)
	expected_fp = ws_pending["short_pick"]["fingerprint"]
	request_ok = (
		ws_pending["run"]["short_pick_status"] == "Pending"
		and ws_pending["run"]["short_pick_reason"] == "Physical count short in freezer"
		and ws_pending["run"]["short_pick_fingerprint"] == expected_fp
		and ws_pending["run"]["short_pick_requested_by"] == "Administrator"
		and ws_pending["short_pick"]["blocker"] == "SHORT_PICK_APPROVAL_PENDING"
		and ws_pending["next_action"]["reason"] == "SHORT_PICK_APPROVAL_PENDING"
	)
	ok = _check(checks, "request_sets_pending_and_fingerprint", request_ok, ws_pending["run"]) and ok

	# 4. Approve with mismatched/stale fingerprint fails SHORT_PICK_STALE_APPROVAL
	stale_approve_failed = False
	try:
		approve_short_pick(run=app_run, expected_fingerprint="bad_fingerprint_hash_0000000000000000")
	except Exception as exc:
		if "SHORT_PICK_STALE_APPROVAL" in str(exc):
			stale_approve_failed = True
	ok = _check(checks, "approve_stale_fingerprint_fails", stale_approve_failed, stale_approve_failed) and ok

	# 5. Approve with correct fingerprint sets Approved status and approver info
	ws_approved = approve_short_pick(run=app_run, expected_fingerprint=expected_fp)
	approve_ok = (
		ws_approved["run"]["short_pick_status"] == "Approved"
		and ws_approved["run"]["short_pick_approved_by"] == "Administrator"
		and ws_approved["run"]["short_pick_fingerprint"] == expected_fp
		and ws_approved["short_pick"]["blocker"] is None
		and ws_approved["next_action"]["key"] == "finish_picking"
		and ws_approved["next_action"]["reason"] is None
	)
	ok = _check(checks, "approve_sets_approved_and_actor", approve_ok, ws_approved["run"]) and ok

	# 6. Changing short qty after approval clears approval status (via save_picking)
	f_pl_doc = frappe.get_doc("Pick List", frozen_pl)
	ws_repicked = save_picking(
		run=app_run,
		rows=[{"pick_list": frozen_pl, "row": frozen_row["name"], "picked_qty": 2.0}],
		expected_modified={frozen_pl: str(f_pl_doc.modified)},
	)
	qty_change_cleared = (
		ws_repicked["run"]["short_pick_status"] in (None, "None", "")
		and ws_repicked["run"]["short_pick_fingerprint"] == ""
		and ws_repicked["run"]["short_pick_approved_by"] == ""
	)
	ok = _check(checks, "approval_cleared_on_qty_change_in_approval_check", qty_change_cleared, ws_repicked["run"]) and ok

	# 7. Reject with reason sets Rejected status and stores rejection reason
	ws_re_pending = request_short_pick_approval(
		run=app_run,
		reason="Short 3 units now",
	)
	reject_no_reason_failed = False
	try:
		reject_short_pick(run=app_run, reason="")
	except Exception as exc:
		if "SHORT_PICK_REASON_REQUIRED" in str(exc):
			reject_no_reason_failed = True

	ws_rejected = reject_short_pick(
		run=app_run,
		reason="Recheck physically with storekeeper",
	)
	reject_ok = (
		reject_no_reason_failed
		and ws_rejected["run"]["short_pick_status"] == "Rejected"
		and ws_rejected["run"]["short_pick_rejection_reason"] == "Recheck physically with storekeeper"
		and ws_rejected["run"]["short_pick_approved_by"] == ""
		and ws_rejected["short_pick"]["blocker"] == "SHORT_PICK_APPROVAL_REJECTED"
		and ws_rejected["next_action"]["reason"] == "SHORT_PICK_APPROVAL_REJECTED"
	)
	ok = _check(checks, "reject_sets_rejected_and_reason", reject_ok, ws_rejected["run"]) and ok

	# Extra: Cannot approve or reject when not Pending
	not_pending_approve_failed = False
	try:
		approve_short_pick(run=app_run, expected_fingerprint=ws_rejected["short_pick"]["fingerprint"])
	except Exception as exc:
		if "SHORT_PICK_NOT_PENDING" in str(exc):
			not_pending_approve_failed = True

	not_pending_reject_failed = False
	try:
		reject_short_pick(run=app_run, reason="Another reject")
	except Exception as exc:
		if "SHORT_PICK_NOT_PENDING" in str(exc):
			not_pending_reject_failed = True

	ok = _check(
		checks,
		"actions_fail_when_not_pending",
		not_pending_approve_failed and not_pending_reject_failed,
		{"approve_not_pending": not_pending_approve_failed, "reject_not_pending": not_pending_reject_failed},
	) and ok

	# 8. No SLE changes throughout
	after_stock = _stock()
	after_sle_count = frappe.db.count("Stock Ledger Entry")
	no_sle = (after_stock == before_stock and after_sle_count == before_sle_count)
	ok = _check(checks, "approval_no_sle", no_sle, {"stock": after_stock, "sle_count": after_sle_count}) and ok

	return ok


def _check_finish_picking(data: dict, checks: dict[str, str] | None = None) -> bool:
	if checks is None:
		checks = {}
	ok = True
	from warehouse_app.warehouse_app.fulfillment.api import (
		approve_short_pick,
		complete_picking,
		get_run_workspace,
		request_short_pick_approval,
		submit_pick_list,
	)

	before_stock = _stock()
	before_sle_count = frappe.db.count("Stock Ledger Entry")

	# Target runs from previous test steps:
	mixed_so_name = data["sales_orders"]["mixed"]
	mixed_run = frappe.db.get_value(RUN, {"sales_order": mixed_so_name}, "name")
	mixed_ws = get_run_workspace(mixed_run)
	dry_pl = mixed_ws["groups"]["dry"]["pick_list"]
	dry_mod = mixed_ws["groups"]["dry"]["modified"]
	frozen_pl = mixed_ws["groups"]["frozen"]["pick_list"]
	frozen_mod = mixed_ws["groups"]["frozen"]["modified"]

	dry_so_name = data["sales_orders"]["dry"]
	block_run = frappe.db.get_value(RUN, {"sales_order": dry_so_name}, "name")

	frozen_so_name = data["sales_orders"]["frozen"]
	app_run = frappe.db.get_value(RUN, {"sales_order": frozen_so_name}, "name")

	# 1. Stale PL modified fails with STALE_PL
	stale_failed = False
	try:
		complete_picking(
			run=mixed_run,
			expected_modified={dry_pl: "2020-01-01 00:00:00.000000", frozen_pl: frozen_mod},
		)
	except Exception as exc:
		if "STALE_PL" in str(exc):
			stale_failed = True
	ok = _check(checks, "finish_stale_pl_fails", stale_failed, stale_failed) and ok

	# 2. Untouched/zero row fails with PICKED_QTY_ZERO_UNSUPPORTED even when Run has no short rows
	zero_row_failed = False
	dry_pl_doc = frappe.get_doc("Pick List", dry_pl)
	dry_loc_row = dry_pl_doc.locations[0]
	orig_custom_qty = dry_loc_row.custom_picked_qty
	try:
		frappe.db.set_value("Pick List Item", dry_loc_row.name, "custom_picked_qty", 0.0)
		frappe.clear_document_cache("Pick List", dry_pl)
		complete_picking(
			run=mixed_run,
			expected_modified={dry_pl: dry_mod, frozen_pl: frozen_mod},
		)
	except Exception as exc:
		if "PICKED_QTY_ZERO_UNSUPPORTED" in str(exc):
			zero_row_failed = True
	finally:
		frappe.db.set_value("Pick List Item", dry_loc_row.name, "custom_picked_qty", orig_custom_qty)
		frappe.clear_document_cache("Pick List", dry_pl)
	ok = _check(checks, "finish_zero_row_fails", zero_row_failed, zero_row_failed) and ok

	# 3. Block Run (policy 0): Finish fails with SHORT_PICK_BLOCKED
	block_failed = False
	try:
		complete_picking(run=block_run)
	except Exception as exc:
		if "SHORT_PICK_BLOCKED" in str(exc):
			block_failed = True
	block_pl_name = frappe.db.get_value(RUN, block_run, "dry_pick_list")
	block_pl_draft = frappe.db.get_value("Pick List", block_pl_name, "docstatus") == 0
	ok = _check(
		checks,
		"finish_block_run_fails_short_pick_blocked",
		block_failed and block_pl_draft,
		{"block_failed": block_failed, "block_pl_draft": block_pl_draft},
	) and ok

	# 4. Short Run with policy 1 and Pending: Finish fails with SHORT_PICK_APPROVAL_PENDING
	pending_failed = False
	request_short_pick_approval(run=app_run, reason="Requesting approval for frozen short pick")
	try:
		complete_picking(run=app_run)
	except Exception as exc:
		if "SHORT_PICK_APPROVAL_PENDING" in str(exc):
			pending_failed = True
	app_pl_name = frappe.db.get_value(RUN, app_run, "frozen_pick_list")
	app_pl_draft = frappe.db.get_value("Pick List", app_pl_name, "docstatus") == 0
	ok = _check(
		checks,
		"finish_pending_run_fails_approval_pending",
		pending_failed and app_pl_draft,
		{"pending_failed": pending_failed, "app_pl_draft": app_pl_draft},
	) and ok

	# 5. Full Run: Submit single PL via submit_pick_list, then finish picking submits remaining PL
	fresh_dry_mod = str(frappe.db.get_value("Pick List", dry_pl, "modified"))
	fresh_frozen_mod = str(frappe.db.get_value("Pick List", frozen_pl, "modified"))

	# Test submit_pick_list validation: invalid group and stale modified
	submit_invalid_group_failed = False
	try:
		submit_pick_list(run=mixed_run, group="invalid_group", expected_pl_modified=fresh_dry_mod)
	except Exception as exc:
		if "WRONG_PL_ROW" in str(exc) or "PL_NOT_DRAFT" in str(exc):
			submit_invalid_group_failed = True

	submit_stale_failed = False
	try:
		submit_pick_list(run=mixed_run, group="dry", expected_pl_modified="2020-01-01 00:00:00.000000")
	except Exception as exc:
		if "STALE_PL" in str(exc):
			submit_stale_failed = True

	ok = _check(
		checks,
		"submit_pick_list_validations",
		submit_invalid_group_failed and submit_stale_failed,
		{"invalid_group": submit_invalid_group_failed, "stale": submit_stale_failed},
	) and ok

	# Submit dry group via submit_pick_list
	ws_dry_submitted = submit_pick_list(run=mixed_run, group="dry", expected_pl_modified=fresh_dry_mod)
	dry_submitted = frappe.db.get_value("Pick List", dry_pl, "docstatus") == 1
	frozen_still_draft = frappe.db.get_value("Pick List", frozen_pl, "docstatus") == 0
	mixed_still_picking = ws_dry_submitted["run"]["status"] == "PICKING"
	ok = _check(
		checks,
		"submit_pick_list_single_group_submits",
		dry_submitted and frozen_still_draft and mixed_still_picking,
		{"dry": dry_submitted, "frozen": frozen_still_draft, "status": ws_dry_submitted["run"]["status"]},
	) and ok

	# Complete picking submits remaining PL (skips already submitted dry PL) and advances status to PICKED
	ws_mixed_done = complete_picking(
		run=mixed_run,
		expected_modified={frozen_pl: fresh_frozen_mod},
	)
	frozen_submitted = frappe.db.get_value("Pick List", frozen_pl, "docstatus") == 1
	mixed_picked = (
		ws_mixed_done["run"]["status"] == "PICKED"
		and dry_submitted
		and frozen_submitted
		and ws_mixed_done["groups"]["dry"]["docstatus"] == 1
		and ws_mixed_done["groups"]["frozen"]["docstatus"] == 1
		and ws_mixed_done["next_action"]["key"] == "create_delivery_note"
	)
	ok = _check(
		checks,
		"finish_full_run_submits_both_pls",
		mixed_picked,
		{"status": ws_mixed_done["run"]["status"], "dry": dry_submitted, "frozen": frozen_submitted},
	) and ok

	# 6. Short Run with policy 1 and Approved: Finish submits the native short PL; no SLE; picked qty remains short
	# 7. One-group Run (e.g. frozen only): Finish submits one PL cleanly and does not create an empty PL
	ws_app = get_run_workspace(app_run)
	approve_short_pick(run=app_run, expected_fingerprint=ws_app["short_pick"]["fingerprint"])
	ws_app_done = complete_picking(run=app_run)

	app_pl_doc = frappe.get_doc("Pick List", app_pl_name)
	app_submitted = app_pl_doc.docstatus == 1
	short_picked_retained = (
		flt(app_pl_doc.locations[0].custom_picked_qty) == 2.0
		and flt(app_pl_doc.locations[0].picked_qty) == 2.0
	)
	one_group_clean = (
		ws_app_done["run"]["status"] == "PICKED"
		and app_submitted
		and short_picked_retained
		and ws_app_done["groups"]["dry"]["pick_list"] is None
		and ws_app_done["groups"]["frozen"]["docstatus"] == 1
	)
	ok = _check(
		checks,
		"finish_short_approved_one_group_run",
		one_group_clean,
		{
			"status": ws_app_done["run"]["status"],
			"submitted": app_submitted,
			"custom_picked_qty": flt(app_pl_doc.locations[0].custom_picked_qty),
			"picked_qty": flt(app_pl_doc.locations[0].picked_qty),
			"dry_group": ws_app_done["groups"]["dry"]["pick_list"],
		},
	) and ok

	# 8. No SLE changes throughout
	after_stock = _stock()
	after_sle_count = frappe.db.count("Stock Ledger Entry")
	no_sle = (after_stock == before_stock and after_sle_count == before_sle_count)
	ok = _check(
		checks,
		"finish_picking_no_sle",
		no_sle,
		{"stock": after_stock, "sle_count": after_sle_count},
	) and ok

	return ok


def _check_delivery_note(data: dict, checks: dict[str, str] | None = None) -> bool:
	if checks is None:
		checks = {}
	ok = True
	from warehouse_app.warehouse_app.fulfillment.api import (
		create_delivery_note,
		get_run_workspace,
	)
	from warehouse_app.warehouse_app.fulfillment.idempotency import begin_request

	before_stock = _stock()
	before_sle_count = frappe.db.count("Stock Ledger Entry")

	mixed_so_name = data["sales_orders"]["mixed"]
	mixed_run = frappe.db.get_value(RUN, {"sales_order": mixed_so_name}, "name")

	dry_so_name = data["sales_orders"]["dry"]
	block_run = frappe.db.get_value(RUN, {"sales_order": dry_so_name}, "name")

	frozen_so_name = data["sales_orders"]["frozen"]
	app_run = frappe.db.get_value(RUN, {"sales_order": frozen_so_name}, "name")

	# 1. Attempt DN creation with draft PL fails PICKING_NOT_COMPLETE
	draft_pl_failed = False
	try:
		create_delivery_note(run=block_run, idempotency_key=f"{REQUEST_PREFIX}-BLOCK-DN")
	except Exception as exc:
		if "PICKING_NOT_COMPLETE" in str(exc):
			draft_pl_failed = True
	block_dn_exists = bool(frappe.db.get_value(RUN, block_run, "delivery_note"))
	ok = _check(
		checks,
		"dn_draft_pl_fails",
		draft_pl_failed and not block_dn_exists,
		{"failed": draft_pl_failed, "dn": block_dn_exists},
	) and ok

	# 2. Pending short pick fails SHORT_PICK_APPROVAL_PENDING and creates no DN
	app_run_doc = frappe.get_doc(RUN, app_run)
	orig_status = app_run_doc.short_pick_status
	frappe.db.set_value(RUN, app_run, "short_pick_status", "Pending")
	pending_failed = False
	try:
		create_delivery_note(run=app_run, idempotency_key=f"{REQUEST_PREFIX}-APP-DN-PENDING")
	except Exception as exc:
		if "SHORT_PICK_APPROVAL_PENDING" in str(exc):
			pending_failed = True
	app_dn_none = not bool(frappe.db.get_value(RUN, app_run, "delivery_note"))
	frappe.db.set_value(RUN, app_run, "short_pick_status", orig_status)
	ok = _check(
		checks,
		"dn_pending_short_pick_fails",
		pending_failed and app_dn_none,
		{"failed": pending_failed, "dn_none": app_dn_none},
	) and ok

	# 3. Call with same key and mismatched payload fails IDEMPOTENCY_MISMATCH
	mismatch_key = f"{REQUEST_PREFIX}-APP-MISMATCH"
	app_so = frappe.db.get_value(RUN, app_run, "sales_order")
	app_company = frappe.db.get_value(RUN, app_run, "company")
	begin_request(
		"Administrator",
		app_company,
		app_so,
		"CreateDeliveryNote",
		mismatch_key,
		"0000000000000000000000000000000000000000000000000000000000000000",
	)
	mismatch_failed = False
	try:
		create_delivery_note(run=app_run, idempotency_key=mismatch_key)
	except Exception as exc:
		if "IDEMPOTENCY_MISMATCH" in str(exc):
			mismatch_failed = True
	ok = _check(
		checks,
		"dn_idempotency_mismatch_fails",
		mismatch_failed,
		mismatch_failed,
	) and ok

	# 4. Mixed Run: create one DN from 2 submitted PLs; assert both PLs in against_pick_list; Run.delivery_note == dn.name; Run.status == "DN_DRAFT"
	mixed_key = f"{REQUEST_PREFIX}-MIXED-DN"
	ws_dn = create_delivery_note(run=mixed_run, idempotency_key=mixed_key)
	mixed_run_doc = frappe.get_doc(RUN, mixed_run)
	dn_name = mixed_run_doc.delivery_note
	dn_doc = frappe.get_doc("Delivery Note", dn_name)
	dn_items_pls = {item.against_pick_list for item in dn_doc.items if item.against_pick_list}
	expected_pls = {mixed_run_doc.dry_pick_list, mixed_run_doc.frozen_pick_list}

	mixed_dn_ok = (
		dn_doc.docstatus == 0
		and dn_items_pls == expected_pls
		and mixed_run_doc.status == "DN_DRAFT"
		and mixed_run_doc.dn_created_at is not None
		and ws_dn["delivery_note"]["name"] == dn_name
		and ws_dn["run"]["status"] == "DN_DRAFT"
	)
	ok = _check(
		checks,
		"mixed_run_dn_created",
		mixed_dn_ok,
		{"dn": dn_name, "pls": list(dn_items_pls), "status": mixed_run_doc.status},
	) and ok

	# 5. Replay with same key returns same DN and creates no second DN
	ws_dn_replay = create_delivery_note(run=mixed_run, idempotency_key=mixed_key)
	dn_count_mixed = frappe.db.count("Delivery Note", {"custom_fulfillment_run": mixed_run})
	replay_ok = (
		ws_dn_replay["delivery_note"]["name"] == dn_name
		and dn_count_mixed == 1
	)
	ok = _check(
		checks,
		"dn_replay_same_key",
		replay_ok,
		{"replayed_dn": ws_dn_replay["delivery_note"]["name"], "dn_count": dn_count_mixed},
	) and ok

	# 6. One-group Run creates DN from one PL
	app_key = f"{REQUEST_PREFIX}-APP-DN"
	ws_app_dn = create_delivery_note(run=app_run, idempotency_key=app_key)
	app_run_doc = frappe.get_doc(RUN, app_run)
	app_dn_name = app_run_doc.delivery_note
	app_dn_doc = frappe.get_doc("Delivery Note", app_dn_name)
	app_dn_items_pls = {item.against_pick_list for item in app_dn_doc.items if item.against_pick_list}
	expected_app_pls = {app_run_doc.frozen_pick_list}

	one_group_ok = (
		app_dn_doc.docstatus == 0
		and app_dn_items_pls == expected_app_pls
		and app_run_doc.status == "DN_DRAFT"
		and ws_app_dn["delivery_note"]["name"] == app_dn_name
	)
	ok = _check(
		checks,
		"one_group_dn_created",
		one_group_ok,
		{"dn": app_dn_name, "pls": list(app_dn_items_pls)},
	) and ok

	# 7. No SLE changes throughout
	after_stock = _stock()
	after_sle_count = frappe.db.count("Stock Ledger Entry")
	no_sle = (after_stock == before_stock and after_sle_count == before_sle_count)
	ok = _check(
		checks,
		"delivery_note_no_sle",
		no_sle,
		{"stock": after_stock, "sle_count": after_sle_count},
	) and ok

	return ok


def _check_packing(data: dict, checks: dict[str, str] | None = None) -> bool:
	if checks is None:
		checks = {}
	ok = True
	from warehouse_app.warehouse_app.fulfillment.api import (
		get_run_workspace,
		pack_all,
		reset_packing,
	)

	before_stock = _stock()
	before_sle_count = frappe.db.count("Stock Ledger Entry")

	mixed_so_name = data["sales_orders"]["mixed"]
	mixed_run = frappe.db.get_value(RUN, {"sales_order": mixed_so_name}, "name")
	ws_before = get_run_workspace(mixed_run)
	dn_name = ws_before["delivery_note"]["name"]
	dn_mod = ws_before["delivery_note"]["modified"]

	# 1. Stale DN modified fails STALE_DN
	stale_dn_failed = False
	try:
		pack_all(run=mixed_run, expected_dn_modified="2020-01-01 00:00:00.000000")
	except Exception as exc:
		if "STALE_DN" in str(exc):
			stale_dn_failed = True
	ok = _check(checks, "pack_stale_dn_fails", stale_dn_failed, stale_dn_failed) and ok

	# 2. Pack all on mixed Run: assert exactly 1 submitted PS, all DN items packed, Run status READY, no SLE
	ws_packed = pack_all(run=mixed_run, expected_dn_modified=dn_mod)
	ps_list = frappe.get_all(
		"Packing Slip",
		filters={"custom_fulfillment_run": mixed_run, "delivery_note": dn_name},
		fields=["name", "docstatus"],
	)
	dn_doc = frappe.get_doc("Delivery Note", dn_name)
	all_dn_packed = bool(dn_doc.items) and all(flt(item.packed_qty) >= flt(item.qty) for item in dn_doc.items)
	sle_count_packed = frappe.db.count("Stock Ledger Entry")
	pack_all_ok = (
		len(ps_list) == 1
		and ps_list[0].docstatus == 1
		and all_dn_packed
		and ws_packed["run"]["status"] == "READY"
		and ws_packed["packing"]["fully_packed"] is True
		and ws_packed["next_action"]["key"] == "submit_delivery_note"
		and _stock() == before_stock
		and sle_count_packed == before_sle_count
	)
	ok = _check(
		checks,
		"pack_all_submitted_one_ps",
		pack_all_ok,
		{"ps_count": len(ps_list), "fully_packed": all_dn_packed, "status": ws_packed["run"]["status"]},
	) and ok
	first_ps_name = ps_list[0].name

	# 3. Replay pack_all returns same PS and creates no duplicate
	fresh_dn_mod = str(frappe.db.get_value("Delivery Note", dn_name, "modified"))
	ws_replay = pack_all(run=mixed_run, expected_dn_modified=fresh_dn_mod)
	ps_list_replay = frappe.get_all(
		"Packing Slip",
		filters={"custom_fulfillment_run": mixed_run, "delivery_note": dn_name},
		fields=["name", "docstatus"],
	)
	replay_ok = (
		len(ps_list_replay) == 1
		and ps_list_replay[0].name == first_ps_name
		and ws_replay["run"]["status"] == "READY"
	)
	ok = _check(
		checks,
		"pack_all_replay_idempotent",
		replay_ok,
		{"ps_count": len(ps_list_replay), "ps_name": ps_list_replay[0].name if ps_list_replay else None},
	) and ok

	# 4. Reset packing cancels PS, DN packed_qty returns to 0, Run status PACKING, no SLE
	fresh_dn_mod_2 = str(frappe.db.get_value("Delivery Note", dn_name, "modified"))
	ws_reset = reset_packing(run=mixed_run, expected_dn_modified=fresh_dn_mod_2)
	ps_after_cancel = frappe.get_doc("Packing Slip", first_ps_name)
	dn_after_reset = frappe.get_doc("Delivery Note", dn_name)
	all_packed_zero = all(flt(item.packed_qty) == 0 for item in dn_after_reset.items)
	sle_count_reset = frappe.db.count("Stock Ledger Entry")
	reset_ok = (
		ps_after_cancel.docstatus == 2
		and all_packed_zero
		and ws_reset["run"]["status"] == "PACKING"
		and ws_reset["packing"]["fully_packed"] is False
		and ws_reset["next_action"]["key"] == "pack_all"
		and _stock() == before_stock
		and sle_count_reset == before_sle_count
	)
	ok = _check(
		checks,
		"reset_packing_cancels_ps",
		reset_ok,
		{
			"ps_docstatus": ps_after_cancel.docstatus,
			"all_packed_zero": all_packed_zero,
			"status": ws_reset["run"]["status"],
		},
	) and ok

	# 5. Pack all again creates a new submitted PS, all rows packed, status READY, no SLE
	fresh_dn_mod_3 = str(frappe.db.get_value("Delivery Note", dn_name, "modified"))
	ws_repack = pack_all(run=mixed_run, expected_dn_modified=fresh_dn_mod_3)
	ps_active_list = frappe.get_all(
		"Packing Slip",
		filters={"custom_fulfillment_run": mixed_run, "delivery_note": dn_name, "docstatus": 1},
		fields=["name"],
	)
	dn_after_repack = frappe.get_doc("Delivery Note", dn_name)
	all_packed_again = all(flt(item.packed_qty) >= flt(item.qty) for item in dn_after_repack.items)
	sle_count_repack = frappe.db.count("Stock Ledger Entry")
	repack_ok = (
		len(ps_active_list) == 1
		and ps_active_list[0].name != first_ps_name
		and all_packed_again
		and ws_repack["run"]["status"] == "READY"
		and ws_repack["packing"]["fully_packed"] is True
		and _stock() == before_stock
		and sle_count_repack == before_sle_count
	)
	ok = _check(
		checks,
		"pack_all_again_new_submitted_ps",
		repack_ok,
		{
			"new_ps": ps_active_list[0].name if ps_active_list else None,
			"all_packed": all_packed_again,
			"status": ws_repack["run"]["status"],
		},
	) and ok

	# 6. Reset packing rejected with DN_ALREADY_SUBMITTED when DN docstatus == 1
	dn_submitted_fail = False
	try:
		frappe.db.set_value("Delivery Note", dn_name, "docstatus", 1)
		frappe.clear_document_cache("Delivery Note", dn_name)
		reset_packing(run=mixed_run)
	except Exception as exc:
		if "DN_ALREADY_SUBMITTED" in str(exc):
			dn_submitted_fail = True
	finally:
		frappe.db.set_value("Delivery Note", dn_name, "docstatus", 0)
		frappe.clear_document_cache("Delivery Note", dn_name)
	ok = _check(
		checks,
		"reset_packing_dn_already_submitted_fails",
		dn_submitted_fail,
		dn_submitted_fail,
	) and ok

	# 7. No SLE throughout
	after_stock = _stock()
	after_sle = frappe.db.count("Stock Ledger Entry")
	no_sle = (after_stock == before_stock and after_sle == before_sle_count)
	ok = _check(
		checks,
		"packing_no_sle",
		no_sle,
		{"stock": after_stock, "sle_count": after_sle},
	) and ok

	return ok


def _check_submit_dn(data: dict, checks: dict[str, str] | None = None) -> bool:
	if checks is None:
		checks = {}
	ok = True
	from warehouse_app.warehouse_app.fulfillment.api import (
		get_run_workspace,
		reset_packing,
		submit_delivery_note,
	)

	mixed_so_name = data["sales_orders"]["mixed"]
	mixed_run = frappe.db.get_value(RUN, {"sales_order": mixed_so_name}, "name")
	mixed_ws = get_run_workspace(mixed_run)
	dn_name = mixed_ws["delivery_note"]["name"]

	frozen_so_name = data["sales_orders"]["frozen"]
	app_run = frappe.db.get_value(RUN, {"sales_order": frozen_so_name}, "name")

	# 1. Stale DN modified fails STALE_DN
	stale_dn_failed = False
	try:
		submit_delivery_note(
			run=mixed_run,
			idempotency_key=f"{REQUEST_PREFIX}-MIXED-SUBMIT-STALE",
			expected_dn_modified="2020-01-01 00:00:00.000000",
		)
	except Exception as exc:
		if "STALE_DN" in str(exc):
			stale_dn_failed = True
	ok = _check(checks, "submit_stale_dn_fails", stale_dn_failed, stale_dn_failed) and ok

	# 2. Unpacked / partially packed DN fails DN_NOT_FULLY_PACKED
	unpacked_failed = False
	try:
		submit_delivery_note(
			run=app_run,
			idempotency_key=f"{REQUEST_PREFIX}-APP-SUBMIT-UNPACKED",
		)
	except Exception as exc:
		if "DN_NOT_FULLY_PACKED" in str(exc):
			unpacked_failed = True
	ok = _check(checks, "submit_unpacked_dn_fails", unpacked_failed, unpacked_failed) and ok

	# 3. Pending short pick fails SHORT_PICK_APPROVAL_PENDING
	orig_app_status = frappe.db.get_value(RUN, app_run, "short_pick_status")
	frappe.db.set_value(RUN, app_run, "short_pick_status", "Pending")
	pending_failed = False
	try:
		submit_delivery_note(
			run=app_run,
			idempotency_key=f"{REQUEST_PREFIX}-APP-SUBMIT-PENDING",
		)
	except Exception as exc:
		if "SHORT_PICK_APPROVAL_PENDING" in str(exc):
			pending_failed = True
	finally:
		frappe.db.set_value(RUN, app_run, "short_pick_status", orig_app_status)
	ok = _check(checks, "submit_pending_short_pick_fails", pending_failed, pending_failed) and ok

	# 4. Submit mixed Run DN: assert dn.docstatus == 1, Run.status == "DISPATCHED", stock ledger changed, later reset packing fails DN_ALREADY_SUBMITTED
	before_stock = _stock()
	before_sle_count = frappe.db.count("Stock Ledger Entry")
	fresh_dn_mod = str(frappe.db.get_value("Delivery Note", dn_name, "modified"))
	submit_key = f"{REQUEST_PREFIX}-MIXED-SUBMIT"

	ws_dispatched = submit_delivery_note(
		run=mixed_run,
		idempotency_key=submit_key,
		expected_dn_modified=fresh_dn_mod,
	)

	dn_doc = frappe.get_doc("Delivery Note", dn_name)
	mixed_run_doc = frappe.get_doc(RUN, mixed_run)
	after_stock = _stock()
	after_sle_count = frappe.db.count("Stock Ledger Entry")

	stock_decreased = (
		after_stock[R0_DRY] < before_stock[R0_DRY]
		and after_stock[R0_FROZEN] < before_stock[R0_FROZEN]
		and after_stock[R0_BOX] < before_stock[R0_BOX]
	)
	sle_increased = after_sle_count > before_sle_count

	# Attempt reset packing on submitted DN fails DN_ALREADY_SUBMITTED
	reset_failed = False
	try:
		reset_packing(run=mixed_run)
	except Exception as exc:
		if "DN_ALREADY_SUBMITTED" in str(exc):
			reset_failed = True

	submit_ok = (
		dn_doc.docstatus == 1
		and mixed_run_doc.status == "DISPATCHED"
		and mixed_run_doc.dispatched_at is not None
		and ws_dispatched["run"]["status"] == "DISPATCHED"
		and ws_dispatched["next_action"]["key"] == "done"
		and ws_dispatched["next_action"]["enabled"] is False
		and stock_decreased
		and sle_increased
		and reset_failed
	)
	ok = _check(
		checks,
		"submit_mixed_run_dispatched",
		submit_ok,
		{
			"dn_docstatus": dn_doc.docstatus,
			"run_status": mixed_run_doc.status,
			"dispatched_at": mixed_run_doc.dispatched_at,
			"stock_decreased": stock_decreased,
			"sle_increased": sle_increased,
			"reset_failed": reset_failed,
		},
	) and ok

	# 5. Replay submit with same key: returns same submitted DN, no second stock movement
	ws_replay = submit_delivery_note(
		run=mixed_run,
		idempotency_key=submit_key,
	)
	replay_stock = _stock()
	replay_sle_count = frappe.db.count("Stock Ledger Entry")
	replay_ok = (
		ws_replay["delivery_note"]["name"] == dn_name
		and ws_replay["run"]["status"] == "DISPATCHED"
		and replay_stock == after_stock
		and replay_sle_count == after_sle_count
	)
	ok = _check(
		checks,
		"submit_replay_same_key_no_stock_movement",
		replay_ok,
		{
			"replayed_dn": ws_replay["delivery_note"]["name"],
			"run_status": ws_replay["run"]["status"],
			"stock_unchanged": replay_stock == after_stock,
			"sle_unchanged": replay_sle_count == after_sle_count,
		},
	) and ok

	return ok





