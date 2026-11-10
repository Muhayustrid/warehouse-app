# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""W54 schema gate: Run fields, native lineage fields, and policy snapshot."""

from __future__ import annotations

import json

import frappe

from warehouse_app.tests.w49_f1_fixture import COMPANY, PROFILE, guard_site
from warehouse_app.tests.w49_f2_fixture import SO_MARKERS, cleanup_r0, seed_r0
from warehouse_app.warehouse_app.fulfillment.generate import generate_fulfillment_run
from warehouse_app import upgrade

RUN = "Warehouse Fulfillment Run"
KEY = "Warehouse Fulfillment Request Key"
NEW_RUN_FIELDS = (
	"delivery_note",
	"short_pick_approval_required_snapshot",
	"short_pick_status",
	"short_pick_reason",
	"short_pick_rejection_reason",
	"short_pick_fingerprint",
	"short_pick_requested_by",
	"short_pick_requested_on",
	"short_pick_approved_by",
	"short_pick_approved_on",
	"dn_created_at",
	"dispatched_at",
)
STATUS_OPTIONS = (
	"PLANNING",
	"PICKING",
	"PICKED",
	"DN_DRAFT",
	"PACKING",
	"READY",
	"DISPATCHED",
	"NEEDS_RECONCILIATION",
)
SHORT_STATUS_OPTIONS = ("None", "Pending", "Approved", "Rejected")


