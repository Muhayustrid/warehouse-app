# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""Packing service: pack all items into a single package and reset packing."""

from __future__ import annotations

import json
import frappe
from erpnext.stock.doctype.delivery_note.delivery_note import make_packing_slip
from frappe.utils import flt

from warehouse_app.warehouse_app.fulfillment.generate import FulfillmentError
from warehouse_app.warehouse_app.fulfillment.permissions import has_write_roles, require_write
from warehouse_app.warehouse_app.fulfillment.short_pick import finish_blocker, short_rows
from warehouse_app.warehouse_app.fulfillment.workspace import get_run_workspace

RUN = "Warehouse Fulfillment Run"


def distribute_items_across_packages(items: list[dict], num_packages: int) -> list[list[dict]]:
	"""Distribute item quantities sequentially across N packages (sequential bin filling).
	Items are placed into boxes in order until box capacity is reached, keeping items intact
	in a single box rather than splitting every single SKU across all boxes.
	"""
	if num_packages <= 0 or not items:
		return []
	if num_packages == 1:
		return [[dict(item) for item in items]]

	total_qty = sum(flt(item.get("qty", 0)) for item in items)
	if total_qty <= 0:
		return [[] for _ in range(num_packages)]

	target_per_pkg = total_qty / num_packages
	packages: list[list[dict]] = [[] for _ in range(num_packages)]
	pkg_totals = [0.0] * num_packages
	current_pkg = 0

	for item in items:
		item_qty = flt(item.get("qty", 0))
		if item_qty <= 0:
			continue
		remaining = item_qty
		while remaining > 0.0001:
			if current_pkg >= num_packages - 1:
				pkg_item = dict(item)
				pkg_item["qty"] = int(remaining) if remaining == int(remaining) else remaining
				packages[-1].append(pkg_item)
				pkg_totals[-1] += remaining
				break

			cap_left = target_per_pkg - pkg_totals[current_pkg]
			if cap_left <= 0.0001:
				current_pkg += 1
				continue

			if remaining <= cap_left:
				pkg_item = dict(item)
				pkg_item["qty"] = int(remaining) if remaining == int(remaining) else remaining
				packages[current_pkg].append(pkg_item)
				pkg_totals[current_pkg] += remaining
				remaining = 0
			else:
				if pkg_totals[current_pkg] > 0.0001:
					current_pkg += 1
					continue
				else:
					import math
					take = int(math.ceil(cap_left)) if cap_left >= 1 else 1
					take = min(int(remaining), take)
					pkg_item = dict(item)
					pkg_item["qty"] = take
					packages[current_pkg].append(pkg_item)
					pkg_totals[current_pkg] += take
					remaining -= take
					current_pkg += 1

	return packages


def split_delivery_items_by_category(
	items: list,
	dry_pl: str | None = None,
	frozen_pl: str | None = None,
	frozen_groups: set[str] | None = None,
	dry_exceptions: set[str] | None = None,
) -> tuple[list, list]:
	"""Split delivery note items into dry and frozen collections."""
	dry: list = []
	frozen: list = []

	for row in items:
		item_code = row.get("item_code") if isinstance(row, dict) else getattr(row, "item_code", None)
		if dry_exceptions and item_code and item_code in dry_exceptions:
			dry.append(row)
			continue

		pl = row.get("against_pick_list") if isinstance(row, dict) else getattr(row, "against_pick_list", None)
		if dry_pl and pl == dry_pl:
			dry.append(row)
		elif frozen_pl and pl == frozen_pl:
			frozen.append(row)
		elif frozen_groups:
			ig = row.get("item_group") if isinstance(row, dict) else getattr(row, "item_group", None)
			if ig in frozen_groups:
				frozen.append(row)
			else:
				dry.append(row)
		else:
			dry.append(row)

	return dry, frozen


def plan_packing_slips(
	dry_items: list[dict],
	frozen_items: list[dict],
	dry_packages: int = 1,
	frozen_packages: int = 1,
) -> list[dict]:
	"""Plan sequential packing slips for dry and frozen categories."""
	slips: list[dict] = []
	case_no = 1

	if dry_items and dry_packages > 0:
		dry_pkgs = distribute_items_across_packages(dry_items, dry_packages)
		for pkg_items in dry_pkgs:
			if pkg_items:
				slips.append({
					"category": "dry",
					"case_no": case_no,
					"items": pkg_items,
				})
				case_no += 1

	if frozen_items and frozen_packages > 0:
		frozen_pkgs = distribute_items_across_packages(frozen_items, frozen_packages)
		for pkg_items in frozen_pkgs:
			if pkg_items:
				slips.append({
					"category": "frozen",
					"case_no": case_no,
					"items": pkg_items,
				})
				case_no += 1

	return slips


