# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""Packing List page: per-delivery-date packing paper grouped by customer and
Dry/Frozen, editable (koli/berat/picker), persisted as Delivery Manifest
``page_state`` JSON and printable as A4 paper + 60x40mm koli labels."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import frappe
from frappe.utils import escape_html, flt, getdate

from warehouse_app.warehouse_app.doctype.delivery_manifest.delivery_manifest import (
	customer_region,
)
from warehouse_app.warehouse_app.fulfillment.manifest import estimate_weight
from warehouse_app.warehouse_app.fulfillment.permissions import require_read
from warehouse_app.warehouse_app.fulfillment.profile import (
	resolve_dry_exceptions,
	resolve_frozen,
)

DAY_NAMES = ("SENIN", "SELASA", "RABU", "KAMIS", "JUMAT", "SABTU", "MINGGU")


def day_name(value) -> str:
	"""Indonesian day name in caps for a date object or ``yyyy-mm-dd`` string."""
	if isinstance(value, str):
		try:
			value = date.fromisoformat(value[:10])
		except ValueError:
			return ""
	return DAY_NAMES[value.weekday()]


def empty_row(line: dict) -> dict:
	row = {
		"item_code": line.get("item_code") or "",
		"item_name": line.get("item_name") or "",
		"qty": flt(line.get("qty")),
		"uom": line.get("uom") or "",
		"koli": 1,
		"berat": "",
		"box_size": "",
		"picker": "",
	}
	weight = estimate_weight(row["qty"], line.get("weight_per_unit"))
	if weight is not None:
		row["estimated_weight"] = weight
	return row


def aggregate_lines(
	lines: list[dict],
	frozen: set[str] | None,
	dry_exceptions: set[str] | None = None,
) -> dict[str, list[dict]]:
	"""Aggregate SO lines per item+category into editable packing rows.

	Frozen rows carry ``estimated_weight`` = weight_per_unit x qty; dry rows are
	hand-weighed so the field stays blank."""
	# Classify without failing on unclassified items: fail-closed classification
	# is a picking concern; the packing page must still render the paper.
	def is_frozen(line: dict) -> bool:
		if line.get("custom_fulfillment_category"):
			return str(line["custom_fulfillment_category"]).strip().lower() == "frozen"
		if dry_exceptions and line.get("item_code") in dry_exceptions:
			return False
		return bool(frozen and line.get("item_group") in frozen)

	buckets: dict[str, dict[str, dict]] = {"dry": {}, "frozen": {}}
	for line in lines:
		category = "frozen" if is_frozen(line) else "dry"
		code = line.get("item_code") or ""
		row = buckets[category].get(code)
		if row is None:
			row = empty_row(line)
			buckets[category][code] = row
		else:
			row["qty"] = flt(row["qty"]) + flt(line.get("qty"))
			weight = estimate_weight(row["qty"], line.get("weight_per_unit"))
			if weight is not None:
				row["estimated_weight"] = weight
	return {
		category: sorted(rows.values(), key=lambda r: r["item_code"])
		for category, rows in buckets.items()
	}


def overlay_saved(groups: list[dict], saved_by_date: dict[str, dict]) -> None:
	"""Overlay saved page_state edits (vehicle/driver/customers) onto derived
	groups. Saved customers replace derived ones: edits are the truth."""
	for group in groups:
		saved = saved_by_date.get(group["delivery_date"])
		if not saved:
			continue
		group["vehicle"] = saved.get("vehicle") or group["vehicle"]
		group["region"] = saved.get("region") or group.get("region", "")
		group["driver"] = saved.get("driver") or group["driver"]
		if saved.get("customers"):
			group["customers"] = saved["customers"]


# ---------------------------------------------------------------- frappe layer


