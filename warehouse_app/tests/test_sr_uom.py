# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto and contributors
# For license information, please see license.txt

"""Unit tests for warehouse_app.sr_uom module.

Verifies:
1. compute_row consistency rules (Review Focus 2 & 5)
2. is_convertible filtering logic
3. resolve_factors batch resolution and edge cases
4. apply_to_doc atomicity on invalid UOM (Review Focus 3)
5. apply_to_doc uses doc posting date & time
"""

import sys
import unittest
import math
from pathlib import Path
from types import ModuleType
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

# Setup stock_ledger and batch stubs before importing modules that might use it
for mod_name in [
    "erpnext",
    "erpnext.stock",
    "erpnext.stock.stock_ledger",
    "erpnext.stock.doctype",
    "erpnext.stock.doctype.batch",
    "erpnext.stock.doctype.batch.batch",
]:
    if mod_name not in sys.modules:
        m = ModuleType(mod_name)
        m.__path__ = []
        sys.modules[mod_name] = m
_stock_ledger = sys.modules["erpnext.stock.stock_ledger"]
if not hasattr(_stock_ledger, "get_previous_sle"):
    _stock_ledger.get_previous_sle = MagicMock(return_value=None)
_batch_mod = sys.modules["erpnext.stock.doctype.batch.batch"]
if not hasattr(_batch_mod, "get_batch_qty"):
    _batch_mod.get_batch_qty = MagicMock(return_value=0.0)

if not hasattr(frappe, "get_cached_value"):
    frappe.get_cached_value = MagicMock(return_value=None)

from warehouse_app.sr_uom import (
    SR_AFTER_FIELD,
    SR_BEFORE_FIELD,
    SR_CONFIRMATION_FIELD,
    SR_DIFF_FIELD,
    SR_FACTOR_FIELD,
    SR_RATE_FIELD,
    SR_UOM_FIELD,
    apply_to_doc,
    compute_row,
    confirm_count_rows,
    count_confirmation,
    is_convertible,
    ledger_qty,
    precisions,
    resolve_factors,
    validate_representable_qty,
)

P = {"qty": 6, "valuation_rate": 6, "rate_per_uom": 2}


def _frappe_flt(v, p=None):
    """Reproduces Frappe's legacy banker's rounding (frappe/utils/data.py:1260-1276)."""
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
        if field in (SR_BEFORE_FIELD, SR_AFTER_FIELD):
            return 3
        return 2


