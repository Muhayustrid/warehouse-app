# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

import unittest

from warehouse_app.warehouse_app.fulfillment.classification import (
	ClassificationError,
	classify,
	classify_rows,
	frozen_groups,
	validate_profile_config,
)


class TestFrozenGroups(unittest.TestCase):
	def test_exact_group_is_frozen(self):
		frozen = frozen_groups("Produk Jadi Pabrik", ["Dough"], include_children=False)
		self.assertEqual(classify("Produk Jadi Pabrik", frozen), "frozen")

	def test_child_group_is_frozen_when_enabled(self):
		frozen = frozen_groups("Produk Jadi Pabrik", ["Dough"], include_children=True)
		self.assertEqual(classify("Dough", frozen), "frozen")

	def test_child_group_is_dry_when_disabled(self):
		frozen = frozen_groups("Produk Jadi Pabrik", ["Dough"], include_children=False)
		self.assertEqual(classify("Dough", frozen), "dry")

	def test_unrelated_group_is_dry(self):
		frozen = frozen_groups("Produk Jadi Pabrik", ["Dough"], include_children=True)
		self.assertEqual(classify("Bahan Baku", frozen), "dry")

	def test_frozen_groups_returns_configured_and_descendants(self):
		frozen = frozen_groups("Parent", ["Child A", "Child B"], include_children=True)
		self.assertEqual(frozen, {"Parent", "Child A", "Child B"})

	def test_missing_configured_group_raises(self):
		with self.assertRaises(ClassificationError):
			frozen_groups(None, ["Dough"], include_children=True)


class TestClassify(unittest.TestCase):
	def test_missing_item_group_raises(self):
		with self.assertRaises(ClassificationError):
			classify(None, {"Produk Jadi Pabrik"})

	def test_empty_frozen_set_raises(self):
		with self.assertRaises(ClassificationError):
			classify("Produk Jadi Pabrik", set())

	def test_result_is_stable_technical_enum(self):
		frozen = {"Produk Jadi Pabrik"}
		self.assertIn(classify("Produk Jadi Pabrik", frozen), {"dry", "frozen"})
		self.assertIn(classify("Bahan Baku", frozen), {"dry", "frozen"})


class TestValidateProfileConfig(unittest.TestCase):
	def test_leaf_group_is_valid(self):
		validate_profile_config("Dough", group_is_group=False, has_children=False, include_children=False)

	def test_parent_group_with_children_and_flag_off_raises(self):
		with self.assertRaises(ClassificationError):
			validate_profile_config(
				"Produk Jadi Pabrik",
				group_is_group=True,
				has_children=True,
				include_children=False,
			)

	def test_parent_group_with_children_and_flag_on_is_valid(self):
		validate_profile_config(
			"Produk Jadi Pabrik",
			group_is_group=True,
			has_children=True,
			include_children=True,
		)

	def test_missing_group_raises(self):
		with self.assertRaises(ClassificationError):
			validate_profile_config(None, group_is_group=False, has_children=False, include_children=False)


class TestClassifyRows(unittest.TestCase):
	def test_preserves_duplicate_sales_order_rows(self):
		rows = [
			{"sales_order_item": "SO-1", "item_code": "CUP", "item_group": "Dry Goods"},
			{"sales_order_item": "SO-2", "item_code": "CUP", "item_group": "Dry Goods"},
			{"sales_order_item": "SO-3", "item_code": "DOUGH", "item_group": "Dough"},
		]
		classified = classify_rows(rows, {"Produk Jadi Pabrik", "Dough"})
		self.assertEqual([row["sales_order_item"] for row in classified], ["SO-1", "SO-2", "SO-3"])
		self.assertEqual([row["picking_group"] for row in classified], ["dry", "dry", "frozen"])

	def test_missing_sales_order_item_raises(self):
		with self.assertRaises(ClassificationError):
			classify_rows([{"item_code": "CUP", "item_group": "Dry Goods"}], {"Frozen"})

	def test_missing_item_code_raises(self):
		with self.assertRaises(ClassificationError):
			classify_rows([{"sales_order_item": "SO-1", "item_group": "Dry Goods"}], {"Frozen"})

	def test_missing_item_group_raises(self):
		with self.assertRaises(ClassificationError):
			classify_rows([{"sales_order_item": "SO-1", "item_code": "CUP"}], {"Frozen"})


if __name__ == "__main__":
	unittest.main()