def load_packing_page_data(company: str, from_date: str, to_date: str) -> dict:
	"""Date groups of picked orders (submitted Pick List or any Delivery Note)
	for the page. Internal queries use frappe.get_all: gudang users (Stock User)
	often lack SO/DN/Pick List doc permissions."""
	so_rows = frappe.get_all(
		"Sales Order",
		filters={
			"company": company,
			"docstatus": 1,
			"delivery_date": ("between", [from_date, to_date]),
		},
		fields=["name", "customer", "customer_name", "delivery_date"],
		order_by="delivery_date asc, customer_name asc",
		limit_page_length=0,
	)
	so_names = [row.name for row in so_rows]
	if not so_names:
		return {"company": company, "groups": []}

	# Picked = submitted Pick List exists ...
	pl_sos = set(
		frappe.get_all(
			"Pick List Item",
			filters={"sales_order": ("in", so_names), "docstatus": 1},
			pluck="sales_order",
			limit_page_length=0,
		)
	)
	dn_links = frappe.get_all(
		"Delivery Note Item",
		filters={"against_sales_order": ("in", so_names)},
		fields=["parent", "against_sales_order"],
		limit_page_length=0,
	)
	dn_names = sorted({row["parent"] for row in dn_links})
	# ... or a (non-cancelled) Delivery Note exists.
	dn_docstatus = {
		row["name"]: row["docstatus"]
		for row in frappe.get_all(
			"Delivery Note",
			filters={"name": ("in", dn_names)},
			fields=["name", "docstatus"],
			limit_page_length=0,
		)
	}
	dn_sos = {
		row["against_sales_order"]
		for row in dn_links
		if dn_docstatus.get(row["parent"]) and dn_docstatus[row["parent"]] != 2
	}

	picked = {row.name: row for row in so_rows if row.name in pl_sos or row.name in dn_sos}
	if not picked:
		return {"company": company, "groups": []}

	item_master = _item_master(
		{
			item.item_code
			for so_name in picked
			for item in frappe.get_doc("Sales Order", so_name).items
		}
	)

	profile = _profile(company)
	frozen = resolve_frozen(profile)
	dry_exceptions = resolve_dry_exceptions(profile) if profile else set()

	# SO lines per (date, customer): qty minus already-delivered qty.
	so_items = frappe.get_all(
		"Sales Order Item",
		filters={"parent": ("in", sorted(picked))},
		fields=[
			"parent",
			"item_code",
			"item_name",
			"qty",
			"delivered_qty",
			"uom",
		],
		limit_page_length=0,
	)
	lines_by_so: dict[str, list[dict]] = {}
	for row in so_items:
		qty = flt(row.qty) - flt(row.delivered_qty)
		if qty <= 0:
			continue
		master = item_master.get(row.item_code, {})
		lines_by_so.setdefault(row.parent, []).append(
			{
				"item_code": row.item_code,
				"item_name": row.item_name or master.get("item_name"),
				"qty": qty,
				"uom": row.uom,
				"item_group": master.get("item_group"),
				"custom_fulfillment_category": master.get("custom_fulfillment_category"),
				"weight_per_unit": flt(master.get("weight_per_unit")),
			}
		)

	groups: dict[str, dict] = {}
	for so_name, so in picked.items():
		lines = lines_by_so.get(so_name)
		if not lines:
			continue
		group = groups.setdefault(
			str(so.delivery_date),
			{
				"delivery_date": str(so.delivery_date),
				"day_name": day_name(so.delivery_date),
				"region": "",
				"vehicle": "",
				"driver": "",
				"customers": [],
			},
		)
		agg = aggregate_lines(lines, frozen, dry_exceptions=dry_exceptions)
		# Merge same customer across SOs of the same date.
		bucket = next(
			(
				c
				for c in group["customers"]
				if c["customer"] == so.customer
			),
			None,
		)
		if bucket is None:
			bucket = {
				"customer": so.customer,
				"customer_name": so.customer_name or so.customer,
				"region": customer_region(so.customer),
				"dry": [],
				"frozen": [],
			}
			group["customers"].append(bucket)
		bucket["dry"].extend(agg["dry"])
		brozen = bucket["frozen"]
		brozen.extend(agg["frozen"])

	group_list = sorted(groups.values(), key=lambda g: g["delivery_date"])
	saved = _saved_page_states(company, [g["delivery_date"] for g in group_list])
	overlay_saved(group_list, saved)
	for group in group_list:
		for customer in group["customers"]:
			customer["dry"].sort(key=lambda r: r["item_code"])
			customer["frozen"].sort(key=lambda r: r["item_code"])
	return {"company": company, "groups": group_list}


def save_packing_page_data(company: str, delivery_date: str, payload: dict) -> dict:
	"""Persist page edits on the Delivery Manifest of (company, delivery_date):
	``page_state`` JSON + region vehicle/driver sync. Read-role gated because
	this page IS the gudang workflow."""
	require_read()
	state = payload.get("state")
	if isinstance(state, str):
		try:
			state = json.loads(state)
		except ValueError:
			frappe.throw("Invalid state payload.", frappe.ValidationError)
	if state is None:
		state = {"groups": payload.get("groups") or []}

	existing = frappe.db.get_value(
		"Delivery Manifest",
		{"company": company, "delivery_date": delivery_date},
		"name",
	)
	doc = (
		frappe.get_doc("Delivery Manifest", existing)
		if existing
		else frappe.new_doc("Delivery Manifest")
	)
	doc.company = company
	doc.delivery_date = delivery_date

	doc.page_state = frappe.as_json(state or {})
	doc.regions = []
	for group in (state or {}).get("groups") or []:
		region = str(group.get("region") or "").strip()
		if not region:
			continue
		doc.append(
			"regions",
			{
				"region": region,
				"vehicle": str(group.get("vehicle") or "").strip(),
				"driver": str(group.get("driver") or "").strip(),
			},
		)
	if existing:
		doc.save(ignore_permissions=True)
	else:
		doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"name": doc.name}


