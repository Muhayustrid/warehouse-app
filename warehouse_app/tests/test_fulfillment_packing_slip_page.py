# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

import unittest

from warehouse_app.warehouse_app.fulfillment.packing_slip_page import (
	_labels_page,
	csv_estimasi,
	packing_summary,
	sheet_card_html,
	sheet_koli_total,
	slip_lines_from_ps_items,
	slip_totals,
	validate_slip_lines,
)


class TestCsvEstimasi(unittest.TestCase):
	def test_krim_kopi_from_cream_columns(self):
		# Baris Krim Kopi ada di grup kolom CREAM (kolom 5-8): 45 x 0,7
		self.assertAlmostEqual(csv_estimasi("Dough Ropi Krim Kopi", 45), 31.5)

	def test_butter_from_dough_columns(self):
		# Butter qty 40 (grup DOUGH, berat item 0,8)
		self.assertAlmostEqual(csv_estimasi("Butter", 40), 32.0)

	def test_no_match(self):
		self.assertIsNone(csv_estimasi("Paper Bag Ropi", 50))

	def test_per_unit_weight_table_bottom(self):
		# Tabel "Item,Weight" di bawah CSV: Coklat = 0,74/kg walaupun baris
		# bulk-nya di master kosong.
		self.assertAlmostEqual(csv_estimasi("Dough Ropi Coklat", 5), 3.7)


class TestSheetCardColly(unittest.TestCase):
	def test_cap_colly_without_number(self):
		# Colly di caption kartu dicatat tulis tangan: tanpa angka.
		html = sheet_card_html("RS Uji", [_item()])
		self.assertIn("Colly", html)
		self.assertNotRegex(html, r"Colly\s*:\s*\d")


	def test_profile_classification_overrides_box_size(self):
		# Frozen Item Group dari profile menang atas custom_box_size koli:
		# koli B (dry) berisi item frozen tetap masuk FROZEN, dan sebaliknya.
		ps_items = [
			[_item(item_group="Produk Jadi Pabrik", qty=1)],
			[_item(item_code="BB260001", item_name="Terigu", item_group="Bahan Baku", qty=1)],
		]
		lines = slip_lines_from_ps_items(
			ps_items,
			categories=["dry", "frozen"],
			frozen={"Produk Jadi Pabrik"},
			dry_exceptions=set(),
		)
		self.assertEqual([l["category"] for l in lines], ["frozen", "dry"])

	def test_dry_exception_overrides_frozen_group(self):
		ps_items = [[_item(item_group="Produk Jadi Pabrik", item_code="PJ260009", qty=1)]]
		lines = slip_lines_from_ps_items(
			ps_items, frozen={"Produk Jadi Pabrik"}, dry_exceptions={"PJ260009"}
		)
		self.assertEqual(lines[0]["category"], "dry")


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


class TestLabelsPage(unittest.TestCase):
	def test_layout_centered_60x40(self):
		html = _labels_page("<div class='label'>x</div>", "Label Koli X")
		self.assertIn("@page{size:60mm 40mm", html)
		self.assertIn("margin:0 auto", html)
		self.assertIn("<div class='label'>x</div>", html)

	def test_empty_body_fallback(self):
		self.assertIn("Tidak ada label.", _labels_page("", "T"))


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

	def test_dry_fallback_estimasi(self):
		# Dry tanpa match CSV: fallback estimasi = weight_per_unit x qty.
		ps_items = [[_item(item_name="Paper Bag Ropi", qty=10, net_weight=0.05, weight_per_unit=0.05)]]
		lines = slip_lines_from_ps_items(ps_items, categories=["dry"])
		self.assertEqual(lines[0]["estimated_weight"], 0.5)


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


