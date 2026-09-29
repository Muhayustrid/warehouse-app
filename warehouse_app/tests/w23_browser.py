# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto
# License: MIT

# W23 browser E2E helper (fixture setup/teardown + DB verify) — dipanggil via
#   docker exec erpnext-new-backend-1 bench --site frontend execute \
#       warehouse_app.tests.w23_browser.setup
#   ... teardown --kwargs '{"item": "...", "sr_names_json": "[...]", "email": "..."}'
# Playwright host script memanggil ini lewat subprocess docker exec.

import json
import time

import frappe
from frappe.utils import nowdate, nowtime

PREFIX = "ZZTEST-W23UI"


def _pick_expense_account(company):
	"""Mirror w23_gate._pick_expense_account: SR pertama di site virgin dianggap
	opening entry native (butuh akun Balance Sheet); setelah ada SLE pakai
	stock_adjustment_account."""
	if frappe.db.sql("select name from `tabStock Ledger Entry` limit 1"):
		return frappe.db.get_value("Company", company, "stock_adjustment_account")
	opening = frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0, "account_type": "Temporary"},
		pluck="name",
		limit=1,
	) or frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0, "report_type": "Balance Sheet"},
		pluck="name",
		order_by="lft",
		limit=1,
	)
	return opening[0] if opening else frappe.db.get_value("Company", company, "stock_adjustment_account")


def setup():
	company = "JURI"
	item_group = "Products" if frappe.db.exists("Item Group", "Products") else frappe.get_all(
		"Item Group", pluck="name", order_by="lft", limit=1
	)[0]
	stamp = str(int(time.time()))
	email = f"zztest-w23ui-{stamp}@example.com"
	# site menegakkan minimum password strength — password lemah (mis. zztest123)
	# ditolak User.password_strength_test; pakai yang selalu lolos.
	pwd = "W23ui!" + stamp + "Kq"

	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": "ZZTEST W23UI",
			"user_type": "System User",
			"send_welcome_email": 0,
		}
	)
	user.insert(ignore_permissions=True)
	user.add_roles("Gudang Barang Jadi", "Stock Manager", "Stock User")
	user.new_password = pwd
	user.save(ignore_permissions=True)
	frappe.db.commit()

	item = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": PREFIX + "-" + frappe.generate_hash(length=8),
			"item_name": "ZZTEST W23 UI Item",
			"item_group": item_group,
			"stock_uom": "Nos",
			"is_stock_item": 1,
			"has_batch_no": 0,
			"has_serial_no": 0,
			"uoms": [{"uom": "Box", "conversion_factor": 12}],
			"custom_default_inventory_unit_of_measure": "Box",
		}
	)
	item.insert(ignore_permissions=True)
	frappe.db.commit()

	return {
		"email": email,
		"pwd": pwd,
		"item": item.name,
		"item_group": item_group,
		"company": company,
		"expense_account": _pick_expense_account(company),
		"stock_uom": "Nos",
	}


def teardown(item="", sr_names_json="[]", email=""):
	"""Cancel+delete SR, sweep SLE/Repost/Bin, purge item+user fixture. Selalu
	dipanggil (finally). Return: residue dict guard."""
	sr_names = json.loads(sr_names_json or "[]")

	def _safe(fn):
		try:
			fn()
		except Exception:
			pass

	for name in sr_names:
		if not frappe.db.exists("Stock Reconciliation", name):
			continue

		def _cancel_del(name=name):
			doc = frappe.get_doc("Stock Reconciliation", name)
			if doc.docstatus == 1:
				doc.cancel()
			frappe.delete_doc("Stock Reconciliation", name, force=1, ignore_missing=True)

		_safe(_cancel_del)

	for dt, key in (
		("Stock Ledger Entry", "item_code"),
		("Repost Item Valuation", "item_code"),
		("Bin", "item_code"),
	):
		if item:
			for name in frappe.get_all(dt, filters={key: item}, pluck="name"):
				_safe(lambda dt=dt, name=name: frappe.delete_doc(dt, name, force=1, ignore_missing=True))

	if item and frappe.db.exists("Item", item):
		_safe(lambda: frappe.delete_doc("Item", item, force=1, ignore_missing=True))

	for name in frappe.get_all("Version", filters={"docname": ("like", PREFIX + "%")}, pluck="name"):
		_safe(lambda name=name: frappe.delete_doc("Version", name, force=1, ignore_missing=True))

	if email and frappe.db.exists("User", email):
		_safe(lambda: frappe.delete_doc("User", email, force=1, ignore_missing=True))
		_safe(lambda: frappe.db.delete("Sessions", {"user": email}))
		_safe(lambda: frappe.db.delete("Activity Log", {"user": email}))
		if frappe.db.has_column("Activity Log", "for_user"):
			_safe(lambda: frappe.db.delete("Activity Log", {"for_user": email}))
	frappe.db.commit()

	from warehouse_app.tests.guard import count_residue

	return count_residue()


def verify_db(sr_name):
	"""Bukti persist: row SR + SLE. Return dict utk laporan."""
	row = frappe.db.get_value(
		"Stock Reconciliation Item",
		{"parent": sr_name},
		[
			"item_code",
			"qty",
			"valuation_rate",
			"custom_uom",
			"custom_conversion_factor",
			"custom_qty_before",
			"custom_qty_after",
			"custom_valuation_rate_per_uom",
		],
		as_dict=1,
	)
	sle = frappe.db.get_value(
		"Stock Ledger Entry",
		{"voucher_type": "Stock Reconciliation", "voucher_no": sr_name, "is_cancelled": 0},
		["actual_qty", "qty_after_transaction", "valuation_rate"],
		as_dict=1,
	)
	return {"row": dict(row) if row else None, "sle": dict(sle) if sle else None}