# ---------------------------------------------------------------- print layer


def packing_print_html(company: str, delivery_date: str) -> str:
	"""A4 paper replicating the on-screen packing list layout."""
	data = _print_state(company, delivery_date)
	head = (
		f"<!doctype html><html><head><meta charset='utf-8'><title>Packing List {escape_html(delivery_date)}</title>"
		"<style>"
		"@page{size:A4;margin:10mm}"
		"body{font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#111}"
		"h1{font-size:18px;margin:0;text-align:center;letter-spacing:.06em}"
		".company{text-align:center;font-size:12px;margin:2px 0 4px}"
		".datebar{text-align:right;font-size:11px;margin-bottom:8px}"
		".dayhead{background:#f7ecd2;border:1px solid #e6d3a2;padding:4px 8px;"
		"font-weight:bold;font-size:12px;margin:10px 0 6px;display:flex;gap:14px}"
		"table{width:100%;border-collapse:collapse;margin-bottom:10px}"
		"th,td{border:1px solid #999;padding:3px 5px;text-align:left}"
		"th{background:#f7ecd2;font-size:10px;text-transform:uppercase}"
		".cardhead{background:#f7ecd2;border:1px solid #e6d3a2;padding:3px 6px;"
		"font-weight:bold;margin-top:8px;display:flex;justify-content:space-between}"
		".num{text-align:right;white-space:nowrap}"
		".total td{font-weight:bold;background:#f4f4f0}"
		".empty{text-align:center;color:#555;padding:24px 0}"
		"</style></head><body>"
	)
	title = (
		"<h1>PACKING LIST</h1>"
		f"<p class='company'>{escape_html(company)}</p>"
		f"<p class='datebar'>Tanggal: {escape_html(delivery_date)}</p>"
	)
	groups = data.get("groups") or []
	if not groups:
		return (
			head
			+ title
			+ "<p class='empty'>Tidak ada data packing untuk tanggal ini.</p>"
			+ "<script>window.print()</script></body></html>"
		)
	sections = []
	for group in groups:
		mobil = escape_html(group.get("vehicle") or "—")
		driver = escape_html(group.get("driver") or "—")
		sections.append(
			f"<div class='dayhead'><span>{escape_html(group['day_name'])}</span>"
			f"<span>MOBIL — {mobil}</span><span>DRIVER — {driver}</span></div>"
		)
		for customer in group["customers"]:
			for category, label in (("frozen", "FROZEN"), ("dry", "DRY")):
				rows = customer.get(category) or []
				if not rows:
					continue
				koli = sum(_int(row.get("koli")) for row in rows)
				body = "".join(_print_row(row, category, customer) for row in rows)
				qty_total = sum(flt(row.get("qty")) for row in rows)
				koli_total = sum(_int(row.get("koli")) for row in rows)
				sections.append(
					f"<div class='cardhead'><span>{escape_html(customer['customer_name'])}</span>"
					f"<span>{label} : {koli} COLLY</span></div>"
					"<table><thead><tr><th>ITEM</th><th>QTY</th><th>KOLI</th><th>BERAT</th>"
					"<th>B / K</th><th>PICKER</th><th>ESTIMASI</th></tr></thead>"
					f"<tbody>{body}"
					f"<tr class='total'><td>Total</td><td class='num'>{qty_total:g}</td>"
					f"<td class='num'>{koli_total}</td><td colspan='4'></td></tr>"
					"</tbody></table>"
				)
	return head + title + "".join(sections) + "<script>window.print()</script></body></html>"


