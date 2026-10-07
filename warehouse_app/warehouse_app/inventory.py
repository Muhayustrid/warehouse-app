# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto
# License: MIT

# W40 — halaman Inventory SPA (/gudang/inventory). Read-only atas ledger
# native: Stock Ledger Entry (SLE) + Bin; nol tabel baru.
#
# - Semua query server-side + paginasi LIMIT/OFFSET; halaman diambil dengan
#   deferred join (pilih s.name dulu, baru join detail utk <= page_len baris).
# - Qty ditampilkan dalam Default Inventory UOM item (W21,
#   custom_default_inventory_unit_of_measure): qty / conversion_factor dari
#   tabel UOM Conversion item; tanpa default / tanpa faktor -> stock UOM, faktor 1.
#   Nilai Rp tidak dikonversi.
# - Perubahan qty per SLE: Stock Reconciliation non-batch menyimpan
#   actual_qty = 0 dengan qty_after_transaction absolut, jadi perubahannya =
#   qty_after - qty_after SLE sebelumnya (pola report Stock Ledger native).
# - Permission: read Stock Ledger Entry / Bin wajib; User Permission
#   Warehouse/Company user ditegakkan manual karena query memakai SQL mentah.

import frappe
from frappe.utils import add_days, cint, getdate

PAGE_SIZES = (20, 50, 100)

SLE = "`tabStock Ledger Entry`"

# UOM inventaris per item; dipakai sebagai potongan JOIN + kolom SELECT.
UOM_JOIN = """
	join `tabItem` i on i.name = s.item_code
	left join `tabUOM Conversion Detail` u
		on u.parent = i.name and u.uom = i.custom_default_inventory_unit_of_measure
		and i.custom_default_inventory_unit_of_measure != i.stock_uom
"""
UOM_COLS = """
	if(u.conversion_factor > 0, u.conversion_factor, 1) as factor,
	if(u.conversion_factor > 0, u.uom, i.stock_uom) as uom
"""

# Perubahan qty satu SLE (lihat catatan Stock Reconciliation di atas).
# ponytail: subquery berkorelasi — hanya dievaluasi utk baris halaman aktif
# (deferred join), memakai index item_code+warehouse+posting_datetime+creation.
QTY_CHANGE = f"""
	if(s.voucher_type = 'Stock Reconciliation' and s.actual_qty = 0,
		s.qty_after_transaction - ifnull((
			select p.qty_after_transaction from {SLE} p
			where p.item_code = s.item_code and p.warehouse = s.warehouse
				and p.is_cancelled = 0
				and (p.posting_datetime < s.posting_datetime
					or (p.posting_datetime = s.posting_datetime and p.creation < s.creation))
			order by p.posting_datetime desc, p.creation desc limit 1
		), 0),
		s.actual_qty)
"""

def _page(page, page_len):
	page_len = cint(page_len)
	if page_len not in PAGE_SIZES:
		page_len = PAGE_SIZES[0]
	return max(cint(page), 1), page_len

def _sle_filters(
	from_date=None, to_date=None, warehouse=None, item=None, item_group=None, item_code=None
):
	"""WHERE atas alias s (SLE) + i (Item). Kembali (sql, values, butuh_join_item).
	item = cari (like kode/nama); item_code = satu item persis (modal detail)."""
	conds = ["s.is_cancelled = 0"]
	values = {}
	if item_code:
		conds.append("s.item_code = %(item_code)s")
		values["item_code"] = item_code
	if from_date:
		conds.append("s.posting_datetime >= %(from_dt)s")
		values["from_dt"] = str(getdate(from_date))
	if to_date:
		# batas atas eksklusif hari berikutnya: posting_time punya mikrodetik
		conds.append("s.posting_datetime < %(to_dt)s")
		values["to_dt"] = str(add_days(getdate(to_date), 1))
	if warehouse:
		conds.append("s.warehouse = %(warehouse)s")
		values["warehouse"] = warehouse
	need_item = False
	if item and str(item).strip():
		conds.append("(s.item_code like %(item)s or i.item_name like %(item)s)")
		values["item"] = f"%{str(item).strip()}%"
		need_item = True
	if item_group:
		lft, rgt = frappe.db.get_value("Item Group", item_group, ["lft", "rgt"]) or (0, 0)
		conds.append(
			"i.item_group in (select name from `tabItem Group` where lft >= %(ig_lft)s and rgt <= %(ig_rgt)s)"
		)
		values.update(ig_lft=lft, ig_rgt=rgt)
		need_item = True
	_apply_user_permissions(conds, values, {"Warehouse": "s.warehouse", "Company": "s.company"})
	return " and ".join(conds), values, need_item

