# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto
# License: MIT

import math
import frappe
from frappe import _
from frappe.utils import cint, flt

try:
	from frappe.utils import nowtime
except ImportError:
	nowtime = None

from erpnext.stock.doctype.stock_reconciliation.stock_reconciliation import (
	get_items as native_get_items,
)
from warehouse_app.inventory_uom import ITEM_UOM_FIELD
from warehouse_app.sr_access import assert_sr_access
from warehouse_app import sr_uom
from warehouse_app.sr_uom import (
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
	assert_sr_access("write", warehouse=warehouse, company=company, require_warehouse=True)
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
			or row.get("current_serial_no")
			or row.get("serial_and_batch_bundle")
			or row.get("current_serial_and_batch_bundle")
		):
			continue
		item = items.get(code)
		if not item or item.get("has_serial_no"):
			continue
		stock_uom = item.get("stock_uom") or row.get("stock_uom")
		custom_uom = item.get(ITEM_UOM_FIELD) or stock_uom
		if not custom_uom:
			continue
		candidates.append((row, code, custom_uom, stock_uom))

	if not candidates:
		return res

	pairs = [(code, custom_uom, stock_uom) for (row, code, custom_uom, stock_uom) in candidates]
	factors = sr_uom.resolve_factors(pairs)
	prec = sr_uom.precisions()

	for row, code, custom_uom, stock_uom in candidates:
		factor = factors.get((code, custom_uom))
		if factor is None:
			uom = stock_uom
			factor = 1.0
		else:
			uom = custom_uom

		computed = sr_uom.compute_row(
			factor=factor,
			ledger_qty=row.get("qty"),
			qty_after=None,
			qty=row.get("qty"),
			valuation_rate=row.get("valuation_rate"),
			prec=prec,
		)

		row[SR_UOM_FIELD] = uom
		row[SR_FACTOR_FIELD] = factor
		row[SR_BEFORE_FIELD] = computed["custom_qty_before"]
		row[SR_AFTER_FIELD] = None
		row[SR_DIFF_FIELD] = None
		if computed["custom_valuation_rate_per_uom"] is not None:
			row[SR_RATE_FIELD] = computed["custom_valuation_rate_per_uom"]

	return res


def _coerce_numeric(val, field_label: str) -> float | None:
	if val in (None, "", "null", "undefined"):
		return None
	parsed = None
	if isinstance(val, (int, float)):
		parsed = float(val)
	elif isinstance(val, str):
		cleaned = val.strip()
		if cleaned in ("", "null", "undefined"):
			return None
		try:
			parsed = float(cleaned)
		except ValueError:
			frappe.throw(_("Nilai untuk {0} tidak valid: harus berupa angka.").format(field_label))
	else:
		try:
			parsed = float(val)
		except (ValueError, TypeError):
			frappe.throw(_("Nilai untuk {0} tidak valid: harus berupa angka.").format(field_label))

	if parsed is not None and not math.isfinite(parsed):
		frappe.throw(_("Nilai untuk {0} tidak valid: harus berupa angka.").format(field_label))

	return parsed


@frappe.whitelist(methods=["POST"])
def compute_row(
	item_code,
	warehouse,
	posting_date,
	posting_time=None,
	uom=None,
	qty_after=None,
	rate_per_uom=None,
	qty=None,
	valuation_rate=None,
	allow_zero_valuation_rate=0,
	batch_no=None,
	company=None,
	set_posting_time=0,
	omit_confirmation=0,
) -> dict:
	"""Compute per-UOM conversion and native values for a single Stock Reconciliation row."""
	assert_sr_access("write", warehouse=warehouse, company=company, require_warehouse=True)

	if not item_code:
		frappe.throw(_("Item Code wajib diisi."))
	if not warehouse:
		frappe.throw(_("Warehouse wajib diisi."))
	if not posting_date:
		frappe.throw(_("Posting Date wajib diisi."))
	if not uom:
		frappe.throw(_("UOM wajib diisi."))

	qty_after = _coerce_numeric(qty_after, "Qty After")
	rate_per_uom = _coerce_numeric(rate_per_uom, "Rate per UOM")
	qty = _coerce_numeric(qty, "Qty")
	valuation_rate = _coerce_numeric(valuation_rate, "Valuation Rate")
	allow_zero = (
		bool(cint(allow_zero_valuation_rate))
		if allow_zero_valuation_rate not in (None, "", "null", "undefined")
		else False
	)
	clean_batch = (
		batch_no.strip()
		if isinstance(batch_no, str) and batch_no.strip() not in ("", "null", "undefined")
		else None
	)

	if not posting_time:
		posting_time = nowtime() if callable(nowtime) else "00:00:00"

	stock_uom = frappe.get_cached_value("Item", item_code, "stock_uom")
	factors = sr_uom.resolve_factors([(item_code, uom, stock_uom)])
	factor = factors.get((item_code, uom))
	if factor is None:
		frappe.throw(
			_("UOM {0} untuk Item {1} pada Stock Reconciliation tidak valid: harus sama "
			  "dengan Stock UOM, atau ditambahkan dulu ke tabel UOM Conversion item "
			  "tersebut.").format(frappe.bold(uom), frappe.bold(item_code))
		)

	ledger = sr_uom.ledger_qty(
		item_code, warehouse, posting_date, posting_time, {}, batch_no=clean_batch
	)
	prec = sr_uom.precisions()

	res = sr_uom.compute_row(
		factor=factor,
		ledger_qty=ledger,
		qty_after=qty_after,
		rate_per_uom=rate_per_uom,
		qty=qty,
		valuation_rate=valuation_rate,
		allow_zero_valuation_rate=allow_zero,
		prec=prec,
		stock_uom=stock_uom,
	)
	res[SR_UOM_FIELD] = uom

	confirmation = None
	if qty_after is not None and not cint(omit_confirmation):
		confirmation = sr_uom.count_confirmation(
			company=company,
			item_code=item_code,
			warehouse=warehouse,
			posting_date=posting_date,
			posting_time=posting_time,
			set_posting_time=set_posting_time,
			uom=uom,
			factor=factor,
			batch_no=clean_batch,
		)
	res[sr_uom.SR_CONFIRMATION_FIELD] = confirmation
	return res
