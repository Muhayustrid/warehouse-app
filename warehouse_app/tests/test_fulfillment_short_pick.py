# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

import unittest

from warehouse_app.warehouse_app.fulfillment.short_pick import (
	finish_blocker,
	short_fingerprint,
	short_rows,
)


class TestShortPickRules(unittest.TestCase):
	def test_empty_short_rows(self):
		self.assertEqual(short_rows([]), [])
		self.assertEqual(len(short_fingerprint([])), 64)

	def test_short_row_uses_custom_picked_qty(self):
		rows = [
			{"pick_list": "PL-1", "row": "r1", "item_code": "A", "qty": 10, "custom_picked_qty": 7},
			{"pick_list": "PL-1", "row": "r2", "item_code": "B", "qty": 5, "custom_picked_qty": 5},
		]
		self.assertEqual([row["row"] for row in short_rows(rows)], ["r1"])

	def test_zero_is_not_a_short_row(self):
		rows = [{"pick_list": "PL-1", "row": "r1", "item_code": "A", "qty": 10, "custom_picked_qty": 0}]
		self.assertEqual(short_rows(rows), [])

	def test_fingerprint_changes_when_short_qty_changes(self):
		base = [{"pick_list": "PL-1", "row": "r1", "item_code": "A", "qty": 10, "custom_picked_qty": 7}]
		changed = [{**base[0], "custom_picked_qty": 6}]
		self.assertNotEqual(short_fingerprint(base), short_fingerprint(changed))

	def test_fingerprint_is_order_independent(self):
		a = {"pick_list": "PL-1", "row": "r1", "item_code": "A", "qty": 10, "custom_picked_qty": 7}
		b = {"pick_list": "PL-2", "row": "r2", "item_code": "B", "qty": 8, "custom_picked_qty": 3}
		self.assertEqual(short_fingerprint([a, b]), short_fingerprint([b, a]))

	def test_block_policy_blocks_any_short(self):
		short = [{"pick_list": "PL-1", "row": "r1", "item_code": "A", "qty": 10, "custom_picked_qty": 7}]
		self.assertEqual(finish_blocker(short, False, None, None), "SHORT_PICK_BLOCKED")

	def test_approval_requires_matching_fingerprint(self):
		short = [{"pick_list": "PL-1", "row": "r1", "item_code": "A", "qty": 10, "custom_picked_qty": 7}]
		fp = short_fingerprint(short)
		self.assertEqual(finish_blocker(short, True, "None", fp), "SHORT_PICK_APPROVAL_PENDING")
		self.assertEqual(finish_blocker(short, True, "Rejected", fp), "SHORT_PICK_APPROVAL_REJECTED")
		self.assertEqual(finish_blocker(short, True, "Approved", "wrong"), "SHORT_PICK_STALE_APPROVAL")
		self.assertIsNone(finish_blocker(short, True, "Approved", fp))
		self.assertIsNone(finish_blocker(short, False, "Approved", fp))
