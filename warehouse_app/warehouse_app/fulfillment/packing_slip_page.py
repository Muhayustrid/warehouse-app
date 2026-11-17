# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""Packing Slip per Sales Order: list page data, editor save, A4 print and
60x40mm koli labels. Source of truth is the native Packing Slip documents
created by the packing flow; edits update those docs until the Delivery Note
is submitted (then read-only)."""

from __future__ import annotations

import json
import os

import frappe
from frappe.utils import escape_html, flt, getdate

from warehouse_app.warehouse_app.fulfillment.manifest import estimate_weight
from warehouse_app.warehouse_app.fulfillment.permissions import require_read
from warehouse_app.warehouse_app.fulfillment.profile import (
	resolve_dry_exceptions,
	resolve_frozen,
)

COMPANY = "PT. JUARA ROTI INDONESIA"

# Master berat dough/cream/gempi (Harian Gudang - Dough Weight.csv): estimasi
# per baris = berat per item dari baris master dengan qty terbesar <= qty baris.
_DOUGH_WEIGHT_CSV = os.path.join(os.path.dirname(__file__), "dough_weight.csv")
_dough_weight_cache: list[tuple[str, float, float]] | None = None


def _dough_weight_rows() -> list[tuple[str, float, float]]:
	"""[(item_lower, qty, berat_per_unit)] dari CSV; baris header/section dilewati."""
	global _dough_weight_cache
	if _dough_weight_cache is not None:
		return _dough_weight_cache
	rows: list[tuple[str, float, float]] = []
	try:
		with open(_DOUGH_WEIGHT_CSV, encoding="utf-8-sig") as f:
			import csv as _csv

			for raw in _csv.reader(f):
				# Tabel "Item,Weight" di bawah CSV: kolom 1 = berat per unit (kg),
				# berlaku untuk semua rasa termasuk yang tidak punya tabel Qty.
				first = raw[0].strip().lower() if raw else ""
				if first and first != "item" and len(raw) > 1:
					try:
						per_unit_w = flt(raw[1].split("-")[0].strip().replace(",", "."))
					except Exception:
						per_unit_w = 0
					if 0 < per_unit_w < 10:  # <10 kg = berat satuan, bukan qty bulk
						rows.append((first, 1.0, per_unit_w))
				# CSV punya 2 grup kolom: DOUGH (0-3) dan CREAM/GEMPI (5-8).
				for base in (0, 5):
					if len(raw) < base + 4 or not raw[base] or raw[base].strip().lower() == "item":
						continue
					try:
						qty = flt(raw[base + 1])
					except Exception:
						continue
					if qty <= 0:
						continue
					# "0,8" atau "33,92 - 34,85" -> angka pertama, koma desimal -> titik
					berat_item = raw[base + 3].split("-")[0].strip().replace(",", ".")
					try:
						per_unit = flt(berat_item)
					except Exception:
						continue
					if per_unit <= 0:
						continue
					rows.append((raw[base].strip().lower(), qty, per_unit))
	except OSError:
		pass
	_dough_weight_cache = rows
	return rows


def csv_estimasi(item_name: str, qty: float) -> float | None:
	name = (item_name or "").strip().lower()
	if not name:
		return None
	best = None
	best_qty = -1
	for csv_name, csv_qty, per_unit in _dough_weight_rows():
		if (csv_name in name or name in csv_name) and csv_qty <= qty and csv_qty > best_qty:
			best, best_qty = per_unit, csv_qty
	return round(best * qty, 2) if best else None


# ------------------------------------------------------------------ pure logic


def slip_lines_from_ps_items(
	ps_items: list[list[dict]],
	categories: list[str] | None = None,
	frozen: set | None = None,
	dry_exceptions: set | None = None,
) -> list[dict]:
	"""Flatten per-koli Packing Slip item lists into editor lines: one line per
	koli (items may repeat across koli). Frozen rows carry estimated_weight
	(weight_per_unit x qty); dry rows are hand-weighed (blank).
	When a profile frozen set is given, classification is per item via its
	item_group (Frozen Item Group settings), overriding the koli box_size."""
	lines: list[dict] = []
	for idx, items in enumerate(ps_items, start=1):
		if not items:
			continue
		category = (categories[idx - 1] if categories and idx - 1 < len(categories) else "frozen").lower()
		for item in items:
			qty = flt(item.get("qty"))
			if qty <= 0:
				continue
			line_category = category
			if frozen is not None:
				if dry_exceptions and item.get("item_code") in dry_exceptions:
					line_category = "dry"
				elif item.get("item_group") in frozen:
					line_category = "frozen"
				else:
					line_category = "dry"
			line = {
				"item_code": item.get("item_code") or "",
				"item_name": item.get("item_name") or "",
				"qty": qty,
				"uom": item.get("stock_uom") or "",
				"koli_no": idx,
				"koli": 1,
				"berat": "",
				"category": "frozen" if "frozen" in line_category else "dry",
				"net_weight": flt(item.get("net_weight")),
			}
			# Estimasi dari master dough weight; fallback weight_per_unit item master.
			est = csv_estimasi(line["item_name"], qty)
			if est is None:
				est = estimate_weight(qty, item.get("weight_per_unit"))
			if est is not None:
				line["estimated_weight"] = est
				if line["category"] == "frozen":
					line["berat"] = est
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


def validate_slip_lines(lines: list[dict], dn_items: set[str]) -> list[str]:
	"""Editor-line validation before persist: item must exist on the DN,
	qty > 0. Koli number defaults to 1. Returns a list of error messages."""
	errors: list[str] = []
	for idx, line in enumerate(lines or [], start=1):
		item_code = line.get("item_code")
		if not item_code or item_code not in dn_items:
			errors.append(f"Baris {idx}: item {item_code or '(kosong)'} tidak ada di Delivery Note.")
			continue
		if flt(line.get("qty")) <= 0:
			errors.append(f"Baris {idx}: {item_code} qty harus > 0.")
	return errors


def packing_summary(ps_docs: list[dict]) -> dict:
	"""Aggregate packing results per DN from its Packing Slip docs, for the
	Fulfillment Packing tab: koli dry/frozen counts + weights + driver."""
	koli_frozen = koli_dry = 0
	weight_frozen = weight_dry = 0.0
	driver = ""
	vehicle_no = ""
	for doc in ps_docs:
		if (doc.get("custom_box_size") or "B") == "K":
			koli_frozen += 1
			weight_frozen += flt(doc.get("net_weight_pkg"))
		else:
			koli_dry += 1
			weight_dry += flt(doc.get("net_weight_pkg"))
		driver = driver or (doc.get("custom_driver") or "")
		vehicle_no = vehicle_no or (doc.get("custom_vehicle_no") or "")
	return {
		"packed": bool(ps_docs),
		"koli_frozen": koli_frozen,
		"koli_dry": koli_dry,
		"weight_frozen": round(weight_frozen, 2),
		"weight_dry": round(weight_dry, 2),
		"driver": driver,
		"vehicle_no": vehicle_no,
	}


# ---------------------------------------------------------------- frappe layer


def load_packing_slips(company: str, from_date: str, to_date: str) -> dict:
	"""List of packing papers per Sales Order: every SO with a non-cancelled
	Delivery Note (picked/packed). Editable until the DN is submitted."""
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
		filters={"against_sales_order": ("in", sorted(so_by_name))},
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

	ps_counts: dict[str, int] = {}
	for row in frappe.get_all(
		"Packing Slip",
		filters={"docstatus": ("<", 2)},
		fields=["delivery_note"],
		limit_page_length=0,
	):
		ps_counts[row["delivery_note"]] = ps_counts.get(row["delivery_note"], 0) + 1

	# Packing results per DN (for the Fulfillment Packing tab summary).
	ps_docs = frappe.get_all(
		"Packing Slip",
		filters={"docstatus": ("<", 2)},
		fields=["name", "delivery_note", "from_case_no", "custom_box_size", "net_weight_pkg", "custom_driver", "custom_vehicle_no"],
		order_by="from_case_no asc",
		limit_page_length=0,
	)
	ps_by_dn: dict[str, list[dict]] = {}
	for row in ps_docs:
		ps_by_dn.setdefault(row["delivery_note"], []).append(row)

	slips: list[dict] = []
	for so_name, so in so_by_name.items():
		dn_names = sorted({dn for dn in dn_by_so.get(so_name, []) if dn_status.get(dn) not in (None, 2)})
		if not dn_names:
			continue
		dn_docstatus = min(dn_status[dn] for dn in dn_names)
		ps_total = sum(ps_counts.get(dn, 0) for dn in dn_names)
		# Aggregate packing results across every DN of the SO.
		summary = packing_summary([doc for dn in dn_names for doc in ps_by_dn.get(dn, [])])
		slips.append(
			{
				"name": so_name,
				"sales_order": so_name,
				"customer": so.customer,
				"customer_name": so.customer_name or so.customer,
				"po_no": so.po_no or "",
				"delivery_date": str(so.delivery_date),
				"delivery_note": dn_names[0],
				"status": "Read-only" if dn_docstatus == 1 else ("Editable" if ps_total else "Belum Packing"),
				"editable": dn_docstatus != 1,
				"packing": summary,
				"modified": str(max(
					frappe.db.get_value("Delivery Note", dn, "modified") for dn in dn_names
				)),
			}
		)
	# Driver/vehicle are per delivery day (shared by all packings of the date).
	day_driver = next((s["packing"]["driver"] for s in slips if s["packing"]["driver"]), "")
	day_vehicle = next((s["packing"]["vehicle_no"] for s in slips if s["packing"]["vehicle_no"]), "")
	return {"company": company, "slips": slips, "driver": day_driver, "vehicle_no": day_vehicle}


def save_packing_driver(company: str, date: str, driver: str, vehicle_no: str) -> dict:
	"""Apply one driver + vehicle number to every draft Packing Slip of the
	given delivery date (driver is shared across packings, not per slip)."""
	require_read()
	res = load_packing_slips(company, date or "", date or "")
	updated = 0
	for row in res["slips"]:
		if not row.get("editable"):
			continue
		for sib in frappe.get_all(
			"Packing Slip", filters={"delivery_note": row["delivery_note"], "docstatus": 0}, pluck="name", limit_page_length=0
		):
			frappe.db.set_value("Packing Slip", sib, {"custom_driver": driver or "", "custom_vehicle_no": vehicle_no or ""})
			updated += 1
	frappe.db.commit()
	return {"updated": updated}


def load_packing_slip(name: str) -> dict:
	"""Editor payload for one Sales Order: koli lines from its Packing Slips
	(fallback: DN items when packing has not run yet), header, totals."""
	require_read()
	so = frappe.db.get_value(
		"Sales Order", name, ["customer", "customer_name", "po_no", "delivery_date"], as_dict=True
	)
	if not so:
		frappe.throw(f"Sales Order {name} not found.", frappe.DoesNotExistError)
	header = {
		"customer": so.customer,
		"customer_name": so.customer_name or so.customer,
		"po_no": so.po_no or "",
		"delivery_date": str(so.delivery_date),
	}

	dn_links = frappe.get_all(
		"Delivery Note Item",
		filters={"against_sales_order": name},
		pluck="parent",
		limit_page_length=0,
	)
	dn_names = sorted(
		{
			dn
			for dn in dn_links
			if frappe.db.get_value("Delivery Note", dn, "docstatus") != 2
		}
	)
	if not dn_names:
		frappe.throw(f"No Delivery Note for {name}.", frappe.DoesNotExistError)
	# Prefer the draft DN (still editable); a submitted sibling is read-only.
	draft_dns = [dn for dn in dn_names if frappe.db.get_value("Delivery Note", dn, "docstatus") == 0]
	dn_name = draft_dns[-1] if draft_dns else dn_names[-1]
	editable = bool(draft_dns)

	siblings = frappe.get_all(
		"Packing Slip",
		filters={"delivery_note": dn_name, "docstatus": ("<", 2)},
		fields=["name", "from_case_no", "custom_box_size", "net_weight_pkg", "custom_driver", "custom_vehicle_no"],
		order_by="from_case_no asc",
		limit_page_length=0,
	)
	if siblings:
		# Classification per item from Frozen Item Group settings (profile),
		# so mixed dry/frozen koli split correctly; box_size stays only as the
		# physical koli marker when no profile exists.
		docs = [frappe.get_doc("Packing Slip", s.name) for s in siblings]
		company = frappe.db.get_value("Delivery Note", dn_name, "company")
		frozen_set, dry_exc = _frozen_profile(company)
		item_groups: dict = {}
		if frozen_set is not None:
			codes = sorted({it.item_code for d in docs for it in d.items})
			item_groups = {
				r.name: r.item_group
				for r in frappe.get_all(
					"Item",
					filters={"name": ["in", codes or ["-"]]},
					fields=["name", "item_group"],
					limit_page_length=0,
				)
			}
		categories = ["frozen" if (s.custom_box_size == "K") else "dry" for s in siblings]
		ps_items = [
			[
				{
					"item_code": it.item_code,
					"item_name": it.item_name or it.item_code,
					"qty": flt(it.qty),
					"net_weight": flt(it.net_weight),
					"stock_uom": it.stock_uom,
					**({"item_group": item_groups.get(it.item_code, "")} if frozen_set is not None else {}),
				}
				for it in d.items
			]
			for d in docs
		]
		lines = slip_lines_from_ps_items(
			ps_items, categories=categories, frozen=frozen_set, dry_exceptions=dry_exc
		)
		# Hand-weighed weight per koli persists on the doc (net_weight_pkg).
		for line in lines:
			sibling = siblings[line["koli_no"] - 1]
			if flt(sibling.net_weight_pkg):
				line["berat"] = flt(sibling.net_weight_pkg)
	else:
		lines = _lines_from_dn(dn_name)

	# DN items for the editor's add-row picker.
	dn_item_rows = frappe.get_all(
		"Delivery Note Item",
		filters={"parent": dn_name},
		fields=["item_code", "item_name", "stock_uom", "uom", "qty"],
		order_by="idx asc",
		limit_page_length=0,
	)

	return {
		"name": name,
		"delivery_note": dn_name,
		"editable": editable,
		"header": header,
		"lines": lines,
		"dn_items": dn_item_rows,
		"driver": next((s.custom_driver or "" for s in siblings if s.custom_driver), ""),
		"vehicle_no": next((s.custom_vehicle_no or "" for s in siblings if s.custom_vehicle_no), ""),
		"totals": slip_totals(lines),
	}


def _frozen_profile(company: str) -> tuple[set | None, set]:
	"""(frozen item groups, dry exceptions) of the company's profile;
	(None, set()) when there is no profile."""
	profile = frappe.get_all(
		"Warehouse Fulfillment Profile",
		filters={"company": company},
		fields=["name", "enabled", "frozen_item_group", "include_child_item_groups", "dry_item_exceptions"],
		limit_page_length=1,
	)
	if not profile:
		return None, set()
	return resolve_frozen(profile[0]), resolve_dry_exceptions(profile[0])


def _lines_from_dn(dn_name: str) -> list[dict]:
	"""Fallback editor lines from DN items (packing not run yet): one line per
	item, frozen/dry via Item master category, sequential koli numbers."""
	company = frappe.db.get_value("Delivery Note", dn_name, "company")
	frozen, dry_exceptions = _frozen_profile(company)
	items = frappe.get_all(
		"Delivery Note Item",
		filters={"parent": dn_name},
		fields=["item_code", "item_name", "qty", "uom", "stock_uom", "item_group"],
		order_by="idx asc",
		limit_page_length=0,
	)
	dry_koli = frozen_koli = 0
	lines = []
	for it in items:
		if it.item_code in dry_exceptions:
			category = "dry"
		elif frozen and it.item_group in frozen:
			category = "frozen"
		else:
			category = "dry"
		if category == "frozen":
			frozen_koli += 1
			koli_no = frozen_koli
		else:
			dry_koli += 1
			koli_no = dry_koli
		qty = flt(it.qty)
		line = {
			"item_code": it.item_code,
			"item_name": it.item_name or it.item_code,
			"qty": qty,
			"uom": it.stock_uom or it.uom,
			"koli_no": koli_no,
			"koli": 1,
			"berat": "",
			"category": category,
			"net_weight": 0,
		}
		# Estimasi sama seperti jalur Packing Slip: CSV master, lalu Item master.
		est = csv_estimasi(line["item_name"], qty)
		if est is None:
			wpu = frappe.db.get_value("Item", it.item_code, "weight_per_unit")
			est = estimate_weight(qty, wpu)
		if est is not None:
			line["estimated_weight"] = est
		lines.append(line)
	return lines


def save_packing_slip(name: str, lines: list, driver: str = "", vehicle_no: str = "") -> dict:
	"""Persist edited koli lines onto draft Packing Slip documents of the SO's
	Delivery Note (one doc per koli). Blocked once the DN is submitted."""
	require_read()
	if isinstance(lines, str):
		try:
			lines = json.loads(lines)
		except ValueError:
			frappe.throw("Invalid lines payload.", frappe.ValidationError)
	data = load_packing_slip(name)
	if not data["editable"]:
		frappe.throw("Packing Slip is read-only: Delivery Note already submitted.", frappe.ValidationError)
	dn_name = data["delivery_note"]

	# Validate against the DN item set before touching any document.
	dn_items = {
		row.item_code
		for row in frappe.get_all(
			"Delivery Note Item", filters={"parent": dn_name}, fields=["item_code"], limit_page_length=0
		)
	}
	errors = validate_slip_lines(lines or [], dn_items)
	if errors:
		frappe.throw("; ".join(errors), frappe.ValidationError)

	# Group edited lines per koli number; delete extra slips, update/create the rest.
	by_koli: dict[int, list[dict]] = {}
	for line in lines or []:
		koli = max(1, int(flt(line.get("koli_no")) or 1))
		by_koli.setdefault(koli, []).append(line)

	siblings = frappe.get_all(
		"Packing Slip",
		filters={"delivery_note": dn_name, "docstatus": 0},
		fields=["name", "from_case_no"],
		order_by="from_case_no asc",
		limit_page_length=0,
	)
	sibling_by_case = {int(s.from_case_no or 1): s.name for s in siblings}

	dn_doc = frappe.get_doc("Delivery Note", dn_name)
	dn_row_by_item = {}
	for row in dn_doc.items:
		dn_row_by_item.setdefault(row.item_code, row)

	for koli in sorted(by_koli):
		target = sibling_by_case.get(koli)
		if target:
			doc = frappe.get_doc("Packing Slip", target)
			doc.set("items", [])
		else:
			doc = frappe.new_doc("Packing Slip")
			doc.delivery_note = dn_name
			doc.from_case_no = koli
			doc.to_case_no = koli
		# Category persists on the doc: box_size K=frozen/B=dry.
		first = by_koli[koli][0]
		doc.custom_box_size = "K" if first.get("category") == "frozen" else "B"
		# Hand-weighed weight per koli: the input is one weight per koli, so
		# take it from the koli's first line only. It persists on item rows
		# (net_weight) because calculate_net_total_pkg recomputes header =
		# sum(net_weight x qty).
		weight = flt(by_koli[koli][0].get("berat")) or 0
		total_qty = sum(flt(l.get("qty")) or 0 for l in by_koli[koli])
		doc.net_weight_pkg = weight
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
					# per-unit weight = koli weight / total qty, so the ERPNext
					# recompute (net_weight x qty) lands on the hand-weighed value.
					"net_weight": (weight / total_qty) if (weight and total_qty) else 0,
					"weight_uom": "Kg",
				},
			)
		if not doc.name:
			doc.insert(ignore_permissions=True)  # insert after items: PS requires >=1 line
		doc.save(ignore_permissions=True)

	# Koli rows removed in the editor: delete those draft slips.
	for case_no, sib_name in sibling_by_case.items():
		if case_no not in by_koli:
			frappe.delete_doc("Packing Slip", sib_name, ignore_permissions=True, force=1)

	# Driver + vehicle number: uniform across every draft PS of the DN.
	if driver or vehicle_no:
		for sib in frappe.get_all(
			"Packing Slip",
			filters={"delivery_note": dn_name, "docstatus": 0},
			pluck="name",
			limit_page_length=0,
		):
			frappe.db.set_value(
				"Packing Slip", sib, {"custom_driver": driver, "custom_vehicle_no": vehicle_no}
			)

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
			berat_html = escape_html(str(berat)) if berat == "" or isinstance(berat, str) else f"{flt(berat):g}"
			out.append(
				f"<tr><td>{escape_html(line['item_code'])} &mdash; {escape_html(line['item_name'])}</td>"
				f"<td class='num'>{flt(line['qty']):g}</td><td class='num'>{escape_html(str(line.get('uom') or ''))}</td>"
				f"<td class='num'>{line['koli_no']}</td><td class='num'>{berat_html}</td></tr>"
			)
		return "".join(out)

	totals = data["totals"]
	dry_rows = rows_html("dry")
	frozen_rows = rows_html("frozen")
	driver = data.get("driver") or "-"
	vehicle_no = data.get("vehicle_no") or "-"

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
<span>TO: <strong>{escape_html(header.get('customer_name') or '')}</strong></span>
<span>PO No: <strong>{escape_html(header.get('po_no') or '-')}</strong></span>
<span>Delivery date: <strong>{escape_html(header.get('delivery_date') or '-')}</strong></span>
<span>Driver: <strong>{escape_html(driver)}</strong></span>
<span>No. Mobil: <strong>{escape_html(vehicle_no)}</strong></span>
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
	return _labels_page(_slip_label_divs(name), f"Label Koli {escape_html(name)}")


def packing_slips_labels_html(company: str | None = None, date: str | None = None) -> str:
	"""All koli labels for packing slips packed on `date` (company-wide),
	concatenated in one print run."""
	require_read()
	company = company or frappe.defaults.get_user_default("Company")
	if not company:
		frappe.throw("Company is required.", frappe.ValidationError)
	res = load_packing_slips(company, date or "", date or "")
	divs = []
	for row in res["slips"]:
		if not (row.get("packing") or {}).get("packed"):
			continue
		divs.append(_slip_label_divs(row["name"]))
	title = f"Label Koli {company} {date or ''}".strip()
	return _labels_page("".join(divs), title)


def sheet_koli_total(lines: list[dict]) -> int:
	"""Total colly of one card: sum of per-line koli."""
	return sum(max(1, int(flt(l.get("koli")) or 1)) for l in lines)


def sheet_card_html(customer_name: str, lines: list[dict]) -> str:
	"""One customer card of the combined packing sheet (pure, testable): yellow
	caption row (customer, Dry count, Colly total) + DRY and FROZEN tables
	(Item/Qty/Koli/Berat/B-K/Picker/Estimasi), each with its own Total row.
	B/K and Picker stay blank (hand-filled on paper)."""

	def cat_table(cat_lines: list[dict], label: str) -> str:
		rows = []
		koli_sum = 0
		for line in cat_lines:
			koli = max(1, int(flt(line.get("koli")) or 1))
			koli_sum += koli
			est = line.get("estimated_weight")
			est_s = f"{flt(est):g}" if est not in (None, "") else ""
			rows.append(
				f"<tr><td class='it'>{escape_html(line.get('item_name') or '')}</td>"
				f"<td class='qty'>{flt(line.get('qty')):g}</td><td class='k'>{koli}</td>"
				f"<td class='w'>{escape_html(str(line.get('berat') or ''))}</td>"
				f"<td class='hand'></td><td class='hand'></td><td class='est'>{est_s}</td></tr>"
			)
		head = (
			"<tr><th>Item</th><th>Qty</th><th>Koli</th><th>Berat</th>"
			"<th>B / K</th><th>Picker</th><th>Estimasi</th></tr>"
		)
		foot = f"<tr class='tf'><td colspan='2'>Total {label}</td><td>{koli_sum}</td><td colspan='4'></td></tr>"
		return f"<div class='sect'>{label}</div><table>{head}{''.join(rows)}{foot}</table>"

	dry = [l for l in lines if l.get("category") != "frozen"]
	frozen = [l for l in lines if l.get("category") == "frozen"]
	body = ""
	if dry:
		body += cat_table(dry, "DRY")
	if frozen:
		body += cat_table(frozen, "FROZEN")
	dry_koli = sum(max(1, int(flt(l.get("koli")) or 1)) for l in dry)
	koli_sum = sheet_koli_total(lines)
	return (
		f"<div class='card'><div class='cap'><span class='cust'>{escape_html(customer_name)}</span>"
		f"<span class='dry'>Dry : {dry_koli}</span><span class='blank'></span><span class='colly'>Colly</span></div>"
		f"{body}</div>"
	)


def load_packing_sheet(company: str, date: str) -> dict:
	"""Combined packing sheet for one delivery date: per-SO slips with editor
	lines attached (sheet view + print)."""
	require_read()
	res = load_packing_slips(company, date or "", date or "")
	for slip in res["slips"]:
		try:
			full = load_packing_slip(slip["sales_order"])
		except frappe.DoesNotExistError:
			slip["lines"] = []
			continue
		slip["lines"] = full["lines"]
		slip["totals"] = full["totals"]
		slip["driver"] = full["driver"]
		slip["vehicle_no"] = full["vehicle_no"]
		slip["dn_items"] = full["dn_items"]
	return res


def packing_sheet_html(company: str | None = None, date: str | None = None) -> str:
	"""A4 print of the combined packing sheet: per-customer yellow cards,
	blank B/K + Picker to hand-fill, TOTAL KOLI, truck box table, MOBIL/DRIVER."""
	require_read()
	company = company or frappe.defaults.get_user_default("Company")
	if not company:
		frappe.throw("Company is required.", frappe.ValidationError)
	res = load_packing_sheet(company, date or "")
	groups: dict[tuple[str, str], list[str]] = {}
	koli_per_group: dict[tuple[str, str], int] = {}
	order: list[tuple[str, str]] = []
	for slip in res["slips"]:
		if not slip["lines"]:
			continue
		key = (slip.get("driver") or "", slip.get("vehicle_no") or "")
		if key not in groups:
			groups[key] = []
			order.append(key)
			koli_per_group[key] = 0
		groups[key].append(sheet_card_html(slip["customer_name"], slip["lines"]))
		koli_per_group[key] += sheet_koli_total(slip["lines"])
	body = ""
	for driver, vehicle_no in order:
		key = (driver, vehicle_no)
		body += "".join(groups[key])
		body += (
			f"<div class='boxfoot'><div class='total'>TOTAL {koli_per_group[key]} KOLI</div>"
			"<table class='boxtable'>"
			"<tr><th></th><th>BERANGKAT</th><th>PULANG</th></tr>"
			"<tr><td>BOX ABU</td><td></td><td></td></tr>"
			"<tr><td>KRANJANG BESAR</td><td></td><td></td></tr>"
			"<tr><td>KRANJANG KECIL</td><td></td><td></td></tr>"
			"</table>"
			f"<div class='mobil'><span>MOBIL : {escape_html(vehicle_no)}</span>"
			f"<span>DRIVER : {escape_html(driver)}</span></div></div>"
		)
	title = f"Packing List {company} {date or ''}".strip()
	return _sheet_page(body, title)


def _sheet_page(body: str, title: str) -> str:
	return f"""<!doctype html><html><head><meta charset='utf-8'><title>{escape_html(title)}</title>
