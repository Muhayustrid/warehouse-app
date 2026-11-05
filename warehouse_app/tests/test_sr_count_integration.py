# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto and contributors
# For license information, please see license.txt

"""Integration tests for Stock Reconciliation counted-input protection (Task 6).

Runs on isolated test site (srcount.localhost) through native FrappeTestCase,
exercising the real Stock Reconciliation document controller, lifecycle hooks,
and native stock/GL ledger.
"""

from contextlib import contextmanager
from datetime import datetime
import unittest
from unittest.mock import patch

import frappe
from frappe.utils import flt, getdate, get_time

try:
    from frappe.tests.utils import FrappeTestCase
except ImportError:
    from unittest import TestCase as FrappeTestCase

from erpnext.stock.doctype.stock_reconciliation.stock_reconciliation import (
    EmptyStockReconciliationItemsError,
)
from warehouse_app.sr_uom import (
    SR_AFTER_FIELD,
    SR_BEFORE_FIELD,
    SR_CONFIRMATION_FIELD,
    SR_DIFF_FIELD,
    SR_FACTOR_FIELD,
    SR_UOM_FIELD,
    apply_to_doc,
    confirm_count_rows,
    count_confirmation,
)


class TestSrCountIntegration(FrappeTestCase):
    """End-to-end integration tests for Stock Reconciliation count protection."""

    SHOW_TRANSACTION_COMMIT_WARNINGS = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Verify execution context is strictly isolated scratch site
        current_site = getattr(frappe.local, "site", None)
        if current_site != "srcount.localhost":
            raise unittest.SkipTest(
                f"TestSrCountIntegration must run on srcount.localhost, current: {current_site}"
            )

        cls.company = "_Test SR Count Co"
        cls.warehouse = "Stores - _SCC"

        cls._setup_fixtures()

    @classmethod
    def _setup_fixtures(cls):
        # Capture exact snapshot of pre-test settings to restore in tearDownClass
        cls._pre_test_snapshot = {
            "company": {
                "exists": bool(frappe.db.exists("Company", cls.company)),
                "enable_perpetual_inventory": frappe.db.get_value("Company", cls.company, "enable_perpetual_inventory")
                if frappe.db.exists("Company", cls.company)
                else None,
            },
            "uoms": {
                uom: {
                    "exists": bool(frappe.db.exists("UOM", uom)),
                    "must_be_whole_number": frappe.db.get_value("UOM", uom, "must_be_whole_number")
                    if frappe.db.exists("UOM", uom)
                    else None,
                }
                for uom in ["Pcs", "Pack", "Kg", "Box"]
            },
            "stock_settings": {
                "enable_serial_and_batch_no_for_item": frappe.db.get_single_value(
                    "Stock Settings", "enable_serial_and_batch_no_for_item"
                )
            },
        }

        # 1. Company with perpetual inventory enabled
        if not frappe.db.exists("Company", cls.company):
            frappe.get_doc({
                "doctype": "Company",
                "company_name": cls.company,
                "default_currency": "IDR",
                "country": "Indonesia",
            }).insert()

        co = frappe.get_doc("Company", cls.company)
        if not co.enable_perpetual_inventory:
            co.enable_perpetual_inventory = 1
            co.save()

        # 2. UOMs
        uoms = [
            ("Pcs", 1),
            ("Pack", 0),
            ("Kg", 0),
            ("Box", 1),
        ]
        for uom_name, whole in uoms:
            if not frappe.db.exists("UOM", uom_name):
                frappe.get_doc({
                    "doctype": "UOM",
                    "uom_name": uom_name,
                    "must_be_whole_number": whole,
                }).insert()
            else:
                current_whole = frappe.db.get_value("UOM", uom_name, "must_be_whole_number")
                if current_whole != whole:
                    frappe.db.set_value("UOM", uom_name, "must_be_whole_number", whole)

        # 3. Stock Settings
        cls._orig_stock_settings_serial_batch = frappe.db.get_single_value(
            "Stock Settings", "enable_serial_and_batch_no_for_item"
        )
        frappe.db.set_single_value("Stock Settings", "enable_serial_and_batch_no_for_item", 1)

        cls._class_created_docs = []
        cls._class_created_items = []

        # 4. Seed an initial SLE so ERPNext does not consider subsequent reconciliations as Opening Stock
        seed_item = "_SEED_FIXTURE_ITEM"
        if not frappe.db.exists("Item", seed_item):
            frappe.get_doc({
                "doctype": "Item",
                "item_code": seed_item,
                "item_name": seed_item,
                "item_group": "All Item Groups",
                "stock_uom": "Pcs",
                "is_stock_item": 1,
            }).insert()
            cls._class_created_items.append(seed_item)
        if not frappe.db.sql("select name from `tabStock Ledger Entry` where item_code = %s limit 1", (seed_item,)):
            se = frappe.get_doc({
                "doctype": "Stock Entry",
                "stock_entry_type": "Material Receipt",
                "company": cls.company,
                "posting_date": "2026-01-01",
                "posting_time": "00:00:00",
                "set_posting_time": 1,
                "items": [{
                    "item_code": seed_item,
                    "t_warehouse": cls.warehouse,
                    "qty": 1.0,
                    "basic_rate": 1000.0,
                }],
            })
            se.insert()
            cls._class_created_docs.append(("Stock Entry", se.name))
            se.submit()

        frappe.db.commit()

    @classmethod
    def _cleanup_records(cls, docs, items):
        """Clean up exact tracked documents and items without any LIKE wildcards."""
        if not docs and not items:
            return

        # Deduplicate docs while preserving reverse creation order
        seen_docs = set()
        unique_docs = []
        for dt, dn in reversed(docs or []):
            if (dt, dn) not in seen_docs:
                seen_docs.add((dt, dn))
                unique_docs.append((dt, dn))

        # 1. Cancel and delete documents via standard API where possible
        for dt, dn in unique_docs:
            if not frappe.db.exists(dt, dn):
                continue
            try:
                doc = frappe.get_doc(dt, dn)
                if doc.docstatus == 1:
                    doc.cancel()
                doc.delete()
            except Exception:
                pass

        # 2. Delete leftovers per voucher doctype: names are never mixed across doctypes,
        # and ledgers are scoped by (voucher_type, voucher_no).
        names_by_doctype = {}
        for dt, dn in unique_docs:
            names_by_doctype.setdefault(dt, set()).add(dn)

        # doctype -> (child table, parent table)
        voucher_tables = {
            "Stock Reconciliation": ("Stock Reconciliation Item", "Stock Reconciliation"),
            "Stock Entry": ("Stock Entry Detail", "Stock Entry"),
        }
        for dt, (child_table, parent_table) in voucher_tables.items():
            names = names_by_doctype.get(dt)
            if not names:
                continue
            v_tuple = tuple(names)
            bundles = frappe.db.sql_list(
                "select name from `tabSerial and Batch Bundle` where voucher_type = %s and voucher_no in %s",
                (dt, v_tuple),
            )
            if bundles:
                b_tuple = tuple(bundles)
                frappe.db.sql("delete from `tabSerial and Batch Entry` where parent in %s", (b_tuple,))
                frappe.db.sql("delete from `tabSerial and Batch Bundle` where name in %s", (b_tuple,))

            for ledger_table in ("Stock Ledger Entry", "GL Entry", "Repost Item Valuation"):
                frappe.db.sql(
                    f"delete from `tab{ledger_table}` where voucher_type = %s and voucher_no in %s",
                    (dt, v_tuple),
                )
            frappe.db.sql(f"delete from `tab{child_table}` where parent in %s", (v_tuple,))
            frappe.db.sql(f"delete from `tab{parent_table}` where name in %s", (v_tuple,))

        # 3. Clean up batches
        batch_names = [dn for dt, dn in unique_docs if dt == "Batch"]
        if batch_names:
            frappe.db.sql("delete from `tabBatch` where name in %s", (tuple(set(batch_names)),))

        # 4. Clean up items
        if items:
            it_tuple = tuple(set(items))
            bundles = frappe.db.sql_list(
                "select name from `tabSerial and Batch Bundle` where item_code in %s",
                (it_tuple,),
            )
            if bundles:
                b_tuple = tuple(bundles)
                frappe.db.sql("delete from `tabSerial and Batch Entry` where parent in %s", (b_tuple,))
                frappe.db.sql("delete from `tabSerial and Batch Bundle` where name in %s", (b_tuple,))

            frappe.db.sql("delete from `tabBin` where item_code in %s", (it_tuple,))
            frappe.db.sql("delete from `tabBatch` where item in %s", (it_tuple,))
            frappe.db.sql("delete from `tabUOM Conversion Detail` where parent in %s", (it_tuple,))
            frappe.db.sql("delete from `tabItem` where name in %s", (it_tuple,))

    @classmethod
    def tearDownClass(cls):
        # 1. Cleanup created documents and items
        cls._cleanup_records(getattr(cls, "_class_created_docs", []), getattr(cls, "_class_created_items", []))

        # 2. Restore exact pre-test snapshot
        snapshot = getattr(cls, "_pre_test_snapshot", None)
        if snapshot:
            # Restore Company
            co_snap = snapshot.get("company", {})
            if co_snap.get("exists"):
                frappe.db.set_value(
                    "Company",
                    cls.company,
                    "enable_perpetual_inventory",
                    co_snap.get("enable_perpetual_inventory"),
                )
            elif frappe.db.exists("Company", cls.company):
                frappe.delete_doc("Company", cls.company, force=1)

            # Restore UOMs
            for uom_name, uom_snap in snapshot.get("uoms", {}).items():
                if uom_snap.get("exists"):
                    frappe.db.set_value(
                        "UOM",
                        uom_name,
                        "must_be_whole_number",
                        uom_snap.get("must_be_whole_number"),
                    )
                elif frappe.db.exists("UOM", uom_name):
                    frappe.delete_doc("UOM", uom_name, force=1)

            # Restore Stock Settings
            st_snap = snapshot.get("stock_settings", {})
            if "enable_serial_and_batch_no_for_item" in st_snap:
                frappe.db.set_single_value(
                    "Stock Settings",
                    "enable_serial_and_batch_no_for_item",
                    st_snap["enable_serial_and_batch_no_for_item"],
                )

            frappe.db.commit()

            # 3. Assert post-run values equal the snapshot
            if co_snap.get("exists"):
                curr_co = frappe.db.get_value("Company", cls.company, "enable_perpetual_inventory")
                assert curr_co == co_snap["enable_perpetual_inventory"], (
                    f"Company {cls.company} enable_perpetual_inventory post-test mismatch: {curr_co} != {co_snap['enable_perpetual_inventory']}"
                )
            for uom_name, uom_snap in snapshot.get("uoms", {}).items():
                if uom_snap.get("exists"):
                    curr_uom = frappe.db.get_value("UOM", uom_name, "must_be_whole_number")
                    assert curr_uom == uom_snap["must_be_whole_number"], (
                        f"UOM {uom_name} must_be_whole_number post-test mismatch: {curr_uom} != {uom_snap['must_be_whole_number']}"
                    )
            curr_sb = frappe.db.get_single_value("Stock Settings", "enable_serial_and_batch_no_for_item")
            assert curr_sb == st_snap["enable_serial_and_batch_no_for_item"], (
                f"Stock Settings enable_serial_and_batch_no_for_item mismatch: {curr_sb} != {st_snap['enable_serial_and_batch_no_for_item']}"
            )
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self._created_docs = []
        self._created_items = []

    def track(self, doc):
        """Track a document for automatic cancellation and deletion during tearDown."""
        if doc and hasattr(doc, "doctype") and hasattr(doc, "name"):
            self._created_docs.append((doc.doctype, doc.name))
        return doc

    def track_sr(self, sr):
        """Track a Stock Reconciliation; every created SR must go through this."""
        self._created_docs.append(("Stock Reconciliation", sr.name))
        return sr

    def tearDown(self):
        # Only documents tracked at creation are cleaned up; nothing is discovered by item_code.
        self._cleanup_records(self._created_docs, self._created_items)
        frappe.db.commit()
        super().tearDown()

    def make_test_item(self, tag, stock_uom="Pcs", pack_factor=None, has_batch=False):
        """Create a uniquely named test item fixture for the current test method."""
        uid = frappe.generate_hash(length=6)
        item_code = f"_T_{tag}_{uid}"
        doc = {
            "doctype": "Item",
            "item_code": item_code,
            "item_name": item_code,
            "item_group": "All Item Groups",
            "stock_uom": stock_uom,
            "is_stock_item": 1,
        }
        if pack_factor:
            doc["uoms"] = [{"uom": "Pack", "conversion_factor": pack_factor}]
        if has_batch:
            doc["has_batch_no"] = 1
            doc["create_new_batch"] = 1
            doc["batch_number_series"] = f"B-{tag}-.#####"
        item_doc = frappe.get_doc(doc).insert()
        frappe.db.commit()
        if hasattr(self, "_created_items"):
            self._created_items.append(item_doc.name)
        if hasattr(self, "_created_docs"):
            self._created_docs.append(("Item", item_doc.name))
        return item_doc.name

    def make_stock_entry(
        self,
        item_code,
        qty,
        rate,
        posting_date="2026-11-01",
        posting_time="10:00:00",
        batch_no=None,
    ):
        """Create and submit a Material Receipt Stock Entry to seed stock."""
        stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
        item_row = {
            "item_code": item_code,
            "t_warehouse": self.warehouse,
            "qty": qty,
            "basic_rate": rate,
            "uom": stock_uom,
            "conversion_factor": 1.0,
            "stock_uom": stock_uom,
        }
        if batch_no:
            item_row["batch_no"] = batch_no
            item_row["use_serial_batch_fields"] = 1

        se = frappe.get_doc({
            "doctype": "Stock Entry",
            "stock_entry_type": "Material Receipt",
            "company": self.company,
            "posting_date": posting_date,
            "posting_time": posting_time,
            "set_posting_time": 1,
            "items": [item_row],
        })
        se.insert()
        # Track before submit so a submit failure cannot leak an untracked document.
        if hasattr(self, "_created_docs"):
            self._created_docs.append(("Stock Entry", se.name))
        se.submit()
        frappe.db.commit()
        return se

    @staticmethod
    @contextmanager
    def mock_now(frozen_dt: datetime):
        """Context manager to freeze frappe datetime for 'now' mode simulation."""
        with patch("frappe.utils.data.now_datetime", return_value=frozen_dt), \
             patch("frappe.utils.now_datetime", return_value=frozen_dt), \
             patch("erpnext.utilities.transaction_base.now_datetime", return_value=frozen_dt):
            yield

    def test_01_1056_pack_save_submit_reload_and_ledger(self):
        """1056 Pack -> save/reload (After 1056, qty 6336) -> submit/reload -> SLE qty 6336."""
        item = self.make_test_item("C01", stock_uom="Pcs", pack_factor=6.0)
        # Initial seed: 6000 Pcs at rate 1000
        self.make_stock_entry(item, 6000.0, 1000.0, posting_date="2026-11-01")

        sr = frappe.get_doc({
            "doctype": "Stock Reconciliation",
            "company": self.company,
            "purpose": "Stock Reconciliation",
            "posting_date": "2026-11-05",
            "posting_time": "12:00:00",
            "set_posting_time": 1,
            "items": [{
                "item_code": item,
                "warehouse": self.warehouse,
                "custom_uom": "Pack",
                "custom_qty_after": 1056.0,
                "valuation_rate": 1000.0,
            }],
        })
        confirm_count_rows(sr)
        sr.insert()
        self.track_sr(sr)
        frappe.db.commit()

        # Save and reload: user count target 1056 Pack and derived native qty 6336 Pcs preserved
        sr.reload()
        row = sr.items[0]
        self.assertEqual(row.custom_qty_after, 1056.0)
        self.assertEqual(row.qty, 6336.0)

        # Submit and reload: ledger balance populated and After/Qty unchanged
        sr.submit()
        frappe.db.commit()

        sr.reload()
        row = sr.items[0]
        self.assertEqual(row.custom_qty_after, 1056.0)
        self.assertEqual(row.qty, 6336.0)
        self.assertEqual(row.custom_qty_before, 1000.0)
        self.assertEqual(row.custom_qty_difference_per_uom, 56.0)

        # SLE check
        sle = frappe.db.get_value(
            "Stock Ledger Entry",
            {"voucher_no": sr.name, "is_cancelled": 0},
            ["qty_after_transaction", "valuation_rate", "stock_value"],
            as_dict=True,
        )
        self.assertIsNotNone(sle)
        self.assertEqual(sle.qty_after_transaction, 6336.0)
        self.assertEqual(sle.valuation_rate, 1000.0)
        self.assertEqual(sle.stock_value, 6336000.0)

        # GL check (perpetual inventory enabled)
        gl_entries = frappe.db.get_all(
            "GL Entry",
            filters={"voucher_no": sr.name, "is_cancelled": 0},
            fields=["account", "debit", "credit"],
        )
        self.assertTrue(len(gl_entries) >= 2)
        debits = sum(g.debit for g in gl_entries)
        credits = sum(g.credit for g in gl_entries)
        self.assertAlmostEqual(debits, credits, places=2)
        self.assertAlmostEqual(debits, 336000.0, places=2)

        # Repost state check: no failed repost entries
        failed_reposts = frappe.db.get_all(
            "Repost Item Valuation",
            filters={"voucher_no": sr.name, "status": "Failed"},
        )
        self.assertEqual(len(failed_reposts), 0)

    def test_02_later_movement_changes_balance_not_sr(self):
        """A later fixture movement changes today's balance but not the submitted SR."""
        item = self.make_test_item("C02", stock_uom="Pcs", pack_factor=6.0)
        # Seed 6000 Pcs on 2026-11-01, reconcile to 1056 Pack (6336 Pcs) on 2026-11-02
        self.make_stock_entry(item, 6000.0, 1000.0, posting_date="2026-11-01", posting_time="10:00:00")

        sr = frappe.get_doc({
            "doctype": "Stock Reconciliation",
            "company": self.company,
            "purpose": "Stock Reconciliation",
            "posting_date": "2026-11-02",
            "posting_time": "12:00:00",
            "set_posting_time": 1,
            "items": [{
                "item_code": item,
                "warehouse": self.warehouse,
                "custom_uom": "Pack",
                "custom_qty_after": 1056.0,
                "valuation_rate": 1000.0,
            }],
        })
        confirm_count_rows(sr)
        sr.insert()
        self.track_sr(sr)
        sr.submit()
        frappe.db.commit()

        sr.reload()
        before_qty = sr.items[0].qty
        before_after = sr.items[0].custom_qty_after
        before_modified = sr.modified

        # Movement on later date: adds 120 Pcs on 2026-11-03
        self.make_stock_entry(
            item, 120.0, 1000.0, posting_date="2026-11-03", posting_time="10:00:00"
        )

        # Check current stock balance is now 6336 + 120 = 6456
        from erpnext.stock.utils import get_stock_balance
        curr_bal = get_stock_balance(item, self.warehouse)
        self.assertEqual(curr_bal, 6456.0)

        # Reload submitted SR: completely unchanged
        sr.reload()
        self.assertEqual(sr.items[0].qty, before_qty)
        self.assertEqual(sr.items[0].custom_qty_after, before_after)
        self.assertEqual(sr.modified, before_modified)

    def test_03_count_zero(self):
        """Count 0: After 0 -> derived native qty 0 -> SLE qty_after_transaction 0."""
        item = self.make_test_item("C03", stock_uom="Pcs", pack_factor=6.0)
        self.make_stock_entry(item, 600.0, 1000.0, posting_date="2026-11-01")

        sr = frappe.get_doc({
            "doctype": "Stock Reconciliation",
            "company": self.company,
            "purpose": "Stock Reconciliation",
            "posting_date": "2026-11-05",
            "posting_time": "12:00:00",
            "set_posting_time": 1,
            "items": [{
                "item_code": item,
                "warehouse": self.warehouse,
                "custom_uom": "Pack",
                "custom_qty_after": 0.0,
                "valuation_rate": 1000.0,
            }],
        })
        confirm_count_rows(sr)
        sr.insert()
        self.track_sr(sr)
        sr.submit()
        frappe.db.commit()

        sr.reload()
        self.assertEqual(sr.items[0].custom_qty_after, 0.0)
        self.assertEqual(sr.items[0].qty, 0.0)

        sle = frappe.db.get_value(
            "Stock Ledger Entry",
            {"voucher_no": sr.name, "is_cancelled": 0},
            ["qty_after_transaction", "stock_value"],
            as_dict=True,
        )
        self.assertIsNotNone(sle)
        self.assertEqual(sle.qty_after_transaction, 0.0)
        self.assertEqual(sle.stock_value, 0.0)

    def test_04_representable_fraction(self):
        """Representable fraction with non-integer factor: 2.5 Pack * 1.2 = 3.0 Kg."""
        item = self.make_test_item("C04", stock_uom="Kg", pack_factor=1.2)
        self.make_stock_entry(item, 10.0, 500.0, posting_date="2026-11-01")

        sr = frappe.get_doc({
            "doctype": "Stock Reconciliation",
            "company": self.company,
            "purpose": "Stock Reconciliation",
            "posting_date": "2026-11-05",
            "posting_time": "12:00:00",
            "set_posting_time": 1,
            "items": [{
                "item_code": item,
                "warehouse": self.warehouse,
                "custom_uom": "Pack",
                "custom_qty_after": 2.5,
                "valuation_rate": 500.0,
            }],
        })
        confirm_count_rows(sr)
        sr.insert()
        self.track_sr(sr)
        sr.submit()
        frappe.db.commit()

        sr.reload()
        self.assertEqual(sr.items[0].custom_qty_after, 2.5)
        self.assertEqual(sr.items[0].qty, 3.0)

        sle = frappe.db.get_value(
            "Stock Ledger Entry",
            {"voucher_no": sr.name, "is_cancelled": 0},
            ["qty_after_transaction"],
            as_dict=True,
        )
        self.assertEqual(sle.qty_after_transaction, 3.0)

    def test_05_non_representable_refusal(self):
        """Non-representable target on integer stock UOM throws ValidationError."""
        item = self.make_test_item("C05", stock_uom="Pcs", pack_factor=1.0)
        sr = frappe.get_doc({
            "doctype": "Stock Reconciliation",
            "company": self.company,
            "purpose": "Stock Reconciliation",
            "posting_date": "2026-11-05",
            "posting_time": "12:00:00",
            "set_posting_time": 1,
            "items": [{
                "item_code": item,
                "warehouse": self.warehouse,
                "custom_uom": "Pack",
                "custom_qty_after": 1.5,  # 1.5 * 1.0 = 1.5, but stock UOM Pcs must be whole
                "valuation_rate": 100.0,
            }],
        })
        with self.assertRaises(frappe.ValidationError):
            confirm_count_rows(sr)

    def test_06_master_factor_change_between_save_and_submit_errors(self):
        """Master factor changed after Save prevents Submit and leaves doc numbers unchanged."""
        item_code = self.make_test_item("C06", stock_uom="Pcs", pack_factor=6.0)
        self.make_stock_entry(item_code, 6000.0, 1000.0, posting_date="2026-11-01")

        sr = frappe.get_doc({
            "doctype": "Stock Reconciliation",
            "company": self.company,
            "purpose": "Stock Reconciliation",
            "posting_date": "2026-11-05",
            "posting_time": "12:00:00",
            "set_posting_time": 1,
            "items": [{
                "item_code": item_code,
                "warehouse": self.warehouse,
                "custom_uom": "Pack",
                "custom_qty_after": 100.0,
                "valuation_rate": 1000.0,
            }],
        })
        confirm_count_rows(sr)
        sr.insert()
        self.track_sr(sr)
        frappe.db.commit()

        # Modify master factor in Item to 12.0
        item = frappe.get_doc("Item", item_code)
        item.uoms[0].conversion_factor = 12.0
        item.save()
        frappe.db.commit()

        with self.assertRaises(frappe.ValidationError):
            sr.submit()

        # Reload: numbers in DB unchanged
        sr.reload()
        self.assertEqual(sr.items[0].custom_qty_after, 100.0)
        self.assertEqual(sr.items[0].qty, 600.0)
        self.assertEqual(sr.docstatus, 0)

    def test_07_now_mode_save_submit_across_midnight(self):
        """'now' mode Save before midnight and Submit after midnight succeeds with unchanged target."""
        item = self.make_test_item("C07", stock_uom="Pcs", pack_factor=6.0)
        self.make_stock_entry(item, 6000.0, 1000.0, posting_date="2026-11-01")

        t1 = datetime(2026, 11, 8, 23, 59, 0)
        t2 = datetime(2026, 11, 9, 0, 5, 0)

        with self.mock_now(t1):
            sr = frappe.get_doc({
                "doctype": "Stock Reconciliation",
                "company": self.company,
                "purpose": "Stock Reconciliation",
                "posting_date": "2026-11-08",
                "posting_time": "23:59:00",
                "set_posting_time": 0,
                "items": [{
                    "item_code": item,
                    "warehouse": self.warehouse,
                    "custom_uom": "Pack",
                    "custom_qty_after": 1056.0,
                    "valuation_rate": 1000.0,
                }],
            })
            confirm_count_rows(sr)
            sr.insert()
            self.track_sr(sr)
            frappe.db.commit()

        with self.mock_now(t2):
            sr.reload()
            sr.submit()
            frappe.db.commit()

        sr.reload()
        self.assertEqual(sr.items[0].custom_qty_after, 1056.0)
        self.assertEqual(sr.items[0].qty, 6336.0)
        self.assertEqual(sr.docstatus, 1)

        sle = frappe.db.get_value(
            "Stock Ledger Entry",
            {"voucher_no": sr.name, "is_cancelled": 0},
            ["posting_date", "qty_after_transaction"],
            as_dict=True,
        )
        self.assertEqual(getdate(sle.posting_date), getdate("2026-11-09"))
        self.assertEqual(sle.qty_after_transaction, 6336.0)

    def test_08_explicit_mode_same_day_time_change_invalid(self):
        """In explicit mode (set_posting_time=1), altering posting_time invalidates confirmation."""
        item = self.make_test_item("C08", stock_uom="Pcs", pack_factor=6.0)
        sr = frappe.get_doc({
            "doctype": "Stock Reconciliation",
            "company": self.company,
            "purpose": "Stock Reconciliation",
            "posting_date": "2026-11-10",
            "posting_time": "10:00:00",
            "set_posting_time": 1,
            "items": [{
                "item_code": item,
                "warehouse": self.warehouse,
                "custom_uom": "Pack",
                "custom_qty_after": 50.0,
                "valuation_rate": 1000.0,
            }],
        })
        confirm_count_rows(sr)
        sr.insert()
        self.track_sr(sr)
        frappe.db.commit()

        # Same-day time change
        sr.posting_time = "11:00:00"
        with self.assertRaises(frappe.ValidationError):
            sr.save()

    def test_09_toggle_set_posting_time_invalid(self):
        """Toggling set_posting_time invalidates confirmation."""
        item = self.make_test_item("C09", stock_uom="Pcs", pack_factor=6.0)
        sr = frappe.get_doc({
            "doctype": "Stock Reconciliation",
            "company": self.company,
            "purpose": "Stock Reconciliation",
            "posting_date": "2026-11-10",
            "posting_time": "10:00:00",
            "set_posting_time": 0,
            "items": [{
                "item_code": item,
                "warehouse": self.warehouse,
                "custom_uom": "Pack",
                "custom_qty_after": 50.0,
                "valuation_rate": 1000.0,
            }],
        })
        confirm_count_rows(sr)
        sr.insert()
        self.track_sr(sr)
        frappe.db.commit()

        # Toggle to explicit mode
        sr.set_posting_time = 1
        with self.assertRaises(frappe.ValidationError):
            sr.save()

    def test_10_intervening_transaction_does_not_rewrite_count(self):
        """Intervening stock movement between Save and Submit does not rewrite user count target."""
        item = self.make_test_item("C10", stock_uom="Pcs", pack_factor=6.0)
        self.make_stock_entry(item, 6000.0, 1000.0, posting_date="2026-11-01")

        t1 = datetime(2026, 11, 11, 10, 0, 0)
        t2 = datetime(2026, 11, 11, 11, 0, 0)

        with self.mock_now(t1):
            sr = frappe.get_doc({
                "doctype": "Stock Reconciliation",
                "company": self.company,
                "purpose": "Stock Reconciliation",
                "posting_date": "2026-11-11",
                "posting_time": "10:00:00",
                "set_posting_time": 0,
                "items": [{
                    "item_code": item,
                    "warehouse": self.warehouse,
                    "custom_uom": "Pack",
                    "custom_qty_after": 1056.0,
                    "valuation_rate": 1000.0,
                }],
            })
            confirm_count_rows(sr)
            sr.insert()
            self.track_sr(sr)
            frappe.db.commit()

        # Intervening receipt at 10:30:00 adds 120 Pcs
        self.make_stock_entry(
            item, 120.0, 1000.0, posting_date="2026-11-11", posting_time="10:30:00"
        )

        with self.mock_now(t2):
            sr.reload()
            sr.submit()
            frappe.db.commit()

        sr.reload()
        # After remains exactly 1056.0 Pack and target qty remains 6336.0 Pcs
        self.assertEqual(sr.items[0].custom_qty_after, 1056.0)
        self.assertEqual(sr.items[0].qty, 6336.0)

        sle = frappe.db.get_value(
            "Stock Ledger Entry",
            {"voucher_no": sr.name, "is_cancelled": 0},
            ["qty_after_transaction"],
            as_dict=True,
        )
        self.assertEqual(sle.qty_after_transaction, 6336.0)

    def test_11_explicit_fingerprint_stable_after_reload(self):
        """Explicit confirmation token is persisted and stable across doc reloads."""
        item = self.make_test_item("C11", stock_uom="Pcs", pack_factor=6.0)
        sr = frappe.get_doc({
            "doctype": "Stock Reconciliation",
            "company": self.company,
            "purpose": "Stock Reconciliation",
            "posting_date": "2026-11-12",
            "posting_time": "14:00:00",
            "set_posting_time": 1,
            "items": [{
                "item_code": item,
                "warehouse": self.warehouse,
                "custom_uom": "Pack",
                "custom_qty_after": 200.0,
                "valuation_rate": 1000.0,
            }],
        })
        confirm_count_rows(sr)
        expected_token = sr.items[0].custom_count_confirmation
        self.assertTrue(expected_token)
        sr.insert()
        self.track_sr(sr)
        frappe.db.commit()

        sr.reload()
        reloaded_token = sr.items[0].custom_count_confirmation
        self.assertEqual(reloaded_token, expected_token)

        # Save again without changes succeeds
        sr.save()
        self.assertEqual(sr.items[0].custom_count_confirmation, expected_token)

    def test_12_native_only_and_mixed_rows(self):
        """Mixed SR: custom row converts one-way, native row preserves native behavior."""
        item_custom = self.make_test_item("C12C", stock_uom="Pcs", pack_factor=6.0)
        item_native = self.make_test_item("C12N", stock_uom="Pcs", pack_factor=None)

        sr = frappe.get_doc({
            "doctype": "Stock Reconciliation",
            "company": self.company,
            "purpose": "Stock Reconciliation",
            "posting_date": "2026-11-13",
            "posting_time": "12:00:00",
            "set_posting_time": 1,
            "items": [
                {
                    "item_code": item_custom,
                    "warehouse": self.warehouse,
                    "custom_uom": "Pack",
                    "custom_qty_after": 100.0,
                    "valuation_rate": 1000.0,
                },
                {
                    "item_code": item_native,
                    "warehouse": self.warehouse,
                    "qty": 50.0,
                    "valuation_rate": 200.0,
                },
            ],
        })
        confirm_count_rows(sr)
        self.assertIsNotNone(sr.items[0].custom_count_confirmation)
        self.assertIsNone(getattr(sr.items[1], "custom_count_confirmation", None))

        sr.insert()
        self.track_sr(sr)
        sr.submit()
        frappe.db.commit()

        sr.reload()
        # Row 1 (custom)
        self.assertEqual(sr.items[0].custom_qty_after, 100.0)
        self.assertEqual(sr.items[0].qty, 600.0)
        # Row 2 (native)
        self.assertIsNone(sr.items[1].custom_uom)
        self.assertEqual(sr.items[1].qty, 50.0)

    def test_13_batch_custom_row(self):
        """Batch item with direct batch_no field converts one-way and posts batch balance."""
        item = self.make_test_item("C13", stock_uom="Pcs", pack_factor=6.0, has_batch=True)
        batch_id = f"B-C13-{frappe.generate_hash(length=4)}"
        batch = frappe.get_doc({
            "doctype": "Batch",
            "batch_id": batch_id,
            "item": item,
        }).insert()
        frappe.db.commit()
        self.track(batch)

        # Seed batch stock
        self.make_stock_entry(
            item,
            600.0,
            2000.0,
            posting_date="2026-11-01",
            posting_time="10:00:00",
            batch_no=batch_id,
        )

        sr = frappe.get_doc({
            "doctype": "Stock Reconciliation",
            "company": self.company,
            "purpose": "Stock Reconciliation",
            "posting_date": "2026-11-14",
            "posting_time": "12:00:00",
            "set_posting_time": 1,
            "items": [{
                "item_code": item,
                "warehouse": self.warehouse,
                "custom_uom": "Pack",
                "custom_qty_after": 120.0,
                "valuation_rate": 2000.0,
                "batch_no": batch_id,
                "use_serial_batch_fields": 1,
            }],
        })
        confirm_count_rows(sr)
        sr.insert()
        self.track_sr(sr)
        sr.submit()
        frappe.db.commit()

        sr.reload()
        self.assertEqual(sr.items[0].custom_qty_after, 120.0)
        self.assertEqual(sr.items[0].qty, 720.0)
        self.assertEqual(sr.items[0].custom_qty_before, 100.0)
        self.assertEqual(sr.items[0].custom_qty_difference_per_uom, 20.0)

    def test_14_no_change_all_matched_behaviour(self):
        """All-matched items save on draft but throw EmptyStockReconciliationItemsError on submit."""
        item = self.make_test_item("C14", stock_uom="Pcs", pack_factor=6.0)
        # Seed stock: 6000 Pcs at rate 1000
        self.make_stock_entry(item, 6000.0, 1000.0, posting_date="2026-11-01")

        # Target count matches current balance (1000 Pack = 6000 Pcs) and valuation rate (1000)
        sr = frappe.get_doc({
            "doctype": "Stock Reconciliation",
            "company": self.company,
            "purpose": "Stock Reconciliation",
            "posting_date": "2026-11-15",
            "posting_time": "12:00:00",
            "set_posting_time": 1,
            "items": [{
                "item_code": item,
                "warehouse": self.warehouse,
                "custom_uom": "Pack",
                "custom_qty_after": 1000.0,
                "valuation_rate": 1000.0,
            }],
        })
        confirm_count_rows(sr)
        # Draft save succeeds (blind count rows kept intact)
        sr.insert()
        self.track_sr(sr)
        frappe.db.commit()

        # Submit raises EmptyStockReconciliationItemsError
        with self.assertRaises(EmptyStockReconciliationItemsError):
            sr.submit()

    def test_15_refresh_reload_docstatus_1_and_2_does_not_mutate(self):
        """Reloading submitted (docstatus=1) or cancelled (docstatus=2) doc does not mutate modified."""
        item = self.make_test_item("C15", stock_uom="Pcs", pack_factor=6.0)
        self.make_stock_entry(item, 6000.0, 1000.0, posting_date="2026-11-01")

        sr = frappe.get_doc({
            "doctype": "Stock Reconciliation",
            "company": self.company,
            "purpose": "Stock Reconciliation",
            "posting_date": "2026-11-15",
            "posting_time": "12:00:00",
            "set_posting_time": 1,
            "items": [{
                "item_code": item,
                "warehouse": self.warehouse,
                "custom_uom": "Pack",
                "custom_qty_after": 1056.0,
                "valuation_rate": 1000.0,
            }],
        })
        confirm_count_rows(sr)
        sr.insert()
        self.track_sr(sr)
        sr.submit()
        frappe.db.commit()

        sr.reload()
        mod_before = sr.modified

        sr.reload()
        self.assertEqual(sr.modified, mod_before)

        # Non-mutating apply_to_doc simulation
        apply_to_doc(sr)
        self.assertEqual(sr.modified, mod_before)

    def test_16_non_fixture_sentinel_survives_cleanup(self):
        """A non-fixture sentinel Item and transaction survive suite cleanup without being touched."""
        # Fresh unique name: never reuse (or later delete) a record this test did not create.
        sentinel_item = f"ITEM-SENTINEL-W49-{frappe.generate_hash(length=8)}"
        self.assertFalse(frappe.db.exists("Item", sentinel_item), "sentinel item name must be unused")
        sentinel_se = None
        try:
            # 1. Create sentinel item directly without tracking
            frappe.get_doc({
                "doctype": "Item",
                "item_code": sentinel_item,
                "item_name": sentinel_item,
                "item_group": "All Item Groups",
                "stock_uom": "Pcs",
                "is_stock_item": 1,
            }).insert()

            # 2. Create stock transaction for sentinel
            se = frappe.get_doc({
                "doctype": "Stock Entry",
                "stock_entry_type": "Material Receipt",
                "company": self.company,
                "posting_date": "2026-11-01",
                "posting_time": "08:00:00",
                "set_posting_time": 1,
                "items": [{
                    "item_code": sentinel_item,
                    "t_warehouse": self.warehouse,
                    "qty": 10.0,
                    "basic_rate": 500.0,
                    "uom": "Pcs",
                    "conversion_factor": 1.0,
                    "stock_uom": "Pcs",
                }],
            })
            se.insert()
            sentinel_se = se.name  # tracked before submit so a failed submit still cleans it up
            se.submit()
            frappe.db.commit()

            # 3. Create regular test item and doc, tracked
            tracked_item = self.make_test_item("C16", stock_uom="Pcs", pack_factor=6.0)
            tracked_se = self.make_stock_entry(tracked_item, 60.0, 100.0)

            # 4. Trigger suite cleanup
            self.tearDown()

            # 5. Assert that sentinel SURVIVED
            self.assertTrue(frappe.db.exists("Item", sentinel_item), "Sentinel Item must survive cleanup")
            self.assertTrue(frappe.db.exists("Stock Entry", sentinel_se), "Sentinel Stock Entry must survive cleanup")
            sle_count = frappe.db.count("Stock Ledger Entry", {"voucher_no": sentinel_se, "is_cancelled": 0})
            self.assertEqual(sle_count, 1, "Sentinel SLE must survive cleanup")

            # Assert that tracked fixture was indeed deleted
            self.assertFalse(frappe.db.exists("Item", tracked_item), "Tracked fixture item must be deleted")
            self.assertFalse(frappe.db.exists("Stock Entry", tracked_se.name), "Tracked fixture Stock Entry must be deleted")

        finally:
            # Explicit scoped cleanup of ONLY the records this test created, by exact name.
            if sentinel_se:
                self._cleanup_records([("Stock Entry", sentinel_se)], [sentinel_item])
            else:
                self._cleanup_records([], [sentinel_item])
            frappe.db.commit()
