# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto and contributors
# For license information, please see license.txt

"""Security and access unit tests for warehouse_app Stock Reconciliation routes.

Verifies Task 4 public-route contract:
1. Public routes: get_items, compute_row, download_stock_count_template, upload_stock_count.
2. Outlet-only and outlet+Stock User denial before protected reads (native_get_items,
   Bin actual_qty, ledger_qty, get_previous_sle, parse/validate_count_rows).
3. Equality oracle denial: test_import_equal_and_unequal_counts_both_deny_outlet.
4. Empty context rejection before protected stock reads.
5. pos_next broken helper fails closed (never falls back to standalone).
6. HQ role with denied Warehouse / Company context.
7. Mismatched company rejection.
8. Multiple imported warehouses with one denied aborts all before any ledger read.
9. Standalone mode (without pos_next): native action + SR read + Warehouse/Company scope,
   no HQ membership requirement.
10. Standalone denial when lacking SR action, SR read, or context read.
11. Direct warehouse dotted paths and pos_next delegate parity.
"""

import base64
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
if not getattr(sys.modules.get("frappe"), "__file__", None):
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

# Setup stock_ledger stub
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

# Setup desk utils for download template
for mod_name in ["frappe.desk", "frappe.desk.utils"]:
    if mod_name not in sys.modules:
        m = ModuleType(mod_name)
        m.__path__ = []
        sys.modules[mod_name] = m
_desk_utils = sys.modules["frappe.desk.utils"]
if not hasattr(_desk_utils, "provide_binary_file"):
    _desk_utils.provide_binary_file = MagicMock()

# Setup pos_next mock override module matching helper.diff
for mod_name in [
    "pos_next",
    "pos_next.overrides",
    "pos_next.overrides.stock_reconciliation",
]:
    if mod_name not in sys.modules:
        m = ModuleType(mod_name)
        m.__path__ = []
        sys.modules[mod_name] = m
_pos_next_sr = sys.modules["pos_next.overrides.stock_reconciliation"]

HQ_ROLES = {"Stock Manager", "System Manager", "Administrator"}

def _mock_is_hq_user(user=None):
    roles = set(frappe.get_roles(user))
    return bool(roles & HQ_ROLES)

def _mock_assert_system_stock_access(warehouse=None, company=None, user=None):
    user = user or frappe.session.user
    if (
        user == "Guest"
        or not frappe.db.exists("User", {"name": user, "enabled": 1})
        or not _mock_is_hq_user(user)
        or not frappe.has_permission("Stock Reconciliation", "read", user=user)
    ):
        frappe.throw("Not permitted to read system stock.", frappe.PermissionError)
    if warehouse is None and company is None:
        return
    if not warehouse or not frappe.db.exists("Warehouse", warehouse):
        frappe.throw("A permitted warehouse is required.", frappe.PermissionError)
    warehouse_doc = frappe.get_doc("Warehouse", warehouse)
    if not getattr(warehouse_doc, "company", None) or (company and company != warehouse_doc.company):
        frappe.throw("Warehouse and company do not match.", frappe.PermissionError)
    if not warehouse_doc.has_permission("read", user=user) or not frappe.get_doc(
        "Company", warehouse_doc.company
    ).has_permission("read", user=user):
        frappe.throw("Not permitted to read this warehouse or company.", frappe.PermissionError)

_pos_next_sr.assert_system_stock_access = _mock_assert_system_stock_access
_pos_next_sr.is_hq_user = _mock_is_hq_user
_pos_next_sr.HQ_ROLES = HQ_ROLES

def _mock_pos_next_get_items(warehouse, posting_date, posting_time, company, item_code=None, ignore_empty_stock=False):
    _mock_assert_system_stock_access(warehouse or "", company)
    if "warehouse_app" in frappe.get_installed_apps():
        from warehouse_app.warehouse_app.stock_reconciliation import get_items as delegate
    else:
        from erpnext.stock.doctype.stock_reconciliation.stock_reconciliation import get_items as delegate
    return delegate(warehouse, posting_date, posting_time, company, item_code, ignore_empty_stock)

_pos_next_sr.get_items = _mock_pos_next_get_items

from warehouse_app.warehouse_app import stock_reconciliation, sr_import