def pack_all(
	run: str,
	expected_dn_modified: str | None = None,
	actor: str | None = None,
	dry_packages: int | str | None = None,
	frozen_packages: int | str | None = None,
	custom_slips: list[dict] | str | None = None,
) -> dict:
	actor = actor or frappe.session.user
	if actor and actor != frappe.session.user:
		roles = set(frappe.get_roles(actor))
		if not has_write_roles(roles):
			raise frappe.PermissionError("Fulfillment writes require System Manager or paired stock roles.")
	else:
		require_write()

	if not run or not frappe.db.exists(RUN, run):
		raise FulfillmentError("RUN_NOT_FOUND", "Fulfillment Run does not exist.")

	run_doc = frappe.get_doc(RUN, run)

	if not frappe.has_permission("Company", doc=run_doc.company, ptype="read"):
		raise frappe.PermissionError

	if not run_doc.delivery_note:
		raise FulfillmentError("DN_NOT_FOUND", "Fulfillment Run has no Delivery Note.")

	if not frappe.db.exists("Delivery Note", run_doc.delivery_note):
		raise FulfillmentError("DN_NOT_FOUND", "Delivery Note does not exist.")

	dn = frappe.get_doc("Delivery Note", run_doc.delivery_note)

	if dn.docstatus != 0:
		raise FulfillmentError("DN_NOT_DRAFT", "Delivery Note is not in draft status.")

	if expected_dn_modified and str(dn.modified) != str(expected_dn_modified):
		raise FulfillmentError("STALE_DN", "Delivery Note has changed.")

	run_pls = [pl for pl in (run_doc.dry_pick_list, run_doc.frozen_pick_list) if pl]
	all_rows = []
	for pl_name in run_pls:
		pl = frappe.get_doc("Pick List", pl_name)
		for loc in pl.locations:
			all_rows.append({
				"pick_list": pl.name,
				"row": loc.name,
				"item_code": loc.item_code,
				"qty": flt(loc.qty),
				"custom_picked_qty": flt(getattr(loc, "custom_picked_qty", 0)),
			})

	short = short_rows(all_rows)
	blocker = finish_blocker(
		short,
		bool(run_doc.short_pick_approval_required_snapshot),
		run_doc.short_pick_status,
		run_doc.short_pick_fingerprint,
	)
	if blocker:
		raise FulfillmentError(blocker, f"Short pick blocked: {blocker}")

	# Idempotency check: submitted Packing Slip for this Run and DN
	existing_submitted_ps = frappe.get_all(
		"Packing Slip",
		filters={
			"custom_fulfillment_run": run_doc.name,
			"delivery_note": dn.name,
			"docstatus": 1,
		},
		pluck="name",
	)
	if existing_submitted_ps:
		dn.reload()
		if any(flt(item.packed_qty) < flt(item.qty) for item in dn.items):
			for ps_name in existing_submitted_ps:
				ps_doc = frappe.get_doc("Packing Slip", ps_name)
				ps_doc.update_prevdoc_status()
			dn.reload()
		fully_packed = bool(dn.items) and all(flt(item.packed_qty) >= flt(item.qty) for item in dn.items)
		run_doc.status = "READY" if fully_packed else "PACKING"
		run_doc.save()
		frappe.db.commit()
		return get_run_workspace(run)

	existing_draft_ps = frappe.get_all(
		"Packing Slip",
		filters={
			"delivery_note": dn.name,
			"docstatus": 0,
		},
		pluck="name",
	)
	num_dry = 0
	num_frozen = 0
	if isinstance(custom_slips, str):
		try:
			custom_slips = json.loads(custom_slips)
		except Exception:
			custom_slips = None

	if custom_slips and isinstance(custom_slips, list):
		dn_rows_by_detail = {row.name: row for row in dn.items}
		dn_rows_by_item = {}
		for row in dn.items:
			dn_rows_by_item.setdefault(row.item_code, []).append(row)

		case_no = 1
		for slip_data in custom_slips:
			items_list = slip_data.get("items") or []
			if not items_list:
				continue
			actual_case_no = int(slip_data.get("case_no") or case_no)
			ps = frappe.new_doc("Packing Slip")
			ps.delivery_note = dn.name
			ps.custom_fulfillment_run = run_doc.name
			ps.from_case_no = actual_case_no
			ps.to_case_no = actual_case_no
			if slip_data.get("box_size") in ("B", "K"):
				ps.custom_box_size = slip_data["box_size"]

			cat = (slip_data.get("category") or "").lower()
			if "frozen" in cat:
				num_frozen += 1
			else:
				num_dry += 1

			for it in items_list:
				item_code = it.get("item_code")
				qty = flt(it.get("qty", 0))
				if qty <= 0:
					continue
				dn_row = None
				if it.get("dn_detail") and it["dn_detail"] in dn_rows_by_detail:
					dn_row = dn_rows_by_detail[it["dn_detail"]]
				elif item_code in dn_rows_by_item:
					dn_row = dn_rows_by_item[item_code][0]

				if not dn_row:
					continue

				ps.append("items", {
					"item_code": dn_row.item_code,
					"item_name": getattr(dn_row, "item_name", None) or dn_row.item_code,
					"description": getattr(dn_row, "description", None) or dn_row.item_code,
					"qty": qty,
					"dn_detail": dn_row.name,
					"stock_uom": getattr(dn_row, "stock_uom", None) or getattr(dn_row, "uom", None),
					"batch_no": getattr(dn_row, "batch_no", None),
				})

			if ps.items:
				ps.insert()
				ps.submit()
				case_no = actual_case_no + 1
	elif existing_draft_ps:
		for draft_ps_name in existing_draft_ps:
			ps = frappe.get_doc("Packing Slip", draft_ps_name)
			ps.custom_fulfillment_run = run_doc.name
			ps.save()
			ps.submit()
		submitted_slips = frappe.get_all(
			"Packing Slip",
			filters={"delivery_note": dn.name, "docstatus": 1},
			pluck="name",
		)
		num_dry = len(submitted_slips)
	elif dry_packages is None and frozen_packages is None:
		ps = make_packing_slip(dn.name)
		ps.custom_fulfillment_run = run_doc.name
		ps.insert()
		ps.submit()
		dry_rows, frozen_rows = split_delivery_items_by_category(
			[{"against_pick_list": getattr(row, "against_pick_list", None), "item_group": getattr(row, "item_group", None)} for row in dn.items],
			dry_pl=run_doc.dry_pick_list,
			frozen_pl=run_doc.frozen_pick_list,
		)
		num_dry = 1 if dry_rows else 0
		num_frozen = 1 if frozen_rows else 0
	else:
		# Parse package counts
		parsed_dry_pkgs = int(dry_packages) if dry_packages is not None and str(dry_packages).strip() != "" else 1
		parsed_frozen_pkgs = int(frozen_packages) if frozen_packages is not None and str(frozen_packages).strip() != "" else 1

		unpacked_rows = []
		for row in dn.items:
			rem_qty = flt(row.qty) - flt(row.packed_qty)
			if rem_qty > 0:
				unpacked_rows.append({
					"item_code": row.item_code,
					"item_name": getattr(row, "item_name", None) or row.item_code,
					"description": getattr(row, "description", None) or row.item_code,
					"qty": rem_qty,
					"dn_detail": row.name,
					"stock_uom": getattr(row, "stock_uom", None) or getattr(row, "uom", None),
					"batch_no": getattr(row, "batch_no", None),
					"against_pick_list": getattr(row, "against_pick_list", None),
					"item_group": getattr(row, "item_group", None),
				})

		dry_rows, frozen_rows = split_delivery_items_by_category(
			unpacked_rows,
			dry_pl=run_doc.dry_pick_list,
			frozen_pl=run_doc.frozen_pick_list,
		)

		num_dry = max(1, parsed_dry_pkgs) if dry_rows else 0
		num_frozen = max(1, parsed_frozen_pkgs) if frozen_rows else 0

		slips_plan = plan_packing_slips(dry_rows, frozen_rows, num_dry, num_frozen)

		for slip_spec in slips_plan:
			ps = frappe.new_doc("Packing Slip")
			ps.delivery_note = dn.name
			ps.custom_fulfillment_run = run_doc.name
			ps.from_case_no = slip_spec["case_no"]
			ps.to_case_no = slip_spec["case_no"]
			for item_data in slip_spec["items"]:
				ps.append("items", {
					"item_code": item_data["item_code"],
					"item_name": item_data.get("item_name") or item_data["item_code"],
					"description": item_data.get("description") or item_data["item_code"],
					"qty": item_data["qty"],
					"dn_detail": item_data["dn_detail"],
					"stock_uom": item_data.get("stock_uom"),
					"batch_no": item_data.get("batch_no"),
				})
			ps.insert()
			ps.submit()

	if num_dry or num_frozen:
		frappe.db.set_value(
			"Delivery Note",
			dn.name,
			{
				"custom_dry_packages": num_dry,
				"custom_frozen_packages": num_frozen,
				"custom_total_packages": num_dry + num_frozen,
			},
			update_modified=False,
		)

	dn.reload()
	submitted_slips = frappe.get_all(
		"Packing Slip",
		filters={"delivery_note": dn.name, "docstatus": 1},
		pluck="name",
	)
	if submitted_slips and any(flt(item.packed_qty) < flt(item.qty) for item in dn.items):
		for ps_name in submitted_slips:
			ps_doc = frappe.get_doc("Packing Slip", ps_name)
			ps_doc.update_prevdoc_status()
		dn.reload()

	fully_packed = bool(dn.items) and all(flt(item.packed_qty) >= flt(item.qty) for item in dn.items)
	run_doc.status = "READY" if fully_packed else "PACKING"
	run_doc.save()
	frappe.db.commit()
	return get_run_workspace(run)


