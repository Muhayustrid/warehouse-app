# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto
# License: MIT

# Picker request serah terima ala-gudang (W9).
# Bahasa gudang: adonan ke + nama item — bukan nomor WO + qty.
# Endpoint ini HANYA membaca Work Order untuk daftar; pembuatan/pembatalan
# MR tetap lewat endpoint production_app (create_request/cancel_request)
# yang dipanggil client langsung — production_app tetap satu-satunya penulis
# ringkasan WO (custom_handover_material_request + box), nol duplikasi logika
# (ruling W9 Opsi A). Gudang punya read Work Order (Stock User / Gudang
# Barang Jadi), jadi get_list polos tanpa bypass perm.
#
# Filter ala list view ERPNext (permintaan user): panel [Field][operator]
# [nilai]. Field dibatasi whitelist FILTER_FIELDS — get_list tetap
# parameterized + perm user ditegakkan, jadi tidak ada jalur injection;
# "Item" adalah field virtual yang di-expand ke production_item via
# pencarian nama/kode item (bahasa gudang adalah nama item).
#
# W19: flag grup — group_item (item di Warehouse App Settings) + box_plan /
# group_boxes / group_size dari custom_handover_box_plan MR anggota. Bacaan
# saja; group create/cancel tetap endpoint production_app. Doctype/kolom
# production_app yang belum ter-migrate (site baru) -> flag netral.

import json

import frappe
from frappe.utils import cint, flt, get_datetime

STATUS_TERBLOKIR = ("Stopped", "Closed", "Cancelled")

FILTER_FIELDS = {
	"custom_adonan_ke": {
		"label": "Batch",
		"fieldtype": "Data",
		"operators": ["=", "!="],
	},
	"creation": {
		"label": "Date",
		"fieldtype": "Date",
		"operators": ["between", ">=", "<="],
	},
	"production_item": {
		"label": "Item",
		"fieldtype": "Link",
		"operators": ["like", "="],
		"placeholder": "item name or code",
	},
	"status": {
		"label": "Work Order Status",
		"fieldtype": "Select",
		"operators": ["=", "!="],
	},
	"name": {
		"label": "Work Order No.",
		"fieldtype": "Data",
		"operators": ["like", "="],
	},
	"produced_qty": {
		"label": "Qty",
		"fieldtype": "Float",
		"operators": [">=", "<=", "="],
	},
	"fg_warehouse": {
		"label": "Finished Goods Warehouse",
		"fieldtype": "Link",
		"operators": ["like", "="],
		"placeholder": "e.g. Gudang Produksi",
	},
}


@frappe.whitelist()
def filter_fields():
	"""Meta panel filter untuk client: field + operator + opsi select."""
	meta = frappe.get_meta("Work Order")
	out = {}
	for fname, cfg in FILTER_FIELDS.items():
		entry = dict(cfg)
		df = meta.get_field(fname)
		if df and df.fieldtype == "Select":
			entry["options"] = [
				o for o in (df.options or "").split("\n") if o and not o.startswith("#")
			]
		out[fname] = entry
	return out


