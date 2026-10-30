# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

import unittest
from unittest.mock import patch

import frappe

from warehouse_app.warehouse_app.fulfillment.permissions import (
	has_approver_roles,
	has_write_roles,
	require_approver,
	require_read,
	require_write,
)


class TestFulfillmentRoleMatrix(unittest.TestCase):
	def test_stock_user_alone_is_read_only(self):
		roles = {"Stock User"}
		self.assertFalse(has_write_roles(roles))
		self.assertFalse(has_approver_roles(roles))

	def test_stock_manager_without_stock_user_is_read_only(self):
		roles = {"Stock Manager"}
		self.assertFalse(has_write_roles(roles))
		self.assertFalse(has_approver_roles(roles))

	def test_system_manager_can_write_and_approve(self):
		roles = {"System Manager"}
		self.assertTrue(has_write_roles(roles))
		self.assertTrue(has_approver_roles(roles))

	def test_stock_manager_with_stock_user_can_write_and_approve(self):
		roles = {"Stock Manager", "Stock User"}
		self.assertTrue(has_write_roles(roles))
		self.assertTrue(has_approver_roles(roles))


class TestFulfillmentRoleRequirements(unittest.TestCase):
	@patch("warehouse_app.warehouse_app.fulfillment.permissions.frappe.get_roles", return_value=["Stock User"])
	def test_read_role_cannot_write_or_approve(self, _roles):
		require_read()
		with self.assertRaises(frappe.PermissionError):
			require_write()
		with self.assertRaises(frappe.PermissionError):
			require_approver()

	@patch("warehouse_app.warehouse_app.fulfillment.permissions.frappe.get_roles", return_value=[])
	def test_read_requires_a_warehouse_role(self, _roles):
		with self.assertRaises(frappe.PermissionError):
			require_read()

	@patch(
		"warehouse_app.warehouse_app.fulfillment.permissions.frappe.get_roles",
		return_value=["Stock Manager", "Stock User"],
	)
	def test_paired_stock_roles_can_write_and_approve(self, _roles):
		require_write()
		require_approver()
