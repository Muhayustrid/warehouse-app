# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto
# License: MIT

# Gate W23 — kolom UOM di Stock Reconciliation (konversi server-pure via
# before_validate; native qty/valuation_rate tetap sumber kebenaran ledger).
#
# Jalankan:
#   docker exec erpnext-new-backend-1 bench --site frontend execute \
#       warehouse_app.tests.w23_gate.run_gate
#
# Kontrak output: TEPAT satu baris GATE_JSON:{...} (ok: bool, checks: dict,
# error: opsional). Cek gagal -> ok=false TANPA raise; hanya crash tak terduga
# yang di-raise (bench exit nonzero).
#
# Yang diverifikasi:
#   1. 6 Custom Field di Stock Reconciliation Item sesuai spec (fieldtype,
#      options, read_only, in_list_view).
#   2. Client Script SR ber-marker eksis & enabled.
#   3. Happy path server-pure: baris HANYA ber-custom_uom + custom_qty_after +
#      custom_valuation_rate_per_uom (tanpa qty native) — submit menghasilkan
#      qty = after x faktor (2.5x12 = 30), valuation_rate = rate/faktor
#      (1200/12 = 100), SLE actual_qty = qty_after_transaction = 30, dan
#      custom_qty_difference_per_uom = after − before (2.5 − 0).
#   4. Rate kosong = passthrough native: valuation_rate eksplisit 90 tetap 90;
#      diff negatif tercatat (after 1 − before 2.5 = −1.5).
#   5. Rate 0 sah (allow_zero_valuation_rate) → valuation_rate 0 tersimpan.
#   6. UOM di luar tabel konversi ditolak (ValidationError menyebut UOM +
#      Conversion) dan TIDAK menyisakan SR baru.
#   7. Baris tanpa field custom tidak tersentuh hook (qty 5 & rate 50 utuh).
#   8. Qty & rate identik bin → native EmptyStockReconciliationItemsError
#      (pesan "None of the items have any change in quantity or value.").
#   9. ensure_sr_fields idempoten (run kedua "unchanged") + client script utuh.
#  10. Draft di-reload lalu disimpan ulang: baris native tetap (qty tak
#      menjadi 0) dan baris UOM rate-passthrough tetap (tak berevaluasi ke 0)
#      — regresi zero-storage Float custom.
#
# Fixture (prefix "ZZTEST-W23", TANPA user fixture): 1 Item run-unik
# (item_code hash, site boleh menimpa via naming series — pakai doc.name
# hasil insert); SR native naming SR-#### di-track saat run. Teardown di
# finally, residu prefix = 0. Alur stok fixture: 0 → 30 → 12 → 24 → 5.

import json
import time
import traceback

import frappe
from frappe.utils import flt, nowdate, nowtime

from warehouse_app import upgrade
from warehouse_app.inventory_uom import (
	SR_AFTER_FIELD,
	SR_BEFORE_FIELD,
	SR_DIFF_FIELD,
	SR_FACTOR_FIELD,
	SR_RATE_FIELD,
	SR_UOM_FIELD,
)
from warehouse_app.tests.guard import count_residue

PREFIX = "ZZTEST-W23"
MARKER = upgrade.SR_SCRIPT_MARKER
TRACKED = {"sr": [], "item": []}


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


