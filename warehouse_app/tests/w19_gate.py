# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto
# License: MIT

# Gate W19 — group handover request (N WO satu item, satu permintaan bersama).
#
# Jalankan:
#   docker exec erpnext-new-backend-1 bench --site frontend execute \
#       warehouse_app.tests.w19_gate.run_gate
#
# Kontrak output: TEPAT satu baris GATE_JSON:{...} (ok: bool, checks: dict,
# error: opsional). Cek gagal -> ok=false TANPA raise; hanya crash tak terduga
# yang di-raise (bench exit nonzero).
#
# Yang diverifikasi:
#   1. Settings CRUD (warehouse_app): set_group_items/get_group_items
#      role-gated — gudang boleh, user tanpa role PermissionError.
#   2. Picker (requestable_work_orders): flag group_item + field grup netral
#      sebelum ada grup.
#   3. create_group_request production_app (2026-10-10) -> SATU MR dengan
#      satu baris per WO, ringkasan WO = Link ke MR itu, picker group_size.
#   4. Negative: single WO (<2), item campuran — ditolak nol-tulis.
#   5. Duplicate: grup kedua yang menyentuh anggota aktif -> ditolak.
#   6. cancel_request MR bulk -> MR batal, link semua WO bersih, picker normal.
#
# Fixture (prefix "ZZTEST-W19"): 2 item, 4 WO (3 item utama + 1 item lain
# utk uji campuran), SE Manufacture per WO utama memakai POOL gudang asal
# yang environment-aware (custom_default_handover_source_warehouse, fallback
# Gudang Produksi) — pola w9_gate. User fixture email UNIK per run (cache
# roles). MR/SE/HBP native naming di-track via daftar nama saat run;
# teardown lengkap di finally, settings dikembalikan kosong.

import json
import traceback

import frappe
from frappe.utils import flt, now_datetime

from warehouse_app.tests.guard import count_residue, item_inventory_defaults
from warehouse_app.warehouse_app.gudang_request import requestable_work_orders

PREFIX = "ZZTEST-W19"
ITEM_CODE = PREFIX + "-ITEM"
ITEM_NAME = "ZZTEST W19 Gate Item"  # varian ber-spasi: cakupan guard item_name
ITEM2_CODE = PREFIX + "-ITEM2"
ITEM2_NAME = "ZZTEST W19 Gate Item 2"
ADONAN = 919
QTY = 100
# Email UNIK per run — cache roles per email menempel lintas run bila statis.
USER_EMAIL = "zztest-w19-%s@example.com" % now_datetime().strftime("%Y%m%d%H%M%S%f")

