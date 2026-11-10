# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""F2 Generate acceptance gate. Draft-only product path; no stock movement."""

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.utils import add_days, flt, today

from warehouse_app.tests.w49_f1_fixture import (
	COMPANY,
	CUSTOMER,
	DRY_ITEM,
	FROZEN_ITEM,
	PROFILE,
	WAREHOUSE,
	guard_site,
)
from warehouse_app.warehouse_app.fulfillment.generate import (
	FulfillmentError,
	generate_fulfillment_run,
)
from warehouse_app.warehouse_app.fulfillment.idempotency import begin_request
from warehouse_app.warehouse_app.fulfillment.loader import load_order_preview, load_order_queue

RUN = "Warehouse Fulfillment Run"
KEY = "Warehouse Fulfillment Request Key"
TEST_MARKERS = (
	"ZZTEST-W49-F2-DRY",
	"ZZTEST-W49-F2-FROZEN",
	"ZZTEST-W49-F2-STALE",
	"ZZTEST-W49-F2-DISABLED",
	"ZZTEST-W49-F2-SHORT",
	"ZZTEST-W49-F2-ROLLBACK",
	"ZZTEST-W49-F2-PERM",
	"ZZTEST-W49-F2-UOM",
)
TEMP_EMAIL = "zztest-w49-f2-stock@example.com"