def _apply_user_permissions(conds, values, columns):
	user_perms = frappe.permissions.get_user_permissions(frappe.session.user)
	for doctype, column in columns.items():
		allowed = sorted({p.get("doc") for p in user_perms.get(doctype, []) if p.get("doc")})
		if allowed:
			key = "up_" + doctype.lower()
			conds.append(f"{column} in %({key})s")
			values[key] = tuple(allowed)

@frappe.whitelist()
def stock_cards(
	from_date=None,
	to_date=None,
	warehouse=None,
	item=None,
	item_group=None,
	item_code=None,
	page=1,
	page_len=20,
):
	"""Tab Stock Cards + tabel modal detail: satu baris = satu SLE, terbaru dulu."""
	frappe.has_permission("Stock Ledger Entry", "read", throw=True)
	page, page_len = _page(page, page_len)
	rows, total = _stock_cards(
		(from_date, to_date, warehouse, item, item_group, item_code), page_len, (page - 1) * page_len
	)
	return {"rows": rows, "total": total}

def _stock_cards(filter_args, limit, offset):
	where, values, need_item = _sle_filters(*filter_args)
	item_join = "join `tabItem` i on i.name = s.item_code" if need_item else ""

	total = frappe.db.sql(f"select count(*) from {SLE} s {item_join} where {where}", values)[0][0]
	if not total:
		return [], 0

	values.update(limit=limit, offset=offset)
	# ponytail: OFFSET dalam = scan sebanyak offset (~0.3 dtk @100rb SLE tanpa
	# filter); keyset pagination bila ledger tumbuh jauh melebihi itu.
	rows = frappe.db.sql(
		f"""
		select s.name, s.item_code, i.item_name, s.warehouse, s.posting_datetime,
			s.voucher_type, s.voucher_no, s.qty_after_transaction, s.stock_value,
			s.stock_value_difference, {QTY_CHANGE} as qty_change, {UOM_COLS}
		from (
			select s.name from {SLE} s {item_join}
			where {where}
			order by s.posting_datetime desc, s.creation desc
			limit %(limit)s offset %(offset)s
		) pg
		join {SLE} s on s.name = pg.name
		{UOM_JOIN}
		order by s.posting_datetime desc, s.creation desc
		""",
		values,
		as_dict=True,
	)
	remarks = _voucher_remarks(rows)
	out = []
	for r in rows:
		f = r.factor
		out.append(
			{
				"name": r.name,
				"item_code": r.item_code,
				"item_name": r.item_name,
				"warehouse": r.warehouse,
				"posting_datetime": str(r.posting_datetime),
				"voucher_type": r.voucher_type,
				"voucher_no": r.voucher_no,
				"uom": r.uom,
				"qty_before": (r.qty_after_transaction - r.qty_change) / f,
				"qty_in": r.qty_change / f if r.qty_change > 0 else None,
				"qty_out": -r.qty_change / f if r.qty_change < 0 else None,
				"qty_after": r.qty_after_transaction / f,
				"value_before": r.stock_value - r.stock_value_difference,
				"value_change": r.stock_value_difference,
				"value_after": r.stock_value,
				"remarks": remarks.get((r.voucher_type, r.voucher_no)),
			}
		)
	return out, total

def _voucher_remarks(rows):
	"""Remarks dokumen sumber, satu query per voucher_type di halaman ini."""
	by_type = {}
	for r in rows:
		by_type.setdefault(r.voucher_type, set()).add(r.voucher_no)
	out = {}
	for vt, names in by_type.items():
		if not frappe.get_meta(vt).has_field("remarks"):
			continue
		for d in frappe.get_all(vt, filters={"name": ("in", list(names))}, fields=["name", "remarks"]):
			# ERPNext mengisi "No Remarks" sebagai default di beberapa doctype
			if d.remarks and d.remarks.strip() != "No Remarks":
				out[(vt, d.name)] = d.remarks.strip()
	return out

SEARCH_BY = {"name": "i.item_name", "sku": "s.item_code", "item_group": "i.item_group"}