@frappe.whitelist()
def requestable_work_orders(search=None, filters=None, limit_start=0, limit_page_length=50, paginated=0):
	"""Daftar WO siap-diminta untuk user gudang: adonan + item + produced qty.

	- WO submitted, bukan Stopped/Closed/Cancelled, produced qty > 0.
	- `request_active` = ada MR aktif menempel di WO (submitted, bukan
	  Stopped, belum ada SE submitted) — semantik _active_mr_now production_app
	  tapi HANYA untuk tampilan; keputusan final tetap di endpoint
	  create_request (throw duplikat di bawah row lock).
	- `filters`: JSON list [{field, operator, value}] — field wajib ada di
	  whitelist FILTER_FIELDS; nilai kosong dilewati.
	- `limit_start`: offset halaman; `limit_page_length`: ukuran halaman
	  (20/50/100/250) — kompatibel dgn pemanggil lama (load more: offset
	  kelipatan 50).
	- `paginated`: 0 = balas LIST (kontrak lama, dipakai gate + caller lama);
	  1 = balas {rows, total} utk pager SPA (total = seluruh WO cocok).
	"""
	limit_start = max(cint(limit_start), 0)
	limit_page_length = min(max(cint(limit_page_length or 50), 1), 250)
	filters_base = [
		["docstatus", "=", 1],
		["status", "not in", list(STATUS_TERBLOKIR)],
		["produced_qty", ">", 0],
	]
	or_filters = None
	search = str(search or "").strip()
	if search:
		pattern = f"%{search}%"
		items = frappe.get_all(
			"Item", filters=[["item_name", "like", pattern]], pluck="name", limit=0
		)
		or_filters = [
			["custom_adonan_ke", "like", pattern],
			["name", "like", pattern],
			["production_item", "in", items or [""]],
		]

	for parsed_flt in _parse_filters(filters):
		filters_base.append(parsed_flt)

	# total dihitung terpisah dari halaman (count query ringan) supaya pager
	# client tahu jumlah halaman tanpa memuat seluruh baris.
	total = len(
		frappe.get_all(
			"Work Order",
			filters=filters_base,
			or_filters=or_filters,
			pluck="name",
			limit_page_length=0,
		)
	)

	rows = frappe.get_list(
		"Work Order",
		filters=filters_base,
		or_filters=or_filters,
		fields=[
			"name",
			"creation",
			"custom_adonan_ke",
			"production_item",
			"produced_qty",
			"stock_uom",
			"status",
			"fg_warehouse",
			"custom_handover_material_request",
		],
		order_by="creation desc",
		limit_page_length=limit_page_length,
		limit_start=limit_start,
	)

	item_names = dict(
		frappe.get_all(
			"Item",
			filters=[["name", "in", [r.production_item for r in rows] or [""]]],
			fields=["name", "item_name"],
			as_list=True,
		)
	)
	mr_info, mr_dikirim, mr_plan = _active_request_map(rows)
	group_items = _group_items()
	plan_info = _group_plan_map(sorted({p for p in mr_plan.values() if p}))
	bulk_size = _bulk_size_map(sorted({m for m in mr_info if not mr_plan.get(m)}))

	for r in rows:
		r.item_name = item_names.get(r.production_item) or r.production_item
		mr = r.custom_handover_material_request
		docstatus, status = mr_info.get(mr, (None, None))
		r.request_active = bool(
			mr and docstatus == 1 and status != "Stopped" and mr not in mr_dikirim
		)
		# MR sudah terpenuhi SE submitted — tanpa ini baris tampil seperti WO
		# yang belum pernah diminta (operator kebingungan); UI kasih pill
		# "Shipped" + baris non-selectable.
		r.request_shipped = bool(mr and docstatus == 1 and mr in mr_dikirim)
		# W19: info grup box bersama (tanpa grup -> None/[]/0).
		r.box_plan = mr_plan.get(mr) if mr else None
		info = plan_info.get(r.box_plan) or {}
		r.group_boxes = info.get("boxes") or []
		# 2026-10-10: grup baru = SATU MR berbaris banyak (tanpa plan)
		r.group_size = info.get("size") or bulk_size.get(mr, 0)
		r.group_item = r.production_item in group_items

	# Satuan qty request mengikuti display UOM produksi (mis. Pcs -> Pack);
	# logika konversi TIDAK diduplikasi — pakai _enrich_units production_app,
	# sumber yang sama dengan validasi create_request. Fallback = stock qty.
	try:
		from production_app.api.work_order import _enrich_units

		_enrich_units(rows)
	except Exception:
		for r in rows:
			r.display_uom = r.stock_uom
			r.display_conversion_factor = 1
	for r in rows:
		factor = flt(r.get("display_conversion_factor") or 1)
		if factor <= 0:
			factor = 1
		r.expected_units = int(round(flt(r.produced_qty) / factor))
		r.display_uom = r.get("display_uom") or r.stock_uom

	# Default (paginated=0) = list polos — kontrak LAMA utuh, semua pemanggil
	# lama (gate w9/w16/w19 memanggil fungsi langsung) tak perlu diubah.
	# Client SPA mengirim paginated=1 dan menerima {rows, total} untuk pager.
	if not paginated:
		return rows
	return frappe._dict({"rows": rows, "total": total})


