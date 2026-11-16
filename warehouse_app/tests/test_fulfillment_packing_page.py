# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

import unittest
from datetime import date

from warehouse_app.warehouse_app.fulfillment.packing_page import (
	aggregate_lines,
	day_name,
	empty_row,
	overlay_saved,
)


FROZEN = {"Produk Jadi Pabrik"}


def _line(**overrides):
	row = {
		"item_code": "PJ260010",
		"item_group": "Produk Jadi Pabrik",
		"qty": 2,
		"weight_per_unit": 0.53,
	}
	row.update(overrides)
	return row


class TestDayName(unittest.TestCase):
	def test_indonesian_caps(self):
		self.assertEqual(day_name(date(2026, 11, 13)), "JUMAT")
		self.assertEqual(day_name(date(2026, 11, 12)), "KAMIS")

	def test_string_input(self):
		self.assertEqual(day_name("2026-11-13"), "JUMAT")

	def test_invalid_string(self):
		self.assertEqual(day_name("not-a-date"), "")


class TestAggregateLines(unittest.TestCase):
	def test_frozen_and_dry_buckets(self):
		rows = aggregate_lines(
			[
				_line(qty=5),
				_line(item_code="BB260001", item_group="Bahan Baku", qty=3),
			],
			FROZEN,
		)
		self.assertEqual(len(rows["frozen"]), 1)
		self.assertEqual(len(rows["dry"]), 1)
		self.assertEqual(rows["frozen"][0]["qty"], 5)
		self.assertEqual(rows["dry"][0]["item_code"], "BB260001")

	def test_same_item_qty_merged(self):
		rows = aggregate_lines([_line(qty=2), _line(qty=3)], FROZEN)
		self.assertEqual(rows["frozen"][0]["qty"], 5)

	def test_frozen_row_has_estimate(self):
		rows = aggregate_lines([_line(qty=2)], FROZEN)
		self.assertIsNotNone(rows["frozen"][0].get("estimated_weight"))


class TestEmptyRow(unittest.TestCase):
	def test_defaults(self):
		row = empty_row(_line())
		self.assertEqual(row["koli"], 1)
		self.assertEqual(row["berat"], "")
		self.assertEqual(row["box_size"], "")


class TestOverlaySaved(unittest.TestCase):
	def test_saved_replaces_customers(self):
		groups = [
			{
				"delivery_date": "2026-11-13",
				"vehicle": "",
				"driver": "",
				"customers": [{"customer": "CUST-1", "dry": [], "frozen": []}],
			}
		]
		overlay_saved(
			groups,
			{
				"2026-11-13": {
					"vehicle": "B 123 ABC",
					"driver": "Sofyan",
					"customers": [{"customer": "CUST-1", "dry": [{"item_code": "X"}], "frozen": []}],
				}
			},
		)
		self.assertEqual(groups[0]["vehicle"], "B 123 ABC")
		self.assertEqual(groups[0]["customers"][0]["dry"][0]["item_code"], "X")

	def test_without_saved_keeps_derived(self):
		groups = [{"delivery_date": "2026-11-13", "vehicle": "", "driver": "", "customers": []}]
		overlay_saved(groups, {})
		self.assertEqual(groups[0]["customers"], [])
