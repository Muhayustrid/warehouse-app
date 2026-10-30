# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""F2 native Generate service. Creates draft PLs; never picks or moves stock."""

from __future__ import annotations

import json

import frappe
from frappe.utils import flt

from warehouse_app.warehouse_app.fulfillment.generation import (
	GenerationError,
	build_generation_plan,
	profile_policy_snapshot,
	split_locations,
)
from warehouse_app.warehouse_app.fulfillment.idempotency import (
	begin_request,
	complete_request,
	fail_request,
	request_hash,
)
from warehouse_app.warehouse_app.fulfillment.profile import (
	resolve_dry_exceptions,
	resolve_frozen,
)

RUN = "Warehouse Fulfillment Run"
PROFILE = "Warehouse Fulfillment Profile"
REQUEST_TYPE = "GeneratePickLists"


class FulfillmentError(Exception):
	def __init__(self, code: str, message: str):
		self.code = code
		self.message = message
		super().__init__(f"{code}: {message}")


def generate_fulfillment_run(
	sales_order: str,
	idempotency_key: str,
	expected_so_modified: str,
	actor: str | None = None,
) -> dict:
	actor = actor or frappe.session.user
	_require_roles()
	if not idempotency_key:
		raise FulfillmentError("IDEMPOTENCY_KEY_REQUIRED", "Idempotency key is required.")
	if not expected_so_modified:
		raise FulfillmentError("STALE_SO", "Reload the Sales Order before generating.")

	so = _load_sales_order(sales_order)
	if str(so.modified) != str(expected_so_modified):
		raise FulfillmentError("SO_CHANGED", "The Sales Order changed. Reload before generating.")
	_require_company(so.company)

	hash_value = request_hash(so.name, expected_so_modified, REQUEST_TYPE)
	request = begin_request(
		actor, so.company, so.name, REQUEST_TYPE, idempotency_key, hash_value
	)
	scope = request["scope"]
	state = request["state"]
	if state == "mismatch":
		raise FulfillmentError(
			"IDEMPOTENCY_MISMATCH", "This request key was used with a different payload."
		)

	if state == "replay":
		return _result_from_refs(request["request"].get("result_doc_refs") or [], reused=True)

	active = _active_run(so.name)
	if state == "in_progress":
		if active:
			refs = _refs_clean(active)
			complete_request(scope, refs)
			return _result(active, reused=True)
		raise FulfillmentError("REQUEST_IN_PROGRESS", "A generate request is already in progress.")
	if active:
		refs = _refs_clean(active)
		complete_request(scope, refs)
		return _result(active, reused=True)

	try:
		profile = _require_profile(so.company)
		frozen = resolve_frozen(profile)
		if frozen is None:
			raise FulfillmentError("PROFILE_INVALID", "The Fulfillment profile is invalid.")
		plan = _preflight(so, profile, frozen)
		run, created = _create_run(so, profile, plan, idempotency_key)
		if not created:
			complete_request(scope, _refs_clean(run))
			return _result(run, reused=True)
		_run = _materialize(so, profile, plan, run, frozen)
		frappe.db.commit()
		refs = _refs_clean(_run)
		complete_request(scope, refs)
		return _result(_run, reused=False)
	except FulfillmentError as exc:
		frappe.db.rollback()
		fail_request(scope, exc.code, exc.message)
		raise
	except GenerationError as exc:
		frappe.db.rollback()
		fail_request(scope, exc.code, _generation_message(exc))
		raise FulfillmentError(exc.code, _generation_message(exc))
	except Exception as exc:
		frappe.db.rollback()
		fail_request(scope, "GENERATE_FAILED", type(exc).__name__)
		raise


def _require_roles() -> None:
	roles = set(frappe.get_roles())
	# Stock Manager needs Stock User because standard ERPNext grants Company/SO/Warehouse
	# read to Stock User, not Stock Manager. Do not widen native DocPerms from this app.
	if "System Manager" not in roles and not {"Stock Manager", "Stock User"}.issubset(roles):
		raise frappe.PermissionError


