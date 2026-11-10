# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

import unittest

from warehouse_app.warehouse_app.fulfillment.workspace import next_action


DRAFT_PL = {"docstatus": 0}
SUBMITTED_PL = {"docstatus": 1}
DRAFT_DN = {"docstatus": 0}
SUBMITTED_DN = {"docstatus": 1}


class TestNextAction(unittest.TestCase):
	def test_no_pick_list_disables_finish_picking(self):
		self.assertEqual(
			next_action([], None, False),
			{
				"key": "finish_picking",
				"label": "Finish picking",
				"enabled": False,
				"reason": "NO_PICK_LIST",
			},
		)

	def test_draft_pick_list_finishes_picking(self):
		self.assertEqual(next_action([DRAFT_PL], None, False)["key"], "finish_picking")
		self.assertTrue(next_action([DRAFT_PL], None, False)["enabled"])

	def test_draft_pick_list_wins_over_submitted_pick_list(self):
		action = next_action([SUBMITTED_PL, DRAFT_PL], None, False)
		self.assertEqual(action["key"], "finish_picking")

	def test_submitted_pick_lists_create_delivery_note(self):
		self.assertEqual(next_action([SUBMITTED_PL], None, False)["key"], "create_delivery_note")

	def test_empty_or_inactive_pick_list_group_is_ignored(self):
		self.assertEqual(
			next_action([SUBMITTED_PL, {"pick_list": None, "docstatus": None}], None, False)["key"],
			"create_delivery_note",
		)

	def test_short_pick_blocker_wins_over_pick_list_and_delivery_states(self):
		for pick_lists, delivery_note, packed in (
			([DRAFT_PL], None, False),
			([SUBMITTED_PL], None, False),
			([SUBMITTED_PL], DRAFT_DN, True),
		):
			with self.subTest(delivery_note=delivery_note, packed=packed):
				action = next_action(pick_lists, delivery_note, packed, "SHORT_PICK_BLOCKED")
				self.assertEqual(action["key"], "review_short_pick")
				self.assertEqual(action["reason"], "SHORT_PICK_BLOCKED")

	def test_draft_unpacked_delivery_note_packs_all(self):
		self.assertEqual(next_action([SUBMITTED_PL], DRAFT_DN, False)["key"], "pack_all")

	def test_skip_packing_slip_advances_directly_to_submit_delivery_note(self):
		action = next_action([SUBMITTED_PL], DRAFT_DN, False, enable_packing_slip=False)
		self.assertEqual(action["key"], "submit_delivery_note")
		self.assertTrue(action["enabled"])

	def test_packed_delivery_note_is_submitted_next(self):
		action = next_action([SUBMITTED_PL], DRAFT_DN, True)
		self.assertEqual(action["key"], "submit_delivery_note")

	def test_submitted_delivery_note_is_done(self):
		action = next_action([SUBMITTED_PL], SUBMITTED_DN, True)
		self.assertEqual(action["key"], "done")
		self.assertFalse(action["enabled"])
