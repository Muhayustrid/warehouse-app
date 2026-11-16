# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""Read-only queue and preview loaders for F1."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from warehouse_app.warehouse_app.fulfillment.generation import (
	GenerationError,
	pending_stock_qty,
)
from warehouse_app.warehouse_app.fulfillment.profile import (
	get_profile,
	resolve_dry_exceptions,
	resolve_frozen,
)
from warehouse_app.warehouse_app.fulfillment.queue import (
	derive_stage,
	group_counts,
	is_eligible,
	safe_classify,
)

STAGES = ("open", "picking", "packing", "ready", "partially_delivered", "completed", "exception")
ROLES = {"Stock Manager", "Stock User", "System Manager"}


def load_order_queue(
	company=None,
	search=None,
	stage=None,
	stages=None,
	from_date=None,
	to_date=None,
	page=1,
	page_length=20,
) -> dict:
	_require_roles()
	company = _resolve_company(company)
	page = _positive_int(page, "page")
	page_length = min(_positive_int(page_length, "page_length"), 100)
	stage = (stage or "all").strip().lower()
	if stage not in ("all", *STAGES):
		frappe.throw(_("Invalid fulfillment stage: {0}").format(stage))
	# stages = comma-separated multi-stage filter (tab UI); overrides stage.
	stage_set = None
	if stages and str(stages).strip():
		stage_set = {s.strip().lower() for s in str(stages).split(",") if s.strip()}
		invalid = stage_set - set(STAGES)
		if invalid:
			frappe.throw(_("Invalid fulfillment stage: {0}").format(", ".join(sorted(invalid))))

	profile = get_profile(company)
	frozen = resolve_frozen(profile)
	dry_exceptions = resolve_dry_exceptions(profile)
	profile_ok = frozen is not None
	profile_payload = _profile_payload(profile, profile_ok)
	profile_warnings = _profile_warnings(profile, frozen)

	so_rows = _query_sales_orders(company, search, from_date, to_date)
	so_names = [row["name"] for row in so_rows]
	items_by_so = _load_sales_order_items(so_names) if so_names else {}
	documents = _load_documents(so_names) if so_names else _empty_documents()

	rows = []
	for so in so_rows:
		items = items_by_so.get(so["name"], [])
		if not items:
			continue
		has_outstanding = any(_deliverable_outstanding(item) > 0 for item in items)
		if not is_eligible(
			so.get("docstatus"),
			so.get("status"),
			so.get("per_delivered"),
			has_outstanding,
			allow_completed=True,
		):
			continue

		classified = [_classify_item(item, frozen, dry_exceptions=dry_exceptions) for item in items]
		counts = group_counts(classified)
		warnings = sorted(
			set(profile_warnings + [item["reason"] for item in classified if item.get("reason")])
		)
		row_docs = {
			"pick_lists": documents["pick_lists_by_so"].get(so["name"], []),
			"delivery_notes": documents["delivery_notes_by_so"].get(so["name"], []),
			"packing_slips": documents["packing_slips_by_so"].get(so["name"], []),
		}
		stage_value = _stage_for(
			profile_ok,
			counts["unclassified"] > 0,
			row_docs["pick_lists"],
			row_docs["delivery_notes"],
			documents["draft_dn_fully_packed"],
			has_outstanding,
		)
		can_generate, can_generate_reason = _can_generate_for_so(so, classified, profile_ok)
		rows.append(
			{
				"sales_order": so["name"],
				"customer": so.get("customer"),
				"customer_name": so.get("customer_name"),
				"transaction_date": so.get("transaction_date"),
				"delivery_date": so.get("delivery_date"),
				"stage": stage_value,
				"run": _active_run_summary(so["name"]),
				"dry_count": counts["dry"],
				"frozen_count": counts["frozen"],
				"unclassified_count": counts["unclassified"],
				"pick_lists": _doc_counts(row_docs["pick_lists"]),
				"delivery_notes": _doc_counts(row_docs["delivery_notes"]),
				"packing_slips": _doc_counts(row_docs["packing_slips"]),
				"warnings": warnings,
				"can_generate": can_generate,
				"can_generate_reason": can_generate_reason,
			}
		)

	counts = {"all": len(rows), **{name: 0 for name in STAGES}}
	for row in rows:
		counts[row["stage"]] += 1

	if stage != "all":
		rows = [row for row in rows if row["stage"] == stage]
	elif stage_set:
		rows = [row for row in rows if row["stage"] in stage_set]

	total = len(rows)
	start = (page - 1) * page_length
	return {
		"company": company,
		"companies": _readable_companies(),
		"profile": profile_payload,
		"counts": counts,
		"rows": rows[start : start + page_length],
		"total": total,
		"page": page,
		"page_length": page_length,
		"warnings": profile_warnings,
	}


