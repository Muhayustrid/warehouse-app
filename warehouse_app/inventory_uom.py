# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto
# License: MIT

# W21 — doc-events "Default Inventory UOM" per Item (field
# custom_default_inventory_unit_of_measure) + kolom tampilan
# custom_basic_rate_per_uom di Stock Entry Detail.
#
# Batas arsitektur: validasi Item hanya menambah syarat pada field milik app
# ini — kosong = langsung lewat tanpa menyentuh alur native (impor, alur
# produksi). Perhitungan rate per UOM murni display-only, tidak pernah throw.

import frappe
from frappe import _
from frappe.utils import flt

ITEM_UOM_FIELD = "custom_default_inventory_unit_of_measure"
SE_RATE_FIELD = "custom_basic_rate_per_uom"


def validate_inventory_uom(doc, method):
	"""Item validate: Default Inventory UOM harus stock UOM atau tercantum di
	tabel UOM Conversion item tersebut."""
	value = doc.get(ITEM_UOM_FIELD)
	if not value:
		return
	allowed = {row.uom for row in (doc.get("uoms") or [])}
	if value == doc.stock_uom or value in allowed:
		return
	frappe.throw(
		_("Default Inventory UOM {0} pada Item {1} tidak valid: harus sama dengan Stock UOM, "
			"atau ditambahkan dulu ke tabel UOM Conversion item tersebut (atau dikosongkan).").format(
			frappe.bold(value), frappe.bold(doc.name)
		)
	)


def compute_rate_per_uom(doc, method):
	"""Stock Entry validate: isi kolom display Basic Rate per UOM baris
	(= Basic Rate x conversion factor). Display-only, tidak pernah throw."""
	for row in doc.get("items") or []:
		value = flt(row.get("basic_rate")) * flt(row.get("conversion_factor") or 1)
		row.set(SE_RATE_FIELD, flt(value, row.precision(SE_RATE_FIELD)))


# ------------------------------------------------------------------ W23 ----
# Stock Reconciliation: baris hitung stok boleh dicatat dalam UOM lain lewat
# kolom custom (custom_uom + custom_qty_after + custom_valuation_rate_per_uom
# + custom_qty_difference_per_uom display, spec di upgrade.py seksi W23).
# Hook before_validate mengonversinya ke field
# native qty & valuation_rate (stock UOM) SEBELUM controller validate, sehingga
# remove_items_with_no_change(), validate_uom_is_integer, dan SLE melihat nilai
# akhir hasil konversi. Baris native (custom_uom kosong) dan baris serial/batch
# tidak disentuh.
# Anti-faktor-1: faktor hanya 1 bila UOM dipilih eksplisit sama dengan stock
# UOM; UOM lain wajib tercantum di tabel UOM Conversion item — kalau tidak,
# dokumen ditolak secara atomik.

SR_UOM_FIELD = "custom_uom"
SR_FACTOR_FIELD = "custom_conversion_factor"
SR_BEFORE_FIELD = "custom_qty_before"
SR_AFTER_FIELD = "custom_qty_after"
SR_RATE_FIELD = "custom_valuation_rate_per_uom"
SR_DIFF_FIELD = "custom_qty_difference_per_uom"


def _ledger_qty(doc, row, cache):
	"""Saldo ledger item+gudang pada posting timestamp SR (mirror
	get_stock_balance_for native — dasar deteksi perubahan native). Dipakai
	UNTUK SEMUA baris: row.current_qty tidak bisa dipercaya di pass insert
	karena Document._set_defaults menerapkan DocField default "0" ke child
	row sebelum before_validate (insert programmatic selalu membawa 0.0,
	bukan None)."""
	key = (row.item_code, row.warehouse)
	if key not in cache:
		from erpnext.stock.stock_ledger import get_previous_sle

		prev = get_previous_sle(
			{
				"item_code": row.item_code,
				"warehouse": row.warehouse,
				"posting_date": doc.posting_date,
				"posting_time": doc.posting_time,
			}
		)
		cache[key] = flt(prev.get("qty_after_transaction")) if prev else 0
	return cache[key]


