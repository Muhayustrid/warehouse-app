# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""F2 Profile schema and validation gate. Uses the disposable site only."""

from __future__ import annotations

import json

import frappe

from warehouse_app.tests.w49_f1_fixture import (
	COMPANY,
	FROZEN_CHILD,
	FROZEN_PARENT,
	PROFILE,
	WAREHOUSE,
	guard_site,
)

PICK_FORMAT = "ZZTEST-W49 Profile Pick Format"
OTHER_FORMAT = "ZZTEST-W49 Profile Other Format"
VALID_ROLE = "Stock User"
ALL_FIELDS = {
	"enabled": 1,
	"frozen_item_group": FROZEN_CHILD,
	"dry_display_name": "Dry",
	"frozen_display_name": "Frozen",
	"include_child_item_groups": 1,
	"dry_parent_warehouse": WAREHOUSE,
	"frozen_parent_warehouse": WAREHOUSE,
	"print_paper_size": "A4",
	"dry_print_copies": 1,
	"frozen_print_copies": 1,
	"allow_partial_delivery": 0,
	"short_pick_approval_required": 1,
	"require_all_packed": 1,
	"require_checker_approval": 1,
	"allow_cross_group_packing": 0,
	"allow_draft_print": 1,
	"barcode_mode_enabled": 0,
	"minimum_shelf_life_days": 0,
	"role_order_coordinator": "Stock Manager",
	"role_picker_dry": VALID_ROLE,
	"role_picker_frozen": VALID_ROLE,
	"role_packer": VALID_ROLE,
	"role_checker": VALID_ROLE,
	"role_dispatch": VALID_ROLE,
}


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
		_ensure_formats()
		frappe.db.commit()
		pick_format = PICK_FORMAT
		other_format = OTHER_FORMAT
		existing = frappe.db.get_value(PROFILE, {"company": COMPANY}, "name")
		if existing:
			frappe.delete_doc(PROFILE, existing, force=1, ignore_permissions=True)

		payload = {
			"doctype": PROFILE,
			"company": COMPANY,
			"dry_print_format": pick_format,
			"frozen_print_format": pick_format,
			**ALL_FIELDS,
		}
		payload["config_revision"] = 99  # server must ignore client input
		doc = frappe.get_doc(payload).insert(ignore_permissions=True)
		frappe.db.commit()
		check("new_revision", doc.config_revision == 1, doc.config_revision)
		check("all_fields_saved", doc.frozen_display_name == "Frozen", doc.frozen_display_name)

		doc.save(ignore_permissions=True)
		frappe.db.commit()
		check("revision_increments", doc.config_revision == 2, doc.config_revision)

		doc.dry_display_name = ""
		check("blank_display_rejected", _save_error(doc), "ValidationError")
		doc.reload()

		doc.enabled = 1
		doc.frozen_item_group = None
		check("enabled_requires_frozen", _save_error(doc), "ValidationError")
		doc.reload()

		doc.frozen_item_group = FROZEN_PARENT
		doc.include_child_item_groups = 0
		check("parent_without_children_rejected", _save_error(doc), "ValidationError")
		doc.reload()

		doc.dry_print_format = other_format
		check("wrong_print_format_rejected", _save_error(doc), "ValidationError")
		doc.reload()

		doc.role_picker_dry = "ZZTEST-W49 No Such Role"
		check("unknown_role_rejected", _save_error(doc), "ValidationError")
		doc.reload()

		doc.dry_parent_warehouse = "ZZTEST-W49 No Such Warehouse"
		check("unknown_warehouse_rejected", _save_error(doc), "ValidationError")
		doc.reload()

		doc.config_revision = 99
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		check("revision_not_client_controlled", doc.config_revision == 3, doc.config_revision)
		doc.reload()

		try:
			frappe.get_doc(
				{
					"doctype": PROFILE,
					"company": COMPANY,
					"enabled": 0,
				}
			).insert(ignore_permissions=True)
			check("duplicate_company_rejected", False, "duplicate inserted")
		except (frappe.ValidationError, frappe.DuplicateEntryError):
			check("duplicate_company_rejected", True, "validation/duplicate error")
		finally:
			frappe.db.rollback()

		doc.reload()
		doc.enabled = 1
		doc.frozen_item_group = FROZEN_CHILD
		doc.include_child_item_groups = 1
		doc.dry_display_name = "Dry"
		doc.dry_print_format = pick_format
		doc.role_picker_dry = VALID_ROLE
		doc.dry_parent_warehouse = WAREHOUSE
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		check("profile_restored", doc.enabled == 1, doc.name)
	except Exception as exc:
		ok = False
		checks["exception"] = f"{type(exc).__name__}: {exc}"
		frappe.log_error(frappe.get_traceback(), "W49 F2 profile gate")
	finally:
		_ensure_profile()
		_cleanup_formats()
		frappe.db.commit()

	print("GATE_JSON:" + json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, default=str))


def _save_error(doc) -> bool:
	try:
		doc.save(ignore_permissions=True)
		return False
	except frappe.ValidationError:
		frappe.db.rollback()
		return True
	except frappe.DuplicateEntryError:
		frappe.db.rollback()
		return True


def _ensure_formats() -> None:
	for name, doc_type in ((PICK_FORMAT, "Pick List"), (OTHER_FORMAT, "Sales Invoice")):
		if frappe.db.exists("Print Format", name):
			continue
		frappe.get_doc(
			{
				"doctype": "Print Format",
				"name": name,
				"doc_type": doc_type,
				"standard": "No",
				"custom_format": 1,
				"print_format_type": "Jinja",
				"html": "<div>ZZTEST W49 format</div>",
			}
		).insert(ignore_permissions=True)


def _cleanup_formats() -> None:
	for name in (PICK_FORMAT, OTHER_FORMAT):
		if frappe.db.exists("Print Format", name):
			frappe.delete_doc("Print Format", name, force=1, ignore_permissions=True, ignore_missing=True)


def _ensure_profile() -> None:
	existing = frappe.db.get_value(PROFILE, {"company": COMPANY}, "name")
	if existing:
		doc = frappe.get_doc(PROFILE, existing)
		if not doc.meta.has_field("dry_display_name"):
			return
		doc.enabled = 1
		doc.frozen_item_group = FROZEN_CHILD
		doc.include_child_item_groups = 1
		doc.dry_display_name = doc.get("dry_display_name") or "Dry"
		doc.frozen_display_name = doc.get("frozen_display_name") or "Frozen"
		doc.dry_print_format = None
		doc.frozen_print_format = None
		doc.save(ignore_permissions=True)
		return
	frappe.get_doc(
		{
			"doctype": PROFILE,
			"company": COMPANY,
			"enabled": 1,
			"frozen_item_group": FROZEN_CHILD,
			"include_child_item_groups": 1,
			"dry_display_name": "Dry",
			"frozen_display_name": "Frozen",
		}
	).insert(ignore_permissions=True)
