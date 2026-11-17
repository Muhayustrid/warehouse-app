# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""Seed dummy Sales Orders (dry + frozen) for end-to-end testing.

Run: bench --site <site> execute warehouse_app.warehouse_app.fulfillment.seed_dummy_so.seed
Picks only items whose Bin actually has stock (pick list needs availability),
classifies dry/frozen via the app's own profile, then creates and submits
4 SOs tagged po_no = "DUMMY-SEED" (easy cleanup later).
"""

from __future__ import annotations

import frappe
from frappe.utils import nowdate
from frappe.utils import flt

from warehouse_app.warehouse_app.fulfillment.classification import classify
from warehouse_app.warehouse_app.fulfillment.profile import (
    PROFILE,
    get_profile,
    resolve_frozen,
)

PO_NO = "DUMMY-SEED"


def _pick_items(frozen: set[str], company: str, per_cat: int = 6) -> dict[str, list[dict]]:
	"""Items with real available stock per (warehouse, item); classified dry/frozen."""
	bins = frappe.get_all(
		"Bin",
		fields=["item_code", "warehouse", "actual_qty", "reserved_qty"],
	)
	# Only warehouses belonging to the company's own warehouses set.
	valid_wh = set(
		frappe.get_all("Warehouse", filters={"company": company}, pluck="name")
	)
	available = {}
	for b in bins:
		if b.warehouse not in valid_wh:
			continue
		free = flt(b.actual_qty) - flt(b.reserved_qty)
		if free >= 10:
			available[(b.item_code, b.warehouse)] = free
	# item_code -> (item_group, stock_uom)
	items = frappe.get_all(
		"Item",
		filters={"disabled": 0, "is_stock_item": 1, "is_sales_item": 1},
		fields=["name", "item_group", "stock_uom"],
	)
	info = {i.name: i for i in items}

	out: dict[str, list[dict]] = {"dry": [], "frozen": []}
	for (code, wh), free in available.items():
		meta = info.get(code)
		if not meta:
			continue
		try:
			cat = classify(meta.item_group, frozen, item_code=code)
		except Exception:
			continue  # item without a valid group: skip, don't guess
		out[cat].append(
			{
				"item_code": code,
				"item_name": frappe.db.get_value("Item", code, "item_name") or code,
				"warehouse": wh,
				"uom": meta.stock_uom,
				"max_qty": free,
			}
		)

	for cat in out:
		out[cat].sort(key=lambda r: -r["max_qty"])
		out[cat] = out[cat][: per_cat * 3]
	return out


def _so_lines(rows: list[dict], company: str) -> list[dict]:
	lines = []
	for r in rows:
		qty = min(10, int(r["max_qty"]))
		lines.append(
			{
				"item_code": r["item_code"],
				"item_name": r["item_name"],
				"qty": qty,
				"uom": r["uom"],
				"stock_uom": r["uom"],
				"conversion_factor": 1.0,
				"warehouse": r["warehouse"],
				"rate": 1000,
				"delivery_date": nowdate(),
			}
		)
	return lines


def _make_so(company: str, customer: str, label: str, rows: list[dict]) -> str:
	so = frappe.get_doc(
		{
			"doctype": "Sales Order",
			"customer": customer,
			"company": company,
			"transaction_date": nowdate(),
			"delivery_date": nowdate(),
			"po_no": f"{PO_NO} {label}",
			"items": _so_lines(rows, company),
		}
	)
	so.insert(ignore_permissions=True)
	so.submit()
	return so.name


def seed():
	companies = frappe.get_all(PROFILE, pluck="company", limit=1)
	if not companies:
		frappe.throw("No Warehouse Fulfillment Profile configured.")
	company = companies[0]
	profile = get_profile(company)
	frozen = resolve_frozen(profile)
	if not frozen:
		frappe.throw("Frozen Item Group is not configured for company " + company)

	customers = frappe.get_list(
		"Customer", filters={"disabled": 0}, fields=["name"], limit_page_length=5
	)
	if not customers:
		frappe.throw("No customer exists; create one first.")
	cust = customers[0].name

	pool = _pick_items(frozen, company)
	dry, froz = pool["dry"], pool["frozen"]
	if len(dry) < 4 or len(froz) < 3:
		frappe.throw(
			f"Not enough stock-bearing items: dry={len(dry)} frozen={len(froz)}. "
			"Create stock (Material Receipt/RECO) first."
		)

	plans = [
		("DRY-1", dry[0:5]),
		("DRY-2", dry[5:10]),
		("FROZEN-1", froz[0:4]),
		("MIX-1", dry[10:12] + froz[4:7]),
	]
	created = []
	for label, rows in plans:
		if not rows:
			continue
		created.append(_make_so(company, cust, label, rows))

	frappe.db.commit()
	print("SO dummy created (submitted):")
	for name in created:
		print(" -", name)
	print("po_no prefix:", PO_NO, "| customer:", cust, "| company:", company)
	print("Stock note: all rows use warehouses with real available stock.")