class TestValidateSlipLines(unittest.TestCase):
	"""Validasi baris editor sebelum persist: item harus ada di DN, qty > 0,
	nomor koli >= 1."""

	def test_valid_lines_pass(self):
		lines = [{"item_code": "PJ260010", "qty": 5, "koli_no": 1}]
		self.assertEqual(validate_slip_lines(lines, dn_items={"PJ260010"}), [])

	def test_item_not_in_dn_rejected(self):
		lines = [{"item_code": "XX999", "qty": 5, "koli_no": 1}]
		errors = validate_slip_lines(lines, dn_items={"PJ260010"})
		self.assertEqual(len(errors), 1)
		self.assertIn("XX999", errors[0])

	def test_zero_qty_rejected(self):
		lines = [{"item_code": "PJ260010", "qty": 0, "koli_no": 1}]
		errors = validate_slip_lines(lines, dn_items={"PJ260010"})
		self.assertEqual(len(errors), 1)
		self.assertIn("PJ260010", errors[0])

	def test_missing_koli_defaults_ok(self):
		# koli_no kosong -> default 1, bukan error.
		lines = [{"item_code": "PJ260010", "qty": 2}]
		self.assertEqual(validate_slip_lines(lines, dn_items={"PJ260010"}), [])


class TestSheetCard(unittest.TestCase):
	"""Kartu customer pada sheet gabungan ala Image 2 (pure helpers)."""

	def _lines(self):
		return [
			{"item_name": "Krim Kopi", "qty": 45, "koli": 1, "berat": "", "category": "dry"},
			{"item_name": "Butter", "qty": 35, "koli": 1, "berat": "31.62", "category": "frozen", "estimated_weight": 31.62},
		]

	def test_card_layout(self):
		html = sheet_card_html("RS ISLAM AL-IKHLAS", self._lines())
		self.assertIn("RS ISLAM AL-IKHLAS", html)
		for col in ("Item", "Qty", "Koli", "Berat", "B / K", "Picker", "Estimasi"):
			self.assertIn(col, html)
		self.assertIn("31.62", html)  # estimasi frozen tampil

	def test_totals_and_dry_count(self):
		html = sheet_card_html("CUST", self._lines())
		self.assertIn("Dry : 1", html)
		self.assertIn("Colly", html)  # colly tanpa angka/titik dua, diisi tulis tangan
		self.assertIn("blank", html)  # kotak kosong antara Dry dan Colly
		self.assertIn("DRY", html)
		self.assertIn("FROZEN", html)
		self.assertIn("Total DRY", html)
		self.assertIn("Total FROZEN", html)
		self.assertLess(html.index("DRY"), html.index("FROZEN"))  # dry dulu, kayak picking list
		self.assertIn("<td>1</td>", html)  # total per tabel (1 koli dry + 1 koli frozen)

	def test_koli_total(self):
		self.assertEqual(sheet_koli_total(self._lines()), 2)
		self.assertEqual(sheet_koli_total([{"koli": ""}, {"koli": 3}]), 4)


class TestPackingSummary(unittest.TestCase):
	"""Agregat hasil packing per DN untuk tab Packing: koli dry/frozen +
	berat + driver dari dokumen PS."""

	def test_summary_counts_koli_and_weight(self):
		ps_docs = [
			{
				"from_case_no": 1,
				"custom_box_size": "K",
				"net_weight_pkg": 9.99,
				"custom_driver": "Ismail",
				"custom_vehicle_no": "B 1234 XYZ",
			},
			{
				"from_case_no": 2,
				"custom_box_size": "B",
				"net_weight_pkg": 4.5,
				"custom_driver": "Ismail",
				"custom_vehicle_no": "B 1234 XYZ",
			},
		]
		summary = packing_summary(ps_docs)
		self.assertEqual(summary["koli_frozen"], 1)
		self.assertEqual(summary["koli_dry"], 1)
		self.assertEqual(summary["weight_frozen"], 9.99)
		self.assertEqual(summary["weight_dry"], 4.5)
		self.assertEqual(summary["driver"], "Ismail")
		self.assertEqual(summary["vehicle_no"], "B 1234 XYZ")
		self.assertTrue(summary["packed"])

	def test_empty_means_not_packed(self):
		summary = packing_summary([])
		self.assertFalse(summary["packed"])
		self.assertEqual(summary["koli_frozen"], 0)
		self.assertEqual(summary["koli_dry"], 0)
		self.assertEqual(summary["driver"], "")


if __name__ == "__main__":
	unittest.main()
