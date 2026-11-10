# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""Disposable R0 fixtures for F2. Only runs on fulfillment.localhost."""

from __future__ import annotations

import frappe
from frappe.utils import add_days, flt, today

from warehouse_app.tests.w49_f1_fixture import (
	COMPANY,
	COMPANY_ABBR,
	CUSTOMER,
	DRY_GROUP,
	FROZEN_CHILD,
	PROFILE,
	WAREHOUSE,
	bootstrap_base,
	guard_site,
)

R0_DRY = "ZZTEST-W49-R0-DRY"
R0_FROZEN = "ZZTEST-W49-R0-FROZEN"
R0_BOX = "ZZTEST-W49-R0-BOX"
R0_BATCH = "ZZTEST-W49-R0-BATCH"
R0_STOCK_MARKER = "ZZTEST-W49-R0 stock"
_previous_serial_batch = None
SO_MARKERS = {
	"mixed": "ZZTEST-W49-R0-SO-MIXED",
	"dry": "ZZTEST-W49-R0-SO-DRY",
	"frozen": "ZZTEST-W49-R0-SO-FROZEN",
}


def seed_r0() -> dict:
	guard_site()
	global _previous_serial_batch
	base = bootstrap_base()
	cleanup_r0()
	_ensure_profile()
	_previous_serial_batch = frappe.db.get_single_value(
		"Stock Settings", "enable_serial_and_batch_no_for_item"
	)
	frappe.db.set_single_value("Stock Settings", "enable_serial_and_batch_no_for_item", 1)
	frappe.db.commit()

	_ensure_item(R0_DRY, DRY_GROUP)
	_ensure_item(R0_FROZEN, FROZEN_CHILD, has_batch_no=1)
	_ensure_item(R0_BOX, DRY_GROUP, uoms=[{"uom": "Box", "conversion_factor": 12}])
	_ensure_stock()

	sales_orders = {
		"mixed": _create_so(
			SO_MARKERS["mixed"],
			[
				(R0_DRY, 10, "Nos", 1),
				(R0_FROZEN, 10, "Nos", 1),
				(R0_BOX, 2, "Box", 12),
				(R0_DRY, 5, "Nos", 1),
			],
		),
		"dry": _create_so(SO_MARKERS["dry"], [(R0_DRY, 5, "Nos", 1)]),
		"frozen": _create_so(SO_MARKERS["frozen"], [(R0_FROZEN, 5, "Nos", 1)]),
	}
	frappe.db.commit()
	return {
		**base,
		"items": {"dry": R0_DRY, "frozen": R0_FROZEN, "box": R0_BOX},
		"batch": R0_BATCH,
		"sales_orders": sales_orders,
	}


def cleanup_r0() -> dict:
	global _previous_serial_batch
	guard_site()
	deleted = {"packing_slips": 0, "delivery_notes": 0, "pick_lists": 0, "sales_orders": 0, "stock_entries": 0, "batches": 0, "items": 0}

	dn_names = _dn_names()
	ps_names = (
		frappe.get_all(
			"Packing Slip",
			filters={"delivery_note": ("in", dn_names)},
			pluck="name",
		)
		if dn_names
		else []
	)
	pl_names = _pl_names()
	so_names = _so_names()

	deleted["packing_slips"] = _cancel_delete("Packing Slip", ps_names)
	deleted["delivery_notes"] = _cancel_delete("Delivery Note", dn_names)
	deleted["pick_lists"] = _cancel_delete("Pick List", pl_names)
	deleted["sales_orders"] = _cancel_delete("Sales Order", so_names)
	deleted["stock_entries"] = _cancel_delete(
		"Stock Entry",
		frappe.get_all("Stock Entry", filters={"remarks": R0_STOCK_MARKER}, pluck="name"),
	)

	if frappe.db.exists("Batch", R0_BATCH):
		frappe.delete_doc("Batch", R0_BATCH, force=1, ignore_permissions=True, ignore_missing=True)
		deleted["batches"] = 1
	for item_code in (R0_DRY, R0_FROZEN, R0_BOX):
		if frappe.db.exists("Item", item_code):
			frappe.delete_doc("Item", item_code, force=1, ignore_permissions=True, ignore_missing=True)
			deleted["items"] += 1
	if _previous_serial_batch is not None:
		frappe.db.set_single_value(
			"Stock Settings", "enable_serial_and_batch_no_for_item", _previous_serial_batch
		)
		_previous_serial_batch = None
	frappe.db.commit()
	return deleted


def verify_r0() -> dict:
	guard_site()
	return {
		"items": {
			code: frappe.db.exists("Item", code) for code in (R0_DRY, R0_FROZEN, R0_BOX)
		},
		"stock": {
			code: flt(
				frappe.db.get_value(
					"Bin", {"item_code": code, "warehouse": WAREHOUSE}, "actual_qty"
				)
			)
			for code in (R0_DRY, R0_FROZEN, R0_BOX)
		},
		"sales_orders": {
			name: frappe.db.get_value("Sales Order", name, "docstatus") or 0
			for name in _so_names()
		},
	}


