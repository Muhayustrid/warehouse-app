# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto
# License: MIT

# Gate W31 — Pick List + permukaan batch dalam UOM inventaris (custom_picked_qty
# <-> picked_qty native, hook before_validate/on_submit; SR baris batch langsung
# kini dikonversi, serial tetap passthrough).
#
# Jalankan:
#   docker exec erpnext-new-backend-1 bench --site frontend execute \
#       warehouse_app.tests.w31_gate.run_gate
#
# Kontrak output: TEPAT satu baris GATE_JSON:{...} (ok: bool, checks: dict,
# error: opsional). Cek gagal -> ok=false TANPA raise; hanya crash tak terduga
# yang di-raise (bench exit nonzero).
#
# Yang diverifikasi:
#   1. Custom Field custom_picked_qty di Pick List Item sesuai spec (Float,
#      in_list_view, insert_after picked_qty, TANPA default) + 3 Client Script
#      W31 (Pick List, Stock Entry patch, Batch) enabled + body SR W23
#      ter-drift-update persis sama dengan source.
#   2. Server-pure: baris PL uom Box faktor 12, custom 2 -> picked 24,
#      stock_qty konsisten (qty x faktor); draft reload + resave -> nilai
#      IDENTIK (invarian anti silent-zero Float 0.0).
#   3. Passthrough native: custom tak pernah diisi (0), picked diisi langsung
#      24 -> picked TIDAK berubah, custom ter-backfill 2.
#   4. Mapper-WO style: uom == stock_uom -> hook no-op (picked 3 utuh).
#   5. Clamp pick_manually=0: custom 5 dengan qty 2 -> custom 2, picked 24,
#      baris selamat melewati set_item_locations native.
#   6. on_submit backfill: scan_mode 0 tanpa picked -> submit -> native
#      auto-fill picked = stock_qty (24) dan custom ter-backfill 2.
#   7. SR: baris batch_no (direct) DIKONVERSI (qty = after x faktor) sejak
#      W31; baris serial_no tetap skip — dibuktikan lewat pemanggilan fungsi
#      hook murni (tanpa insert dokumen).
#   8. Partial-pick kedua mode pick_manually: baris ber-picked selamat,
#      custom konsisten pasca set_item_locations (mode 0); mode 1 baris utuh.
#   9. ensure_pl_fields + ensure_client_scripts idempoten (run kedua
#      "unchanged").
#
# Fixture (prefix "ZZTEST-W31", TANPA user fixture): 1 Item run-unik
# (item_code hash, site boleh menimpa via naming series — SELALU pakai
# doc.name hasil insert, jangan assert nama) + 1 SE Material Receipt 48 unit
# stock @100 untuk stok (Pick List tidak membuat SLE; hanya SE yang bergerak).
# Teardown di finally, residu prefix = 0 + nama ter-track.

import json
import time
import traceback

import frappe
from frappe.utils import flt, nowdate, nowtime

from warehouse_app import upgrade
from warehouse_app.inventory_uom import (
	PL_PICKED_FIELD,
	SR_AFTER_FIELD,
	SR_FACTOR_FIELD,
	SR_UOM_FIELD,
	apply_sr_inventory_uom,
)
from warehouse_app.tests.guard import count_residue

PREFIX = "ZZTEST-W31"
MARKER = upgrade.PL_SCRIPT_MARKER
SE_MARKER = upgrade.PL_SE_SCRIPT_MARKER
BATCH_MARKER = upgrade.PL_BATCH_SCRIPT_MARKER
TRACKED = {"pl": [], "se": [], "item": []}


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


def _make_pl(company, rows, **extra):
	doc = frappe.get_doc(
		{
			"doctype": "Pick List",
			"company": company,
			"purpose": "Material Transfer",
			"locations": rows,
			**extra,
		}
	)
	doc.insert()
	return doc


def _pl_row(item, warehouse, stock, alt, **extra):
	return {
		"item_code": item,
		"warehouse": warehouse,
		"uom": alt,
		"stock_uom": stock,
		"conversion_factor": 12,
		"qty": 2,
		"stock_qty": 24,
		**extra,
	}