def _make_sr(company, rows, expense_account=None):
	doc = frappe.get_doc(
		{
			"doctype": "Stock Reconciliation",
			"purpose": "Stock Reconciliation",
			"posting_date": nowdate(),
			"posting_time": nowtime(),
			"company": company,
			**({"expense_account": expense_account} if expense_account else {}),
			"items": rows,
		}
	)
	doc.insert()
	return doc


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

	# --- 5 Custom Field di Stock Reconciliation Item sesuai spec ---
	specs = {spec["fieldname"]: spec for spec in upgrade.SR_FIELD_SPECS}
	fields = frappe.get_all(
		"Custom Field",
		filters={"dt": "Stock Reconciliation Item", "fieldname": ("in", sorted(specs))},
		fields=["fieldname", "fieldtype", "options", "read_only", "in_list_view"],
	)
	by_name = {d.fieldname: d for d in fields}

	def _field_ok(fn):
		d = by_name.get(fn)
		spec = specs[fn]
		return bool(
			d
			and d.fieldtype == spec["fieldtype"]
			and (d.get("options") or None) == (spec.get("options") or None)
			and int(d.read_only or 0) == int(spec.get("read_only") or 0)
			and int(d.in_list_view or 0) == int(spec.get("in_list_view") or 0)
		)

	check(
		"sr_custom_fields",
		len(fields) == len(specs) and all(_field_ok(fn) for fn in specs),
		f"ada={sorted(by_name)}, want={sorted(specs)}",
	)

	# --- Client Script SR ber-marker, enabled ---
	enabled = frappe.db.get_value(
		"Client Script",
		{"dt": "Stock Reconciliation", "script": ("like", "%" + MARKER + "%")},
		"enabled",
	)
	check("client_script", int(enabled or 0) == 1, f"enabled={enabled!r} (marker {MARKER!r})")

	skip_reason = None
	if not company:
		skip_reason = "skipped: site belum punya Company"
	elif not warehouse:
		skip_reason = f"skipped: tidak ada Warehouse utk company {company!r}"

	if skip_reason:
		for name in (
			"fixture_item",
			"sr_server_pure_conversion",
			"rate_empty_passthrough",
			"rate_zero_allowed",
			"invalid_uom_rejected",
			"native_row_untouched",
			"no_change_throws_native",
		):
			check(name, True, skip_reason)
	else:
		_run_sr_cases(check, stock, alt, invalid, item_group, company, warehouse)

	# --- ensure_sr_fields idempoten + client script utuh ---
	try:
		first = upgrade.ensure_sr_fields()
		second = upgrade.ensure_sr_fields()
		script_row = frappe.db.get_value(
			"Client Script",
			{"dt": "Stock Reconciliation", "script": ("like", "%" + MARKER + "%")},
			["enabled", "script"],
			as_dict=1,
		)
		check(
			"upgrade_idempotent",
			first in ("created", "updated", "unchanged")
			and second == "unchanged"
			and bool(script_row)
			and int(script_row.enabled or 0) == 1
			and MARKER in (script_row.script or ""),
			f"first={first!r}, second={second!r}, script={'ada' if script_row else 'absen'}",
		)
	except Exception as e:
		check("upgrade_idempotent", False, f"{type(e).__name__}: {e}")


def _pick_expense_account(company):
	"""Environment-aware ala w21: native menganggap SR sebagai Opening Entry
	bila site belum punya SLE sama sekali (stock_reconciliation.py:984) dan
	menuntut difference account Balance Sheet — stock_adjustment_account site
	virgin adalah akun P&L. Untuk SR pertama di site kosong pakai akun
	"Temporary" (fallback: Balance Sheet non-group pertama)."""
	if frappe.db.sql("select name from `tabStock Ledger Entry` limit 1"):
		return frappe.db.get_value("Company", company, "stock_adjustment_account")
	opening = frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0, "account_type": "Temporary"},
		pluck="name",
		limit=1,
	) or frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0, "report_type": "Balance Sheet"},
		pluck="name",
		order_by="lft",
		limit=1,
	)
	return opening[0] if opening else frappe.db.get_value("Company", company, "stock_adjustment_account")


