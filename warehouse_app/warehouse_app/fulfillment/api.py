# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""Whitelisted read-only F1 fulfillment endpoints."""

from __future__ import annotations

import json

import frappe

from warehouse_app.warehouse_app.fulfillment.approval import (
	approve_short_pick as _approve_short_pick,
	reject_short_pick as _reject_short_pick,
	request_short_pick_approval as _request_short_pick_approval,
)
from warehouse_app.warehouse_app.fulfillment.delivery import (
	create_delivery_note as _create_delivery_note,
	update_delivery_packages as _update_delivery_packages,
)
from warehouse_app.warehouse_app.doctype.delivery_manifest.delivery_manifest import (
	get_manifest as _get_manifest,
	get_manifests as _get_manifests,
	manifest_candidates as _manifest_candidates,
	save_manifest as _save_manifest,
)
from warehouse_app.warehouse_app.fulfillment.dispatch import (
	submit_delivery_note as _submit_delivery_note,
)
from warehouse_app.warehouse_app.fulfillment.generate import (
	FulfillmentError,
	generate_fulfillment_run as _generate_fulfillment_run,
)
from warehouse_app.warehouse_app.fulfillment.loader import (
	load_order_preview,
	load_order_queue,
)
from warehouse_app.warehouse_app.fulfillment.packing import (
	pack_all as _pack_all,
	reset_packing as _reset_packing,
)
from warehouse_app.warehouse_app.fulfillment.picking import (
	complete_picking as _complete_picking,
	save_picking as _save_picking,
	submit_pick_list as _submit_pick_list,
)
from warehouse_app.warehouse_app.fulfillment.packing_slip_page import (
	load_packing_slip,
	load_packing_slips,
	packing_slip_labels_html,
	packing_slip_print_html,
	save_packing_slip,
)
from warehouse_app.warehouse_app.fulfillment.permissions import (
	require_manifest_write,
	require_read,
)
from warehouse_app.warehouse_app.fulfillment.settings_api import (
	fulfillment_settings_options as _fulfillment_settings_options,
)
from warehouse_app.warehouse_app.fulfillment.settings_api import (
	get_fulfillment_settings as _get_fulfillment_settings,
)
from warehouse_app.warehouse_app.fulfillment.settings_api import (
	save_fulfillment_settings as _save_fulfillment_settings,
)
from warehouse_app.warehouse_app.fulfillment.workspace import (
	get_run_workspace as _get_run_workspace,
)


@frappe.whitelist(methods=["GET"])
def get_order_queue(
	company=None,
	search=None,
	stage=None,
	stages=None,
	from_date=None,
	to_date=None,
	page=1,
	page_length=20,
):
	return load_order_queue(
		company=company,
		search=search,
		stage=stage,
		stages=stages,
		from_date=from_date,
		to_date=to_date,
		page=page,
		page_length=page_length,
	)


@frappe.whitelist(methods=["GET"])
def get_order_preview(sales_order):
	return load_order_preview(sales_order)


@frappe.whitelist(methods=["GET"])
def get_fulfillment_settings(company=None):
	return _get_fulfillment_settings(company=company)


@frappe.whitelist(methods=["POST"])
def save_fulfillment_settings(payload=None):
	return _save_fulfillment_settings(payload=payload)


@frappe.whitelist(methods=["GET"])
def fulfillment_settings_options(company=None):
	return _fulfillment_settings_options(company=company)


@frappe.whitelist(methods=["POST"])
def generate_fulfillment_run(sales_order, idempotency_key, expected_so_modified):
	try:
		return _generate_fulfillment_run(
			sales_order=sales_order,
			idempotency_key=idempotency_key,
			expected_so_modified=expected_so_modified,
		)
	except FulfillmentError as exc:
		frappe.throw(f"{exc.code}: {exc.message}", frappe.ValidationError)


@frappe.whitelist(methods=["GET"])
def get_run_workspace(run):
	try:
		return _get_run_workspace(run)
	except FulfillmentError as exc:
		frappe.throw(f"{exc.code}: {exc.message}", frappe.ValidationError)


@frappe.whitelist(methods=["POST"])
def save_picking(run, rows=None, expected_modified=None):
	if isinstance(rows, str):
		try:
			rows = json.loads(rows)
		except ValueError:
			frappe.throw("Invalid rows payload.", frappe.ValidationError)
	if isinstance(expected_modified, str):
		try:
			expected_modified = json.loads(expected_modified)
		except ValueError:
			frappe.throw("Invalid expected_modified payload.", frappe.ValidationError)
	try:
		return _save_picking(
			run=run,
			rows=rows if rows is not None else [],
			expected_modified=expected_modified if expected_modified is not None else {},
		)
	except FulfillmentError as exc:
		frappe.throw(f"{exc.code}: {exc.message}", frappe.ValidationError)


