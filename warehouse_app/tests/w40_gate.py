# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto
# License: MIT

# Gate W40 — perhitungan halaman Inventory (inventory.movements/stock_cards).
#
# Jalankan:
#   docker exec frappe-backend-1 bench --site inventory.localhost execute \
#       warehouse_app.tests.w40_gate.run_gate
#
# Kontrak output: TEPAT satu baris GATE_JSON:{...} (ok, checks, error opsional).
#
# Fixture (prefix "ZZTEST-W40"): 1 Item stock UOM + UOM inventaris faktor 12,
# allow_negative_stock per item. SE (qty dalam stock UOM):
#   D-10  receipt 24 @100                    -> Beginning periode hari ini
#   hari ini (banyak transaksi sehari): receipt 12 @100, issue 6, issue 12,
#         issue 30 -> stok -12 (negatif)
# Diverifikasi:
#   1. Beginning = 2 (24/12) Rp2.400; IN = 1; OUT = 4; Ending = -1 (negatif).
#   2. Beginning + IN - OUT = Ending (qty & nilai), Ending = SLE terakhir periode.
#   3. Periode sebelum transaksi pertama -> tak ada baris.
#   4. Periode tanpa transaksi setelahnya -> IN/OUT 0, Beginning = Ending.
#   5. Totals footer = jumlah Beginning/Ending seluruh baris.
#   6. stock_cards: 4 baris hari ini, terbaru dulu, qty dalam UOM inventaris.
#   7. export csv/xlsx mengikuti filter; recalculate -> RIV Completed, saldo tetap.

import json
import traceback
from unittest.mock import patch

import frappe
from frappe.utils import add_days, flt, nowdate

from warehouse_app import upgrade
from warehouse_app.tests.guard import count_residue, item_inventory_defaults
from warehouse_app.warehouse_app import inventory

PREFIX = "ZZTEST-W40"
TRACKED = {"se": []}

class GateAborted(Exception):
	pass

def run_gate():
	checks = {}
	error = None

	def check(name, ok, evidence):
		checks[name] = str(evidence) if ok else f"GAGAL: {evidence}"

	try:
		_run_gate(check)
	except GateAborted:
		pass
	except Exception:
		error = traceback.format_exc()
	finally:
		try:
			_teardown(check)
		except Exception as te:
			check("teardown", False, f"teardown error {type(te).__name__}: {te}")
		payload = {
			"ok": error is None and not any(v.startswith("GAGAL") for v in checks.values()),
			"checks": checks,
		}
		if error:
			payload["error"] = error[-2000:]
		print("GATE_JSON:" + json.dumps(payload, ensure_ascii=False))

	if error:
		raise SystemExit(1)

def _se(company, item, warehouse, stock, purpose, qty, posting_date=None):
	row = {
		"item_code": item,
		"qty": qty,
		"uom": stock,
		"stock_uom": stock,
		"conversion_factor": 1,
	}
	if purpose == "Material Receipt":
		row.update(t_warehouse=warehouse, basic_rate=100)
	else:
		row["s_warehouse"] = warehouse
	doc = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"company": company,
			"stock_entry_type": purpose,
			"purpose": purpose,
			"items": [row],
		}
	)
	if posting_date:
		doc.set_posting_time = 1
		doc.posting_date = posting_date
	doc.insert()
	doc.submit()
	TRACKED["se"].append(doc.name)
	frappe.db.commit()
	return doc

