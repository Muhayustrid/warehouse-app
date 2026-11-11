import frappe
from frappe import _
from frappe.model.document import Document


class PurchaseReceiptQRLabel(Document):
	def validate(self):
		row = frappe.db.get_value(
			"Purchase Receipt Item", self.purchase_receipt_item,
			["parent", "item_code", "batch_no", "serial_and_batch_bundle"], as_dict=True,
		)
		serial = frappe.db.get_value(
			"Product QR Serial", self.product_qr_serial, ["item_code", "batch_no"], as_dict=True,
		)
		if not row or row.parent != self.purchase_receipt or not serial or serial.item_code != row.item_code:
			frappe.throw(_("Product QR Serial must belong to the Purchase Receipt Item"))
		batch_numbers = {row.batch_no} if row.batch_no else set()
		if row.serial_and_batch_bundle:
			batch_numbers.update(filter(None, frappe.get_all(
				"Serial and Batch Entry", filters={"parent": row.serial_and_batch_bundle},
				pluck="batch_no", limit_page_length=0,
			)))
		if len(batch_numbers) > 1 or (serial.batch_no or None) != next(iter(batch_numbers), None):
			frappe.throw(_("Product QR Serial Batch must match the Purchase Receipt Item"))
		if not self.is_new():
			old = frappe.db.get_value(
				self.doctype, self.name,
				["purchase_receipt", "purchase_receipt_item", "product_qr_serial"], as_dict=True,
			)
			if old and any(self.get(field) != old[field] for field in old):
				frappe.throw(_("Purchase Receipt QR Label cannot be reassigned"))