def _run_gate(check):
	check("pre_clean", *_sweep())

	# --- Preflight (environment-aware) ---
	stock, alt, invalid = _pick_uoms()
	item_group = _pick_item_group()
	company = "JURI" if frappe.db.exists("Company", "JURI") else None
	if not company:
		companies = frappe.get_all("Company", pluck="name", limit=1)
		company = companies[0] if companies else None
	warehouse = None
	if company:
		warehouses = frappe.get_all(
			"Warehouse",
			filters={"company": company, "is_group": 0, "disabled": 0},
			pluck="name",
			limit=1,
		)
		warehouse = warehouses[0] if warehouses else None
	check(
		"preflight",
		bool(stock and alt and invalid and item_group),
		f"stock={stock!r}, alt={alt!r}, invalid={invalid!r}, group={item_group!r}, "
		f"company={company!r}, warehouse={warehouse!r}",
	)
	if not (stock and alt and invalid and item_group):
		raise GateAborted()

	# --- Pemasangan (agar gate mandiri walau migrate belum jalan) ---
	try:
		upgrade.ensure_pl_fields()
		upgrade.ensure_client_scripts()
	except Exception as e:
		check("pl_custom_field", False, f"gagal ensure: {type(e).__name__}: {str(e)[:150]}")
		raise GateAborted()

	# --- Custom Field Pick List Item sesuai spec ---
	row = frappe.db.get_value(
		"Custom Field",
		{"dt": "Pick List Item", "fieldname": PL_PICKED_FIELD},
		["fieldtype", "in_list_view", "insert_after", "default"],
		as_dict=1,
	)
	check(
		"pl_custom_field",
		bool(
			row
			and row.fieldtype == "Float"
			and int(row.in_list_view or 0) == 1
			and row.insert_after == "picked_qty"
			and not row.default
		),
		f"row={dict(row) if row else None}, want Float, in_list_view=1, "
		f"after picked_qty, tanpa default",
	)

	# --- 3 Client Script W31 + body SR W23 drift-update ---
	scripts = frappe.get_all(
		"Client Script",
		filters={"script": ("like", "%" + MARKER + "%")},
		fields=["dt", "enabled"],
	)
	se_script = frappe.get_all(
		"Client Script",
		filters={"script": ("like", "%" + SE_MARKER + "%")},
		fields=["dt", "enabled"],
	)
	batch_script = frappe.get_all(
		"Client Script",
		filters={"script": ("like", "%" + BATCH_MARKER + "%")},
		fields=["dt", "enabled"],
	)
	sr_body = frappe.db.get_value(
		"Client Script",
		{"dt": "Stock Reconciliation", "script": ("like", "%" + upgrade.SR_SCRIPT_MARKER + "%")},
		"script",
	)
	batch_body = frappe.db.get_value(
		"Client Script",
		{"dt": "Batch", "script": ("like", "%" + BATCH_MARKER + "%")},
		"script",
	)
	# Guard anchor hint Batch (temuan E2E percobaan 1): frappe.ui.form.Dashboard
	# v16 TIDAK punya properti `wrapper` (hanya `parent` + section wrapper), jadi
	# guard lama `frm.dashboard.wrapper` membuat hint selalu bail senyap.
	# Gate tak bisa merender DOM — rendering tetap milik E2E browser; yang
	# dijaga di sini adalah anchor API-nya.
	batch_anchor_ok = bool(
		batch_body
		and "dashboard.parent" in batch_body
		and "dashboard.wrapper" not in batch_body
	)
	check(
		"client_scripts",
		len(scripts) == 1
		and scripts[0].dt == "Pick List"
		and int(scripts[0].enabled or 0) == 1
		and len(se_script) == 1
		and se_script[0].dt == "Stock Entry"
		and int(se_script[0].enabled or 0) == 1
		and len(batch_script) == 1
		and batch_script[0].dt == "Batch"
		and int(batch_script[0].enabled or 0) == 1
		and sr_body == upgrade.CLIENT_SCRIPT_STOCK_RECONCILIATION
		and batch_anchor_ok,
		f"pl={[(d.dt, d.enabled) for d in scripts]}, se={[(d.dt, d.enabled) for d in se_script]}, "
		f"batch={[(d.dt, d.enabled) for d in batch_script]}, "
		f"sr_body={'persis source' if sr_body == upgrade.CLIENT_SCRIPT_STOCK_RECONCILIATION else 'BEDA'}, "
		f"batch_anchor={'dashboard.parent' if batch_anchor_ok else 'GAGAL: anchor bukan dashboard.parent'}",
	)

	skip_reason = None
	if not company:
		skip_reason = "skipped: site belum punya Company"
	elif not warehouse:
		skip_reason = f"skipped: tidak ada Warehouse utk company {company!r}"

	if skip_reason:
		for name in (
			"fixture_item",
			"fixture_stock",
			"pl_server_pure_conversion",
			"pl_passthrough_native",
			"pl_mapper_wo_noop",
			"pl_clamp_auto",
			"pl_on_submit_backfill",
			"sr_batch_row_converted",
			"sr_serial_row_skipped",
			"pl_partial_pick_auto",
			"pl_partial_pick_manual",
		):
			check(name, True, skip_reason)
	else:
		_run_pl_cases(check, stock, alt, item_group, company, warehouse)

	# --- ensure idempoten (run kedua unchanged) ---
	try:
		first_fields = upgrade.ensure_pl_fields()
		second_fields = upgrade.ensure_pl_fields()
		first_scripts = upgrade.ensure_client_scripts()
		second_scripts = upgrade.ensure_client_scripts()
		check(
			"upgrade_idempotent",
			first_fields in ("created", "updated", "unchanged")
			and second_fields == "unchanged"
			and first_scripts in ("created", "updated", "unchanged")
			and second_scripts == "unchanged",
			f"fields={first_fields!r}->{second_fields!r}, scripts={first_scripts!r}->{second_scripts!r}",
		)
	except Exception as e:
		check("upgrade_idempotent", False, f"{type(e).__name__}: {e}")


