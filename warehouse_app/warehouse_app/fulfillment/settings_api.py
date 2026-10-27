# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""F2 Profile settings read/write service for the existing SPA Settings page."""

from __future__ import annotations

import json

import frappe
from frappe import _

PROFILE = "Warehouse Fulfillment Profile"
READ_ROLES = {"System Manager", "Stock Manager", "Stock User"}
EDITABLE_FIELDS = (
	"company",
	"enabled",
	"frozen_item_group",
	"dry_display_name",
	"frozen_display_name",
	"include_child_item_groups",
	"dry_parent_warehouse",
	"frozen_parent_warehouse",
	"dry_print_format",
	"frozen_print_format",
	"print_paper_size",
	"dry_print_copies",
	"frozen_print_copies",
	"allow_partial_delivery",
	"short_pick_approval_required",
	"require_all_packed",
	"require_checker_approval",
	"allow_cross_group_packing",
	"allow_draft_print",
	"barcode_mode_enabled",
	"minimum_shelf_life_days",
	"role_order_coordinator",
	"role_picker_dry",
	"role_picker_frozen",
	"role_packer",
	"role_checker",
	"role_dispatch",
)
PROFILE_FIELDS = ("name", *EDITABLE_FIELDS, "config_revision", "modified")
SPECIAL_FIELDS = {"expected_modified", "expected_revision"}


def get_fulfillment_settings(company=None) -> dict:
	_require_read()
	company = _resolve_company(company)
	profile_name = frappe.db.get_value(PROFILE, {"company": company}, "name")
	profile = frappe.get_doc(PROFILE, profile_name) if profile_name else None
	return {
		"company": company,
		"companies": _readable_companies(),
		"profile": _serialize_profile(profile),
		"can_edit": _can_edit(),
	}


def save_fulfillment_settings(payload=None) -> dict:
	_require_write()
	payload = _parse_payload(payload)
	company = str(payload.get("company") or "").strip()
	if not company:
		frappe.throw(_("Company is required."))
	if company not in [row["name"] for row in _readable_companies()]:
		raise frappe.PermissionError

	profile_name = frappe.db.get_value(PROFILE, {"company": company}, "name")
	profile = frappe.get_doc(PROFILE, profile_name) if profile_name else frappe.get_doc(
		{"doctype": PROFILE, "company": company}
	)
	if not profile.is_new():
		if not payload.get("expected_modified") and payload.get("expected_revision") is None:
			frappe.throw(_("Reload the fulfillment profile before saving."), frappe.ValidationError)
		_assert_expected(profile, payload)
		if company != profile.company:
			frappe.throw(_("The profile Company cannot be changed."))

	for fieldname in EDITABLE_FIELDS:
		if fieldname == "company":
			continue
		if fieldname in payload:
			profile.set(fieldname, payload[fieldname])

	profile.save() if not profile.is_new() else profile.insert()
	frappe.db.commit()
	return {
		"ok": True,
		"company": company,
		"profile": _serialize_profile(profile),
		"can_edit": True,
	}


def fulfillment_settings_options(company=None) -> dict:
	_require_read()
	company = _resolve_company(company)
	return {
		"warehouses": frappe.get_list(
			"Warehouse",
			filters={"company": company, "disabled": 0},
			fields=["name", "warehouse_name", "is_group", "company"],
			order_by="name asc",
			limit_page_length=0,
		),
		"roles": frappe.get_all(
			"Role",
			filters={"disabled": 0},
			fields=["name"],
			order_by="name asc",
			limit=0,
		),
		"print_formats": frappe.get_all(
			"Print Format",
			filters={"doc_type": "Pick List"},
			fields=["name", "doc_type"],
			order_by="name asc",
			limit=0,
		),
	}


def _require_read() -> None:
	if not set(frappe.get_roles()).intersection(READ_ROLES):
		raise frappe.PermissionError


def _require_write() -> None:
	if "System Manager" not in frappe.get_roles():
		raise frappe.PermissionError


def _can_edit() -> bool:
	return "System Manager" in frappe.get_roles()


def _readable_companies() -> list[dict]:
	return frappe.get_list(
		"Company",
		fields=["name"],
		order_by="name asc",
		limit_page_length=0,
	)


def _resolve_company(company=None) -> str:
	companies = [row["name"] for row in _readable_companies()]
	if not companies:
		raise frappe.PermissionError
	company = (company or "").strip()
	if company:
		if company not in companies:
			raise frappe.PermissionError
		return company
	default = frappe.defaults.get_user_default("Company")
	if default in companies:
		return default
	return companies[0]


def _parse_payload(payload) -> dict:
	if isinstance(payload, str):
		try:
			payload = json.loads(payload)
		except ValueError:
			frappe.throw(_("Invalid fulfillment settings payload."))
	if not isinstance(payload, dict):
		frappe.throw(_("Invalid fulfillment settings payload."))
	unknown = set(payload) - set(EDITABLE_FIELDS) - SPECIAL_FIELDS
	if unknown:
		frappe.throw(_("Unknown fulfillment settings: {0}").format(", ".join(sorted(unknown))))
	return payload


def _assert_expected(profile, payload) -> None:
	expected_modified = payload.get("expected_modified")
	expected_revision = payload.get("expected_revision")
	if expected_modified and str(expected_modified) != str(profile.modified):
		frappe.throw(_("The fulfillment profile changed. Reload before saving."), frappe.ValidationError)
	if expected_revision is not None and int(expected_revision) != int(profile.config_revision or 0):
		frappe.throw(_("The fulfillment profile changed. Reload before saving."), frappe.ValidationError)


def _serialize_profile(profile) -> dict | None:
	if not profile:
		return None
	payload = {fieldname: profile.get(fieldname) for fieldname in PROFILE_FIELDS}
	payload["modified"] = str(profile.modified) if profile.modified else None
	return payload
