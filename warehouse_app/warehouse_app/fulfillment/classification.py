# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""Fail-closed Dry/Frozen classification.

Pure functions only: no frappe imports, so the core can be unit-tested outside
a bench. The caller supplies the Item Group tree data.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


class ClassificationError(ValueError):
	"""Raised when classification configuration or item master data is invalid."""


def validate_profile_config(
	configured_group: str | None,
	group_is_group: bool,
	has_children: bool,
	include_children: bool,
) -> None:
	"""Reject configurations that would silently classify every item as Dry."""
	if not configured_group:
		raise ClassificationError("Frozen Item Group is not configured.")
	if group_is_group and has_children and not include_children:
		raise ClassificationError(
			f"Frozen Item Group {configured_group} is a parent group with children. "
			"Enable 'Include Child Item Groups' or select a leaf group."
		)


def frozen_groups(
	configured_group: str | None,
	descendants: Iterable[str],
	include_children: bool,
) -> set[str]:
	"""Return the configured group plus descendants when the flag is enabled."""
	if not configured_group:
		raise ClassificationError("Frozen Item Group is not configured.")

	groups = {configured_group}
	if include_children:
		groups.update(descendants)
	return groups


def classify(item_group: str | None, frozen: set[str]) -> str:
	"""Return exactly ``dry`` or ``frozen``; never guess on missing data."""
	if not item_group:
		raise ClassificationError("Item has no Item Group.")
	if not frozen:
		raise ClassificationError("Frozen Item Group set is empty.")
	return "frozen" if item_group in frozen else "dry"


def classify_rows(
	rows: Iterable[Mapping[str, Any]],
	frozen: set[str],
) -> list[dict[str, Any]]:
	"""Classify SO Item rows without merging duplicate item codes."""
	classified: list[dict[str, Any]] = []
	for row in rows:
		if not row.get("sales_order_item"):
			raise ClassificationError("Row is missing sales_order_item.")
		if not row.get("item_code"):
			raise ClassificationError("Row is missing item_code.")

		result = dict(row)
		result["picking_group"] = classify(row.get("item_group"), frozen)
		classified.append(result)
	return classified
