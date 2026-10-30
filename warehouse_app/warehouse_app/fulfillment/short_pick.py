# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""Fail-closed short-pick rules.

Pure functions only: no frappe imports, so the rules can be unit-tested outside
a bench. A short row is 0 < custom_picked_qty < qty; zero is a separate
unsupported state rejected before save.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any


def _num(value: Any) -> float:
	return float(value or 0)


def short_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
	"""Return the rows whose picked quantity is greater than zero and below target."""
	short: list[dict[str, Any]] = []
	for row in rows:
		qty = _num(row.get("qty"))
		picked = _num(row.get("custom_picked_qty"))
		if 0 < picked < qty:
			short.append(
				{
					"pick_list": row.get("pick_list"),
					"row": row.get("row"),
					"item_code": row.get("item_code"),
					"qty": qty,
					"custom_picked_qty": picked,
				}
			)
	return short


def short_fingerprint(rows: Iterable[Mapping[str, Any]]) -> str:
	"""Hash the short rows, order independent, rounded to 6 decimals."""
	values = [
		[
			row["pick_list"],
			row["row"],
			row["item_code"],
			round(row["qty"], 6),
			round(row["custom_picked_qty"], 6),
		]
		for row in short_rows(rows)
	]
	payload = json.dumps(sorted(values), separators=(",", ":"))
	return hashlib.sha256(payload.encode()).hexdigest()


def finish_blocker(
	short: list[dict[str, Any]],
	approval_required: bool,
	status: str | None,
	fingerprint: str | None,
) -> str | None:
	"""Return the stable error code that blocks Finish picking, or None."""
	if not short:
		return None
	if status == "Approved" and fingerprint == short_fingerprint(short):
		return None
	if not approval_required:
		return "SHORT_PICK_BLOCKED"
	if status == "Rejected":
		return "SHORT_PICK_APPROVAL_REJECTED"
	if status != "Approved":
		return "SHORT_PICK_APPROVAL_PENDING"
	if not fingerprint or fingerprint != short_fingerprint(short):
		return "SHORT_PICK_STALE_APPROVAL"
	return None