# Dokumen bernama native (tidak ber-prefix) yang tercipta saat run.
TRACKED = {"wo": [], "se": [], "mr": [], "item": [], "hbp": []}


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

	# --- Preflight (environment-aware, pola w9_gate) ---
	target = _safe_resolve("Gudang Barang Jadi")
	source = _safe_resolve("Gudang Produksi")
	company = frappe.db.get_value("Warehouse", target, "company") if target else None
	setting_target = frappe.db.get_single_value(
		"Manufacturing Settings", "custom_default_handover_warehouse"
	)
	pool = (
		frappe.db.get_single_value(
			"Manufacturing Settings", "custom_default_handover_source_warehouse"
		)
		or source
	)
	pool_ok = bool(
		pool
		and frappe.db.exists("Warehouse", pool)
		and not frappe.db.get_value("Warehouse", pool, "is_group")
	)
	check(
		"preflight",
		bool(target and source and company and setting_target == target and pool_ok),
		f"source={source!r}, pool={pool!r}, target={target!r}, setting={setting_target!r}",
	)
	if not (target and source and company and pool_ok):
		raise GateAborted()

	uom = next((u for u in ("Nos", "Kg") if frappe.db.exists("UOM", u)), None)
	item_group = _pick_item_group()
	check("preflight_uom_group", bool(uom and item_group), f"uom={uom!r}, group={item_group!r}")
	if not (uom and item_group):
		raise GateAborted()

	# --- Item fixture (2 item: utama utk grup, kedua utk uji campuran) ---
	try:
		for code, name in ((ITEM_CODE, ITEM_NAME), (ITEM2_CODE, ITEM2_NAME)):
			item = frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": code,
					"item_name": name,
					"item_group": item_group,
					"stock_uom": uom,
					"is_stock_item": 1,
					"has_batch_no": 0,
					"has_serial_no": 0,
					# site item-wise inventory account (mis. 1oktober2026) butuh
					# ini agar SE submit bisa posting GL — no-op di site lain
					"item_defaults": item_inventory_defaults(company),
				}
			)
			item.insert()
			if not item.name.startswith(PREFIX):
				frappe.rename_doc("Item", item.name, code)
			TRACKED["item"].append(code)
		check(
			"fixture_item",
			frappe.db.exists("Item", ITEM_CODE) is not None
			and frappe.db.exists("Item", ITEM2_CODE) is not None,
			f"{ITEM_CODE}, {ITEM2_CODE}",
		)
	except Exception as e:
		check("fixture_item", False, f"{type(e).__name__}: {e}")
		raise GateAborted()

	# --- WO fixture: 3 WO item utama (ignore_validate + docstatus manual) ---
	try:
		for i in range(3):
			wo = frappe.get_doc(
				{
					"doctype": "Work Order",
					"company": company,
					"production_item": ITEM_CODE,
					"qty": QTY,
					"stock_uom": uom,
					"fg_warehouse": source,
					"wip_warehouse": source,
					"custom_adonan_ke": ADONAN,
				}
			)
			wo.flags.ignore_validate = True
			wo.flags.ignore_mandatory = True
			wo.insert(ignore_permissions=True)
			frappe.db.set_value(
				"Work Order",
				wo.name,
				{"docstatus": 1, "status": "Completed", "produced_qty": QTY},
				update_modified=False,
			)
			TRACKED["wo"].append(wo.name)
		# WO ke-4: item LAIN untuk uji penolakan campuran (tanpa SE — harus
		# ditolak sebelum kebutuhan lot relevan)
		wo4 = frappe.get_doc(
			{
				"doctype": "Work Order",
				"company": company,
				"production_item": ITEM2_CODE,
				"qty": QTY,
				"stock_uom": uom,
				"fg_warehouse": source,
				"wip_warehouse": source,
				"custom_adonan_ke": ADONAN,
			}
		)
		wo4.flags.ignore_validate = True
		wo4.flags.ignore_mandatory = True
		wo4.insert(ignore_permissions=True)
		frappe.db.set_value(
			"Work Order",
			wo4.name,
			{"docstatus": 1, "status": "Completed", "produced_qty": QTY},
			update_modified=False,
		)
		TRACKED["wo"].append(wo4.name)
		check(
			"fixture_wo",
			len(TRACKED["wo"]) == 4
			and all(
				frappe.db.get_value("Work Order", n, "docstatus") == 1 for n in TRACKED["wo"]
			),
			f"{TRACKED['wo']}",
		)
	except Exception as e:
		check("fixture_wo", False, f"{type(e).__name__}: {e}")
		raise GateAborted()

	# --- SE Manufacture per WO utama: sumber lot production_app ---
	try:
		for wo_name in TRACKED["wo"][:3]:
			se = frappe.get_doc(
				{
					"doctype": "Stock Entry",
					"company": company,
					"purpose": "Manufacture",
					"work_order": wo_name,
					"items": [
						{
							"item_code": ITEM_CODE,
							"t_warehouse": pool,
							"qty": QTY,
							"transfer_qty": QTY,
							"stock_uom": uom,
							"conversion_factor": 1,
							"is_finished_item": 1,
							"expense_account": frappe.db.get_value(
								"Company", company, "default_expense_account"
							),
							"cost_center": frappe.db.get_value(
								"Cost Center", {"company": company, "is_group": 0}, "name"
							),
						}
					],
				}
			)
			se.flags.ignore_validate = True
			se.flags.ignore_mandatory = True
			se.submit()
			TRACKED["se"].append(se.name)
		check("fixture_se_manufacture", len(TRACKED["se"]) == 3, f"{TRACKED['se']} -> {pool}")
	except Exception as e:
		check("fixture_se_manufacture", False, f"{type(e).__name__}: {e}")
		raise GateAborted()

	# --- User fixture: TANPA role dulu -> negative settings ---
	try:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": USER_EMAIL,
				"first_name": PREFIX,
				"user_type": "System User",
				"desk_access": 1,
				"send_welcome_email": 0,
				"new_password": frappe.generate_hash(length=16),
			}
		)
		user.flags.ignore_permissions = True
		user.insert()
		check("fixture_user", frappe.db.exists("User", USER_EMAIL) is not None, USER_EMAIL)
	except Exception as e:
		check("fixture_user", False, f"{type(e).__name__}: {e}")
		raise GateAborted()

	from warehouse_app.warehouse_app.gudang_settings import get_group_items, set_group_items

	frappe.set_user(USER_EMAIL)
	try:
		set_group_items(items=[ITEM_CODE])
		check("settings_denied_without_role", False, "set_group_items TIDAK ditolak tanpa role")
	except frappe.PermissionError as e:
		check("settings_denied_without_role", True, f"PermissionError: {str(e)[:150]}")
	except Exception as e:
		check("settings_denied_without_role", False, f"{type(e).__name__}: {str(e)[:150]}")
	finally:
		frappe.set_user("Administrator")

	# --- Beri role gudang ---
	try:
		user = frappe.get_doc("User", USER_EMAIL)
		user.add_roles("Stock Manager", "Stock User")
		frappe.clear_cache(user=USER_EMAIL)
		check(
			"fixture_roles",
			"Stock User" in frappe.get_roles(USER_EMAIL),
			str(frappe.get_roles(USER_EMAIL)),
		)
	except Exception as e:
		check("fixture_roles", False, f"{type(e).__name__}: {e}")
		raise GateAborted()

	# --- Settings CRUD sebagai user gudang: set (dengan duplikat) -> round-trip ---
	try:
		frappe.set_user(USER_EMAIL)
		res_set = set_group_items(items=[ITEM_CODE, ITEM_CODE])
		res_get = get_group_items()
		check(
			"settings_roundtrip",
			bool(res_set.get("ok") and res_set.get("items") == [ITEM_CODE] and res_get.get("items") == [ITEM_CODE]),
			f"set={res_set}, get={res_get}",
		)
		# W20: get_group_items balas peta nama utk tampilan chip nama+kode
		check(
			"settings_names",
			(res_get.get("names") or {}).get(ITEM_CODE) == ITEM_NAME,
			f"names={res_get.get('names')}, want {ITEM_CODE} -> {ITEM_NAME}",
		)
	except Exception as e:
		check("settings_roundtrip", False, f"{type(e).__name__}: {e}")
		frappe.set_user("Administrator")
		raise GateAborted()

	# --- Picker: 3 WO utama ber-flag group_item, field grup netral ---
	try:
		rows = requestable_work_orders(search=ITEM_NAME)
		main_rows = [r for r in rows if r.name in TRACKED["wo"][:3]]
		ok = len(main_rows) == 3 and all(
			r.group_item and not r.box_plan and not r.group_boxes and not r.group_size
			for r in main_rows
		)
		check(
			"picker_group_flags",
			ok,
			f"rows={[(r.name, r.group_item, r.box_plan, r.group_boxes, r.group_size) for r in main_rows]}",
		)
		# expected unit per WO dalam display UOM (fallback stock) — dasar qty grup
		expected = {r.name: int(r.expected_units or 0) for r in main_rows}
		display_uom = main_rows[0].display_uom if main_rows else ""
	except Exception as e:
		check("picker_group_flags", False, f"{type(e).__name__}: {e}")
		frappe.set_user("Administrator")
		raise GateAborted()

	w1, w2, w3, w4 = TRACKED["wo"]
	e1, e2, e3 = expected.get(w1, 0), expected.get(w2, 0), expected.get(w3, 0)
	total = e1 + e2 + e3

	from production_app.api.handover import (
		cancel_request,
		create_group_request,
	)

	def _member_mr_count():
		"""Jumlah MR yang menempel ke WO utama (untuk assert nol-tulis)."""
		return frappe.db.count(
			"Material Request", {"name": ("in", frappe.get_all(
				"Work Order",
				filters={"name": ("in", [w1, w2, w3])},
				pluck="custom_handover_material_request",
			) or [""])}
		)

	# --- Negative: negasi dieksekusi SEBELUM happy create agar guard
	# "anggota aktif" tidak menutupi validasi masing-masing ---
	try:
		create_group_request(work_orders=json.dumps([w1]))
		check("group_single_rejected", False, "1 WO (<2) TIDAK ditolak!")
	except Exception as e:
		check("group_single_rejected", _member_mr_count() == 0, f"{type(e).__name__}: {str(e)[:180]}")

	try:
		create_group_request(work_orders=json.dumps([w1, w4]))
		check("group_mixed_rejected", False, "item campuran TIDAK ditolak!")
	except Exception as e:
		check("group_mixed_rejected", _member_mr_count() == 0, f"{type(e).__name__}: {str(e)[:180]}")

	# --- Happy path: 3 WO satu item -> SATU MR, satu baris per WO (2026-10-10) ---
	try:
		res = create_group_request(work_orders=json.dumps([w1, w2, w3]))
		mr = res.get("material_request")
		TRACKED["mr"].append(mr)
		mr_doc = frappe.get_doc("Material Request", mr)
		wo_state = frappe.get_all(
			"Work Order",
			filters={"name": ("in", [w1, w2, w3])},
			fields=["name", "custom_handover_material_request"],
		)
		ok = bool(
			res.get("ok")
			and res.get("box_plan") is None
			and int(res.get("expected_unit_count") or 0) == total
			and mr_doc.docstatus == 1
			and mr_doc.material_request_type == "Material Transfer"
			and sorted(i.custom_work_order for i in mr_doc.items) == sorted([w1, w2, w3])
			and len(wo_state) == 3
			and all(d.custom_handover_material_request == mr for d in wo_state)
		)
		check(
			"create_group_request",
			ok,
			f"mr={mr!r}, rows={[i.custom_work_order for i in mr_doc.items]}, expected={res.get('expected_unit_count')}/{total}, wo={wo_state}",
		)
	except Exception as e:
		check("create_group_request", False, f"{type(e).__name__}: {e}")
		frappe.set_user("Administrator")
		raise GateAborted()

	# --- Picker: anggota aktif + ukuran grup dari baris MR ---
	try:
		rows = requestable_work_orders(search=ITEM_NAME)
		main_rows = [r for r in rows if r.name in TRACKED["wo"][:3]]
		ok = len(main_rows) == 3 and all(
			r.request_active and not r.box_plan and r.group_size == 3 for r in main_rows
		)
		check(
			"picker_group_active",
			ok,
			f"rows={[(r.name, r.request_active, r.box_plan, r.group_size) for r in main_rows]}",
		)
	except Exception as e:
		check("picker_group_active", False, f"{type(e).__name__}: {e}")

	# --- Duplicate: grup kedua menyentuh anggota aktif -> ditolak nol-tulis ---
	try:
		before = _member_mr_count()
		create_group_request(work_orders=json.dumps([w1, w2]))
		check("group_duplicate_rejected", False, "grup kedua TIDAK ditolak!")
	except Exception as e:
		after = _member_mr_count()
		check(
			"group_duplicate_rejected",
			after == before,
			f"{type(e).__name__}: {str(e)[:180]}, mr_before={before}, mr_after={after}",
		)

	# --- cancel_request MR bulk: semua WO bersih, picker normal lagi ---
	try:
		cancel_request(material_request=mr)
		wo_links = {
			d.name: d.custom_handover_material_request
			for d in frappe.get_all(
				"Work Order",
				filters={"name": ("in", [w1, w2, w3])},
				fields=["name", "custom_handover_material_request"],
			)
		}
		rows = requestable_work_orders(search=ITEM_NAME)
		main_rows = [r for r in rows if r.name in TRACKED["wo"][:3]]
		ok = bool(
			frappe.db.get_value("Material Request", mr, "docstatus") == 2
			and all(v in (None, "") for v in wo_links.values())
			and len(main_rows) == 3
			and all(not r.request_active and not r.group_size for r in main_rows)
		)
		check(
			"cancel_group_request",
			ok,
			f"wo_links={wo_links}, picker={[(r.name, r.request_active, r.group_size) for r in main_rows]}",
		)
	except Exception as e:
		check("cancel_group_request", False, f"{type(e).__name__}: {e}")
	finally:
		frappe.set_user("Administrator")

