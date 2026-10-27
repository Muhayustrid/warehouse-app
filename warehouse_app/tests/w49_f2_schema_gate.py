# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""F2 schema gate for Run, Request Key, and optional Pick List lineage fields."""

from __future__ import annotations

import json

import frappe

from warehouse_app.tests.w49_f1_fixture import COMPANY, PROFILE, guard_site

RUN = "Warehouse Fulfillment Run"
RUN_ITEM = "Warehouse Fulfillment Run Item"
ALLOCATION = "Warehouse Fulfillment Run Allocation"
KEY = "Warehouse Fulfillment Request Key"


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

	run = None
	key = None
	try:
		doctypes = (RUN, RUN_ITEM, ALLOCATION, KEY)
		check("doctypes", all(frappe.db.exists("DocType", dt) for dt in doctypes), doctypes)

		run_meta = frappe.get_meta(RUN)
		required_run_fields = {
			"company",
			"sales_order",
			"customer",
			"profile",
			"profile_revision",
			"frozen_item_group_snapshot",
			"include_child_groups_snapshot",
			"policy_snapshot",
			"status",
			"dry_pick_list",
			"frozen_pick_list",
			"items",
			"allocations",
			"active_so_key",
			"request_key",
			"run_revision",
			"error_code",
			"error_message",
		}
		check(
			"run_fields",
			required_run_fields.issubset({df.fieldname for df in run_meta.fields}),
			sorted(required_run_fields - {df.fieldname for df in run_meta.fields}),
		)
		check("active_so_key_unique", bool(run_meta.get_field("active_so_key").unique), run_meta.get_field("active_so_key").unique)
		check(
			"run_child_tables",
			run_meta.get_field("items").options == RUN_ITEM
			and run_meta.get_field("allocations").options == ALLOCATION,
			{
				"items": run_meta.get_field("items").options,
				"allocations": run_meta.get_field("allocations").options,
			},
		)

		check("run_item_child", frappe.get_meta(RUN_ITEM).istable == 1, frappe.get_meta(RUN_ITEM).istable)
		check("allocation_child", frappe.get_meta(ALLOCATION).istable == 1, frappe.get_meta(ALLOCATION).istable)
		check(
			"run_item_groups",
			set(frappe.get_meta(RUN_ITEM).get_field("picking_group").options.split("\n")) == {"dry", "frozen"},
			frappe.get_meta(RUN_ITEM).get_field("picking_group").options,
		)
		check("scope_key_unique", bool(frappe.get_meta(KEY).get_field("scope_key").unique), frappe.get_meta(KEY).get_field("scope_key").unique)

		for dt, role, create, write in (
			(RUN, "Stock Manager", 1, 1),
			(RUN, "Stock User", 0, 0),
			(KEY, "Stock Manager", 1, 1),
			(KEY, "Stock User", 0, 0),
			(RUN, "System Manager", 1, 1),
		):
			rows = frappe.get_all(
				"DocPerm",
				filters={"parent": dt, "role": role},
				fields=["create", "read", "write"],
				limit=1,
			)
			perm = rows[0] if rows else {}
			check(
				f"perm_{dt}_{role}",
				int(perm.get("create") or 0) == create
				and int(perm.get("write") or 0) == write
				and int(perm.get("read") or 0) == 1,
				perm,
			)

		pl_meta = frappe.get_meta("Pick List")
		run_field = pl_meta.get_field("custom_fulfillment_run")
		group_field = pl_meta.get_field("custom_fulfillment_group")
		check(
			"pl_custom_fields",
			bool(run_field)
			and run_field.fieldtype == "Link"
			and run_field.options == RUN
			and bool(group_field)
			and group_field.fieldtype == "Select"
			and set(group_field.options.split("\n")) == {"Dry", "Frozen"}
			and not run_field.reqd
			and not group_field.reqd,
			{
				"run": run_field and run_field.options,
				"group": group_field and group_field.options,
				"run_reqd": run_field and run_field.reqd,
				"group_reqd": group_field and group_field.reqd,
			},
		)
		check(
			"w31_field_intact",
			bool(frappe.get_meta("Pick List Item").get_field("custom_picked_qty")),
			bool(frappe.get_meta("Pick List Item").get_field("custom_picked_qty")),
		)

		profile_name = frappe.db.get_value(PROFILE, {"company": COMPANY}, "name")
		so_name = frappe.db.get_value("Sales Order", {"company": COMPANY}, "name")
		check("fixture_profile", bool(profile_name), profile_name)
		check("fixture_so", bool(so_name), so_name)
		if profile_name and so_name:
			run = frappe.get_doc(
				{
					"doctype": RUN,
					"company": COMPANY,
					"sales_order": so_name,
					"profile": profile_name,
					"status": "PLANNING",
					"active_so_key": "ZZTEST-W49-SCHEMA-ACTIVE",
				}
			).insert(ignore_permissions=True)
			frappe.db.commit()
			check("run_insert", bool(run.name), run.name)

			key = frappe.get_doc(
				{
					"doctype": KEY,
					"scope_key": "ZZTEST-W49-SCHEMA-SCOPE",
					"status": "PENDING",
				}
			).insert(ignore_permissions=True)
			frappe.db.commit()
			check("key_insert", bool(key.name), key.name)

			try:
				frappe.get_doc(
					{
						"doctype": RUN,
						"company": COMPANY,
						"sales_order": so_name,
						"profile": profile_name,
						"status": "PLANNING",
						"active_so_key": "ZZTEST-W49-SCHEMA-ACTIVE",
					}
				).insert(ignore_permissions=True)
				check("active_so_key_duplicate_rejected", False, "duplicate inserted")
			except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
				check("active_so_key_duplicate_rejected", True, "unique constraint")
			frappe.db.rollback()

			try:
				frappe.get_doc(
					{
						"doctype": KEY,
						"scope_key": "ZZTEST-W49-SCHEMA-SCOPE",
						"status": "PENDING",
					}
				).insert(ignore_permissions=True)
				check("scope_key_duplicate_rejected", False, "duplicate inserted")
			except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
				check("scope_key_duplicate_rejected", True, "unique constraint")
			frappe.db.rollback()

			profile = frappe.get_doc(PROFILE, profile_name)
			profile.company = "ZZTEST-W49-SCHEMA-NO-COMPANY"
			try:
				# Exercise the controller guard without a second Company fixture.
				# A real save would be rejected by link validation first.
				profile.run_method("validate")
				check("company_change_blocked", False, "company changed")
			except frappe.ValidationError as exc:
				check("company_change_blocked", "Company cannot be changed" in str(exc), str(exc))
			finally:
				frappe.db.rollback()
	except Exception as exc:
		ok = False
		checks["exception"] = f"{type(exc).__name__}: {exc}"
		frappe.log_error(frappe.get_traceback(), "W49 F2 schema gate")
	finally:
		frappe.db.rollback()
		for doctype, name in ((RUN, run and run.name), (KEY, key and key.name)):
			if name and frappe.db.exists(doctype, name):
				frappe.delete_doc(doctype, name, force=1, ignore_permissions=True, ignore_missing=True)
		frappe.db.commit()

	print("GATE_JSON:" + json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, default=str))
