# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""F1 profile gate. Read-only except for the disposable profile record."""

from __future__ import annotations

import json

import frappe

from warehouse_app.tests.w49_f1_fixture import (
	COMPANY,
	FROZEN_CHILD,
	FROZEN_PARENT,
	guard_site,
)

PROFILE = "Warehouse Fulfillment Profile"


def run_gate():
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

	def cleanup() -> None:
		for name in frappe.get_all(PROFILE, filters={"company": COMPANY}, pluck="name"):
			try:
				frappe.delete_doc(PROFILE, name, force=1, ignore_permissions=True)
			except Exception:
				frappe.db.rollback()
		frappe.db.commit()

	if not frappe.db.exists("DocType", PROFILE):
		check("doctype_exists", False, "DocType is missing")
		print("GATE_JSON:" + json.dumps({"ok": False, "checks": checks}, ensure_ascii=False))
		return

	cleanup()
	try:
		profile = frappe.get_doc(
			{
				"doctype": PROFILE,
				"company": COMPANY,
				"enabled": 1,
				"frozen_item_group": FROZEN_PARENT,
				"include_child_item_groups": 1,
			}
		).insert(ignore_permissions=True)
		check("valid_profile_saved", True, profile.name)

		check("leaf_child_exists", frappe.db.exists("Item Group", FROZEN_CHILD), FROZEN_CHILD)

		try:
			frappe.get_doc(
				{
					"doctype": PROFILE,
					"company": COMPANY,
					"enabled": 1,
					"frozen_item_group": FROZEN_PARENT,
					"include_child_item_groups": 1,
				}
			).insert(ignore_permissions=True)
			check("duplicate_company_rejected", False, "duplicate profile was saved")
		except (frappe.ValidationError, frappe.DuplicateEntryError):
			check("duplicate_company_rejected", True, "validation/duplicate error")

		profile.reload()
		profile.include_child_item_groups = 0
		try:
			profile.save(ignore_permissions=True)
			check("parent_without_children_rejected", False, "invalid profile was saved")
		except frappe.ValidationError:
			check("parent_without_children_rejected", True, "ValidationError")
		finally:
			frappe.db.rollback()
	finally:
		cleanup()

	print("GATE_JSON:" + json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False))
