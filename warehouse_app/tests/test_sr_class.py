# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto and contributors
# For license information, please see license.txt

"""Unit tests for StockReconciliationUOM class extension and hooks registration.

Verifies:
1. validate_posting_time converts after posting_time is set and before bundle steps & native filter
2. apply_to_doc uses final posting_time after super().validate_posting_time (Review Focus 4)
3. MRO cooperation with pos_next CustomStockReconciliation override
4. Regression test for batch zero-count converting before bundle is attached (F1)
5. extend_doctype_class hooks registration and doc_events removal
6. Old hook apply_sr_inventory_uom removal from inventory_uom
"""

import sys
import unittest
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
sys.path.insert(0, str(_p.parents[2]))

import frappe_stub
import frappe

# Setup erpnext module stubs before importing override module
for mod_name in [
    "erpnext",
    "erpnext.stock",
    "erpnext.stock.doctype",
    "erpnext.stock.doctype.stock_reconciliation",
    "erpnext.stock.doctype.stock_reconciliation.stock_reconciliation",
    "erpnext.stock.stock_ledger",
]:
    if mod_name not in sys.modules:
        m = ModuleType(mod_name)
        m.__path__ = []
        sys.modules[mod_name] = m

_stock_ledger = sys.modules["erpnext.stock.stock_ledger"]
if not hasattr(_stock_ledger, "get_previous_sle"):
    _stock_ledger.get_previous_sle = MagicMock(return_value=None)


class FakeStockReconciliation:
    def __init__(self, *args, **kwargs):
        self.posting_time = "OLD"
        self.docstatus = 0
        self.items = []
        self.calls = []
        for k, v in kwargs.items():
            setattr(self, k, v)

    def validate_posting_time(self):
        self.posting_time = "NOW"
        self.calls.append("native_validate_posting_time")

    def set_new_serial_and_batch_bundle(self):
        self.calls.append("bundle_step")

    def remove_items_with_no_change(self):
        self.calls.append("native_remove_items_with_no_change")

    def validate(self):
        self.validate_posting_time()
        self.set_new_serial_and_batch_bundle()
        self.remove_items_with_no_change()


sys.modules[
    "erpnext.stock.doctype.stock_reconciliation.stock_reconciliation"
].StockReconciliation = FakeStockReconciliation


class PosNextSR(FakeStockReconciliation):
    def validate(self):
        self.calls.append("pos_next_validate_pre")
        super().validate()
        self.calls.append("pos_next_validate_post")

    def remove_items_with_no_change(self):
        self.calls.append("pos_next_remove_items_with_no_change")
        if self.docstatus == 0:
            return
        super().remove_items_with_no_change()


# pos_next stubs: the Desk-save guard imports these lazily when pos_next is installed.
for mod_name in [
    "pos_next",
    "pos_next.overrides",
    "pos_next.overrides.stock_reconciliation",
    "pos_next.stock_opname_setup",
]:
    if mod_name not in sys.modules:
        m = ModuleType(mod_name)
        m.__path__ = []
        sys.modules[mod_name] = m
_pos_next_sr = sys.modules["pos_next.overrides.stock_reconciliation"]
if not hasattr(_pos_next_sr, "is_hq_user"):
    _pos_next_sr.is_hq_user = MagicMock(return_value=True)
sys.modules["pos_next.stock_opname_setup"].OUTLET_ROLES = ["POSNext Outlet User"]

# The override reads frappe.local.form_dict / frappe.form_dict; the stub creates neither.
frappe.local = getattr(frappe, "local", frappe._dict())
frappe.form_dict = getattr(frappe, "form_dict", frappe._dict())
if not hasattr(frappe, "get_installed_apps"):
    frappe.get_installed_apps = MagicMock(return_value=[])

from warehouse_app.overrides.stock_reconciliation import DESK_SAVE, StockReconciliationUOM
from warehouse_app.sr_uom import confirm_count_rows


class MockRow(frappe._dict):
    def set(self, k, v):
        self[k] = v

    def precision(self, field):
        return 6


