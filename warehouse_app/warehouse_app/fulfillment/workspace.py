# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""Read-only workspace projection over native fulfillment documents."""

from __future__ import annotations

import frappe
from frappe.utils import flt

from warehouse_app.warehouse_app.fulfillment.generate import FulfillmentError
from warehouse_app.warehouse_app.fulfillment.permissions import (
	has_approver_roles,
	has_write_roles,
	require_read,
)
from warehouse_app.warehouse_app.fulfillment.short_pick import (
	finish_blocker,
	short_fingerprint,
	short_rows,
)

RUN = "Warehouse Fulfillment Run"
PROFILE = "Warehouse Fulfillment Profile"
from warehouse_app.warehouse_app.fulfillment.profile import resolve_dry_exceptions


def get_run_workspace(run: str) -> dict:
	if not run or not frappe.db.exists(RUN, run):
		raise FulfillmentError("RUN_NOT_FOUND", "Fulfillment Run does not exist.")
	run_doc = _readable_doc(RUN, run)
	require_read()

	so = _readable_doc("Sales Order", run_doc.sales_order)
	profile = _readable_doc(PROFILE, run_doc.profile)
	groups = {
		"dry": _pick_list_group(run_doc.dry_pick_list),
		"frozen": _pick_list_group(run_doc.frozen_pick_list),
	}
	short = short_rows(_short_pick_source(groups))
	fingerprint = short_fingerprint(short)
	blocker = finish_blocker(
		short,
		bool(run_doc.short_pick_approval_required_snapshot),
		run_doc.short_pick_status,
		run_doc.short_pick_fingerprint,
	)
	delivery_note, packing = _delivery_projection(run_doc.delivery_note)
	roles = set(frappe.get_roles())

	return {
		"run": _run_payload(run_doc, so),
		"sales_order": {
			"name": so.name,
			"customer_name": so.customer_name,
			"delivery_date": _string(so.delivery_date),
			"modified": str(so.modified),
		},
		"profile": {
			"dry_display_name": profile.dry_display_name or "Dry",
			"frozen_display_name": profile.frozen_display_name or "Frozen",
			"dry_print_format": profile.dry_print_format,
			"frozen_print_format": profile.frozen_print_format,
			"dry_parent_warehouse": profile.dry_parent_warehouse,
			"frozen_parent_warehouse": profile.frozen_parent_warehouse,
			"dry_item_exceptions": sorted(list(resolve_dry_exceptions(profile))),
			"enable_packing_slip": 1 if getattr(profile, "enable_packing_slip", None) is None else int(profile.enable_packing_slip),
		},
		"groups": groups,
		"short_pick": {"rows": short, "fingerprint": fingerprint, "blocker": blocker},
		"delivery_note": delivery_note,
		"packing": packing,
		"permissions": {
			"can_write": has_write_roles(roles),
			"can_approve": has_approver_roles(roles),
		},
		"next_action": next_action(
			list(groups.values()),
			delivery_note,
			packing["fully_packed"],
			blocker,
			enable_packing_slip=bool(getattr(profile, "enable_packing_slip", 1) if getattr(profile, "enable_packing_slip", None) is not None else 1),
		),
	}


def next_action(
	pick_lists: list[dict],
	delivery_note: dict | None,
	fully_packed: bool,
	blocker: str | None = None,
	enable_packing_slip: bool = True,
) -> dict:
	active_pls = [row for row in pick_lists if row.get("docstatus") is not None]
	if blocker:
		return _action("review_short_pick", "Review short pick", True, blocker)
	if not active_pls:
		return _action("finish_picking", "Finish picking", False, "NO_PICK_LIST")
	if any(row.get("docstatus") == 0 for row in active_pls):
		return _action("finish_picking", "Finish picking")
	if delivery_note is None:
		all_submitted = all(row.get("docstatus") == 1 for row in active_pls)
		return _action(
			"create_delivery_note",
			"Create DN",
			all_submitted,
			None if all_submitted else "PL_NOT_SUBMITTED",
		)
	if delivery_note.get("docstatus") == 0:
		if not enable_packing_slip or fully_packed:
			return _action("submit_delivery_note", "Submit DN")
		return _action("pack_all", "Pack all")
	return _action("done", "Done", False)


def _run_payload(run, so) -> dict:
	return {
		"name": run.name,
		"status": run.status,
		"sales_order": run.sales_order,
		"customer": run.customer,
		"company": run.company,
		"delivery_date": _string(so.delivery_date),
		"short_pick_approval_required": 1 if run.short_pick_approval_required_snapshot else 0,
		"short_pick_status": run.short_pick_status or "None",
		"short_pick_reason": run.short_pick_reason or "",
		"short_pick_rejection_reason": run.short_pick_rejection_reason or "",
		"short_pick_fingerprint": run.short_pick_fingerprint or "",
		"short_pick_requested_by": run.short_pick_requested_by or "",
		"short_pick_approved_by": run.short_pick_approved_by or "",
		"delivery_note": run.delivery_note,
		"dn_created_at": _string(run.dn_created_at),
		"dispatched_at": _string(run.dispatched_at),
	}


