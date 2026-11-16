# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""Packing Slip per Sales Order: list page data, editor save, A4 print and
60x40mm koli labels. Source of truth is the native Packing Slip documents
created by the packing flow; edits update those docs until the Delivery Note
is submitted (then read-only)."""

from __future__ import annotations

import json

import frappe
from frappe.utils import escape_html, flt, getdate

from warehouse_app.warehouse_app.fulfillment.manifest import estimate_weight
from warehouse_app.warehouse_app.fulfillment.permissions import require_read
from warehouse_app.warehouse_app.fulfillment.profile import (
	resolve_dry_exceptions,
	resolve_frozen,
)

COMPANY = "PT. JUARA ROTI INDONESIA"


# ------------------------------------------------------------------ pure logic


def slip_lines_from_ps_items(
	ps_items: list[list[dict]],
	categories: list[str] | None = None,
) -> list[dict]:
	"""Flatten per-koli Packing Slip item lists into editor lines: one line per
	koli (items may repeat across koli). Frozen rows carry estimated_weight
	(weight_per_unit x qty); dry rows are hand-weighed (blank)."""
	lines: list[dict] = []
	for idx, items in enumerate(ps_items, start=1):
		if not items:
			continue
		category = (categories[idx - 1] if categories and idx - 1 < len(categories) else "frozen").lower()
		for item in items:
			qty = flt(item.get("qty"))
			if qty <= 0:
				continue
			line = {
				"item_code": item.get("item_code") or "",
				"item_name": item.get("item_name") or "",
				"qty": qty,
				"uom": item.get("stock_uom") or "",
				"koli_no": idx,
				"koli": 1,
				"berat": "",
				"category": "frozen" if "frozen" in category else "dry",
				"net_weight": flt(item.get("net_weight")),
			}
			if line["category"] == "frozen":
				weight = estimate_weight(qty, item.get("weight_per_unit"))
				if weight is not None:
					line["estimated_weight"] = weight
					line["berat"] = weight
			lines.append(line)
	return lines


def slip_totals(lines: list[dict]) -> dict:
	"""Footer totals: Total Dry (colly) and Net Weight Dry (kg), plus frozen."""
	dry_koli = sum(int(l.get("koli") or 1) for l in lines if l.get("category") == "dry")
	dry_weight = sum(flt(l.get("berat")) or flt(l.get("estimated_weight")) or 0 for l in lines if l.get("category") == "dry")
	frozen_koli = sum(int(l.get("koli") or 1) for l in lines if l.get("category") == "frozen")
	frozen_weight = sum(flt(l.get("berat")) or flt(l.get("estimated_weight")) or 0 for l in lines if l.get("category") == "frozen")
	return {
		"total_dry_colly": dry_koli,
		"net_weight_dry": round(dry_weight, 2),
		"total_frozen_colly": frozen_koli,
		"net_weight_frozen": round(frozen_weight, 2),
	}


# ---------------------------------------------------------------- frappe layer


def load_packing_slips(company: str, from_date: str, to_date: str) -> dict:
	"""List of Packing Slips grouped per Sales Order for the list page."""
	so_filters = {"company": company, "docstatus": 1}
	if from_date or to_date:
		so_filters["delivery_date"] = ("between", [from_date or to_date, to_date or from_date])
	sos = frappe.get_all(
		"Sales Order",
		filters=so_filters,
		fields=["name", "customer", "customer_name", "delivery_date", "po_no"],
		order_by="delivery_date asc, customer_name asc",
		limit_page_length=0,
	)
	so_by_name = {row.name: row for row in sos}
	if not so_by_name:
		return {"company": company, "slips": []}

	dn_links = frappe.get_all(
		"Delivery Note Item",
		filters={"against_sales_order": ("in", sorted(so_by_name)), "docstatus": ("<", 2)},
		fields=["parent", "against_sales_order"],
		limit_page_length=0,
	)
	dn_by_so: dict[str, list[str]] = {}
	for row in dn_links:
		dn_by_so.setdefault(row.against_sales_order, []).append(row.parent)
	dn_status = {
		row["name"]: row["docstatus"]
		for row in frappe.get_all(
			"Delivery Note",
			filters={"name": ("in", sorted({p for v in dn_by_so.values() for p in v}))} if dn_by_so else {"name": ("in", [])},
			fields=["name", "docstatus"],
			limit_page_length=0,
		)
	}

	slips: list[dict] = []
	for so_name, so in so_by_name.items():
		dn_names = [dn for dn in dn_by_so.get(so_name, []) if dn_status.get(dn) not in (None, 2)]
		if not dn_names:
			continue
		ps_rows = frappe.get_all(
			"Packing Slip",
			filters={"delivery_note": ("in", dn_names), "docstatus": ("<", 2)},
			fields=["name", "delivery_note", "docstatus", "modified", "from_case_no", "to_case_no"],
			order_by="from_case_no asc",
			limit_page_length=0,
		)
		if not ps_rows:
			continue
		dn_docstatus = min(dn_status[dn] for dn in dn_names)
		for ps in ps_rows:
			slips.append(
				{
					"name": ps.name,
					"sales_order": so_name,
					"customer": so.customer,
					"customer_name": so.customer_name or so.customer,
					"po_no": so.po_no or "",
					"delivery_date": str(so.delivery_date),
					"delivery_note": ps.delivery_note,
					"status": "Read-only" if dn_docstatus == 1 else "Editable",
					"editable": dn_docstatus != 1,
					"modified": str(ps.modified),
					"from_case_no": ps.from_case_no,
					"to_case_no": ps.to_case_no,
				}
			)
	return {"company": company, "slips": slips}


def load_packing_slip(name: str) -> dict:
	"""Editor payload for one Packing Slip: koli lines, customer/PO header,
	totals, editable flag."""
	require_read()
	ps = frappe.get_doc("Packing Slip", name)
	dn_docstatus = frappe.db.get_value("Delivery Note", ps.delivery_note, "docstatus")
	editable = dn_docstatus != 1
	dn = frappe.get_doc("Delivery Note", ps.delivery_note) if editable else None
	so_name = None
	if dn:
		so_name = next(
			(row.against_sales_order for row in dn.items if getattr(row, "against_sales_order", None)),
			None,
		)

	# Sibling slips of the same DN = the other koli (Frozen/Dry split).
	siblings = frappe.get_all(
		"Packing Slip",
		filters={"delivery_note": ps.delivery_note, "docstatus": ("<", 2)},
		fields=["name", "from_case_no", "custom_box_size"],
		order_by="from_case_no asc",
		limit_page_length=0,
	)
	categories = ["frozen" if (s.custom_box_size == "K") else "dry" for s in siblings]
	ps_items = [
		[
			{
				"item_code": it.item_code,
				"item_name": it.item_name or it.item_code,
				"qty": flt(it.qty),
				"net_weight": flt(it.net_weight),
				"stock_uom": it.stock_uom,
			}
			for it in frappe.get_doc("Packing Slip", s.name).items
		]
		for s in siblings
	]
	lines = slip_lines_from_ps_items(ps_items, categories=categories)

	header = {"customer": "", "customer_name": "", "po_no": "", "delivery_date": ""}
	if so_name:
		so = frappe.db.get_value(
			"Sales Order", so_name, ["customer", "customer_name", "po_no", "delivery_date"], as_dict=True
		)
		if so:
			header = {
				"customer": so.customer,
				"customer_name": so.customer_name or so.customer,
				"po_no": so.po_no or "",
				"delivery_date": str(so.delivery_date),
			}
	return {
		"name": ps.name,
		"delivery_note": ps.delivery_note,
		"editable": editable,
		"header": header,
		"lines": lines,
		"totals": slip_totals(lines),
	}


def save_packing_slip(name: str, lines: list) -> dict:
	"""Persist edited koli lines back onto the native Packing Slip documents of
	the DN (one doc per koli). Blocked once the DN is submitted."""
	require_read()
	if isinstance(lines, str):
		try:
			lines = json.loads(lines)
		except ValueError:
			frappe.throw("Invalid lines payload.", frappe.ValidationError)
	ps = frappe.get_doc("Packing Slip", name)
	dn_docstatus = frappe.db.get_value("Delivery Note", ps.delivery_note, "docstatus")
	if dn_docstatus == 1:
		frappe.throw("Packing Slip is read-only: Delivery Note already submitted.", frappe.ValidationError)

	# Group edited lines per koli number; delete extra slips, update/create the rest.
	by_koli: dict[int, list[dict]] = {}
	for line in lines or []:
		koli = max(1, int(flt(line.get("koli_no"), 1) or 1))
		by_koli.setdefault(koli, []).append(line)

	siblings = frappe.get_all(
		"Packing Slip",
		filters={"delivery_note": ps.delivery_note, "docstatus": 0},
		fields=["name", "from_case_no"],
		order_by="from_case_no asc",
		limit_page_length=0,
	)
	sibling_by_case = {int(s.from_case_no or 1): s.name for s in siblings}
	max_case = max(sibling_by_case) if sibling_by_case else 0

	for koli in sorted(by_koli):
		target = sibling_by_case.get(koli)
		if target:
			doc = frappe.get_doc("Packing Slip", target)
			doc.set("items", [])
		else:
			doc = frappe.new_doc("Packing Slip")
			doc.delivery_note = ps.delivery_note
			doc.from_case_no = koli
			doc.to_case_no = koli
			doc.insert(ignore_permissions=True)
		dn_row_by_item = {}
		dn_doc = frappe.get_doc("Delivery Note", ps.delivery_note)
		for row in dn_doc.items:
			dn_row_by_item.setdefault(row.item_code, row)
		for line in by_koli[koli]:
			dn_row = dn_row_by_item.get(line.get("item_code"))
			doc.append(
				"items",
				{
					"item_code": line.get("item_code"),
					"item_name": line.get("item_name") or line.get("item_code"),
					"description": line.get("item_name") or line.get("item_code"),
					"qty": flt(line.get("qty")),
					"dn_detail": dn_row.name if dn_row else None,
					"stock_uom": line.get("uom") or (dn_row.stock_uom if dn_row else None),
				},
			)
		doc.save(ignore_permissions=True)

	# Koli rows removed in the editor: delete those draft slips.
	for case_no, sib_name in sibling_by_case.items():
		if case_no not in by_koli:
			frappe.delete_doc("Packing Slip", sib_name, ignore_permissions=True, force=1)

	frappe.db.commit()
	return {"name": name, "totals": slip_totals(lines or [])}


# ---------------------------------------------------------------- print layer


def packing_slip_print_html(name: str) -> str:
	"""A4 paper replicating the old packing paper: orange PACKING LIST header,
	Frozen (left) and Dry (right) side by side, one row per koli, footer totals."""
	require_read()
	data = load_packing_slip(name)
	header = data["header"]
	lines = data["lines"]

	def rows_html(category: str) -> str:
		out = []
		for line in lines:
			if line["category"] != category:
				continue
			berat = line.get("berat") if line.get("berat") != "" else (line.get("estimated_weight") or "")
			out.append(
				f"<tr><td>{escape_html(line['item_code'])} &mdash; {escape_html(line['item_name'])}</td>"
				f"<td class='num'>{flt(line['qty']):g}</td><td class='num'>{escape_html(str(line.get('uom') or ''))}</td>"
				f"<td class='num'>{line['koli_no']}</td><td class='num'>{berat if berat == '' else flt(berat):g}</td></tr>"
			)
		return "".join(out)

	totals = data["totals"]
	dry_rows = rows_html("dry")
	frozen_rows = rows_html("frozen")

	return f"""<!doctype html><html><head><meta charset='utf-8'><title>Packing List {escape_html(name)}</title>