def _run_gate(check):
	check("pre_clean", *_sweep())

	company = frappe.get_all("Company", pluck="name", limit=1)
	company = company[0] if company else None
	warehouse = company and frappe.db.get_value(
		"Warehouse", {"company": company, "is_group": 0, "disabled": 0}, "name", order_by="name"
	)
	stock = next((u for u in ("Nos", "Unit") if frappe.db.exists("UOM", u)), None)
	alt = next((u for u in ("Box", "Pack") if frappe.db.exists("UOM", u)), None)
	group = frappe.db.get_value("Item Group", {"is_group": 0}, "name", order_by="name")
	ok = all((company, warehouse, stock, alt, group))
	check("preflight", ok, f"company={company!r}, wh={warehouse!r}, uom={stock!r}/{alt!r}, group={group!r}")
	if not ok:
		raise GateAborted()

	item = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": PREFIX + "-" + frappe.generate_hash(length=8),
			"item_name": PREFIX + " Gate Item",
			"item_group": group,
			"stock_uom": stock,
			"is_stock_item": 1,
			"allow_negative_stock": 1,
			"uoms": [{"uom": alt, "conversion_factor": 12}],
			"item_defaults": item_inventory_defaults(company),
			upgrade.ITEM_UOM_FIELD: alt,
		}
	).insert()
	frappe.db.commit()

	today = nowdate()
	_se(company, item.name, warehouse, stock, "Material Receipt", 24, add_days(today, -10))
	_se(company, item.name, warehouse, stock, "Material Receipt", 12)
	for qty in (6, 12, 30):
		_se(company, item.name, warehouse, stock, "Material Issue", qty)

	def mv(from_date, to_date):
		return inventory.movements(
			from_date=from_date, to_date=to_date, warehouse=warehouse, item=item.name, page_len=20
		)

	res = mv(today, today)
	r = res["rows"][0] if res["rows"] else {}
	check(
		"period_values",
		res["total"] == 1
		and r.get("uom") == alt
		and abs(r["begin_qty"] - 2) < 1e-6
		and abs(r["begin_value"] - 2400) < 0.01
		and abs(r["in_qty"] - 1) < 1e-6
		and abs(r["in_value"] - 1200) < 0.01
		and abs(r["out_qty"] - 4) < 1e-6
		and abs(r["end_qty"] + 1) < 1e-6,
		f"row={r}",
	)
	last = frappe.db.sql(
		"""select qty_after_transaction, stock_value from `tabStock Ledger Entry`
		where item_code=%s and warehouse=%s and is_cancelled=0
		order by posting_datetime desc, creation desc limit 1""",
		(item.name, warehouse),
	)[0]
	check(
		"ending_invariant_negative",
		r
		and abs(r["begin_qty"] + r["in_qty"] - r["out_qty"] - r["end_qty"]) < 1e-6
		and abs(r["begin_value"] + r["in_value"] - r["out_value"] - r["end_value"]) < 0.01
		and abs(r["end_qty"] * 12 - flt(last[0])) < 1e-6
		and abs(r["end_value"] - flt(last[1])) < 0.01
		and r["end_qty"] < 0,
		f"end=({r.get('end_qty')}, {r.get('end_value')}), last_sle={last}",
	)
	check(
		"totals_footer",
		abs(res["totals"]["begin_value"] - r.get("begin_value", 0)) < 0.01
		and abs(res["totals"]["end_value"] - r.get("end_value", 0)) < 0.01,
		f"totals={res['totals']}",
	)

	before = mv(add_days(today, -20), add_days(today, -15))
	check("no_history_no_row", before["total"] == 0, f"total={before['total']}")

	after = mv(add_days(today, 1), add_days(today, 2))
	a = after["rows"][0] if after["rows"] else {}
	check(
		"no_tx_in_period",
		after["total"] == 1
		and a["in_qty"] == 0
		and a["out_qty"] == 0
		and abs(a["begin_qty"] - a["end_qty"]) < 1e-6
		and abs(a["end_qty"] + 1) < 1e-6,
		f"row={a}",
	)

	cards = inventory.stock_cards(from_date=today, to_date=today, item=item.name, page_len=20)
	first = cards["rows"][0] if cards["rows"] else {}
	check(
		"stock_cards_day",
		cards["total"] == 4
		and abs(first.get("qty_out", 0) - 2.5) < 1e-6
		and abs(first.get("qty_after", 0) + 1) < 1e-6
		and abs(cards["rows"][-1]["qty_in"] - 1) < 1e-6,
		f"total={cards['total']}, first={first}",
	)

	# W40-6: export mengikuti filter (xlsx + csv) & recalculate -> RIV Completed
	frappe.response.clear()
	inventory.export(kind="movements", file_format="csv", from_date=today, to_date=today, item=item.name)
	csv_text = frappe.response.get("filecontent", b"").decode("utf-8-sig")
	frappe.response.clear()
	inventory.export(kind="cards", file_format="xlsx", from_date=today, to_date=today, item=item.name)
	xlsx = frappe.response.get("filecontent", b"")
	check(
		"export",
		item.name in csv_text
		and csv_text.count("\n") == 3  # header + 1 baris + Total
		and xlsx[:2] == b"PK"
		and frappe.response.get("filename", "").endswith(".xlsx"),
		f"csv_lines={csv_text.count(chr(10))}, xlsx_bytes={len(xlsx)}",
	)
	frappe.response.clear()

	queued = []
	with patch.object(frappe, "enqueue", lambda fn, **kw: queued.append((fn, kw))):
		names = inventory.recalculate(from_date=today, to_date=today, item_code=item.name, warehouse=warehouse)
	frappe.db.commit()
	queued[0][0](**{k: v for k, v in queued[0][1].items() if k == "names"})
	status = inventory.recalculate_status(names)
	after_recalc = mv(today, today)["rows"][0]
	check(
		"recalculate",
		len(names) == 1
		and status.get(names[0]) == "Completed"
		and abs(after_recalc["end_qty"] - r["end_qty"]) < 1e-6
		and abs(after_recalc["end_value"] - r["end_value"]) < 0.01,
		f"names={names}, status={status}, end=({after_recalc['end_qty']}, {after_recalc['end_value']})",
	)

