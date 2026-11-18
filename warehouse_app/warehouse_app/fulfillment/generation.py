# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""Pure F2 planning rules. No Frappe imports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from warehouse_app.warehouse_app.fulfillment.classification import classify


class GenerationError(Exception):
	def __init__(self, code: str, row: Mapping | None = None):
		self.code = code
		self.row = row
		super().__init__(code)


def pending_stock_qty(
	qty, picked_qty, delivered_qty, conversion_factor
) -> float:
	factor = _flt(conversion_factor)
	if factor <= 0:
		raise GenerationError("INVALID_CONVERSION")
	picked_in_stock_uom = _flt(picked_qty) / factor
	consumed = max(picked_in_stock_uom, _flt(delivered_qty))
	return max(0.0, _flt(qty) - consumed)


def build_generation_plan(
	items: Iterable[Mapping],
	frozen: set[str] | None,
	dry_exceptions: set[str] | None = None,
) -> dict:
	if not frozen:
		raise GenerationError("PROFILE_INVALID")

	rows: list[dict] = []
	groups: dict[str, list[dict]] = {"dry": [], "frozen": []}
	for raw in items:
		sales_order_item = raw.get("sales_order_item")
		if not sales_order_item:
			raise GenerationError("SALES_ORDER_ITEM_MISSING", raw)
		item_group = raw.get("item_group")
		if not item_group:
			raise GenerationError("ITEM_GROUP_MISSING", raw)

		conversion_factor = _flt(raw.get("conversion_factor")) or 1.0
		pending_qty = pending_stock_qty(
			raw.get("qty"),
			raw.get("picked_qty"),
			raw.get("delivered_qty"),
			raw.get("conversion_factor"),
		)
		if pending_qty <= 0:
			continue

		picking_group = classify(
			item_group,
			frozen,
			item_code=raw.get("item_code"),
			dry_exceptions=dry_exceptions,
			item_override=raw.get("custom_fulfillment_category"),
		)
		row = {
			"sales_order_item": sales_order_item,
			"item_code": raw.get("item_code"),
			"item_group": item_group,
			"item_group_snapshot": item_group,
			"picking_group": picking_group,
			"pending_qty": pending_qty,
			"required_stock_qty": pending_qty * conversion_factor,
			"allocated_stock_qty": 0.0,
			"stock_uom": raw.get("stock_uom"),
			"conversion_factor": conversion_factor,
			"warehouse": raw.get("warehouse"),
		}
		rows.append(row)
		groups[picking_group].append(row)

	return {"items": rows, "groups": groups}


def split_locations(
	locations: Iterable[Mapping], group_by_so_item: Mapping[str, str]
) -> dict[str, list[dict]]:
	groups: dict[str, list[dict]] = {"dry": [], "frozen": []}
	for raw in locations:
		sales_order_item = raw.get("sales_order_item")
		group = group_by_so_item.get(sales_order_item)
		if not sales_order_item or group not in groups:
			raise GenerationError("SPLIT_MAPPING_MISSING", raw)
		as_dict = getattr(raw, "as_dict", None)
		row = as_dict() if callable(as_dict) else dict(raw)
		groups[group].append(row)
	return groups


def profile_policy_snapshot(profile: Mapping) -> dict:
	return {
		"profile_revision": profile.get("config_revision") or 0,
		"frozen_item_group": profile.get("frozen_item_group"),
		"include_child_item_groups": profile.get("include_child_item_groups") or 0,
		"allow_partial_delivery": profile.get("allow_partial_delivery") or 0,
		"short_pick_approval_required": profile.get("short_pick_approval_required") or 0,
		"require_all_packed": profile.get("require_all_packed") or 0,
		"enable_packing_slip": 1 if profile.get("enable_packing_slip") is None else (profile.get("enable_packing_slip") or 0),
		"skip_packing_dry": profile.get("skip_packing_dry") or 0,
		"require_checker_approval": profile.get("require_checker_approval") or 0,
		"allow_cross_group_packing": profile.get("allow_cross_group_packing") or 0,
		"dry_parent_warehouse": profile.get("dry_parent_warehouse"),
		"frozen_parent_warehouse": profile.get("frozen_parent_warehouse"),
	}


def _flt(value) -> float:
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0
