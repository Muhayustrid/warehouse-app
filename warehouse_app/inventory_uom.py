# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto
# License: MIT

# W21 — doc-events "Default Inventory UOM" per Item (field
# custom_default_inventory_unit_of_measure) + kolom
# custom_basic_rate_per_uom di Stock Entry Detail.
#
# Batas arsitektur: validasi Item hanya menambah syarat pada field milik app
# ini — kosong = langsung lewat tanpa menyentuh alur native (impor, alur
# produksi). Selaraskan rate per UOM <-> basic_rate native tidak pernah throw.

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
	"""Stock Entry validate (W32): selaraskan Basic Rate (as per UOM) dan
	Basic Rate native (stock UOM) dengan aturan ASIMETRIS anti silent-zero
	(Currency custom yang tak diisi tersimpan 0.0, bukan NULL):
	(1) custom > 0 dan basic_rate <= 0 -> basic_rate = custom / faktor
	    (input per-UOM men-drive native — jalur input gudang);
	(2) selain itu custom = basic_rate x faktor (backfill display — baris
	    native/programmatic yang hanya mengisi basic_rate tetap konsisten,
	    native menang bila keduanya terisi tak konsisten).
	Tidak pernah throw; hook jalan setelah controller validate."""
	for row in doc.get("items") or []:
		factor = flt(row.get("conversion_factor") or 1)
		custom = flt(row.get(SE_RATE_FIELD))
		basic = flt(row.get("basic_rate"))
		if custom > 0 and basic <= 0:
			row.set("basic_rate", flt(custom / factor, row.precision("basic_rate")))
		else:
			row.set(SE_RATE_FIELD, flt(basic * factor, row.precision(SE_RATE_FIELD)))


# ------------------------------------------------------------------ W31 ----
# Pick List: picking boleh dicatat dalam UOM baris (default = Default Inventory
# UOM item, W21) lewat custom_picked_qty; picked_qty native tetap selalu stock
# UOM karena dipakai validate_stock_qty, cap set_item_locations (before_save,
# pick_manually = 0), dan pembuatan bundle on_submit. Hook before_validate
# menjaga keduanya selaras SEBELUM controller validate (doc_events custom jalan
# lebih dulu; controller Pick List tidak punya before_validate sendiri).
# after_save klien melakukan reload penuh — semua nilai wajib persist di DB.

PL_PICKED_FIELD = "custom_picked_qty"


def apply_pl_inventory_uom(doc, method):
	"""Pick List before_validate: selaraskan custom_picked_qty (UOM baris) dan
	picked_qty (stock UOM). Aturan ASIMETRIS anti silent-zero (Float custom yang
	tak pernah diisi tersimpan 0.0, bukan NULL):
	(1) custom > 0 -> picked_qty = custom x faktor (precision row);
	(2) elif picked_qty > 0 -> backfill custom = picked / faktor HANYA bila
	    hasil pembulatan != 0 (picked tidak pernah ditimpa);
	(3) else no-op (0 = belum dipick, netral native).
	Baris native (tanpa uom / uom == stock_uom, mis. mapper Work Order) tidak
	disentuh. pick_manually = 0: custom di-clamp ke qty baris (mirror cap native
	lalu recompute picked)."""
	for row in doc.get("locations") or []:
		if not row.item_code:
			continue
		stock_uom = row.get("stock_uom") or frappe.get_cached_value("Item", row.item_code, "stock_uom")
		uom = row.get("uom")
		if not uom or uom == stock_uom:
			continue  # baris native murni: hook no-op
		factor = flt(row.get("conversion_factor"))
		if factor <= 0:
			frappe.throw(
				_("UOM {0} untuk Item {1} pada Pick List tidak valid: conversion factor kosong atau nol, "
					"periksa tabel UOM Conversion pada item tersebut.").format(
					frappe.bold(uom), frappe.bold(row.item_code)
				)
			)
		custom = flt(row.get(PL_PICKED_FIELD))
		picked = flt(row.get("picked_qty"))
		if custom > 0:
			qty = flt(row.get("qty"))
			# mirror cap set_item_locations: picked tak boleh melebihi permintaan
			# baris saat gudang tidak memilih manual
			if not doc.get("pick_manually") and qty > 0 and custom > qty:
				custom = qty
				row.set(PL_PICKED_FIELD, custom)
			row.set("picked_qty", flt(custom * factor, row.precision("picked_qty")))
		elif picked > 0:
			value = flt(picked / factor, row.precision(PL_PICKED_FIELD))
			if value:  # pembulatan 0 = terlalu kecil utk direpresentasikan: biarkan 0
				row.set(PL_PICKED_FIELD, value)


def _pl_backfill(doc, method):
	"""Pick List on_submit: jalur auto-fill native (scan_mode 0 dan picked 0 ->
	picked_qty = stock_qty di before_submit) tidak melewati hook konversi —
	isi customnya di sini agar submit tetap meninggalkan pasangan konsisten."""
	for row in doc.get("locations") or []:
		if not row.item_code:
			continue
		stock_uom = row.get("stock_uom") or frappe.get_cached_value("Item", row.item_code, "stock_uom")
		uom = row.get("uom")
		if not uom or uom == stock_uom:
			continue
		if flt(row.get("picked_qty")) <= 0 or flt(row.get(PL_PICKED_FIELD)) > 0:
			continue
		factor = flt(row.get("conversion_factor"))
		if factor <= 0:
			continue
		value = flt(flt(row.get("picked_qty")) / factor, row.precision(PL_PICKED_FIELD))
		if value:
			row.db_set(PL_PICKED_FIELD, value, update_modified=False)
