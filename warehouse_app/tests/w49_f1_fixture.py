# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""F1 test-site fixtures. Only runs on the disposable fulfillment site."""

from __future__ import annotations

import frappe

SITE = "fulfillment.localhost"
COMPANY = "ZZTEST W49"
COMPANY_ABBR = "W49"
DRY_GROUP = "ZZTEST W49 Dry"
FROZEN_PARENT = "ZZTEST W49 Frozen"
FROZEN_CHILD = "ZZTEST W49 Frozen Child"
DRY_ITEM = "ZZTEST-W49-DRY"
FROZEN_ITEM = "ZZTEST-W49-FROZEN"
CUSTOMER = "ZZTEST-W49 Customer"
WAREHOUSE = f"Stores - {COMPANY_ABBR}"


def guard_site() -> None:
	if frappe.local.site != SITE:
		raise RuntimeError(f"Refusing to run F1 fixtures on {frappe.local.site}; expected {SITE}.")


def bootstrap_base() -> dict[str, str]:
	guard_site()
	frappe.local.lang = "en"
	frappe.db.set_single_value("System Settings", "language", "en")

	if not frappe.db.exists("Company", COMPANY):
		from erpnext.setup.setup_wizard.setup_wizard import setup_complete

		setup_complete(
			frappe._dict(
				{
					"country": "Indonesia",
					"company_name": COMPANY,
					"company_abbr": COMPANY_ABBR,
					"currency": "IDR",
					"chart_of_accounts": "Standard",
					"domain": "Retail",
					"fy_start_date": "2026-01-01",
					"fy_end_date": "2026-12-31",
				}
			)
		)

	_ensure_uom("Nos")
	_ensure_uom("Box")
	_ensure_uom("Kg")
	_ensure_warehouse_type("Transit")
	_ensure_currency("IDR")
	_ensure_item_group(DRY_GROUP, "All Item Groups", is_group=0)
	_ensure_item_group(FROZEN_PARENT, "All Item Groups", is_group=1)
	_ensure_item_group(FROZEN_CHILD, FROZEN_PARENT, is_group=0)

	company = frappe.get_doc("Company", COMPANY)
	if not company.stock_adjustment_account:
		account = frappe.db.get_value(
			"Account",
			{"company": COMPANY, "account_name": "Stock Adjustment", "is_group": 0},
			"name",
		)
		if account:
			company.stock_adjustment_account = account
			company.save(ignore_permissions=True)

	warehouse = _ensure_warehouse()
	_ensure_item(DRY_ITEM, DRY_GROUP)
	_ensure_item(FROZEN_ITEM, FROZEN_CHILD)
	customer = _ensure_customer()
	_ensure_base_stock(warehouse)

	frappe.db.set_single_value("Stock Settings", "item_naming_by", "Item Code")
	frappe.db.set_single_value("System Settings", "setup_complete", 1)
	for app_name in ("erpnext", "warehouse_app"):
		if frappe.db.exists("Installed Application", {"app_name": app_name}):
			frappe.db.set_value(
				"Installed Application",
				{"app_name": app_name},
				"is_setup_complete",
				1,
				update_modified=False,
			)
	frappe.db.commit()

	return {
		"company": COMPANY,
		"warehouse": warehouse,
		"dry_group": DRY_GROUP,
		"frozen_parent": FROZEN_PARENT,
		"frozen_child": FROZEN_CHILD,
		"dry_item": DRY_ITEM,
		"frozen_item": FROZEN_ITEM,
		"customer": customer,
	}


def verify_base() -> dict[str, int]:
	guard_site()
	return {
		"companies": frappe.db.count("Company", {"company_name": COMPANY}),
		"items": frappe.db.count("Item", {"name": ("in", [DRY_ITEM, FROZEN_ITEM])}),
		"base_stock_entries": frappe.db.count(
			"Stock Entry", {"remarks": "ZZTEST-W49 base stock", "docstatus": 1}
		),
		"item_groups": frappe.db.count(
			"Item Group", {"name": ("in", [DRY_GROUP, FROZEN_PARENT, FROZEN_CHILD])}
		),
		"customers": frappe.db.count("Customer", {"customer_name": CUSTOMER}),
	}


