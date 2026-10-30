# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""Picking service: validate and persist picked quantities on native Pick Lists."""

from __future__ import annotations

import json

import frappe
from frappe.utils import flt

from warehouse_app.warehouse_app.fulfillment.generate import FulfillmentError
from warehouse_app.warehouse_app.fulfillment.permissions import has_write_roles, require_write
from warehouse_app.warehouse_app.fulfillment.short_pick import finish_blocker, short_fingerprint, short_rows
from warehouse_app.warehouse_app.fulfillment.workspace import get_run_workspace

RUN = "Warehouse Fulfillment Run"


def save_picking(
	run: str,
	rows: list[dict],
	expected_modified: dict[str, str],
	actor: str | None = None,
) -> dict:
	actor = actor or frappe.session.user
	if actor and actor != frappe.session.user:
		roles = set(frappe.get_roles(actor))
		if not has_write_roles(roles):
			raise frappe.PermissionError("Fulfillment writes require System Manager or paired stock roles.")
	else:
		require_write()

	if isinstance(rows, str):
		try:
			rows = json.loads(rows)
		except Exception:
			raise FulfillmentError("WRONG_PL_ROW", "Invalid rows payload.")
	if isinstance(expected_modified, str):
		try:
			expected_modified = json.loads(expected_modified)
		except Exception:
			raise FulfillmentError("STALE_PL", "Invalid expected_modified payload.")

	if rows is None:
		rows = []
	if expected_modified is None:
		expected_modified = {}

	if not run or not frappe.db.exists(RUN, run):
		raise FulfillmentError("RUN_NOT_FOUND", "Fulfillment Run does not exist.")

	run_doc = frappe.get_doc(RUN, run)

	if not frappe.has_permission("Company", doc=run_doc.company, ptype="read"):
		raise frappe.PermissionError

	if run_doc.delivery_note:
		raise FulfillmentError("DN_EXISTS", "Run already has a Delivery Note.")

	run_pl_names = [pl for pl in (run_doc.dry_pick_list, run_doc.frozen_pick_list) if pl]
	if not run_pl_names:
		raise FulfillmentError("PL_NOT_DRAFT", "Run has no Pick Lists.")

	pl_docs = {name: frappe.get_doc("Pick List", name) for name in run_pl_names}

	draft_pls = [pl for pl in pl_docs.values() if pl.docstatus == 0]
	if not draft_pls:
		raise FulfillmentError("PL_NOT_DRAFT", "Run has no draft Pick Lists.")

	# Concurrency check against expected_modified
	for pl_name, exp_ts in expected_modified.items():
		if pl_name not in pl_docs or str(pl_docs[pl_name].modified) != str(exp_ts):
			raise FulfillmentError("STALE_PL", f"Pick List {pl_name} modified timestamp mismatch.")

	seen_rows: set[str] = set()
	touched_pls: set[str] = set()
	row_updates: list[tuple[object, object, float]] = []

	for r in rows:
		if not isinstance(r, dict):
			raise FulfillmentError("WRONG_PL_ROW", "Each row must be a dictionary.")
		pl_name = r.get("pick_list")
		row_name = r.get("row")
		if not pl_name or not row_name:
			raise FulfillmentError("WRONG_PL_ROW", "Row must specify pick_list and row.")
		if row_name in seen_rows:
			raise FulfillmentError("WRONG_PL_ROW", f"Duplicate row '{row_name}'.")
		seen_rows.add(row_name)

		if pl_name not in pl_docs:
			raise FulfillmentError("WRONG_PL_ROW", f"Pick List '{pl_name}' does not belong to this Run.")

		pl_doc = pl_docs[pl_name]
		if pl_doc.docstatus != 0:
			raise FulfillmentError("PL_NOT_DRAFT", f"Pick List '{pl_name}' is not in draft status.")

		if pl_name not in expected_modified or str(pl_doc.modified) != str(expected_modified[pl_name]):
			raise FulfillmentError("STALE_PL", f"Pick List '{pl_name}' modified timestamp mismatch.")

		loc = next((loc for loc in pl_doc.locations if loc.name == row_name), None)
		if not loc:
			raise FulfillmentError("WRONG_PL_ROW", f"Row '{row_name}' not found in Pick List '{pl_name}'.")

		if "picked_qty" not in r:
			raise FulfillmentError("PICKED_QTY_INVALID", f"Missing picked_qty for row '{row_name}'.")

		picked_qty = flt(r["picked_qty"])
		target_qty = flt(loc.qty)

		if picked_qty <= 0 or abs(picked_qty) < 0.0001:
			raise FulfillmentError("PICKED_QTY_ZERO_UNSUPPORTED", f"Zero picked quantity on row '{row_name}' is unsupported.")
		if picked_qty - target_qty > 0.0001:
			raise FulfillmentError("PICKED_QTY_INVALID", f"Picked quantity {picked_qty} exceeds target {target_qty} on row '{row_name}'.")

		touched_pls.add(pl_name)
		row_updates.append((pl_doc, loc, picked_qty))

	# Persist picked quantities on native Pick Lists
	for pl_doc, loc, picked_qty in row_updates:
		conversion_factor = flt(loc.conversion_factor) or 1.0
		loc.custom_picked_qty = picked_qty
		loc.picked_qty = flt(picked_qty * conversion_factor, loc.precision("picked_qty"))

	for pl_name in touched_pls:
		pl_docs[pl_name].save()

	# Recompute short rows and fingerprint
	all_rows = []
	for pl_doc in pl_docs.values():
		for loc in pl_doc.locations:
			all_rows.append({
				"pick_list": pl_doc.name,
				"row": loc.name,
				"item_code": loc.item_code,
				"qty": flt(loc.qty),
				"custom_picked_qty": flt(getattr(loc, "custom_picked_qty", 0)),
			})
	new_short = short_rows(all_rows)
	new_fingerprint = short_fingerprint(new_short)

	if (run_doc.short_pick_fingerprint and run_doc.short_pick_fingerprint != new_fingerprint) or (
		run_doc.short_pick_status not in (None, "None", "") and run_doc.short_pick_fingerprint != new_fingerprint
	):
		run_doc.short_pick_status = None
		run_doc.short_pick_fingerprint = ""
		run_doc.short_pick_approved_by = ""
		run_doc.short_pick_approved_on = None

	run_doc.status = "PICKING"
	run_doc.save()

	return get_run_workspace(run)


