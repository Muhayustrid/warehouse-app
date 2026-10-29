# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto and contributors
# For license information, please see license.txt

"""Unit tests for warehouse_app partial picker state derivation."""

import sys
import unittest
from unittest.mock import MagicMock, patch

try:
    import frappe
except ImportError:
    from pathlib import Path

    _apps = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(_apps / "production_app"))
    sys.path.insert(0, str(_apps / "production_app" / "production_app" / "tests"))
    sys.path.insert(0, str(_apps / "warehouse_app"))
    import frappe_stub
    import frappe

frappe.logger = MagicMock()


class TestWarehousePartialPicker(unittest.TestCase):
    def test_partial_transferred_wo_remains_requestable(self):
        """A Work Order with 25 Pcs produced and 21 Pcs transferred:
        - transferred_qty: 21.0
        - remaining_qty: 4.0
        - unrequested_qty: 4.0
        - request_shipped: False
        - request_partial: True
        - request_active: False (when no pending active MR)
        """
        produced = 25.0
        transferred = 21.0
        active_req = 0.0

        remaining = max(0.0, produced - transferred)
        unrequested = max(0.0, produced - transferred - active_req)
        request_active = active_req > 0
        request_shipped = bool(transferred > 0 and remaining <= 0)
        request_partial = bool(transferred > 0 and remaining > 0)

        self.assertEqual(transferred, 21.0)
        self.assertEqual(remaining, 4.0)
        self.assertEqual(unrequested, 4.0)
        self.assertFalse(request_shipped)
        self.assertTrue(request_partial)
        self.assertFalse(request_active)

    def test_fully_transferred_wo_marks_shipped(self):
        """A Work Order with 25 Pcs produced and 25 Pcs transferred:
        - transferred_qty: 25.0
        - remaining_qty: 0.0
        - request_shipped: True
        - request_partial: False
        """
        produced = 25.0
        transferred = 25.0
        active_req = 0.0

        remaining = max(0.0, produced - transferred)
        request_shipped = bool(transferred > 0 and remaining <= 0)
        request_partial = bool(transferred > 0 and remaining > 0)

        self.assertEqual(remaining, 0.0)
        self.assertTrue(request_shipped)
        self.assertFalse(request_partial)

    def test_expected_units_conversion(self):
        """expected_units must convert based on context:
        - active request: converts active_req
        - partial unrequested: converts unrequested_qty
        - new lot: converts produced_qty
        """
        row_active = frappe._dict({
            "name": "WO-ACTIVE",
            "produced_qty": 25.0,
            "display_conversion_factor": 1.0,
            "stock_uom": "Pcs",
            "request_active": True,
            "request_partial": False,
            "unrequested_qty": 4.0,
        })
        active_req_by_wo = {"WO-ACTIVE": 21.0}

        # Conversion for active:
        qty_to_convert = float(active_req_by_wo.get(row_active.name, 0.0)) or float(row_active.produced_qty)
        expected_units = int(round(qty_to_convert / float(row_active.display_conversion_factor or 1)))
        self.assertEqual(expected_units, 21)

        # Conversion for partial unrequested:
        row_partial = frappe._dict({
            "name": "WO-PARTIAL",
            "produced_qty": 25.0,
            "display_conversion_factor": 1.0,
            "stock_uom": "Pcs",
            "request_active": False,
            "request_partial": True,
            "unrequested_qty": 4.0,
        })
        qty_to_convert = float(row_partial.unrequested_qty)
        expected_units = int(round(qty_to_convert / float(row_partial.display_conversion_factor or 1)))
        self.assertEqual(expected_units, 4)

    def test_destination_warehouse_filtering(self):
        """transferred_by_wo query must apply target_warehouse clause from Manufacturing Settings."""
        from warehouse_app.warehouse_app.gudang_request import requestable_work_orders

        # Mock settings
        frappe.db.get_single_value = MagicMock(return_value="Gudang Barang Jadi - RR")
        frappe.get_all = MagicMock(return_value=[])
        frappe.get_list = MagicMock(return_value=[
            frappe._dict({
                "name": "WO-001",
                "creation": "2026-10-28 10:00:00",
                "custom_adonan_ke": 1,
                "production_item": "ITEM-1",
                "produced_qty": 25.0,
                "stock_uom": "Pcs",
                "status": "Completed",
                "fg_warehouse": "Gudang Produksi - RR",
                "custom_handover_material_request": None,
            })
        ])
        frappe.db.sql = MagicMock(side_effect=[
            [("WO-001", 21.0)],  # transferred_by_wo
            [],                   # active_mrs
        ])

        rows = requestable_work_orders(paginated=0)
        self.assertIn("company", frappe.get_list.call_args.kwargs["fields"])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r.transferred_qty, 21.0)
        self.assertEqual(r.remaining_qty, 4.0)
        self.assertEqual(r.unrequested_qty, 4.0)
        self.assertTrue(r.request_partial)
        self.assertFalse(r.request_active)
        self.assertFalse(r.request_shipped)

        # Verify SQL call checked target warehouse
        sql_call = frappe.db.sql.call_args_list[0]
        query = sql_call[0][0]
        params = sql_call[0][1]
        self.assertIn("sed.t_warehouse", query)
        self.assertEqual(params[1], "Gudang Barang Jadi - RR")

    def test_destination_warehouse_unset_fail_closed(self):
        """When custom_default_handover_warehouse is unset, transferred_by_wo must fail-closed to empty
        so transfers to unknown/other destinations are never counted as GBJ transfers.
        """
        from warehouse_app.warehouse_app.gudang_request import requestable_work_orders

        frappe.db.get_single_value = MagicMock(return_value=None)
        frappe.get_all = MagicMock(return_value=[])
        frappe.get_list = MagicMock(return_value=[
            frappe._dict({
                "name": "WO-FAIL-CLOSED",
                "creation": "2026-10-28 10:00:00",
                "custom_adonan_ke": 1,
                "production_item": "ITEM-1",
                "produced_qty": 25.0,
                "stock_uom": "Pcs",
                "status": "Completed",
                "fg_warehouse": "Gudang Produksi - RR",
                "custom_handover_material_request": None,
            })
        ])
        frappe.db.sql = MagicMock(return_value=[])

        rows = requestable_work_orders(paginated=0)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        # Must fail-closed: transferred_qty is 0.0, remaining_qty is full 25.0
        self.assertEqual(r.transferred_qty, 0.0)
        self.assertEqual(r.remaining_qty, 25.0)
        self.assertEqual(r.unrequested_qty, 25.0)

    def test_picker_active_flag_depends_on_outstanding_reservations(self):
        """request_active must depend on active_req > 0 (actual outstanding reservation),
        NOT on single-pointer custom_handover_material_request presence or any-SE.
        """
        from warehouse_app.warehouse_app.gudang_request import requestable_work_orders

        frappe.db.get_single_value = MagicMock(return_value="Gudang Barang Jadi - RR")
        frappe.get_all = MagicMock(return_value=[])
        frappe.get_list = MagicMock(return_value=[
            frappe._dict({
                "name": "WO-ACTIVE-RES",
                "creation": "2026-10-28 10:00:00",
                "custom_adonan_ke": 1,
                "production_item": "ITEM-1",
                "produced_qty": 25.0,
                "stock_uom": "Pcs",
                "status": "Completed",
                "fg_warehouse": "Gudang Produksi - RR",
                "custom_handover_material_request": "MR-OLD-COMPLETED",
            }),
            frappe._dict({
                "name": "WO-INACTIVE-RES",
                "creation": "2026-10-28 10:00:00",
                "custom_adonan_ke": 2,
                "production_item": "ITEM-1",
                "produced_qty": 25.0,
                "stock_uom": "Pcs",
                "status": "Completed",
                "fg_warehouse": "Gudang Produksi - RR",
                "custom_handover_material_request": "MR-OLD-COMPLETED-2",
            }),
        ])
        frappe.db.sql = MagicMock(side_effect=[
            [("WO-ACTIVE-RES", 0.0), ("WO-INACTIVE-RES", 25.0)],  # transferred_by_wo
            [{"custom_work_order": "WO-ACTIVE-RES", "outstanding_qty": 25.0}],  # active_mrs
        ])

        rows = requestable_work_orders(paginated=0)
        self.assertEqual(len(rows), 2)
        r_active = next(r for r in rows if r.name == "WO-ACTIVE-RES")
        r_inactive = next(r for r in rows if r.name == "WO-INACTIVE-RES")

        self.assertTrue(r_active.request_active)
        self.assertFalse(r_inactive.request_active)

    def test_fractional_display_uom_non_rounding(self):
        """Fractional display UOM conversions must NOT be rounded into valid integers.
        Inexact / non-whole divisions must set expected_units = None and unsupported_conversion = True.
        """
        from warehouse_app.warehouse_app.gudang_request import requestable_work_orders

        frappe.db.get_single_value = MagicMock(return_value="Gudang Barang Jadi - RR")
        frappe.get_all = MagicMock(return_value=[])
        # Two WOs: one with exact divisible yield (24 Pcs with factor 6 -> 4 Packs)
        # and one with inexact yield (25 Pcs with factor 6 -> 4.1667 Packs)
        frappe.get_list = MagicMock(return_value=[
            frappe._dict({
                "name": "WO-EXACT",
                "creation": "2026-10-28 10:00:00",
                "custom_adonan_ke": 1,
                "production_item": "ITEM-PACK",
                "produced_qty": 24.0,
                "stock_uom": "Pcs",
                "status": "Completed",
                "fg_warehouse": "Gudang Produksi - RR",
                "custom_handover_material_request": None,
                "display_uom": "Pack",
                "display_conversion_factor": 6.0,
            }),
            frappe._dict({
                "name": "WO-INEXACT",
                "creation": "2026-10-28 10:00:00",
                "custom_adonan_ke": 2,
                "production_item": "ITEM-PACK",
                "produced_qty": 25.0,
                "stock_uom": "Pcs",
                "status": "Completed",
                "fg_warehouse": "Gudang Produksi - RR",
                "custom_handover_material_request": None,
                "display_uom": "Pack",
                "display_conversion_factor": 6.0,
            }),
        ])
        frappe.db.sql = MagicMock(side_effect=[
            [],  # transferred_by_wo
            [],  # active_mrs
        ])

        with patch("production_app.api.work_order._enrich_units") as mock_enrich:
            # Let _enrich_units preserve the display_uom and factor
            rows = requestable_work_orders(paginated=0)

        self.assertEqual(len(rows), 2)
        r_exact = next(r for r in rows if r.name == "WO-EXACT")
        r_inexact = next(r for r in rows if r.name == "WO-INEXACT")

        # Exact: 24 / 6 = 4.0
        self.assertEqual(r_exact.expected_units, 4)
        self.assertFalse(r_exact.unsupported_conversion)

        # Inexact: 25 / 6 = 4.1667 -> must NOT round to 4!
        self.assertIsNone(r_inexact.expected_units)
        self.assertTrue(r_inexact.unsupported_conversion)


if __name__ == "__main__":
    unittest.main()