def _ensure_uom(uom_name: str) -> str:
	if not frappe.db.exists("UOM", uom_name):
		frappe.get_doc({"doctype": "UOM", "uom_name": uom_name}).insert(
			ignore_permissions=True, ignore_if_duplicate=True
		)
	return uom_name


def _ensure_currency(currency: str) -> str:
	if not frappe.db.exists("Currency", currency):
		frappe.get_doc(
			{
				"doctype": "Currency",
				"currency_name": currency,
				"symbol": "Rp",
				"enabled": 1,
			}
		).insert(ignore_permissions=True, ignore_if_duplicate=True)
	return currency


def _ensure_warehouse_type(name: str) -> str:
	if not frappe.db.exists("Warehouse Type", name):
		frappe.get_doc({"doctype": "Warehouse Type", "name": name}).insert(
			ignore_permissions=True, ignore_if_duplicate=True
		)
	return name


def _ensure_item_group(name: str, parent: str, is_group: int) -> str:
	if not frappe.db.exists("Item Group", name):
		frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": name,
				"parent_item_group": parent if frappe.db.exists("Item Group", parent) else None,
				"is_group": is_group,
			}
		).insert(ignore_permissions=True, ignore_if_duplicate=True)
	return name


def _ensure_warehouse() -> str:
	if frappe.db.exists("Warehouse", WAREHOUSE):
		return WAREHOUSE

	parent = frappe.db.get_value(
		"Warehouse", {"company": COMPANY, "is_group": 1, "warehouse_name": "All Warehouses"}
	)
	doc = frappe.get_doc(
		{
			"doctype": "Warehouse",
			"warehouse_name": "Stores",
			"company": COMPANY,
			"is_group": 0,
			"parent_warehouse": parent,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_item(item_code: str, item_group: str) -> str:
	if not frappe.db.exists("Item", item_code):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"item_group": item_group,
				"stock_uom": "Nos",
				"is_stock_item": 1,
				"uoms": [{"uom": "Box", "conversion_factor": 12}],
			}
		).insert(ignore_permissions=True)
	return item_code


def _ensure_customer() -> str:
	existing = frappe.db.get_value("Customer", {"customer_name": CUSTOMER}, "name")
	if existing:
		return existing

	customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
	territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
	if not customer_group or not territory:
		raise RuntimeError("ERPNext setup fixtures did not create leaf Customer Group/Territory.")

	doc = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": CUSTOMER,
			"customer_type": "Company",
			"customer_group": customer_group,
			"territory": territory,
			"default_currency": "IDR",
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_base_stock(warehouse: str) -> None:
	marker = "ZZTEST-W49 base stock"
	if frappe.db.exists("Stock Entry", {"remarks": marker, "docstatus": 1}):
		return

	company = frappe.get_doc("Company", COMPANY)
	expense_account = company.stock_adjustment_account or frappe.db.get_value(
		"Account", {"company": COMPANY, "account_name": "Stock Adjustment", "is_group": 0}, "name"
	)
	doc = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Receipt",
			"company": COMPANY,
			"remarks": marker,
			"items": [
				{
					"item_code": DRY_ITEM,
					"qty": 100,
					"uom": "Nos",
					"conversion_factor": 1,
					"basic_rate": 100,
					"t_warehouse": warehouse,
					"expense_account": expense_account,
				},
				{
					"item_code": FROZEN_ITEM,
					"qty": 100,
					"uom": "Nos",
					"conversion_factor": 1,
					"basic_rate": 100,
					"t_warehouse": warehouse,
					"expense_account": expense_account,
				},
			],
		}
	)
	doc.insert(ignore_permissions=True)
	doc.submit()
