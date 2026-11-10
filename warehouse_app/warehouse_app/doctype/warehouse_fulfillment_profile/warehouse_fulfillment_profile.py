# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from warehouse_app.warehouse_app.fulfillment.classification import (
	ClassificationError,
	validate_profile_config,
)

PAPER_SIZES = {"A4", "A5", "Letter", "Thermal 80mm"}
ROLE_FIELDS = (
	"role_order_coordinator",
	"role_picker_dry",
	"role_picker_frozen",
	"role_packer",
	"role_checker",
	"role_dispatch",
)
WAREHOUSE_FIELDS = ("dry_parent_warehouse", "frozen_parent_warehouse")
PRINT_FORMAT_FIELDS = ("dry_print_format", "frozen_print_format")


class WarehouseFulfillmentProfile(Document):
	def before_save(self):
		previous = self.get_doc_before_save()
		previous_revision = previous.config_revision if previous else 0
		self.config_revision = (previous_revision or 0) + 1

	def validate(self):
		if not self.company:
			frappe.throw(_("Company is required."))

		if (
			not self.is_new()
			and self.has_value_changed("company")
			and frappe.db.exists("DocType", "Warehouse Fulfillment Run")
			and frappe.db.exists("Warehouse Fulfillment Run", {"profile": self.name})
		):
			frappe.throw(_("The Company cannot be changed after a fulfillment Run exists."))

		duplicate = frappe.db.exists(
			"Warehouse Fulfillment Profile",
			{"company": self.company, "name": ("!=", self.name)},
		)
		if duplicate:
			frappe.throw(
				_("A fulfillment profile already exists for company {0}.").format(self.company),
				frappe.DuplicateEntryError,
			)

		self._validate_display_names()
		self._validate_print_settings()
		self._validate_warehouses()
		self._validate_roles()

		if self.minimum_shelf_life_days is not None and self.minimum_shelf_life_days < 0:
			frappe.throw(_("Minimum Shelf Life Days cannot be negative."))

		if not self.enabled:
			return

		if not self.frozen_item_group:
			frappe.throw(_("Frozen Item Group is required when the profile is enabled."))

		group = frappe.get_doc("Item Group", self.frozen_item_group)
		has_children = frappe.db.exists(
			"Item Group", {"parent_item_group": self.frozen_item_group}
		)
		try:
			validate_profile_config(
				self.frozen_item_group,
				group.is_group,
				bool(has_children),
				self.include_child_item_groups,
			)
		except ClassificationError as exc:
			frappe.throw(str(exc))

	def _validate_display_names(self):
		for fieldname, label in (
			("dry_display_name", "Dry Display Name"),
			("frozen_display_name", "Frozen Display Name"),
		):
			if not str(self.get(fieldname) or "").strip():
				frappe.throw(_("{0} is required.").format(label))

	def _validate_print_settings(self):
		for fieldname in PRINT_FORMAT_FIELDS:
			value = self.get(fieldname)
			if not value:
				continue
			print_format = frappe.db.get_value(
				"Print Format", value, ["doc_type", "disabled"], as_dict=True
			)
			if not print_format:
				frappe.throw(_("Print Format {0} does not exist.").format(value))
			if print_format.doc_type != "Pick List":
				frappe.throw(_("Print Format {0} must be for Pick List.").format(value))
			if print_format.disabled:
				frappe.throw(_("Print Format {0} is disabled.").format(value))

		if self.print_paper_size and self.print_paper_size not in PAPER_SIZES:
			frappe.throw(_("Invalid print paper size: {0}.").format(self.print_paper_size))

		for fieldname, label in (
			("dry_print_copies", "Dry Print Copies"),
			("frozen_print_copies", "Frozen Print Copies"),
		):
			value = self.get(fieldname)
			if value is not None and value < 1:
				frappe.throw(_("{0} must be at least 1.").format(label))

	def _validate_warehouses(self):
		for fieldname in WAREHOUSE_FIELDS:
			value = self.get(fieldname)
			if not value:
				continue
			warehouse = frappe.db.get_value(
				"Warehouse", value, ["company", "disabled"], as_dict=True
			)
			if not warehouse:
				frappe.throw(_("Warehouse {0} does not exist.").format(value))
			if warehouse.company != self.company:
				frappe.throw(
					_("Warehouse {0} does not belong to company {1}.").format(
						value, self.company
					)
				)
			if warehouse.disabled:
				frappe.throw(_("Warehouse {0} is disabled.").format(value))

	def _validate_roles(self):
		for fieldname in ROLE_FIELDS:
			value = self.get(fieldname)
			if not value:
				continue
			role = frappe.db.get_value("Role", value, "disabled")
			if role is None:
				frappe.throw(_("Role {0} does not exist.").format(value))
			if role:
				frappe.throw(_("Role {0} is disabled.").format(value))
