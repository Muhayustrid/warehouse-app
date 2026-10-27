# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""F1 test-site fixtures. Only runs on the disposable fulfillment site."""

from __future__ import annotations

import frappe
from frappe.utils import add_days, flt, today

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
PROFILE = "Warehouse Fulfillment Profile"
SO_MARKERS = {
	"open": "ZZTEST-W49-SO-OPEN",
	"picking": "ZZTEST-W49-SO-PICKING",
	"packing": "ZZTEST-W49-SO-PACKING",
	"ready": "ZZTEST-W49-SO-READY",
}


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


def seed() -> dict[str, list[str]]:
	guard_site()
	bootstrap_base()
	cleanup_documents()
	_ensure_profile()

	sales_orders = {
		state: _create_sales_order(marker) for state, marker in SO_MARKERS.items()
	}

	pick_lists = []
	pick_lists.append(_create_pick_list(sales_orders["picking"], submit=False))
	pick_lists.append(_create_pick_list(sales_orders["packing"], submit=True))
	ready_pl = _create_pick_list(sales_orders["ready"], submit=True)
	pick_lists.append(ready_pl)

	delivery_notes = []
	packing_slips = []
	dn = _create_delivery_note(ready_pl)
	delivery_notes.append(dn)
	packing_slips.append(_create_packing_slip(dn))
	frappe.db.commit()

	return {
		"sales_orders": list(sales_orders.values()),
		"pick_lists": pick_lists,
		"delivery_notes": delivery_notes,
		"packing_slips": packing_slips,
	}


def cleanup_documents() -> dict[str, int]:
	guard_site()
	customer = frappe.db.get_value("Customer", {"customer_name": CUSTOMER}, "name")
	if not customer:
		return {"packing_slips": 0, "delivery_notes": 0, "pick_lists": 0, "sales_orders": 0}

	so_names = frappe.get_all("Sales Order", filters={"customer": customer}, pluck="name")
	pl_names = (
		frappe.get_all(
			"Pick List Item",
			filters={"sales_order": ("in", so_names)},
			pluck="parent",
			distinct=True,
		)
		if so_names
		else []
	)
	dn_names = (
		frappe.get_all(
			"Delivery Note Item",
			filters={"against_sales_order": ("in", so_names)},
			pluck="parent",
			distinct=True,
		)
		if so_names
		else []
	)
	ps_names = (
		frappe.get_all(
			"Packing Slip", filters={"delivery_note": ("in", dn_names)}, pluck="name"
		)
		if dn_names
		else []
	)

	deleted = {
		"packing_slips": _cancel_delete("Packing Slip", ps_names),
		"delivery_notes": _cancel_delete("Delivery Note", dn_names),
		"pick_lists": _cancel_delete("Pick List", pl_names),
		"sales_orders": _cancel_delete("Sales Order", so_names),
	}
	frappe.db.commit()
	return deleted


def verify_seed() -> dict[str, object]:
	guard_site()
	customer = frappe.db.get_value("Customer", {"customer_name": CUSTOMER}, "name")
	rows = frappe.get_all(
		"Sales Order",
		filters={"customer": customer},
		fields=["name", "po_no", "docstatus"],
	) if customer else []
	states = {
		marker: row.name
		for row in rows
		for marker in SO_MARKERS.values()
		if row.po_no == marker
	}
	so_names = [row.name for row in rows]
	pl_names = (
		frappe.get_all(
			"Pick List Item",
			filters={"sales_order": ("in", so_names)},
			pluck="parent",
			distinct=True,
		)
		if so_names
		else []
	)
	dn_names = (
		frappe.get_all(
			"Delivery Note Item",
			filters={"against_sales_order": ("in", so_names)},
			pluck="parent",
			distinct=True,
		)
		if so_names
		else []
	)
	ps_names = (
		frappe.get_all(
			"Packing Slip", filters={"delivery_note": ("in", dn_names)}, pluck="name"
		)
		if dn_names
		else []
	)
	ready_so = states.get("ZZTEST-W49-SO-READY")
	ready_dn = (
		frappe.db.get_value("Delivery Note Item", {"against_sales_order": ready_so}, "parent")
		if ready_so
		else None
	)
	ready_dn_fully_packed = False
	if ready_dn:
		ready_dn_fully_packed = all(
			flt(row.packed_qty) >= flt(row.qty)
			for row in frappe.get_all(
				"Delivery Note Item",
				filters={"parent": ready_dn},
				fields=["qty", "packed_qty"],
			)
		)
	return {
		"states": states,
		"counts": {
			"sales_orders": len(so_names),
			"pick_lists": len(pl_names),
			"delivery_notes": len(dn_names),
			"packing_slips": len(ps_names),
		},
		"docstatuses": {
			"pick_lists": {name: frappe.db.get_value("Pick List", name, "docstatus") for name in pl_names},
			"delivery_notes": {
				name: frappe.db.get_value("Delivery Note", name, "docstatus") for name in dn_names
			},
			"packing_slips": {
				name: frappe.db.get_value("Packing Slip", name, "docstatus") for name in ps_names
			},
		},
		"ready_dn_fully_packed": ready_dn_fully_packed,
		"names": {
			"sales_orders": so_names,
			"pick_lists": pl_names,
			"delivery_notes": dn_names,
			"packing_slips": ps_names,
		},
	}


