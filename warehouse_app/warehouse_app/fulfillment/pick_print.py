# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""Combined pick list print: one A4 sheet aggregating every draft Pick List
of a delivery date, for the warehouse pickers (paper = role/day, documents
stay per-SO)."""

from __future__ import annotations

from collections.abc import Callable, Mapping

import frappe
from frappe.utils import flt

RUN = "Warehouse Fulfillment Run"

# Row qty: picked_qty when picking has started, otherwise planned qty so the
# paper is still usable H-1.
def _row_qty(row: Mapping) -> float:
	picked = flt(row.get("picked_qty"))
	if picked > 0:
		return picked
	return flt(row.get("qty"))


def combined_pick_rows(
	runs: list[dict],
	pick_list_rows: Callable[[str], list[dict]],
) -> list[dict]:
	"""Flatten run pick lists into printable rows: FROZEN first, then customer,
	then item_code."""
	rows: list[dict] = []
	for run in runs:
		delivery_date = run.get("delivery_date") or ""
		for group, pl_name in (
			("FROZEN", run.get("frozen_pick_list")),
			("DRY", run.get("dry_pick_list")),
		):
			if not pl_name:
				continue
			for row in pick_list_rows(pl_name):
				rows.append(
					{
						"group": group,
						"customer": run.get("customer") or "",
						"delivery_date": delivery_date,
						"pick_list": pl_name,
						"item_code": row.get("item_code") or "",
						"item_name": row.get("item_name") or "",
						"qty": _row_qty(row),
						"stock_uom": row.get("stock_uom") or row.get("uom") or "",
						"warehouse": row.get("warehouse") or "",
					}
				)
	rows.sort(key=lambda r: (0 if r["group"] == "FROZEN" else 1, r["customer"], r["item_code"]))
	return rows


def pick_run_names(company: str, delivery_date: str) -> list[str]:
	"""Runs whose pick lists are still relevant for that delivery date."""
	return frappe.get_all(
		RUN,
		filters={
			"company": company,
			"status": ("not in", ["DISPATCHED", "CANCELLED"]),
		},
		or_filters=[
			["dry_pick_list", "is", "set"],
			["frozen_pick_list", "is", "set"],
		],
		order_by="name asc",
		pluck="name",
	)


def _pick_list_rows(pl_name: str) -> list[dict]:
	if not frappe.db.exists("Pick List", pl_name):
		return []
	doc = frappe.get_doc("Pick List", pl_name)
	return [
		{
			"item_code": row.item_code,
			"item_name": row.item_name,
			"qty": flt(row.qty),
			"picked_qty": flt(row.get("custom_picked_qty")),
			"stock_uom": row.uom,
			"warehouse": row.warehouse,
		}
		for row in doc.locations
	]


def _pick_list_html(rows: list[dict], delivery_date: str, company: str) -> str:
	"""One A4 sheet: all rows for a delivery date, FROZEN section then DRY."""
	head = (
		f"<!doctype html><html><head><meta charset='utf-8'><title>Pick List {delivery_date}</title>"
		"<style>"
		"@page{size:A4;margin:12mm}"
		"body{font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#111}"
		"h1{font-size:16px;margin:0 0 2px}"
		".sub{color:#555;margin:0 0 10px;font-size:11px}"
		"table{width:100%;border-collapse:collapse;margin-bottom:14px}"
		"th,td{border:1px solid #999;padding:4px 6px;text-align:left}"
		"th{background:#e8eef5;font-size:10px;text-transform:uppercase}"
		".qty,.uom{white-space:nowrap}"
		"h2{font-size:13px;margin:14px 0 4px;letter-spacing:.04em}"
		".empty{color:#555;font-size:13px;padding:24px 0}"
		"@media print{.noprint{display:none}}"
		"</style></head><body>"
	)
	title = f"<h1>PICK LIST &mdash; {company}</h1><p class='sub'>Tanggal kirim: {delivery_date}</p>"
	if not rows:
		return head + title + "<p class='empty'>Tidak ada pick list untuk tanggal ini.</p></body></html>"

	sections = []
	for group in ("FROZEN", "DRY"):
		group_rows = [r for r in rows if r["group"] == group]
		if not group_rows:
			continue
		body = "".join(
			f"<tr><td>{r['customer']}</td><td>{r['item_code']} &mdash; {r['item_name']}</td>"
			f"<td class='qty'>{r['qty']:g}</td><td class='uom'>{r['stock_uom']}</td>"
			f"<td>{r['warehouse']}</td></tr>"
			for r in group_rows
		)
		sections.append(
			f"<h2>{group} ({len(group_rows)} baris)</h2>"
			"<table><thead><tr><th>Customer</th><th>Item</th><th>Qty</th><th>UOM</th><th>Warehouse</th></tr></thead>"
			f"<tbody>{body}</tbody></table>"
		)
	total = len(rows)
	return head + title + "".join(sections) + f"<p class='sub'>Total {total} baris.</p></body></html>"


def load_combined_pick_rows(company: str, delivery_date: str) -> list[dict]:
	runs = [
		dict(r)
		for r in frappe.get_all(
			RUN,
			filters={"name": ("in", pick_run_names(company, delivery_date))},
			fields=["name", "company", "customer", "status"],
			order_by="name asc",
		)
	]
	# delivery_date lives on the Sales Order, not the Run.
	so_names = [r["sales_order"] for r in frappe.get_all(
		RUN,
		filters={"name": ("in", [r["name"] for r in runs])} if runs else {"name": ("in", [])},
		fields=["sales_order"],
	)]
	delivery_by_run = {}
	if runs:
		pairs = frappe.get_all(
			RUN,
			filters={"name": ("in", [r["name"] for r in runs])},
			fields=["name", "sales_order"],
		)
		so_dates = dict(
			frappe.get_all(
				"Sales Order",
				filters={"name": ("in", list({p["sales_order"] for p in pairs}))},
				fields=["name", "delivery_date"],
				as_list=True,
			)
		)
		for p in pairs:
			delivery_by_run[p["name"]] = str(so_dates.get(p["sales_order"]) or "")
	for r in runs:
		r["delivery_date"] = delivery_by_run.get(r["name"], "")
	runs = [r for r in runs if r["delivery_date"] == str(delivery_date)]
	return combined_pick_rows(runs, _pick_list_rows)
