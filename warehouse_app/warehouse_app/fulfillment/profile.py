# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""Profile lookup and frozen-group resolution for the F1 read-only API."""

from __future__ import annotations

import frappe

from warehouse_app.warehouse_app.fulfillment.classification import frozen_groups

PROFILE = "Warehouse Fulfillment Profile"


def get_profile(company: str):
	rows = frappe.get_list(
		PROFILE,
		filters={"company": company},
		fields=[
			"name",
			"enabled",
			"frozen_item_group",
			"include_child_item_groups",
			"dry_display_name",
			"frozen_display_name",
		],
		limit_page_length=1,
	)
	return rows[0] if rows else None


def resolve_frozen(profile) -> set[str] | None:
	if not profile or not profile.get("enabled") or not profile.get("frozen_item_group"):
		return None

	group = frappe.get_list(
		"Item Group",
		filters={"name": profile.get("frozen_item_group")},
		fields=["name", "lft", "rgt", "is_group"],
		limit_page_length=1,
	)
	if not group:
		return None
	group = group[0]

	if not profile.get("include_child_item_groups"):
		has_children = frappe.db.exists(
			"Item Group", {"parent_item_group": profile.get("frozen_item_group")}
		)
		if group.get("is_group") and has_children:
			return None
		return frozen_groups(profile.get("frozen_item_group"), [], False)

	descendants = frappe.get_list(
		"Item Group",
		filters=[
			["lft", ">", group.get("lft")],
			["rgt", "<", group.get("rgt")],
		],
		pluck="name",
		limit_page_length=0,
	)
	return frozen_groups(
		profile.get("frozen_item_group"),
		descendants,
		bool(profile.get("include_child_item_groups")),
	)