class TestSrUom(unittest.TestCase):
    def setUp(self):
        self.flt_patcher = patch("warehouse_app.sr_uom.flt", side_effect=_frappe_flt)
        self.flt_patcher.start()
        self.addCleanup(self.flt_patcher.stop)

    def test_counted_1056_factor_6_stale_6306_yields_6336(self):
        res = compute_row(
            factor=6,
            ledger_qty=6306,
            qty_after=1056,
            qty=6306,
            prec=P,
        )
        self.assertEqual(res["custom_qty_after"], 1056)
        self.assertEqual(res["qty"], 6336.0)

    def test_counted_zero_yields_zero(self):
        res = compute_row(
            factor=6,
            ledger_qty=6306,
            qty_after=0,
            qty=6306,
            prec=P,
        )
        self.assertEqual(res["custom_qty_after"], 0)
        self.assertEqual(res["qty"], 0.0)

    def test_one_way_derived_native_qty_overrides_stale_qty(self):
        # Revision 3.1: No rounded-equality preservation of stale native qty
        res = compute_row(factor=12, ledger_qty=10, qty_after=0.833, qty=10, prec=P)
        self.assertEqual(res["qty"], 9.996)
        self.assertEqual(res["custom_qty_after"], 0.833)

    def test_changed_after_recomputes_qty(self):
        res = compute_row(factor=12, ledger_qty=10, qty_after=1, qty=10, prec=P)
        self.assertEqual(res["qty"], 12)

    def test_empty_qty_is_computed(self):
        res = compute_row(factor=12, ledger_qty=10, qty_after=0.833, qty=None, prec=P)
        self.assertEqual(res["qty"], 9.996)

    def test_empty_after_does_not_prefill_from_ledger(self):
        # Revision 3.1: empty After is not prefilled from balance
        res = compute_row(factor=12, ledger_qty=10, qty_after=None, qty=None, prec=P)
        self.assertIsNone(res["custom_qty_after"])
        self.assertEqual(res["qty"], 10)
        self.assertIsNone(res["custom_qty_difference_per_uom"])

    def test_rate_round_trip_kept(self):
        res = compute_row(
            factor=12,
            ledger_qty=10,
            qty_after=1,
            valuation_rate=1234.5678,
            rate_per_uom=14814.81,
            prec=P,
        )
        self.assertEqual(res["valuation_rate"], 1234.5678)

    def test_rate_changed_recomputes(self):
        res = compute_row(
            factor=12,
            ledger_qty=10,
            qty_after=1,
            valuation_rate=1234.5678,
            rate_per_uom=1200,
            prec=P,
        )
        self.assertEqual(res["valuation_rate"], 100)

    def test_silent_zero_rate_is_empty(self):
        res = compute_row(
            factor=12,
            ledger_qty=10,
            qty_after=1,
            rate_per_uom=0.0,
            allow_zero_valuation_rate=False,
            valuation_rate=100,
            prec=P,
        )
        self.assertEqual(res["valuation_rate"], 100)
        self.assertEqual(res["custom_valuation_rate_per_uom"], 1200)

    def test_explicit_zero_rate_allowed(self):
        res = compute_row(
            factor=12,
            ledger_qty=10,
            qty_after=1,
            rate_per_uom=0.0,
            allow_zero_valuation_rate=True,
            valuation_rate=100,
            prec=P,
        )
        self.assertEqual(res["valuation_rate"], 0)

    def test_inconsistent_rate_rounded_first_fixed_point(self):
        # When rate_per_uom is set and inconsistent, rate_per_uom must be rounded
        # to its precision (2) first, and valuation_rate derived from that rounded value.
        # Inputs: factor=12, rate_per_uom=1200.004999, prec={"qty": 6, "valuation_rate": 6, "rate_per_uom": 2}
        out1 = compute_row(
            factor=12,
            ledger_qty=10,
            qty_after=1,
            rate_per_uom=1200.004999,
            prec=P,
        )
        self.assertEqual(out1["custom_valuation_rate_per_uom"], 1200.00)
        self.assertEqual(out1["valuation_rate"], 100.0)

        # Feeding out1 back into compute_row (as save does) must produce the exact same values
        out2 = compute_row(
            factor=12,
            ledger_qty=10,
            qty_after=out1["custom_qty_after"],
            rate_per_uom=out1["custom_valuation_rate_per_uom"],
            qty=out1["qty"],
            valuation_rate=out1["valuation_rate"],
            prec=P,
        )
        self.assertEqual(out2["valuation_rate"], 100.0)
        self.assertEqual(out2["custom_valuation_rate_per_uom"], 1200.00)
        self.assertEqual(out1, out2)

    def test_compute_row_idempotence(self):
        combos = [
            (12, 10, 1.0, 1200.004999, None, None, False),
            (12, 84, 2.5, 14814.81, 30, 1234.5678, False),
            (0.5, 5, 10.0, 50.0049, None, None, False),
            (1, 10, 10.0, 100.555, None, None, False),
            (12, 10, None, None, None, 100, False),
        ]
        for factor, lq, qa, rpu, q, vr, az in combos:
            with self.subTest(factor=factor, rate=rpu):
                o1 = compute_row(
                    factor=factor,
                    ledger_qty=lq,
                    qty_after=qa,
                    rate_per_uom=rpu,
                    qty=q,
                    valuation_rate=vr,
                    allow_zero_valuation_rate=az,
                    prec=P,
                )
                o2 = compute_row(
                    factor=factor,
                    ledger_qty=lq,
                    qty_after=o1["custom_qty_after"],
                    rate_per_uom=o1["custom_valuation_rate_per_uom"],
                    qty=o1["qty"],
                    valuation_rate=o1["valuation_rate"],
                    allow_zero_valuation_rate=az,
                    prec=P,
                )
                self.assertEqual(o1, o2)

    def test_before_and_diff(self):
        res = compute_row(factor=12, ledger_qty=84, qty_after=2.5, prec=P)
        self.assertEqual(res["custom_qty_before"], 7)
        self.assertEqual(res["custom_qty_difference_per_uom"], -4.5)
        self.assertEqual(res["qty"], 30)

    def test_is_convertible(self):
        base_row = {
            "item_code": "ITEM-1",
            "custom_uom": "Box",
            "custom_qty_after": 5.0,
        }
        self.assertTrue(is_convertible(base_row))

        # serial_no -> False
        self.assertFalse(is_convertible(dict(base_row, serial_no="SN-001")))

        # serial_and_batch_bundle -> False
        self.assertFalse(is_convertible(dict(base_row, serial_and_batch_bundle="SABB-001")))

        # batch_no only -> True
        self.assertTrue(is_convertible(dict(base_row, batch_no="BATCH-001")))

        # custom_uom empty -> False
        self.assertFalse(is_convertible(dict(base_row, custom_uom=None)))
        self.assertFalse(is_convertible(dict(base_row, custom_uom="")))

        # custom_qty_after empty -> False
        self.assertFalse(is_convertible(dict(base_row, custom_qty_after=None)))
        self.assertFalse(is_convertible(dict(base_row, custom_qty_after="")))

        # custom_qty_after = 0.0 -> True
        self.assertTrue(is_convertible(dict(base_row, custom_qty_after=0.0)))

    def test_resolve_factors(self):
        pairs = [
            ("ITEM-STOCK", "Nos", "Nos"),
            ("ITEM-HIT", "Box", "Nos"),
            ("ITEM-MISSING", "Carton", "Nos"),
            ("ITEM-ZERO", "Pack", "Nos"),
        ]

        with patch("frappe.get_all") as mock_get_all:
            mock_get_all.return_value = [
                {"parent": "ITEM-HIT", "uom": "Box", "conversion_factor": 10.0},
                {"parent": "ITEM-ZERO", "uom": "Pack", "conversion_factor": 0.0},
            ]
            factors = resolve_factors(pairs)
            self.assertEqual(factors[("ITEM-STOCK", "Nos")], 1.0)
            self.assertEqual(factors[("ITEM-HIT", "Box")], 10.0)
            self.assertIsNone(factors[("ITEM-MISSING", "Carton")])
            self.assertIsNone(factors[("ITEM-ZERO", "Pack")])
            mock_get_all.assert_called_once()

    def test_apply_to_doc_invalid_uom_atomic(self):
        row_valid = MockDoc(
            item_code="ITEM-VALID",
            stock_uom="Nos",
            warehouse="WH-1",
            custom_uom="Box",
            custom_qty_after=2.0,
            qty=10.0,
        )
        row_invalid = MockDoc(
            item_code="ITEM-INVALID",
            stock_uom="Nos",
            warehouse="WH-1",
            custom_uom="Unknown",
            custom_qty_after=3.0,
            qty=20.0,
        )
        doc = MockDoc(
            posting_date="2026-11-03",
            posting_time="10:00:00",
            items=[row_valid, row_invalid],
        )

        with patch("frappe.get_all") as mock_get_all:
            mock_get_all.return_value = [
                {"parent": "ITEM-VALID", "uom": "Box", "conversion_factor": 10.0},
            ]
            with self.assertRaises(frappe.ValidationError):
                apply_to_doc(doc)

        # Valid row's qty must be untouched (Review Focus 3)
        self.assertEqual(row_valid.qty, 10.0)
        self.assertNotIn(SR_FACTOR_FIELD, row_valid)

    def test_apply_to_doc_uses_doc_posting_time(self):
        row = MockDoc(
            item_code="ITEM-1",
            stock_uom="Nos",
            warehouse="WH-1",
            custom_uom="Nos",
            custom_qty_after=5.0,
            qty=0.0,
        )
        doc = MockDoc(
            posting_date="2026-11-03",
            posting_time="15:45:00",
            items=[row],
        )

        _stock_ledger.get_previous_sle.reset_mock()
        _stock_ledger.get_previous_sle.return_value = {"qty_after_transaction": 8.0}

        with patch("warehouse_app.sr_uom.resolve_factors", return_value={("ITEM-1", "Nos"): 1.0}):
            confirm_count_rows(doc)
            apply_to_doc(doc)

        _stock_ledger.get_previous_sle.assert_called_once_with(
            {
                "item_code": "ITEM-1",
                "warehouse": "WH-1",
                "posting_date": "2026-11-03",
                "posting_time": "15:45:00",
            }
        )
        self.assertEqual(row.qty, 5.0)
        self.assertEqual(row[SR_BEFORE_FIELD], 8.0)
        self.assertEqual(row[SR_DIFF_FIELD], -3.0)

    def test_precisions_from_row(self):
        row = MockDoc()
        prec = precisions(row)
        self.assertEqual(prec, {"qty": 6, "valuation_rate": 6, "rate_per_uom": 2, "qty_uom": 3})

    def test_precisions_from_new_doc(self):
        mock_doc = MockDoc()
        with patch("frappe.new_doc", return_value=mock_doc):
            prec = precisions(None)
            self.assertEqual(prec, {"qty": 6, "valuation_rate": 6, "rate_per_uom": 2, "qty_uom": 3})

    def test_ledger_qty_caching(self):
        _stock_ledger.get_previous_sle.reset_mock()
        _stock_ledger.get_previous_sle.return_value = {"qty_after_transaction": 42.0}
        cache = {}
        q1 = ledger_qty("ITEM-1", "WH-1", "2026-11-03", "10:00:00", cache)
        q2 = ledger_qty("ITEM-1", "WH-1", "2026-11-03", "10:00:00", cache)
        self.assertEqual(q1, 42.0)
        self.assertEqual(q2, 42.0)
        _stock_ledger.get_previous_sle.assert_called_once()

    def test_ledger_qty_with_batches(self):
        """F1: ledger_qty with batch_no uses get_batch_qty, forwards timestamp, caches per batch, nonbatch uses SLE."""
        _batch_mod.get_batch_qty.reset_mock()
        _stock_ledger.get_previous_sle.reset_mock()

        def mock_batch_qty(*args, **kwargs):
            b = kwargs.get("batch_no") or (args[0] if args else None)
            if b == "B1":
                return 24.0
            if b == "B2":
                return 36.0
            return 0.0

        _batch_mod.get_batch_qty.side_effect = mock_batch_qty
        _stock_ledger.get_previous_sle.return_value = {"qty_after_transaction": 60.0}

        cache = {}
        # B1 lookup
        q_b1 = ledger_qty("ITEM-B", "WH-1", "2026-11-03", "14:30:00", cache, batch_no="B1")
        self.assertEqual(q_b1, 24.0)
        _batch_mod.get_batch_qty.assert_called_once()
        b1_call_kwargs = _batch_mod.get_batch_qty.call_args[1]
        self.assertEqual(b1_call_kwargs.get("batch_no"), "B1")
        self.assertEqual(b1_call_kwargs.get("warehouse"), "WH-1")
        self.assertEqual(b1_call_kwargs.get("item_code"), "ITEM-B")
        self.assertEqual(b1_call_kwargs.get("posting_date"), "2026-11-03")
        self.assertEqual(b1_call_kwargs.get("posting_time"), "14:30:00")
        self.assertTrue(b1_call_kwargs.get("ignore_reserved_stock"))

        # B2 lookup
        q_b2 = ledger_qty("ITEM-B", "WH-1", "2026-11-03", "14:30:00", cache, batch_no="B2")
        self.assertEqual(q_b2, 36.0)
        self.assertEqual(_batch_mod.get_batch_qty.call_count, 2)

        # Cached B1 lookup (should not call get_batch_qty again)
        q_b1_again = ledger_qty("ITEM-B", "WH-1", "2026-11-03", "14:30:00", cache, batch_no="B1")
        self.assertEqual(q_b1_again, 24.0)
        self.assertEqual(_batch_mod.get_batch_qty.call_count, 2)

        # Non-batch lookup: uses get_previous_sle, not get_batch_qty
        q_nonbatch = ledger_qty("ITEM-B", "WH-1", "2026-11-03", "14:30:00", cache, batch_no=None)
        self.assertEqual(q_nonbatch, 60.0)
        _stock_ledger.get_previous_sle.assert_called_once()

    def test_apply_to_doc_two_batches_same_item_warehouse(self):
        """F1: apply_to_doc handles multiple batches of same item/warehouse correctly without setting warehouse sum."""
        _batch_mod.get_batch_qty.reset_mock()
        _stock_ledger.get_previous_sle.reset_mock()

        def mock_batch_qty(*args, **kwargs):
            b = kwargs.get("batch_no") or (args[0] if args else None)
            if b == "B1":
                return 24.0
            if b == "B2":
                return 36.0
            return 0.0

        _batch_mod.get_batch_qty.side_effect = mock_batch_qty
        _stock_ledger.get_previous_sle.return_value = {"qty_after_transaction": 60.0}

        row1 = MockDoc(
            doctype="Stock Reconciliation Item",
            item_code="ITEM-B",
            warehouse="WH-1",
            batch_no="B1",
            stock_uom="Nos",
            custom_uom="Pack",
            custom_qty_after=2.0,
            qty=24.0,
        )
        row2 = MockDoc(
            doctype="Stock Reconciliation Item",
            item_code="ITEM-B",
            warehouse="WH-1",
            batch_no="B2",
            stock_uom="Nos",
            custom_uom="Pack",
            custom_qty_after=3.0,
            qty=36.0,
        )
        doc = MockDoc(
            doctype="Stock Reconciliation",
            name="SR-BATCH-TEST",
            posting_date="2026-11-03",
            posting_time="14:30:00",
            items=[row1, row2],
        )

        with patch("warehouse_app.sr_uom.resolve_factors", return_value={("ITEM-B", "Pack"): 12.0}):
            confirm_count_rows(doc)
            apply_to_doc(doc)

        # B1: ledger=24, factor=12 -> before=2.0, qty_after=2.0, qty=24.0
        self.assertEqual(row1[SR_BEFORE_FIELD], 2.0)
        self.assertEqual(row1[SR_AFTER_FIELD], 2.0)
        self.assertEqual(row1.qty, 24.0)

        # B2: ledger=36, factor=12 -> before=3.0, qty_after=3.0, qty=36.0
        self.assertEqual(row2[SR_BEFORE_FIELD], 3.0)
        self.assertEqual(row2[SR_AFTER_FIELD], 3.0)
        self.assertEqual(row2.qty, 36.0)

    def test_ledger_qty_batch_ignores_reserved_stock(self):
        """F1: get_batch_qty must receive ignore_reserved_stock=True so physical 24 (reserved 12) stays 24."""
        _batch_mod.get_batch_qty.reset_mock()

        def mock_batch_qty(*args, **kwargs):
            if kwargs.get("ignore_reserved_stock"):
                return 24.0  # physical balance
            return 12.0  # available balance (physical 24 - reserved 12)

        _batch_mod.get_batch_qty.side_effect = mock_batch_qty
        cache = {}
        val = ledger_qty("ITEM-B", "WH-1", "2026-11-03", "10:00:00", cache, batch_no="B1")
        self.assertEqual(val, 24.0)
        self.assertTrue(_batch_mod.get_batch_qty.call_args[1].get("ignore_reserved_stock"))

    def test_precision_2_5_x_1_2_equals_3(self):
        res = compute_row(
            factor=1.2,
            ledger_qty=0,
            qty_after=2.5,
            prec=P,
        )
        self.assertEqual(res["qty"], 3.0)

    def test_unrepresentable_target_throws(self):
        with self.assertRaises(frappe.ValidationError):
            validate_representable_qty(1.0000005, 1.0, prec_qty=6)

    def test_unrepresentable_integer_uom_throws(self):
        with patch("frappe.get_cached_value", return_value=1):
            with self.assertRaises(frappe.ValidationError):
                validate_representable_qty(2.5, 1.0, stock_uom="Nos", prec_qty=6)

    def test_invalid_nonfinite_factor_input_throws_atomically(self):
        with self.assertRaises(frappe.ValidationError):
            validate_representable_qty(float("nan"), 1.0, prec_qty=6)
        with self.assertRaises(frappe.ValidationError):
            validate_representable_qty(10, 0, prec_qty=6)
        with self.assertRaises(frappe.ValidationError):
            validate_representable_qty(10, -2, prec_qty=6)

    def test_fingerprint_normalization(self):
        import datetime

        t1 = count_confirmation(
            company="Test Co",
            item_code="ITEM-1",
            warehouse="WH-1",
            posting_date="2026-11-05",
            posting_time="14:30:00",
            set_posting_time=1,
            uom="Pack",
            factor=6.0,
            batch_no=None,
        )
        t2 = count_confirmation(
            company=" Test Co ",
            item_code="ITEM-1",
            warehouse="WH-1",
            posting_date=datetime.date(2026, 11, 5),
            posting_time=datetime.time(14, 30, 0),
            set_posting_time=1,
            uom="Pack",
            factor="6",
            batch_no="",
        )
        self.assertEqual(t1, t2)
        self.assertTrue(len(t1) <= 64)
        t3 = count_confirmation(
            company="Test Co",
            item_code="ITEM-1",
            warehouse="WH-2",
            posting_date="2026-11-05",
            posting_time="14:30:00",
            set_posting_time=1,
            uom="Pack",
            factor=6,
            batch_no=None,
        )
        self.assertNotEqual(t1, t3)

    def test_posting_context_now_mode(self):
        tok1 = count_confirmation(
            company="Test Co",
            item_code="ITEM-1",
            warehouse="WH-1",
            posting_date="2026-11-05",
            posting_time="14:30:00",
            set_posting_time=0,
            uom="Pack",
            factor=6,
        )
        tok2 = count_confirmation(
            company="Test Co",
            item_code="ITEM-1",
            warehouse="WH-1",
            posting_date="2026-11-06",
            posting_time="00:05:00",
            set_posting_time=0,
            uom="Pack",
            factor=6,
        )
        self.assertEqual(tok1, tok2)

    def test_posting_context_explicit_mode_detects_same_day_time_change(self):
        e1 = count_confirmation(
            company="Test Co",
            item_code="ITEM-1",
            warehouse="WH-1",
            posting_date="2026-11-05",
            posting_time="14:30:00",
            set_posting_time=1,
            uom="Pack",
            factor=6,
        )
        e2 = count_confirmation(
            company="Test Co",
            item_code="ITEM-1",
            warehouse="WH-1",
            posting_date="2026-11-05",
            posting_time="14:30:05",
            set_posting_time=1,
            uom="Pack",
            factor=6,
        )
        self.assertNotEqual(e1, e2)

    def test_posting_context_explicit_mode_detects_microsecond_time_change(self):
        e1 = count_confirmation(
            company="Test Co",
            item_code="ITEM-1",
            warehouse="WH-1",
            posting_date="2026-11-05",
            posting_time="14:30:00.100000",
            set_posting_time=1,
            uom="Pack",
            factor=6,
        )
        e2 = count_confirmation(
            company="Test Co",
            item_code="ITEM-1",
            warehouse="WH-1",
            posting_date="2026-11-05",
            posting_time="14:30:00.200000",
            set_posting_time=1,
            uom="Pack",
            factor=6,
        )
        self.assertNotEqual(e1, e2)

    def test_posting_context_toggle_invalidates(self):
        tok_now = count_confirmation(
            company="Test Co",
            item_code="ITEM-1",
            warehouse="WH-1",
            posting_date="2026-11-05",
            posting_time="14:30:00",
            set_posting_time=0,
            uom="Pack",
            factor=6,
        )
        tok_exp = count_confirmation(
            company="Test Co",
            item_code="ITEM-1",
            warehouse="WH-1",
            posting_date="2026-11-05",
            posting_time="14:30:00",
            set_posting_time=1,
            uom="Pack",
            factor=6,
        )
        self.assertNotEqual(tok_now, tok_exp)

    def test_missing_confirmation_on_custom_row_throws(self):
        row = MockDoc(
            item_code="ITEM-1",
            stock_uom="Nos",
            warehouse="WH-1",
            custom_uom="Pack",
            custom_qty_after=10.0,
            qty=60.0,
        )
        doc = MockDoc(
            company="Test Co",
            posting_date="2026-11-05",
            posting_time="10:00:00",
            items=[row],
        )
        with patch("warehouse_app.sr_uom.resolve_factors", return_value={("ITEM-1", "Pack"): 6.0}):
            with self.assertRaises(frappe.ValidationError):
                apply_to_doc(doc)

    def test_context_mismatch_throws(self):
        token = count_confirmation(
            company="Test Co",
            item_code="ITEM-1",
            warehouse="WH-1",
            set_posting_time=0,
            uom="Pack",
            factor=6.0,
        )
        row = MockDoc(
            item_code="ITEM-1",
            stock_uom="Nos",
            warehouse="WH-2",
            custom_uom="Pack",
            custom_qty_after=10.0,
            custom_count_confirmation=token,
        )
        doc = MockDoc(
            company="Test Co",
            posting_date="2026-11-05",
            posting_time="10:00:00",
            set_posting_time=0,
            items=[row],
        )
        with patch("warehouse_app.sr_uom.resolve_factors", return_value={("ITEM-1", "Pack"): 6.0}):
            with self.assertRaises(frappe.ValidationError):
                apply_to_doc(doc)

    def test_posting_context_explicit_mode_accepts_midnight_timedelta(self):
        import datetime
        tok = count_confirmation(
            company="Test Co",
            item_code="ITEM-1",
            warehouse="WH-1",
            posting_date="2026-11-05",
            posting_time=datetime.timedelta(0),
            set_posting_time=1,
            uom="Pack",
            factor=6,
        )
        self.assertTrue(bool(tok))


    def test_master_factor_change_throws(self):
        token = count_confirmation(
            company="Test Co",
            item_code="ITEM-1",
            warehouse="WH-1",
            set_posting_time=0,
            uom="Pack",
            factor=6.0,
        )
        row = MockDoc(
            item_code="ITEM-1",
            stock_uom="Nos",
            warehouse="WH-1",
            custom_uom="Pack",
            custom_qty_after=10.0,
            custom_count_confirmation=token,
        )
        doc = MockDoc(
            company="Test Co",
            posting_date="2026-11-05",
            posting_time="10:00:00",
            set_posting_time=0,
            items=[row],
        )
        with patch("warehouse_app.sr_uom.resolve_factors", return_value={("ITEM-1", "Pack"): 12.0}):
            with self.assertRaises(frappe.ValidationError):
                apply_to_doc(doc)

    def test_native_only_and_mixed_rows_untouched(self):
        token = count_confirmation(
            company="Test Co",
            item_code="ITEM-CUSTOM",
            warehouse="WH-1",
            set_posting_time=0,
            uom="Pack",
            factor=6.0,
        )
        row_custom = MockDoc(
            item_code="ITEM-CUSTOM",
            stock_uom="Nos",
            warehouse="WH-1",
            custom_uom="Pack",
            custom_qty_after=10.0,
            custom_count_confirmation=token,
            qty=0,
        )
        row_native = MockDoc(
            item_code="ITEM-NATIVE",
            stock_uom="Nos",
            warehouse="WH-1",
            custom_uom=None,
            qty=42.0,
        )
        doc = MockDoc(
            company="Test Co",
            posting_date="2026-11-05",
            posting_time="10:00:00",
            set_posting_time=0,
            items=[row_custom, row_native],
        )
        with patch("warehouse_app.sr_uom.resolve_factors", return_value={("ITEM-CUSTOM", "Pack"): 6.0}):
            apply_to_doc(doc)
        self.assertEqual(row_custom.qty, 60.0)
        self.assertEqual(row_native.qty, 42.0)
        self.assertNotIn("custom_conversion_factor", row_native)

    def test_removing_uom_from_saved_counted_row_throws(self):
        """Finding 4: Removing custom_uom from saved counted row must throw ValidationError."""
        token = count_confirmation(
            company="Test Co",
            item_code="ITEM-1",
            warehouse="WH-1",
            set_posting_time=0,
            uom="Pack",
            factor=6.0,
        )
        prev_row = MockDoc(
            name="row-1",
            item_code="ITEM-1",
            stock_uom="Nos",
            warehouse="WH-1",
            custom_uom="Pack",
            custom_qty_after=1056.0,
            custom_count_confirmation=token,
            qty=6336.0,
        )
        prev_doc = MockDoc(
            name="SR-001",
            company="Test Co",
            posting_date="2026-11-05",
            posting_time="10:00:00",
            set_posting_time=0,
            items=[prev_row],
        )
        # In current doc, user/client stripped custom_uom and confirmation to bypass count validation
        curr_row = MockDoc(
            name="row-1",
            item_code="ITEM-1",
            stock_uom="Nos",
            warehouse="WH-1",
            custom_uom=None,
            custom_qty_after=None,
            custom_count_confirmation=None,
            qty=123.0,
        )
        doc = MockDoc(
            name="SR-001",
            company="Test Co",
            posting_date="2026-11-05",
            posting_time="10:00:00",
            set_posting_time=0,
            items=[curr_row],
            get_doc_before_save=lambda: prev_doc,
        )
        with self.assertRaises(frappe.ValidationError):
            apply_to_doc(doc)

    def test_deleting_saved_counted_row_allowed(self):
        """Finding 4: Deleting a row completely is allowed (normal draft row removal)."""
        prev_row = MockDoc(
            name="row-1",
            item_code="ITEM-1",
            stock_uom="Nos",
            warehouse="WH-1",
            custom_uom="Pack",
            custom_qty_after=1056.0,
            custom_count_confirmation="tok",
            qty=6336.0,
        )
        prev_doc = MockDoc(
            name="SR-001",
            company="Test Co",
            posting_date="2026-11-05",
            posting_time="10:00:00",
            set_posting_time=0,
            items=[prev_row],
        )
        doc = MockDoc(
            name="SR-001",
            company="Test Co",
            posting_date="2026-11-05",
            posting_time="10:00:00",
            set_posting_time=0,
            items=[],  # Row-1 was deleted
            get_doc_before_save=lambda: prev_doc,
        )
        # Should not raise
        apply_to_doc(doc)

    def test_confirm_count_rows(self):
        row = MockDoc(
            item_code="ITEM-1",
            stock_uom="Nos",
            warehouse="WH-1",
            custom_uom="Pack",
            custom_qty_after=1056,
        )
        doc = MockDoc(
            company="Test Co",
            posting_date="2026-11-05",
            posting_time="14:30:00",
            set_posting_time=0,
            items=[row],
        )
        with patch("warehouse_app.sr_uom.resolve_factors", return_value={("ITEM-1", "Pack"): 6.0}):
            confirm_count_rows(doc)
        self.assertTrue(row.get(SR_CONFIRMATION_FIELD))
        self.assertEqual(row.get(SR_FACTOR_FIELD), 6.0)

    def test_now_mode_save_submit_different_times_incl_midnight(self):
        row = MockDoc(
            item_code="ITEM-1",
            stock_uom="Nos",
            warehouse="WH-1",
            custom_uom="Pack",
            custom_qty_after=1056,
        )
        doc = MockDoc(
            company="Test Co",
            posting_date="2026-11-05",
            posting_time="23:59:00",
            set_posting_time=0,
            items=[row],
        )
        with patch("warehouse_app.sr_uom.resolve_factors", return_value={("ITEM-1", "Pack"): 6.0}):
            confirm_count_rows(doc)

        doc.posting_date = "2026-11-06"
        doc.posting_time = "00:05:00"
        with patch("warehouse_app.sr_uom.resolve_factors", return_value={("ITEM-1", "Pack"): 6.0}):
            apply_to_doc(doc)

        self.assertEqual(row.qty, 6336.0)
        self.assertEqual(row.custom_qty_after, 1056)


