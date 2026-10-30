# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

import unittest

from warehouse_app.warehouse_app.fulfillment.packing import (
	distribute_items_across_packages,
	plan_packing_slips,
)


class TestPackingDistribution(unittest.TestCase):
	def test_distribute_single_package(self):
		items = [{"item_code": "ROTI-A", "qty": 10, "dn_detail": "row1"}]
		result = distribute_items_across_packages(items, 1)
		self.assertEqual(len(result), 1)
		self.assertEqual(result[0], [{"item_code": "ROTI-A", "qty": 10, "dn_detail": "row1"}])

	def test_distribute_even_split(self):
		items = [{"item_code": "ROTI-A", "qty": 10, "dn_detail": "row1"}]
		result = distribute_items_across_packages(items, 2)
		self.assertEqual(len(result), 2)
		self.assertEqual(result[0][0]["qty"], 5)
		self.assertEqual(result[1][0]["qty"], 5)

	def test_distribute_odd_split(self):
		items = [{"item_code": "ROTI-A", "qty": 5, "dn_detail": "row1"}]
		result = distribute_items_across_packages(items, 2)
		self.assertEqual(len(result), 2)
		self.assertEqual(result[0][0]["qty"], 3)
		self.assertEqual(result[1][0]["qty"], 2)
		self.assertEqual(sum(pkg[0]["qty"] for pkg in result), 5)

	def test_distribute_multiple_items_different_quantities(self):
		items = [
			{"item_code": "ROTI-A", "qty": 10, "dn_detail": "row1"},
			{"item_code": "ROTI-B", "qty": 3, "dn_detail": "row2"},
		]
		result = distribute_items_across_packages(items, 2)
		self.assertEqual(len(result), 2)
		# Sequential filling: ROTI-A fills pkg0 (7 pcs, ceil of 6.5), remaining 3 pcs in pkg1; ROTI-B stays whole (3 pcs) in pkg1
		self.assertEqual(result[0], [
			{"item_code": "ROTI-A", "qty": 7, "dn_detail": "row1"},
		])
		self.assertEqual(result[1], [
			{"item_code": "ROTI-A", "qty": 3, "dn_detail": "row1"},
			{"item_code": "ROTI-B", "qty": 3, "dn_detail": "row2"},
		])

	def test_distribute_distinct_items_sequential(self):
		items = [
			{"item_code": "ROTI-A", "qty": 5, "dn_detail": "row1"},
			{"item_code": "ROTI-B", "qty": 5, "dn_detail": "row2"},
		]
		result = distribute_items_across_packages(items, 2)
		self.assertEqual(len(result), 2)
		# Box 0 has ROTI-A only, Box 1 has ROTI-B only (no needless splitting!)
		self.assertEqual(result[0], [{"item_code": "ROTI-A", "qty": 5, "dn_detail": "row1"}])
		self.assertEqual(result[1], [{"item_code": "ROTI-B", "qty": 5, "dn_detail": "row2"}])

	def test_distribute_item_less_than_package_count(self):
		items = [{"item_code": "ROTI-A", "qty": 1, "dn_detail": "row1"}]
		result = distribute_items_across_packages(items, 3)
		self.assertEqual(len(result), 3)
		self.assertEqual(result[0], [{"item_code": "ROTI-A", "qty": 1, "dn_detail": "row1"}])
		self.assertEqual(result[1], [])
		self.assertEqual(result[2], [])

	def test_plan_packing_slips_dry_and_frozen(self):
		dry_items = [{"item_code": "ROTI-A", "qty": 10, "dn_detail": "d1"}]
		frozen_items = [{"item_code": "ADONAN-F", "qty": 5, "dn_detail": "f1"}]

		plan = plan_packing_slips(dry_items, frozen_items, dry_packages=2, frozen_packages=1)
		self.assertEqual(len(plan), 3)

		# Pkg 1: Dry (5 pcs)
		self.assertEqual(plan[0]["category"], "dry")
		self.assertEqual(plan[0]["case_no"], 1)
		self.assertEqual(plan[0]["items"][0]["qty"], 5)

		# Pkg 2: Dry (5 pcs)
		self.assertEqual(plan[1]["category"], "dry")
		self.assertEqual(plan[1]["case_no"], 2)
		self.assertEqual(plan[1]["items"][0]["qty"], 5)

		# Pkg 3: Frozen (5 pcs)
		self.assertEqual(plan[2]["category"], "frozen")
		self.assertEqual(plan[2]["case_no"], 3)
		self.assertEqual(plan[2]["items"][0]["qty"], 5)

	def test_plan_packing_slips_dry_only(self):
		dry_items = [{"item_code": "ROTI-A", "qty": 10, "dn_detail": "d1"}]
		plan = plan_packing_slips(dry_items, [], dry_packages=1, frozen_packages=0)
		self.assertEqual(len(plan), 1)
		self.assertEqual(plan[0]["category"], "dry")
		self.assertEqual(plan[0]["case_no"], 1)

	def test_plan_packing_slips_frozen_only(self):
		frozen_items = [{"item_code": "ADONAN-F", "qty": 6, "dn_detail": "f1"}]
		plan = plan_packing_slips([], frozen_items, dry_packages=0, frozen_packages=2)
		self.assertEqual(len(plan), 2)
		self.assertEqual(plan[0]["category"], "frozen")
		self.assertEqual(plan[0]["case_no"], 1)
		self.assertEqual(plan[0]["items"][0]["qty"], 3)
		self.assertEqual(plan[1]["category"], "frozen")
		self.assertEqual(plan[1]["case_no"], 2)
		self.assertEqual(plan[1]["items"][0]["qty"], 3)

	def test_split_delivery_items_by_pick_list(self):
		from warehouse_app.warehouse_app.fulfillment.packing import split_delivery_items_by_category

		items = [
			{"item_code": "ROTI-A", "qty": 5, "against_pick_list": "PL-DRY"},
			{"item_code": "ADONAN-F", "qty": 3, "against_pick_list": "PL-FROZEN"},
		]
		dry, frozen = split_delivery_items_by_category(items, dry_pl="PL-DRY", frozen_pl="PL-FROZEN")
		self.assertEqual(len(dry), 1)
		self.assertEqual(dry[0]["item_code"], "ROTI-A")
		self.assertEqual(len(frozen), 1)
		self.assertEqual(frozen[0]["item_code"], "ADONAN-F")

	def test_case_numbers_are_sequential_and_no_gap(self):
		dry_items = [{"item_code": "ROTI-A", "qty": 10, "dn_detail": "d1"}]
		frozen_items = [{"item_code": "ADONAN-F", "qty": 5, "dn_detail": "f1"}]
		plan = plan_packing_slips(dry_items, frozen_items, dry_packages=3, frozen_packages=2)
		self.assertEqual(len(plan), 5)
		case_nos = [p["case_no"] for p in plan]
		self.assertEqual(case_nos, [1, 2, 3, 4, 5])
		self.assertEqual([p["category"] for p in plan], ["dry", "dry", "dry", "frozen", "frozen"])
