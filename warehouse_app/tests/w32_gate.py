# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto
# License: MIT

# Gate W32 — Basic Rate (as per UOM) jadi INPUT di Stock Entry + kolom native
# disembunyikan dari grid (basic_rate di SE; qty & valuation_rate di SR) via
# client script role-gate.
#
# Jalankan:
#   docker exec 1oktober2026-backend-1 bench --site 1oktober2026 execute \
#       warehouse_app.tests.w32_gate.run_gate
#
# Kontrak output: TEPAT satu baris GATE_JSON:{...} (ok: bool, checks: dict,
# error: opsional). Cek gagal -> ok=false TANPA raise; hanya crash tak terduga
# yang di-raise (bench exit nonzero).
#
# Yang diverifikasi (server-side; kolom hidden & lockstep live dibuktikan E2E
# browser):
#   1. Custom Field SE Detail read_only=0 (input sejak W32) + in_list_view=1.
#   2. Client Script SE memuat handler custom_basic_rate_per_uom +
#      set_column_disp("basic_rate", false); Client Script SR memuat
#      set_column_disp(["qty", "valuation_rate"], false); keduanya enabled.
#   3. SE Material Receipt 3 baris satu dokumen (aturan asimetris
#      compute_rate_per_uom):
#      (a) basic=0   custom=1200 -> basic_rate jadi 100  (custom men-drive);
#      (b) basic=100 custom=0    -> custom backfill 1200  (regresi W21);
#      (c) basic=100 custom=999  -> custom backfill 1200  (native menang bila
#          keduanya terisi tak konsisten).
#      + basic_amount row (a) = 24 x 100 (matematika native ikut rate hasil
#      konversi) + SLE diterima (sum actual_qty = 72).
#   4. Residu prefix = 0 (teardown cancel+delete SE, sweep SLE/Bin/Repost/
#      Item/Version).
#
# Fixture (prefix "ZZTEST-W32", TANPA user fixture): 1 Item; SE native naming
# di-track via daftar nama saat run. Teardown di finally.

import json
import traceback

import frappe
from frappe.utils import flt

from warehouse_app.tests.guard import count_residue, item_inventory_defaults
from warehouse_app.tests.w21_gate import _pick_item_group, _pick_uoms
from warehouse_app import upgrade
from warehouse_app.inventory_uom import SE_RATE_FIELD

PREFIX = "ZZTEST-W32"
TRACKED = {"se": [], "item": []}


class GateAborted(Exception):
	"""Prasyarat gate gagal; sisa langkah dilewati, GATE_JSON tetap dicetak (ok=false)."""


def run_gate():
	checks = {}
	error = None

	def check(name, ok, evidence):
		checks[name] = str(evidence) if ok else f"GAGAL: {evidence}"

	try:
		_run_gate(check)
	except GateAborted:
		pass
	except Exception:
		error = traceback.format_exc()
	finally:
		try:
			_teardown(check)
		except Exception as te:
			check("teardown", False, f"teardown error {type(te).__name__}: {te}")
		payload = {
			"ok": error is None and not any(v.startswith("GAGAL") for v in checks.values()),
			"checks": checks,
		}
		if error:
			payload["error"] = error[-2000:]
		print("GATE_JSON:" + json.dumps(payload, ensure_ascii=False))

	if error:
		raise SystemExit(1)