def _teardown(check):
	try:
		frappe.set_user("Administrator")
	except Exception:
		pass
	# Settings dikembalikan kosong SEBELUM item dihapus — child row settings
	# ber-Link Item akan menghalangi delete item fixture.
	settings_evidence = ""
	try:
		from warehouse_app.warehouse_app.gudang_settings import set_group_items

		set_group_items(items=[])
	except Exception as e:
		settings_evidence = f"; set_group_items([]) error {type(e).__name__}: {str(e)[:120]}"
	hbp_names = list(TRACKED["hbp"])
	sweep_ok, sweep_evidence = _sweep()
	residue = count_residue(PREFIX, {"Handover Box Plan": hbp_names})
	zero = all(v == 0 for v in residue.values())
	check(
		"teardown",
		sweep_ok and zero and not settings_evidence,
		f"{sweep_evidence}; residu {PREFIX}={residue} (HBP tracked={hbp_names}){settings_evidence}",
	)


def _sweep():
	"""Bersihkan residu W19: via item prefix + nama native yang ter-track. Idempoten."""
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

	def del_plan(name):
		# Plan boleh punya hook cancel yang menyentuh MR; fallback turunkan
		# docstatus manual agar force-delete tetap mungkin.
		if not frappe.db.exists("Handover Box Plan", name):
			return
		doc = frappe.get_doc("Handover Box Plan", name)
		if doc.docstatus == 1:
			try:
				doc.flags.ignore_permissions = True
				doc.cancel()
			except Exception:
				frappe.db.set_value("Handover Box Plan", name, "docstatus", 0, update_modified=False)
		frappe.delete_doc("Handover Box Plan", name, force=1, ignore_missing=True)

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
	# HBP di-track by name (HBP-##### tidak ber-prefix) — hapus sebelum MR/WO
	for name in TRACKED["hbp"]:
		safe(f"HBP {name}", lambda n=name: del_plan(n))
	# SE via row item (native naming MFG-*) atau track list
	se_names = set(TRACKED["se"])
	if items:
		se_names.update(
			frappe.get_all("Stock Entry Detail", filters={"item_code": ("in", items)}, pluck="parent")
		)
	for name in se_names:
		safe(f"SE {name}", lambda n=name: cancel_delete("Stock Entry", n))
	# MR via row item atau track list
	mr_names = set(TRACKED["mr"])
	if items:
		mr_names.update(
			frappe.get_all("Material Request Item", filters={"item_code": ("in", items)}, pluck="parent")
		)
	for name in mr_names:
		safe(f"MR {name}", lambda n=name: cancel_delete("Material Request", n))
	# WO via production_item atau track list (hapus SETELAH SE/MR)
	wo_names = set(TRACKED["wo"])
	if items:
		wo_names.update(frappe.get_all("Work Order", filters={"production_item": ("in", items)}, pluck="name"))
	for name in wo_names:
		def del_wo(n=name):
			frappe.db.set_value("Work Order", n, "docstatus", 0, update_modified=False)
			frappe.delete_doc("Work Order", n, force=1, ignore_missing=True)
		safe(f"WO {name}", del_wo)
	# SLE/Bin/Repost per item (jaga-jaga bila cancel SE tak sempat membersihkan)
	safe("SLE", lambda: frappe.db.delete("Stock Ledger Entry", {"item_code": ("in", items or [""])}) if items else None)
	safe("Repost", lambda: frappe.db.delete("Repost Item Valuation", {"item_code": ("in", items or [""])}) if items else None)
	safe("Bin", lambda: frappe.db.delete("Bin", {"item_code": ("in", items or [""])}) if items else None)
	# Item
	for name in items:
		safe(f"Item {name}", lambda n=name: frappe.delete_doc("Item", n, force=1, ignore_missing=True))
	# User + jejak sesi (email unik per run tetap tercakup like case-insensitive)
	for name in frappe.get_all("User", filters={"name": ("like", PREFIX + "%")}, pluck="name"):
		safe(f"User {name}", lambda n=name: frappe.delete_doc("User", n, force=1, ignore_missing=True))
	safe("Sessions", lambda: frappe.db.delete("Sessions", {"user": ("like", PREFIX + "%")}))
	safe("ActivityLog.user", lambda: frappe.db.delete("Activity Log", {"user": ("like", PREFIX + "%")}))
	if frappe.db.has_column("Activity Log", "for_user"):
		safe("ActivityLog.for_user", lambda: frappe.db.delete("Activity Log", {"for_user": ("like", PREFIX + "%")}))
	safe("Version", lambda: frappe.db.delete("Version", {"docname": ("like", PREFIX + "%")}))

	TRACKED.update({"wo": [], "se": [], "mr": [], "item": [], "hbp": []})
	return (not errors), ("bersih" if not errors else "; ".join(errors[:5]))


def _safe_resolve(base):
	try:
		from warehouse_app.warehouse_app.report.serah_terima_gudang.serah_terima_gudang import (
			resolve_warehouse,
		)

		return resolve_warehouse(base)
	except Exception:
		return None


def _pick_item_group():
	for group in ("Bread", "Products"):
		if frappe.db.exists("Item Group", group) and not frappe.db.get_value("Item Group", group, "is_group"):
			return group
	return frappe.db.get_value("Item Group", {"is_group": 0}, "name", order_by="name")