def run_gate() -> None:
	guard_site()
	checks: dict[str, str] = {}
	ok = True
	so_names: list[str] = []
	profile = None
	original_policy = None

	def check(name: str, passed: bool, evidence: object) -> None:
		nonlocal ok
		if not passed:
			ok = False
			checks[name] = f"FAIL: {evidence}"
		else:
			checks[name] = str(evidence)

	try:
		meta = frappe.get_meta(RUN)
		missing = [name for name in NEW_RUN_FIELDS if not meta.get_field(name)]
		check("run_fields", not missing, missing or "all present")

		status_field = meta.get_field("status")
		status_values = set((status_field.options or "").splitlines()) if status_field else set()
		check(
			"status_options",
			status_values == set(STATUS_OPTIONS),
			sorted(status_values),
		)

		short_field = meta.get_field("short_pick_status")
		check(
			"run_short_status",
			bool(short_field)
			and short_field.fieldtype == "Select"
			and set((short_field.options or "").splitlines()) == set(SHORT_STATUS_OPTIONS)
			and (short_field.default or "") == "None",
			{
				"options": short_field and short_field.options,
				"default": short_field and short_field.default,
			},
		)

		check("run_delivery_note", bool(meta.get_field("delivery_note")), "delivery_note")
		check(
			"run_short_snapshot",
			bool(meta.get_field("short_pick_approval_required_snapshot")),
			"short_pick_approval_required_snapshot",
		)

		for dt, name in (("Delivery Note", "dn_lineage"), ("Packing Slip", "ps_lineage")):
			field = frappe.get_meta(dt).get_field("custom_fulfillment_run")
			check(
				name,
				bool(field)
				and field.fieldtype == "Link"
				and field.options == RUN
				and bool(field.read_only),
				{
					"type": field and field.fieldtype,
					"options": field and field.options,
					"read_only": field and field.read_only,
				},
			)

		profile = frappe.get_doc(PROFILE, frappe.db.get_value(PROFILE, {"company": COMPANY}, "name"))
		original_policy = int(profile.short_pick_approval_required or 0)
		data = seed_r0()

		# Policy 1 differs from the Check default, so a deleted assignment in
		# _create_run() cannot pass by falling back to 0.
		profile.reload()
		profile.short_pick_approval_required = 1
		profile.save(ignore_permissions=True)
		frappe.db.commit()
		dry_so = frappe.get_doc("Sales Order", data["sales_orders"]["dry"])
		dry_run = frappe.get_doc(RUN, _generate(dry_so, "ZZTEST-W54-SCHEMA-KEY-1")["run"])
		check(
			"generated_snapshot_required",
			dry_run.short_pick_approval_required_snapshot == 1,
			dry_run.short_pick_approval_required_snapshot,
		)

		# Policy 0 must land as an explicit zero, never as a missing value.
		profile.reload()
		profile.short_pick_approval_required = 0
		profile.save(ignore_permissions=True)
		frappe.db.commit()
		frozen_so = frappe.get_doc("Sales Order", data["sales_orders"]["frozen"])
		frozen_run = frappe.get_doc(RUN, _generate(frozen_so, "ZZTEST-W54-SCHEMA-KEY-0")["run"])
		check(
			"generated_snapshot_optional",
			frozen_run.short_pick_approval_required_snapshot is not None
			and int(frozen_run.short_pick_approval_required_snapshot) == 0,
			frozen_run.short_pick_approval_required_snapshot,
		)
		check("generated_status_default", dry_run.short_pick_status == "None", dry_run.short_pick_status)

		# Backfill: PLANNING + snapshot 0 follows the profile; reviewed runs are kept.
		profile.reload()
		profile.short_pick_approval_required = 1
		profile.save(ignore_permissions=True)
		frappe.db.commit()
		backfill_run = _make_run(dry_so.name, "ZZTEST-W54-BACKFILL", "PLANNING", "None")
		reviewed_run = _make_run(dry_so.name, "ZZTEST-W54-REVIEWED", "PICKED", "Approved")
		result_text = upgrade.backfill_run_short_pick_snapshot()
		check(
			"backfill_planning",
			int(frappe.db.get_value(RUN, backfill_run, "short_pick_approval_required_snapshot") or 0) == 1,
			{"result": result_text, "run": backfill_run},
		)
		check(
			"backfill_skips_reviewed",
			int(frappe.db.get_value(RUN, reviewed_run, "short_pick_approval_required_snapshot") or 0) == 0,
			reviewed_run,
		)
	except Exception as exc:
		ok = False
		checks["exception"] = f"{type(exc).__name__}: {exc}"
		frappe.log_error(frappe.get_traceback(), "W54 schema gate")
	finally:
		if profile and original_policy is not None:
			profile.reload()
			profile.short_pick_approval_required = original_policy
			profile.save(ignore_permissions=True)
		# Marker-based: also finds fixture documents when seed_r0() died halfway.
		so_names = list(
			dict.fromkeys(
				so_names
				+ frappe.get_all(
					"Sales Order",
					filters={"po_no": ("in", list(SO_MARKERS.values()))},
					pluck="name",
				)
			)
		)
		for name in frappe.get_all(RUN, filters={"sales_order": ("in", so_names)}, pluck="name"):
			frappe.delete_doc(RUN, name, force=1, ignore_permissions=True, ignore_missing=True)
		for name in frappe.get_all(KEY, filters={"sales_order": ("in", so_names)}, pluck="name"):
			frappe.delete_doc(KEY, name, force=1, ignore_permissions=True, ignore_missing=True)
		frappe.db.commit()
		try:
			cleanup_r0()
		except Exception as exc:
			ok = False
			checks["teardown_cleanup"] = f"FAIL: {type(exc).__name__}: {exc}"
		residual = len(frappe.get_all(RUN, filters={"sales_order": ("in", so_names)}, pluck="name"))
		residual += len(
			frappe.get_all(RUN, filters={"active_so_key": ("like", "ZZTEST-W%")}, pluck="name")
		)
		residual += len(frappe.get_all(KEY, filters={"sales_order": ("in", so_names)}, pluck="name"))
		residual += len(
			frappe.get_all(
				"Sales Order",
				filters={"po_no": ("like", "ZZTEST-W49-R0-%")},
				pluck="name",
			)
		)
		check("teardown_runs", residual == 0, residual)

	print("GATE_JSON:" + json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, default=str))


def _generate(so, idempotency_key: str) -> dict:
	return generate_fulfillment_run(
		sales_order=so.name,
		idempotency_key=idempotency_key,
		expected_so_modified=str(so.modified),
		actor="Administrator",
	)


def _make_run(sales_order: str, active_so_key: str, status: str, short_status: str) -> str:
	profile = frappe.db.get_value(PROFILE, {"company": COMPANY}, "name")
	run = frappe.get_doc(
		{
			"doctype": RUN,
			"company": COMPANY,
			"sales_order": sales_order,
			"profile": profile,
			"status": status,
			"short_pick_status": short_status,
			"short_pick_approval_required_snapshot": 0,
			"active_so_key": active_so_key,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	return run.name