def _load_sales_order(sales_order: str):
	if not sales_order or not frappe.db.exists("Sales Order", sales_order):
		raise FulfillmentError("SO_NOT_FOUND", "Sales Order does not exist.")
	if not frappe.has_permission("Sales Order", doc=sales_order, ptype="read"):
		raise frappe.PermissionError
	return frappe.get_doc("Sales Order", sales_order)


def _require_company(company: str) -> None:
	if not company or not frappe.has_permission("Company", doc=company, ptype="read"):
		raise frappe.PermissionError


def _require_profile(company: str):
	profile_name = frappe.db.get_value(PROFILE, {"company": company}, "name")
	if not profile_name:
		raise FulfillmentError("PROFILE_MISSING", "Configure the Fulfillment profile first.")
	profile = frappe.get_doc(PROFILE, profile_name)
	if not profile.enabled:
		raise FulfillmentError("PROFILE_DISABLED", "The Fulfillment profile is disabled.")
	return profile


def _preflight(so, profile, frozen: set[str]) -> dict:
	if so.docstatus != 1:
		raise FulfillmentError("SO_NOT_ELIGIBLE", "Sales Order is not submitted.")
	if so.status in ("Closed", "Cancelled", "On Hold"):
		raise FulfillmentError("SO_NOT_ELIGIBLE", "Sales Order is not open.")
	if flt(so.per_delivered) >= 100:
		raise FulfillmentError("SO_NOT_ELIGIBLE", "Sales Order is fully delivered.")
	if flt(so.per_picked) >= 100:
		raise FulfillmentError("SO_NOT_ELIGIBLE", "Sales Order is fully picked.")
	if so.get("packed_items"):
		raise FulfillmentError("ITEM_NOT_PICKABLE", "Packed Items/Product Bundles are not supported.")

	items = []
	for row in so.items:
		item = frappe.db.get_value(
			"Item", row.item_code, ["item_group", "is_stock_item", "disabled"], as_dict=True
		)
		if not item:
			raise FulfillmentError("ITEM_NOT_PICKABLE", f"Item {row.item_code} does not exist.")
		if not item.is_stock_item:
			raise FulfillmentError("ITEM_NOT_PICKABLE", f"Item {row.item_code} is not stock.")
		if item.disabled:
			raise FulfillmentError("ITEM_NOT_PICKABLE", f"Item {row.item_code} is disabled.")
		if not item.item_group:
			raise FulfillmentError("ITEM_GROUP_MISSING", f"Item {row.item_code} has no Item Group.")
		group = frappe.db.get_value(
			"Item Group", item.item_group, ["name", "is_group"], as_dict=True
		)
		if not group or group.is_group:
			raise FulfillmentError(
				"ITEM_GROUP_MISSING",
				f"Item {row.item_code} has an invalid Item Group.",
			)
		if flt(row.stock_reserved_qty) > 0:
			raise FulfillmentError("STOCK_RESERVED", "Sales Order has reserved stock.")
		if row.get("delivered_by_supplier"):
			raise FulfillmentError("ITEM_NOT_PICKABLE", "Supplier-delivered items are not supported.")
		if frappe.db.exists("Product Bundle", {"new_item_code": row.item_code, "disabled": 0}):
			raise FulfillmentError("ITEM_NOT_PICKABLE", "Product Bundles are not supported.")
		items.append(
			{
				"sales_order_item": row.name,
				"item_code": row.item_code,
				"item_group": item.item_group,
				"qty": row.qty,
				"picked_qty": row.picked_qty,
				"delivered_qty": row.delivered_qty,
				"conversion_factor": row.conversion_factor,
				"stock_uom": row.stock_uom,
				"warehouse": row.warehouse or so.set_warehouse,
				"stock_reserved_qty": row.stock_reserved_qty,
				"delivered_by_supplier": row.delivered_by_supplier,
				"custom_fulfillment_category": getattr(item, "custom_fulfillment_category", None),
			}
		)

	dry_exceptions = resolve_dry_exceptions(profile)
	plan = build_generation_plan(items, frozen, dry_exceptions=dry_exceptions)
	if not plan["items"]:
		raise FulfillmentError("NO_OUTSTANDING", "There is no outstanding quantity to pick.")
	return plan