def _parse_filters(filters):
	"""JSON [{field, operator, value}] -> get_list filters tervalidasi.

	Field "production_item" dicocokkan via nama/kode item (virtual); sisanya
	lolos apa adanya — get_list memakai parameter binding, perm user tetap
	ditegakkan.
	"""
	if not filters:
		return []
	try:
		parsed = json.loads(filters) if isinstance(filters, str) else filters
	except (ValueError, TypeError):
		frappe.throw(frappe._("Format filter tidak valid"))
	if not isinstance(parsed, list):
		frappe.throw(frappe._("Format filter tidak valid"))

	out = []
	for f in parsed:
		if isinstance(f, dict):
			field, operator, value = f.get("field"), f.get("operator"), f.get("value")
		else:
			field = f[0] if len(f) > 0 else None
			operator = f[1] if len(f) > 1 else None
			value = f[2] if len(f) > 2 else None
		cfg = FILTER_FIELDS.get(field)
		if not cfg or operator not in cfg["operators"]:
			frappe.throw(
				frappe._("Filter tidak didukung: {0} {1}").format(
					frappe.bold(str(field)), frappe.bold(str(operator))
				)
			)
		if value is None or str(value).strip() == "":
			continue
		if field == "production_item":
			out.extend(_item_filter(operator, str(value).strip()))
			continue
		if cfg["fieldtype"] in ("Float", "Int"):
			value = flt(value)
		if cfg["fieldtype"] == "Date":
			out.extend(_date_filter(field, operator, value))
			continue
		if operator == "like":
			# get_list "like" tidak menambah wildcard — list view ERPNext
			# juga membungkus %value% di sisi nilai.
			value = f"%{str(value).strip()}%"
		out.append([field, operator, value])
	return out


def _date_filter(field, operator, value):
	"""Filter tanggal per-hari: `creation` bertipe datetime, jadi batas
	hari diperluas ke 00:00:00–23:59:59 agar perbandingan tanggal akurat.
	Ukuran `between`: [d1, d2] (satu sisi boleh kosong -> jadi >= / <=).
	"""
	if isinstance(value, (list, tuple)):
		d1 = str(value[0] or "").strip() if len(value) > 0 else ""
		d2 = str(value[1] or "").strip() if len(value) > 1 else ""
	else:
		d1, d2 = str(value or "").strip(), ""

	if operator == "between":
		if d1 and d2:
			return [
				[field, ">=", get_datetime(d1)],
				[field, "<=", get_datetime(d2).replace(hour=23, minute=59, second=59)],
			]
		if d1:
			operator, value = ">=", d1
		elif d2:
			operator, value = "<=", d2
		else:
			return []
	elif operator in (">=", "<="):
		d1 = d1 or d2

	if not d1:
		return []
	bound = get_datetime(d1)
	if operator == "<=":
		bound = bound.replace(hour=23, minute=59, second=59)
	else:
		bound = bound.replace(hour=0, minute=0, second=0)
	return [[field, operator, bound]]


def _item_filter(operator, value):
	"""Filter Item dalam bahasa gudang: nama ATAU kode item."""
	if operator == "=":
		pat = value
		items = frappe.get_all(
			"Item",
			or_filters=[["name", "=", pat], ["item_name", "=", pat]],
			pluck="name",
			limit=0,
		)
	else:
		pat = f"%{value}%"
		items = frappe.get_all(
			"Item",
			or_filters=[["name", "like", pat], ["item_name", "like", pat]],
			pluck="name",
			limit=0,
		)
	return [["production_item", "in", items or [""]]]


