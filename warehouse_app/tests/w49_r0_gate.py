# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""R0 runtime gate for F2. Executes native PL/DN/Packing flow on the test site."""

from __future__ import annotations

import json

import frappe
from frappe.utils import flt

from warehouse_app.tests.w49_f2_fixture import (
	R0_BATCH,
	R0_BOX,
	R0_DRY,
	R0_FROZEN,
	R0_STOCK_MARKER,
	WAREHOUSE,
	cleanup_r0,
	guard_site,
	seed_r0,
)
from warehouse_app.tests.w49_f1_fixture import FROZEN_CHILD


def run_gate() -> None:
	guard_site()
	checks: dict[str, str] = {}
	ok = True

	def check(name: str, passed: bool, evidence: object) -> None:
		nonlocal ok
		if not passed:
			ok = False
			checks[name] = f"FAIL: {evidence}"
		else:
			checks[name] = str(evidence)

	try:
		data = seed_r0()
		check("fixture", True, data["items"])
		check("stock", all(value >= 200 for value in _stock().values()), _stock())

		mixed = data["sales_orders"]["mixed"]
		group_map = _group_map(mixed, {FROZEN_CHILD})
		template = _template(mixed)
		split = _split(template, group_map)
		check(
			"native_template_rows",
			bool(template.locations) and all(row.sales_order_item for row in template.locations),
			[(row.sales_order_item, row.item_code, row.qty) for row in template.locations],
		)
		check("group_map_complete", set(group_map) == {row.sales_order_item for row in template.locations}, group_map)
		check("split_disjoint", _disjoint(split), {k: len(v) for k, v in split.items()})
		check(
			"split_union",
			{
				row.sales_order_item
				for rows in split.values()
				for row in rows
			}
			== set(group_map),
			{k: len(v) for k, v in split.items()},
		)
		check("dry_nonempty", bool(split["dry"]), len(split["dry"]))
		check("frozen_nonempty", bool(split["frozen"]), len(split["frozen"]))

		dry = _insert_group(template, split["dry"], "Dry", pick_manually=0)
		frozen = _insert_group(template, split["frozen"], "Frozen", pick_manually=1)
		check("saved_disjoint", _saved_disjoint(dry.name, frozen.name), (dry.name, frozen.name))

		stock_before_pl = _stock()
		_dry_full(dry)
		dry.submit()
		check("dry_submitted", dry.docstatus == 1, dry.name)

		_short_pick(frozen, 0.5)
		frozen.submit()
		check("frozen_short_submitted", frozen.docstatus == 1, frozen.name)
		check("pl_submit_no_stock_movement", _stock() == stock_before_pl, {"before": stock_before_pl, "after": _stock()})

		dn = _create_dn(dry.name, frozen.name)
		check("one_dn", bool(dn.name), dn.name)
		check("dn_draft", dn.docstatus == 0, dn.name)
		check("dn_from_both_pls", _dn_covers_both(dn.name, dry.name, frozen.name), dn.name)

		ps = _create_packing_slip(dn.name)
		check("packing_slip_submitted", ps.docstatus == 1, ps.name)
		dn.reload()
		check("dn_packed", _dn_fully_packed(dn.name), dn.name)

		before_dn = _stock()
		dn.submit()
		after_dn = _stock()
		check("dn_submitted", dn.docstatus == 1, dn.name)
		check("dn_stock_moved", _less(after_dn, before_dn), {"before": before_dn, "after": after_dn})
		progress = _so_progress(mixed)
		check(
			"so_progress",
			progress["docstatus"] == 1 and flt(progress["per_delivered"]) > 0,
			progress,
		)

		for state in ("dry", "frozen"):
			so_name = data["sales_orders"][state]
			so_map = _group_map(so_name, {FROZEN_CHILD})
			so_template = _template(so_name)
			so_split = _split(so_template, so_map)
			non_empty = [key for key, rows in so_split.items() if rows]
			check(f"{state}_only", non_empty == [state], {k: len(v) for k, v in so_split.items()})
			if non_empty:
				draft = _insert_group(so_template, so_split[non_empty[0]], state.title(), pick_manually=1)
				check(f"{state}_one_pl", bool(draft.name), draft.name)
				frappe.delete_doc("Pick List", draft.name, force=1, ignore_permissions=True)

		short = _template(data["sales_orders"]["frozen"])
		short_split = _split(short, _group_map(data["sales_orders"]["frozen"], {FROZEN_CHILD}))
		short_pl = _insert_group(short, short_split["frozen"], "Frozen scan", pick_manually=1)
		short_pl.scan_mode = 1
		_short_pick(short_pl, 0.5)
		try:
			short_pl.submit()
			check("scan_mode_short_rejected", False, "short pick submitted")
		except frappe.ValidationError:
			check("scan_mode_short_rejected", True, "ValidationError")

		check("batch_present", bool(frappe.db.exists("Batch", R0_BATCH)), R0_BATCH)
		check("items_present", all(frappe.db.exists("Item", code) for code in (R0_DRY, R0_FROZEN, R0_BOX)), data["items"])
	except Exception as exc:
		ok = False
		checks["exception"] = f"{type(exc).__name__}: {exc}"
		frappe.log_error(frappe.get_traceback(), "W49 R0 gate")
	finally:
		try:
			cleanup = cleanup_r0()
			checks["cleanup"] = cleanup
			checks["teardown_stock"] = _stock()
			checks["teardown_items"] = {
				code: frappe.db.exists("Item", code) for code in (R0_DRY, R0_FROZEN, R0_BOX)
			}
			checks["teardown_stock_metadata"] = frappe.db.exists(
				"Stock Entry", {"remarks": R0_STOCK_MARKER}
			)
		except Exception as exc:
			ok = False
			checks["cleanup_exception"] = f"{type(exc).__name__}: {exc}"
			frappe.log_error(frappe.get_traceback(), "W49 R0 cleanup")

	print("GATE_JSON:" + json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, default=str))