def run_gate() -> None:
	guard_site()
	checks: dict[str, str] = {}
	ok = True
	test_sos = []

	def check(name: str, passed: bool, evidence: object) -> None:
		nonlocal ok
		if not passed:
			ok = False
			checks[name] = f"FAIL: {evidence}"
		else:
			checks[name] = str(evidence)

	try:
		profile = _profile()
		original_enabled = profile.enabled
		profile.enabled = 1
		profile.save(ignore_permissions=True)
		frappe.db.commit()
		_cleanup_markers()
		so_open = _so("ZZTEST-W49-SO-OPEN")
		_cleanup_orders([so_open.name], [])
		preview = load_order_preview(so_open.name)
		check("preview_can_generate", preview["can_generate"] is True, preview["can_generate_reason"])
		check("preview_has_modified", bool(preview["modified"]), preview["modified"])
		check("preview_has_no_run", preview["run"] is None, preview["run"])
		queue = load_order_queue(company=COMPANY, stage="open", page_length=100)
		queue_row = next((row for row in queue["rows"] if row["sales_order"] == so_open.name), None)
		check(
			"queue_can_generate",
			bool(queue_row and queue_row.get("can_generate") is True),
			queue_row and queue_row.get("can_generate_reason"),
		)

		before_stock = _stock()
		key = "ZZTEST-W49-F2-KEY-OPEN"
		result = generate_fulfillment_run(
			sales_order=so_open.name,
			idempotency_key=key,
			expected_so_modified=preview["modified"],
			actor="Administrator",
		)
		check("run_created", bool(result["run"]) and result["reused"] is False, result["run"])
		check("two_draft_pls", bool(result["dry_pick_list"]) and bool(result["frozen_pick_list"]), result)
		check(
			"draft_pls",
			_pl_docstatus(result["dry_pick_list"]) == 0
			and _pl_docstatus(result["frozen_pick_list"]) == 0,
			"draft",
		)
		check("no_stock_movement", _stock() == before_stock, {"before": before_stock, "after": _stock()})
		check("no_picked_qty", _generated_picked_qty(so_open.name) == 0, _generated_picked_qty(so_open.name))
		check("run_active", _run_for(so_open.name) == result["run"], _run_for(so_open.name))
		check("run_items", _run_items(result["run"]) == 2, _run_items(result["run"]))
		check("run_allocations", _run_allocations(result["run"]) > 0, _run_allocations(result["run"]))
		check("run_item_required_stock", _run_required_stock(result["run"]) > 0, _run_required_stock(result["run"]))
		check("post_save_pl_lineage", _pl_lineage(result) is True, _pl_lineage(result))
		check("post_save_allocation_match", _allocation_match(result) is True, _allocation_match(result))

		replay = generate_fulfillment_run(so_open.name, key, preview["modified"], actor="Administrator")
		check("replay_same_run", replay["run"] == result["run"] and replay["reused"] is True, replay)

		second_key = "ZZTEST-W49-F2-KEY-OPEN-2"
		reused = generate_fulfillment_run(so_open.name, second_key, preview["modified"], actor="Administrator")
		check("active_run_reused", reused["run"] == result["run"] and reused["reused"] is True, reused)
		check("no_duplicate_run", len(frappe.get_all(RUN, filters={"sales_order": so_open.name}, pluck="name")) == 1, _run_for(so_open.name))

		mismatch = begin_request(
			"Administrator",
			COMPANY,
			so_open.name,
			"GeneratePickLists",
			key,
			"different-hash",
		)
		check("idempotency_mismatch", mismatch["state"] == "mismatch", mismatch["state"])

		dry_so = _test_so("ZZTEST-W49-F2-DRY", [(DRY_ITEM, 2, "Nos", 1)])
		test_sos.append(dry_so.name)
		dry_result = _generate(dry_so, "ZZTEST-W49-F2-KEY-DRY")
		check("dry_only", bool(dry_result["dry_pick_list"]) and dry_result["frozen_pick_list"] is None, dry_result)

		frozen_so = _test_so("ZZTEST-W49-F2-FROZEN", [(FROZEN_ITEM, 2, "Nos", 1)])
		test_sos.append(frozen_so.name)
		frozen_result = _generate(frozen_so, "ZZTEST-W49-F2-KEY-FROZEN")
		check("frozen_only", bool(frozen_result["frozen_pick_list"]) and frozen_result["dry_pick_list"] is None, frozen_result)

		stale_so = _create_so("ZZTEST-W49-F2-STALE", [(DRY_ITEM, 2, "Nos", 1)])
		test_sos.append(stale_so.name)
		try:
			generate_fulfillment_run(stale_so.name, "ZZTEST-W49-F2-KEY-STALE", "2000-01-01 00:00:00", actor="Administrator")
			check("stale_rejected", False, "generated")
		except FulfillmentError as exc:
			check("stale_rejected", exc.code == "SO_CHANGED", exc.code)
		check("stale_no_run", not _run_for(stale_so.name), _run_for(stale_so.name))

		disabled_so = _create_so("ZZTEST-W49-F2-DISABLED", [(DRY_ITEM, 2, "Nos", 1)])
		test_sos.append(disabled_so.name)
		profile.reload()
		profile.enabled = 0
		profile.save(ignore_permissions=True)
		frappe.db.commit()
		try:
			generate_fulfillment_run(
				disabled_so.name,
				"ZZTEST-W49-F2-KEY-DISABLED",
				str(disabled_so.modified),
				actor="Administrator",
			)
			check("disabled_profile_rejected", False, "generated")
		except FulfillmentError as exc:
			check("disabled_profile_rejected", exc.code == "PROFILE_DISABLED", exc.code)
		check("disabled_no_run", not _run_for(disabled_so.name), _run_for(disabled_so.name))
		profile.reload()
		profile.enabled = 1
		profile.save(ignore_permissions=True)
		frappe.db.commit()

		short_so = _create_so("ZZTEST-W49-F2-SHORT", [(DRY_ITEM, 500, "Nos", 1)])
		test_sos.append(short_so.name)
		try:
			generate_fulfillment_run(
				short_so.name,
				"ZZTEST-W49-F2-KEY-SHORT",
				str(short_so.modified),
				actor="Administrator",
			)
			check("shortage_rejected", False, "generated")
		except FulfillmentError as exc:
			check("shortage_rejected", exc.code == "STOCK_SHORTAGE", exc.code)
		check("shortage_no_run", not _run_for(short_so.name), _run_for(short_so.name))

		uom_so = _uom_shortage_so()
		test_sos.append(uom_so.name)
		try:
			generate_fulfillment_run(
				uom_so.name,
				"ZZTEST-W49-F2-KEY-UOM",
				str(uom_so.modified),
				actor="Administrator",
			)
			check("factor_shortage_rejected", False, "generated")
		except FulfillmentError as exc:
			check("factor_shortage_rejected", exc.code == "STOCK_SHORTAGE", exc.code)
		check("factor_shortage_no_run", not _run_for(uom_so.name), _run_for(uom_so.name))

		rollback_so = _create_so(
			"ZZTEST-W49-F2-ROLLBACK",
			[(DRY_ITEM, 2, "Nos", 1), (FROZEN_ITEM, 2, "Nos", 1)],
		)
		test_sos.append(rollback_so.name)
		original_insert = __import__(
			"warehouse_app.warehouse_app.fulfillment.generate", fromlist=["_insert_pick_list"]
		)._insert_pick_list
		calls = {"count": 0}

		def flaky_insert(*args, **kwargs):
			calls["count"] += 1
			if calls["count"] == 2:
				raise FulfillmentError("TEST_ROLLBACK", "forced second-PL failure")
			return original_insert(*args, **kwargs)

		with patch("warehouse_app.warehouse_app.fulfillment.generate._insert_pick_list", side_effect=flaky_insert):
			try:
				generate_fulfillment_run(
					rollback_so.name,
					"ZZTEST-W49-F2-KEY-ROLLBACK",
					str(rollback_so.modified),
					actor="Administrator",
				)
				check("rollback_rejected", False, "generated")
			except FulfillmentError as exc:
				check("rollback_rejected", exc.code == "TEST_ROLLBACK", exc.code)
		check("rollback_no_run", not _run_for(rollback_so.name), _run_for(rollback_so.name))
		check("rollback_no_pl", _pl_count(rollback_so.name) == 0, _pl_count(rollback_so.name))

		perm_so = _create_so("ZZTEST-W49-F2-PERM", [(DRY_ITEM, 2, "Nos", 1)])
		test_sos.append(perm_so.name)
		user = _create_stock_user()
		frappe.set_user(user)
		try:
			generate_fulfillment_run(
				perm_so.name,
				"ZZTEST-W49-F2-KEY-PERM",
				str(perm_so.modified),
				actor=user,
			)
			check("permission_rejected", False, "generated")
		except frappe.PermissionError:
			check("permission_rejected", True, "PermissionError")
		finally:
			frappe.set_user("Administrator")
		manager = frappe.get_doc("User", user)
		manager.add_roles("Stock Manager")
		manager.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.set_user(user)
		try:
			manager_result = generate_fulfillment_run(
				perm_so.name,
				"ZZTEST-W49-F2-KEY-PERM-MANAGER",
				str(perm_so.modified),
				actor=user,
			)
			check(
				"manager_can_generate",
				bool(manager_result.get("run")) and manager_result.get("reused") is False,
				manager_result.get("run"),
			)
		except Exception as exc:
			check("manager_can_generate", False, f"{type(exc).__name__}: {exc}")
		finally:
			frappe.set_user("Administrator")
		_cleanup_user(user)

		after_preview = load_order_preview(so_open.name)
		check("preview_run_summary", after_preview["run"] and after_preview["run"]["name"] == result["run"], after_preview["run"])
		check("preview_no_stock_side_effect", _stock() == before_stock, _stock())
	except Exception as exc:
		ok = False
		checks["exception"] = f"{type(exc).__name__}: {exc}"
		checks["traceback"] = frappe.get_traceback()
		frappe.log_error(frappe.get_traceback(), "W49 F2 gate")
	finally:
		frappe.set_user("Administrator")
		_cleanup_user(TEMP_EMAIL)
		_cleanup_orders([so_open.name] if "so_open" in locals() else [], test_sos)
		profile = _profile()
		profile.enabled = 1
		profile.save(ignore_permissions=True)
		frappe.db.commit()
		cleanup_sos = ([so_open.name] if "so_open" in locals() else []) + test_sos
		if cleanup_sos:
			check(
				"teardown_runs",
				frappe.db.count(RUN, {"sales_order": ("in", cleanup_sos)}) == 0,
				frappe.db.count(RUN, {"sales_order": ("in", cleanup_sos)}),
			)
			check(
				"teardown_keys",
				frappe.db.count(KEY, {"sales_order": ("in", cleanup_sos)}) == 0,
				frappe.db.count(KEY, {"sales_order": ("in", cleanup_sos)}),
			)
		check(
			"teardown_test_sos",
			all(not frappe.db.exists("Sales Order", name) for name in test_sos),
			[ name for name in test_sos if frappe.db.exists("Sales Order", name)],
		)

	print("GATE_JSON:" + json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, default=str))


