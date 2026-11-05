# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto and contributors
# For license information, please see license.txt

"""Unit tests for Stock Reconciliation script retirement and idempotent install.

Verifies:
1. Calling upgrade.apply() twice creates custom_count_confirmation exactly once.
2. W23 (warehouse-app-w23-stock-reconciliation-uom) and W26 (warehouse-app-w26-stock-count-import)
   are disabled (enabled=0), not deleted.
3. Conflicting Server Script (sr_auto_populate_before_after) is disabled (disabled=1), not deleted.
4. Unrelated Client Scripts and Server Scripts remain untouched.
5. Calling upgrade.apply() a second time does not re-enable retired scripts.
"""

from pathlib import Path
import sys
import unittest
from types import ModuleType
from unittest.mock import MagicMock, patch

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
if not getattr(sys.modules.get("frappe"), "__file__", None):
    frappe_stub.setup_frappe_stub()
import frappe

from warehouse_app import upgrade
from warehouse_app.sr_uom import SR_CONFIRMATION_FIELD


class TestSrInstall(unittest.TestCase):
    def setUp(self):
        # In-memory document store to simulate Frappe DB
        self.docs = {
            "Custom Field": {},
            "Client Script": {},
            "Server Script": {},
        }

        def _make_doc(d):
            doc = frappe._dict(d)
            doc.flags = frappe._dict()
            doc.save = lambda: doc
            return doc

        # Seed pre-existing scripts
        self.docs["Client Script"]["warehouse-app-w23-stock-reconciliation-uom"] = _make_doc({
            "doctype": "Client Script",
            "name": "warehouse-app-w23-stock-reconciliation-uom",
            "dt": "Stock Reconciliation",
            "enabled": 1,
            "script": upgrade.SR_SCRIPT_MARKER + "\nconsole.log('w23');",
            "view": "Form",
        })
        self.docs["Client Script"]["warehouse-app-w26-stock-count-import"] = _make_doc({
            "doctype": "Client Script",
            "name": "warehouse-app-w26-stock-count-import",
            "dt": "Stock Reconciliation",
            "enabled": 1,
            "script": upgrade.SR_FORM_SCRIPT_MARKER + "\nconsole.log('w26');",
            "view": "Form",
        })
        self.docs["Client Script"]["custom-unrelated-sr-script"] = _make_doc({
            "doctype": "Client Script",
            "name": "custom-unrelated-sr-script",
            "dt": "Stock Reconciliation",
            "enabled": 1,
            "script": "// unrelated custom script\nconsole.log('custom');",
            "view": "Form",
        })
        self.docs["Server Script"]["sr_auto_populate_before_after"] = _make_doc({
            "doctype": "Server Script",
            "name": "sr_auto_populate_before_after",
            "disabled": 0,
            "script": "# server script\npass",
        })
        self.docs["Server Script"]["unrelated_server_script"] = _make_doc({
            "doctype": "Server Script",
            "name": "unrelated_server_script",
            "disabled": 0,
            "script": "# other server script\npass",
        })

        self._setup_mock_db()

    def _setup_mock_db(self):
        def mock_exists(dt, name_or_filters=None):
            if isinstance(name_or_filters, dict):
                return bool(mock_get_value(dt, name_or_filters, "name"))
            return name_or_filters in self.docs.get(dt, {})

        def mock_get_value(dt, filters, fieldname="name", as_dict=False):
            table = self.docs.get(dt, {})
            if isinstance(filters, str):
                doc = table.get(filters)
                if not doc:
                    return None
                if as_dict:
                    return doc
                return doc.get(fieldname) if isinstance(fieldname, str) else [doc.get(f) for f in fieldname]

            matches = []
            for doc in table.values():
                matched = True
                for k, v in filters.items():
                    doc_val = doc.get(k)
                    if isinstance(v, tuple) and v[0] == "like":
                        pattern = v[1].replace("%", "")
                        if pattern not in (doc_val or ""):
                            matched = False
                            break
                    elif isinstance(v, (list, tuple)) and v[0] == "in":
                        if doc_val not in v[1]:
                            matched = False
                            break
                    elif doc_val != v:
                        matched = False
                        break
                if matched:
                    matches.append(doc)

            if not matches:
                return None
            doc = matches[0]
            if as_dict:
                return doc
            if isinstance(fieldname, str):
                return doc.get(fieldname)
            return [doc.get(f) for f in fieldname]

        def mock_get_all(dt, filters=None, pluck=None, fields=None, **kwargs):
            table = self.docs.get(dt, {})
            results = []
            for doc in table.values():
                matched = True
                if filters:
                    for k, v in filters.items():
                        doc_val = doc.get(k)
                        if isinstance(v, tuple) and v[0] == "like":
                            pattern = v[1].replace("%", "")
                            if pattern not in (doc_val or ""):
                                matched = False
                                break
                        elif isinstance(v, (list, tuple)) and v[0] == "in":
                            if doc_val not in v[1]:
                                matched = False
                                break
                        elif doc_val != v:
                            matched = False
                            break
                if matched:
                    if pluck:
                        results.append(doc.get(pluck))
                    elif fields:
                        results.append({f: doc.get(f) for f in fields})
                    else:
                        results.append(doc)
            return results

        def mock_get_doc(*args, **kwargs):
            if len(args) == 2:
                dt, name = args
                doc = self.docs.get(dt, {}).get(name)
                if doc:
                    if not hasattr(doc, "flags") or doc.flags is None:
                        doc.flags = frappe._dict()
                    if not hasattr(doc, "save"):
                        doc.save = lambda: doc
                return doc
            if len(args) == 1 and isinstance(args[0], dict):
                d = frappe._dict(args[0])
                def insert():
                    dt = d.doctype
                    name = d.name or f"{d.dt}-{d.fieldname}"
                    d.name = name
                    self.docs[dt][name] = d
                    return d
                def save():
                    dt = d.doctype
                    self.docs[dt][d.name] = d
                    return d
                d.insert = insert
                d.save = save
                d.flags = frappe._dict()
                return d
            return None

        def mock_delete_doc(dt, name, **kwargs):
            if name in self.docs.get(dt, {}):
                del self.docs[dt][name]

        frappe.db.exists = MagicMock(side_effect=mock_exists)
        frappe.db.get_value = MagicMock(side_effect=mock_get_value)
        frappe.get_all = MagicMock(side_effect=mock_get_all)
        frappe.get_doc = MagicMock(side_effect=mock_get_doc)
        frappe.delete_doc = MagicMock(side_effect=mock_delete_doc)
        frappe.clear_cache = MagicMock()
        frappe.cache = MagicMock()
        frappe.cache.delete_key = MagicMock()
        frappe.get_meta = MagicMock(return_value=frappe._dict(has_field=MagicMock(return_value=False)))

    def test_apply_twice_disables_w23_w26_and_server_script_idempotently(self):
        """upgrade.apply() disables W23/W26 and server script without deleting, and leaves unrelated scripts intact."""
        # First run
        upgrade.apply()

        # 1. Custom field custom_count_confirmation exists once
        conf_fields = [
            f for f in self.docs["Custom Field"].values()
            if f.get("dt") == "Stock Reconciliation Item" and f.get("fieldname") == SR_CONFIRMATION_FIELD
        ]
        self.assertEqual(len(conf_fields), 1)

        # 2. W23 and W26 are disabled (enabled=0), NOT deleted
        self.assertIn("warehouse-app-w23-stock-reconciliation-uom", self.docs["Client Script"])
        w23 = self.docs["Client Script"]["warehouse-app-w23-stock-reconciliation-uom"]
        self.assertEqual(w23.enabled, 0, "W23 must be disabled (enabled=0)")

        self.assertIn("warehouse-app-w26-stock-count-import", self.docs["Client Script"])
        w26 = self.docs["Client Script"]["warehouse-app-w26-stock-count-import"]
        self.assertEqual(w26.enabled, 0, "W26 must be disabled (enabled=0)")

        # 3. Server script sr_auto_populate_before_after is disabled (disabled=1), NOT deleted
        self.assertIn("sr_auto_populate_before_after", self.docs["Server Script"])
        ss = self.docs["Server Script"]["sr_auto_populate_before_after"]
        self.assertEqual(ss.disabled, 1, "Server Script must be disabled (disabled=1)")

        # 4. Unrelated scripts are untouched
        unrelated_cs = self.docs["Client Script"]["custom-unrelated-sr-script"]
        self.assertEqual(unrelated_cs.enabled, 1, "Unrelated Client Script must remain enabled=1")

        unrelated_ss = self.docs["Server Script"]["unrelated_server_script"]
        self.assertEqual(unrelated_ss.disabled, 0, "Unrelated Server Script must remain disabled=0")

        # Second run (idempotency check)
        upgrade.apply()

        # No duplicate custom field
        conf_fields_2 = [
            f for f in self.docs["Custom Field"].values()
            if f.get("dt") == "Stock Reconciliation Item" and f.get("fieldname") == SR_CONFIRMATION_FIELD
        ]
        self.assertEqual(len(conf_fields_2), 1)

        # Retired scripts are NOT re-enabled
        self.assertEqual(w23.enabled, 0, "Second apply() must not re-enable W23")
        self.assertEqual(w26.enabled, 0, "Second apply() must not re-enable W26")
        self.assertEqual(ss.disabled, 1, "Second apply() must not re-enable Server Script")

        # Unrelated scripts still untouched
        self.assertEqual(unrelated_cs.enabled, 1)
        self.assertEqual(unrelated_ss.disabled, 0)


if __name__ == "__main__":
    unittest.main()