@frappe.whitelist(methods=["POST"])
def request_short_pick_approval(run, reason=None):
	try:
		return _request_short_pick_approval(run=run, reason=reason)
	except FulfillmentError as exc:
		frappe.throw(f"{exc.code}: {exc.message}", frappe.ValidationError)


@frappe.whitelist(methods=["POST"])
def approve_short_pick(run, expected_fingerprint=None):
	try:
		return _approve_short_pick(run=run, expected_fingerprint=expected_fingerprint)
	except FulfillmentError as exc:
		frappe.throw(f"{exc.code}: {exc.message}", frappe.ValidationError)


@frappe.whitelist(methods=["POST"])
def reject_short_pick(run, reason=None):
	try:
		return _reject_short_pick(run=run, reason=reason)
	except FulfillmentError as exc:
		frappe.throw(f"{exc.code}: {exc.message}", frappe.ValidationError)


@frappe.whitelist(methods=["POST"])
def complete_picking(run, expected_modified=None, short_pick_reason=None):
	if isinstance(expected_modified, str):
		try:
			expected_modified = json.loads(expected_modified)
		except ValueError:
			frappe.throw("STALE_PL: Invalid expected_modified payload.", frappe.ValidationError)
	try:
		return _complete_picking(
			run=run,
			expected_modified=expected_modified if expected_modified is not None else {},
			actor=frappe.session.user,
			short_pick_reason=short_pick_reason,
		)
	except FulfillmentError as exc:
		frappe.throw(f"{exc.code}: {exc.message}", frappe.ValidationError)


@frappe.whitelist(methods=["POST"])
def submit_pick_list(run, group=None, expected_pl_modified=None):
	try:
		return _submit_pick_list(
			run=run,
			group=group,
			expected_pl_modified=expected_pl_modified,
			actor=frappe.session.user,
		)
	except FulfillmentError as exc:
		frappe.throw(f"{exc.code}: {exc.message}", frappe.ValidationError)


@frappe.whitelist(methods=["POST"])
def create_delivery_note(run, idempotency_key=None, dry_packages=None, frozen_packages=None):
	try:
		return _create_delivery_note(
			run=run,
			idempotency_key=idempotency_key,
			actor=frappe.session.user,
			dry_packages=dry_packages,
			frozen_packages=frozen_packages,
		)
	except FulfillmentError as exc:
		frappe.throw(f"{exc.code}: {exc.message}", frappe.ValidationError)


@frappe.whitelist(methods=["POST"])
def update_delivery_packages(run, dry_packages=None, frozen_packages=None):
	try:
		return _update_delivery_packages(
			run=run,
			dry_packages=dry_packages,
			frozen_packages=frozen_packages,
			actor=frappe.session.user,
		)
	except FulfillmentError as exc:
		frappe.throw(f"{exc.code}: {exc.message}", frappe.ValidationError)


@frappe.whitelist(methods=["POST"])
def pack_all(run, expected_dn_modified=None, dry_packages=None, frozen_packages=None, custom_slips=None):
	try:
		return _pack_all(
			run=run,
			expected_dn_modified=expected_dn_modified,
			actor=frappe.session.user,
			dry_packages=dry_packages,
			frozen_packages=frozen_packages,
			custom_slips=custom_slips,
		)
	except FulfillmentError as exc:
		frappe.throw(f"{exc.code}: {exc.message}", frappe.ValidationError)


@frappe.whitelist(methods=["POST"])
def reset_packing(run, expected_dn_modified=None):
	try:
		return _reset_packing(
			run=run,
			expected_dn_modified=expected_dn_modified,
			actor=frappe.session.user,
		)
	except FulfillmentError as exc:
		frappe.throw(f"{exc.code}: {exc.message}", frappe.ValidationError)


@frappe.whitelist(methods=["POST"])
def submit_delivery_note(run, idempotency_key=None, expected_dn_modified=None):
	try:
		return _submit_delivery_note(
			run=run,
			idempotency_key=idempotency_key,
			expected_dn_modified=expected_dn_modified,
			actor=frappe.session.user,
		)
	except FulfillmentError as exc:
		frappe.throw(f"{exc.code}: {exc.message}", frappe.ValidationError)


@frappe.whitelist(methods=["GET"])
def get_combined_pick_list_html(company=None, delivery_date=None):
	from warehouse_app.warehouse_app.fulfillment.pick_print import (
		_pick_list_html,
		load_combined_pick_rows,
	)

	require_read()
	if not delivery_date:
		frappe.throw("Delivery date is required.", frappe.ValidationError)
	company = company or frappe.defaults.get_user_default("Company")
	if not company:
		frappe.throw("Company is required.", frappe.ValidationError)
	if not frappe.has_permission("Company", doc=company, ptype="read"):
		raise frappe.PermissionError
	rows = load_combined_pick_rows(company, delivery_date)
	return _pick_list_html(rows, delivery_date, company)