def _run_pl_cases(check, stock, alt, item_group, company, warehouse):
	"""Semua kasus PL berbagi satu item fixture + stok 48 (SE Material Receipt)."""

	# --- Fixture item (mirror make_item w21; SELALU pakai doc.name hasil insert) ---
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
				upgrade.ITEM_UOM_FIELD: alt,
			}
		)
		item.insert()
		TRACKED["item"].append(item.name)
		frappe.db.commit()
		check("fixture_item", True, f"item={item.name!r}, stock_uom={stock!r}, alt={alt!r} (faktor 12)")
	except Exception as e:
		check("fixture_item", False, f"{type(e).__name__}: {str(e)[:200]}")
		raise GateAborted()

	# --- Fixture stok: SE Material Receipt 48 unit stock @100 ---
	try:
		se = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"company": company,
				"stock_entry_type": "Material Receipt",
				"purpose": "Material Receipt",
				"items": [
					{
						"item_code": item.name,
						"qty": 48,
						"uom": stock,
						"stock_uom": stock,
						"conversion_factor": 1,
						"basic_rate": 100,
						"t_warehouse": warehouse,
					}
				],
			}
		)
		se.insert()
		se.submit()
		TRACKED["se"].append(se.name)
		frappe.db.commit()
		bin_qty = flt(
			frappe.db.get_value("Bin", {"item_code": item.name, "warehouse": warehouse}, "actual_qty")
		)
		check("fixture_stock", abs(bin_qty - 48) < 0.0001, f"se={se.name}, bin={bin_qty} (want 48)")
	except Exception as e:
		check("fixture_stock", False, f"{type(e).__name__}: {str(e)[:200]}")

	# --- Case 1: server-pure + invarian reload/resave ---
	try:
		pl1 = _make_pl(
			company,
			[_pl_row(item.name, warehouse, stock, alt, **{PL_PICKED_FIELD: 2})],
			pick_manually=1,
		)
		TRACKED["pl"].append(pl1.name)
		frappe.db.commit()
		row = _pl_items(pl1.name)[0]
		ok_first = bool(
			row
			and abs(flt(row.picked_qty) - 24) < 0.0001  # 2 x 12
			and abs(flt(row.get(PL_PICKED_FIELD)) - 2) < 0.0001
			and abs(flt(row.stock_qty) - 24) < 0.0001  # qty x faktor konsisten
			and abs(flt(row.qty) - 2) < 0.0001
		)
		reloaded = frappe.get_doc("Pick List", pl1.name)  # baca ulang dari DB
		reloaded.save()
		frappe.db.commit()
		row2 = _pl_items(pl1.name)[0]
		ok_resave = bool(
			row2
			and abs(flt(row2.picked_qty) - flt(row.picked_qty)) < 1e-9
			and abs(flt(row2.get(PL_PICKED_FIELD)) - flt(row.get(PL_PICKED_FIELD))) < 1e-9
			and abs(flt(row2.stock_qty) - flt(row.stock_qty)) < 1e-9
		)
		check(
			"pl_server_pure_conversion",
			ok_first and ok_resave,
			f"pl={pl1.name}, insert={dict(row) if row else None}, resave={dict(row2) if row2 else None}, "
			"want picked=24 (2x12), custom=2, stock_qty=24 identik pasca resave",
		)
	except Exception as e:
		check("pl_server_pure_conversion", False, f"{type(e).__name__}: {str(e)[:200]}")

	# --- Case 2: passthrough native (custom tak pernah diisi) ---
	try:
		pl2 = _make_pl(
			company,
			[_pl_row(item.name, warehouse, stock, alt, picked_qty=24)],
			pick_manually=1,
		)
		TRACKED["pl"].append(pl2.name)
		frappe.db.commit()
		row = _pl_items(pl2.name)[0]
		ok = bool(
			row
			and abs(flt(row.picked_qty) - 24) < 0.0001  # tidak berubah
			and abs(flt(row.get(PL_PICKED_FIELD)) - 2) < 0.0001  # backfill 24 / 12
		)
		check(
			"pl_passthrough_native",
			ok,
			f"pl={pl2.name}, row={dict(row) if row else None}, want picked=24 tetap, custom=2",
		)
	except Exception as e:
		check("pl_passthrough_native", False, f"{type(e).__name__}: {str(e)[:200]}")

	# --- Case 3: mapper-WO style (uom = stock_uom) -> hook no-op ---
	try:
		pl3 = _make_pl(
			company,
			[
				{
					"item_code": item.name,
					"warehouse": warehouse,
					"uom": stock,
					"stock_uom": stock,
					"conversion_factor": 1,
					"qty": 5,
					"stock_qty": 5,
					"picked_qty": 3,
				}
			],
			pick_manually=1,
		)
		TRACKED["pl"].append(pl3.name)
		frappe.db.commit()
		row = _pl_items(pl3.name)[0]
		ok = bool(
			row
			and abs(flt(row.picked_qty) - 3) < 0.0001
			and row.get(PL_PICKED_FIELD) in (None, "", 0)
		)
		check(
			"pl_mapper_wo_noop",
			ok,
			f"pl={pl3.name}, row={dict(row) if row else None}, want picked=3 utuh, custom=0/None",
		)
	except Exception as e:
		check("pl_mapper_wo_noop", False, f"{type(e).__name__}: {str(e)[:200]}")

	# --- Case 4: clamp pick_manually=0 ---
	try:
		pl4 = _make_pl(
			company,
			[_pl_row(item.name, warehouse, stock, alt, **{PL_PICKED_FIELD: 5})],
			pick_manually=0,
		)
		TRACKED["pl"].append(pl4.name)
		frappe.db.commit()
		row = _pl_items(pl4.name)[0]
		ok = bool(
			row
			and abs(flt(row.get(PL_PICKED_FIELD)) - 2) < 0.0001  # min(5, qty 2)
			and abs(flt(row.picked_qty) - 24) < 0.0001  # 2 x 12
		)
		check(
			"pl_clamp_auto",
			ok,
			f"pl={pl4.name}, row={dict(row) if row else None}, want custom=2 (clamp ke qty), picked=24",
		)
	except Exception as e:
		check("pl_clamp_auto", False, f"{type(e).__name__}: {str(e)[:200]}")

	# --- Case 5: on_submit backfill (jalur auto-fill native) ---
	try:
		pl5 = _make_pl(
			company,
			[_pl_row(item.name, warehouse, stock, alt)],
			pick_manually=1,
			scan_mode=0,
		)
		TRACKED["pl"].append(pl5.name)
		frappe.db.commit()
		# RELOAD sebelum submit (mirror alur Desk: after_save Pick List selalu
		# reload penuh): objek hasil insert menyimpan picked_qty None di memori
		# (default kolom 0.0 hanya diterapkan DB saat INSERT), sedangkan
		# auto-fill native (validate_picked_items) mensyaratkan picked_qty == 0
		# — None lolos dari cek itu dan submit "insert+submit satu tarikan"
		# tidak ter-auto-fill.
		pl5 = frappe.get_doc("Pick List", pl5.name)
		pl5.submit()
		frappe.db.commit()
		row = _pl_items(pl5.name)[0]
		ok = bool(
			row
			and abs(flt(row.picked_qty) - 24) < 0.0001  # native: picked = stock_qty
			and abs(flt(row.get(PL_PICKED_FIELD)) - 2) < 0.0001  # backfill 24 / 12
		)
		check(
			"pl_on_submit_backfill",
			ok,
			f"pl={pl5.name} (submitted), row={dict(row) if row else None}, "
			"want picked=24 (auto-fill native), custom=2 (backfill)",
		)
	except Exception as e:
		check("pl_on_submit_backfill", False, f"{type(e).__name__}: {str(e)[:200]}")

	# --- Case 6+7: SR baris batch dikonversi, serial tetap skip (fungsi murni,
	# tanpa insert dokumen — fixture serial terlalu berat utk dibuat nyata) ---
	try:
		sr = frappe.get_doc(
			{
				"doctype": "Stock Reconciliation",
				"purpose": "Stock Reconciliation",
				"company": company,
				"posting_date": nowdate(),
				"posting_time": nowtime(),
				"items": [
					{  # batch direct field: sejak W31 dikonversi seperti baris biasa
						"item_code": item.name,
						"warehouse": warehouse,
						"batch_no": PREFIX + "-BATCH",
						SR_UOM_FIELD: alt,
						SR_AFTER_FIELD: 2,
					},
					{  # serial: tetap passthrough native
						"item_code": item.name,
						"warehouse": warehouse,
						"serial_no": PREFIX + "-SN1\n" + PREFIX + "-SN2",
						SR_UOM_FIELD: alt,
						SR_AFTER_FIELD: 9,
					},
				],
			}
		)
		apply_sr_inventory_uom(sr, None)
		batch_row, serial_row = sr.items[0], sr.items[1]
		ok_batch = bool(
			abs(flt(batch_row.qty) - 24) < 0.0001  # 2 x 12
			and abs(flt(batch_row.get(SR_FACTOR_FIELD)) - 12) < 0.0001
		)
		ok_serial = bool(
			serial_row.qty in (None, "", 0)
			and serial_row.get(SR_FACTOR_FIELD) in (None, "", 0)
		)
		check(
			"sr_batch_row_converted",
			ok_batch,
			f"batch_row qty={batch_row.qty!r}, faktor={batch_row.get(SR_FACTOR_FIELD)!r}, "
			"want qty=24 (2x12), faktor=12",
		)
		check(
			"sr_serial_row_skipped",
			ok_serial,
			f"serial_row qty={serial_row.qty!r}, faktor={serial_row.get(SR_FACTOR_FIELD)!r}, "
			"want keduanya kosong (passthrough native)",
		)
	except Exception as e:
		check("sr_batch_row_converted", False, f"{type(e).__name__}: {str(e)[:200]}")
		check("sr_serial_row_skipped", False, f"{type(e).__name__}: {str(e)[:200]}")

	# --- Case 8: partial-pick mode otomatis (pick_manually=0, set_item_locations).
	# Item DEDIKASI (bukan item bersama kasus 1-5): set_item_locations native
	# mengurangi ketersediaan gudang dengan SEMUA Pick List lain atas item yang
	# sama — draft ikut terhitung (_get_pick_list_items: docstatus 0 memakai
	# stock_qty, filter hanya status != Completed/Cancelled) — plus stock_qty
	# baris ter-pick PL sendiri (update_picked_item_from_current_pick_list),
	# lalu lokasi tersedia di-nol-kan (filter_locations_by_picked_materials)
	# sehingga baris unpicked dihapus TANPA rebuild. Bin 48 item khusus:
	# 48 - 24 (stock_qty baris ter-pick sendiri) = 24 tersedia -> baris unpicked
	# (permintaan stock_qty 24) ter-rebuild penuh dengan stock_qty 24. ---
	try:
		item2 = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": PREFIX + "-" + frappe.generate_hash(length=8),
				"item_name": PREFIX + " Gate Item 2",
				"item_group": item_group,
				"stock_uom": stock,
				"is_stock_item": 1,
				"has_batch_no": 0,
				"has_serial_no": 0,
				"uoms": [{"uom": alt, "conversion_factor": 12}],
				upgrade.ITEM_UOM_FIELD: alt,
			}
		)
		item2.insert()
		TRACKED["item"].append(item2.name)
		se2 = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"company": company,
				"stock_entry_type": "Material Receipt",
				"purpose": "Material Receipt",
				"items": [
					{
						"item_code": item2.name,
						"qty": 48,
						"uom": stock,
						"stock_uom": stock,
						"conversion_factor": 1,
						"basic_rate": 100,
						"t_warehouse": warehouse,
					}
				],
			}
		)
		se2.insert()
		se2.submit()
		TRACKED["se"].append(se2.name)
		frappe.db.commit()
		pl8a = _make_pl(
			company,
			[
				_pl_row(item2.name, warehouse, stock, alt, **{PL_PICKED_FIELD: 1}),  # ter-pick
				_pl_row(item2.name, warehouse, stock, alt),  # belum dipick -> di-rebuild native
			],
			pick_manually=0,
		)
		TRACKED["pl"].append(pl8a.name)
		frappe.db.commit()
		rows = _pl_items(pl8a.name)
		picked_rows = [r for r in rows if flt(r.picked_qty) > 0]
		unpicked_rows = [r for r in rows if flt(r.picked_qty) == 0]
		ok = bool(
			len(rows) == 2
			and len(picked_rows) == 1
			and abs(flt(picked_rows[0].picked_qty) - 12) < 0.0001  # 1 x 12
			and abs(flt(picked_rows[0].get(PL_PICKED_FIELD)) - 1) < 0.0001
			and len(unpicked_rows) == 1
			and abs(flt(unpicked_rows[0].stock_qty) - 24) < 0.0001  # 48 - 24 ter-pick sendiri
			and abs(flt(unpicked_rows[0].qty) - 2) < 0.0001
		)
		check(
			"pl_partial_pick_auto",
			ok,
			f"pl={pl8a.name}, item={item2.name!r}, se={se2.name}, rows={[dict(r) for r in rows]}, "
			"want 1 baris picked=12 custom=1 + 1 baris rebuilt picked=0 stock_qty=24 (bin 48 - 24)",
		)
	except Exception as e:
		check("pl_partial_pick_auto", False, f"{type(e).__name__}: {str(e)[:200]}")

	# --- Case 9: partial-pick mode manual (pick_manually=1, tabel tak disusun ulang) ---
	try:
		pl8b = _make_pl(
			company,
			[
				_pl_row(item.name, warehouse, stock, alt, **{PL_PICKED_FIELD: 1}),
				_pl_row(item.name, warehouse, stock, alt),
			],
			pick_manually=1,
		)
		TRACKED["pl"].append(pl8b.name)
		frappe.db.commit()
		rows = _pl_items(pl8b.name)
		picked_rows = [r for r in rows if flt(r.picked_qty) > 0]
		ok = bool(
			len(rows) == 2
			and len(picked_rows) == 1
			and abs(flt(picked_rows[0].picked_qty) - 12) < 0.0001
			and abs(flt(picked_rows[0].get(PL_PICKED_FIELD)) - 1) < 0.0001
			and flt(rows[1].picked_qty) == 0
		)
		check(
			"pl_partial_pick_manual",
			ok,
			f"pl={pl8b.name}, rows={[dict(r) for r in rows]}, want baris ter-pick utuh picked=12 "
			"custom=1 + baris kedua picked=0",
		)
	except Exception as e:
		check("pl_partial_pick_manual", False, f"{type(e).__name__}: {str(e)[:200]}")