def _profile():
	name = frappe.db.get_value(PROFILE, {"company": COMPANY}, "name")
	if not name:
		raise RuntimeError("F2 gate requires the F1 profile")
	return frappe.get_doc(PROFILE, name)


def _so(po_no: str):
	name = frappe.db.get_value("Sales Order", {"po_no": po_no}, "name")
	if not name:
		raise RuntimeError(f"Sales Order {po_no} not found")
	return frappe.get_doc("Sales Order", name)


def _test_so(marker: str, rows) -> str:
	return _create_so(marker, rows)


def _create_so(marker: str, rows) -> str:
	customer = frappe.db.get_value("Customer", {"customer_name": CUSTOMER}, "name")
	delivery_date = add_days(today(), 7)
	so = frappe.get_doc(
		{
			"doctype": "Sales Order",
			"customer": customer,
			"company": COMPANY,
			"transaction_date": today(),
			"delivery_date": delivery_date,
			"selling_price_list": "Standard Selling",
			"currency": "IDR",
			"conversion_rate": 1,
			"plc_conversion_rate": 1,
			"set_warehouse": WAREHOUSE,
			"po_no": marker,
			"items": [
				{
					"item_code": item_code,
					"qty": qty,
					"rate": 100,
					"price_list_rate": 100,
					"uom": uom,
					"conversion_factor": factor,
					"warehouse": WAREHOUSE,
					"delivery_date": delivery_date,
				}
				for item_code, qty, uom, factor in rows
			],
		}
	)
	so.insert(ignore_permissions=True)
	so.submit()
	frappe.db.commit()
	return so


