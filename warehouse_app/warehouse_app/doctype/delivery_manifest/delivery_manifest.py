# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

from __future__ import annotations

import frappe
from frappe.contacts.doctype.address.address import get_default_address
from frappe.model.document import Document
from frappe.utils import flt

from warehouse_app.warehouse_app.fulfillment.manifest import (
	bucket_lines,
	estimate_weight,
	total_weight,
)
from warehouse_app.warehouse_app.fulfillment.permissions import is_manifest_driver_only
from warehouse_app.warehouse_app.fulfillment.profile import (
	get_profile,
	resolve_dry_exceptions,
	resolve_frozen,
)


class DeliveryManifest(Document):
	def packing_list_data(self):
		"""Derive dry/frozen item rows from the linked Delivery Notes at print
		time, so the manifest never stores duplicated item/qty."""
		return _packing_list_data(self)


# Provinsi yang sama ditulis beda di master Address (dilihat 2026-11-13):
# "Daerah Khusus Ibukota Jakarta" (3) vs "DKI Jakarta" (1). Canonical = nama resmi.
_STATE_ALIASES = {
	"DKI Jakarta": "Daerah Khusus Ibukota Jakarta",
}


def customer_region(customer: str) -> str:
	"""Wilayah an outlet belongs to: the customer's primary address province
	(`state`), falling back to `city`. Empty when the customer has no address."""
	address = get_default_address("Customer", customer)
	if not address:
		return ""
	state = (
		frappe.db.get_value("Address", address, "state")
		or frappe.db.get_value("Address", address, "city")
		or ""
	)
	return _STATE_ALIASES.get(state, state)


def _packing_list_data(doc) -> dict:
	profile = get_profile(doc.company) or {}
	frozen = resolve_frozen(profile)
	dry_exceptions = resolve_dry_exceptions(profile) if profile else set()

	# Vehicle/driver live on the region row (Delivery Manifest Region).
	region_meta: dict[str, dict] = {}
	for region in doc.regions or []:
		region_meta.setdefault(region.region, {"vehicle": region.vehicle, "driver": region.driver})

	dn_names = [
		row.delivery_note for row in (doc.outlets or []) if getattr(row, "delivery_note", None)
	]
	dn_by_name: dict[str, Document] = {}
	item_codes: set[str] = set()
	for name in dn_names:
		if not frappe.db.exists("Delivery Note", name):
			continue
		dn = frappe.get_doc("Delivery Note", name)
		dn_by_name[name] = dn
		for item in dn.items:
			item_codes.add(item.item_code)

	item_master = _item_master(item_codes)

	regions: dict[str, dict] = {}
	for row in doc.outlets or []:
		dn = dn_by_name.get(getattr(row, "delivery_note", None))
		if dn is None:
			continue
		lines = []
		for item in dn.items:
			master = item_master.get(item.item_code, {})
			lines.append(
				{
					"item_code": item.item_code,
					"item_name": item.item_name or master.get("item_name"),
					"qty": flt(item.qty),
					"uom": item.uom,
					"conversion_factor": flt(getattr(item, "conversion_factor", 0)),
					"item_group": master.get("item_group"),
					"custom_fulfillment_category": master.get("custom_fulfillment_category"),
					"weight_per_unit": flt(master.get("weight_per_unit")),
				}
			)
		if not lines:
			continue
		dry_lines, frozen_lines = bucket_lines(lines, frozen, dry_exceptions=dry_exceptions)
		for line in frozen_lines:
			line["estimated_weight"] = estimate_weight(line["qty"], line["weight_per_unit"])

		region_name = (row.region or "").strip() or customer_region(dn.customer) or "-"
		bucket = regions.setdefault(
			region_name,
			{
				"region": region_name,
				"vehicle": "",
				"driver": "",
				"outlets": [],
			},
		)
		meta = region_meta.get(region_name)
		if meta:
			bucket["vehicle"] = meta["vehicle"] or ""
			bucket["driver"] = meta["driver"] or ""
		bucket["outlets"].append(
			{
				"customer": dn.customer,
				"customer_name": dn.customer_name,
				"delivery_note": dn.name,
				"picker": getattr(row, "picker", None) or "",
				"dry_koli": _int_or_zero(getattr(row, "dry_koli", None)),
				"frozen_koli": _int_or_zero(getattr(row, "frozen_koli", None)),
				"dry": dry_lines,
				"frozen": frozen_lines,
			}
		)

	region_rows = sorted(regions.values(), key=lambda r: r["region"])
	frozen_rows = [line for region in region_rows for outlet in region["outlets"] for line in outlet["frozen"]]
	for region in region_rows:
		region["frozen_total_weight"] = total_weight(
			[line for outlet in region["outlets"] for line in outlet["frozen"]]
		)
	return {
		"company": doc.company,
		"delivery_date": doc.delivery_date,
		"box_big_depart": doc.box_big_depart,
		"box_small_depart": doc.box_small_depart,
		"box_big_return": doc.box_big_return,
		"box_small_return": doc.box_small_return,
		"regions": region_rows,
		"frozen_total_weight": total_weight(frozen_rows),
	}


