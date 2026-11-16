# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto and contributors
# For license information, please see license.txt

"""Stock Reconciliation class extension.

Subclasses native StockReconciliation and overrides validate_posting_time
to apply per-UOM conversion after posting_time is final and before serial/batch
bundles are set.
"""

import frappe
from erpnext.stock.doctype.stock_reconciliation.stock_reconciliation import (
	StockReconciliation,
)

from warehouse_app.sr_uom import apply_to_doc

DESK_SAVE = "frappe.desk.form.save.savedocs"


class StockReconciliationUOM(StockReconciliation):
	def validate_posting_time(self):
		super().validate_posting_time()
		apply_to_doc(self)

	def remove_items_with_no_change(self):
		# POSNext keeps no-change rows on draft save (blind outlet count); a Desk form
		# save by a user allowed to see system stock drops them right away.
		if self.docstatus == 0 and _desk_save_by_stock_viewer():
			return StockReconciliation.remove_items_with_no_change(self)
		return super().remove_items_with_no_change()


def _desk_save_by_stock_viewer() -> bool:
	if getattr(frappe.local, "form_dict", None) is None or frappe.form_dict.get("cmd") != DESK_SAVE:
		return False
	if "pos_next" not in frappe.get_installed_apps():
		return True
	from pos_next.overrides.stock_reconciliation import is_hq_user
	from pos_next.stock_opname_setup import OUTLET_ROLES

	# Only outlet (cashier) users count blind; everyone else may see the dropped rows.
	return is_hq_user() or not set(frappe.get_roles()) & set(OUTLET_ROLES)