def load_order_preview(sales_order: str) -> dict:
	_require_roles()
	if not frappe.db.exists("Sales Order", sales_order):
		frappe.throw(_("Sales Order {0} does not exist.").format(sales_order), frappe.DoesNotExistError)
	if not frappe.has_permission("Sales Order", doc=sales_order, ptype="read"):
		raise frappe.PermissionError

	so = frappe.get_doc("Sales Order", sales_order)
	companies = _readable_companies()
	if so.company not in [row["name"] for row in companies]:
		raise frappe.PermissionError

	profile = get_profile(so.company)
	frozen = resolve_frozen(profile)
	dry_exceptions = resolve_dry_exceptions(profile)
	profile_ok = frozen is not None
	profile_warnings = _profile_warnings(profile, frozen)
	item_groups = _item_group_map([item.item_code for item in so.items])
	items = []
	groups = {"dry": [], "frozen": [], "unclassified": []}
	for row in so.items:
		item_group = item_groups.get(row.item_code)
		classification, reason = safe_classify(
			item_group,
			frozen,
			item_code=row.item_code,
			dry_exceptions=dry_exceptions,
			item_override=getattr(row, "custom_fulfillment_category", None),
		)
		item = {
			"sales_order_item": row.name,
			"item_code": row.item_code,
			"item_name": row.item_name,
			"item_group": item_group,
			"classification": classification,
			"reason": reason,
			"uom": row.uom,
			"conversion_factor": row.conversion_factor,
			"ordered": flt(row.qty),
			"picked": flt(row.picked_qty),
			"delivered": flt(row.delivered_qty),
			"outstanding": _outstanding(row),
			"stock_reserved_qty": flt(row.stock_reserved_qty),
			"delivered_by_supplier": flt(row.delivered_by_supplier),
		}
		items.append(item)
		groups[classification].append(item)

	documents = _load_documents([so.name])
	row_docs = {
		"pick_lists": documents["pick_lists_by_so"].get(so.name, []),
		"delivery_notes": documents["delivery_notes_by_so"].get(so.name, []),
		"packing_slips": documents["packing_slips_by_so"].get(so.name, []),
	}
	has_outstanding = any(
		_deliverable_outstanding(item) > 0 for item in items
	)
	stage = _stage_for(
		profile_ok,
		bool(groups["unclassified"]),
		row_docs["pick_lists"],
		row_docs["delivery_notes"],
		documents["draft_dn_fully_packed"],
		has_outstanding,
	)
	warnings = sorted(
		set(profile_warnings + [item["reason"] for item in items if item.get("reason")])
	)
	can_generate, can_generate_reason = _can_generate_for_so(so, items, profile_ok)
	run = _active_run_summary(so.name)

	return {
		"sales_order": {
			"name": so.name,
			"customer": so.customer,
			"customer_name": so.customer_name,
			"company": so.company,
			"transaction_date": so.transaction_date,
			"delivery_date": so.delivery_date,
			"status": so.status,
			"docstatus": so.docstatus,
			"modified": str(so.modified),
		},
		"modified": str(so.modified),
		"can_generate": can_generate,
		"can_generate_reason": can_generate_reason,
		"run": run,
		"profile": _profile_payload(profile, profile_ok),
		"stage": stage,
		"groups": groups,
		"items": items,
		"documents": {
			"pick_lists": [_public_doc(row) for row in row_docs["pick_lists"]],
			"delivery_notes": [_public_doc(row) for row in row_docs["delivery_notes"]],
			"packing_slips": [
				{**_public_doc(row), "delivery_note": row.get("delivery_note")}
				for row in row_docs["packing_slips"]
			],
		},
		"warnings": warnings,
	}


def _require_roles() -> None:
	if not set(frappe.get_roles()).intersection(ROLES):
		raise frappe.PermissionError("Fulfillment queue requires a warehouse role.")


def _readable_companies() -> list[dict]:
	return frappe.get_list(
		"Company",
		fields=["name"],
		order_by="name asc",
		limit_page_length=0,
	)


def _resolve_company(company: str | None) -> str:
	companies = _readable_companies()
	names = [row["name"] for row in companies]
	if not names:
		raise frappe.PermissionError
	if company:
		if company not in names:
			raise frappe.PermissionError
		return company
	default = frappe.defaults.get_user_default("Company")
	if default in names:
		return default
	return names[0]