def _run_gate(check):
	check("pre_clean", *_sweep())

	stock, alt, invalid = _pick_uoms()
	item_group = _pick_item_group()
	company = (frappe.get_all("Company", pluck="name", limit=1) or [None])[0]
	warehouse = (
		frappe.get_all(
			"Warehouse", filters={"company": company, "is_group": 0, "disabled": 0},
			pluck="name", limit=1,
		)
		if company
		else []
	)
	warehouse = warehouse[0] if warehouse else None
	check(
		"preflight",
		bool(stock and alt and invalid and item_group and company and warehouse),
		f"stock={stock!r}, alt={alt!r}, company={company!r}, warehouse={warehouse!r}, "
		f"group={item_group!r}",
	)
	if not (stock and alt and item_group and company and warehouse):
		raise GateAborted()

	# --- Custom Field SE Detail: input + in_list_view ---
	row = frappe.db.get_value(
		"Custom Field", {"dt": "Stock Entry Detail", "fieldname": SE_RATE_FIELD},
		["read_only", "in_list_view"], as_dict=1,
	)
	check(
		"spec_input_field",
		bool(row and int(row.read_only or 0) == 0 and int(row.in_list_view or 0) == 1),
		f"read_only={getattr(row, 'read_only', None)!r} (want 0), "
		f"in_list_view={getattr(row, 'in_list_view', None)!r}",
	)

	# --- Client Script SE/SR membawa mekanik W32 & enabled ---
	se_script = frappe.db.get_value(
		"Client Script", {"dt": "Stock Entry", "script": ("like", "%" + upgrade.SCRIPT_MARKER + "%")},
		["script", "enabled"], as_dict=1,
	)
	check(
		"client_script_se_w32",
		bool(
			se_script
			and int(se_script.enabled or 0) == 1
			and 'custom_basic_rate_per_uom(frm' in se_script.script
			and 'set_column_disp("basic_rate", false)' in se_script.script
		),
		f"enabled={getattr(se_script, 'enabled', None)!r}, "
		f"handler={'custom_basic_rate_per_uom(frm' in (se_script.script if se_script else '')}, "
		f"hide={'set_column_disp(\"basic_rate\", false)' in (se_script.script if se_script else '')}",
	)
	sr_script = frappe.db.get_value(
		"Client Script",
		{"dt": "Stock Reconciliation", "script": ("like", "%" + upgrade.SR_SCRIPT_MARKER + "%")},
		["script", "enabled"], as_dict=1,
	)
	check(
		"client_script_sr_w32",
		bool(
			sr_script
			and int(sr_script.enabled or 0) == 1
			and 'set_column_disp(["qty", "valuation_rate"], false)' in sr_script.script
		),
		f"enabled={getattr(sr_script, 'enabled', None)!r}, "
		f"hide={'set_column_disp([\"qty\", \"valuation_rate\"], false)' in (sr_script.script if sr_script else '')}",
	)

	# --- SE 3 baris: aturan asimetris compute_rate_per_uom ---
	try:
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": PREFIX + "-" + frappe.generate_hash(length=8),
				"item_name": PREFIX + " Gate Item",
				"item_group": item_group,
				"stock_uom": stock,
				"is_stock_item": 1,
				"has_batch_no": 0,
				"has_serial_no": 0,
				"uoms": [{"uom": alt, "conversion_factor": 12}],
				"item_defaults": item_inventory_defaults(company),
			}
		)
		item.insert()
		TRACKED["item"].append(item.name)
		frappe.db.commit()

		def row(basic, custom):
			return {
				"item_code": item.name,
				"qty": 2,
				"uom": alt,
				"stock_uom": stock,
				"conversion_factor": 12,
				"basic_rate": basic,
				SE_RATE_FIELD: custom,
				"t_warehouse": warehouse,
			}

		se = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"company": company,
				"stock_entry_type": "Material Receipt",
				"purpose": "Material Receipt",
				"items": [row(0, 1200), row(100, 0), row(100, 999)],
			}
		)
		se.insert()
		se.submit()
		TRACKED["se"].append(se.name)
		frappe.db.commit()

		rows = frappe.get_all(
			"Stock Entry Detail", filters={"parent": se.name},
			fields=["basic_rate", SE_RATE_FIELD, "basic_amount", "idx"],
			order_by="idx",
		)
		got = [((round(flt(r.basic_rate), 4)), (round(flt(r.get(SE_RATE_FIELD)), 4))) for r in rows]
		want = [(100.0, 1200.0)] * 3
		amount_a = flt(rows[0].basic_amount) if rows else None
		sle_qty = flt(sum(frappe.get_all(
			"Stock Ledger Entry",
			filters={"voucher_type": "Stock Entry", "voucher_no": se.name},
			pluck="actual_qty",
		)))
		check(
			"se_asymmetric_rule",
			len(rows) == 3 and got == want,
			f"rows(basic,custom)={got} want {want}",
		)
		check(
			"se_native_math_uses_rate",
			amount_a is not None and abs(amount_a - 2400) < 0.01,
			f"basic_amount row-a={amount_a} (want 24 x 100 = 2400)",
		)
		check(
			"se_sle_accepted",
			abs(sle_qty - 72) < 0.0001,
			f"sum(SLE actual_qty)={sle_qty} (want 3 x 24 = 72)",
		)
	except Exception as e:
		check("se_asymmetric_rule", False, f"{type(e).__name__}: {str(e)[:250]}")
		check("se_native_math_uses_rate", True, "skipped: SE gagal dibuat")
		check("se_sle_accepted", True, "skipped: SE gagal dibuat")


def _teardown(check):
	try:
		frappe.set_user("Administrator")
	except Exception:
		pass
	sweep_ok, sweep_evidence = _sweep()
	residue = count_residue(PREFIX, {"Stock Entry": TRACKED["se"]})
	zero = all(v == 0 for v in residue.values())
	check(
		"teardown",
		sweep_ok and zero,
		f"{sweep_evidence}; residu {PREFIX}={residue} (SE tracked={TRACKED['se']})",
	)


def _sweep():
	"""Bersihkan residu W32: via item prefix + SE native yang ter-track. Idempoten."""
	errors = []

	def safe(label, fn):
		try:
			fn()
		except Exception as e:
			errors.append(f"{label}: {type(e).__name__}: {str(e)[:120]}")

	def cancel_delete(doctype, name):
		if not frappe.db.exists(doctype, name):
			return
		doc = frappe.get_doc(doctype, name)
		if doc.docstatus == 1:
			doc.flags.ignore_permissions = True
			doc.cancel()
		frappe.delete_doc(doctype, name, force=1, ignore_missing=True)

	items = frappe.get_all(
		"Item",
		or_filters=[
			["Item", "name", "like", PREFIX + "%"],
			["Item", "item_code", "like", PREFIX + "%"],
			["Item", "item_name", "like", PREFIX + "%"],
		],
		pluck="name",
	)
	se_names = set(TRACKED["se"])
	if items:
		se_names.update(
			frappe.get_all("Stock Entry Detail", filters={"item_code": ("in", items)}, pluck="parent")
		)
	for name in se_names:
		safe(f"SE {name}", lambda n=name: cancel_delete("Stock Entry", n))
	if items:
		safe("SLE", lambda: frappe.db.delete("Stock Ledger Entry", {"item_code": ("in", items)}))
		safe("Repost", lambda: frappe.db.delete("Repost Item Valuation", {"item_code": ("in", items)}))
		safe("Bin", lambda: frappe.db.delete("Bin", {"item_code": ("in", items)}))
	for name in items:
		safe(f"Item {name}", lambda n=name: frappe.delete_doc("Item", n, force=1, ignore_missing=True))
	safe("Version", lambda: frappe.db.delete("Version", {"docname": ("like", PREFIX + "%")}))

	TRACKED.update({"se": [], "item": []})
	return (not errors), ("bersih" if not errors else "; ".join(errors[:5]))
