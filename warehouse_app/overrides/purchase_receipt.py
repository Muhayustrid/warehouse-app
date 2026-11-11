"""Purchase Receipt labels using the Work Order Product QR serial contract."""

import json
import math
import re
from datetime import date

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import PurchaseReceipt

MAPPING_DOCTYPE = "Purchase Receipt QR Label"
SERIAL_DOCTYPE = "Product QR Serial"
MAX_LABELS = 10000


class WarehousePurchaseReceipt(PurchaseReceipt):
    pass


def _batch_for_row(row):
    batch_numbers = {row.batch_no} if row.batch_no else set()
    if row.serial_and_batch_bundle:
        batch_numbers.update(filter(None, frappe.get_all(
            "Serial and Batch Entry", filters={"parent": row.serial_and_batch_bundle},
            pluck="batch_no", limit_page_length=0,
        )))
    if len(batch_numbers) > 1:
        frappe.throw(_("Baris {0} memiliki lebih dari satu Batch; label QR memerlukan satu Batch.").format(row.idx))
    batch_no = next(iter(batch_numbers), None)
    if not batch_no:
        return None
    batch = frappe.db.get_value("Batch", batch_no, ["name", "item", "manufacturing_date", "expiry_date"], as_dict=True)
    if not batch or batch.item != row.item_code:
        frappe.throw(_("Batch {0} tidak cocok dengan Item pada baris {1}.").format(batch_no, row.idx))
    return batch


def _row_data(pr, row):
    batch = _batch_for_row(row)
    item = frappe.db.get_value("Item", row.item_code, ["item_name", "shelf_life_in_days"], as_dict=True)
    item_name = row.item_name or (item.item_name if item else row.item_code)
    dough_match = re.search(r"\bdough\b", item_name, flags=re.IGNORECASE)
    dough_tail = item_name[dough_match.end():].strip() if dough_match else ""
    mfg = (batch.manufacturing_date if batch else None) or getdate(pr.posting_date)
    exp = (batch.expiry_date if batch else None) or (
        add_days(mfg, int(item.shelf_life_in_days)) if item and item.shelf_life_in_days else None
    )
    qty = flt(row.qty)
    if not math.isfinite(qty) or qty <= 0:
        frappe.throw(_("Quantity baris {0} harus lebih dari nol untuk mencetak label.").format(row.idx))
    return {
        "row": row.name, "sku": row.item_code, "item_name": item_name,
        "item_name_prefix": item_name[:dough_match.end()].strip() if dough_tail else "",
        "item_name_main": dough_tail or item_name, "batch_no": batch.name if batch else None,
        "receipt_date": str(getdate(pr.posting_date)), "expiry_date": str(exp) if exp else None,
        "max_labels": min(MAX_LABELS, max(1, math.ceil(qty - 1e-8))),
    }


def _receipt(name):
    if not name:
        frappe.throw(_("Purchase Receipt wajib dipilih untuk mencetak label."))
    pr = frappe.get_doc("Purchase Receipt", name)
    pr.check_permission("read")
    if pr.docstatus != 1:
        frappe.throw(_("Submit Purchase Receipt sebelum mencetak label."))
    if not frappe.db.table_exists(SERIAL_DOCTYPE) or not frappe.db.table_exists(MAPPING_DOCTYPE):
        frappe.throw(_("App product_qr dan Purchase Receipt QR Label harus dipasang dan dimigrasi."))
    return pr


@frappe.whitelist()
def get_purchase_receipt_label_data(purchase_receipt_name):
    """Read-only data for the selection dialog; serials are issued by POST only."""
    pr = _receipt(purchase_receipt_name)
    return {"purchase_receipt": pr.name, "items": [_row_data(pr, row) for row in pr.items]}