@frappe.whitelist()
def movements(
	from_date=None,
	to_date=None,
	warehouse=None,
	item=None,
	item_group=None,
	item_code=None,
	search=None,
	search_by="name",
	page=1,
	page_len=20,
):
	"""Tab Inventory Movements: satu baris = item+gudang dalam periode.

	Perubahan per SLE (dq/dv) = selisih qty_after_transaction/stock_value dari
	SLE sebelumnya pada item+gudang yang sama (window LAG) — otomatis benar
	utk Stock Reconciliation. Beginning = jumlah dq/dv sebelum from_date
	(= saldo SLE terakhir sebelum periode), IN/OUT = dq/dv positif/negatif
	dalam periode, Ending = jumlah semua (= saldo SLE terakhir periode)."""
	frappe.has_permission("Stock Ledger Entry", "read", throw=True)
	page, page_len = _page(page, page_len)
	agg = _movement_agg(from_date, to_date, warehouse, item, item_group, item_code, search, search_by)
	totals = {
		"begin_value": sum(r.bv for r in agg),
		"in_value": sum(r.iv for r in agg),
		"out_value": sum(r.ov for r in agg),
		"end_value": sum(r.ev for r in agg),
	}
	rows = _movement_rows(agg[(page - 1) * page_len : page * page_len])
	return {"rows": rows, "total": len(agg), "totals": totals}

def _movement_agg(from_date, to_date, warehouse, item, item_group, item_code, search, search_by):
	"""Agregat mentah per item+gudang (qty stock UOM), urut item_code, warehouse."""
	from_dt = str(getdate(from_date)) if from_date else "1900-01-01"
	# history sebelum periode tetap discan (Beginning), jadi from_date tak masuk WHERE
	where, values, _ = _sle_filters(None, to_date, warehouse, item, item_group, item_code)
	if search and str(search).strip():
		where += f" and {SEARCH_BY.get(search_by, SEARCH_BY['name'])} like %(search)s"
		values["search"] = f"%{str(search).strip()}%"
	values["from"] = from_dt

	is_in = "(dq > 0 or (dq = 0 and dv > 0))"
	is_out = "(dq < 0 or (dq = 0 and dv < 0))"
	# ponytail: hasil agregat (<= jumlah Bin, ~3rb) diurut+dipaging di Python agar
	# window ~1 dtk @100rb SLE cukup jalan sekali utk rows+count+total; pindah ke
	# tabel ringkasan per periode bila Bin menembus ratusan ribu.
	return frappe.db.sql(
		f"""
		select item_code, warehouse,
			sum(if(pdt < %(from)s, dq, 0)) bq, sum(if(pdt < %(from)s, dv, 0)) bv,
			sum(if(pdt >= %(from)s and {is_in}, dq, 0)) iq,
			sum(if(pdt >= %(from)s and {is_in}, dv, 0)) iv,
			sum(if(pdt >= %(from)s and {is_out}, -dq, 0)) oq,
			sum(if(pdt >= %(from)s and {is_out}, -dv, 0)) ov,
			sum(dq) eq, sum(dv) ev
		from (
			select s.item_code, s.warehouse, s.posting_datetime pdt,
				s.qty_after_transaction - ifnull(lag(s.qty_after_transaction) over w, 0) dq,
				s.stock_value - ifnull(lag(s.stock_value) over w, 0) dv
			from {SLE} s join `tabItem` i on i.name = s.item_code
			where {where}
			window w as (partition by s.item_code, s.warehouse order by s.posting_datetime, s.creation)
		) x
		group by item_code, warehouse
		having bq or bv or iq or iv or oq or ov
		order by item_code, warehouse
		""",
		values,
		as_dict=True,
	)

def _movement_rows(chunk):
	"""Agregat -> baris tampilan (nama item + qty dalam UOM inventaris)."""
	info = {}
	if chunk:
		info = {
			r.item_code: r
			for r in frappe.db.sql(
				f"""
				select i.name as item_code, i.item_name, {UOM_COLS}
				from `tabItem` i
				left join `tabUOM Conversion Detail` u
					on u.parent = i.name and u.uom = i.custom_default_inventory_unit_of_measure
					and i.custom_default_inventory_unit_of_measure != i.stock_uom
				where i.name in %(codes)s
				""",
				{"codes": tuple({r.item_code for r in chunk})},
				as_dict=True,
			)
		}
	rows = []
	for r in chunk:
		meta = info.get(r.item_code) or frappe._dict(item_name=r.item_code, uom="", factor=1)
		f = meta.factor
		rows.append(
			{
				"item_code": r.item_code,
				"item_name": meta.item_name,
				"warehouse": r.warehouse,
				"uom": meta.uom,
				"begin_qty": r.bq / f,
				"begin_value": r.bv,
				"in_qty": r.iq / f,
				"in_value": r.iv,
				"out_qty": r.oq / f,
				"out_value": r.ov,
				"end_qty": r.eq / f,
				"end_value": r.ev,
			}
		)
	return rows

