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


class WarehouseFulfillmentProfile(Document):
	def validate(self):
		if not self.company:
			frappe.throw(_("Company is required."))

		duplicate = frappe.db.exists(
			"Warehouse Fulfillment Profile",
			{"company": self.company, "name": ("!=", self.name)},
		)
		if duplicate:
			frappe.throw(
				_("A fulfillment profile already exists for company {0}.").format(self.company),
				frappe.DuplicateEntryError,
			)

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