@frappe.whitelist(methods=["GET"])
def get_delivery_summary_html(company=None, delivery_date=None):
	from warehouse_app.warehouse_app.fulfillment.pick_print import (
		_delivery_summary_html,
		load_delivery_summary_rows,
	)

	require_read()
	if not delivery_date:
		frappe.throw("Delivery date is required.", frappe.ValidationError)
	company = company or frappe.defaults.get_user_default("Company")
	if not company:
		frappe.throw("Company is required.", frappe.ValidationError)
	if not frappe.has_permission("Company", doc=company, ptype="read"):
		raise frappe.PermissionError
	customers = load_delivery_summary_rows(company, delivery_date)
	return _delivery_summary_html(customers, delivery_date, company)


@frappe.whitelist(methods=["GET"])
def get_packing_slips_print_html(delivery_note):
	if not delivery_note:
		return ""
	slips = frappe.get_all(
		"Packing Slip",
		filters={"delivery_note": delivery_note, "docstatus": 1},
		order_by="from_case_no asc",
		pluck="name",
	)
	if not slips:
		return ""

	template_html = frappe.db.get_value("Print Format", "Format Print Packing Slip", "html") or ""
	pages = []
	for name in slips:
		doc = frappe.get_doc("Packing Slip", name)
		if template_html:
			rendered = frappe.render_template(template_html, {"doc": doc, "frappe": frappe})
		else:
			rendered = frappe.get_print("Packing Slip", name)
		pages.append(f'<div class="ps-print-sheet">{rendered}</div>')

	return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Packing Slips - {delivery_note}</title>
<style>
@page {{
    size: A4 portrait;
    margin: 10mm;
}}
body {{
    margin: 0;
    padding: 15px;
    background: #f1f5f9;
    font-family: Arial, sans-serif;
}}
.ps-print-sheet {{
    background: #ffffff;
    max-width: 800px;
    margin: 0 auto 30px auto;
    padding: 24px;
    border-radius: 6px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}}
@media print {{
    body {{
        background: transparent !important;
        padding: 0 !important;
    }}
    .ps-print-sheet {{
        box-shadow: none !important;
        border-radius: 0 !important;
        padding: 0 !important;
        margin: 0 !important;
        page-break-after: always;
        break-after: page;
    }}
    .ps-print-sheet:last-child {{
        page-break-after: avoid;
        break-after: avoid;
    }}
}}
</style>
</head>
<body>
{''.join(pages)}
</body>
</html>"""


@frappe.whitelist(methods=["GET"])
def get_manifest_candidates(company=None, delivery_date=None):
	if not delivery_date:
		frappe.throw("Delivery date is required.", frappe.ValidationError)
	require_read()
	company = company or frappe.defaults.get_user_default("Company")
	if not company:
		frappe.throw("Company is required.", frappe.ValidationError)
	return _manifest_candidates(company=company, delivery_date=delivery_date)


@frappe.whitelist(methods=["POST"])
def save_delivery_manifest(payload=None):
	require_manifest_write()
	if isinstance(payload, str):
		try:
			payload = json.loads(payload)
		except ValueError:
			frappe.throw("Invalid payload.", frappe.ValidationError)
	if not isinstance(payload, dict):
		frappe.throw("Payload is required.", frappe.ValidationError)
	return _save_manifest(payload)


@frappe.whitelist(methods=["GET"])
def get_manifests(company=None, delivery_date=None):
	require_read()
	if not delivery_date:
		frappe.throw("Delivery date is required.", frappe.ValidationError)
	company = company or frappe.defaults.get_user_default("Company")
	if not company:
		frappe.throw("Company is required.", frappe.ValidationError)
	return _get_manifests(company=company, delivery_date=delivery_date)


@frappe.whitelist(methods=["GET"])
def get_manifest(name=None):
	require_read()
	if not name:
		frappe.throw("Manifest name is required.", frappe.ValidationError)
	return _get_manifest(name=name)


@frappe.whitelist(methods=["GET"])
def get_packing_slips(company=None, from_date=None, to_date=None):
	require_read()
	company = company or frappe.defaults.get_user_default("Company")
	if not company:
		frappe.throw("Company is required.", frappe.ValidationError)
	return load_packing_slips(company, from_date or "", to_date or "")


@frappe.whitelist(methods=["GET"])
def get_packing_slip(name=None):
	if not name:
		frappe.throw("Packing Slip name is required.", frappe.ValidationError)
	return load_packing_slip(name)


@frappe.whitelist(methods=["POST"])
def save_packing_slip(name=None, lines=None):
	if not name:
		frappe.throw("Packing Slip name is required.", frappe.ValidationError)
	return save_packing_slip(name, lines)


@frappe.whitelist(methods=["GET"])
def get_packing_slip_print_html(name=None):
	if not name:
		frappe.throw("Packing Slip name is required.", frappe.ValidationError)
	return packing_slip_print_html(name)


@frappe.whitelist(methods=["GET"])
def get_packing_slip_labels_html(name=None):
	if not name:
		frappe.throw("Packing Slip name is required.", frappe.ValidationError)
	return packing_slip_labels_html(name)


