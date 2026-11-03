# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto and contributors
# For license information, please see license.txt

"""Unit tests for Stock Reconciliation get_items override and compute_row endpoint.

Verifies:
1. get_items fetch round trip stability with sr_uom.compute_row
2. get_items fills batch rows
3. get_items skips serial and bundle rows
4. get_items invalid default inventory UOM falls back to stock UOM (factor 1)
5. compute_row endpoint enforces write permission before ledger access
6. compute_row endpoint throws on invalid UOM with W23 message
7. compute_row endpoint prefill and change behavior (with custom_uom returned)
8. compute_row endpoint valuation rate handling and zero rate rules
"""

import math
from pathlib import Path
import sys
from types import ModuleType
import unittest
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
sys.path.insert(0, str(_p.parents[2]))  # worktree root

import frappe_stub
frappe_stub.setup_frappe_stub()
import frappe

# Setup stock_ledger stub before importing modules
for mod_name in ["erpnext", "erpnext.stock", "erpnext.stock.stock_ledger"]:
    if mod_name not in sys.modules:
        m = ModuleType(mod_name)
        m.__path__ = []
        sys.modules[mod_name] = m
_stock_ledger = sys.modules["erpnext.stock.stock_ledger"]
if not hasattr(_stock_ledger, "get_previous_sle"):
    _stock_ledger.get_previous_sle = MagicMock(return_value=None)

# Setup native stock_reconciliation get_items stub
for mod_name in [
    "erpnext.stock.doctype",
    "erpnext.stock.doctype.stock_reconciliation",
    "erpnext.stock.doctype.stock_reconciliation.stock_reconciliation",
]:
    if mod_name not in sys.modules:
        m = ModuleType(mod_name)
        m.__path__ = []
        sys.modules[mod_name] = m
_native_sr = sys.modules["erpnext.stock.doctype.stock_reconciliation.stock_reconciliation"]
if not hasattr(_native_sr, "get_items"):
    _native_sr.get_items = MagicMock(return_value=[])

for mod_name in [
    "erpnext.stock.doctype.batch",
    "erpnext.stock.doctype.batch.batch",
]:
    if mod_name not in sys.modules:
        m = ModuleType(mod_name)
        m.__path__ = []
        sys.modules[mod_name] = m
_batch_mod = sys.modules["erpnext.stock.doctype.batch.batch"]
if not hasattr(_batch_mod, "get_batch_qty"):
    _batch_mod.get_batch_qty = MagicMock(return_value=0.0)

if not hasattr(frappe, "get_cached_value"):
    frappe.get_cached_value = MagicMock(return_value=None)


class MockDoc(frappe._dict):
    def precision(self, field):
        if field in ("qty", "valuation_rate"):
            return 6
        if field == "custom_valuation_rate_per_uom":
            return 2
        return 2


frappe.new_doc = MagicMock(side_effect=lambda dt="Stock Reconciliation Item": MockDoc())

from warehouse_app import sr_uom
from warehouse_app.warehouse_app import stock_reconciliation


def _frappe_flt(v, p=None):
    """Reproduces Frappe's legacy banker's rounding with flt error suppression."""
    if v is None or v == "":
        return 0.0
    try:
        val = float(v)
    except (ValueError, TypeError):
        return 0.0
    if p is None:
        return val
    multiplier = 10**p
    num = round(val * multiplier if p else val, 8)
    floor_num = math.floor(num)
    decimal_part = num - floor_num
    if not p and decimal_part == 0.5:
        num = floor_num if (floor_num % 2 == 0) else floor_num + 1
    else:
        if decimal_part == 0.5:
            num = floor_num + 1
        else:
            num = round(num)
    return (num / multiplier) if p else num