def reset_packing(
	run: str,
	expected_dn_modified: str | None = None,
	actor: str | None = None,
) -> dict:
	actor = actor or frappe.session.user
	if actor and actor != frappe.session.user:
		roles = set(frappe.get_roles(actor))
		if not has_write_roles(roles):
			raise frappe.PermissionError("Fulfillment writes require System Manager or paired stock roles.")
	else:
		require_write()

	if not run or not frappe.db.exists(RUN, run):
		raise FulfillmentError("RUN_NOT_FOUND", "Fulfillment Run does not exist.")

	run_doc = frappe.get_doc(RUN, run)

	if not frappe.has_permission("Company", doc=run_doc.company, ptype="read"):
		raise frappe.PermissionError

	if not run_doc.delivery_note:
		raise FulfillmentError("DN_NOT_FOUND", "Fulfillment Run has no Delivery Note.")

	if not frappe.db.exists("Delivery Note", run_doc.delivery_note):
		raise FulfillmentError("DN_NOT_FOUND", "Delivery Note does not exist.")

	dn = frappe.get_doc("Delivery Note", run_doc.delivery_note)

	if dn.docstatus == 1:
		raise FulfillmentError("DN_ALREADY_SUBMITTED", "Cannot reset packing on a submitted Delivery Note.")
	if dn.docstatus != 0:
		raise FulfillmentError("DN_NOT_DRAFT", "Delivery Note is not in draft status.")

	if expected_dn_modified and str(dn.modified) != str(expected_dn_modified):
		raise FulfillmentError("STALE_DN", "Delivery Note has changed.")

	submitted_ps_names = frappe.get_all(
		"Packing Slip",
		filters={
			"custom_fulfillment_run": run_doc.name,
			"delivery_note": dn.name,
			"docstatus": 1,
		},
		pluck="name",
	)
	if not submitted_ps_names:
		submitted_ps_names = frappe.get_all(
			"Packing Slip",
			filters={
				"delivery_note": dn.name,
				"docstatus": 1,
			},
			pluck="name",
		)

	if not submitted_ps_names:
		return get_run_workspace(run)

	for ps_name in submitted_ps_names:
		ps = frappe.get_doc("Packing Slip", ps_name)
		ps.cancel()

	frappe.db.set_value(
		"Delivery Note",
		dn.name,
		{
			"custom_dry_packages": 0,
			"custom_frozen_packages": 0,
			"custom_total_packages": 0,
		},
		update_modified=False,
	)
	dn.reload()
	if any(flt(item.packed_qty) > flt(item.qty) for item in dn.items):
		raise FulfillmentError("PACKING_RESET_FAILED", "Failed to reset packed quantities on Delivery Note.")

	run_doc.status = "PACKING"
	run_doc.save()
	frappe.db.commit()
	return get_run_workspace(run)