def _active_request_map(rows):
	"""(docstatus, status) per MR + set MR yang sudah ada SE submitted +
	MR -> custom_handover_box_plan (kolom production_app bisa belum ada)."""
	mr_names = [
		r.custom_handover_material_request for r in rows if r.custom_handover_material_request
	]
	if not mr_names:
		return {}, set(), {}
	fields = ["name", "docstatus", "status"]
	if frappe.db.has_column("Material Request", "custom_handover_box_plan"):
		fields.append("custom_handover_box_plan")
	mr_rows = frappe.get_all("Material Request", filters=[["name", "in", mr_names]], fields=fields)
	mr_info = {d.name: (d.docstatus, d.status) for d in mr_rows}
	mr_plan = {d.name: d.get("custom_handover_box_plan") for d in mr_rows}
	mr_dikirim = set(
		frappe.get_all(
			"Stock Entry Detail",
			filters={
				"material_request": ("in", mr_names),
				"docstatus": 1,
				"parenttype": "Stock Entry",
			},
			pluck="material_request",
		)
	)
	return mr_info, mr_dikirim, mr_plan


def _bulk_size_map(mr_names):
	"""MR -> jumlah baris ber-WO, hanya MR bulk (> 1 baris)."""
	if not mr_names or not frappe.db.has_column("Material Request Item", "custom_work_order"):
		return {}
	sizes = {}
	for parent in frappe.get_all(
		"Material Request Item",
		filters={"parent": ("in", mr_names), "custom_work_order": ("is", "set")},
		pluck="parent",
		limit=0,
	):
		sizes[parent] = sizes.get(parent, 0) + 1
	return {m: n for m, n in sizes.items() if n > 1}

def _group_items():
	"""Set item group-request dari Warehouse App Settings. Doctype belum ada
	(site baru sebelum migrate) -> anggap kosong; error lain dibiarkan naik
	supaya bug nyata tidak tersembunyi di balik flag netral."""
	if not frappe.db.exists("DocType", "Warehouse App Group Item"):
		return set()
	return set(
		frappe.get_all(
			"Warehouse App Group Item",
			filters={"parent": "Warehouse App Settings", "parenttype": "Warehouse App Settings"},
			pluck="item",
			limit=0,
		)
	)


def _group_plan_map(plan_names):
	"""plan -> {boxes, size}: baris child {kg, qty} (dibaca dari field Table
	pertama Handover Box Plan — nama field child tidak dikontrak) + jumlah MR
	anggota docstatus 1. Doctype/kolom production_app yang belum ter-migrate
	-> {} (flag grup netral di papan); error lain dibiarkan naik."""
	if not plan_names:
		return {}
	if not frappe.db.exists("DocType", "Handover Box Plan"):
		return {}
	if not frappe.db.has_column("Material Request", "custom_handover_box_plan"):
		return {}
	child_dt = next(
		(
			df.options
			for df in frappe.get_meta("Handover Box Plan").fields
			if df.fieldtype == "Table"
		),
		None,
	)
	if not child_dt:
		return {}
	boxes = {}
	for parent, kg, qty in frappe.get_all(
		child_dt,
		filters={"parent": ("in", plan_names), "parenttype": "Handover Box Plan"},
		fields=["parent", "kg", "qty"],
		order_by="parent asc, idx asc",
		as_list=True,
		limit=0,
	):
		boxes.setdefault(parent, []).append({"kg": flt(kg), "qty": cint(qty)})
	plan_hits = frappe.get_all(
		"Material Request",
		filters=[
			["custom_handover_box_plan", "in", plan_names],
			["docstatus", "=", 1],
		],
		pluck="custom_handover_box_plan",
		limit=0,
	)
	sizes = {}
	for p in plan_hits:
		sizes[p] = sizes.get(p, 0) + 1
	return {p: {"boxes": boxes.get(p) or [], "size": cint(sizes.get(p, 0))} for p in plan_names}
