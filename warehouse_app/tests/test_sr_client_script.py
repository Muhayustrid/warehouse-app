# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto and contributors
# For license information, please see license.txt

"""Functional test wrapper for Stock Reconciliation client script.

Executes warehouse_app/tests/sr_client_script.test.mjs under Node.js --test.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

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

# Setup stock_ledger stub if not already present
for mod_name in ["erpnext", "erpnext.stock", "erpnext.stock.stock_ledger"]:
    if mod_name not in sys.modules:
        m = ModuleType(mod_name)
        m.__path__ = []
        sys.modules[mod_name] = m
_stock_ledger = sys.modules["erpnext.stock.stock_ledger"]
if not hasattr(_stock_ledger, "get_previous_sle"):
    _stock_ledger.get_previous_sle = MagicMock(return_value=None)


@unittest.skipUnless(shutil.which("node"), "Node.js is required for client script tests")
class TestSrClientScript(unittest.TestCase):
    def test_sr_client_script_node_suite(self):
        """Run Node test runner against public/js/stock_reconciliation.js."""
        mjs_path = _p.parent / "sr_client_script.test.mjs"
        self.assertTrue(mjs_path.is_file(), f"Missing test runner: {mjs_path}")
        app_js_path = _p.parents[1] / "public" / "js" / "stock_reconciliation.js"
        self.assertTrue(app_js_path.is_file(), f"Missing app script: {app_js_path}")

        # Syntax validation via node --check
        check_proc = subprocess.run(
            ["node", "--check", str(app_js_path)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            check_proc.returncode,
            0,
            f"node --check failed:\n{check_proc.stderr}",
        )

        env = os.environ.copy()
        env["SR_SCRIPT"] = str(app_js_path)
        env["NATIVE_SR_SCRIPT"] = str(_p.parent / "fixtures" / "native_stock_reconciliation.js")

        proc = subprocess.run(
            ["node", "--test", str(mjs_path)],
            env=env,
            capture_output=True,
            text=True,
        )

        if proc.returncode != 0:
            self.fail(
                f"Node test runner failed with exit code {proc.returncode}:\n"
                f"--- stdout ---\n{proc.stdout}\n"
                f"--- stderr ---\n{proc.stderr}"
            )


if __name__ == "__main__":
    unittest.main()