class TestStockReconciliationClass(unittest.TestCase):
    def setUp(self):
        # Default: not a Desk form save, so the no-change filter follows the normal MRO.
        frappe.local = frappe._dict()
        frappe.form_dict = frappe._dict()

    def test_converts_after_posting_time_before_bundle_and_native_filter(self):
        with patch(
            "warehouse_app.overrides.stock_reconciliation.apply_to_doc",
            side_effect=lambda doc: doc.calls.append("apply_to_doc"),
        ):
            doc = StockReconciliationUOM()
            doc.validate()
            self.assertEqual(
                doc.calls,
                [
                    "native_validate_posting_time",
                    "apply_to_doc",
                    "bundle_step",
                    "native_remove_items_with_no_change",
                ],
            )

    def test_uses_final_posting_time(self):
        seen_posting_time = []
        with patch(
            "warehouse_app.overrides.stock_reconciliation.apply_to_doc",
            side_effect=lambda doc: seen_posting_time.append(doc.posting_time),
        ):
            doc = StockReconciliationUOM()
            doc.posting_time = "OLD"
            doc.validate()
            self.assertEqual(seen_posting_time, ["NOW"])

    def test_mro_with_pos_next_override(self):
        extended_cls = type(
            "ExtendedStockReconciliation", (StockReconciliationUOM, PosNextSR), {}
        )
        with patch(
            "warehouse_app.overrides.stock_reconciliation.apply_to_doc",
            side_effect=lambda doc: doc.calls.append("apply_to_doc"),
        ):
            doc = extended_cls()
            doc.docstatus = 0
            doc.validate()
            self.assertEqual(
                doc.calls,
                [
                    "pos_next_validate_pre",
                    "native_validate_posting_time",
                    "apply_to_doc",
                    "bundle_step",
                    "pos_next_remove_items_with_no_change",
                    "pos_next_validate_post",
                ],
            )

    def test_batch_zero_count_converts_before_bundle(self):
        """Regression test for F1: batch row with custom_qty_after=0 must convert
        before set_new_serial_and_batch_bundle attaches bundle.
        """
        class BundleAttachingSR(FakeStockReconciliation):
            def set_new_serial_and_batch_bundle(self):
                super().set_new_serial_and_batch_bundle()
                for row in self.items:
                    if row.get("batch_no"):
                        self.bundle_qty = row.get("qty")
                        row.serial_and_batch_bundle = "SABB-0001"

        cls = type("TestSR", (StockReconciliationUOM, BundleAttachingSR), {})
        doc = cls()
        doc.posting_date = "2026-11-03"
        doc.posting_time = "12:00:00"

        row = MockRow(
            item_code="BATCH-ITEM",
            warehouse="Stores - T",
            batch_no="B1",
            stock_uom="Pcs",
            custom_uom="Pcs",
            custom_qty_after=0,
            qty=10,
            serial_no=None,
            serial_and_batch_bundle=None,
        )
        doc.items = [row]
        doc.company = "Test Company"
        doc.set_posting_time = 0

        with patch("warehouse_app.sr_uom.resolve_factors", return_value={("BATCH-ITEM", "Pcs"): 1.0}):
            confirm_count_rows(doc)

        with patch(
            "erpnext.stock.stock_ledger.get_previous_sle",
            return_value={"qty_after_transaction": 10},
        ), patch(
            "warehouse_app.sr_uom.resolve_factors",
            return_value={("BATCH-ITEM", "Pcs"): 1.0},
        ):
            doc.validate()

        self.assertEqual(row.qty, 0.0)
        self.assertEqual(doc.bundle_qty, 0.0)
        self.assertEqual(row.serial_and_batch_bundle, "SABB-0001")

    def _set_desk_save(self, cmd=DESK_SAVE):
        frappe.local = frappe._dict(form_dict=frappe._dict(cmd=cmd))
        frappe.form_dict = frappe._dict(cmd=cmd)

    def _pos_next_doc(self):
        cls = type("TestSR", (StockReconciliationUOM, PosNextSR), {})
        doc = cls()
        doc.docstatus = 0
        return doc

    def test_desk_save_by_non_outlet_user_bypasses_pos_next_draft_skip(self):
        doc = self._pos_next_doc()
        self._set_desk_save()

        with patch("frappe.get_installed_apps", return_value=["frappe", "erpnext", "pos_next"]), patch(
            "frappe.get_roles", return_value=["Stock User"]
        ), patch.object(_pos_next_sr, "is_hq_user", return_value=False):
            doc.remove_items_with_no_change()

        self.assertEqual(doc.calls, ["native_remove_items_with_no_change"])

    def test_desk_save_by_outlet_user_keeps_pos_next_draft_skip(self):
        doc = self._pos_next_doc()
        self._set_desk_save()

        with patch("frappe.get_installed_apps", return_value=["frappe", "erpnext", "pos_next"]), patch(
            "frappe.get_roles", return_value=["POSNext Outlet User"]
        ), patch.object(_pos_next_sr, "is_hq_user", return_value=False):
            doc.remove_items_with_no_change()

        self.assertEqual(doc.calls, ["pos_next_remove_items_with_no_change"])

    def test_no_desk_cmd_keeps_pos_next_draft_skip(self):
        doc = self._pos_next_doc()
        self._set_desk_save(cmd="pos_next.api.stock")

        with patch("frappe.get_installed_apps", return_value=["frappe", "erpnext", "pos_next"]) as installed:
            doc.remove_items_with_no_change()

        self.assertEqual(doc.calls, ["pos_next_remove_items_with_no_change"])
        installed.assert_not_called()

    def test_hooks_registration(self):
        import warehouse_app.hooks as hooks

        self.assertEqual(
            hooks.extend_doctype_class.get("Stock Reconciliation"),
            ["warehouse_app.overrides.stock_reconciliation.StockReconciliationUOM"],
        )
        self.assertNotIn("Stock Reconciliation", hooks.doc_events)

    def test_old_hook_removed(self):
        import warehouse_app.inventory_uom as inventory_uom

        self.assertFalse(hasattr(inventory_uom, "apply_sr_inventory_uom"))


if __name__ == "__main__":
    unittest.main()
