# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto
# License: MIT

"""Shared access guard for Stock Reconciliation public routes in warehouse_app.

Enforces:
1. Current session user identity (no request user impersonation).
2. Action permission ('write' or 'create') plus 'read' on Stock Reconciliation.
3. Lazy integration with pos_next.assert_system_stock_access when pos_next is installed;
   fails closed if pos_next is installed but the helper is unavailable.
4. Standalone scope check (Warehouse + Company read) without HQ membership requirement
   when pos_next is not installed.
"""

import frappe
from frappe import _


def assert_sr_access(
	action: str,
	warehouse: str | None = None,
	company: str | None = None,
	require_warehouse: bool = False,
):
	"""Check SR action + read permission and contextual warehouse/company access."""
	session = getattr(frappe, "session", None)
	user = getattr(session, "user", None) or "Guest"
	if user == "Guest":
		frappe.throw(_("Not permitted to access Stock Reconciliation."), frappe.PermissionError)

	if not frappe.has_permission("Stock Reconciliation", "read", user=user):
		frappe.throw(_("Not permitted to read Stock Reconciliation."), frappe.PermissionError)

	if action and action != "read":
		if not frappe.has_permission("Stock Reconciliation", action, user=user):
			frappe.throw(_("Not permitted to {0} Stock Reconciliation.").format(action), frappe.PermissionError)

	if require_warehouse:
		warehouse = str(warehouse or "").strip()
		if not warehouse:
			frappe.throw(_("A permitted warehouse is required."), frappe.PermissionError)
	elif warehouse is not None:
		warehouse = str(warehouse).strip()

	get_installed = getattr(frappe, "get_installed_apps", None)
	installed_apps = get_installed() if callable(get_installed) else []
	if "pos_next" in installed_apps:
		try:
			from pos_next.overrides.stock_reconciliation import assert_system_stock_access
		except Exception as exc:
			frappe.throw(
				_("pos_next is installed but assert_system_stock_access is unavailable: {0}").format(exc),
				frappe.PermissionError,
			)
		assert_system_stock_access(warehouse=warehouse, company=company, user=user)
		return

	# Standalone mode (without pos_next installed)
	if warehouse is None and company is None:
		return

	if not warehouse or not frappe.db.exists("Warehouse", warehouse):
		frappe.throw(_("A permitted warehouse is required."), frappe.PermissionError)

	warehouse_doc = frappe.get_doc("Warehouse", warehouse)
	wh_company = getattr(warehouse_doc, "company", None)
	if not wh_company or (company and company != wh_company):
		frappe.throw(_("Warehouse and company do not match."), frappe.PermissionError)

	wh_ok = True
	if hasattr(warehouse_doc, "has_permission"):
		wh_ok = warehouse_doc.has_permission("read", user=user)
	elif hasattr(frappe, "has_permission"):
		wh_ok = frappe.has_permission("Warehouse", "read", doc=warehouse_doc, user=user)

	company_doc = frappe.get_doc("Company", wh_company)
	comp_ok = True
	if hasattr(company_doc, "has_permission"):
		comp_ok = company_doc.has_permission("read", user=user)
	elif hasattr(frappe, "has_permission"):
		comp_ok = frappe.has_permission("Company", "read", doc=company_doc, user=user)

	if not wh_ok or not comp_ok:
		frappe.throw(_("Not permitted to read this warehouse or company."), frappe.PermissionError)