def _so_names() -> list[str]:
	return frappe.get_all(
		"Sales Order",
		filters={"customer": CUSTOMER, "po_no": ("in", list(SO_MARKERS.values()))},
		pluck="name",
	)


def _pl_names() -> list[str]:
	so_names = _so_names()
	if not so_names:
		return []
	return frappe.get_all(
		"Pick List Item",
		filters={"sales_order": ("in", so_names)},
		pluck="parent",
		distinct=True,
	)


def _dn_names() -> list[str]:
	so_names = _so_names()
	if not so_names:
		return []
	return frappe.get_all(
		"Delivery Note Item",
		filters={"against_sales_order": ("in", so_names)},
		pluck="parent",
		distinct=True,
	)


def _ensure_profile() -> None:
	existing = frappe.db.get_value(PROFILE, {"company": COMPANY}, "name")
	profile = frappe.get_doc(PROFILE, existing) if existing else frappe.get_doc(
		{"doctype": PROFILE, "company": COMPANY}
	)
	profile.enabled = 1
	profile.frozen_item_group = FROZEN_CHILD
	profile.include_child_item_groups = 1
	profile.save(ignore_permissions=True) if existing else profile.insert(ignore_permissions=True)


def _ensure_item(item_code: str, item_group: str, has_batch_no: int = 0, uoms=None) -> str:
	if frappe.db.exists("Item", item_code):
		return item_code
	doc = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": item_code,
			"item_name": item_code,
			"item_group": item_group,
			"stock_uom": "Nos",
			"is_stock_item": 1,
			"has_batch_no": has_batch_no,
			"uoms": uoms or [],
		}
	)
	doc.insert(ignore_permissions=True)
	return item_code


def _ensure_stock() -> None:
	if frappe.db.exists("Stock Entry", {"remarks": R0_STOCK_MARKER, "docstatus": 1}):
		return
	if not frappe.db.exists("Batch", R0_BATCH):
		frappe.get_doc(
			{
				"doctype": "Batch",
				"batch_id": R0_BATCH,
				"item": R0_FROZEN,
				"manufacturing_date": today(),
				"expiry_date": add_days(today(), 30),
			}
		).insert(ignore_permissions=True)

	company = frappe.get_doc("Company", COMPANY)
	expense_account = company.stock_adjustment_account or frappe.db.get_value(
		"Account", {"company": COMPANY, "account_name": "Stock Adjustment", "is_group": 0}, "name"
	)
	doc = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Receipt",
			"company": COMPANY,
			"remarks": R0_STOCK_MARKER,
			"use_serial_batch_fields": 1,
			"items": [
				{
					"item_code": R0_DRY,
					"qty": 200,
					"uom": "Nos",
					"conversion_factor": 1,
					"basic_rate": 100,
					"t_warehouse": WAREHOUSE,
					"expense_account": expense_account,
				},
				{
					"item_code": R0_FROZEN,
					"qty": 200,
					"uom": "Nos",
					"conversion_factor": 1,
					"basic_rate": 100,
					"t_warehouse": WAREHOUSE,
					"batch_no": R0_BATCH,
					"expense_account": expense_account,
				},
				{
					"item_code": R0_BOX,
					"qty": 200,
					"uom": "Nos",
					"conversion_factor": 1,
					"basic_rate": 100,
					"t_warehouse": WAREHOUSE,
					"expense_account": expense_account,
				},
			],
		}
	)
	doc.insert(ignore_permissions=True)
	doc.submit()


def _create_so(marker: str, rows: list[tuple[str, float, str, float]]) -> str:
	customer = frappe.db.get_value("Customer", {"customer_name": CUSTOMER}, "name")
	delivery_date = add_days(today(), 7)
	so = frappe.get_doc(
		{
			"doctype": "Sales Order",
			"customer": customer,
			"company": COMPANY,
			"transaction_date": today(),
			"delivery_date": delivery_date,
			"selling_price_list": "Standard Selling",
			"currency": "IDR",
			"conversion_rate": 1,
			"plc_conversion_rate": 1,
			"set_warehouse": WAREHOUSE,
			"po_no": marker,
			"items": [
				{
					"item_code": item_code,
					"qty": qty,
					"rate": 100,
					"price_list_rate": 100,
					"uom": uom,
					"conversion_factor": conversion_factor,
					"warehouse": WAREHOUSE,
					"delivery_date": delivery_date,
				}
				for item_code, qty, uom, conversion_factor in rows
			],
		}
	)
	so.insert(ignore_permissions=True)
	so.submit()
	return so.name


def _cancel_delete(doctype: str, names: list[str]) -> int:
	deleted = 0
	for name in names:
		if not frappe.db.exists(doctype, name):
			continue
		doc = frappe.get_doc(doctype, name)
		if doc.docstatus == 1:
			doc.cancel()
		frappe.delete_doc(doctype, name, force=1, ignore_permissions=True, ignore_missing=True)
		deleted += 1
	return deleted
