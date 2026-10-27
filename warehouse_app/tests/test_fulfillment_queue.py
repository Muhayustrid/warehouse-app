# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

import unittest

from warehouse_app.warehouse_app.fulfillment.queue import (
	derive_stage,
	group_counts,
	is_eligible,
	safe_classify,
)


class TestDeriveStage(unittest.TestCase):
	def test_missing_profile_is_exception(self):
		self.assertEqual(
			derive_stage(False, False, True, False, False, True, False, True), "exception"
		)

	def test_unclassified_is_exception(self):
		self.assertEqual(
			derive_stage(True, True, False, False, False, False, False, True), "exception"
		)

	def test_draft_pick_list_is_picking(self):
		self.assertEqual(
			derive_stage(True, False, True, False, False, True, False, True), "picking"
		)

	def test_draft_pick_list_wins_over_draft_dn(self):
		self.assertEqual(
			derive_stage(True, False, True, True, True, False, False, True), "picking"
		)

	def test_draft_dn_fully_packed_is_ready(self):
		self.assertEqual(
			derive_stage(True, False, False, True, True, True, False, True), "ready"
		)

	def test_draft_dn_not_packed_is_packing(self):
		self.assertEqual(
			derive_stage(True, False, False, True, False, True, False, True), "packing"
		)

	def test_submitted_pl_without_dn_is_packing(self):
		self.assertEqual(
			derive_stage(True, False, False, False, False, True, False, True), "packing"
		)

	def test_partial_delivery_without_active_drafts_is_partially_delivered(self):
		self.assertEqual(
			derive_stage(True, False, False, False, False, False, True, True),
			"partially_delivered",
		)

	def test_partial_delivery_with_draft_pl_is_picking(self):
		self.assertEqual(
			derive_stage(True, False, True, False, False, False, True, True), "picking"
		)

	def test_no_documents_is_open(self):
		self.assertEqual(
			derive_stage(True, False, False, False, False, False, False, True), "open"
		)


class TestGroupCounts(unittest.TestCase):
	def test_counts_do_not_merge_duplicate_item_codes(self):
		items = [
			{"sales_order_item": "SO-1", "classification": "dry"},
			{"sales_order_item": "SO-2", "classification": "dry"},
			{"sales_order_item": "SO-3", "classification": "frozen"},
		]
		self.assertEqual(group_counts(items), {"dry": 2, "frozen": 1, "unclassified": 0})

	def test_counts_ignore_mixed_uom_quantities(self):
		items = [
			{"sales_order_item": "SO-1", "classification": "dry", "qty": 10, "uom": "Kg"},
			{"sales_order_item": "SO-2", "classification": "dry", "qty": 5, "uom": "Pcs"},
		]
		self.assertEqual(group_counts(items), {"dry": 2, "frozen": 0, "unclassified": 0})

	def test_unknown_classification_counts_as_unclassified(self):
		self.assertEqual(
			group_counts([{"sales_order_item": "SO-1", "classification": "unknown"}]),
			{"dry": 0, "frozen": 0, "unclassified": 1},
		)


class TestSafeClassify(unittest.TestCase):
	def test_missing_group_is_unclassified(self):
		self.assertEqual(safe_classify(None, {"Frozen"}), ("unclassified", "item_group_missing"))

	def test_missing_profile_is_unclassified(self):
		self.assertEqual(safe_classify("Dry", None), ("unclassified", "profile_missing"))

	def test_frozen_and_dry_values(self):
		self.assertEqual(safe_classify("Frozen", {"Frozen"}), ("frozen", None))
		self.assertEqual(safe_classify("Dry", {"Frozen"}), ("dry", None))


class TestEligibility(unittest.TestCase):
	def test_eligible_open_order(self):
		self.assertTrue(is_eligible(1, "To Deliver", 0.0, 5.0))

	def test_ineligible_when_fully_delivered(self):
		self.assertFalse(is_eligible(1, "To Deliver", 100.0, 0.0))

	def test_ineligible_when_closed_or_cancelled(self):
		self.assertFalse(is_eligible(1, "Closed", 0.0, 5.0))
		self.assertFalse(is_eligible(1, "Cancelled", 0.0, 5.0))

	def test_ineligible_draft(self):
		self.assertFalse(is_eligible(0, "Draft", 0.0, 5.0))

	def test_ineligible_without_outstanding(self):
		self.assertFalse(is_eligible(1, "To Deliver", 0.0, 0.0))


if __name__ == "__main__":
	unittest.main()