if __name__ == "__main__":
    unittest.main()


class TestSrUomPrecisionContract(unittest.TestCase):
    """Round 6b: per-UOM qty precision comes from installed metadata, not a constant."""

    def setUp(self):
        self.flt_patcher = patch("warehouse_app.sr_uom.flt", side_effect=_frappe_flt)
        self.flt_patcher.start()
        self.addCleanup(self.flt_patcher.stop)

    def test_precisions_reads_qty_uom_from_before_field_metadata(self):
        class Row(MockDoc):
            def precision(self, field):
                return {SR_BEFORE_FIELD: 4, "qty": 5, "valuation_rate": 5, SR_RATE_FIELD: 4}.get(field, 9)

        self.assertEqual(
            precisions(Row()), {"qty": 5, "valuation_rate": 5, "rate_per_uom": 4, "qty_uom": 4}
        )

    def test_nondefault_precision_before_diff_and_rate_round_trip(self):
        prec = {"qty": 5, "valuation_rate": 5, "rate_per_uom": 4, "qty_uom": 4}
        # Balance 6301 Pcs @ 1000.004 seeded as the stock-UOM rate (client seed), factor 6.
        out1 = compute_row(
            factor=6, ledger_qty=6301, qty_after=1056, qty=None, valuation_rate=1000.004, prec=prec
        )
        self.assertEqual(out1["custom_qty_before"], 1050.1667)
        self.assertEqual(out1["custom_qty_difference_per_uom"], 5.8333)
        self.assertEqual(out1["custom_valuation_rate_per_uom"], 6000.024)
        self.assertEqual(out1["valuation_rate"], 1000.004)
        self.assertEqual(out1["qty"], 6336.0)
        # Save feeds the reply back: valuation must not drift.
        out2 = compute_row(
            factor=6,
            ledger_qty=6301,
            qty_after=out1["custom_qty_after"],
            rate_per_uom=out1["custom_valuation_rate_per_uom"],
            qty=out1["qty"],
            valuation_rate=out1["valuation_rate"],
            prec=prec,
        )
        self.assertEqual(out1, out2)