def _create_run(so, profile, plan: dict, request_key: str):
	policy = profile_policy_snapshot(profile)
	run = frappe.get_doc(
		{
			"doctype": RUN,
			"company": so.company,
			"sales_order": so.name,
			"customer": so.customer,
			"profile": profile.name,
			"profile_revision": profile.config_revision,
			"frozen_item_group_snapshot": profile.frozen_item_group,
			"include_child_groups_snapshot": profile.include_child_item_groups,
			"policy_snapshot": json.dumps(policy, ensure_ascii=False),
			"short_pick_approval_required_snapshot": (
				1 if profile.short_pick_approval_required else 0
			),
			"status": "PLANNING",
			"active_so_key": so.name,
			"request_key": request_key,
			"run_revision": 1,
		}
	)
	try:
		run.insert()
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		frappe.db.rollback()
		active = _active_run(so.name)
		if active:
			return active, False
		raise
	return run, True


def _materialize(so, profile, plan: dict, run, frozen: set[str]):
	template = _template(so.name)
	if not template.locations:
		raise FulfillmentError("STOCK_SHORTAGE", "Native create_pick_list returned no locations.")

	group_map = {row["sales_order_item"]: row["picking_group"] for row in plan["items"]}
	split = split_locations(template.locations, group_map)
	_by_item = {row["sales_order_item"]: row for row in plan["items"]}
	allocated: dict[str, float] = {}
	for group, rows in split.items():
		for row in rows:
			so_item = row.get("sales_order_item")
			allocated[so_item] = allocated.get(so_item, 0.0) + flt(
				row.get("stock_qty") or flt(row.get("qty")) * flt(row.get("conversion_factor"))
			)
	for so_item, item in _by_item.items():
		if allocated.get(so_item, 0.0) + 0.0001 < flt(item["required_stock_qty"]):
			raise FulfillmentError(
				"STOCK_SHORTAGE",
				f"Stock is insufficient for {item['item_code']} / {so_item}.",
			)

	pick_lists = {}
	saved_allocated: dict[str, float] = {}
	for group in ("dry", "frozen"):
		rows = split.get(group) or []
		if not rows:
			continue
		pick_lists[group] = _insert_pick_list(template, rows, run, group)
		if group == "dry":
			run.dry_pick_list = pick_lists[group].name
		else:
			run.frozen_pick_list = pick_lists[group].name
		for row in pick_lists[group].locations:
			so_item = row.sales_order_item
			expected = _by_item.get(so_item)
			if not expected or expected["picking_group"] != group:
				raise FulfillmentError(
					"PL_MISMATCH",
					f"Saved Pick List contains a row outside group {group}.",
				)
			saved_allocated[so_item] = saved_allocated.get(so_item, 0.0) + flt(row.stock_qty)

	for item in plan["items"]:
		if saved_allocated.get(item["sales_order_item"], 0.0) + 0.0001 < flt(
			item["required_stock_qty"]
		):
			raise FulfillmentError(
				"STOCK_SHORTAGE",
				f"Saved Pick List is short for {item['item_code']} / {item['sales_order_item']}.",
			)
		item_allocated = flt(saved_allocated.get(item["sales_order_item"], 0.0))
		run.append(
			"items",
			{
				"sales_order_item": item["sales_order_item"],
				"item_code": item["item_code"],
				"item_group_snapshot": item["item_group_snapshot"],
				"picking_group": item["picking_group"],
				"required_stock_qty": item["required_stock_qty"],
				"allocated_stock_qty": item_allocated,
				"stock_uom": item["stock_uom"],
				"conversion_factor": item["conversion_factor"],
			},
		)
		for pl in pick_lists.values():
			for row in pl.locations:
				if row.sales_order_item != item["sales_order_item"]:
					continue
				run.append(
					"allocations",
					{
						"sales_order_item": item["sales_order_item"],
						"item_code": item["item_code"],
						"picking_group": item["picking_group"],
						"pick_list": pl.name,
						"pick_list_item": row.name,
						"warehouse": row.warehouse,
						"batch_no": row.batch_no,
						"serial_and_batch_bundle": row.serial_and_batch_bundle,
						"allocated_stock_qty": flt(row.stock_qty),
					},
				)
	run.save()
	return run


