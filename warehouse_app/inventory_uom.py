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
# kolom custom (custom_uom + custom_qty_after + custom_valuation_rate_per_uom,
# spec di upgrade.py seksi W23). Hook before_validate mengonversinya ke field
# native qty & valuation_rate (stock UOM) SEBELUM controller validate, sehingga
# remove_items_with_no_change(), validate_uom_is_integer, dan SLE melihat nilai
# akhir hasil konversi. Baris tanpa custom_qty_after dan baris serial/batch =
# native murni, tidak disentuh.
# Anti-faktor-1: faktor hanya 1 bila UOM kosong (semantik "kosong = stock UOM")
# atau memang sama dengan stock UOM; UOM lain wajib tercantum di tabel
# UOM Conversion item — kalau tidak, dokumen ditolak secara atomik.

SR_UOM_FIELD = "custom_uom"
SR_FACTOR_FIELD = "custom_conversion_factor"
SR_BEFORE_FIELD = "custom_qty_before"
SR_AFTER_FIELD = "custom_qty_after"
SR_RATE_FIELD = "custom_valuation_rate_per_uom"


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

	for row in rows:
		after = row.get(SR_AFTER_FIELD)
		if after in (None, ""):
			continue  # kolom UOM tidak dipakai — baris native murni
		if (
			not row.item_code
			or row.get("serial_no")
			or row.get("serial_and_batch_bundle")
			or row.get("use_serial_batch_fields")
		):
			continue  # serial/batch = passthrough native
		uom = row.get(SR_UOM_FIELD)
		stock_uom = row.get("stock_uom") or frappe.get_cached_value(
			"Item", row.item_code, "stock_uom"
		)
		if not uom or uom == stock_uom:
			factor = 1  # kosong / sama dengan stock UOM = tanpa konversi
		else:
			factor = uoms_map.get(row.item_code, {}).get(uom)
			if not factor:
				frappe.throw(
					_("UOM {0} untuk Item {1} pada Stock Reconciliation tidak valid: harus sama "
						"dengan Stock UOM, atau ditambahkan dulu ke tabel UOM Conversion item "
						"tersebut.").format(frappe.bold(uom), frappe.bold(row.item_code))
				)
		row.set(SR_FACTOR_FIELD, factor)
		if row.get("current_qty") is not None:
			row.set(SR_BEFORE_FIELD, flt(flt(row.current_qty) / factor, row.precision(SR_BEFORE_FIELD)))
		row.set("qty", flt(flt(after) * factor, row.precision("qty")))
		rate = row.get(SR_RATE_FIELD)
		if rate is not None:  # 0 sah (revaluasi) — hanya None yang lolos native
			row.set("valuation_rate", flt(flt(rate) / factor, row.precision("valuation_rate")))