def complete_picking(
	run: str,
	expected_modified: dict[str, str] | str | None = None,
	actor: str | None = None,
	short_pick_reason: str | None = None,
) -> dict:
	actor = actor or frappe.session.user
	if actor and actor != frappe.session.user:
		roles = set(frappe.get_roles(actor))
		if not has_write_roles(roles):
			raise frappe.PermissionError("Fulfillment writes require System Manager or paired stock roles.")
	else:
		require_write()

	if isinstance(expected_modified, str):
		try:
			expected_modified = json.loads(expected_modified)
		except Exception:
			raise FulfillmentError("STALE_PL", "Invalid expected_modified payload.")
	if expected_modified is None:
		expected_modified = {}

	if not run or not frappe.db.exists(RUN, run):
		raise FulfillmentError("RUN_NOT_FOUND", "Fulfillment Run does not exist.")

	run_doc = frappe.get_doc(RUN, run)

	if not frappe.has_permission("Company", doc=run_doc.company, ptype="read"):
		raise frappe.PermissionError

	if run_doc.delivery_note:
		raise FulfillmentError("DN_EXISTS", "Run already has a Delivery Note.")

	run_pl_names = [pl for pl in (run_doc.dry_pick_list, run_doc.frozen_pick_list) if pl]
	if not run_pl_names:
		raise FulfillmentError("PL_NOT_DRAFT", "Run has no Pick Lists.")

	pl_docs = {name: frappe.get_doc("Pick List", name) for name in run_pl_names}

	for pl_name, pl_doc in pl_docs.items():
		if pl_doc.custom_fulfillment_run != run_doc.name:
			raise FulfillmentError("WRONG_PL_ROW", f"Pick List '{pl_name}' does not belong to this Run.")
		if pl_doc.docstatus not in (0, 1):
			raise FulfillmentError("PL_NOT_DRAFT", f"Pick List '{pl_name}' is not in draft or submitted status.")

	draft_pls = [pl for pl in pl_docs.values() if pl.docstatus == 0]
	if not draft_pls:
		raise FulfillmentError("PL_NOT_DRAFT", "Run has no draft Pick Lists.")

	# Concurrency check against expected_modified
	for pl in draft_pls:
		if pl.name in expected_modified and str(pl.modified) != str(expected_modified[pl.name]):
			raise FulfillmentError("STALE_PL", f"Pick List '{pl.name}' modified timestamp mismatch.")
	for pl_name in expected_modified:
		if pl_name not in pl_docs:
			raise FulfillmentError("STALE_PL", f"Pick List '{pl_name}' does not belong to this Run.")

	# Zero pick check: any draft PL with custom_picked_qty <= 0 fails
	for pl in draft_pls:
		for loc in pl.locations:
			picked = flt(getattr(loc, "custom_picked_qty", 0))
			if picked <= 0:
				raise FulfillmentError(
					"PICKED_QTY_ZERO_UNSUPPORTED",
					f"Untouched or zero picked row found: {loc.name} in Pick List {pl.name}.",
				)

	# Short-pick blocker check across all active PLs
	all_rows = []
	for pl in pl_docs.values():
		for loc in pl.locations:
			all_rows.append({
				"pick_list": pl.name,
				"row": loc.name,
				"item_code": loc.item_code,
				"qty": flt(loc.qty),
				"custom_picked_qty": flt(getattr(loc, "custom_picked_qty", 0)),
			})
	short = short_rows(all_rows)
	if short and short_pick_reason:
		reason_text = str(short_pick_reason).strip() or "Stok fisik di gudang tidak mencukupi"
		run_doc.short_pick_reason = reason_text
		run_doc.short_pick_status = "Approved"
		run_doc.short_pick_fingerprint = short_fingerprint(short)
		run_doc.short_pick_requested_by = actor
		run_doc.short_pick_approved_by = actor
		run_doc.short_pick_approved_on = frappe.utils.now_datetime()
		run_doc.save()
		blocker = None
	else:
		blocker = finish_blocker(
			short,
			bool(run_doc.short_pick_approval_required_snapshot),
			run_doc.short_pick_status,
			run_doc.short_pick_fingerprint,
		)
	if blocker:
		raise FulfillmentError(blocker, f"Short pick blocked: {blocker}")

	# Submit each draft PL
	try:
		for pl in draft_pls:
			if pl.scan_mode != 0:
				pl.scan_mode = 0
				pl.save()
			pl.submit()
	except FulfillmentError:
		frappe.db.rollback()
		raise
	except Exception as exc:
		frappe.db.rollback()
		raise FulfillmentError("NATIVE_ERROR", str(exc))

	# Advance Run status if all active PLs are now submitted
	all_submitted = all(
		frappe.db.get_value("Pick List", name, "docstatus") == 1
		for name in run_pl_names
	)
	if all_submitted:
		run_doc.status = "PICKED"
		run_doc.save()

	return get_run_workspace(run)


