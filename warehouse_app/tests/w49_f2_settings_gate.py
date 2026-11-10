# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""F2 Settings API gate: permissions, revision, stale write, options."""

from __future__ import annotations

import json

import frappe

from warehouse_app.tests.w49_f1_fixture import COMPANY, PROFILE, guard_site

STOCK_EMAIL = "zztest-w49-settings-stock@example.com"
PICK_FORMAT = "ZZTEST-W49 Settings Pick Format"
OTHER_FORMAT = "ZZTEST-W49 Settings Other Format"


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

	user = None
	try:
		_ensure_formats()
		frappe.db.commit()
		from warehouse_app.warehouse_app.fulfillment.settings_api import (
			fulfillment_settings_options,
			get_fulfillment_settings,
			save_fulfillment_settings,
		)

		settings = get_fulfillment_settings(COMPANY)
		check("read_company", settings["company"] == COMPANY, settings["company"])
		check("read_profile", bool(settings["profile"]), settings["profile"] and settings["profile"]["name"])
		check("can_edit_admin", settings["can_edit"] is True, settings["can_edit"])
		check("profile_fields", "config_revision" in settings["profile"], settings["profile"].keys())

		current = settings["profile"]
		old_modified = current["modified"]
		payload = {
			"company": COMPANY,
			"expected_modified": old_modified,
			"dry_display_name": "Dry Test",
		}
		saved = save_fulfillment_settings(json.dumps(payload))
		check("save_revision", saved["profile"]["config_revision"] == current["config_revision"] + 1, saved["profile"]["config_revision"])
		check("save_display", saved["profile"]["dry_display_name"] == "Dry Test", saved["profile"]["dry_display_name"])

		stale = {
			"company": COMPANY,
			"expected_modified": old_modified,
			"dry_display_name": "Should Not Save",
		}
		check("stale_modified_rejected", _save_error(save_fulfillment_settings, stale), "ValidationError")
		check(
			"stale_did_not_change",
			get_fulfillment_settings(COMPANY)["profile"]["dry_display_name"] == "Dry Test",
			get_fulfillment_settings(COMPANY)["profile"]["dry_display_name"],
		)

		mismatch = {
			"company": COMPANY,
			"expected_revision": int(saved["profile"]["config_revision"]) + 1,
			"dry_display_name": "Should Not Save",
		}
		check("stale_revision_rejected", _save_error(save_fulfillment_settings, mismatch), "ValidationError")

		unknown = {
			"company": COMPANY,
			"expected_modified": get_fulfillment_settings(COMPANY)["profile"]["modified"],
			"bogus_field": "x",
		}
		check("unknown_field_rejected", _save_error(save_fulfillment_settings, unknown), "ValidationError")

		options = fulfillment_settings_options(COMPANY)
		check("warehouse_scope", all(row["company"] == COMPANY for row in options["warehouses"]), len(options["warehouses"]))
		check("print_format_scope", any(row["name"] == PICK_FORMAT for row in options["print_formats"]), [row["name"] for row in options["print_formats"]])
		check("print_format_excludes_other", all(row["doc_type"] == "Pick List" for row in options["print_formats"]), [row["doc_type"] for row in options["print_formats"]])
		check("roles_present", any(row["name"] == "Stock User" for row in options["roles"]), len(options["roles"]))

		user = _create_stock_user()
		frappe.set_user(user)
		try:
			stock_settings = get_fulfillment_settings(COMPANY)
			check("stock_user_read", stock_settings["can_edit"] is False, stock_settings["can_edit"])
			error = _error_type(
				save_fulfillment_settings,
				{"company": COMPANY, "dry_display_name": "Nope"},
			)
			check("stock_user_save_rejected", error == "PermissionError", error)
		finally:
			frappe.set_user("Administrator")

		save_fulfillment_settings(
			{
				"company": COMPANY,
				"expected_modified": get_fulfillment_settings(COMPANY)["profile"]["modified"],
				"dry_display_name": "Dry",
				"frozen_display_name": "Frozen",
			}
		)
		check(
			"profile_restored",
			get_fulfillment_settings(COMPANY)["profile"]["dry_display_name"] == "Dry",
			get_fulfillment_settings(COMPANY)["profile"]["dry_display_name"],
		)
	except Exception as exc:
		ok = False
		checks["exception"] = f"{type(exc).__name__}: {exc}"
		frappe.log_error(frappe.get_traceback(), "W49 F2 settings gate")
	finally:
		frappe.set_user("Administrator")
		_cleanup_user(user)
		_cleanup_formats()
		frappe.db.commit()

	print("GATE_JSON:" + json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, default=str))


def _save_error(fn, payload) -> bool:
	return _error_type(fn, payload) is not None


def _error_type(fn, payload):
	try:
		fn(payload)
		return None
	except Exception as exc:
		return type(exc).__name__


def _create_stock_user() -> str:
	_cleanup_user(STOCK_EMAIL)
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": STOCK_EMAIL,
			"first_name": "W49 Settings Stock",
			"send_welcome_email": 0,
		}
	).insert(ignore_permissions=True)
	user.add_roles("Stock User")
	user.save(ignore_permissions=True)
	frappe.db.commit()
	return user.name


def _cleanup_user(email) -> None:
	if not email or not frappe.db.exists("User", email):
		return
	frappe.delete_doc("User", email, force=1, ignore_permissions=True, ignore_missing=True)
	frappe.db.delete("Sessions", {"user": email})
	frappe.db.delete("Activity Log", {"user": email})
	if frappe.db.has_column("Activity Log", "for_user"):
		frappe.db.delete("Activity Log", {"for_user": email})


def _ensure_formats() -> None:
	for name, doc_type in ((PICK_FORMAT, "Pick List"), (OTHER_FORMAT, "Sales Invoice")):
		if not frappe.db.exists("Print Format", name):
			frappe.get_doc(
				{
					"doctype": "Print Format",
					"name": name,
					"doc_type": doc_type,
					"standard": "No",
					"custom_format": 1,
					"print_format_type": "Jinja",
					"html": "<div>ZZTEST W49 settings</div>",
				}
			).insert(ignore_permissions=True)


def _cleanup_formats() -> None:
	for name in (PICK_FORMAT, OTHER_FORMAT):
		if frappe.db.exists("Print Format", name):
			frappe.delete_doc("Print Format", name, force=1, ignore_permissions=True, ignore_missing=True)