def _generate(so, key: str) -> dict:
	return generate_fulfillment_run(
		sales_order=so.name,
		idempotency_key=key,
		expected_so_modified=str(so.modified),
		actor="Administrator",
	)


def _stock() -> dict[str, float]:
	return {
		code: flt(
			frappe.db.get_value("Bin", {"item_code": code, "warehouse": WAREHOUSE}, "actual_qty")
		)
		for code in (DRY_ITEM, FROZEN_ITEM)
	}


def _run_for(sales_order: str):
	return frappe.db.get_value(RUN, {"sales_order": sales_order}, "name")


def _pl_docstatus(pl):
	return frappe.db.get_value("Pick List", pl["name"], "docstatus") if pl else None


def _generated_picked_qty(sales_order: str) -> float:
	rows = frappe.get_all(
		"Pick List Item",
		filters={"sales_order": sales_order},
		fields=["picked_qty", "custom_picked_qty"],
	)
	return sum(flt(row.picked_qty) + flt(row.custom_picked_qty) for row in rows)


def _run_items(run: str) -> int:
	return frappe.db.count("Warehouse Fulfillment Run Item", {"parent": run})


def _run_allocations(run: str) -> int:
	return frappe.db.count("Warehouse Fulfillment Run Allocation", {"parent": run})


def _run_required_stock(run: str) -> float:
	return sum(
		flt(row.required_stock_qty)
		for row in frappe.get_all(
			"Warehouse Fulfillment Run Item",
			filters={"parent": run},
			fields=["required_stock_qty"],
		)
	)


def _pl_lineage(result: dict) -> bool:
	run = frappe.get_doc(RUN, result["run"])
	for group, key in (("Dry", "dry_pick_list"), ("Frozen", "frozen_pick_list")):
		info = result.get(key)
		if not info:
			continue
		pl = frappe.get_doc("Pick List", info["name"])
		if (
			pl.docstatus != 0
			or not pl.pick_manually
			or pl.custom_fulfillment_run != run.name
			or pl.custom_fulfillment_group != group
			or not pl.locations
		):
			return False
		if any(
			flt(row.picked_qty) or flt(getattr(row, "custom_picked_qty", 0))
			for row in pl.locations
		):
			return False
	return True


