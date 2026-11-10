# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""Short-pick request, approval, and rejection services."""

from __future__ import annotations

import frappe
from frappe.utils import flt

from warehouse_app.warehouse_app.fulfillment.generate import FulfillmentError
from warehouse_app.warehouse_app.fulfillment.permissions import (
	has_approver_roles,
	has_write_roles,
	require_approver,
	require_write,
)
from warehouse_app.warehouse_app.fulfillment.short_pick import short_fingerprint, short_rows
from warehouse_app.warehouse_app.fulfillment.workspace import get_run_workspace

RUN = "Warehouse Fulfillment Run"


def _check_run_access(run: str):
	if not run or not frappe.db.exists(RUN, run):
		raise FulfillmentError("RUN_NOT_FOUND", "Fulfillment Run does not exist.")
	run_doc = frappe.get_doc(RUN, run)
	if not frappe.has_permission("Company", doc=run_doc.company, ptype="read"):
		raise frappe.PermissionError
	return run_doc


def _current_short_rows(run_doc) -> list[dict]:
	run_pl_names = [pl for pl in (run_doc.dry_pick_list, run_doc.frozen_pick_list) if pl]
	if not run_pl_names:
		return []
	pl_docs = [frappe.get_doc("Pick List", name) for name in run_pl_names]
	all_rows = []
	for pl_doc in pl_docs:
		for loc in pl_doc.locations:
			all_rows.append(
				{
					"pick_list": pl_doc.name,
					"row": loc.name,
					"item_code": loc.item_code,
					"qty": flt(loc.qty),
					"custom_picked_qty": flt(getattr(loc, "custom_picked_qty", 0)),
				}
			)
	return short_rows(all_rows)


def request_short_pick_approval(run: str, reason: str, actor: str | None = None) -> dict:
	actor = actor or frappe.session.user
	if actor and actor != frappe.session.user:
		roles = set(frappe.get_roles(actor))
		if not has_write_roles(roles):
			raise frappe.PermissionError("Fulfillment writes require System Manager or paired stock roles.")
	else:
		require_write()

	run_doc = _check_run_access(run)

	if not run_doc.short_pick_approval_required_snapshot:
		raise FulfillmentError(
			"SHORT_PICK_APPROVAL_NOT_REQUIRED",
			"Short pick approval is not enabled for this run.",
		)

	if not reason or not isinstance(reason, str) or not reason.strip():
		raise FulfillmentError("SHORT_PICK_REASON_REQUIRED", "Reason is required.")

	if run_doc.short_pick_status == "Approved":
		raise FulfillmentError("SHORT_PICK_ALREADY_APPROVED", "Short pick is already approved.")

	current_short = _current_short_rows(run_doc)
	if not current_short:
		raise FulfillmentError("SHORT_PICK_NOT_SHORT", "No short pick rows found.")

	run_doc.short_pick_status = "Pending"
	run_doc.short_pick_reason = reason.strip()
	run_doc.short_pick_fingerprint = short_fingerprint(current_short)
	run_doc.short_pick_requested_by = actor
	run_doc.short_pick_requested_on = frappe.utils.now_datetime()
	run_doc.short_pick_rejection_reason = ""
	run_doc.save()

	return get_run_workspace(run)


def approve_short_pick(run: str, expected_fingerprint: str, actor: str | None = None) -> dict:
	actor = actor or frappe.session.user
	if actor and actor != frappe.session.user:
		roles = set(frappe.get_roles(actor))
		if not has_approver_roles(roles):
			raise frappe.PermissionError("Short-pick approval requires System Manager or paired stock roles.")
	else:
		require_approver()

	run_doc = _check_run_access(run)

	if run_doc.short_pick_status != "Pending":
		raise FulfillmentError("SHORT_PICK_NOT_PENDING", "Short pick approval is not pending.")

	current_short = _current_short_rows(run_doc)
	current_fp = short_fingerprint(current_short)
	if (
		not expected_fingerprint
		or expected_fingerprint != run_doc.short_pick_fingerprint
		or expected_fingerprint != current_fp
	):
		raise FulfillmentError(
			"SHORT_PICK_STALE_APPROVAL",
			"Short pick quantities changed. Please review again.",
		)

	run_doc.short_pick_status = "Approved"
	run_doc.short_pick_approved_by = actor
	run_doc.short_pick_approved_on = frappe.utils.now_datetime()
	run_doc.save()

	return get_run_workspace(run)


def reject_short_pick(run: str, reason: str, actor: str | None = None) -> dict:
	actor = actor or frappe.session.user
	if actor and actor != frappe.session.user:
		roles = set(frappe.get_roles(actor))
		if not has_approver_roles(roles):
			raise frappe.PermissionError("Short-pick approval requires System Manager or paired stock roles.")
	else:
		require_approver()

	run_doc = _check_run_access(run)

	if run_doc.short_pick_status != "Pending":
		raise FulfillmentError("SHORT_PICK_NOT_PENDING", "Short pick approval is not pending.")

	if not reason or not isinstance(reason, str) or not reason.strip():
		raise FulfillmentError("SHORT_PICK_REASON_REQUIRED", "Rejection reason is required.")

	run_doc.short_pick_status = "Rejected"
	run_doc.short_pick_rejection_reason = reason.strip()
	run_doc.short_pick_approved_by = ""
	run_doc.short_pick_approved_on = None
	run_doc.save()

	return get_run_workspace(run)
