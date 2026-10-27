# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""Pure fulfillment queue rules. No Frappe imports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from warehouse_app.warehouse_app.fulfillment.classification import (
	ClassificationError,
	classify,
)


def derive_stage(
	profile_ok: bool,
	has_unclassified: bool,
	has_draft_pick_list: bool,
	has_draft_delivery_note: bool,
	dn_fully_packed: bool,
	has_submitted_pick_list: bool,
	has_submitted_delivery_note: bool,
	has_outstanding: bool,
) -> str:
	if not profile_ok or has_unclassified:
		return "exception"
	if has_draft_pick_list:
		return "picking"
	if has_draft_delivery_note:
		return "ready" if dn_fully_packed else "packing"
	if has_submitted_pick_list and not has_submitted_delivery_note:
		return "packing"
	if has_submitted_delivery_note and has_outstanding:
		return "partially_delivered"
	return "open"


def group_counts(items: Iterable[Mapping]) -> dict[str, int]:
	counts = {"dry": 0, "frozen": 0, "unclassified": 0}
	for item in items:
		classification = item.get("classification")
		counts[classification if classification in counts else "unclassified"] += 1
	return counts


def is_eligible(
	docstatus: int, status: str, per_delivered: float, outstanding_qty: float
) -> bool:
	if docstatus != 1 or status in ("Closed", "Cancelled"):
		return False
	if float(per_delivered or 0) >= 100:
		return False
	return float(outstanding_qty or 0) > 0


def safe_classify(
	item_group: str | None, frozen: set[str] | None
) -> tuple[str, str | None]:
	if frozen is None:
		return "unclassified", "profile_missing"
	if not item_group:
		return "unclassified", "item_group_missing"
	try:
		return classify(item_group, frozen), None
	except ClassificationError:
		return "unclassified", "item_group_missing"