def _allocation_match(result: dict) -> bool:
	run = frappe.get_doc(RUN, result["run"])
	required = sum(flt(row.required_stock_qty) for row in run.items)
	allocated = sum(flt(row.allocated_stock_qty) for row in run.allocations)
	return required > 0 and allocated > 0 and abs(required - allocated) < 0.0001


def _uom_shortage_so():
	item = frappe.get_doc("Item", DRY_ITEM)
	original_uoms = [(row.uom, row.conversion_factor) for row in item.uoms]
	try:
		item.set("uoms", [])
		for uom, factor in original_uoms:
			item.append("uoms", {"uom": uom, "conversion_factor": factor})
		if not any(uom == "Box" for uom, _factor in original_uoms):
			item.append("uoms", {"uom": "Box", "conversion_factor": 12})
		item.save(ignore_permissions=True)
		frappe.db.commit()
		return _create_so("ZZTEST-W49-F2-UOM", [(DRY_ITEM, 10, "Box", 12)])
	finally:
		item.reload()
		item.set("uoms", [])
		for uom, factor in original_uoms:
			item.append("uoms", {"uom": uom, "conversion_factor": factor})
		item.save(ignore_permissions=True)
		frappe.db.commit()


def _pl_count(sales_order: str) -> int:
	return len(
		frappe.get_all(
			"Pick List Item",
			filters={"sales_order": sales_order},
			pluck="parent",
			distinct=True,
		)
	)


def _create_stock_user() -> str:
	_cleanup_user(TEMP_EMAIL)
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": TEMP_EMAIL,
			"first_name": "W49 F2 Stock",
			"send_welcome_email": 0,
		}
	).insert(ignore_permissions=True)
	user.add_roles("Stock User")
	user.save(ignore_permissions=True)
	frappe.db.commit()
	return user.name


def _cleanup_user(email) -> None:
	if not email or not frappe.db.exists("User", email):
		return
	frappe.delete_doc("User", email, force=1, ignore_permissions=True, ignore_missing=True)
	frappe.db.delete("Sessions", {"user": email})
	frappe.db.delete("Activity Log", {"user": email})
	if frappe.db.has_column("Activity Log", "for_user"):
		frappe.db.delete("Activity Log", {"for_user": email})
	frappe.db.commit()


def _cleanup_markers() -> None:
	so_names = frappe.get_all(
		"Sales Order", filters={"po_no": ("in", TEST_MARKERS)}, pluck="name"
	)
	_cleanup_orders([], so_names)


def _cleanup_orders(base_sos: list[str], test_sos: list[str]) -> None:
	so_names = list(dict.fromkeys([*base_sos, *test_sos]))
	if not so_names:
		return
	pl_names = frappe.get_all(
		"Pick List Item",
		filters={"sales_order": ("in", so_names)},
		pluck="parent",
		distinct=True,
	)
	for name in pl_names:
		if frappe.db.exists("Pick List", name):
			frappe.delete_doc("Pick List", name, force=1, ignore_permissions=True, ignore_missing=True)
	for name in frappe.get_all(RUN, filters={"sales_order": ("in", so_names)}, pluck="name"):
		frappe.delete_doc(RUN, name, force=1, ignore_permissions=True, ignore_missing=True)
	for name in frappe.get_all(KEY, filters={"sales_order": ("in", so_names)}, pluck="name"):
		frappe.delete_doc(KEY, name, force=1, ignore_permissions=True, ignore_missing=True)
	for name in test_sos:
		if not frappe.db.exists("Sales Order", name):
			continue
		doc = frappe.get_doc("Sales Order", name)
		if doc.docstatus == 1:
			doc.cancel()
		frappe.delete_doc("Sales Order", name, force=1, ignore_permissions=True, ignore_missing=True)
	frappe.db.commit()