<style>
@page{{size:A4 portrait;margin:8mm}}
body{{font-family:Arial,Helvetica,sans-serif;font-size:9px;margin:0;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
.grid{{column-count:2;column-gap:5mm}}
.card{{break-inside:avoid;margin-bottom:4mm;border:1.5px solid #111;background:#fff}}
.sect{{font-weight:bold;font-size:8.5px;padding:0.6mm 1.5mm}}
.cap{{display:flex;gap:3mm;align-items:center;background:#ffe94a;border-bottom:1.5px solid #111;padding:0.8mm 2mm}}
.cap .cust{{flex:1;font-weight:bold;font-size:10px}}
.cap .dry,.cap .colly{{white-space:nowrap;font-size:9px}}
.cap .blank{{display:inline-block;width:14mm;height:4mm;background:#fff;border:1px solid #111}}
table{{width:100%;border-collapse:collapse}}
th,td{{border:1px solid #111;padding:0.6mm 1.5mm;text-align:left}}
th{{background:#ffe94a;font-size:8.5px}}
td.qty,td.k,td.w,td.est{{text-align:center}}
td.hand{{width:11mm}}
tr.tf td{{background:#ffe94a;font-weight:bold}}
.boxtable td,.boxtable th{{height:6mm}}
.boxfoot{{break-inside:avoid;margin-top:3mm}}
.total{{font-size:12px;font-weight:bold;margin-top:3mm}}
.mobil{{margin-top:3mm;font-size:10px;font-weight:bold}}
.mobil span{{display:inline-block;margin-right:10mm}}
</style></head><body>
<div class='grid'>{body or "<p>Belum ada packing pada tanggal ini.</p>"}</div>
<script>window.print()</script></body></html>"""


def _label_groups(lines: list[dict]) -> list[dict]:
	"""One label group per (category, koli): a mixed koli splits into a FROZEN
	and a DRY label. FROZEN first, then koli order; weight per category."""
	groups: dict[tuple, dict] = {}
	for line in lines:
		key = (line["category"], line["koli_no"])
		g = groups.setdefault(
			key,
			{"category": line["category"], "koli_no": line["koli_no"], "items": [], "master": 0.0, "hand": ""},
		)
		g["items"].append(f"{line['item_code']} - {line['item_name']}")
		g["master"] += flt(line.get("net_weight")) * flt(line.get("qty"))
		if line.get("berat"):
			g["hand"] = str(line["berat"])
	return sorted(groups.values(), key=lambda g: (0 if g["category"] == "frozen" else 1, g["koli_no"]))


def _slip_label_divs(name: str) -> str:
	"""Label <div>s for one packing slip, in koli order (1/total first)."""
	data = load_packing_slip(name)
	header = data["header"]
	lines = data["lines"]

	# Numbering per category: FROZEN 1/N, DRY 1/M (mixed koli -> two labels).
	groups = _label_groups(lines)
	counts: dict[str, int] = {}
	seen: dict[str, int] = {}
	for g in groups:
		counts[g["category"]] = counts.get(g["category"], 0) + 1
	labels = []
	for g in groups:
		seen[g["category"]] = seen.get(g["category"], 0) + 1
		category = g["category"].upper()
		master = g["master"]
		weight = f"{round(master, 2):g}" if master > 0 else g["hand"]
		items = "<br>".join(escape_html(i) for i in g["items"])
		labels.append(
			f"""<div class='label'>
<div class='co'>PT. JUARA ROTI INDONESIA</div>
<div class='body'>
<div class='left'><div class='ratio'><span class='n'>{seen[g['category']]}</span><span class='tot'>/{counts[g['category']]}</span></div><div class='wgrp'><div class='bw'>{category}</div><div class='kg'>{escape_html(str(weight)) if str(weight).strip() else '—'}</div></div></div>
<div class='right'>
<div class='cust'>{escape_html(header.get('customer_name') or '')}</div>
<div class='items'>{items}</div>
<span class='badge'>{category}</span>
</div>
</div>
</div>"""
		)
	return "".join(labels)


def _labels_page(body: str, title: str) -> str:
	return f"""<!doctype html><html><head><meta charset='utf-8'><title>{title}</title>
<style>
@page{{size:60mm 40mm;margin:1.5mm}}
body{{font-family:Arial,Helvetica,sans-serif;font-size:8px;margin:0}}
.label{{width:57mm;height:37mm;border:1.5px solid #111;page-break-after:always;box-sizing:border-box;display:flex;flex-direction:column;overflow:hidden;margin:0 auto;background:#fff}}
.co{{text-align:center;font-size:10.5px;font-weight:bold;letter-spacing:.12em;border-bottom:2px solid #111;padding:1mm 0 0.8mm}}
.body{{flex:1;display:flex;min-height:0}}
.left{{width:38%;border-right:1.5px solid #111;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;gap:1.6mm}}
.ratio .n{{font-size:24px;font-weight:bold}}
.ratio .tot{{font-size:11px;font-weight:bold;color:#111}}
.wgrp{{display:flex;flex-direction:column;align-items:center}}
.bw{{font-size:7.5px;letter-spacing:.14em;color:#111}}
.kg{{font-size:24px;font-weight:bold;line-height:1.05;min-height:1em}}
.right{{flex:1;padding-left:1.8mm;padding-right:1.5mm;display:flex;flex-direction:column;justify-content:center}}
.cust{{font-size:12.5px;font-weight:bold;line-height:1.2;text-transform:uppercase}}
.items{{font-size:9px;line-height:1.35;margin-top:0.6mm;word-break:break-word}}
.badge{{align-self:flex-start;display:inline-block;background:#fff;border:1.5px solid #111;border-radius:2px;padding:0.3mm 2mm;font-size:9.5px;font-weight:bold;margin-top:1mm}}
</style></head><body>
{body or "<div class='label'>Tidak ada label.</div>"}
<script>window.print()</script></body></html>"""
