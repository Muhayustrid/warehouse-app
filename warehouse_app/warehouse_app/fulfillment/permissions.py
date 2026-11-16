# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""Role gates shared by fulfillment read and write services."""

from __future__ import annotations

import frappe

READ_ROLES = {"System Manager", "Stock Manager", "Stock User"}


def has_write_roles(roles: set[str]) -> bool:
	return "System Manager" in roles or {"Stock Manager", "Stock User"}.issubset(roles)


def has_approver_roles(roles: set[str]) -> bool:
	return has_write_roles(roles)


def require_read() -> None:
	if not READ_ROLES.intersection(frappe.get_roles()):
		raise frappe.PermissionError("Fulfillment workspace requires a warehouse role.")


def require_write() -> None:
	if not has_write_roles(set(frappe.get_roles())):
		raise frappe.PermissionError("Fulfillment writes require System Manager or paired stock roles.")


def require_approver() -> None:
	if not has_approver_roles(set(frappe.get_roles())):
		raise frappe.PermissionError("Short-pick approval requires System Manager or paired stock roles.")


def require_manifest_write() -> None:
	"""Delivery Manifest read/write is open to System Manager, paired stock
	roles, or a lone Stock User (driver/mobil fields only)."""
	roles = set(frappe.get_roles())
	if not (has_write_roles(roles) or "Stock User" in roles):
		raise frappe.PermissionError("Delivery Manifest requires a warehouse role.")


def is_manifest_driver_only(roles: set[str] | None = None) -> bool:
	"""True when the user is a lone Stock User (no gudang write), i.e. may only
	edit driver/vehicle fields of an existing manifest."""
	roles = set(roles if roles is not None else frappe.get_roles())
	return "Stock User" in roles and not has_write_roles(roles)