<style>
@page{{size:A4;margin:10mm}}
body{{font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#111}}
.head{{background:#f7a600;color:#fff;padding:10px 14px;display:flex;justify-content:space-between;align-items:center}}
.head h1{{font-size:20px;margin:0;letter-spacing:.08em}}
.head .to{{font-size:12px}}
.meta{{display:flex;gap:24px;margin:8px 0 12px;font-size:12px}}
.cols{{display:flex;gap:10px}}
.col{{flex:1}}
.colh{{background:#f7ecd2;border:1px solid #e6d3a2;padding:4px 8px;font-weight:bold;font-size:12px}}
table{{width:100%;border-collapse:collapse}}
th,td{{border:1px solid #999;padding:3px 5px;text-align:left}}
th{{background:#f7ecd2;font-size:10px;text-transform:uppercase}}
.num{{text-align:right;white-space:nowrap}}
.total td{{font-weight:bold;background:#f4f4f0}}
.empty{{color:#555;padding:12px 0;text-align:center}}
</style></head><body>
<div class='head'><h1>PACKING LIST</h1><div class='to'>TO: {escape_html(header.get('customer_name') or '')}</div></div>
<div class='meta'>
<span>PO No: <strong>{escape_html(header.get('po_no') or '-')}</strong></span>
<span>Delivery date: <strong>{escape_html(header.get('delivery_date') or '-')}</strong></span>
<span>No: <strong>{escape_html(name)}</strong></span>
</div>
<div class='cols'>
<div class='col'>
<div class='colh'>FROZEN</div>
<table><thead><tr><th>Item</th><th>Qty</th><th>Unit</th><th>Koli</th><th>Weight (Kg)</th></tr></thead>
<tbody>{frozen_rows or "<tr><td colspan='5' class='empty'>&mdash;</td></tr>"}</tbody></table>
</div>
<div class='col'>
<div class='colh'>DRY</div>
<table><thead><tr><th>Item</th><th>Qty</th><th>Unit</th><th>Koli</th><th>Weight (Kg)</th></tr></thead>
<tbody>{dry_rows or "<tr><td colspan='5' class='empty'>&mdash;</td></tr>"}</tbody></table>
<div class='total' style='margin-top:8px;border:1px solid #999;padding:5px 8px'>
Total Dry (colly): <strong>{totals['total_dry_colly']}</strong> &nbsp;|&nbsp;
Net Weight Dry (kg): <strong>{totals['net_weight_dry']:g}</strong>
</div>
</div>
</div>
<script>window.print()</script></body></html>"""


def packing_slip_labels_html(name: str) -> str:
	"""One 60x40mm label per koli: left n/total + BERAT big; right company on
	top line, customer bold, item, yellow FROZEN/DRY badge."""
	require_read()
	data = load_packing_slip(name)
	header = data["header"]
	lines = data["lines"]

	koli_categories: dict[int, str] = {}
	koli_items: dict[int, list[str]] = {}
	for line in lines:
		n = line["koli_no"]
		koli_categories.setdefault(n, line["category"])
		koli_items.setdefault(n, []).append(f"{line['item_code']} - {line['item_name']}")

	total = len(koli_categories)
	labels = []
	for n in sorted(koli_categories):
		category = koli_categories[n].upper()
		weight = ""
		for line in lines:
			if line["koli_no"] == n:
				weight = line.get("berat") or line.get("estimated_weight") or ""
				break
		items = "<br>".join(escape_html(i) for i in koli_items[n])
		labels.append(
			f"""<div class='label'>
<div class='left'><div class='ratio'>{n}/{total}</div><div class='bw'>BERAT</div><div class='kg'>{escape_html(str(weight))}</div></div>
<div class='right'>
<div class='company'>PT. JUARA ROTI INDONESIA</div>
<div class='cust'>{escape_html(header.get('customer_name') or '')}</div>
<div class='items'>{items}</div>
<span class='badge'>{category}</span>
</div>
</div>"""
		)
	return f"""<!doctype html><html><head><meta charset='utf-8'><title>Label Koli {escape_html(name)}</title>
<style>
@page{{size:60mm 40mm;margin:1.5mm}}
body{{font-family:Arial,Helvetica,sans-serif;font-size:7px;margin:0}}
.label{{width:57mm;height:37mm;border:1px solid #333;padding:1mm;page-break-after:always;box-sizing:border-box;display:flex;overflow:hidden}}
.left{{width:40%;border-right:1px dashed #666;padding-right:1mm;display:flex;flex-direction:column;justify-content:center;align-items:center}}
.ratio{{font-size:10px;font-weight:bold}}
.bw{{font-size:8px;margin-top:1mm;letter-spacing:.1em}}
.kg{{font-size:14px;font-weight:bold}}
.right{{flex:1;padding-left:1.5mm}}
.company{{border-top:1px solid #333;font-size:6.5px;padding-top:0.5mm}}
.cust{{font-size:9px;font-weight:bold;margin:0.5mm 0}}
.items{{font-size:7px;line-height:1.3}}
.badge{{display:inline-block;background:#ffe07a;border:1px solid #d9a300;border-radius:2px;padding:0 2mm;font-size:8px;font-weight:bold;margin-top:1mm}}
</style></head><body>
{''.join(labels) or "<div class='label'>Tidak ada label.</div>"}
<script>window.print()</script></body></html>"""
