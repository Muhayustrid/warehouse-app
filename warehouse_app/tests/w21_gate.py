# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto
# License: MIT

# Gate W21 — Default Inventory UOM per Item + Basic Rate (UOM) di Stock Entry.
#
# Jalankan:
#   docker exec erpnext-new-backend-1 bench --site frontend execute \
#       warehouse_app.tests.w21_gate.run_gate
#
# Kontrak output: TEPAT satu baris GATE_JSON:{...} (ok: bool, checks: dict,
# error: opsional). Cek gagal -> ok=false TANPA raise; hanya crash tak terduga
# yang di-raise (bench exit nonzero).
#
# Yang diverifikasi:
#   1. Custom Field Item (Link UOM) + Stock Entry Detail (read_only,
#      in_list_view) eksis.
#   2. 3 Client Script ber-marker eksis & enabled.
#   3. Validasi Item menolak Default Inventory UOM di luar UOM Conversion /
#      stock UOM, menerima yang valid (W20 lesson: TANPA item_code — naming
#      series site menimpa; pakai doc.name hasil insert).
#   4. SE Material Receipt: server mengisi custom_basic_rate_per_uom
#      (basic_rate x conversion factor) + transfer_qty — env-aware, skip bila
#      site belum punya Company/Warehouse.
#   5. production_app._enrich_units memprioritaskan field baru di atas legacy
#      custom_default_uom_warehouse (env-aware: hanya bila production_app
#      terpasang).
#   6. migrate_legacy_uom_field idempoten (run kedua copied 0).
#   7. upgrade.ensure_item_fields idempoten (run kedua "unchanged").
#
# Fixture (prefix "ZZTEST-W21", TANPA user fixture): 3 Item dengan item_code
# run-unik (site naming-series menimpanya — W20 — site autoname field:item_code
# seperti fresh.localhost memakainya sebagai nama); SE native naming di-track
# via daftar nama saat run. Teardown di finally, residu prefix = 0.

import json
import re
import traceback

import frappe
from frappe.utils import flt

from warehouse_app.tests.guard import count_residue
from warehouse_app import upgrade
from warehouse_app.inventory_uom import ITEM_UOM_FIELD, SE_RATE_FIELD