def _pl_items(pl_name):
	return frappe.get_all(
		"Pick List Item",
		filters={"parent": pl_name},
		fields=[
			"qty",
			"stock_qty",
			"picked_qty",
			"uom",
			"conversion_factor",
			PL_PICKED_FIELD,
		],
		order_by="idx",
	)


def _teardown(check):
	try:
		frappe.set_user("Administrator")
	except Exception:
		pass
	sweep_ok, sweep_evidence = _sweep()
	# Item & Batch TIDAK diikut extra_doctypes: key extra MENIMPA hitung prefix
	# bawaan guard dgn daftar tracked saja (site bisa menamai Item via series,
	# jadi hitung prefix name/item_code/item_name jauh lebih kuat).
	residue = count_residue(
		PREFIX,
		{
			"Pick List": TRACKED["pl"],
			"Stock Entry": TRACKED["se"],
			"Serial and Batch Bundle": [],
			"User": [],
		},
	)
	zero = all(v == 0 for v in residue.values())
	check(
		"teardown",
		sweep_ok and zero,
		f"{sweep_evidence}; residu {PREFIX}={residue} "
		f"(PL tracked={TRACKED['pl']}, SE tracked={TRACKED['se']})",
	)
	TRACKED.update({"pl": [], "se": [], "item": []})