@frappe.whitelist()
def inventory_info(item_code, warehouse):
	"""Accordion "Inventory Information" di modal detail: master item + Bin saat ini."""
	frappe.has_permission("Stock Ledger Entry", "read", throw=True)
	conds, values = ["b.item_code = %(item)s", "b.warehouse = %(wh)s"], {"item": item_code, "wh": warehouse}
	_apply_user_permissions(conds, values, {"Warehouse": "b.warehouse"})
	info = frappe.db.sql(
		f"""
		select i.item_name, i.item_group, i.stock_uom, i.description, {UOM_COLS},
			b.actual_qty, b.reserved_qty, b.projected_qty, b.valuation_rate, b.stock_value,
			w.company
		from `tabBin` b
		join `tabItem` i on i.name = b.item_code
		join `tabWarehouse` w on w.name = b.warehouse
		left join `tabUOM Conversion Detail` u
			on u.parent = i.name and u.uom = i.custom_default_inventory_unit_of_measure
			and i.custom_default_inventory_unit_of_measure != i.stock_uom
		where {" and ".join(conds)}
		""",
		values,
		as_dict=True,
	)
	if not info:
		return None
	r = info[0]
	f = r.factor
	return {
		"item_name": r.item_name,
		"item_group": r.item_group,
		"description": r.description,
		"company": r.company,
		"stock_uom": r.stock_uom,
		"uom": r.uom,
		"factor": f,
		"actual_qty": r.actual_qty / f,
		"reserved_qty": r.reserved_qty / f,
		"projected_qty": r.projected_qty / f,
		"valuation_rate": r.valuation_rate * f,
		"stock_value": r.stock_value,
	}

@frappe.whitelist()
def filter_options():
	"""Opsi dropdown Warehouse + Item Group. Sengaja tidak lewat get_list
	Warehouse/Item Group: Custom DocPerm pos_next di Warehouse menimpa perm
	standar sehingga Stock User kena 403 — yang dibutuhkan di sini hanya read
	ledger. Warehouse = yang punya Bin (pernah bertransaksi), bukan 800+ gudang."""
	frappe.has_permission("Stock Ledger Entry", "read", throw=True)
	conds, values = ["1=1"], {}
	_apply_user_permissions(conds, values, {"Warehouse": "warehouse"})
	warehouses = frappe.db.sql_list(
		f"select distinct warehouse from `tabBin` where {' and '.join(conds)} order by warehouse",
		values,
	)
	groups = frappe.db.sql_list("select name from `tabItem Group` order by name")
	return {
		"warehouses": warehouses,
		"item_groups": groups,
		"can_export": bool(frappe.has_permission("Stock Ledger Entry", "export")),
		"can_recalculate": bool(frappe.has_permission("Repost Item Valuation", "create")),
	}

# ---------------------------------------------------------------- W40-6 ----
# Export (Excel/CSV) mengikuti filter aktif + Recalculate via Repost Item
# Valuation (doctype native) yang langsung dijalankan di worker long.

EXPORT_MAX = 100_000
STOCK_CARD_HEADER = [
	"Date", "SKU", "Item Name", "Warehouse", "Voucher Type", "Voucher No", "UOM",
	"Stock Before", "In", "Out", "Stock After",
	"Balance Before", "Value Change", "Balance After", "Remarks",
]
MOVEMENT_HEADER = [
	"SKU", "Item Name", "Warehouse", "UOM",
	"Beginning Qty", "Beginning Value", "In Qty", "In Value",
	"Out Qty", "Out Value", "Ending Qty", "Ending Value",
]

