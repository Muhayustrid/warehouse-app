# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto and contributors
# For license information, please see license.txt

"""Unit tests for Stock Count import per-UOM conversion using sr_uom.

Verifies:
1. test_import_row_matches_class_math: counted 1 Pack (12) -> row qty == 12;
   feeding the row back through sr_uom.compute_row with stored qty/valuation_rate
   changes nothing.
2. test_import_explicit_rate: rate 1200 -> valuation_rate == 100,
   custom_valuation_rate_per_uom == 1200.
3. test_import_no_rate_uses_system_rate: rate blank -> valuation_rate == 100.
4. test_import_invalid_uom_error_message: unchanged message text
   "Row {0}: UOM {1} is not valid for Item {2}...".
5. test_import_matched_row_stripped: counted 0.833 Pack vs ledger 10 ->
   matched == 1, no rows.
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

# Setup required frappe.utils helpers if missing from stub
_fu = sys.modules.get("frappe.utils")
if _fu:
    if not hasattr(_fu, "cstr"):
        _fu.cstr = lambda v: "" if v is None else str(v)
    if not hasattr(_fu, "escape_html"):
        _fu.escape_html = lambda v: str(v)
    if not hasattr(_fu, "nowdate"):
        _fu.nowdate = lambda: "2026-11-03"
    if not hasattr(_fu, "nowtime"):
        _fu.nowtime = lambda: "10:00:00"
    frappe.utils = _fu

# Setup stock_ledger stub before importing modules
for mod_name in ["erpnext", "erpnext.stock", "erpnext.stock.stock_ledger"]:
    if mod_name not in sys.modules:
        m = ModuleType(mod_name)
        m.__path__ = []
        sys.modules[mod_name] = m
_stock_ledger = sys.modules["erpnext.stock.stock_ledger"]
if not hasattr(_stock_ledger, "get_previous_sle"):
    _stock_ledger.get_previous_sle = MagicMock(return_value=None)

from warehouse_app.sr_uom import (
    SR_AFTER_FIELD,
    SR_BEFORE_FIELD,
    SR_DIFF_FIELD,
    SR_FACTOR_FIELD,
    SR_RATE_FIELD,
    SR_UOM_FIELD,
    compute_row,
    precisions,
)
from warehouse_app.warehouse_app.sr_import import validate_count_rows

P = {"qty": 6, "valuation_rate": 6, "rate_per_uom": 2}


def _frappe_flt(v, p=None):
    """Reproduces Frappe's legacy banker's rounding."""
    if v is None or v == "":
        return 0.0
    val = float(v)
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


class MockDoc(frappe._dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get(self, k, default=None):
        return super().get(k, default)

    def set(self, k, v):
        self[k] = v

    def precision(self, field):
        if field in ("qty", "valuation_rate"):
            return 6
        if field == SR_RATE_FIELD:
            return 2
        return 2


class TestSrImportUom(unittest.TestCase):
    def setUp(self):
        self.flt_sr_uom_patcher = patch("warehouse_app.sr_uom.flt", side_effect=_frappe_flt)
        self.flt_sr_uom_patcher.start()
        self.addCleanup(self.flt_sr_uom_patcher.stop)

        self.flt_sr_import_patcher = patch(
            "warehouse_app.warehouse_app.sr_import.flt", side_effect=_frappe_flt
        )
        self.flt_sr_import_patcher.start()
        self.addCleanup(self.flt_sr_import_patcher.stop)

        self.mock_new_doc = MockDoc()
        frappe.new_doc.return_value = self.mock_new_doc
        frappe.db.get_single_value.return_value = 0

        _stock_ledger.get_previous_sle.reset_mock()
        _stock_ledger.get_previous_sle.return_value = {
            "qty_after_transaction": 10,
            "valuation_rate": 100,
        }

    def _mock_get_all(self, doctype, *args, **kwargs):
        if doctype == "Item":
            return [
                MockDoc(
                    name="ITEM-1",
                    item_name="Item 1",
                    stock_uom="Nos",
                    disabled=0,
                    has_batch_no=0,
                    has_serial_no=0,
                    custom_inventory_uom="Pack",
                )
            ]
        elif doctype == "Warehouse":
            return [
                MockDoc(
                    name="WH-1",
                    company="Test Company",
                    is_group=0,
                    disabled=0,
                )
            ]
        elif doctype == "UOM Conversion Detail":
            return [
                MockDoc(
                    parent="ITEM-1",
                    uom="Pack",
                    conversion_factor=12.0,
                )
            ]
        return []

    def test_import_row_matches_class_math(self):
        """Counted 1 Pack (12) -> row qty == 12; feeding row back through sr_uom.compute_row changes nothing."""
        parsed = {
            "rows": [
                {
                    "row_no": 2,
                    "item_code": "ITEM-1",
                    "warehouse": "WH-1",
                    "uom": "Pack",
                    "counted": 1.0,
                    "rate": None,
                }
            ],
            "skipped": 0,
        }

        with patch("frappe.get_all", side_effect=self._mock_get_all):
            res = validate_count_rows(parsed, company="Test Company")

        self.assertEqual(res["added"], 1)
        self.assertEqual(len(res["rows"]), 1)
        row = res["rows"][0]

        self.assertEqual(row["qty"], 12.0)
        self.assertEqual(row["valuation_rate"], 100.0)
        self.assertEqual(row[SR_FACTOR_FIELD], 12.0)
        self.assertEqual(row[SR_BEFORE_FIELD], 0.833)
        self.assertEqual(row[SR_AFTER_FIELD], 1.0)
        self.assertEqual(row[SR_DIFF_FIELD], 0.167)
        self.assertEqual(row.get(SR_RATE_FIELD), 1200.0)

        # Feeding row back through compute_row with stored qty/valuation_rate
        recomputed = compute_row(
            factor=row[SR_FACTOR_FIELD],
            ledger_qty=10,
            qty_after=row[SR_AFTER_FIELD],
            rate_per_uom=row.get(SR_RATE_FIELD),
            qty=row["qty"],
            valuation_rate=row["valuation_rate"],
            prec=P,
        )

        self.assertEqual(recomputed["qty"], row["qty"])
        self.assertEqual(recomputed["valuation_rate"], row["valuation_rate"])
        self.assertEqual(recomputed[SR_FACTOR_FIELD], row[SR_FACTOR_FIELD])
        self.assertEqual(recomputed[SR_BEFORE_FIELD], row[SR_BEFORE_FIELD])
        self.assertEqual(recomputed[SR_AFTER_FIELD], row[SR_AFTER_FIELD])
        self.assertEqual(recomputed[SR_DIFF_FIELD], row[SR_DIFF_FIELD])
        self.assertEqual(recomputed[SR_RATE_FIELD], row.get(SR_RATE_FIELD))

    def test_import_explicit_rate(self):
        """Rate 1200 -> valuation_rate == 100, custom_valuation_rate_per_uom == 1200."""
        parsed = {
            "rows": [
                {
                    "row_no": 2,
                    "item_code": "ITEM-1",
                    "warehouse": "WH-1",
                    "uom": "Pack",
                    "counted": 1.0,
                    "rate": 1200.0,
                }
            ],
            "skipped": 0,
        }

        with patch("frappe.get_all", side_effect=self._mock_get_all):
            res = validate_count_rows(parsed, company="Test Company")

        self.assertEqual(res["added"], 1)
        row = res["rows"][0]
        self.assertEqual(row["valuation_rate"], 100.0)
        self.assertEqual(row[SR_RATE_FIELD], 1200.0)

    def test_import_no_rate_uses_system_rate(self):
        """Rate blank -> valuation_rate == 100."""
        parsed = {
            "rows": [
                {
                    "row_no": 2,
                    "item_code": "ITEM-1",
                    "warehouse": "WH-1",
                    "uom": "Pack",
                    "counted": 1.0,
                    "rate": None,
                }
            ],
            "skipped": 0,
        }

        with patch("frappe.get_all", side_effect=self._mock_get_all):
            res = validate_count_rows(parsed, company="Test Company")

        self.assertEqual(res["added"], 1)
        row = res["rows"][0]
        self.assertEqual(row["valuation_rate"], 100.0)

    def test_import_invalid_uom_error_message(self):
        """Unchanged message text 'Row {0}: UOM {1} is not valid for Item {2}...'."""
        parsed = {
            "rows": [
                {
                    "row_no": 2,
                    "item_code": "ITEM-1",
                    "warehouse": "WH-1",
                    "uom": "InvalidUOM",
                    "counted": 1.0,
                    "rate": None,
                }
            ],
            "skipped": 0,
        }

        with patch("frappe.get_all", side_effect=self._mock_get_all):
            with self.assertRaises(frappe.ValidationError) as cm:
                validate_count_rows(parsed, company="Test Company")

        err = str(cm.exception)
        self.assertIn("Row 2: UOM InvalidUOM is not valid for Item ITEM-1", err)
        self.assertIn("Use the Stock UOM or add it to the item's UOM conversion table", err)

    def test_import_matched_row_stripped(self):
        """Counted 0.833 Pack vs ledger 10 -> matched == 1, no rows."""
        parsed = {
            "rows": [
                {
                    "row_no": 2,
                    "item_code": "ITEM-1",
                    "warehouse": "WH-1",
                    "uom": "Pack",
                    "counted": 0.833,
                    "rate": None,
                }
            ],
            "skipped": 0,
        }

        with patch("frappe.get_all", side_effect=self._mock_get_all):
            res = validate_count_rows(parsed, company="Test Company")

        self.assertEqual(res["matched"], 1)
        self.assertEqual(res["added"], 0)
        self.assertEqual(res["rows"], [])
        self.assertIn("All counts match", res.get("message", ""))

    def test_import_zero_stock_warning_and_none_rate(self):
        """Zero stock item without explicit rate gets warning and None valuation_rate."""
        _stock_ledger.get_previous_sle.return_value = {
            "qty_after_transaction": 0,
            "valuation_rate": 0,
        }
        parsed = {
            "rows": [
                {
                    "row_no": 2,
                    "item_code": "ITEM-1",
                    "warehouse": "WH-1",
                    "uom": "Pack",
                    "counted": 1.0,
                    "rate": None,
                }
            ],
            "skipped": 0,
        }

        with patch("frappe.get_all", side_effect=self._mock_get_all):
            res = validate_count_rows(parsed, company="Test Company")

        self.assertEqual(res["added"], 1)
        row = res["rows"][0]
        self.assertIsNone(row["valuation_rate"])
        self.assertNotIn(SR_RATE_FIELD, row)
        self.assertTrue(any("zero stock" in w for w in res["warnings"]))

    def test_import_explicit_rate_only_preserves_ledger_qty(self):
        """F4: Explicit-rate-only row with ledger 10, factor 12, counted 0.833, rate 2400 preserves qty 10.0."""
        parsed = {
            "rows": [
                {
                    "row_no": 2,
                    "item_code": "ITEM-1",
                    "warehouse": "WH-1",
                    "uom": "Pack",
                    "counted": 0.833,
                    "rate": 2400.0,
                }
            ],
            "skipped": 0,
        }
        with patch("frappe.get_all", side_effect=self._mock_get_all):
            res = validate_count_rows(parsed, company="Test Company")

        self.assertEqual(res["added"], 1)
        row = res["rows"][0]
        self.assertEqual(row["qty"], 10.0)
        self.assertEqual(row["valuation_rate"], 200.0)
        self.assertEqual(row[SR_RATE_FIELD], 2400.0)

    def test_import_matched_row_boundary_uses_rounded_before(self):
        """F2 boundary regression: ledger 10.0008 / 12 -> before 0.833 (not 0.8334).
        Counted 0.8336 is >= 0.0005 from 0.833, so it is kept as a real correction."""
        _stock_ledger.get_previous_sle.return_value = {
            "qty_after_transaction": 10.0008,
            "valuation_rate": 100,
        }
        parsed = {
            "rows": [
                {
                    "row_no": 2,
                    "item_code": "ITEM-1",
                    "warehouse": "WH-1",
                    "uom": "Pack",
                    "counted": 0.8336,
                    "rate": None,
                }
            ],
            "skipped": 0,
        }

        with patch("frappe.get_all", side_effect=self._mock_get_all):
            res = validate_count_rows(parsed, company="Test Company")

        self.assertEqual(res["matched"], 0)
        self.assertEqual(res["added"], 1)
        row = res["rows"][0]
        self.assertEqual(row[SR_BEFORE_FIELD], 0.833)
        self.assertEqual(row[SR_AFTER_FIELD], 0.8336)
        self.assertEqual(row[SR_DIFF_FIELD], 0.001)
        self.assertEqual(row["qty"], 10.0032)

    def test_import_rate_drift_1200_004999_round_trip(self):
        """F1 regression: feeding imported row with rate 1200.004999 back through
        sr_uom.compute_row leaves qty and valuation_rate unchanged.

        Note: May fail if F1 fix in sr_uom.compute_row has not yet landed in parallel work.
        """
        _stock_ledger.get_previous_sle.return_value = {
            "qty_after_transaction": 10,
            "valuation_rate": 100,
        }
        parsed = {
            "rows": [
                {
                    "row_no": 2,
                    "item_code": "ITEM-1",
                    "warehouse": "WH-1",
                    "uom": "Pack",
                    "counted": 1.0,
                    "rate": 1200.004999,
                }
            ],
            "skipped": 0,
        }

        with patch("frappe.get_all", side_effect=self._mock_get_all):
            res = validate_count_rows(parsed, company="Test Company")

        self.assertEqual(res["added"], 1)
        row = res["rows"][0]

        recomputed = compute_row(
            factor=row[SR_FACTOR_FIELD],
            ledger_qty=10,
            qty_after=row[SR_AFTER_FIELD],
            rate_per_uom=row.get(SR_RATE_FIELD),
            qty=row["qty"],
            valuation_rate=row["valuation_rate"],
            prec=P,
        )

        self.assertEqual(recomputed["qty"], row["qty"])
        self.assertEqual(recomputed["valuation_rate"], row["valuation_rate"])


if __name__ == "__main__":
    unittest.main()