def _pick_list_group(name: str | None) -> dict:
	if not name or not frappe.db.exists("Pick List", name):
		return {"pick_list": None, "docstatus": None, "modified": None, "rows": []}
	pl = _readable_doc("Pick List", name)
	return {
		"pick_list": pl.name,
		"docstatus": pl.docstatus,
		"modified": str(pl.modified),
		"rows": [
			{
				"name": row.name,
				"item_code": row.item_code,
				"item_name": row.item_name,
				"warehouse": row.warehouse,
				"qty": flt(row.qty),
				"custom_picked_qty": flt(row.get("custom_picked_qty")),
				"stock_qty": flt(row.stock_qty),
				"conversion_factor": flt(row.conversion_factor),
				"uom": row.uom,
				"batch_no": row.batch_no,
				"serial_and_batch_bundle": row.serial_and_batch_bundle,
			}
			for row in pl.locations
		],
	}


def _short_pick_source(groups: dict) -> list[dict]:
	return [
		{
			"pick_list": group["pick_list"],
			"row": row["name"],
			"item_code": row["item_code"],
			"qty": row["qty"],
			"custom_picked_qty": row["custom_picked_qty"],
		}
		for group in groups.values()
		for row in group["rows"]
	]


def _delivery_projection(name: str | None) -> tuple[dict | None, dict]:
	if not name or not frappe.db.exists("Delivery Note", name):
		return None, _empty_packing()
	dn = _readable_doc("Delivery Note", name)
	items = [
		{
			"name": row.name,
			"item_code": row.item_code,
			"item_name": row.item_name,
			"warehouse": row.warehouse,
			"qty": flt(row.qty),
			"packed_qty": flt(row.packed_qty),
			"uom": row.uom,
			"batch_no": row.batch_no,
			"against_sales_order": row.against_sales_order,
			"so_detail": row.so_detail,
			"against_pick_list": getattr(row, "against_pick_list", None),
			"item_group": getattr(row, "item_group", None),
		}
		for row in dn.items
	]
	raw_slips = frappe.get_list(
		"Packing Slip",
		filters={"delivery_note": dn.name, "docstatus": 1},
		fields=["name", "docstatus", "modified", "from_case_no", "to_case_no", "net_weight_pkg", "gross_weight_pkg"],
		order_by="from_case_no asc, modified asc",
		limit_page_length=0,
	)
	total_packages = max([row.to_case_no for row in raw_slips if row.to_case_no], default=len(raw_slips))
	submitted_slips = []
	for row in raw_slips:
		slip_items = frappe.get_all(
			"Packing Slip Item",
			filters={"parent": row.name},
			fields=["item_code", "item_name", "qty"],
			order_by="idx asc",
		)
		submitted_slips.append({
			"name": row.name,
			"docstatus": row.docstatus,
			"modified": str(row.modified),
			"from_case_no": row.from_case_no,
			"to_case_no": row.to_case_no,
			"total_packages": total_packages,
			"net_weight_pkg": flt(row.net_weight_pkg),
			"gross_weight_pkg": flt(row.gross_weight_pkg),
			"items_count": len(slip_items),
			"items": slip_items,
		})
	packing = {
		"submitted": submitted_slips,
		"total_packages": total_packages,
		"dry_packages": getattr(dn, "custom_dry_packages", 0) or 0,
		"frozen_packages": getattr(dn, "custom_frozen_packages", 0) or 0,
		"fully_packed": bool(items)
		and all(row["packed_qty"] >= row["qty"] for row in items),
		"dn_qty": sum(row["qty"] for row in items),
		"packed_qty": sum(row["packed_qty"] for row in items),
	}
	return {
		"name": dn.name,
		"docstatus": dn.docstatus,
		"modified": str(dn.modified),
		"items": items,
		"custom_dry_packages": getattr(dn, "custom_dry_packages", 0) or 0,
		"custom_frozen_packages": getattr(dn, "custom_frozen_packages", 0) or 0,
		"custom_total_packages": getattr(dn, "custom_total_packages", 0) or 0,
	}, packing


def _readable_doc(doctype: str, name: str):
	if not frappe.has_permission(doctype, doc=name, ptype="read"):
		raise frappe.PermissionError
	return frappe.get_doc(doctype, name)


def _empty_packing() -> dict:
	return {"submitted": [], "fully_packed": False, "dn_qty": 0, "packed_qty": 0}


def _action(key: str, label: str, enabled: bool = True, reason: str | None = None) -> dict:
	return {"key": key, "label": label, "enabled": enabled, "reason": reason}


def _string(value) -> str | None:
	return str(value) if value is not None else None
