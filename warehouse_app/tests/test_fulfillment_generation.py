# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

import unittest

from warehouse_app.warehouse_app.fulfillment.generation import (
	GenerationError,
	build_generation_plan,
	pending_stock_qty,
	profile_policy_snapshot,
	split_locations,
)


def item(so_item, item_code, group, qty=10, picked=0, delivered=0, factor=1):
	return {
		"sales_order_item": so_item,
		"item_code": item_code,
		"item_group": group,
		"qty": qty,
		"picked_qty": picked,
		"delivered_qty": delivered,
		"conversion_factor": factor,
		"stock_uom": "Nos",
		"warehouse": "Stores - W49",
	}


class TestPendingStockQty(unittest.TestCase):
	def test_uses_delivered_when_larger(self):
		self.assertEqual(pending_stock_qty(10, 2, 3, 1), 7)

	def test_converts_picked_uom(self):
		self.assertEqual(pending_stock_qty(10, 24, 0, 12), 8)

	def test_missing_values_are_zero(self):
		self.assertEqual(pending_stock_qty(10, None, None, 1), 10)

	def test_invalid_conversion_fails(self):
		with self.assertRaises(GenerationError) as ctx:
			pending_stock_qty(10, 0, 0, 0)
		self.assertEqual(ctx.exception.code, "INVALID_CONVERSION")


class TestBuildPlan(unittest.TestCase):
	def test_one_row_per_sales_order_item(self):
		plan = build_generation_plan(
			[
				item("SOI-1", "A", "Dry"),
				item("SOI-2", "A", "Dry"),
				item("SOI-3", "B", "Frozen"),
			],
			{"Frozen"},
		)
		self.assertEqual(len(plan["items"]), 3)
		self.assertEqual(len(plan["groups"]["dry"]), 2)
		self.assertEqual(len(plan["groups"]["frozen"]), 1)
		self.assertEqual([row["sales_order_item"] for row in plan["groups"]["dry"]], ["SOI-1", "SOI-2"])

	def test_fully_delivered_row_is_skipped(self):
		plan = build_generation_plan(
			[item("SOI-1", "A", "Dry", delivered=10)],
			{"Frozen"},
		)
		self.assertEqual(plan["items"], [])
		self.assertEqual(plan["groups"], {"dry": [], "frozen": []})

	def test_missing_item_group_fails(self):
		with self.assertRaises(GenerationError) as ctx:
			build_generation_plan([item("SOI-1", "A", None)], {"Frozen"})
		self.assertEqual(ctx.exception.code, "ITEM_GROUP_MISSING")
		self.assertEqual(ctx.exception.row["sales_order_item"], "SOI-1")

	def test_empty_frozen_profile_fails(self):
		with self.assertRaises(GenerationError) as ctx:
			build_generation_plan([item("SOI-1", "A", "Dry")], set())
		self.assertEqual(ctx.exception.code, "PROFILE_INVALID")

	def test_native_pending_quantity_is_converted_to_stock_uom(self):
		plan = build_generation_plan(
			[item("SOI-1", "A", "Dry", qty=10, picked=24, factor=12)],
			{"Frozen"},
		)
		self.assertEqual(plan["items"][0]["pending_qty"], 8)
		self.assertEqual(plan["items"][0]["required_stock_qty"], 96)

	def test_fractional_conversion_is_converted_to_stock_uom(self):
		plan = build_generation_plan(
			[item("SOI-1", "A", "Dry", qty=10, factor=0.5)],
			{"Frozen"},
		)
		self.assertEqual(plan["items"][0]["required_stock_qty"], 5)


class TestSplitLocations(unittest.TestCase):
	def test_preserves_rows_and_disjoint_groups(self):
		locations = [
			{"name": "L1", "sales_order_item": "SOI-1"},
			{"name": "L2", "sales_order_item": "SOI-2"},
			{"name": "L3", "sales_order_item": "SOI-1"},
		]
		split = split_locations(locations, {"SOI-1": "dry", "SOI-2": "frozen"})
		self.assertEqual([row["name"] for row in split["dry"]], ["L1", "L3"])
		self.assertEqual([row["name"] for row in split["frozen"]], ["L2"])

	def test_missing_mapping_fails(self):
		with self.assertRaises(GenerationError) as ctx:
			split_locations([{"sales_order_item": "SOI-9"}], {})
		self.assertEqual(ctx.exception.code, "SPLIT_MAPPING_MISSING")

	def test_missing_sales_order_item_fails(self):
		with self.assertRaises(GenerationError) as ctx:
			split_locations([{}], {})
		self.assertEqual(ctx.exception.code, "SPLIT_MAPPING_MISSING")


class TestPolicySnapshot(unittest.TestCase):
	def test_snapshot_contains_policy_and_revision(self):
		profile = {
			"config_revision": 7,
			"frozen_item_group": "Frozen",
			"include_child_item_groups": 1,
			"allow_partial_delivery": 0,
			"short_pick_approval_required": 1,
			"require_all_packed": 1,
			"require_checker_approval": 1,
			"allow_cross_group_packing": 0,
			"dry_parent_warehouse": "Stores - W49",
			"frozen_parent_warehouse": "Freezer - W49",
		}
		snapshot = profile_policy_snapshot(profile)
		self.assertEqual(snapshot["profile_revision"], 7)
		self.assertEqual(snapshot["frozen_item_group"], "Frozen")
		self.assertEqual(snapshot["dry_parent_warehouse"], "Stores - W49")
		self.assertEqual(snapshot["allow_partial_delivery"], 0)


if __name__ == "__main__":
	unittest.main()
