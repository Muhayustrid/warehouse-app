# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""F1 read-only API gate. Never mutates seeded native documents."""

from __future__ import annotations

import json

import frappe

from warehouse_app.tests.w49_f1_fixture import (
	COMPANY,
	PROFILE,
	verify_seed,
)

TEMP_EMAIL = "zztest-w49-noperm@example.com"
TEMP_RESTRICTED_EMAIL = "zztest-w49-restricted@example.com"


def run_gate() -> None:
	checks: dict[str, str] = {}
	ok = True
	user = None
	restricted_user = None
	profile = None

	def check(name: str, passed: bool, evidence: object) -> None:
		nonlocal ok
		if not passed:
			ok = False
			checks[name] = f"FAIL: {evidence}"
		else:
			checks[name] = str(evidence)

	def cleanup() -> None:
		frappe.set_user("Administrator")
		if profile:
			profile.reload()
			if not profile.enabled:
				profile.enabled = 1
				profile.save(ignore_permissions=True)
		for email in (user, restricted_user):
			if not email or not frappe.db.exists("User", email):
				continue
			for permission in frappe.get_all(
				"User Permission", filters={"user": email}, pluck="name"
			):
				frappe.delete_doc(
					"User Permission",
					permission,
					force=1,
					ignore_permissions=True,
					ignore_missing=True,
				)
			frappe.delete_doc("User", email, force=1, ignore_permissions=True, ignore_missing=True)
			frappe.db.delete("Sessions", {"user": email})
			frappe.db.delete("Activity Log", {"user": email})
			if frappe.db.has_column("Activity Log", "for_user"):
				frappe.db.delete("Activity Log", {"for_user": email})
		frappe.db.commit()

	try:
		try:
			from warehouse_app.warehouse_app.fulfillment.api import (
				get_order_preview,
				get_order_queue,
			)
		except Exception as exc:
			check("endpoint_available", False, exc)
			print(
				"GATE_JSON:"
				+ json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, default=str)
			)
			return

		seeded = verify_seed()
		states = seeded["states"]
		check("seed_has_four_states", len(states) == 4, states)
		if len(states) != 4:
			return

		profile_name = frappe.db.get_value(PROFILE, {"company": COMPANY}, "name")
		profile = frappe.get_doc(PROFILE, profile_name) if profile_name else None
		check("profile_available", bool(profile and profile.enabled), profile_name)
		if not profile or not profile.enabled:
			return

		q = get_order_queue(search="ZZTEST-W49 Customer")
		check("queue_rows", len(q["rows"]) == 4, len(q["rows"]))
		check("queue_counts", q["counts"]["all"] == 4, q["counts"])
		check("queue_profile", q["profile"]["configured"] is True, q["profile"])
		check("queue_stage_counts", q["counts"]["open"] == 1 and q["counts"]["picking"] == 1 and q["counts"]["packing"] == 1 and q["counts"]["ready"] == 1, q["counts"])
		by_so = {row["sales_order"]: row for row in q["rows"]}
		check("row_open", by_so[states["ZZTEST-W49-SO-OPEN"]]["stage"] == "open", by_so[states["ZZTEST-W49-SO-OPEN"]]["stage"])
		check("row_picking", by_so[states["ZZTEST-W49-SO-PICKING"]]["stage"] == "picking", by_so[states["ZZTEST-W49-SO-PICKING"]]["stage"])
		check("row_packing", by_so[states["ZZTEST-W49-SO-PACKING"]]["stage"] == "packing", by_so[states["ZZTEST-W49-SO-PACKING"]]["stage"])
		check("row_ready", by_so[states["ZZTEST-W49-SO-READY"]]["stage"] == "ready", by_so[states["ZZTEST-W49-SO-READY"]]["stage"])
		check(
			"queue_group_counts",
			all(row["dry_count"] == 1 and row["frozen_count"] == 1 and row["unclassified_count"] == 0 for row in q["rows"]),
			[(row["dry_count"], row["frozen_count"], row["unclassified_count"]) for row in q["rows"]],
		)
		check(
			"queue_documents",
			by_so[states["ZZTEST-W49-SO-READY"]]["pick_lists"]["submitted"] == 1
			and by_so[states["ZZTEST-W49-SO-READY"]]["delivery_notes"]["draft"] == 1
			and by_so[states["ZZTEST-W49-SO-READY"]]["packing_slips"]["submitted"] == 1,
			by_so[states["ZZTEST-W49-SO-READY"]],
		)

		date_q = get_order_queue(
			search="ZZTEST-W49 Customer",
			from_date="2000-01-01",
			to_date="2000-01-02",
		)
		check("date_filter_empty", date_q["rows"] == [], len(date_q["rows"]))
		stage_q = get_order_queue(search="ZZTEST-W49 Customer", stage="picking")
		check("stage_filter", len(stage_q["rows"]) == 1 and stage_q["rows"][0]["stage"] == "picking", stage_q["rows"])
		page_q = get_order_queue(search="ZZTEST-W49 Customer", page=1, page_length=2)
		check("pagination", len(page_q["rows"]) == 2 and page_q["total"] == 4, (len(page_q["rows"]), page_q["total"]))

		preview = get_order_preview(states["ZZTEST-W49-SO-READY"])
		check("preview_stage", preview["stage"] == "ready", preview["stage"])
		check("preview_groups", len(preview["groups"]["dry"]) == 1 and len(preview["groups"]["frozen"]) == 1, preview["groups"])
		check("preview_documents", len(preview["documents"]["pick_lists"]) == 1 and len(preview["documents"]["delivery_notes"]) == 1 and len(preview["documents"]["packing_slips"]) == 1, preview["documents"])

		before = _snapshot(states)
		get_order_queue(search="ZZTEST-W49 Customer")
		get_order_preview(states["ZZTEST-W49-SO-READY"])
		after = _snapshot(states)
		check("no_writes", before == after, (before, after))

		try:
			get_order_preview("ZZTEST-W49-NO-SUCH-SO")
			check("unknown_so_rejected", False, "no error")
		except frappe.DoesNotExistError:
			check("unknown_so_rejected", True, "DoesNotExistError")

		profile.enabled = 0
		profile.save(ignore_permissions=True)
		disabled = get_order_queue(search="ZZTEST-W49 Customer")
		check("disabled_profile", disabled["profile"]["configured"] is False and disabled["counts"]["exception"] == 4, disabled["profile"])
		profile.reload()
		profile.enabled = 1
		profile.save(ignore_permissions=True)

		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": TEMP_EMAIL,
				"first_name": "W49 No Permission",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True).name
		frappe.set_user(user)
		try:
			get_order_queue(search="ZZTEST-W49 Customer")
			check("no_role_rejected", False, "queue succeeded")
		except frappe.PermissionError:
			check("no_role_rejected", True, "PermissionError")
		finally:
			frappe.set_user("Administrator")

		restricted_user = frappe.get_doc(
			{
				"doctype": "User",
				"email": TEMP_RESTRICTED_EMAIL,
				"first_name": "W49 Restricted",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True).name
		restricted_doc = frappe.get_doc("User", restricted_user)
		restricted_doc.add_roles("Stock User")
		restricted_doc.save(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": restricted_user,
				"allow": "Sales Order",
				"for_value": states["ZZTEST-W49-SO-OPEN"],
				"apply_to_all_doctypes": 0,
			}
		).insert(ignore_permissions=True)
		frappe.set_user(restricted_user)
		try:
			restricted_q = get_order_queue(search="ZZTEST-W49 Customer")
			check(
				"restricted_so_queue",
				len(restricted_q["rows"]) == 1
				and restricted_q["rows"][0]["sales_order"] == states["ZZTEST-W49-SO-OPEN"],
				restricted_q["rows"],
			)
			try:
				get_order_preview(states["ZZTEST-W49-SO-READY"])
				check("restricted_preview_rejected", False, "preview succeeded")
			except frappe.PermissionError:
				check("restricted_preview_rejected", True, "PermissionError")
		finally:
			frappe.set_user("Administrator")
	finally:
		cleanup()

	print("GATE_JSON:" + json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, default=str))


def _snapshot(states: dict[str, str]) -> dict[str, object]:
	names = list(states.values())
	return {
		"sales_orders": {
			name: str(frappe.db.get_value("Sales Order", name, "modified")) for name in names
		},
		"counts": {
			doctype: frappe.db.count(doctype, {"customer": "ZZTEST-W49 Customer"})
			if doctype == "Sales Order"
			else frappe.db.count(doctype)
			for doctype in ("Sales Order", "Pick List", "Delivery Note", "Packing Slip")
		},
	}
