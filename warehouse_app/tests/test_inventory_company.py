# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto and contributors
# For license information, please see license.txt

"""Regression tests for Company filtering and permissions in inventory.py.

Verifies:
1. Explicit company filtering across all endpoints: stock_cards, movements,
   stock_balance, and export (cards + movements).
2. Positional pagination backwards compatibility (page, page_len preserved when
   company is omitted or appended).
3. Permission enforcement:
   - filter_options respects Warehouse and Company user permissions without
     corrupting %(up_warehouse)s placeholders.
   - stock_balance and inventory_info respect Company user permissions via w.company.
4. filter_options response shape: retains warehouses array, adds companies array
   and warehouse_company mapping.
5. No-company backward compatibility for all endpoints.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Locate apps directory and setup test stubs
_p = Path(__file__).resolve()
_apps = None
for parent in _p.parents:
    if (parent / "production_app" / "production_app" / "tests" / "frappe_stub.py").is_file():
        _apps = parent
        break
    if (parent / "apps" / "production_app" / "production_app" / "tests" / "frappe_stub.py").is_file():
        _apps = parent / "apps"
        break

if not _apps:
    raise RuntimeError("Cannot locate production_app frappe_stub")

sys.path.insert(0, str(_apps / "production_app" / "production_app" / "tests"))
sys.path.insert(0, str(_p.parents[2]))  # repo/worktree root containing warehouse_app package

import frappe_stub
import frappe

# Setup required frappe attributes if missing from stub
if not hasattr(frappe, "permissions"):
    frappe.permissions = MagicMock()
if not hasattr(frappe, "response"):
    frappe.response = {}
if not hasattr(frappe.db, "sql_list"):
    frappe.db.sql_list = MagicMock(return_value=[])

_fu = sys.modules.get("frappe.utils")
if _fu:
    _fu.getdate = lambda d: d
    _fu.add_days = lambda d, n: f"{d}+{n}d"
    frappe.utils = _fu

# Stub csvutils and xlsxutils for export tests without third-party dependencies
_csvutils = frappe_stub.make_stub("frappe.utils.csvutils") if hasattr(frappe_stub, "make_stub") else MagicMock()
_csvutils.to_csv = MagicMock(return_value="csv,content")
sys.modules["frappe.utils.csvutils"] = _csvutils

_xlsxutils = frappe_stub.make_stub("frappe.utils.xlsxutils") if hasattr(frappe_stub, "make_stub") else MagicMock()
_xlsx_mock_io = MagicMock()
_xlsx_mock_io.getvalue.return_value = b"xlsx-content"
_xlsxutils.make_xlsx = MagicMock(return_value=_xlsx_mock_io)
sys.modules["frappe.utils.xlsxutils"] = _xlsxutils

from warehouse_app.warehouse_app import inventory as inv


class TestInventoryCompanyRegression(unittest.TestCase):
    def setUp(self):
        frappe.session = frappe._dict(user="test_user@example.com")
        frappe.has_permission = MagicMock(return_value=True)
        frappe.permissions.get_user_permissions = MagicMock(return_value={})
        frappe.db.get_value = MagicMock(return_value=None)
        frappe.response = {}

    def test_stock_cards_explicit_company(self):
        """stock_cards with company applies s.company filter in SQL."""
        captured_queries = []

        def mock_sql(query, values=None, as_dict=False):
            captured_queries.append((query, values or {}))
            if "count(*)" in query.lower():
                return [(1,)]
            return [
                frappe._dict(
                    name="SLE-001",
                    item_code="ITEM-01",
                    item_name="Item 1",
                    warehouse="Gudang A",
                    posting_datetime="2026-10-01 10:00:00",
                    voucher_type="Stock Entry",
                    voucher_no="STE-001",
                    voucher_detail_no="STED-001",
                    qty_after_transaction=10,
                    stock_value=100000,
                    stock_value_difference=10000,
                    qty_change=10,
                    factor=1,
                    uom="Pcs",
                )
            ]

        with patch.object(frappe.db, "sql", side_effect=mock_sql), \
             patch.object(inv, "_voucher_remarks", return_value={}), \
             patch.object(inv, "_counterparties", return_value={}):
            res = inv.stock_cards(company="PT Juara Roti")

        self.assertEqual(res["total"], 1)
        self.assertTrue(len(captured_queries) >= 1)
        count_query, count_values = captured_queries[0]
        self.assertIn("s.company = %(company)s", count_query)
        self.assertEqual(count_values.get("company"), "PT Juara Roti")

    def test_stock_cards_positional_args_backward_compatibility(self):
        """Calling stock_cards with positional pagination args (page=2, page_len=50)
        must not assign 2 to company or break offset/limit calculation."""
        captured_queries = []

        def mock_sql(query, values=None, as_dict=False):
            captured_queries.append((query, values or {}))
            if "count(*)" in query.lower():
                return [(100,)]
            return []

        with patch.object(frappe.db, "sql", side_effect=mock_sql), \
             patch.object(inv, "_voucher_remarks", return_value={}), \
             patch.object(inv, "_counterparties", return_value={}):
            # Positional call: from_date, to_date, warehouse, item, item_group, item_code, search, search_by, page, page_len
            res = inv.stock_cards(None, None, None, None, None, None, None, "name", 2, 50)

        self.assertTrue(len(captured_queries) >= 2)
        data_query, data_values = captured_queries[1]
        self.assertEqual(data_values.get("limit"), 50)
        self.assertEqual(data_values.get("offset"), 50)
        self.assertNotIn("s.company = %(company)s", data_query)
        self.assertIsNone(data_values.get("company"))

    def test_movements_explicit_company(self):
        """movements with company filters raw SLE records by company."""
        captured_queries = []

        def mock_sql(query, values=None, as_dict=False):
            captured_queries.append((query, values or {}))
            return []

        with patch.object(frappe.db, "sql", side_effect=mock_sql):
            inv.movements(company="PT Juara Roti")

        self.assertTrue(len(captured_queries) >= 1)
        q, vals = captured_queries[0]
        self.assertIn("s.company = %(company)s", q)
        self.assertEqual(vals.get("company"), "PT Juara Roti")

    def test_movements_positional_args_backward_compatibility(self):
        """Calling movements with positional page=2, page_len=50 must not treat page as company."""
        captured_queries = []

        def mock_sql(query, values=None, as_dict=False):
            captured_queries.append((query, values or {}))
            return []

        with patch.object(frappe.db, "sql", side_effect=mock_sql):
            # Positional call: from_date, to_date, warehouse, item, item_group, item_code, search, search_by, page, page_len
            res = inv.movements(None, None, None, None, None, None, None, "name", 2, 50)

        self.assertTrue(len(captured_queries) >= 1)
        q, vals = captured_queries[0]
        self.assertNotIn("s.company = %(company)s", q)
        self.assertIsNone(vals.get("company"))

    def test_stock_balance_explicit_company(self):
        """stock_balance with company filters by w.company and joins tabWarehouse."""
        captured_queries = []

        def mock_sql(query, values=None, as_dict=False):
            captured_queries.append((query, values or {}))
            if "count(*)" in query.lower():
                return [(0, 0.0)]
            return []

        with patch.object(frappe.db, "sql", side_effect=mock_sql):
            inv.stock_balance(company="PT Juara Roti")

        self.assertTrue(len(captured_queries) >= 1)
        q, vals = captured_queries[0]
        self.assertIn("w.company = %(company)s", q)
        self.assertIn("`tabWarehouse` w", q)
        self.assertEqual(vals.get("company"), "PT Juara Roti")

    def test_stock_balance_positional_args_backward_compatibility(self):
        """Calling stock_balance with positional page=2, page_len=50 must not treat page as company."""
        captured_queries = []

        def mock_sql(query, values=None, as_dict=False):
            captured_queries.append((query, values or {}))
            if "count(*)" in query.lower():
                return [(10, 50000.0)]
            return []

        with patch.object(frappe.db, "sql", side_effect=mock_sql):
            # Positional: warehouse, item, item_group, search, search_by, page, page_len
            inv.stock_balance(None, None, None, None, "name", 2, 50)

        self.assertTrue(len(captured_queries) >= 2)
        data_query, data_values = captured_queries[1]
        self.assertEqual(data_values.get("limit"), 50)
        self.assertEqual(data_values.get("offset"), 50)
        self.assertNotIn("w.company = %(company)s", data_query)
        self.assertIsNone(data_values.get("company"))

    def test_stock_balance_user_permission_company(self):
        """stock_balance respects User Permissions on Company (w.company in %(up_company)s)."""
        frappe.permissions.get_user_permissions = MagicMock(
            return_value={"Company": [{"doc": "PT Juara Roti"}]}
        )
        captured_queries = []

        def mock_sql(query, values=None, as_dict=False):
            captured_queries.append((query, values or {}))
            if "count(*)" in query.lower():
                return [(0, 0.0)]
            return []

        with patch.object(frappe.db, "sql", side_effect=mock_sql):
            inv.stock_balance()

        self.assertTrue(len(captured_queries) >= 1)
        q, vals = captured_queries[0]
        self.assertIn("w.company in %(up_company)s", q)
        self.assertIn("`tabWarehouse` w", q)
        self.assertEqual(vals.get("up_company"), ("PT Juara Roti",))

    def test_inventory_info_user_permission_company(self):
        """inventory_info respects User Permissions on Company."""
        frappe.permissions.get_user_permissions = MagicMock(
            return_value={"Company": [{"doc": "PT Juara Roti"}]}
        )
        captured_queries = []

        def mock_sql(query, values=None, as_dict=False):
            captured_queries.append((query, values or {}))
            return []

        with patch.object(frappe.db, "sql", side_effect=mock_sql):
            res = inv.inventory_info("ITEM-01", "Gudang A")

        self.assertIsNone(res)
        self.assertTrue(len(captured_queries) >= 1)
        q, vals = captured_queries[0]
        self.assertIn("w.company in %(up_company)s", q)
        self.assertEqual(vals.get("up_company"), ("PT Juara Roti",))

    def test_filter_options_permission_and_placeholder_integrity(self):
        """filter_options must respect Warehouse + Company user permissions without
        corrupting %(up_warehouse)s or %(up_company)s placeholders with string replacement."""
        frappe.permissions.get_user_permissions = MagicMock(
            return_value={
                "Warehouse": [{"doc": "Gudang Barang Jadi - RR"}],
                "Company": [{"doc": "PT Juara Roti"}],
            }
        )
        captured_queries = []

        def mock_sql(query, values=None, as_dict=False):
            captured_queries.append((query, values or {}))
            # Test that executing SQL with values dict has matching placeholder keys
            for k in values:
                self.assertIn(f"%({k})s", query, f"Placeholder %({k})s missing from query")
            self.assertNotIn("%(up_b.warehouse)s", query, "Corrupted placeholder %(up_b.warehouse)s found!")
            return [
                frappe._dict(warehouse="Gudang Barang Jadi - RR", company="PT Juara Roti")
            ]

        with patch.object(frappe.db, "sql", side_effect=mock_sql), \
             patch.object(frappe.db, "sql_list", return_value=["Finished Goods"]):
            res = inv.filter_options()

        self.assertEqual(res["warehouses"], ["Gudang Barang Jadi - RR"])
        self.assertEqual(res["companies"], ["PT Juara Roti"])
        self.assertEqual(res["warehouse_company"], {"Gudang Barang Jadi - RR": "PT Juara Roti"})
        self.assertEqual(res["item_groups"], ["Finished Goods"])
        self.assertTrue(res["can_export"])

        q, vals = captured_queries[0]
        self.assertIn("b.warehouse in %(up_warehouse)s", q)
        self.assertIn("w.company in %(up_company)s", q)
        self.assertEqual(vals.get("up_warehouse"), ("Gudang Barang Jadi - RR",))
        self.assertEqual(vals.get("up_company"), ("PT Juara Roti",))

    def test_export_explicit_company(self):
        """export forwards company filter to stock_cards and movements."""
        with patch.object(inv, "_stock_cards", return_value=([], 0)) as mock_cards, \
             patch.object(inv, "_movement_agg", return_value=[]) as mock_mov:

            inv.export(kind="cards", file_format="xlsx", company="PT Juara Roti")
            args_cards = mock_cards.call_args[0][0]
            # args_cards: (from_date, to_date, warehouse, item, item_group, item_code, search, search_by, company)
            self.assertEqual(args_cards[-1], "PT Juara Roti")
            self.assertEqual(frappe.response.get("type"), "binary")
            self.assertTrue(frappe.response.get("filename", "").endswith(".xlsx"))

            inv.export(kind="cards", file_format="csv", company="PT Juara Roti")
            self.assertEqual(frappe.response.get("type"), "binary")
            self.assertTrue(frappe.response.get("filename", "").endswith(".csv"))

            inv.export(kind="movements", company="PT Juara Roti")
            # _movement_agg(from_date, to_date, warehouse, item, item_group, item_code, search, search_by, company)
            self.assertEqual(mock_mov.call_args[0][-1], "PT Juara Roti")

    def test_filter_options_no_permissions(self):
        """filter_options without user permissions returns all warehouses, distinct companies, and mapping."""
        frappe.permissions.get_user_permissions = MagicMock(return_value={})
        captured_queries = []

        def mock_sql(query, values=None, as_dict=False):
            captured_queries.append((query, values or {}))
            return [
                frappe._dict(warehouse="Gudang A", company="Company 1"),
                frappe._dict(warehouse="Gudang B", company="Company 1"),
                frappe._dict(warehouse="Gudang C", company="Company 2"),
            ]

        with patch.object(frappe.db, "sql", side_effect=mock_sql), \
             patch.object(frappe.db, "sql_list", return_value=["Group 1"]):
            res = inv.filter_options()

        self.assertEqual(res["warehouses"], ["Gudang A", "Gudang B", "Gudang C"])
        self.assertEqual(res["companies"], ["Company 1", "Company 2"])
        self.assertEqual(
            res["warehouse_company"],
            {"Gudang A": "Company 1", "Gudang B": "Company 1", "Gudang C": "Company 2"},
        )
        self.assertIn("where 1=1", captured_queries[0][0])

    def test_combined_positional_pagination_with_company(self):
        """Calling endpoints with positional page/page_len AND company keyword works cleanly."""
        captured_queries = []

        def mock_sql(query, values=None, as_dict=False):
            captured_queries.append((query, values or {}))
            if "count(*)" in query.lower():
                return [(100, 1000.0)]
            return []

        # stock_cards
        with patch.object(frappe.db, "sql", side_effect=mock_sql), \
             patch.object(inv, "_voucher_remarks", return_value={}), \
             patch.object(inv, "_counterparties", return_value={}):
            inv.stock_cards(None, None, None, None, None, None, None, "name", 3, 20, company="PT Juara Roti")

        self.assertTrue(len(captured_queries) >= 2)
        q, vals = captured_queries[1]
        self.assertEqual(vals.get("limit"), 20)
        self.assertEqual(vals.get("offset"), 40)
        self.assertEqual(vals.get("company"), "PT Juara Roti")
        self.assertIn("s.company = %(company)s", q)

        # stock_balance
        captured_queries.clear()
        with patch.object(frappe.db, "sql", side_effect=mock_sql):
            inv.stock_balance(None, None, None, None, "name", 3, 20, company="PT Juara Roti")

        self.assertTrue(len(captured_queries) >= 2)
        q, vals = captured_queries[1]
        self.assertEqual(vals.get("limit"), 20)
        self.assertEqual(vals.get("offset"), 40)
        self.assertEqual(vals.get("company"), "PT Juara Roti")
        self.assertIn("w.company = %(company)s", q)

    def test_inventory_info_returns_company(self):
        """inventory_info includes company field from tabWarehouse."""
        mock_row = frappe._dict(
            item_name="Roti Manis",
            item_group="Products",
            stock_uom="Pcs",
            description="Enak",
            factor=1.0,
            uom="Pcs",
            actual_qty=50.0,
            reserved_qty=5.0,
            projected_qty=45.0,
            valuation_rate=5000.0,
            stock_value=250000.0,
            company="PT Juara Roti",
        )
        with patch.object(frappe.db, "sql", return_value=[mock_row]):
            res = inv.inventory_info("ROTI-01", "Gudang A")

        self.assertIsNotNone(res)
        self.assertEqual(res["company"], "PT Juara Roti")
        self.assertEqual(res["actual_qty"], 50.0)


if __name__ == "__main__":
    unittest.main()