def _stock() -> dict[str, float]:
	return {
		code: flt(
			frappe.db.get_value("Bin", {"item_code": code, "warehouse": WAREHOUSE}, "actual_qty")
		)
		for code in (R0_DRY, R0_FROZEN, R0_BOX)
	}


def _template(sales_order: str):
	from erpnext.selling.doctype.sales_order.sales_order import create_pick_list

	return create_pick_list(sales_order)


def _group_map(sales_order: str, frozen: set[str]) -> dict[str, str]:
	so = frappe.get_doc("Sales Order", sales_order)
	out = {}
	for row in so.items:
		item_group = frappe.db.get_value("Item", row.item_code, "item_group")
		out[row.name] = "frozen" if item_group in frozen else "dry"
	return out


def _split(template, group_map: dict[str, str]) -> dict[str, list[dict]]:
	out = {"dry": [], "frozen": []}
	for row in template.locations:
		group = group_map.get(row.sales_order_item)
		if not group:
			raise RuntimeError(f"No group for Pick List row {row.sales_order_item}")
		out[group].append(row)
	return out


def _disjoint(split: dict[str, list]) -> bool:
	seen = set()
	for rows in split.values():
		for row in rows:
			if row.sales_order_item in seen:
				return False
			seen.add(row.sales_order_item)
	return True


def _clone_group(template, rows: list, group: str):
	pl = frappe.copy_doc(template)
	pl.set("locations", [])
	pl.pick_manually = 1
	for row in rows:
		values = row.as_dict()
		values.pop("name", None)
		values.pop("doctype", None)
		values.pop("parent", None)
		values.pop("parentfield", None)
		values.pop("parenttype", None)
		values.pop("idx", None)
		pl.append("locations", values)
	return pl


def _insert_group(template, rows: list, label: str, pick_manually: int):
	pl = _clone_group(template, rows, label)
	pl.pick_manually = pick_manually
	pl.scan_mode = 0
	pl.insert(ignore_permissions=True)
	pl.reload()
	return pl


def _saved_disjoint(dry: str, frozen: str) -> bool:
	dry_rows = {row.sales_order_item for row in frappe.get_doc("Pick List", dry).locations}
	frozen_rows = {row.sales_order_item for row in frappe.get_doc("Pick List", frozen).locations}
	return not (dry_rows & frozen_rows) and bool(dry_rows) and bool(frozen_rows)


def _dry_full(pl) -> None:
	for row in pl.locations:
		row.picked_qty = flt(row.stock_qty)
		row.custom_picked_qty = flt(row.qty)


def _short_pick(pl, fraction: float) -> None:
	for row in pl.locations:
		row.picked_qty = flt(flt(row.stock_qty) * fraction)
		row.custom_picked_qty = flt(flt(row.qty) * fraction)


def _create_dn(dry_pl: str, frozen_pl: str):
	from erpnext.stock.doctype.pick_list.pick_list import create_dn_for_pick_lists

	dn = create_dn_for_pick_lists(dry_pl)
	if not dn:
		raise RuntimeError("No DN from dry pick list")
	dn = create_dn_for_pick_lists(frozen_pl, target_doc=dn)
	if not dn:
		raise RuntimeError("No DN from frozen pick list")
	if not dn.name:
		dn.insert(ignore_permissions=True)
	return dn


def _dn_covers_both(dn_name: str, dry_pl: str, frozen_pl: str) -> bool:
	rows = frappe.get_all(
		"Delivery Note Item",
		filters={"parent": dn_name},
		fields=["against_pick_list"],
	)
	against = {row.against_pick_list for row in rows if row.against_pick_list}
	return dry_pl in against and frozen_pl in against


def _create_packing_slip(dn_name: str):
	from erpnext.stock.doctype.delivery_note.delivery_note import make_packing_slip

	ps = make_packing_slip(dn_name)
	if not ps:
		raise RuntimeError("No Packing Slip")
	ps.from_case_no = 1
	ps.to_case_no = 1
	ps.insert(ignore_permissions=True)
	ps.submit()
	return ps


def _dn_fully_packed(dn_name: str) -> bool:
	rows = frappe.get_all(
		"Delivery Note Item",
		filters={"parent": dn_name},
		fields=["qty", "packed_qty"],
	)
	return bool(rows) and all(flt(row.packed_qty) >= flt(row.qty) for row in rows)


def _less(after: dict, before: dict) -> bool:
	return all(flt(after[key]) < flt(before[key]) for key in after)


def _so_progress(sales_order: str) -> dict:
	so = frappe.get_doc("Sales Order", sales_order)
	return {
		"status": so.status,
		"per_delivered": so.per_delivered,
		"per_picked": so.per_picked,
		"docstatus": so.docstatus,
	}
