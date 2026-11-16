# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

import unittest
from unittest.mock import patch

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


class TestPickListHtml(unittest.TestCase):
	def test_html_groups_and_empty_state(self):
		from warehouse_app.warehouse_app.fulfillment.pick_print import _pick_list_html

		rows = combined_pick_rows(RUNS, lambda n: ROWS[n])
		html = _pick_list_html(rows, "2026-11-17", "PT. JUARA ROTI INDONESIA")
		self.assertIn("FROZEN", html)
		self.assertIn("DRY", html)
		self.assertIn("RS A", html)
		self.assertIn("2026-11-17", html)
		empty = _pick_list_html([], "2026-11-17", "PT. JUARA ROTI INDONESIA")
		self.assertIn("Tidak ada pick list", empty)

	def test_html_escapes_user_data(self):
		from warehouse_app.warehouse_app.fulfillment.pick_print import _pick_list_html

		rows = [
			{
				"group": "DRY",
				"customer": "<script>x</script>",
				"delivery_date": "2026-11-17",
				"pick_list": "PL",
				"item_code": "I1",
				"item_name": "<img src=x onerror=alert(1)>",
				"qty": 1.0,
				"stock_uom": "Pcs",
				"warehouse": "W & H",
			}
		]
		html = _pick_list_html(rows, "2026-11-17", "Co <b> Ltd")
		self.assertNotIn("<script>x</script>", html)
		self.assertNotIn("<img src=x", html)
		self.assertIn("&lt;script&gt;", html)
		self.assertIn("W &amp; H", html)


class TestLoadCombinedPickRowsFiltering(unittest.TestCase):
	"""load_combined_pick_rows must filter by SO delivery_date — the paper is
	per delivery date (H-1), not 'every active run'."""

	def _run_load(self, run_delivery, requested):
		import warehouse_app.warehouse_app.fulfillment.pick_print as pp

		def fake_get_all(doctype, filters=None, fields=None, order_by=None, as_list=False, pluck=None):
			if doctype == pp.RUN:
				if fields and "dry_pick_list" in fields:
					return [
						{
							"name": "WFR-1",
							"company": "CO",
							"customer": "C",
							"status": "IN_PICKING",
							"dry_pick_list": "PL-D",
							"frozen_pick_list": None,
							"sales_order": "SO-1",
						}
					]
				return [{"name": "WFR-1", "sales_order": "SO-1"}]
			if doctype == "Sales Order":
				return [("SO-1", run_delivery)]
			return []

		frappe_flags = {}
		with patch.object(pp, "pick_run_names", return_value=["WFR-1"]), patch.object(
			pp.frappe, "get_all", side_effect=fake_get_all
		), patch.object(pp, "_pick_list_rows", return_value=[
			{"item_code": "I", "item_name": "N", "qty": 1.0, "picked_qty": 0.0, "stock_uom": "Pcs", "warehouse": "W"}
		]):
			return pp.load_combined_pick_rows("CO", requested)

	def test_rows_only_for_requested_delivery_date(self):
		rows = self._run_load("2026-11-17", "2026-11-17")
		self.assertEqual(len(rows), 1)

	def test_rows_empty_when_delivery_date_differs(self):
		rows = self._run_load("2026-11-18", "2026-11-17")
		self.assertEqual(rows, [])


class TestDeliverySummary(unittest.TestCase):
	"""Ringkasan kirim per customer untuk satu tanggal kirim."""

	def _fake_pp(self, dn_doc):
		import warehouse_app.warehouse_app.fulfillment.pick_print as pp

		def fake_get_all(doctype, filters=None, fields=None, order_by=None, as_list=False, pluck=None):
			if doctype == "Sales Order":
				return ["SO-1"]
			if doctype == pp.RUN:
				return [
					{"name": "WFR-1", "customer": "RS A", "delivery_note": "DN-1"},
					{"name": "WFR-2", "customer": "RS B", "delivery_note": None},
				]
			return []

		with patch.object(pp.frappe, "get_all", side_effect=fake_get_all), patch.object(
			pp.frappe, "get_doc", return_value=dn_doc
		):
			return pp.load_delivery_summary_rows("CO", "2026-11-17")

	def test_summary_groups_koli_and_items(self):
		class Row:
			def __init__(self, d):
				self.__dict__.update(d)

		class DN:
			name = "DN-1"
			docstatus = 1
			custom_dry_packages = 2
			custom_frozen_packages = 1
			items = [
				Row({"item_code": "I1", "item_name": "Item 1", "qty": 5.0, "uom": "Pcs", "stock_uom": "Pcs"}),
			]

		customers = self._fake_pp(DN())
		self.assertEqual(len(customers), 1)
		c = customers[0]
		self.assertEqual(c["customer"], "RS A")
		self.assertEqual(c["dry_packages"], 2)
		self.assertEqual(c["frozen_packages"], 1)
		self.assertEqual(c["items"][0]["item_code"], "I1")

	def test_run_without_dn_is_skipped(self):
		class EmptyDN:
			name = "DN-X"
			docstatus = 1
			custom_dry_packages = 0
			custom_frozen_packages = 0
			items = []

		customers = self._fake_pp(EmptyDN())
		self.assertEqual([c["customer"] for c in customers], ["RS A"])

	def test_html_escapes_user_data(self):
		from warehouse_app.warehouse_app.fulfillment.pick_print import _delivery_summary_html

		customers = [
			{
				"customer": "<script>x</script>",
				"delivery_note": "DN-1",
				"dry_packages": 2,
				"frozen_packages": 1,
				"items": [{"item_code": "I1", "item_name": "<img src=x>", "qty": 1.0, "uom": "Pcs"}],
			}
		]
		html = _delivery_summary_html(customers, "2026-11-17", "Co & Sons")
		self.assertNotIn("<script>x</script>", html)
		self.assertNotIn("<img src=x>", html)
		self.assertIn("Total 3 koli", html)


if __name__ == "__main__":
	unittest.main()