def _run_sr_cases(check, stock, alt, invalid, item_group, company, warehouse):
	"""Enam kasus SR berbagi satu item fixture; stok berkembang 0→30→12→24→5."""
	expense_account = _pick_expense_account(company)

	# --- Fixture item (mirror make_item w21) ---
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

	# --- Case 1: server-pure, TANPA qty/valuation_rate native ---
	try:
		sr1 = _make_sr(
			company,
			[
				{
					"item_code": item.name,
					"warehouse": warehouse,
					SR_UOM_FIELD: alt,
					SR_AFTER_FIELD: 2.5,
					SR_RATE_FIELD: 1200,
				}
			],
			expense_account=expense_account,
		)
		sr1.submit()
		TRACKED["sr"].append(sr1.name)
		frappe.db.commit()
		row = frappe.db.get_value(
			"Stock Reconciliation Item",
			{"parent": sr1.name},
			["qty", "valuation_rate", SR_FACTOR_FIELD, SR_AFTER_FIELD, SR_BEFORE_FIELD, SR_DIFF_FIELD],
			as_dict=1,
		)
		sle = frappe.db.get_value(
			"Stock Ledger Entry",
			{
				"voucher_type": "Stock Reconciliation",
				"voucher_no": sr1.name,
				"item_code": item.name,
				"is_cancelled": 0,
			},
			["actual_qty", "qty_after_transaction", "valuation_rate"],
			as_dict=1,
		)
		# Native SR non-batch: SLE selalu actual_qty=0 + qty_after_transaction
		# ABSOLUT (stock_reconciliation.get_sle_for_items) — pergerakan
		# direkonstruksi engine dari qty_after_transaction.
		ok = bool(
			row
			and abs(flt(row.qty) - 30) < 0.0001  # 2.5 x 12
			and abs(flt(row.valuation_rate) - 100) < 0.01  # 1200 / 12
			and abs(flt(row.get(SR_FACTOR_FIELD)) - 12) < 0.0001
			and abs(flt(row.get(SR_AFTER_FIELD)) - 2.5) < 0.0001
			and abs(flt(row.get(SR_BEFORE_FIELD))) < 0.0001  # stok awal 0
			and abs(flt(row.get(SR_DIFF_FIELD)) - 2.5) < 0.0001  # after − before
			and sle
			and abs(flt(sle.qty_after_transaction) - 30) < 0.0001
			and abs(flt(sle.valuation_rate) - 100) < 0.01
		)
		check(
			"sr_server_pure_conversion",
			ok,
			f"sr={sr1.name}, row={dict(row) if row else None}, sle={dict(sle) if sle else None}, "
			"want qty=30 (2.5x12), rate=100 (1200/12), diff=2.5",
		)
	except Exception as e:
		check("sr_server_pure_conversion", False, f"{type(e).__name__}: {str(e)[:200]}")

	# --- Case 2: rate kosong = passthrough native ---
	try:
		sr2 = _make_sr(
			company,
			[
				{
					"item_code": item.name,
					"warehouse": warehouse,
					SR_UOM_FIELD: alt,
					SR_AFTER_FIELD: 1,
					"valuation_rate": 90,  # native eksplisit, kolom custom kosong
				}
			],
			expense_account=expense_account,
		)
		sr2.submit()
		TRACKED["sr"].append(sr2.name)
		frappe.db.commit()
		row = frappe.db.get_value(
			"Stock Reconciliation Item",
			{"parent": sr2.name},
			["qty", "valuation_rate", SR_BEFORE_FIELD, SR_DIFF_FIELD],
			as_dict=1,
		)
		ok = bool(
			row
			and abs(flt(row.qty) - 12) < 0.0001
			and abs(flt(row.valuation_rate) - 90) < 0.01
			and abs(flt(row.get(SR_BEFORE_FIELD)) - 2.5) < 0.0001  # 30 / 12
			and abs(flt(row.get(SR_DIFF_FIELD)) + 1.5) < 0.0001  # 1 − 2.5
		)
		check(
			"rate_empty_passthrough",
			ok,
			f"sr={sr2.name}, row={dict(row) if row else None}, want qty=12, rate=90 tetap, "
			"before=2.5, diff=-1.5",
		)
	except Exception as e:
		check("rate_empty_passthrough", False, f"{type(e).__name__}: {str(e)[:200]}")

	# --- Case 3: rate 0 sah ---
	try:
		sr3 = _make_sr(
			company,
			[
				{
					"item_code": item.name,
					"warehouse": warehouse,
					SR_UOM_FIELD: alt,
					SR_AFTER_FIELD: 2,
					SR_RATE_FIELD: 0,
					"allow_zero_valuation_rate": 1,
				}
			],
			expense_account=expense_account,
		)
		sr3.submit()
		TRACKED["sr"].append(sr3.name)
		frappe.db.commit()
		row = frappe.db.get_value(
			"Stock Reconciliation Item", {"parent": sr3.name}, ["qty", "valuation_rate"], as_dict=1
		)
		ok = bool(row and abs(flt(row.qty) - 24) < 0.0001 and flt(row.valuation_rate) == 0)
		check(
			"rate_zero_allowed",
			ok,
			f"sr={sr3.name}, row={dict(row) if row else None}, want qty=24, rate=0",
		)
	except Exception as e:
		check("rate_zero_allowed", False, f"{type(e).__name__}: {str(e)[:200]}")

	# --- Case 4: UOM di luar tabel konversi ditolak, tak ada SR tersisa ---
	frappe.db.commit()  # rollback negative check tidak boleh menyeret fixture lain
	try:
		_make_sr(
			company,
			[
				{
					"item_code": item.name,
					"warehouse": warehouse,
					SR_UOM_FIELD: invalid,
					SR_AFTER_FIELD: 1,
				}
			],
			expense_account=expense_account,
		)
		check("invalid_uom_rejected", False, f"SR dengan UOM {invalid!r} TIDAK ditolak!")
	except frappe.ValidationError as e:
		frappe.db.rollback()
		msg = str(e)
		persisted = frappe.db.count("Stock Reconciliation Item", {"item_code": item.name})
		check(
			"invalid_uom_rejected",
			"UOM" in msg and "Conversion" in msg and persisted == 3,
			f"ValidationError: {msg[:150]}, persisted rows={persisted} (want 3)",
		)
	except Exception as e:
		frappe.db.rollback()
		check("invalid_uom_rejected", False, f"{type(e).__name__}: {str(e)[:180]}")

	# --- Case 5: baris native murni tidak tersentuh hook ---
	try:
		sr5 = _make_sr(
			company,
			[
				{
					"item_code": item.name,
					"warehouse": warehouse,
					"qty": 5,
					"valuation_rate": 50,
				}
			],
			expense_account=expense_account,
		)
		sr5.submit()
		TRACKED["sr"].append(sr5.name)
		frappe.db.commit()
		row = frappe.db.get_value(
			"Stock Reconciliation Item",
			{"parent": sr5.name},
			["qty", "valuation_rate", SR_DIFF_FIELD],
			as_dict=1,
		)
		ok = bool(
			row
			and abs(flt(row.qty) - 5) < 0.0001
			and abs(flt(row.valuation_rate) - 50) < 0.01
			# row native: kolom custom Float tak pernah diisi pun tersimpan 0.0
			# oleh layer simpan Frappe — diff 0 di sini, bukan NULL
			and row.get(SR_DIFF_FIELD) in (None, "", 0)
		)
		check(
			"native_row_untouched",
			ok,
			f"sr={sr5.name}, row={dict(row) if row else None}, want qty=5, rate=50, diff=0",
		)
	except Exception as e:
		check("native_row_untouched", False, f"{type(e).__name__}: {str(e)[:200]}")

	# --- Case 6: qty & rate identik bin → native empty-items throw ---
	frappe.db.commit()
	try:
		bin_row = frappe.db.get_value(
			"Bin",
			{"item_code": item.name, "warehouse": warehouse},
			["actual_qty", "valuation_rate"],
			as_dict=1,
		)
		if not bin_row or not flt(bin_row.actual_qty):
			check("no_change_throws_native", True, "skipped: stok fixture 0")
		else:
			# after x 12 == bin qty, rate per UOM x 12 == bin rate (tanpa perubahan)
			_make_sr(
				company,
				[
					{
						"item_code": item.name,
						"warehouse": warehouse,
						SR_UOM_FIELD: alt,
						SR_AFTER_FIELD: flt(bin_row.actual_qty) / 12,
						SR_RATE_FIELD: flt(bin_row.valuation_rate) * 12,
					}
				],
				expense_account=expense_account,
			)
			check("no_change_throws_native", False, "SR tanpa perubahan TIDAK ditolak native!")
	except frappe.ValidationError as e:
		frappe.db.rollback()
		check(
			"no_change_throws_native",
			"change in quantity or value" in str(e),
			f"EmptyStockReconciliationItemsError: {str(e)[:120]}",
		)
	except Exception as e:
		frappe.db.rollback()
		check("no_change_throws_native", False, f"{type(e).__name__}: {str(e)[:180]}")

	# --- Case 7: draft di-reload lalu disimpan ulang tak berubah (regresi
	# zero-storage: layer simpan Frappe menulis 0.0 — bukan NULL — untuk custom
	# Float yang tak pernah diisi; penanda baris custom yang stabil = custom_uom
	# Link yang tetap NULL. Dulu: baris native terkonversi qty→0 (stok terhapus
	# diam-diam) dan rate custom "kosong" tersimpan 0 → revaluasi ke 0).
	# Dua draft terpisah — satu SR tak boleh memuat item+warehouse ganda. ---
	try:
		sr7a = _make_sr(
			company,
			[
				{  # baris native murni
					"item_code": item.name,
					"warehouse": warehouse,
					"qty": 7,
					"valuation_rate": 70,
				}
			],
			expense_account=expense_account,
		)
		frappe.db.commit()
		reloaded = frappe.get_doc("Stock Reconciliation", sr7a.name)  # baca ulang dari DB
		reloaded.save()
		frappe.db.commit()
		native_row = frappe.db.get_value(
			"Stock Reconciliation Item", {"parent": sr7a.name}, ["qty", "valuation_rate"], as_dict=1
		)
		ok_native = bool(
			native_row
			and abs(flt(native_row.qty) - 7) < 0.0001  # bukan 0 — stok tak terhapus
			and abs(flt(native_row.valuation_rate) - 70) < 0.01
		)
		check(
			"reload_resave_native_safe",
			ok_native,
			f"sr={sr7a.name}, row={dict(native_row) if native_row else None}, want qty=7, rate=70",
		)
		sr7b = _make_sr(
			company,
			[
				{  # baris UOM; rate native 90 dibiarkan (rate custom tak pernah diisi)
					"item_code": item.name,
					"warehouse": warehouse,
					SR_UOM_FIELD: alt,
					SR_AFTER_FIELD: 1,
					"valuation_rate": 90,
				}
			],
			expense_account=expense_account,
		)
		frappe.db.commit()
		reloaded = frappe.get_doc("Stock Reconciliation", sr7b.name)  # baca ulang dari DB
		reloaded.save()
		frappe.db.commit()
		custom_row = frappe.db.get_value(
			"Stock Reconciliation Item",
			{"parent": sr7b.name},
			["qty", "valuation_rate", SR_AFTER_FIELD, SR_DIFF_FIELD],
			as_dict=1,
		)
		ok_custom = bool(
			custom_row
			and abs(flt(custom_row.qty) - 12) < 0.0001  # 1 x 12 tetap terkonversi
			and abs(flt(custom_row.valuation_rate) - 90) < 0.01  # passthrough tetap, bukan 0
		)
		check(
			"reload_resave_rate_safe",
			ok_custom,
			f"sr={sr7b.name}, row={dict(custom_row) if custom_row else None}, "
			"want qty=12, rate=90 (bukan 0)",
		)
	except Exception as e:
		check("reload_resave_native_safe", False, f"{type(e).__name__}: {str(e)[:200]}")
		check("reload_resave_rate_safe", False, f"{type(e).__name__}: {str(e)[:200]}")


