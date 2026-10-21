# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto
# License: MIT

import frappe
from frappe.utils import flt

from erpnext.stock.doctype.stock_reconciliation.stock_reconciliation import (
	get_items as native_get_items,
)
from warehouse_app.inventory_uom import (
	ITEM_UOM_FIELD,
	SR_AFTER_FIELD,
	SR_BEFORE_FIELD,
	SR_DIFF_FIELD,
	SR_FACTOR_FIELD,
	SR_RATE_FIELD,
	SR_UOM_FIELD,
)


@frappe.whitelist()
def get_items(warehouse, posting_date, posting_time, company, item_code=None, ignore_empty_stock=False):
	"""Override of native get_items: returns pre-computed custom UOM columns."""
	res = native_get_items(
		warehouse,
		posting_date,
		posting_time,
		company,
		item_code=item_code,
		ignore_empty_stock=ignore_empty_stock,
	)
	if not res:
		return res

	item_codes = sorted({row["item_code"] for row in res if row.get("item_code")})
	if not item_codes:
		return res

	items = {
		d.name: d
		for d in frappe.get_all(
			"Item",
			filters={"name": ("in", item_codes)},
			fields=[
				"name",
				"stock_uom",
				"has_batch_no",
				"has_serial_no",
				ITEM_UOM_FIELD,
			],
		)
	}

	candidates = []
	for row in res:
		code = row.get("item_code")
		if (
			not code
			or row.get("serial_no")
			or row.get("batch_no")
			or row.get("current_serial_no")
			or row.get("serial_and_batch_bundle")
		):
			continue
		item = items.get(code)
		if not item or item.has_serial_no or item.has_batch_no:
			continue
		custom_uom = item.get(ITEM_UOM_FIELD)
		stock_uom = item.stock_uom or row.get("stock_uom")
		if not custom_uom or custom_uom == stock_uom:
			continue
		candidates.append((row, item, custom_uom))

	if not candidates:
		return res

	parent_items = sorted({c[1].name for c in candidates})
	factors = {}
	for d in frappe.get_all(
		"UOM Conversion Detail",
		filters={"parent": ("in", parent_items)},
		fields=["parent", "uom", "conversion_factor"],
	):
		factors[(d.parent, d.uom)] = flt(d.conversion_factor)

	for row, item, custom_uom in candidates:
		factor = factors.get((item.name, custom_uom))
		if not factor or factor <= 0:
			continue

		qty = flt(row.get("qty"))
		before = flt(qty / factor, 3)
		row[SR_UOM_FIELD] = custom_uom
		row[SR_FACTOR_FIELD] = factor
		row[SR_BEFORE_FIELD] = before
		row[SR_AFTER_FIELD] = before
		row[SR_DIFF_FIELD] = 0.0

		val_rate = row.get("valuation_rate")
		if val_rate not in (None, "") and flt(val_rate) > 0:
			row[SR_RATE_FIELD] = flt(flt(val_rate) * factor, 2)

	return res