class TestStockReconciliationEndpoints(unittest.TestCase):
    def setUp(self):
        self.flt_sr_uom_patcher = patch("warehouse_app.sr_uom.flt", side_effect=_frappe_flt)
        self.flt_sr_patcher = patch(
            "warehouse_app.warehouse_app.stock_reconciliation.flt", side_effect=_frappe_flt
        )
        self.flt_sr_uom_patcher.start()
        self.flt_sr_patcher.start()
        self.addCleanup(self.flt_sr_uom_patcher.stop)
        self.addCleanup(self.flt_sr_patcher.stop)

        self.orig_get_doc = frappe.get_doc
        self.orig_user = getattr(frappe.session, "user", "Administrator")
        self.orig_apps = getattr(frappe, "get_installed_apps", lambda: [])

        frappe.session.user = "Administrator"
        frappe.get_installed_apps = MagicMock(return_value=["frappe", "erpnext", "warehouse_app"])

        def faithful_get_doc(doctype, name=None):
            if isinstance(doctype, dict):
                return frappe._dict(doctype)
            if doctype == "Warehouse":
                d = frappe._dict(name=name, company="Test Company", is_group=0, disabled=0)
                d.has_permission = MagicMock(return_value=True)
                return d
            if doctype == "Company":
                d = frappe._dict(name=name or "Test Company")
                d.has_permission = MagicMock(return_value=True)
                return d
            d = frappe._dict(name=name)
            d.has_permission = MagicMock(return_value=True)
            return d

        frappe.get_doc = MagicMock(side_effect=faithful_get_doc)

        def cleanup_fixtures():
            frappe.get_doc = self.orig_get_doc
            frappe.session.user = self.orig_user
            frappe.get_installed_apps = self.orig_apps

        self.addCleanup(cleanup_fixtures)

    def test_fetch_round_trip_stable(self):
        native_row = {
            "item_code": "ITEM-PACK",
            "warehouse": "Stores - C",
            "qty": 10.0,
            "valuation_rate": 1234.5678,
            "stock_uom": "Nos",
        }
        _native_sr.get_items.return_value = [native_row]

        item_doc = frappe._dict(
            name="ITEM-PACK",
            stock_uom="Nos",
            has_batch_no=0,
            has_serial_no=0,
            custom_default_inventory_unit_of_measure="Pack",
        )

        def mock_get_all(doctype, filters=None, fields=None):
            if doctype == "Item":
                return [item_doc]
            if doctype == "UOM Conversion Detail":
                return [
                    frappe._dict(
                        parent="ITEM-PACK",
                        uom="Pack",
                        conversion_factor=12.0,
                    )
                ]
            return []

        with patch("frappe.get_all", side_effect=mock_get_all):
            res = stock_reconciliation.get_items(
                warehouse="Stores - C",
                posting_date="2026-11-03",
                posting_time="10:00:00",
                company="Test Company",
            )

        self.assertEqual(len(res), 1)
        row = res[0]
        self.assertEqual(row["custom_uom"], "Pack")
        self.assertEqual(row["custom_conversion_factor"], 12.0)
        self.assertEqual(row["custom_qty_after"], 0.833)
        self.assertEqual(row["qty"], 10.0)
        self.assertEqual(row["valuation_rate"], 1234.5678)
        self.assertEqual(row["custom_valuation_rate_per_uom"], 14814.81)

        # Feeding stored values into compute_row keeps native values intact
        prec = sr_uom.precisions()
        computed = sr_uom.compute_row(
            factor=row["custom_conversion_factor"],
            ledger_qty=10.0,
            qty_after=row["custom_qty_after"],
            rate_per_uom=row["custom_valuation_rate_per_uom"],
            qty=row["qty"],
            valuation_rate=row["valuation_rate"],
            prec=prec,
        )
        self.assertEqual(computed["qty"], 10.0)
        self.assertEqual(computed["valuation_rate"], 1234.5678)

    def test_fetch_fills_batch_rows(self):
        batch_row = {
            "item_code": "ITEM-BATCH",
            "warehouse": "Stores - C",
            "batch_no": "B1",
            "qty": 24.0,
            "valuation_rate": 50.0,
            "stock_uom": "Nos",
        }
        _native_sr.get_items.return_value = [batch_row]

        item_doc = frappe._dict(
            name="ITEM-BATCH",
            stock_uom="Nos",
            has_batch_no=1,
            has_serial_no=0,
            custom_default_inventory_unit_of_measure="Box",
        )

        def mock_get_all(doctype, filters=None, fields=None):
            if doctype == "Item":
                return [item_doc]
            if doctype == "UOM Conversion Detail":
                return [
                    frappe._dict(
                        parent="ITEM-BATCH",
                        uom="Box",
                        conversion_factor=6.0,
                    )
                ]
            return []

        with patch("frappe.get_all", side_effect=mock_get_all):
            res = stock_reconciliation.get_items(
                warehouse="Stores - C",
                posting_date="2026-11-03",
                posting_time="10:00:00",
                company="Test Company",
            )

        self.assertEqual(len(res), 1)
        row = res[0]
        self.assertEqual(row["custom_uom"], "Box")
        self.assertEqual(row["custom_conversion_factor"], 6.0)
        self.assertEqual(row["custom_qty_after"], 4.0)
        self.assertEqual(row["custom_qty_before"], 4.0)
        self.assertEqual(row["qty"], 24.0)

    def test_fetch_skips_serial(self):
        serial_row_1 = {
            "item_code": "ITEM-SN1",
            "warehouse": "Stores - C",
            "serial_no": "SN001",
            "qty": 1.0,
            "stock_uom": "Nos",
        }
        serial_row_2 = {
            "item_code": "ITEM-SN2",
            "warehouse": "Stores - C",
            "current_serial_no": "SN002",
            "qty": 1.0,
            "stock_uom": "Nos",
        }
        bundle_row = {
            "item_code": "ITEM-BND",
            "warehouse": "Stores - C",
            "serial_and_batch_bundle": "SABB001",
            "qty": 1.0,
            "stock_uom": "Nos",
        }
        item_has_serial_row = {
            "item_code": "ITEM-ITEM-SN",
            "warehouse": "Stores - C",
            "qty": 1.0,
            "stock_uom": "Nos",
        }
        _native_sr.get_items.return_value = [
            serial_row_1,
            serial_row_2,
            bundle_row,
            item_has_serial_row,
        ]

        items = [
            frappe._dict(
                name="ITEM-SN1",
                stock_uom="Nos",
                has_batch_no=0,
                has_serial_no=1,
                custom_default_inventory_unit_of_measure="Box",
            ),
            frappe._dict(
                name="ITEM-SN2",
                stock_uom="Nos",
                has_batch_no=0,
                has_serial_no=0,
                custom_default_inventory_unit_of_measure="Box",
            ),
            frappe._dict(
                name="ITEM-BND",
                stock_uom="Nos",
                has_batch_no=0,
                has_serial_no=0,
                custom_default_inventory_unit_of_measure="Box",
            ),
            frappe._dict(
                name="ITEM-ITEM-SN",
                stock_uom="Nos",
                has_batch_no=0,
                has_serial_no=1,
                custom_default_inventory_unit_of_measure="Box",
            ),
        ]

        with patch("frappe.get_all", return_value=items):
            res = stock_reconciliation.get_items(
                warehouse="Stores - C",
                posting_date="2026-11-03",
                posting_time="10:00:00",
                company="Test Company",
            )

        for row in res:
            self.assertNotIn("custom_uom", row)
            self.assertNotIn("custom_conversion_factor", row)

    def test_fetch_invalid_default_uom_falls_back(self):
        row_invalid_default = {
            "item_code": "ITEM-GHOST",
            "warehouse": "Stores - C",
            "qty": 15.0,
            "valuation_rate": 20.0,
            "stock_uom": "Nos",
        }
        _native_sr.get_items.return_value = [row_invalid_default]

        item_doc = frappe._dict(
            name="ITEM-GHOST",
            stock_uom="Nos",
            has_batch_no=0,
            has_serial_no=0,
            custom_default_inventory_unit_of_measure="GhostUOM",
        )

        def mock_get_all(doctype, filters=None, fields=None):
            if doctype == "Item":
                return [item_doc]
            if doctype == "UOM Conversion Detail":
                # GhostUOM not present in UOM Conversion Detail
                return []
            return []

        with patch("frappe.get_all", side_effect=mock_get_all):
            res = stock_reconciliation.get_items(
                warehouse="Stores - C",
                posting_date="2026-11-03",
                posting_time="10:00:00",
                company="Test Company",
            )

        self.assertEqual(len(res), 1)
        row = res[0]
        self.assertEqual(row["custom_uom"], "Nos")
        self.assertEqual(row["custom_conversion_factor"], 1.0)
        self.assertEqual(row["custom_qty_after"], 15.0)
        self.assertEqual(row["qty"], 15.0)

    def test_endpoint_permission(self):
        with patch(
            "frappe.has_permission", side_effect=frappe.PermissionError("Not permitted")
        ), patch("warehouse_app.sr_uom.ledger_qty") as mock_ledger:
            with self.assertRaises(frappe.PermissionError):
                stock_reconciliation.compute_row(
                    item_code="ITEM-1",
                    warehouse="Stores - C",
                    posting_date="2026-11-03",
                    posting_time="10:00:00",
                    uom="Pack",
                )
            mock_ledger.assert_not_called()

    def test_endpoint_invalid_uom_throws(self):
        with patch("frappe.has_permission", return_value=True), patch(
            "frappe.get_cached_value", return_value="Nos"
        ), patch("frappe.get_all", return_value=[]):
            with self.assertRaises(frappe.ValidationError) as ctx:
                stock_reconciliation.compute_row(
                    item_code="ITEM-1",
                    warehouse="Stores - C",
                    posting_date="2026-11-03",
                    posting_time="10:00:00",
                    uom="BadUOM",
                )
            self.assertIn("BadUOM", str(ctx.exception))
            self.assertIn("ITEM-1", str(ctx.exception))

    def test_endpoint_prefill_and_change(self):
        def mock_get_all(doctype, filters=None, fields=None):
            if doctype == "UOM Conversion Detail":
                return [
                    frappe._dict(
                        parent="ITEM-1",
                        uom="Pack",
                        conversion_factor=12.0,
                    )
                ]
            return []

        _stock_ledger.get_previous_sle.reset_mock()
        _stock_ledger.get_previous_sle.return_value = {"qty_after_transaction": 84.0}

        with patch("frappe.has_permission", return_value=True), patch(
            "frappe.get_cached_value", return_value="Nos"
        ), patch("frappe.get_all", side_effect=mock_get_all):
            # Prefill: qty_after is None
            res1 = stock_reconciliation.compute_row(
                item_code="ITEM-1",
                warehouse="Stores - C",
                posting_date="2026-11-03",
                posting_time="10:00:00",
                uom="Pack",
                qty_after=None,
            )
            self.assertEqual(res1["custom_uom"], "Pack")
            self.assertEqual(res1["custom_qty_before"], 7.0)
            self.assertEqual(res1["custom_qty_after"], 7.0)
            self.assertEqual(res1["qty"], 84.0)
            self.assertEqual(res1["custom_qty_difference_per_uom"], 0.0)

            # Change: qty_after is passed as string "2.5"
            res2 = stock_reconciliation.compute_row(
                item_code="ITEM-1",
                warehouse="Stores - C",
                posting_date="2026-11-03",
                posting_time="10:00:00",
                uom="Pack",
                qty_after="2.5",
            )
            self.assertEqual(res2["custom_uom"], "Pack")
            self.assertEqual(res2["custom_qty_before"], 7.0)
            self.assertEqual(res2["custom_qty_after"], 2.5)
            self.assertEqual(res2["qty"], 30.0)
            self.assertEqual(res2["custom_qty_difference_per_uom"], -4.5)

    def test_endpoint_rate_handling(self):
        def mock_get_all(doctype, filters=None, fields=None):
            if doctype == "UOM Conversion Detail":
                return [
                    frappe._dict(
                        parent="ITEM-1",
                        uom="Pack",
                        conversion_factor=12.0,
                    )
                ]
            return []

        _stock_ledger.get_previous_sle.return_value = {"qty_after_transaction": 10.0}

        with patch("frappe.has_permission", return_value=True), patch(
            "frappe.get_cached_value", return_value="Nos"
        ), patch("frappe.get_all", side_effect=mock_get_all):
            # Explicit rate
            res = stock_reconciliation.compute_row(
                item_code="ITEM-1",
                warehouse="Stores - C",
                posting_date="2026-11-03",
                posting_time="10:00:00",
                uom="Pack",
                qty_after=1.0,
                rate_per_uom=1200.0,
            )
            self.assertEqual(res["valuation_rate"], 100.0)
            self.assertEqual(res["custom_valuation_rate_per_uom"], 1200.0)

            # Silent zero without allow_zero_valuation_rate
            res = stock_reconciliation.compute_row(
                item_code="ITEM-1",
                warehouse="Stores - C",
                posting_date="2026-11-03",
                posting_time="10:00:00",
                uom="Pack",
                qty_after=1.0,
                rate_per_uom=0.0,
                allow_zero_valuation_rate=0,
                valuation_rate=100.0,
            )
            self.assertEqual(res["valuation_rate"], 100.0)
            self.assertEqual(res["custom_valuation_rate_per_uom"], 1200.0)

            # Zero rate with allow_zero_valuation_rate=1
            res = stock_reconciliation.compute_row(
                item_code="ITEM-1",
                warehouse="Stores - C",
                posting_date="2026-11-03",
                posting_time="10:00:00",
                uom="Pack",
                qty_after=1.0,
                rate_per_uom=0.0,
                allow_zero_valuation_rate=1,
                valuation_rate=100.0,
            )
            self.assertEqual(res["valuation_rate"], 0.0)
            self.assertEqual(res["custom_valuation_rate_per_uom"], 0.0)

    def test_endpoint_missing_context_throws(self):
        _stock_ledger.get_previous_sle.reset_mock()
        with patch("frappe.has_permission", return_value=True), patch(
            "frappe.get_cached_value", return_value="Nos"
        ):
            # Missing item_code
            with self.assertRaises(frappe.ValidationError) as ctx:
                stock_reconciliation.compute_row(
                    item_code="",
                    warehouse="Stores - C",
                    posting_date="2026-11-03",
                    posting_time="10:00:00",
                    uom="Nos",
                )
            self.assertIn("Item Code", str(ctx.exception))
            _stock_ledger.get_previous_sle.assert_not_called()

            # Missing warehouse is denied by security guard before ledger read
            with self.assertRaises(frappe.PermissionError) as ctx:
                stock_reconciliation.compute_row(
                    item_code="ITEM-1",
                    warehouse="",
                    posting_date="2026-11-03",
                    posting_time="10:00:00",
                    uom="Nos",
                )
            self.assertIn("warehouse", str(ctx.exception).lower())
            _stock_ledger.get_previous_sle.assert_not_called()

            # Missing posting_date (in old code this proceeded to ledger read!)
            with self.assertRaises(frappe.ValidationError) as ctx:
                stock_reconciliation.compute_row(
                    item_code="ITEM-1",
                    warehouse="Stores - C",
                    posting_date="",
                    posting_time="10:00:00",
                    uom="Nos",
                )
            self.assertIn("Posting Date", str(ctx.exception))
            _stock_ledger.get_previous_sle.assert_not_called()

            # Missing uom (in old code item_code=None, uom=None resolved as factor 1)
            with self.assertRaises(frappe.ValidationError) as ctx:
                stock_reconciliation.compute_row(
                    item_code="ITEM-1",
                    warehouse="Stores - C",
                    posting_date="2026-11-03",
                    posting_time="10:00:00",
                    uom="",
                )
            self.assertIn("UOM", str(ctx.exception))
            _stock_ledger.get_previous_sle.assert_not_called()

    def test_endpoint_posting_time_defaults(self):
        def mock_get_all(doctype, filters=None, fields=None):
            if doctype == "UOM Conversion Detail":
                return [
                    frappe._dict(parent="ITEM-1", uom="Pack", conversion_factor=12.0)
                ]
            return []

        _stock_ledger.get_previous_sle.reset_mock()
        _stock_ledger.get_previous_sle.return_value = {"qty_after_transaction": 24.0}

        with patch("frappe.has_permission", return_value=True), patch(
            "frappe.get_cached_value", return_value="Nos"
        ), patch("frappe.get_all", side_effect=mock_get_all):
            res = stock_reconciliation.compute_row(
                item_code="ITEM-1",
                warehouse="Stores - C",
                posting_date="2026-11-03",
                posting_time="",  # empty posting_time
                uom="Pack",
            )
            self.assertEqual(res["qty"], 24.0)
            _stock_ledger.get_previous_sle.assert_called_once()
            call_args = _stock_ledger.get_previous_sle.call_args[0][0]
            self.assertTrue(bool(call_args.get("posting_time")))

    def test_endpoint_string_null_undefined_treated_as_empty(self):
        def mock_get_all(doctype, filters=None, fields=None):
            if doctype == "UOM Conversion Detail":
                return [
                    frappe._dict(parent="ITEM-1", uom="Pack", conversion_factor=12.0)
                ]
            return []

        _stock_ledger.get_previous_sle.reset_mock()
        _stock_ledger.get_previous_sle.return_value = {"qty_after_transaction": 84.0}

        with patch("frappe.has_permission", return_value=True), patch(
            "frappe.get_cached_value", return_value="Nos"
        ), patch("frappe.get_all", side_effect=mock_get_all):
            # "null" for qty_after must not become 0.0; it must prefill 84.0 from ledger
            res_null = stock_reconciliation.compute_row(
                item_code="ITEM-1",
                warehouse="Stores - C",
                posting_date="2026-11-03",
                posting_time="10:00:00",
                uom="Pack",
                qty_after="null",
                rate_per_uom="null",
                qty="null",
                valuation_rate="null",
            )
            self.assertEqual(res_null["qty"], 84.0)
            self.assertEqual(res_null["custom_qty_after"], 7.0)

            # "undefined" for qty_after must also prefill
            res_undef = stock_reconciliation.compute_row(
                item_code="ITEM-1",
                warehouse="Stores - C",
                posting_date="2026-11-03",
                posting_time="10:00:00",
                uom="Pack",
                qty_after="undefined",
                rate_per_uom="undefined",
            )
            self.assertEqual(res_undef["qty"], 84.0)
            self.assertEqual(res_undef["custom_qty_after"], 7.0)

    def test_endpoint_rejects_non_numeric_strings(self):
        _stock_ledger.get_previous_sle.reset_mock()
        with patch("frappe.has_permission", return_value=True), patch(
            "frappe.get_cached_value", return_value="Nos"
        ), patch("frappe.get_all", return_value=[
            frappe._dict(parent="ITEM-1", uom="Pack", conversion_factor=12.0)
        ]):
            # Under old code, flt("abc") returned 0.0 and silently set qty=0
            # Under new code, non-numeric strings throw ValidationError and ledger is not read
            for arg_name, bad_val in [
                ("qty_after", "not_a_number"),
                ("rate_per_uom", "xyz"),
                ("qty", "foo"),
                ("valuation_rate", "bar"),
            ]:
                with self.subTest(arg=arg_name):
                    _stock_ledger.get_previous_sle.reset_mock()
                    kwargs = {
                        "item_code": "ITEM-1",
                        "warehouse": "Stores - C",
                        "posting_date": "2026-11-03",
                        "posting_time": "10:00:00",
                        "uom": "Pack",
                        arg_name: bad_val,
                    }
                    with self.assertRaises(frappe.ValidationError):
                        stock_reconciliation.compute_row(**kwargs)
                    _stock_ledger.get_previous_sle.assert_not_called()

    def test_endpoint_rejects_nonfinite_numbers(self):
        _stock_ledger.get_previous_sle.reset_mock()
        with patch("frappe.has_permission", return_value=True), patch(
            "frappe.get_cached_value", return_value="Nos"
        ), patch("frappe.get_all", return_value=[
            frappe._dict(parent="ITEM-1", uom="Pack", conversion_factor=12.0)
        ]):
            nonfinite_values = [
                "nan",
                "inf",
                "-inf",
                "Infinity",
                "-Infinity",
                float("nan"),
                float("inf"),
                float("-inf"),
            ]
            for arg_name in ["qty_after", "rate_per_uom", "qty", "valuation_rate"]:
                for bad_val in nonfinite_values:
                    with self.subTest(arg=arg_name, val=repr(bad_val)):
                        _stock_ledger.get_previous_sle.reset_mock()
                        kwargs = {
                            "item_code": "ITEM-1",
                            "warehouse": "Stores - C",
                            "posting_date": "2026-11-03",
                            "posting_time": "10:00:00",
                            "uom": "Pack",
                            arg_name: bad_val,
                        }
                        with self.assertRaises(frappe.ValidationError):
                            stock_reconciliation.compute_row(**kwargs)
                        _stock_ledger.get_previous_sle.assert_not_called()

    def test_endpoint_batch_qty(self):
        """F1: compute_row accepts batch_no, calls get_batch_qty, and computes batch-specific balance."""
        def mock_get_all(doctype, filters=None, fields=None):
            if doctype == "UOM Conversion Detail":
                return [
                    frappe._dict(parent="ITEM-BATCH", uom="Pack", conversion_factor=12.0)
                ]
            return []

        _batch_mod.get_batch_qty.reset_mock()
        _batch_mod.get_batch_qty.return_value = 24.0

        with patch("frappe.has_permission", return_value=True), patch(
            "frappe.get_cached_value", return_value="Nos"
        ), patch("frappe.get_all", side_effect=mock_get_all):
            res = stock_reconciliation.compute_row(
                item_code="ITEM-BATCH",
                warehouse="Stores - C",
                posting_date="2026-11-03",
                posting_time="10:00:00",
                uom="Pack",
                batch_no="B1",
            )
            self.assertEqual(res["custom_qty_before"], 2.0)
            self.assertEqual(res["custom_qty_after"], 2.0)
            self.assertEqual(res["qty"], 24.0)
            _batch_mod.get_batch_qty.assert_called_once()
            call_kwargs = _batch_mod.get_batch_qty.call_args[1]
            self.assertEqual(call_kwargs.get("batch_no"), "B1")
            self.assertEqual(call_kwargs.get("item_code"), "ITEM-BATCH")
            self.assertEqual(call_kwargs.get("warehouse"), "Stores - C")
            self.assertEqual(call_kwargs.get("posting_date"), "2026-11-03")
            self.assertEqual(call_kwargs.get("posting_time"), "10:00:00")


if __name__ == "__main__":
    unittest.main()
