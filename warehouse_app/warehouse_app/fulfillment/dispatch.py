# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""Dispatch service: submit Delivery Note natively and finalize Fulfillment Run."""

from __future__ import annotations

import json
import frappe
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
REQUEST_TYPE = "SubmitDeliveryNote"


def submit_delivery_note(
	run: str,
	idempotency_key: str,
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

	if not idempotency_key:
		raise FulfillmentError("IDEMPOTENCY_KEY_REQUIRED", "Idempotency key is required.")

	if not run or not frappe.db.exists(RUN, run):
		raise FulfillmentError("RUN_NOT_FOUND", "Fulfillment Run does not exist.")

	run_doc = frappe.get_doc(RUN, run)

	if not frappe.has_permission("Company", doc=run_doc.company, ptype="read"):
		raise frappe.PermissionError

	if run_doc.status == "DISPATCHED":
		return get_run_workspace(run)

	if not run_doc.delivery_note:
		raise FulfillmentError("DN_NOT_FOUND", "Fulfillment Run has no Delivery Note.")

	if not frappe.db.exists("Delivery Note", run_doc.delivery_note):
		raise FulfillmentError("DN_NOT_FOUND", "Delivery Note does not exist.")

	dn = frappe.get_doc("Delivery Note", run_doc.delivery_note)

	if dn.docstatus == 1:
		if run_doc.status != "DISPATCHED":
			run_doc.status = "DISPATCHED"
			if not run_doc.dispatched_at:
				run_doc.dispatched_at = now_datetime()
			run_doc.save()
			frappe.db.commit()
		return get_run_workspace(run)

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

	profile = None
	if run_doc.profile and frappe.db.exists("Warehouse Fulfillment Profile", run_doc.profile):
		profile = frappe.get_doc("Warehouse Fulfillment Profile", run_doc.profile)

	enable_packing_slip = True
	require_all_packed = True
	if profile:
		if getattr(profile, "enable_packing_slip", None) is not None:
			enable_packing_slip = bool(profile.enable_packing_slip)
		if getattr(profile, "require_all_packed", None) is not None:
			require_all_packed = bool(profile.require_all_packed)
	elif run_doc.policy_snapshot:
		try:
			snap = json.loads(run_doc.policy_snapshot)
			if "enable_packing_slip" in snap:
				enable_packing_slip = bool(snap.get("enable_packing_slip"))
			if "require_all_packed" in snap:
				require_all_packed = bool(snap.get("require_all_packed"))
		except Exception:
			pass

	if enable_packing_slip and require_all_packed:
		if not dn.items or not all(flt(item.packed_qty) >= flt(item.qty) for item in dn.items):
			submitted_slips = frappe.get_all(
				"Packing Slip",
				filters={"delivery_note": dn.name, "docstatus": 1},
				pluck="name",
			)
			if submitted_slips:
				for ps_name in submitted_slips:
					ps_doc = frappe.get_doc("Packing Slip", ps_name)
					ps_doc.update_prevdoc_status()
				dn.reload()

			if not dn.items or not all(flt(item.packed_qty) >= flt(item.qty) for item in dn.items):
				raise FulfillmentError(
					"DN_NOT_FULLY_PACKED",
					"All Delivery Note items must be packed before submit.",
				)

	payload = {
		"run": run_doc.name,
		"dn": dn.name,
		"modified": str(dn.modified),
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
			"A delivery note submit request is already in progress.",
		)
	if state == "replay":
		return get_run_workspace(run)

	try:
		dn.submit()
		dn.reload()
		if dn.docstatus != 1:
			raise FulfillmentError(
				"DELIVERY_NOTE_SUBMIT_FAILED",
				"Delivery Note submit did not complete.",
			)

		run_doc.status = "DISPATCHED"
		run_doc.dispatched_at = now_datetime()
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
