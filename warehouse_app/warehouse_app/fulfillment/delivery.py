# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""Delivery service: create one native draft Delivery Note from submitted Pick Lists."""

from __future__ import annotations

import frappe
from erpnext.stock.doctype.pick_list.pick_list import create_dn_for_pick_lists
from frappe.utils import flt, now_datetime

from warehouse_app.warehouse_app.fulfillment.generate import FulfillmentError
from warehouse_app.warehouse_app.fulfillment.idempotency import (
	begin_request,
	complete_request,
	fail_request,
	request_hash_payload,
)
from warehouse_app.warehouse_app.fulfillment.permissions import (
	has_write_roles,
	require_write,
)
from warehouse_app.warehouse_app.fulfillment.short_pick import (
	finish_blocker,
	short_rows,
)
from warehouse_app.warehouse_app.fulfillment.workspace import get_run_workspace

RUN = "Warehouse Fulfillment Run"
REQUEST_TYPE = "CreateDeliveryNote"


def create_delivery_note(
	run: str,
	idempotency_key: str,
	actor: str | None = None,
	dry_packages: int | str | None = None,
	frozen_packages: int | str | None = None,
) -> dict:
	actor = actor or frappe.session.user
	if actor and actor != frappe.session.user:
		roles = set(frappe.get_roles(actor))
		if not has_write_roles(roles):
			raise frappe.PermissionError("Fulfillment writes require System Manager or paired stock roles.")
	else:
		require_write()

	if not idempotency_key:
		raise FulfillmentError("IDEMPOTENCY_KEY_REQUIRED", "Idempotency key is required.")

	if not run or not frappe.db.exists(RUN, run):
		raise FulfillmentError("RUN_NOT_FOUND", "Fulfillment Run does not exist.")

	run_doc = frappe.get_doc(RUN, run)

	if not frappe.has_permission("Company", doc=run_doc.company, ptype="read"):
		raise frappe.PermissionError

	if run_doc.delivery_note:
		return get_run_workspace(run)

	run_pls = [pl for pl in (run_doc.dry_pick_list, run_doc.frozen_pick_list) if pl]
	if not run_pls:
		raise FulfillmentError("PICKING_NOT_COMPLETE", "Finish picking before creating a Delivery Note.")

	for pl_name in run_pls:
		if frappe.db.get_value("Pick List", pl_name, "docstatus") != 1:
			raise FulfillmentError("PICKING_NOT_COMPLETE", "Finish picking before creating a Delivery Note.")

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

	payload = {
		"run": run_doc.name,
		"pls": sorted([pl for pl in [run_doc.dry_pick_list, run_doc.frozen_pick_list] if pl]),
	}
	hash_value = request_hash_payload(payload, REQUEST_TYPE)
	request = begin_request(
		actor,
		run_doc.company,
		run_doc.sales_order,
		REQUEST_TYPE,
		idempotency_key,
		hash_value,
	)

	scope = request["scope"]
	state = request["state"]

	if state == "mismatch":
		raise FulfillmentError(
			"IDEMPOTENCY_MISMATCH",
			"This request key was used with a different payload.",
		)
	if state == "in_progress":
		raise FulfillmentError(
			"REQUEST_IN_PROGRESS",
			"A delivery note request is already in progress.",
		)
	if state == "replay":
		return get_run_workspace(run)

	try:
		first_pl = run_doc.dry_pick_list or run_doc.frozen_pick_list
		second_pl = run_doc.frozen_pick_list if run_doc.dry_pick_list else None

		dn = create_dn_for_pick_lists(first_pl)
		if second_pl:
			dn = create_dn_for_pick_lists(second_pl, target_doc=dn)

		dn.custom_fulfillment_run = run_doc.name

		def _parse_pkg_num(val):
			if val is None or str(val).strip() == "":
				return None
			try:
				return max(0, int(val))
			except (ValueError, TypeError):
				return None

		parsed_dry = _parse_pkg_num(dry_packages)
		parsed_frozen = _parse_pkg_num(frozen_packages)
		if parsed_dry is not None:
			dn.custom_dry_packages = parsed_dry
		if parsed_frozen is not None:
			dn.custom_frozen_packages = parsed_frozen
		if getattr(dn, "custom_dry_packages", None) is not None or getattr(dn, "custom_frozen_packages", None) is not None:
			dn.custom_total_packages = (getattr(dn, "custom_dry_packages", 0) or 0) + (getattr(dn, "custom_frozen_packages", 0) or 0)

		if not getattr(dn, "name", None):
			dn.insert()
		else:
			dn.save()

		if dn.docstatus != 0:
			raise FulfillmentError("DELIVERY_NOTE_CREATION_FAILED", "Delivery Note is not in draft status.")

		dn_pls = {item.against_pick_list for item in dn.items if item.against_pick_list}
		for pl in run_pls:
			if pl not in dn_pls:
				raise FulfillmentError(
					"DELIVERY_NOTE_CREATION_FAILED",
					f"Pick List '{pl}' missing from Delivery Note items.",
				)

		run_doc.delivery_note = dn.name
		run_doc.dn_created_at = now_datetime()
		run_doc.status = "DN_DRAFT"
		run_doc.save()

		complete_request(scope, [dn.name])
		frappe.db.commit()
		return get_run_workspace(run)
	except FulfillmentError as exc:
		frappe.db.rollback()
		fail_request(scope, exc.code, exc.message)
		raise
	except Exception as exc:
		frappe.db.rollback()
		fail_request(scope, "NATIVE_ERROR", str(exc))
		raise FulfillmentError("NATIVE_ERROR", str(exc)) from exc


def update_delivery_packages(
	run: str,
	dry_packages: int | str | None = None,
	frozen_packages: int | str | None = None,
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
	if not run_doc.delivery_note:
		raise FulfillmentError("DN_NOT_FOUND", "Fulfillment Run has no Delivery Note.")

	dn = frappe.get_doc("Delivery Note", run_doc.delivery_note)
	if dn.docstatus != 0:
		raise FulfillmentError("DN_NOT_DRAFT", "Delivery Note is not in draft status.")

	def _parse_pkg_num(val):
		if val is None or str(val).strip() == "":
			return None
		try:
			return max(0, int(val))
		except (ValueError, TypeError):
			return None

	dn.custom_dry_packages = _parse_pkg_num(dry_packages)
	dn.custom_frozen_packages = _parse_pkg_num(frozen_packages)
	dry = dn.custom_dry_packages or 0
	frozen = dn.custom_frozen_packages or 0
	dn.custom_total_packages = (dry + frozen) if (dn.custom_dry_packages is not None or dn.custom_frozen_packages is not None) else None
	frappe.db.set_value(
		"Delivery Note",
		dn.name,
		{
			"custom_dry_packages": dn.custom_dry_packages,
			"custom_frozen_packages": dn.custom_frozen_packages,
			"custom_total_packages": dn.custom_total_packages,
		},
		update_modified=False,
	)
	frappe.db.commit()
	return get_run_workspace(run)