PREFIX = "ZZTEST-W21"
MARKER = upgrade.SCRIPT_MARKER
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

	# --- Preflight (environment-aware) ---
	stock, alt, invalid = _pick_uoms()
	item_group = _pick_item_group()
	check(
		"preflight",
		bool(stock and alt and invalid and item_group),
		f"stock={stock!r}, alt={alt!r}, invalid={invalid!r}, group={item_group!r}",
	)
	if not (stock and alt and invalid and item_group):
		raise GateAborted()

	# --- Custom Field Item: Link UOM ---
	row = frappe.db.get_value(
		"Custom Field", {"dt": "Item", "fieldname": ITEM_UOM_FIELD}, ["fieldtype", "options"], as_dict=1
	)
	check(
		"item_custom_field",
		bool(row and row.fieldtype == "Link" and row.options == "UOM"),
		f"fieldtype={getattr(row, 'fieldtype', None)!r}, options={getattr(row, 'options', None)!r}",
	)

	# --- Custom Field Stock Entry Detail: read_only + in_list_view ---
	row = frappe.db.get_value(
		"Custom Field", {"dt": "Stock Entry Detail", "fieldname": SE_RATE_FIELD},
		["read_only", "in_list_view"], as_dict=1,
	)
	check(
		"se_custom_field",
		bool(row and int(row.read_only or 0) == 1 and int(row.in_list_view or 0) == 1),
		f"read_only={getattr(row, 'read_only', None)!r}, in_list_view={getattr(row, 'in_list_view', None)!r}",
	)

	# --- 3 Client Script ber-marker, enabled ---
	scripts = frappe.get_all(
		"Client Script", filters={"script": ("like", "%" + MARKER + "%")}, fields=["dt", "enabled"]
	)
	check(
		"client_scripts",
		len(scripts) == 3
		and all(int(d.enabled or 0) == 1 for d in scripts)
		and {d.dt for d in scripts} == {"Item", "Stock Entry", "Material Request"},
		f"{[(d.dt, d.enabled) for d in scripts]}",
	)

	def make_item(uom_value=None, uoms=None):
		doc = frappe.get_doc(
			{
				"doctype": "Item",
				# item_code run-unik per item: site autoname field:item_code
				# (fresh.localhost) mewajibkannya; site naming-series (frontend)
				# menimpanya — tak masalah, pakai doc.name hasil insert.
				"item_code": PREFIX + "-" + frappe.generate_hash(length=8),
				"item_name": PREFIX + " Gate Item",
				"item_group": item_group,
				"stock_uom": stock,
				"is_stock_item": 1,
				"has_batch_no": 0,
				"has_serial_no": 0,
				"uoms": uoms or [{"uom": alt, "conversion_factor": 12}],
				ITEM_UOM_FIELD: uom_value,
			}
		)
		doc.insert()
		return doc

	# --- Validasi Item menolak UOM di luar tabel konversi ---
	frappe.db.commit()  # rollback negative check tidak boleh menyeret fixture lain
	try:
		make_item(uom_value=invalid)
		check("item_validation_rejects", False, f"Item dengan UOM {invalid!r} TIDAK ditolak!")
	except frappe.ValidationError as e:
		frappe.db.rollback()
		check("item_validation_rejects", True, f"ValidationError: {str(e)[:150]}")
	except Exception as e:
		frappe.db.rollback()
		check("item_validation_rejects", False, f"{type(e).__name__}: {str(e)[:180]}")

	# --- Validasi Item menerima UOM di tabel konversi ---
	try:
		item_a = make_item(uom_value=alt)
		TRACKED["item"].append(item_a.name)
		stored = frappe.db.get_value("Item", item_a.name, ITEM_UOM_FIELD)
		check(
			"item_validation_accepts",
			bool(item_a.name) and stored == alt,
			f"item={item_a.name!r}, field={stored!r}",
		)
	except Exception as e:
		check("item_validation_accepts", False, f"{type(e).__name__}: {e}")
		raise GateAborted()
	frappe.db.commit()

	# --- SE Material Receipt: rate per UOM + transfer_qty terhitung ---
	company = (frappe.get_all("Company", pluck="name", limit=1) or [None])[0]
	se_name = None
	if not company:
		check("se_rate_computed", True, "skipped: site belum punya Company")
	else:
		try:
			warehouse = frappe.get_all(
				"Warehouse", filters={"company": company, "is_group": 0, "disabled": 0},
				pluck="name", limit=1,
			)
			warehouse = warehouse[0] if warehouse else None
			if not warehouse:
				check("se_rate_computed", True, f"skipped: tidak ada Warehouse utk company {company!r}")
			else:
				se = frappe.get_doc(
					{
						"doctype": "Stock Entry",
						"company": company,
						"stock_entry_type": "Material Receipt",
						"purpose": "Material Receipt",
						"items": [
							{
								"item_code": item_a.name,
								"qty": 2,
								"uom": alt,
								"stock_uom": stock,
								"conversion_factor": 12,
								"basic_rate": 100,  # per stock UOM
								"t_warehouse": warehouse,
							}
						],
					}
				)
				se.insert()
				se.submit()
				se_name = se.name
				TRACKED["se"].append(se_name)
				frappe.db.commit()
				row = frappe.db.get_value(
					"Stock Entry Detail", {"parent": se_name},
					[SE_RATE_FIELD, "transfer_qty", "conversion_factor", "basic_rate", "uom", "qty"],
					as_dict=1,
				)
				ok = bool(
					row
					and abs(flt(row.get(SE_RATE_FIELD)) - 1200) < 0.01
					and abs(flt(row.transfer_qty) - 24) < 0.0001
				)
				check(
					"se_rate_computed",
					ok,
					f"se={se_name}, row={dict(row) if row else None}, want rate=100x12=1200, transfer_qty=2x12=24",
				)
		except Exception as e:
			check("se_rate_computed", False, f"{type(e).__name__}: {str(e)[:200]}")

	# --- production_app._enrich_units: field baru menang atas legacy ---
	if "production_app" not in (frappe.get_installed_apps() or []):
		check("enrich_units_prefers_new", True, "skipped: production_app tidak terpasang")
	elif not frappe.get_meta("Item").has_field(upgrade.LEGACY_UOM_FIELD):
		check("enrich_units_prefers_new", True, "skipped: legacy field absen")
	else:
		try:
			from production_app.api.work_order import _enrich_units

			# Dua field beda nilai, keduanya valid → bukti precedence, bukan fallback.
			item_b = make_item(
				uom_value=alt,
				uoms=[{"uom": alt, "conversion_factor": 12}, {"uom": invalid, "conversion_factor": 1}],
			)
			TRACKED["item"].append(item_b.name)
			frappe.db.set_value(
				"Item", item_b.name, upgrade.LEGACY_UOM_FIELD, invalid, update_modified=False
			)
			row = {"production_item": item_b.name, "custom_uom": None}
			_enrich_units([row])
			ok = row.get("display_uom") == alt and abs(flt(row.get("display_conversion_factor")) - 12) < 0.0001
			check(
				"enrich_units_prefers_new",
				ok,
				f"item={item_b.name!r}, display_uom={row.get('display_uom')!r} (want {alt!r}), "
				f"factor={row.get('display_conversion_factor')!r} (want 12)",
			)
		except Exception as e:
			check("enrich_units_prefers_new", False, f"{type(e).__name__}: {str(e)[:200]}")

	# --- migrate_legacy_uom_field idempoten ---
	if not frappe.get_meta("Item").has_field(upgrade.LEGACY_UOM_FIELD):
		check("legacy_migration_idempotent", True, "skipped: legacy field absen (install ala Frappe Cloud)")
	else:
		try:
			item_c = make_item(uom_value=None)
			TRACKED["item"].append(item_c.name)
			# Legacy diset SETELAH insert (bypass validate) — hanya migrasi yang
			# menyalinnya ke field baru.
			frappe.db.set_value(
				"Item", item_c.name, upgrade.LEGACY_UOM_FIELD, alt, update_modified=False
			)
			first = upgrade.migrate_legacy_uom_field()
			second = upgrade.migrate_legacy_uom_field()
			copied_first = int(re.search(r"copied (\d+)", first or "").group(1))
			copied_second = int(re.search(r"copied (\d+)", second or "").group(1))
			migrated = frappe.db.get_value("Item", item_c.name, ITEM_UOM_FIELD)
			check(
				"legacy_migration_idempotent",
				copied_first >= 1 and copied_second == 0 and migrated == alt,
				f"item={item_c.name!r}, first={first!r}, second={second!r}, field={migrated!r}",
			)
		except Exception as e:
			check("legacy_migration_idempotent", False, f"{type(e).__name__}: {str(e)[:200]}")

	# --- ensure_item_fields idempoten ---
	try:
		first = upgrade.ensure_item_fields()
		second = upgrade.ensure_item_fields()
		check(
			"upgrade_idempotent",
			first in ("created", "updated", "unchanged") and second == "unchanged",
			f"first={first!r}, second={second!r}",
		)
	except Exception as e:
		check("upgrade_idempotent", False, f"{type(e).__name__}: {e}")


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
	"""Bersihkan residu W21: via item prefix + SE native yang ter-track. Idempoten."""
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
			["Item", "item_name", "like", PREFIX.replace("-", " ") + "%"],
		],
		pluck="name",
	)
	# SE via row item (native naming) atau track list
	se_names = set(TRACKED["se"])
	if items:
		se_names.update(
			frappe.get_all("Stock Entry Detail", filters={"item_code": ("in", items)}, pluck="parent")
		)
	for name in se_names:
		safe(f"SE {name}", lambda n=name: cancel_delete("Stock Entry", n))
	# SLE/Bin/Repost per item (jaga-jaga bila cancel SE tak sempat membersihkan)
	safe("SLE", lambda: frappe.db.delete("Stock Ledger Entry", {"item_code": ("in", items or [""])}) if items else None)
	safe("Repost", lambda: frappe.db.delete("Repost Item Valuation", {"item_code": ("in", items or [""])}) if items else None)
	safe("Bin", lambda: frappe.db.delete("Bin", {"item_code": ("in", items or [""])}) if items else None)
	# Item
	for name in items:
		safe(f"Item {name}", lambda n=name: frappe.delete_doc("Item", n, force=1, ignore_missing=True))
	safe("Version", lambda: frappe.db.delete("Version", {"docname": ("like", PREFIX + "%")}))

	TRACKED.update({"se": [], "item": []})
	return (not errors), ("bersih" if not errors else "; ".join(errors[:5]))


def _pick_uoms():
	"""Tiga UOM eksisting berbeda: (stock, alt utk tabel konversi, invalid)."""
	stock = next((u for u in ("Nos", "Unit", "Kg") if frappe.db.exists("UOM", u)), None)
	alt = next(
		(u for u in ("Pack", "Box", "Bag") if u != stock and frappe.db.exists("UOM", u)), None
	)
	invalid = next(
		(u for u in ("Kg", "Gram", "Meter") if u not in (stock, alt) and frappe.db.exists("UOM", u)),
		None,
	)
	return stock, alt, invalid


def _pick_item_group():
	for group in ("Bread", "Products"):
		if frappe.db.exists("Item Group", group) and not frappe.db.get_value("Item Group", group, "is_group"):
			return group
	return frappe.db.get_value("Item Group", {"is_group": 0}, "name", order_by="name")