def _positive_int(value, field: str) -> int:
	try:
		value = int(value)
	except (TypeError, ValueError):
		frappe.throw(_("{0} must be a positive integer.").format(field))
	if value < 1:
		frappe.throw(_("{0} must be a positive integer.").format(field))
	return value


def _profile_payload(profile, frozen: set[str] | None) -> dict:
	enabled = bool(profile and profile.get("enabled"))
	val = profile.get("enable_packing_slip") if profile else None
	return {
		"configured": bool(enabled and profile.get("frozen_item_group") and frozen is not None),
		"enabled": enabled,
		"frozen_item_group": profile.get("frozen_item_group") if profile else None,
		"dry_display_name": (profile.get("dry_display_name") if profile else None) or "Dry",
		"frozen_display_name": (profile.get("frozen_display_name") if profile else None)
		or "Frozen",
		"enable_packing_slip": 1 if val is None else int(val),
	}


def _profile_warnings(profile, frozen: set[str] | None) -> list[str]:
	if not profile:
		return ["profile_missing"]
	if not profile.get("enabled"):
		return ["profile_disabled"]
	if not profile.get("frozen_item_group") or frozen is None:
		return ["profile_invalid"]
	return []


def _query_sales_orders(
	company: str, search: str | None, from_date: str | None, to_date: str | None
) -> list[dict]:
	filters = [
		["docstatus", "=", 1],
		["company", "=", company],
		["status", "not in", ["Closed", "Cancelled"]],
	]
	if from_date:
		filters.append(["transaction_date", ">=", from_date])
	if to_date:
		filters.append(["transaction_date", "<=", to_date])
	or_filters = None
	if search and search.strip():
		like = f"%{search.strip()}%"
		or_filters = [["name", "like", like], ["customer_name", "like", like]]

	rows = frappe.get_list(
		"Sales Order",
		fields=[
			"name",
			"customer",
			"customer_name",
			"company",
			"transaction_date",
			"delivery_date",
			"status",
			"docstatus",
			"per_delivered",
			"per_picked",
		],
		filters=filters,
		or_filters=or_filters,
		order_by="name asc",
		limit_page_length=0,
	)
	rows.sort(
		key=lambda row: (
			flt(row.get("per_delivered")) >= 100,
			not bool(row.get("delivery_date")),
			row.get("delivery_date") or "",
			row.get("name"),
		)
	)
	return rows


def _load_sales_order_items(so_names: list[str]) -> dict[str, list[dict]]:
	# Child-table links use get_all: get_list returns only name for child doctypes.
	# SO names are already permission-filtered; parent docs are re-fetched with get_list.
	rows = frappe.get_all(
		"Sales Order Item",
		filters={"parent": ("in", so_names)},
		fields=[
			"name",
			"parent",
			"item_code",
			"item_name",
			"item_group",
			"qty",
			"picked_qty",
			"delivered_qty",
			"stock_reserved_qty",
			"delivered_by_supplier",
			"warehouse",
			"uom",
			"conversion_factor",
		],
		limit_page_length=0,
	)
	item_groups = _item_group_map([row.item_code for row in rows])

	items_by_so: dict[str, list[dict]] = {}
	for row in rows:
		item = {
			"name": row.name,
			"parent": row.parent,
			"item_code": row.item_code,
			"item_name": row.item_name,
			"item_group": item_groups.get(row.item_code),
			"qty": row.qty,
			"picked_qty": row.picked_qty,
			"delivered_qty": row.delivered_qty,
			"stock_reserved_qty": row.stock_reserved_qty,
			"delivered_by_supplier": row.delivered_by_supplier,
			"warehouse": row.warehouse,
			"uom": row.uom,
			"conversion_factor": row.conversion_factor,
		}
		item["outstanding"] = _outstanding(item)
		items_by_so.setdefault(row.parent, []).append(item)
	return items_by_so


def _item_group_map(item_codes: list[str]) -> dict[str, str]:
	if not item_codes:
		return {}
	rows = frappe.get_list(
		"Item",
		filters={"name": ("in", sorted(set(item_codes)))},
		fields=["name", "item_group"],
		limit_page_length=0,
	)
	group_names = sorted({row.item_group for row in rows if row.item_group})
	leaf_groups = set()
	if group_names:
		leaf_groups = {
			row.name
			for row in frappe.get_list(
				"Item Group",
				filters={"name": ("in", group_names), "is_group": 0},
				fields=["name"],
				limit_page_length=0,
			)
		}
	return {
		row.name: row.item_group if row.item_group in leaf_groups else None
		for row in rows
	}


