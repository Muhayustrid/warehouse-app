# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto and contributors
# For license information, please see license.txt

"""Stock Reconciliation class extension.

Subclasses native StockReconciliation and overrides validate_posting_time
to apply per-UOM conversion after posting_time is final and before serial/batch
bundles are set.
"""

from erpnext.stock.doctype.stock_reconciliation.stock_reconciliation import (
	StockReconciliation,
)

from warehouse_app.sr_uom import apply_to_doc


class StockReconciliationUOM(StockReconciliation):
	def validate_posting_time(self):
		super().validate_posting_time()
		apply_to_doc(self)
