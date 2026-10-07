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

def _sle_filters(from_date=None, to_date=None, warehouse=None, item=None, item_group=None):
	"""WHERE atas alias s (SLE) + i (Item). Kembali (sql, values, butuh_join_item)."""
	conds = ["s.is_cancelled = 0"]
	values = {}
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
	from_date=None, to_date=None, warehouse=None, item=None, item_group=None, page=1, page_len=20
):
	"""Tab Stock Cards: satu baris = satu SLE, terbaru dulu."""
	frappe.has_permission("Stock Ledger Entry", "read", throw=True)
	page, page_len = _page(page, page_len)
	where, values, need_item = _sle_filters(from_date, to_date, warehouse, item, item_group)
	item_join = "join `tabItem` i on i.name = s.item_code" if need_item else ""

	total = frappe.db.sql(f"select count(*) from {SLE} s {item_join} where {where}", values)[0][0]
	if not total:
		return {"rows": [], "total": 0}

	values.update(limit=page_len, offset=(page - 1) * page_len)
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
				"value_after": r.stock_value,
			}
		)
	return {"rows": out, "total": total}

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
	return {"warehouses": warehouses, "item_groups": groups}