def submit_pick_list(
	run: str,
	group: str,
	expected_pl_modified: str | None = None,
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

	if run_doc.delivery_note:
		raise FulfillmentError("DN_EXISTS", "Run already has a Delivery Note.")

	group_clean = (group or "").strip().lower()
	if group_clean == "dry":
		pl_name = run_doc.dry_pick_list
	elif group_clean == "frozen":
		pl_name = run_doc.frozen_pick_list
	else:
		raise FulfillmentError("WRONG_PL_ROW", f"Invalid group '{group}'. Must be 'dry' or 'frozen'.")

	if not pl_name:
		raise FulfillmentError("PL_NOT_DRAFT", f"Run has no {group_clean} Pick List.")

	pl_doc = frappe.get_doc("Pick List", pl_name)
	if pl_doc.custom_fulfillment_run != run_doc.name:
		raise FulfillmentError("WRONG_PL_ROW", f"Pick List '{pl_name}' does not belong to this Run.")

	if pl_doc.docstatus != 0:
		raise FulfillmentError("PL_NOT_DRAFT", f"Pick List '{pl_name}' is not in draft status.")

	if expected_pl_modified and str(pl_doc.modified) != str(expected_pl_modified):
		raise FulfillmentError("STALE_PL", f"Pick List '{pl_name}' modified timestamp mismatch.")

	for loc in pl_doc.locations:
		picked = flt(getattr(loc, "custom_picked_qty", 0))
		if picked <= 0:
			raise FulfillmentError(
				"PICKED_QTY_ZERO_UNSUPPORTED",
				f"Untouched or zero picked row found: {loc.name} in Pick List {pl_doc.name}.",
			)

	pl_rows = [
		{
			"pick_list": pl_doc.name,
			"row": loc.name,
			"item_code": loc.item_code,
			"qty": flt(loc.qty),
			"custom_picked_qty": flt(getattr(loc, "custom_picked_qty", 0)),
		}
		for loc in pl_doc.locations
	]
	if short_rows(pl_rows):
		run_pl_names = [pl for pl in (run_doc.dry_pick_list, run_doc.frozen_pick_list) if pl]
		all_rows = []
		for name in run_pl_names:
			p = frappe.get_doc("Pick List", name)
			for loc in p.locations:
				all_rows.append({
					"pick_list": p.name,
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

	try:
		if pl_doc.scan_mode != 0:
			pl_doc.scan_mode = 0
			pl_doc.save()
		pl_doc.submit()
	except FulfillmentError:
		frappe.db.rollback()
		raise
	except Exception as exc:
		frappe.db.rollback()
		raise FulfillmentError("NATIVE_ERROR", str(exc))

	run_pl_names = [pl for pl in (run_doc.dry_pick_list, run_doc.frozen_pick_list) if pl]
	all_submitted = all(
		frappe.db.get_value("Pick List", name, "docstatus") == 1
		for name in run_pl_names
	)
	if all_submitted:
		run_doc.status = "PICKED"
		run_doc.save()

	return get_run_workspace(run)