@frappe.whitelist()
def export(
	kind="cards",
	file_format="xlsx",
	from_date=None,
	to_date=None,
	warehouse=None,
	item=None,
	item_group=None,
	item_code=None,
	search=None,
	search_by="name",
):
	"""Unduh tab Stock Cards / Inventory Movements (atau Stock Cards modal bila
	item_code+warehouse) sesuai filter — kolom sama dgn layar, qty UOM inventaris."""
	frappe.has_permission("Stock Ledger Entry", "export", throw=True)
	if kind == "movements":
		agg = _movement_agg(from_date, to_date, warehouse, item, item_group, item_code, search, search_by)
		data = [MOVEMENT_HEADER] + [
			[
				r["item_code"], r["item_name"], r["warehouse"], r["uom"],
				r["begin_qty"], r["begin_value"], r["in_qty"], r["in_value"],
				r["out_qty"], r["out_value"], r["end_qty"], r["end_value"],
			]
			for r in _movement_rows(agg)
		]
		data.append(
			["Total", "", "", "", "", sum(r.bv for r in agg), "", sum(r.iv for r in agg),
			 "", sum(r.ov for r in agg), "", sum(r.ev for r in agg)]
		)
		name = "Inventory Movements"
	else:
		# ponytail: satu file dibangun di memori; batas EXPORT_MAX baris —
		# perlu export bertahap (background + File) bila periode melebihi itu.
		rows, total = _stock_cards(
			(from_date, to_date, warehouse, item, item_group, item_code), EXPORT_MAX, 0
		)
		if total > EXPORT_MAX:
			frappe.throw(
				f"{total:,} rows match — export is limited to {EXPORT_MAX:,}. Narrow the time range or filters."
			)
		data = [STOCK_CARD_HEADER] + [
			[
				r["posting_datetime"][:19], r["item_code"], r["item_name"], r["warehouse"],
				r["voucher_type"], r["voucher_no"], r["uom"],
				r["qty_before"], r["qty_in"] or 0, r["qty_out"] or 0, r["qty_after"],
				r["value_before"], r["value_change"], r["value_after"], r["remarks"] or "",
			]
			for r in rows
		]
		name = "Stock Cards" + (f" {item_code}" if item_code else "")
	filename = f"{name} {from_date or ''}_{to_date or ''}".strip()
	if file_format == "csv":
		from frappe.utils.csvutils import to_csv

		frappe.response.update(
			type="binary", filename=filename + ".csv", filecontent=to_csv(data).encode("utf-8-sig")
		)
	else:
		from frappe.utils.xlsxutils import make_xlsx

		# nama sheet Excel maks 31 karakter -> pakai nama tab, bukan nama file
		frappe.response.update(
			type="binary", filename=filename + ".xlsx", filecontent=make_xlsx(data, name[:31]).getvalue()
		)

RECALC_MAX = 500

@frappe.whitelist(methods=["POST"])
def recalculate(
	from_date,
	to_date=None,
	warehouse=None,
	item=None,
	item_group=None,
	item_code=None,
	search=None,
	search_by="name",
):
	"""Buat Repost Item Valuation (Item and Warehouse, mulai from_date) untuk
	setiap item+gudang yang bertransaksi di periode+filter, lalu jalankan di
	worker long. Modal detail = item_code + warehouse persis (satu RIV).
	Kembali nama RIV — klien memantau lewat recalculate_status."""
	frappe.has_permission("Repost Item Valuation", "create", throw=True)
	agg = _movement_agg(from_date, to_date, warehouse, item, item_group, item_code, search, search_by)
	# tampilan penuh: hanya pasangan yang bertransaksi di periode (yang bisa
	# berubah nilainya); modal detail: pasangan itu sendiri walau periode sepi
	pairs = [(r.item_code, r.warehouse) for r in agg if item_code or r.iq or r.iv or r.oq or r.ov]
	if not pairs:
		frappe.throw("No stock transactions to recalculate in this period.")
	if len(pairs) > RECALC_MAX:
		frappe.throw(
			f"{len(pairs):,} item/warehouse pairs match — recalculate is limited to {RECALC_MAX}. Narrow the filters."
		)
	names = []
	for code, wh in pairs:
		riv = frappe.get_doc(
			{
				"doctype": "Repost Item Valuation",
				"based_on": "Item and Warehouse",
				"item_code": code,
				"warehouse": wh,
				"posting_date": getdate(from_date),
				"posting_time": "00:00:00",
			}
		)
		riv.insert()
		riv.submit()
		names.append(riv.name)
	frappe.enqueue(
		_run_reposts, queue="long", timeout=3600, names=names, enqueue_after_commit=True
	)
	return names

def _run_reposts(names):
	# ponytail: scheduler native (repost_entries / run_parallel_reposting) bisa
	# mengambil RIV yang sama bersamaan — repost idempoten, paling buruk kerja dobel.
	from erpnext.stock.doctype.repost_item_valuation.repost_item_valuation import (
		execute_reposting_entry,
	)

	for name in names:
		execute_reposting_entry(name)
		frappe.db.commit()

@frappe.whitelist()
def recalculate_status(names):
	"""Status RIV hasil recalculate (dipoll klien sampai tak ada yang Queued/In Progress)."""
	names = frappe.parse_json(names) if isinstance(names, str) else names
	rows = frappe.get_list(
		"Repost Item Valuation", filters={"name": ("in", names)}, fields=["name", "status"]
	)
	return {r.name: r.status for r in rows}
