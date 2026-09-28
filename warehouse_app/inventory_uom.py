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