def _teardown(check):
	frappe.set_user("Administrator")
	ok, evidence = _sweep()
	residue = count_residue(PREFIX, {"Stock Entry": TRACKED["se"], "User": []})
	zero = all(v == 0 for v in residue.values())
	check("teardown", ok and zero, f"{evidence}; residu={residue}")
	TRACKED["se"] = []

def _sweep():
	errors = []
	# site menamai Item via naming series -> cari juga lewat item_name
	items = frappe.get_all(
		"Item",
		or_filters=[["item_code", "like", PREFIX + "%"], ["item_name", "like", PREFIX + "%"]],
		pluck="name",
	)
	se_names = set(TRACKED["se"])
	if items:
		se_names.update(
			frappe.get_all("Stock Entry Detail", filters={"item_code": ("in", items)}, pluck="parent")
		)
	# terbaru dulu: issue dibatalkan sebelum receipt
	for name in sorted(se_names, key=lambda n: frappe.db.get_value("Stock Entry", n, "creation") or "", reverse=True):
		try:
			if not frappe.db.exists("Stock Entry", name):
				continue
			doc = frappe.get_doc("Stock Entry", name)
			if doc.docstatus == 1:
				doc.cancel()
			frappe.delete_doc("Stock Entry", name, force=1)
		except Exception as e:
			errors.append(f"SE {name}: {type(e).__name__}: {str(e)[:120]}")
	if items:
		for dt in ("Stock Ledger Entry", "Repost Item Valuation", "Bin"):
			frappe.db.delete(dt, {"item_code": ("in", items)})
	for name in items:
		try:
			frappe.delete_doc("Item", name, force=1)
		except Exception as e:
			errors.append(f"Item {name}: {type(e).__name__}: {str(e)[:120]}")
	frappe.db.delete("Version", {"docname": ("like", PREFIX + "%")})
	frappe.db.commit()
	return (not errors), ("bersih" if not errors else "; ".join(errors[:5]))