def _load_documents(so_names: list[str]) -> dict:
	# Child link rows use get_all because get_list strips child fields. SO names are
	# already permission-filtered and parent documents are re-fetched with get_list.
	pick_lists_by_so: dict[str, list[dict]] = {}
	delivery_notes_by_so: dict[str, list[dict]] = {}
	packing_slips_by_so: dict[str, list[dict]] = {}

	pl_links = frappe.get_all(
		"Pick List Item",
		filters={"sales_order": ("in", so_names)},
		fields=["parent", "sales_order"],
		limit_page_length=0,
	)
	pl_names = sorted({row["parent"] for row in pl_links})
	pl_docs = _get_docs("Pick List", pl_names, ["name", "docstatus", "status", "creation"])
	pl_by_name = {row["name"]: row for row in pl_docs}
	pl_seen = set()
	for row in pl_links:
		key = (row["sales_order"], row["parent"])
		if key in pl_seen:
			continue
		pl_seen.add(key)
		doc = pl_by_name.get(row["parent"])
		if doc:
			pick_lists_by_so.setdefault(row["sales_order"], []).append(doc)

	dn_links = frappe.get_all(
		"Delivery Note Item",
		filters={"against_sales_order": ("in", so_names)},
		fields=["parent", "against_sales_order"],
		limit_page_length=0,
	)
	dn_names = sorted({row["parent"] for row in dn_links})
	dn_docs = _get_docs(
		"Delivery Note", dn_names, ["name", "docstatus", "status", "creation"]
	)
	dn_by_name = {row["name"]: row for row in dn_docs}
	dn_seen = set()
	for row in dn_links:
		key = (row["against_sales_order"], row["parent"])
		if key in dn_seen:
			continue
		dn_seen.add(key)
		doc = dn_by_name.get(row["parent"])
		if doc:
			delivery_notes_by_so.setdefault(row["against_sales_order"], []).append(doc)

	ps_docs = (
		frappe.get_list(
			"Packing Slip",
			filters={"delivery_note": ("in", dn_names)},
			fields=["name", "docstatus", "status", "delivery_note", "creation"],
			limit_page_length=0,
		)
		if dn_names
		else []
	)
	ps_by_dn: dict[str, list[dict]] = {}
	for row in ps_docs:
		ps_by_dn.setdefault(row["delivery_note"], []).append(row)
	ps_seen = set()
	for row in dn_links:
		doc = dn_by_name.get(row["parent"])
		if not doc:
			continue
		for ps in ps_by_dn.get(doc["name"], []):
			key = (row["against_sales_order"], ps["name"])
			if key in ps_seen:
				continue
			ps_seen.add(key)
			packing_slips_by_so.setdefault(row["against_sales_order"], []).append(ps)

	draft_dn_names = [row["name"] for row in dn_docs if row.get("docstatus") == 0]
	draft_dn_fully_packed = {}
	if draft_dn_names:
		dn_items = frappe.get_all(
			"Delivery Note Item",
			filters={"parent": ("in", draft_dn_names)},
			fields=["parent", "qty", "packed_qty"],
			limit_page_length=0,
		)
		by_dn: dict[str, list[dict]] = {}
		for row in dn_items:
			by_dn.setdefault(row["parent"], []).append(row)
		for name in draft_dn_names:
			rows = by_dn.get(name, [])
			draft_dn_fully_packed[name] = bool(rows) and all(
				flt(row.get("packed_qty")) >= flt(row.get("qty")) for row in rows
			)

	return {
		"pick_lists_by_so": pick_lists_by_so,
		"delivery_notes_by_so": delivery_notes_by_so,
		"packing_slips_by_so": packing_slips_by_so,
		"draft_dn_fully_packed": draft_dn_fully_packed,
	}


def _empty_documents() -> dict:
	return {
		"pick_lists_by_so": {},
		"delivery_notes_by_so": {},
		"packing_slips_by_so": {},
		"draft_dn_fully_packed": {},
	}


def _get_docs(doctype: str, names: list[str], fields: list[str]) -> list[dict]:
	if not names:
		return []
	rows = frappe.get_list(
		doctype,
		filters={"name": ("in", names)},
		fields=fields,
		limit_page_length=0,
	)
	return sorted(rows, key=lambda row: row.get("creation") or "")