class TestSrAccessSecurity(unittest.TestCase):
    def setUp(self):
        frappe.session.user = "test_user@example.com"
        frappe.db.exists = MagicMock(return_value=True)
        frappe.get_installed_apps = MagicMock(return_value=["frappe", "erpnext", "warehouse_app", "pos_next"])
        frappe.get_roles = MagicMock(return_value=["Stock User"])
        frappe.has_permission = MagicMock(return_value=True)

        _native_sr.get_items.reset_mock()
        _stock_ledger.get_previous_sle.reset_mock()
        _desk_utils.provide_binary_file.reset_mock()

        # Faithful document mock
        self.wh_doc = frappe._dict(
            name="Stores - C",
            company="Company A",
            is_group=0,
            disabled=0,
        )
        self.wh_doc.has_permission = MagicMock(return_value=True)

        self.comp_doc = frappe._dict(
            name="Company A",
        )
        self.comp_doc.has_permission = MagicMock(return_value=True)

        def mock_get_doc(doctype, name=None):
            if isinstance(doctype, dict):
                return frappe._dict(doctype)
            if doctype == "Warehouse":
                if name == "Stores - C":
                    return self.wh_doc
                d = frappe._dict(name=name, company="Company A", is_group=0, disabled=0)
                d.has_permission = MagicMock(return_value=True)
                return d
            if doctype == "Company":
                return self.comp_doc
            d = frappe._dict(name=name)
            d.has_permission = MagicMock(return_value=True)
            return d

        frappe.get_doc = MagicMock(side_effect=mock_get_doc)

    def test_get_items_outlet_only_denied_before_native_fetch(self):
        """Outlet user calling get_items is denied before native_get_items is called."""
        frappe.get_roles.return_value = ["POS User"]
        with self.assertRaises(frappe.PermissionError):
            stock_reconciliation.get_items(
                warehouse="Stores - C",
                posting_date="2026-11-03",
                posting_time="10:00:00",
                company="Company A",
            )
        _native_sr.get_items.assert_not_called()

    def test_get_items_outlet_plus_stock_user_denied_before_native_fetch(self):
        """Outlet user with Stock User role is still denied when pos_next is installed."""
        frappe.get_roles.return_value = ["POS User", "Stock User"]
        with self.assertRaises(frappe.PermissionError):
            stock_reconciliation.get_items(
                warehouse="Stores - C",
                posting_date="2026-11-03",
                posting_time="10:00:00",
                company="Company A",
            )
        _native_sr.get_items.assert_not_called()

    def test_compute_row_outlet_only_denied_before_ledger_read(self):
        """Outlet user calling compute_row is denied before ledger_qty/get_previous_sle."""
        frappe.get_roles.return_value = ["POS User"]
        with patch("warehouse_app.sr_uom.ledger_qty") as mock_ledger:
            with self.assertRaises(frappe.PermissionError):
                stock_reconciliation.compute_row(
                    item_code="ITEM-1",
                    warehouse="Stores - C",
                    posting_date="2026-11-03",
                    posting_time="10:00:00",
                    uom="Nos",
                )
            mock_ledger.assert_not_called()
        _stock_ledger.get_previous_sle.assert_not_called()

    def test_compute_row_outlet_plus_stock_user_denied_before_ledger_read(self):
        """Mixed outlet + Stock User calling compute_row is denied before ledger read."""
        frappe.get_roles.return_value = ["POS User", "Stock User"]
        with patch("warehouse_app.sr_uom.ledger_qty") as mock_ledger:
            with self.assertRaises(frappe.PermissionError):
                stock_reconciliation.compute_row(
                    item_code="ITEM-1",
                    warehouse="Stores - C",
                    posting_date="2026-11-03",
                    posting_time="10:00:00",
                    uom="Nos",
                )
            mock_ledger.assert_not_called()
        _stock_ledger.get_previous_sle.assert_not_called()

    def test_download_template_outlet_only_denied_before_bin_read(self):
        """Outlet user calling download_stock_count_template is denied before Bin read."""
        frappe.get_roles.return_value = ["POS User"]
        with patch("warehouse_app.warehouse_app.sr_import.build_count_rows") as mock_build:
            with self.assertRaises(frappe.PermissionError):
                sr_import.download_stock_count_template(warehouse="Stores - C")
            mock_build.assert_not_called()
        _desk_utils.provide_binary_file.assert_not_called()

    def test_download_template_outlet_plus_stock_user_denied_before_bin_read(self):
        """Mixed outlet + Stock User calling download_stock_count_template is denied."""
        frappe.get_roles.return_value = ["POS User", "Stock User"]
        with patch("warehouse_app.warehouse_app.sr_import.build_count_rows") as mock_build:
            with self.assertRaises(frappe.PermissionError):
                sr_import.download_stock_count_template(warehouse="Stores - C")
            mock_build.assert_not_called()
        _desk_utils.provide_binary_file.assert_not_called()

    def test_upload_outlet_only_denied_before_parsing_and_validate(self):
        """Outlet user calling upload_stock_count is denied before parsing and validate."""
        frappe.get_roles.return_value = ["POS User"]
        with patch("warehouse_app.warehouse_app.sr_import.parse_count_content") as mock_parse, \
             patch("warehouse_app.warehouse_app.sr_import.validate_count_rows") as mock_val:
            with self.assertRaises(frappe.PermissionError):
                sr_import.upload_stock_count(
                    filename="stock.csv",
                    data=base64.b64encode(b"header").decode("ascii"),
                    company="Company A",
                )
            mock_parse.assert_not_called()
            mock_val.assert_not_called()

    def test_upload_outlet_plus_stock_user_denied_before_parsing_and_validate(self):
        """Mixed outlet + Stock User calling upload_stock_count is denied before parse."""
        frappe.get_roles.return_value = ["POS User", "Stock User"]
        with patch("warehouse_app.warehouse_app.sr_import.parse_count_content") as mock_parse, \
             patch("warehouse_app.warehouse_app.sr_import.validate_count_rows") as mock_val:
            with self.assertRaises(frappe.PermissionError):
                sr_import.upload_stock_count(
                    filename="stock.csv",
                    data=base64.b64encode(b"header").decode("ascii"),
                    company="Company A",
                )
            mock_parse.assert_not_called()
            mock_val.assert_not_called()

    def test_import_equal_and_unequal_counts_both_deny_outlet(self):
        """Neither matched count nor row omission may act as an equality oracle.

        Both files (one with count matching ledger, one with count differing)
        are denied unconditionally for outlet user at the role precheck.
        """
        frappe.get_roles.return_value = ["POS User"]

        csv_equal = "Item Code,Warehouse,Counted Qty,UOM\nITEM-1,Stores - C,10,Nos\n"
        csv_unequal = "Item Code,Warehouse,Counted Qty,UOM\nITEM-1,Stores - C,999,Nos\n"

        with patch("warehouse_app.warehouse_app.sr_import.validate_count_rows") as mock_val:
            with self.assertRaises(frappe.PermissionError):
                sr_import.upload_stock_count(
                    filename="equal.csv",
                    data=base64.b64encode(csv_equal.encode("utf-8")).decode("ascii"),
                    company="Company A",
                )
            mock_val.assert_not_called()

            with self.assertRaises(frappe.PermissionError):
                sr_import.upload_stock_count(
                    filename="unequal.csv",
                    data=base64.b64encode(csv_unequal.encode("utf-8")).decode("ascii"),
                    company="Company A",
                )
            mock_val.assert_not_called()

    def test_empty_context_denied_before_stock_access(self):
        """Empty or missing warehouse context denies before any stock read."""
        frappe.get_roles.return_value = ["Stock Manager"]  # HQ role

        # get_items with empty warehouse
        with self.assertRaises(frappe.PermissionError):
            stock_reconciliation.get_items(
                warehouse="",
                posting_date="2026-11-03",
                posting_time="10:00:00",
                company="Company A",
            )
        _native_sr.get_items.assert_not_called()

        # compute_row with empty warehouse
        with patch("warehouse_app.sr_uom.ledger_qty") as mock_ledger:
            with self.assertRaises(frappe.PermissionError):
                stock_reconciliation.compute_row(
                    item_code="ITEM-1",
                    warehouse="",
                    posting_date="2026-11-03",
                    posting_time="10:00:00",
                    uom="Nos",
                )
            mock_ledger.assert_not_called()

        # download_stock_count_template with empty warehouse
        with patch("warehouse_app.warehouse_app.sr_import.build_count_rows") as mock_build:
            with self.assertRaises(frappe.PermissionError):
                sr_import.download_stock_count_template(warehouse="")
            mock_build.assert_not_called()

        # upload_stock_count with row having empty warehouse rejects before ledger
        csv_empty_wh = "Item Code,Warehouse,Counted Qty,UOM\nITEM-1,,10,Nos\n"
        with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
            sr_import.upload_stock_count(
                filename="empty_wh.csv",
                data=base64.b64encode(csv_empty_wh.encode("utf-8")).decode("ascii"),
                company="Company A",
            )
        _stock_ledger.get_previous_sle.assert_not_called()

    def test_pos_next_broken_helper_fails_closed(self):
        """When pos_next is installed but helper fails to import, fail closed without fallback."""
        frappe.get_roles.return_value = ["Stock Manager"]
        with patch.dict(sys.modules, {"pos_next.overrides.stock_reconciliation": None}):
            # get_items fails closed
            with self.assertRaises(frappe.PermissionError):
                stock_reconciliation.get_items(
                    warehouse="Stores - C",
                    posting_date="2026-11-03",
                    posting_time="10:00:00",
                    company="Company A",
                )
            _native_sr.get_items.assert_not_called()

            # compute_row fails closed
            with patch("warehouse_app.sr_uom.ledger_qty") as mock_ledger:
                with self.assertRaises(frappe.PermissionError):
                    stock_reconciliation.compute_row(
                        item_code="ITEM-1",
                        warehouse="Stores - C",
                        posting_date="2026-11-03",
                        posting_time="10:00:00",
                        uom="Nos",
                    )
                mock_ledger.assert_not_called()

    def test_hq_role_denied_warehouse_context(self):
        """HQ user denied read on Warehouse is rejected."""
        frappe.get_roles.return_value = ["Stock Manager"]
        self.wh_doc.has_permission.return_value = False

        with self.assertRaises(frappe.PermissionError):
            stock_reconciliation.get_items(
                warehouse="Stores - C",
                posting_date="2026-11-03",
                posting_time="10:00:00",
                company="Company A",
            )
        _native_sr.get_items.assert_not_called()

    def test_hq_role_denied_company_context(self):
        """HQ user denied read on Company is rejected."""
        frappe.get_roles.return_value = ["Stock Manager"]
        self.comp_doc.has_permission.return_value = False

        with self.assertRaises(frappe.PermissionError):
            stock_reconciliation.get_items(
                warehouse="Stores - C",
                posting_date="2026-11-03",
                posting_time="10:00:00",
                company="Company A",
            )
        _native_sr.get_items.assert_not_called()

    def test_mismatched_company_denied(self):
        """Warehouse belonging to Company A rejected if Company B is requested."""
        frappe.get_roles.return_value = ["Stock Manager"]
        with self.assertRaises(frappe.PermissionError):
            stock_reconciliation.get_items(
                warehouse="Stores - C",
                posting_date="2026-11-03",
                posting_time="10:00:00",
                company="Wrong Company",
            )
        _native_sr.get_items.assert_not_called()

    def test_multiple_imported_warehouses_one_denied_preflight_aborts_before_ledger(self):
        """All imported warehouse contexts are preflighted before ANY row's ledger evaluation."""
        frappe.get_roles.return_value = ["Stock Manager"]

        wh_ok = frappe._dict(name="WH-OK", company="Company A")
        wh_ok.has_permission = MagicMock(return_value=True)

        wh_denied = frappe._dict(name="WH-DENIED", company="Company A")
        wh_denied.has_permission = MagicMock(return_value=False)

        def mock_get_doc_multi(doctype, name=None):
            if doctype == "Warehouse":
                if name == "WH-OK":
                    return wh_ok
                if name == "WH-DENIED":
                    return wh_denied
            if doctype == "Company":
                return self.comp_doc
            return frappe._dict(name=name)

        frappe.get_doc.side_effect = mock_get_doc_multi

        csv_content = (
            "Item Code,Warehouse,Counted Qty,UOM\n"
            "ITEM-1,WH-OK,10,Nos\n"
            "ITEM-2,WH-DENIED,20,Nos\n"
        )

        with self.assertRaises(frappe.PermissionError):
            sr_import.upload_stock_count(
                filename="multi_wh.csv",
                data=base64.b64encode(csv_content.encode("utf-8")).decode("ascii"),
                company="Company A",
            )
        # Crucial security assertion: NO row reached get_previous_sle
        _stock_ledger.get_previous_sle.assert_not_called()

    def test_standalone_authorized_without_pos_next(self):
        """Without pos_next, native action + SR read + Warehouse/Company scope allows access without HQ role."""
        frappe.get_installed_apps.return_value = ["frappe", "erpnext", "warehouse_app"]
        frappe.get_roles.return_value = ["Stock User"]  # Not HQ role
        frappe.has_permission.return_value = True

        # get_items succeeds
        _native_sr.get_items.return_value = []
        res = stock_reconciliation.get_items(
            warehouse="Stores - C",
            posting_date="2026-11-03",
            posting_time="10:00:00",
            company="Company A",
        )
        self.assertEqual(res, [])
        _native_sr.get_items.assert_called_once()

    def test_standalone_denied_without_action_or_read_permission(self):
        """Without pos_next, user lacking action or read permission on SR is denied."""
        frappe.get_installed_apps.return_value = ["frappe", "erpnext", "warehouse_app"]
        frappe.get_roles.return_value = ["Stock User"]

        def mock_has_perm(doctype, ptype="read", doc=None, user=None):
            if doctype == "Stock Reconciliation" and ptype == "write":
                return False
            return True

        frappe.has_permission.side_effect = mock_has_perm

        with self.assertRaises(frappe.PermissionError):
            stock_reconciliation.get_items(
                warehouse="Stores - C",
                posting_date="2026-11-03",
                posting_time="10:00:00",
                company="Company A",
            )
        _native_sr.get_items.assert_not_called()

    def test_standalone_denied_without_warehouse_read_scope(self):
        """Without pos_next, user lacking read on Warehouse is denied."""
        frappe.get_installed_apps.return_value = ["frappe", "erpnext", "warehouse_app"]
        frappe.get_roles.return_value = ["Stock User"]
        self.wh_doc.has_permission.return_value = False

        with self.assertRaises(frappe.PermissionError):
            stock_reconciliation.get_items(
                warehouse="Stores - C",
                posting_date="2026-11-03",
                posting_time="10:00:00",
                company="Company A",
            )
        _native_sr.get_items.assert_not_called()

    def test_direct_dotted_paths_and_pos_next_delegation(self):
        """Direct warehouse dotted path and pos_next delegate path both enforce guard."""
        # Outlet user calling direct warehouse path
        frappe.get_roles.return_value = ["POS User"]
        with self.assertRaises(frappe.PermissionError):
            stock_reconciliation.get_items(
                warehouse="Stores - C",
                posting_date="2026-11-03",
                posting_time="10:00:00",
                company="Company A",
            )
        _native_sr.get_items.assert_not_called()

        # Outlet user calling pos_next override path
        with self.assertRaises(frappe.PermissionError):
            _pos_next_sr.get_items(
                warehouse="Stores - C",
                posting_date="2026-11-03",
                posting_time="10:00:00",
                company="Company A",
            )
        _native_sr.get_items.assert_not_called()

        # Authorized HQ user calling both paths succeeds
        frappe.get_roles.return_value = ["Stock Manager"]
        _native_sr.get_items.return_value = []
        res1 = stock_reconciliation.get_items(
            warehouse="Stores - C",
            posting_date="2026-11-03",
            posting_time="10:00:00",
            company="Company A",
        )
        self.assertEqual(res1, [])

        res2 = _pos_next_sr.get_items(
            warehouse="Stores - C",
            posting_date="2026-11-03",
            posting_time="10:00:00",
            company="Company A",
        )
        self.assertEqual(res2, [])
        self.assertEqual(_native_sr.get_items.call_count, 2)


if __name__ == "__main__":
    unittest.main()
