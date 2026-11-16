# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

import unittest

from warehouse_app.warehouse_app.fulfillment.pick_print import combined_pick_rows

RUNS = [
	{
		"name": "R1",
		"customer": "RS A",
		"delivery_date": "2026-11-17",
		"dry_pick_list": "PL-D1",
		"frozen_pick_list": "PL-F1",
		"status": "IN_PICKING",
	},
	{
		"name": "R2",
		"customer": "RS B",
		"delivery_date": "2026-11-17",
		"dry_pick_list": None,
		"frozen_pick_list": "PL-F2",
		"status": "IN_PACKING",
	},
]

ROWS = {
	"PL-F1": [
		{"item_code": "FJ1", "item_name": "Frozen 1", "qty": 3.0, "picked_qty": 0.0, "stock_uom": "Pcs", "warehouse": "GF - JURI"},
	],
	"PL-D1": [
		{"item_code": "DJ1", "item_name": "Dry 1", "qty": 2.0, "picked_qty": 2.0, "stock_uom": "Pcs", "warehouse": "GD - JURI"},
	],
	"PL-F2": [
		{"item_code": "FJ2", "item_name": "Frozen 2", "qty": 1.0, "picked_qty": 1.0, "stock_uom": "Pcs", "warehouse": "GF - JURI"},
	],
}


class TestCombinedPickRows(unittest.TestCase):
	def test_frozen_rows_first_then_customer_then_item(self):
		rows = combined_pick_rows(RUNS, lambda n: ROWS[n])
		self.assertEqual([r["group"] for r in rows], ["FROZEN", "FROZEN", "DRY"])
		self.assertEqual(rows[0]["customer"], "RS A")
		self.assertEqual(rows[1]["customer"], "RS B")

	def test_qty_uses_picked_qty_when_set(self):
		rows = {r["item_code"]: r for r in combined_pick_rows(RUNS, lambda n: ROWS[n])}
		self.assertEqual(rows["DJ1"]["qty"], 2.0)  # picked
		self.assertEqual(rows["FJ1"]["qty"], 3.0)  # not picked -> planned qty

	def test_run_without_lists_is_skipped(self):
		runs = RUNS + [
			{
				"name": "R3",
				"customer": "RS C",
				"delivery_date": "2026-11-17",
				"dry_pick_list": None,
				"frozen_pick_list": None,
				"status": "IN_PICKING",
			}
		]
		self.assertFalse(any(r["customer"] == "RS C" for r in combined_pick_rows(runs, lambda n: ROWS[n])))


if __name__ == "__main__":
	unittest.main()