def _teardown(check):
	try:
		frappe.set_user("Administrator")
	except Exception:
		pass
	sweep_ok, sweep_evidence = _sweep()
	residue = count_residue(PREFIX, {"Stock Reconciliation": TRACKED["sr"]})
	zero = all(v == 0 for v in residue.values())
	check(
		"teardown",
		sweep_ok and zero,
		f"{sweep_evidence}; residu {PREFIX}={residue} (SR tracked={TRACKED['sr']})",
	)
	TRACKED.update({"sr": [], "item": []})


def _sweep():
	"""Bersihkan residu W23: via item prefix + SR native yang ter-track. Idempoten."""
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
		# W31: MariaDB 1020 "Record has changed since last read in tabVersion"
		# bisa kena bila transaksi gate ini memegang snapshot basi saat worker
		# queue (memproses pasca-run gate sebelumnya, mis. cancel SE/PL + repost
		# dari gate W31 yang kini berjalan sebelum gate ini di pipeline) menulis
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
	# SR via row item (native naming SR-####) atau track list
	sr_names = set(TRACKED["sr"])
	if items:
		sr_names.update(
			frappe.get_all("Stock Reconciliation Item", filters={"item_code": ("in", items)}, pluck="parent")
		)
	for name in sr_names:
		safe(f"SR {name}", lambda n=name: cancel_delete("Stock Reconciliation", n))
	# SLE/Bin/Repost per item (jaga-jaga bila cancel SR tak sempat membersihkan)
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