def _cached_value_item_stock_uom(stock_uom):
    """frappe.get_cached_value stub: Item.stock_uom answered, everything else empty."""

    def _get(doctype, name, fieldname=None):
        if doctype == "Item" and fieldname == "stock_uom":
            return stock_uom
        return None

    return _get


class TestSrUomMasterStockUom(unittest.TestCase):
    """H2: stock UOM and factor come from the Item master, never from the row payload."""

    def setUp(self):
        self.flt_patcher = patch("warehouse_app.sr_uom.flt", side_effect=_frappe_flt)
        self.flt_patcher.start()
        self.addCleanup(self.flt_patcher.stop)

        cached = patch(
            "frappe.get_cached_value", side_effect=_cached_value_item_stock_uom("Pcs")
        )
        cached.start()
        self.addCleanup(cached.stop)

        get_all = patch(
            "frappe.get_all",
            return_value=[{"parent": "ITEM-1", "uom": "Pack", "conversion_factor": 6.0}],
        )
        get_all.start()
        self.addCleanup(get_all.stop)

    def _lying_row(self, **kwargs):
        # Payload claims the count UOM is the stock UOM; the master says Pcs.
        return MockDoc(
            idx=1,
            item_code="ITEM-1",
            stock_uom="Pack",
            warehouse="WH-1",
            custom_uom="Pack",
            custom_qty_after=1056,
            **kwargs,
        )

    def test_confirm_rows_uses_master_stock_uom_not_row(self):
        row = self._lying_row()
        doc = MockDoc(
            company="Test Co",
            posting_date="2026-11-05",
            posting_time="14:30:00",
            set_posting_time=0,
            items=[row],
        )

        confirm_count_rows(doc)

        self.assertEqual(row.get(SR_FACTOR_FIELD), 6.0)
        self.assertEqual(
            row.get(SR_CONFIRMATION_FIELD),
            count_confirmation(
                company="Test Co",
                item_code="ITEM-1",
                warehouse="WH-1",
                set_posting_time=0,
                uom="Pack",
                factor=6.0,
            ),
        )

    def test_apply_uses_master_factor_when_row_stock_uom_lies(self):
        row = self._lying_row(
            custom_count_confirmation=count_confirmation(
                company="Test Co",
                item_code="ITEM-1",
                warehouse="WH-1",
                set_posting_time=0,
                uom="Pack",
                factor=6.0,
            )
        )
        doc = MockDoc(
            company="Test Co",
            posting_date="2026-11-05",
            posting_time="14:30:00",
            set_posting_time=0,
            items=[row],
        )

        apply_to_doc(doc)

        self.assertEqual(row[SR_FACTOR_FIELD], 6.0)
        self.assertEqual(row.qty, 6336.0)

    def test_apply_rejects_token_minted_with_row_stock_uom(self):
        # Token minted by the pre-fix code, which trusted row.stock_uom="Pack" -> factor 1.
        row = self._lying_row(
            custom_count_confirmation=count_confirmation(
                company="Test Co",
                item_code="ITEM-1",
                warehouse="WH-1",
                set_posting_time=0,
                uom="Pack",
                factor=1.0,
            )
        )
        doc = MockDoc(
            company="Test Co",
            posting_date="2026-11-05",
            posting_time="14:30:00",
            set_posting_time=0,
            items=[row],
        )

        with self.assertRaises(frappe.ValidationError):
            apply_to_doc(doc)
        self.assertIsNone(row.get("qty"))  # 1056 Pack must never become 1056 Pcs