def apply_sr_inventory_uom(doc, method):
	"""Stock Reconciliation before_validate: Qty After & Valuation Rate per UOM
	baris dikonversi ke qty/valuation_rate native (stock UOM). Faktor bukan 1
	dihitung dari tabel UOM Conversion item — satu query untuk semua item dalam
	dokumen (mirror pola migrate_legacy_uom_field); UOM di luar tabel menolak
	dokumen secara atomik."""
	rows = doc.get("items") or []
	if not rows:
		return
	# Satu query konversi untuk semua baris yang berpotensi butuh faktor != 1.
	needs_factor = {
		row.item_code
		for row in rows
		if row.item_code
		and row.get(SR_UOM_FIELD)
		and row.get(SR_UOM_FIELD)
		!= (row.get("stock_uom") or frappe.get_cached_value("Item", row.item_code, "stock_uom"))
	}
	uoms_map = {}
	if needs_factor:
		for r in frappe.get_all(
			"UOM Conversion Detail",
			filters={"parent": ("in", sorted(needs_factor))},
			fields=["parent", "uom", "conversion_factor"],
		):
			uoms_map.setdefault(r.parent, {})[r.uom] = r.conversion_factor
	ledger_cache = {}  # (item, warehouse) -> saldo ledger, utk row tanpa current_qty

	for row in rows:
		uom = row.get(SR_UOM_FIELD)
		after = row.get(SR_AFTER_FIELD)
		# Penanda "baris memakai UOM custom" = custom_uom terisi. Layer penyimpanan
		# Frappe mengubah Float custom yang tak pernah diisi menjadi 0.0 (bukan
		# NULL) saat baris pertama disimpan — memakai custom_qty_after sebagai
		# penanda membuat draft baris-native yang di-reload lalu disimpan ulang
		# dikonversi dengan after=0 → stok terhapus diam-diam. Link (custom_uom)
		# tetap NULL, jadi dia satu-satunya penanda yang stabil lintas reload.
		if after in (None, "") or not uom:
			continue  # baris native murni / after belum diisi
		if (
			not row.item_code
			or row.get("serial_no")
			or row.get("serial_and_batch_bundle")
			# use_serial_batch_fields TIDAK masuk kondisi: form native menyalakan
			# flag ini di row baru (user default) walau item tak ber-serial/batch —
			# konversi tetap aman selama serial/bundle-nya kosong.
		):
			continue  # serial/batch = passthrough native
		stock_uom = row.get("stock_uom") or frappe.get_cached_value(
			"Item", row.item_code, "stock_uom"
		)
		if uom == stock_uom:
			factor = 1  # eksplisit sama dengan stock UOM = tanpa konversi
		else:
			factor = uoms_map.get(row.item_code, {}).get(uom)
			if not factor:
				frappe.throw(
					_("UOM {0} untuk Item {1} pada Stock Reconciliation tidak valid: harus sama "
						"dengan Stock UOM, atau ditambahkan dulu ke tabel UOM Conversion item "
						"tersebut.").format(frappe.bold(uom), frappe.bold(row.item_code))
				)
		row.set(SR_FACTOR_FIELD, factor)
		# Saldo before SELALU dari ledger pada posting timestamp — bukan
		# row.current_qty: pass insert programmatic membawa default 0.0 (lihat
		# catatan _ledger_qty), dan native sendiri mendeteksi perubahan terhadap
		# ledger pada posting date/time (get_stock_balance_for).
		current = _ledger_qty(doc, row, ledger_cache)
		before = flt(current / factor, row.precision(SR_BEFORE_FIELD))
		row.set(SR_BEFORE_FIELD, before)
		row.set("qty", flt(flt(after) * factor, row.precision("qty")))
		row.set(
			SR_DIFF_FIELD,
			flt(flt(after) - flt(before), row.precision(SR_DIFF_FIELD)),
		)
		rate = row.get(SR_RATE_FIELD)
		# 0 sah sebagai revaluasi — tapi hanya bila user eksplisit mengizinkan rate
		# nol (flag native allow_zero_valuation_rate, syarat yang sama dengan
		# "Valuation Rate required" di update_stock_ledger). Tanpa syarat ini,
		# rate yang tak pernah diisi (tersimpan 0.0) akan merevaluasi baris ke 0
		# saat draft di-reload dan disimpan ulang.
		if rate not in (None, "") and (flt(rate) != 0 or row.get("allow_zero_valuation_rate")):
			row.set("valuation_rate", flt(flt(rate) / factor, row.precision("valuation_rate")))