def manifest_candidates(company: str, delivery_date: str) -> list[dict]:
	"""Draft/submitted Delivery Notes whose Sales Order ships on ``delivery_date``,
	grouped by customer, to pre-fill the manifest dialog."""
	so_names = frappe.get_all(
		"Sales Order",
		filters={"company": company, "delivery_date": delivery_date, "docstatus": 1},
		pluck="name",
	)
	if not so_names:
		return []

	dn_links = frappe.get_all(
		"Delivery Note Item",
		filters={"against_sales_order": ("in", so_names)},
		fields=["parent", "against_sales_order"],
		limit_page_length=0,
	)
	dn_names = sorted({row["parent"] for row in dn_links})
	if not dn_names:
		return []

	dn_rows = frappe.get_list(
		"Delivery Note",
		filters={"name": ("in", dn_names)},
		fields=["name", "customer", "customer_name", "docstatus", "status"],
		limit_page_length=0,
	)

	grouped: dict[str, dict] = {}
	for row in dn_rows:
		if row.docstatus == 2:  # cancelled
			continue
		bucket = grouped.setdefault(
			row.customer,
			{
				"customer": row.customer,
				"customer_name": row.customer_name,
				"delivery_notes": [],
			},
		)
		bucket["delivery_notes"].append(
			{"name": row.name, "docstatus": row.docstatus, "status": row.status}
		)

	outlets = sorted(grouped.values(), key=lambda row: row["customer_name"] or row["customer"])
	for outlet in outlets:
		outlet["delivery_notes"].sort(key=lambda row: row["name"])
		outlet["region"] = customer_region(outlet["customer"])
	return outlets


def save_manifest(payload: dict) -> dict:
	"""Create or update a Delivery Manifest from the dialog payload. A lone
	Stock User may only edit driver/vehicle of an existing manifest's regions."""
	existing = payload.get("name")
	if existing and not frappe.db.exists("Delivery Manifest", existing):
		raise frappe.ValidationError(f"Delivery Manifest {existing!r} does not exist.")
	doc = frappe.get_doc("Delivery Manifest", existing) if existing else frappe.new_doc("Delivery Manifest")

	if existing and doc.docstatus != 0:
		raise frappe.ValidationError("Only draft Delivery Manifests can be edited.")

	if is_manifest_driver_only():
		return _save_driver_fields(doc, payload)

	doc.company = payload.get("company") or frappe.defaults.get_user_default("Company")
	doc.delivery_date = payload.get("delivery_date")
	doc.box_big_depart = _int_or_zero(payload.get("box_big_depart"))
	doc.box_small_depart = _int_or_zero(payload.get("box_small_depart"))
	doc.box_big_return = _int_or_zero(payload.get("box_big_return"))
	doc.box_small_return = _int_or_zero(payload.get("box_small_return"))

	doc.regions = []
	for row in payload.get("regions") or []:
		region = _clean(row.get("region"))
		if not region:
			continue
		doc.append(
			"regions",
			{
				"region": region,
				"vehicle": _clean(row.get("vehicle")),
				"driver": _clean(row.get("driver")),
			},
		)

	doc.outlets = []
	for row in payload.get("outlets") or []:
		dn_name = row.get("delivery_note")
		if not dn_name or not frappe.db.exists("Delivery Note", dn_name):
			raise frappe.ValidationError(f"Delivery Note {dn_name!r} does not exist.")
		dn_docstatus = frappe.db.get_value("Delivery Note", dn_name, "docstatus")
		if dn_docstatus == 2:
			raise frappe.ValidationError(f"Delivery Note {dn_name} is cancelled.")
		dn = frappe.get_doc("Delivery Note", dn_name)
		doc.append(
			"outlets",
			{
				"customer": row.get("customer") or dn.customer,
				"customer_name": dn.customer_name,
				"delivery_note": dn_name,
				"region": _clean(row.get("region")),
				"picker": _clean(row.get("picker")),
				"dry_koli": _int_or_zero(row.get("dry_koli")),
				"frozen_koli": _int_or_zero(row.get("frozen_koli")),
			},
		)

	if existing:
		doc.save(ignore_permissions=True)
	else:
		doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"name": doc.name}


