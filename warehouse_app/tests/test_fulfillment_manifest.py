# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

import unittest

from warehouse_app.warehouse_app.fulfillment.manifest import (
	bucket_lines,
	classify_line,
	estimate_weight,
	total_weight,
)


FROZEN = {"Produk Jadi Pabrik"}


def _line(item_group, **overrides):
	row = {
		"item_code": "PJ260010",
		"item_group": item_group,
		"qty": 2,
		"weight_per_unit": 0.53,
	}
	row.update(overrides)
	return row


class TestClassifyLine(unittest.TestCase):
	def test_frozen_group(self):
		self.assertEqual(classify_line({"item_group": "Produk Jadi Pabrik", "item_code": "P"}, FROZEN), "frozen")

	def test_dry_group(self):
		self.assertEqual(classify_line({"item_group": "Lain", "item_code": "P"}, FROZEN), "dry")

	def test_dry_exception_overrides_frozen_group(self):
		self.assertEqual(
			classify_line(
				{"item_group": "Produk Jadi Pabrik", "item_code": "PJ260009"},
				FROZEN,
				dry_exceptions={"PJ260009"},
			),
			"dry",
		)

	def test_item_override_wins(self):
		self.assertEqual(
			classify_line(
				{"item_group": "Produk Jadi Pabrik", "item_code": "P", "custom_fulfillment_category": "Dry"},
				FROZEN,
			),
			"dry",
		)


class TestBucketLines(unittest.TestCase):
	def test_split_preserves_order(self):
		dry, frozen = bucket_lines(
			[
				_line("Lain", item_code="A"),
				_line("Produk Jadi Pabrik", item_code="B"),
				_line("Lain", item_code="C"),
			],
			FROZEN,
		)
		self.assertEqual([r["item_code"] for r in dry], ["A", "C"])
		self.assertEqual([r["item_code"] for r in frozen], ["B"])


class TestEstimateWeight(unittest.TestCase):
	def test_qty_times_weight(self):
		self.assertEqual(estimate_weight(3, 0.53), 1.59)

	def test_zero_weight_is_none(self):
		self.assertIsNone(estimate_weight(3, 0))
		self.assertIsNone(estimate_weight(3, None))

	def test_rounding_two_places(self):
		self.assertEqual(estimate_weight(1, 0.666), 0.67)


class TestTotalWeight(unittest.TestCase):
	def test_sums_available_rows(self):
		rows = [{"estimated_weight": 1.59}, {"estimated_weight": None}, {"estimated_weight": 0.74}]
		self.assertEqual(total_weight(rows), 2.33)


if __name__ == "__main__":
	unittest.main()