def _sweep():
	"""Bersihkan residu W31: via item prefix + PL/SE native yang ter-track. Idempoten."""
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

	def delete_versions():
		# MariaDB 1020 "Record has changed since last read in tabVersion" bisa
		# kena bila transaksi gate ini memegang snapshot basi saat worker queue
		# (memproses pasca-run gate sebelumnya: cancel SE/PL, repost) menulis
		# baris Version — mulai snapshot baru dengan commit + satu retry.
		for attempt in (1, 2):
			try:
				frappe.db.commit()
				frappe.db.delete("Version", {"docname": ("like", PREFIX + "%")})
				return
			except Exception:
				if attempt == 2:
					raise
				time.sleep(0.5)

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
	# PL/SE via row item (native naming STO-PICK/MAT-STE) atau track list;
	# newest-first saat cancel (pelajaran W28)
	pl_names = set(TRACKED["pl"])
	se_names = set(TRACKED["se"])
	if items:
		pl_names.update(
			frappe.get_all("Pick List Item", filters={"item_code": ("in", items)}, pluck="parent")
		)
		se_names.update(
			frappe.get_all("Stock Entry Detail", filters={"item_code": ("in", items)}, pluck="parent")
		)
	for name in sorted(pl_names, reverse=True):
		safe(f"PL {name}", lambda n=name: cancel_delete("Pick List", n))
	for name in sorted(se_names, reverse=True):
		safe(f"SE {name}", lambda n=name: cancel_delete("Stock Entry", n))
	# SLE/Bin/Repost per item (jaga-jaga bila cancel SE tak sempat membersihkan)
	safe("SLE", lambda: frappe.db.delete("Stock Ledger Entry", {"item_code": ("in", items or [""])}) if items else None)
	safe("Repost", lambda: frappe.db.delete("Repost Item Valuation", {"item_code": ("in", items or [""])}) if items else None)
	safe("Bin", lambda: frappe.db.delete("Bin", {"item_code": ("in", items or [""])}) if items else None)
	# Item
	for name in items:
		safe(f"Item {name}", lambda n=name: frappe.delete_doc("Item", n, force=1, ignore_missing=True))
	safe("Version", delete_versions)

	return (not errors), ("bersih" if not errors else "; ".join(errors[:5]))


def _pick_uoms():
	"""Tiga UOM eksisting berbeda: (stock, alt utk tabel konversi, invalid)."""
	stock = next((u for u in ("Nos", "Unit", "Kg") if frappe.db.exists("UOM", u)), None)
	alt = next(
		(u for u in ("Box", "Pack", "Bag") if u != stock and frappe.db.exists("UOM", u)), None
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
