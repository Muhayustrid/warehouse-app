# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""Pure packing-list logic for the Delivery Manifest.

No frappe imports so the core can be unit-tested outside a bench. The
caller (delivery_manifest controller) supplies Item Group / weight data.
"""

from __future__ import annotations

from typing import Any

from warehouse_app.warehouse_app.fulfillment.classification import classify


def classify_line(line: dict[str, Any], frozen: set[str], dry_exceptions: set[str] | None = None) -> str:
	"""Classification of a single DN line: exactly ``dry`` or ``frozen``."""
	return classify(
		item_group=line.get("item_group"),
		frozen=frozen,
		item_code=line.get("item_code"),
		dry_exceptions=dry_exceptions,
		item_override=line.get("custom_fulfillment_category"),
	)


def bucket_lines(
	lines: list[dict[str, Any]],
	frozen: set[str],
	dry_exceptions: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
	"""Split DN lines into (dry, frozen) lists preserving original order."""
	dry: list[dict[str, Any]] = []
	frozen_lines: list[dict[str, Any]] = []
	for line in lines:
		if classify_line(line, frozen, dry_exceptions=dry_exceptions) == "frozen":
			frozen_lines.append(line)
		else:
			dry.append(line)
	return dry, frozen_lines


def estimate_weight(qty, weight_per_unit, places: int = 2):
	"""``qty x weight_per_unit`` rounded; ``None`` when the weight is unset.

	Frozen items carry a standard weight per unit/package; dry items are
	hand-weighed so they return None and print a blank column.
	"""
	weight = float(weight_per_unit or 0.0)
	if not weight > 0:
		return None
	return round(float(qty or 0.0) * weight, places)


def total_weight(rows: list[dict[str, Any]], places: int = 2) -> float:
	"""Sum the estimated weights already attached to each row."""
	return round(sum(float(row.get("estimated_weight") or 0.0) for row in rows), places)