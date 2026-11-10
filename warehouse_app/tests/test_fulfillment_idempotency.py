# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

import unittest

from warehouse_app.warehouse_app.fulfillment.idempotency import (
	request_hash,
	request_hash_payload,
	scope_key,
)


class TestScopeKey(unittest.TestCase):
	def test_deterministic(self):
		first = scope_key("u@example.com", "C", "SO-1", "GeneratePickLists", "key-1")
		second = scope_key("u@example.com", "C", "SO-1", "GeneratePickLists", "key-1")
		self.assertEqual(first, second)
		self.assertEqual(len(first), 64)

	def test_scope_changes(self):
		base = scope_key("u@example.com", "C", "SO-1", "GeneratePickLists", "key-1")
		self.assertNotEqual(base, scope_key("v@example.com", "C", "SO-1", "GeneratePickLists", "key-1"))
		self.assertNotEqual(base, scope_key("u@example.com", "D", "SO-1", "GeneratePickLists", "key-1"))
		self.assertNotEqual(base, scope_key("u@example.com", "C", "SO-2", "GeneratePickLists", "key-1"))
		self.assertNotEqual(base, scope_key("u@example.com", "C", "SO-1", "Other", "key-1"))
		self.assertNotEqual(base, scope_key("u@example.com", "C", "SO-1", "GeneratePickLists", "key-2"))

	def test_whitespace_normalized(self):
		self.assertEqual(
			scope_key(" u@example.com ", "C", " SO-1 ", "GeneratePickLists", " key-1 "),
			scope_key("u@example.com", "C", "SO-1", "GeneratePickLists", "key-1"),
		)


class TestRequestHash(unittest.TestCase):
	def test_deterministic(self):
		first = request_hash("SO-1", "2026-10-27 10:00:00", "GeneratePickLists")
		second = request_hash("SO-1", "2026-10-27 10:00:00", "GeneratePickLists")
		self.assertEqual(first, second)
		self.assertEqual(len(first), 64)

	def test_changed_modified_changes_hash(self):
		self.assertNotEqual(
			request_hash("SO-1", "2026-10-27 10:00:00", "GeneratePickLists"),
			request_hash("SO-1", "2026-10-27 10:01:00", "GeneratePickLists"),
		)


class TestRequestHashPayload(unittest.TestCase):
	def test_deterministic(self):
		payload = {"run": "WFR-1", "pls": ["PL-1", "PL-2"]}
		first = request_hash_payload(payload, "CreateDeliveryNote")
		second = request_hash_payload(payload, "CreateDeliveryNote")
		self.assertEqual(first, second)
		self.assertEqual(len(first), 64)

	def test_different_payload_changes_hash(self):
		h1 = request_hash_payload({"run": "WFR-1", "pls": ["PL-1"]}, "CreateDeliveryNote")
		h2 = request_hash_payload({"run": "WFR-1", "pls": ["PL-2"]}, "CreateDeliveryNote")
		self.assertNotEqual(h1, h2)

	def test_key_order_independence(self):
		p1 = {"b": 2, "a": 1, "c": [1, 2]}
		p2 = {"a": 1, "c": [1, 2], "b": 2}
		self.assertEqual(
			request_hash_payload(p1, "CreateDeliveryNote"),
			request_hash_payload(p2, "CreateDeliveryNote"),
		)

	def test_different_request_type_changes_hash(self):
		payload = {"run": "WFR-1"}
		h1 = request_hash_payload(payload, "TypeA")
		h2 = request_hash_payload(payload, "TypeB")
		self.assertNotEqual(h1, h2)


if __name__ == "__main__":
	unittest.main()