def _ensure_profile() -> None:
	existing = frappe.db.get_value(PROFILE, {"company": COMPANY}, "name")
	profile = frappe.get_doc(PROFILE, existing) if existing else frappe.get_doc(
		{"doctype": PROFILE, "company": COMPANY}
	)
	profile.enabled = 1
	profile.frozen_item_group = FROZEN_PARENT
	profile.include_child_item_groups = 1
	profile.save(ignore_permissions=True) if existing else profile.insert(ignore_permissions=True)


def _create_sales_order(marker: str) -> str:
	customer = frappe.db.get_value("Customer", {"customer_name": CUSTOMER}, "name")
	if not customer:
		customer = _ensure_customer()
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
					"item_code": DRY_ITEM,
					"qty": 5,
					"rate": 100,
					"price_list_rate": 100,
					"uom": "Nos",
					"conversion_factor": 1,
					"warehouse": WAREHOUSE,
					"delivery_date": delivery_date,
				},
				{
					"item_code": FROZEN_ITEM,
					"qty": 5,
					"rate": 100,
					"price_list_rate": 100,
					"uom": "Nos",
					"conversion_factor": 1,
					"warehouse": WAREHOUSE,
					"delivery_date": delivery_date,
				},
			],
		}
	)
	so.insert(ignore_permissions=True)
	so.submit()
	return so.name


def _create_pick_list(sales_order: str, submit: bool) -> str:
	from erpnext.selling.doctype.sales_order.sales_order import create_pick_list

	pick_list = create_pick_list(sales_order)
	if not pick_list.locations:
		raise RuntimeError(f"Native create_pick_list produced no locations for {sales_order}")
	pick_list.scan_mode = 0
	if submit:
		pick_list.pick_manually = 1
		for row in pick_list.locations:
			row.picked_qty = flt(row.stock_qty)
	pick_list.insert(ignore_permissions=True)
	if submit:
		pick_list.submit()
	return pick_list.name


def _create_delivery_note(pick_list: str) -> str:
	from erpnext.stock.doctype.pick_list.pick_list import create_dn_for_pick_lists

	delivery_note = create_dn_for_pick_lists(pick_list)
	if not delivery_note:
		raise RuntimeError(f"Native create_dn_for_pick_lists produced no DN for {pick_list}")
	delivery_note.insert(ignore_permissions=True)
	return delivery_note.name


def _create_packing_slip(delivery_note: str) -> str:
	from erpnext.stock.doctype.delivery_note.delivery_note import make_packing_slip

	packing_slip = make_packing_slip(delivery_note)
	if not packing_slip:
		raise RuntimeError(f"Native make_packing_slip produced no Packing Slip for {delivery_note}")
	packing_slip.from_case_no = 1
	packing_slip.to_case_no = 1
	packing_slip.insert(ignore_permissions=True)
	packing_slip.submit()
	return packing_slip.name


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