@frappe.whitelist(methods=["POST"])
def issue_labels(purchase_receipt_name, selections):
    """Issue missing serials once and return the same first N serials on reprint."""
    pr = _receipt(purchase_receipt_name)
    if not frappe.has_permission(SERIAL_DOCTYPE, "create"):
        frappe.throw(_("Tidak ada izin membuat Product QR Serial."), frappe.PermissionError)
    if isinstance(selections, str):
        try:
            selections = json.loads(selections)
        except ValueError:
            frappe.throw(_("Pilihan label tidak valid."))
    if not isinstance(selections, list) or not selections or len(selections) > len(pr.items):
        frappe.throw(_("Pilihan label tidak valid."))
    row_map = {row.name: row for row in pr.items}
    seen = set()
    requested = []
    total = 0
    for selection in selections:
        if not isinstance(selection, dict) or selection.get("row") not in row_map or selection["row"] in seen:
            frappe.throw(_("Baris label tidak valid atau dipilih dua kali."))
        seen.add(selection["row"])
        data = _row_data(pr, row_map[selection["row"]])
        qty = selection.get("qty")
        if isinstance(qty, bool) or not re.fullmatch(r"[1-9][0-9]{0,4}", str(qty or "")):
            frappe.throw(_("Jumlah label harus bilangan bulat positif."))
        qty = int(qty)
        if qty > data["max_labels"]:
            frappe.throw(_("Jumlah label baris {0} melebihi quantity dokumen.").format(row_map[selection["row"]].idx))
        expiry_date = selection.get("expiry_date")
        if not isinstance(expiry_date, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", expiry_date):
            frappe.throw(_("Tanggal EXP wajib diisi pada baris {0}.").format(row_map[selection["row"]].idx))
        try:
            data["expiry_date"] = date.fromisoformat(expiry_date).isoformat()
        except ValueError:
            frappe.throw(_("Tanggal EXP tidak valid pada baris {0}.").format(row_map[selection["row"]].idx))
        total += qty
        requested.append((data, qty))
    if total > MAX_LABELS:
        frappe.throw(_("Jumlah label melebihi batas {0}.").format(MAX_LABELS))

    # Serialize concurrent requests for this receipt, as Work Order label_data does.
    frappe.db.get_value("Purchase Receipt", pr.name, "name", for_update=True)
    result = []
    for data, qty in requested:
        rows = frappe.get_all(
            MAPPING_DOCTYPE,
            filters={"purchase_receipt": pr.name, "purchase_receipt_item": data["row"]},
            fields=["product_qr_serial"], order_by="creation asc, name asc", limit_page_length=0,
        )
        serial_names = [row.product_qr_serial for row in rows]
        if serial_names:
            first = frappe.db.get_value(SERIAL_DOCTYPE, serial_names[0], ["item_code", "batch_no"], as_dict=True)
            if not first or (first.item_code, first.batch_no or None) != (data["sku"], data["batch_no"]):
                frappe.throw(_("Serial label tidak cocok dengan Item atau Batch saat ini."))
        for serial_index in range(max(0, qty - len(serial_names))):
            serial = frappe.get_doc({
                "doctype": SERIAL_DOCTYPE, "item_code": data["sku"], "batch_no": data["batch_no"],
            }).insert(ignore_permissions=True)
            frappe.get_doc({
                "doctype": MAPPING_DOCTYPE, "purchase_receipt": pr.name,
                "purchase_receipt_item": data["row"], "product_qr_serial": serial.name,
            }).insert(ignore_permissions=True)
            serial_names.append(serial.name)
        labels = []
        for serial_name in serial_names[:qty]:
            serial = frappe.db.get_value(
                SERIAL_DOCTYPE, serial_name, ["item_code", "batch_no", "serial_no", "qr_payload"], as_dict=True,
            )
            if not serial or (serial.item_code, serial.batch_no or None) != (data["sku"], data["batch_no"]):
                frappe.throw(_("Serial label tidak cocok dengan Item atau Batch saat ini."))
            labels.append({"serial_no": serial.serial_no, "qr_value": serial.qr_payload})
        result.append({**data, "labels": labels})
    return {"purchase_receipt": pr.name, "label_count": total, "items": result}