def _print_row(row: dict, category: str, customer: dict) -> str:
	berat = row.get("berat") or ""
	est = (
		f"{flt(row.get('estimated_weight')):g}"
		if category == "frozen" and row.get("estimated_weight") is not None
		else ""
	)
	return (
		f"<tr><td>{escape_html(row.get('item_code') or '')} &mdash; "
		f"{escape_html(row.get('item_name') or '')}</td>"
		f"<td class='num'>{flt(row.get('qty')):g}</td>"
		f"<td class='num'>{_int(row.get('koli'))}</td>"
		f"<td>{escape_html(str(berat))}</td>"
		f"<td>{escape_html(str(row.get('box_size') or ''))}</td>"
		f"<td>{escape_html(str(row.get('picker') or customer.get('picker') or ''))}</td>"
		f"<td class='num'>{est}</td></tr>"
	)


def packing_labels_html(company: str, delivery_date: str) -> str:
	"""One 60x40mm label per koli row: customer, day/date, category, item,
	koli n of N, berat, picker."""
	data = _print_state(company, delivery_date)
	head = (
		f"<!doctype html><html><head><meta charset='utf-8'><title>Label Koli {escape_html(delivery_date)}</title>"
		"<style>"
		"@page{size:60mm 40mm;margin:1.5mm}"
		"body{font-family:Arial,Helvetica,sans-serif;font-size:7px;margin:0}"
		".label{width:57mm;height:37mm;border:1px solid #333;padding:1.5mm;"
		"page-break-after:always;box-sizing:border-box;overflow:hidden}"
		".label .cust{font-size:9px;font-weight:bold}"
		".label .item{font-size:8px}"
		".label .koli{font-size:12px;font-weight:bold}"
		"</style></head><body>"
	)
	labels = []
	for group in data.get("groups") or []:
		day = f"{group['day_name']} {group['delivery_date']}"
		for customer in group["customers"]:
			for category, label in (("frozen", "FROZEN"), ("dry", "DRY")):
				rows = customer.get(category) or []
				for row in rows:
					n = max(1, _int(row.get("koli")))
					for i in range(1, n + 1):
						labels.append(
							"<div class='label'>"
							f"<div class='cust'>{escape_html(customer['customer_name'])}</div>"
							f"<div>{escape_html(day)}</div>"
							f"<div>{label}</div>"
							f"<div class='item'>{escape_html(row.get('item_code') or '')} &#8212; "
							f"{escape_html(row.get('item_name') or '')}</div>"
							f"<div class='koli'>KOLI {i} / {n}</div>"
							f"<div>Berat: {escape_html(str(row.get('berat') or ''))}</div>"
							f"<div>Picker: {escape_html(str(row.get('picker') or customer.get('picker') or ''))}</div>"
							"</div>"
						)
	if not labels:
		return (
			head + "<div class='label'><div class='cust'>Tidak ada label.</div></div>"
			"<script>window.print()</script></body></html>"
		)
	return head + "".join(labels) + "<script>window.print()</script></body></html>"


# -------------------------------------------------------------------- helpers


def _print_state(company: str, delivery_date: str) -> dict:
	"""Print source of truth: saved page_state when present, else derived."""
	groups = load_packing_page_data(company, delivery_date, delivery_date)["groups"]
	return {"groups": groups}


def _saved_page_states(company: str, delivery_dates: list[str]) -> dict[str, dict]:
	"""Saved page_state JSON per delivery date (latest manifest wins)."""
	if not delivery_dates:
		return {}
	rows = frappe.get_all(
		"Delivery Manifest",
		filters={"company": company, "delivery_date": ("in", delivery_dates)},
		fields=["name", "delivery_date", "page_state", "modified"],
		order_by="modified asc",
		limit_page_length=0,
	)
	saved: dict[str, dict] = {}
	for row in rows:
		if not row.get("page_state"):
			continue
		try:
			state = json.loads(row.page_state)
		except ValueError:
			continue
		for group in (state or {}).get("groups") or []:
			if str(group.get("delivery_date") or "") == str(row.delivery_date):
				saved[str(row.delivery_date)] = group
	return saved


def _profile(company: str):
	rows = frappe.get_all(
		"Warehouse Fulfillment Profile",
		filters={"company": company},
		fields=["name", "enabled", "frozen_item_group", "include_child_item_groups", "dry_item_exceptions"],
		limit_page_length=1,
	)
	return rows[0] if rows else None


def _item_master(item_codes: set[str]) -> dict[str, dict]:
	if not item_codes:
		return {}
	rows = frappe.get_all(
		"Item",
		filters={"name": ("in", sorted(item_codes))},
		fields=["name", "item_name", "item_group", "weight_per_unit", "custom_fulfillment_category"],
		limit_page_length=0,
	)
	return {row.name: row for row in rows}


def _int(value) -> int:
	try:
		return max(1, int(value or 1))
	except (TypeError, ValueError):
		return 1
