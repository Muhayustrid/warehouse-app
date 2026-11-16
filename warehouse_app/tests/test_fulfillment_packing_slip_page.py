# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

import unittest

from warehouse_app.warehouse_app.fulfillment.packing_slip_page import (
	slip_lines_from_ps_items,
	slip_totals,
)


def _item(**overrides):
	row = {
		"item_code": "PJ260010",
		"item_name": "Roti Tawar",
		"qty": 5,
		"net_weight": 2.65,
		"stock_uom": "Pcs",
	}
	row.update(overrides)
	return row


class TestSlipLinesFromPsItems(unittest.TestCase):
	def test_one_line_per_koli(self):
		# 2 Packing Slips (koli) with items -> one line per koli, item can repeat.
		ps_items = [
			[_item(qty=5, net_weight=2.65)],
			[_item(qty=3, net_weight=1.59), _item(item_code="BB260001", item_name="Terigu", qty=1, net_weight=0.5)],
		]
		lines = slip_lines_from_ps_items(ps_items)
		self.assertEqual(len(lines), 3)
		self.assertEqual([l["koli_no"] for l in lines], [1, 2, 2])
		self.assertEqual([l["category"] for l in lines], ["frozen", "frozen", "frozen"])
		self.assertEqual(lines[0]["qty"], 5)
		self.assertEqual(lines[2]["item_code"], "BB260001")

	def test_category_from_slip_category(self):
		ps_items = [[_item(qty=1, net_weight=0)], [_item(qty=1, net_weight=0)]]
		categories = ["dry", "frozen"]
		lines = slip_lines_from_ps_items(ps_items, categories=categories)
		self.assertEqual([l["category"] for l in lines], ["dry", "frozen"])

	def test_empty_slips_skipped(self):
		lines = slip_lines_from_ps_items([[], [_item()]])
		self.assertEqual(len(lines), 1)
		self.assertEqual(lines[0]["koli_no"], 2)


class TestSlipTotals(unittest.TestCase):
	def test_totals(self):
		lines = [
			{"category": "dry", "koli": 2, "berat": "3.5"},
			{"category": "dry", "koli": 1, "berat": "2"},
			{"category": "frozen", "koli": 1, "berat": "", "estimated_weight": 5.3},
		]
		totals = slip_totals(lines)
		self.assertEqual(totals["total_dry_colly"], 3)
		self.assertEqual(totals["net_weight_dry"], 5.5)
		self.assertEqual(totals["total_frozen_colly"], 1)
		self.assertEqual(totals["net_weight_frozen"], 5.3)

	def test_empty(self):
		totals = slip_totals([])
		self.assertEqual(totals["total_dry_colly"], 0)
		self.assertEqual(totals["net_weight_dry"], 0)


if __name__ == "__main__":
	unittest.main()