class AfterPrecisionRow(MockDoc):
    """Stock Reconciliation Item row whose After field is pinned to 2 decimals."""

    def precision(self, field):
        return 2 if field == SR_AFTER_FIELD else super().precision(field)


class TestSrUomAfterPrecision(unittest.TestCase):
    """H1: custom_qty_after must be exactly representable at its own field precision."""

    def setUp(self):
        self.flt_patcher = patch("warehouse_app.sr_uom.flt", side_effect=_frappe_flt)
        self.flt_patcher.start()
        self.addCleanup(self.flt_patcher.stop)

        cached = patch(
            "frappe.get_cached_value", side_effect=_cached_value_item_stock_uom("Pcs")
        )
        cached.start()
        self.addCleanup(cached.stop)

        factors = patch(
            "warehouse_app.sr_uom.resolve_factors", return_value={("ITEM-1", "Ton"): 1000.0}
        )
        factors.start()
        self.addCleanup(factors.stop)

    def _row(self, after, **kwargs):
        return AfterPrecisionRow(
            idx=1,
            item_code="ITEM-1",
            stock_uom="Pcs",
            warehouse="WH-1",
            custom_uom="Ton",
            custom_qty_after=after,
            **kwargs,
        )

    def _doc(self, row):
        return MockDoc(
            company="Test Co",
            posting_date="2026-11-05",
            posting_time="14:30:00",
            set_posting_time=0,
            items=[row],
        )

    def test_confirm_rejects_after_not_representable_at_own_precision(self):
        row = self._row(1.234)

        with self.assertRaises(frappe.ValidationError) as cm:
            confirm_count_rows(self._doc(row))

        msg = str(cm.exception)
        self.assertIn("Baris 1 (ITEM-1)", msg)
        self.assertIn("1.234", msg)
        self.assertIn("2 desimal", msg)
        self.assertNotIn(SR_CONFIRMATION_FIELD, row)

    def test_apply_rejects_after_not_representable_at_own_precision(self):
        row = self._row(
            1.234,
            custom_count_confirmation=count_confirmation(
                company="Test Co",
                item_code="ITEM-1",
                warehouse="WH-1",
                set_posting_time=0,
                uom="Ton",
                factor=1000.0,
            ),
        )

        with self.assertRaises(frappe.ValidationError) as cm:
            apply_to_doc(self._doc(row))

        msg = str(cm.exception)
        self.assertIn("Baris 1 (ITEM-1)", msg)
        self.assertIn("1.234", msg)
        self.assertIn("2 desimal", msg)

    def test_after_at_own_precision_round_trip_is_stable(self):
        # 1.23 is exactly representable at precision 2: storing it and re-deriving
        # qty must not move the counted stock.
        out1 = compute_row(factor=1000, ledger_qty=0, qty_after=1.23, prec=P)
        self.assertEqual(out1["qty"], 1230.0)

        stored_after = _frappe_flt(out1["custom_qty_after"], 2)
        out2 = compute_row(factor=1000, ledger_qty=0, qty_after=stored_after, prec=P)
        self.assertEqual(out2["qty"], 1230.0)