def _save_driver_fields(doc: Document, payload: dict) -> dict:
	"""Lone Stock User path: only driver/vehicle per existing region may change."""
	if not doc.name:
		raise frappe.PermissionError("Driver/mobil hanya bisa diisi pada manifest yang sudah ada.")
	by_region = {row.region: row for row in (doc.regions or [])}
	changed = False
	for row in payload.get("regions") or []:
		region = _clean(row.get("region"))
		target = by_region.get(region)
		if target is None:
			continue
		target.vehicle = _clean(row.get("vehicle"))
		target.driver = _clean(row.get("driver"))
		changed = True
	if changed:
		doc.save(ignore_permissions=True)
		frappe.db.commit()
	return {"name": doc.name}


def get_manifests(company: str, delivery_date: str) -> dict:
	"""Manifest list for the day, to reopen an existing packing list. Includes
	``driver_only`` so the UI can lock non-driver fields for a lone Stock User."""
	names = frappe.get_all(
		"Delivery Manifest",
		filters={"company": company, "delivery_date": delivery_date},
		fields=["name", "delivery_date", "modified"],
		order_by="creation desc",
		limit_page_length=0,
	)
	manifests = [
		{
			"name": row.name,
			"delivery_date": row.delivery_date,
			"modified": row.modified,
			"outlet_count": frappe.db.count(
				"Delivery Manifest Outlet", {"parent": row.name}
			),
		}
		for row in names
	]
	return {"manifests": manifests, "driver_only": is_manifest_driver_only()}


def get_manifest(name: str) -> dict:
	doc = frappe.get_doc("Delivery Manifest", name)
	return {
		"name": doc.name,
		"company": doc.company,
		"delivery_date": doc.delivery_date,
		"box_big_depart": doc.box_big_depart,
		"box_small_depart": doc.box_small_depart,
		"box_big_return": doc.box_big_return,
		"box_small_return": doc.box_small_return,
		"regions": [
			{"region": r.region, "vehicle": r.vehicle or "", "driver": r.driver or ""}
			for r in (doc.regions or [])
		],
		"outlets": [
			{
				"customer": o.customer,
				"customer_name": o.customer_name,
				"delivery_note": o.delivery_note,
				"region": o.region or "",
				"picker": o.picker or "",
				"dry_koli": o.dry_koli or 0,
				"frozen_koli": o.frozen_koli or 0,
			}
			for o in (doc.outlets or [])
		],
	}


def _int_or_zero(value):
	try:
		return max(0, int(value or 0))
	except (TypeError, ValueError):
		return 0


def _clean(value):
	return str(value or "").strip()


def _item_master(item_codes: set[str]) -> dict[str, dict]:
	if not item_codes:
		return {}
	rows = frappe.get_list(
		"Item",
		filters={"name": ("in", sorted(item_codes))},
		fields=[
			"name",
			"item_name",
			"item_group",
			"weight_per_unit",
			"custom_fulfillment_category",
		],
		limit_page_length=0,
	)
	return {row.name: row for row in rows}