def _classify_item(
	item: dict,
	frozen: set[str] | None,
	dry_exceptions: set[str] | None = None,
) -> dict:
	classification, reason = safe_classify(
		item.get("item_group"),
		frozen,
		item_code=item.get("item_code"),
		dry_exceptions=dry_exceptions,
		item_override=item.get("custom_fulfillment_category"),
	)
	return {**item, "classification": classification, "reason": reason}


def _outstanding(item) -> float:
	try:
		return pending_stock_qty(
			item.get("qty"),
			item.get("picked_qty"),
			item.get("delivered_qty"),
			item.get("conversion_factor"),
		)
	except GenerationError:
		return 0.0


def _deliverable_outstanding(item) -> float:
	qty = item.get("qty")
	if qty is None:
		qty = item.get("ordered")
	delivered = item.get("delivered_qty")
	if delivered is None:
		delivered = item.get("delivered")
	return flt(qty) - flt(delivered)


def _doc_counts(docs: list[dict]) -> dict[str, int]:
	return {
		"total": len(docs),
		"draft": sum(1 for row in docs if row.get("docstatus") == 0),
		"submitted": sum(1 for row in docs if row.get("docstatus") == 1),
	}


def _can_generate_for_so(so, items: list[dict], profile_ok: bool) -> tuple[bool, str | None]:
	if not profile_ok:
		return False, "PROFILE_INVALID"
	roles = set(frappe.get_roles())
	if "System Manager" not in roles and not {"Stock Manager", "Stock User"}.issubset(roles):
		return False, "GENERATE_PERMISSION"
	if flt(so.get("docstatus")) != 1:
		return False, "SO_NOT_ELIGIBLE"
	if so.get("status") in ("Closed", "Cancelled", "On Hold"):
		return False, "SO_NOT_ELIGIBLE"
	if flt(so.get("per_delivered")) >= 100 or flt(so.get("per_picked")) >= 100:
		return False, "SO_NOT_ELIGIBLE"
	if any(item.get("classification") == "unclassified" for item in items):
		return False, "ITEM_GROUP_MISSING"
	if any(flt(item.get("stock_reserved_qty")) > 0 for item in items):
		return False, "STOCK_RESERVED"
	if any(flt(item.get("delivered_by_supplier")) for item in items):
		return False, "ITEM_NOT_PICKABLE"
	if not any(flt(item.get("outstanding")) > 0 for item in items):
		return False, "NO_OUTSTANDING"
	return True, None


def _active_run_summary(sales_order: str) -> dict | None:
	if not frappe.db.exists("DocType", "Warehouse Fulfillment Run"):
		return None
	name = frappe.db.get_value(
		"Warehouse Fulfillment Run",
		{"sales_order": sales_order, "active_so_key": sales_order},
		"name",
	)
	if not name:
		return None
	row = frappe.db.get_value(
		"Warehouse Fulfillment Run",
		name,
		["name", "status", "dry_pick_list", "frozen_pick_list"],
		as_dict=True,
	)
	if not row:
		return None
	# If run references pick lists that were deleted, it is an orphaned run
	has_dry = bool(row.get("dry_pick_list"))
	has_frozen = bool(row.get("frozen_pick_list"))
	dry_exists = frappe.db.exists("Pick List", row["dry_pick_list"]) if has_dry else False
	frozen_exists = frappe.db.exists("Pick List", row["frozen_pick_list"]) if has_frozen else False
	if (has_dry or has_frozen) and not (dry_exists or frozen_exists):
		return None
	return dict(row)


def _stage_for(
	profile_ok: bool,
	has_unclassified: bool,
	pick_lists: list[dict],
	delivery_notes: list[dict],
	draft_dn_fully_packed: dict[str, bool],
	has_outstanding: bool,
) -> str:
	draft_dns = [row for row in delivery_notes if row.get("docstatus") == 0]
	return derive_stage(
		profile_ok,
		has_unclassified,
		any(row.get("docstatus") == 0 for row in pick_lists),
		bool(draft_dns),
		bool(draft_dns) and all(draft_dn_fully_packed.get(row["name"], False) for row in draft_dns),
		any(row.get("docstatus") == 1 for row in pick_lists),
		any(row.get("docstatus") == 1 for row in delivery_notes),
		has_outstanding,
	)


def _public_doc(row: dict) -> dict:
	creation = row.get("creation")
	return {
		"name": row.get("name"),
		"docstatus": row.get("docstatus"),
		"status": row.get("status")
		or ("Draft" if row.get("docstatus") == 0 else "Submitted"),
		"date": str(creation)[:10] if creation else None,
	}