def _template(sales_order: str):
	from erpnext.selling.doctype.sales_order.sales_order import create_pick_list

	return create_pick_list(sales_order)


def _insert_pick_list(template, rows, run, group: str):
	pl = frappe.copy_doc(template)
	pl.set("locations", [])
	for row in rows:
		as_dict = getattr(row, "as_dict", None)
		values = as_dict() if callable(as_dict) else dict(row)
		for key in ("name", "doctype", "parent", "parentfield", "parenttype", "idx"):
			values.pop(key, None)
		pl.append("locations", values)
	pl.pick_manually = 1
	pl.scan_mode = 0
	pl.custom_fulfillment_run = run.name
	pl.custom_fulfillment_group = "Dry" if group == "dry" else "Frozen"
	pl.insert()
	pl.reload()

	expected_items = {row["sales_order_item"] for row in rows}
	actual_items = {row.sales_order_item for row in pl.locations}
	if not actual_items or actual_items != expected_items:
		raise FulfillmentError(
			"PL_MISMATCH",
			f"Saved {group} Pick List row set does not match the split plan.",
		)
	if pl.docstatus != 0 or flt(pl.scan_mode) != 0:
		raise FulfillmentError("PL_MISMATCH", f"Saved {group} Pick List is not a clean draft.")
	if pl.custom_fulfillment_run != run.name or pl.custom_fulfillment_group != (
		"Dry" if group == "dry" else "Frozen"
	):
		raise FulfillmentError("PL_MISMATCH", f"Saved {group} Pick List lineage is missing.")
	if any(
		flt(row.picked_qty) or flt(getattr(row, "custom_picked_qty", 0))
		for row in pl.locations
	):
		raise FulfillmentError("PL_MISMATCH", f"Saved {group} Pick List has picked quantity.")
	return pl


def _active_run(sales_order: str):
	name = frappe.db.get_value(
		RUN, {"sales_order": sales_order, "active_so_key": sales_order}, "name"
	)
	return frappe.get_doc(RUN, name) if name else None


def _refs(run) -> list[str]:
	return [
		run.name,
		run.dry_pick_list,
		run.frozen_pick_list,
	]


def _refs_clean(run) -> list[str]:
	return [ref for ref in _refs(run) if ref]


def _result_from_refs(refs: list[str], reused: bool) -> dict:
	if not refs:
		raise FulfillmentError("RUN_NOT_FOUND", "The stored Run reference is missing.")
	return _result(frappe.get_doc(RUN, refs[0]), reused=reused)


def _result(run, reused: bool) -> dict:
	return {
		"run": run.name,
		"reused": reused,
		"status": run.status,
		"dry_pick_list": _pick_list_info(run.dry_pick_list),
		"frozen_pick_list": _pick_list_info(run.frozen_pick_list),
		"warnings": [],
	}


def _pick_list_info(name: str | None) -> dict | None:
	if not name:
		return None
	row = frappe.db.get_value("Pick List", name, ["name", "docstatus", "status"], as_dict=True)
	return dict(row) if row else None


def _generation_message(exc: GenerationError) -> str:
	if exc.code == "ITEM_GROUP_MISSING":
		return f"Item Group is missing for Sales Order Item {exc.row.get('sales_order_item')}."
	if exc.code == "SPLIT_MAPPING_MISSING":
		return "Native Pick List has a row outside the generated group plan."
	if exc.code == "INVALID_CONVERSION":
		return "An Item has an invalid UOM conversion factor."
	if exc.code == "PROFILE_INVALID":
		return "The Fulfillment profile is invalid."
	return exc.code
