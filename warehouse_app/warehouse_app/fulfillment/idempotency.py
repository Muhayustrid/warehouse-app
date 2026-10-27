# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""Database-backed idempotency for F2 Generate requests."""

from __future__ import annotations

import hashlib
import json

import frappe
from frappe.utils import add_to_date, now_datetime

KEY = "Warehouse Fulfillment Request Key"
TTL_HOURS = 24


def scope_key(actor, company, sales_order, request_type, idempotency_key) -> str:
	parts = [
		_normalize(actor),
		_normalize(company),
		_normalize(sales_order),
		_normalize(request_type),
		_normalize(idempotency_key),
	]
	return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def request_hash(sales_order, expected_so_modified, request_type) -> str:
	payload = {
		"sales_order": _normalize(sales_order),
		"expected_so_modified": _normalize(expected_so_modified),
		"request_type": _normalize(request_type),
	}
	canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
	return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def begin_request(
	actor, company, sales_order, request_type, idempotency_key, request_hash_value
) -> dict:
	actor = actor or frappe.session.user
	scope = scope_key(actor, company, sales_order, request_type, idempotency_key)
	existing = get_request(scope)
	if existing:
		return _existing_result(existing, request_hash_value)

	now = now_datetime()
	try:
		doc = frappe.get_doc(
			{
				"doctype": KEY,
				"scope_key": scope,
				"idempotency_key": _normalize(idempotency_key),
				"actor": actor,
				"company": company,
				"sales_order": sales_order,
				"request_type": request_type,
				"request_hash": request_hash_value,
				"status": "PENDING",
				"created_at": now,
				"expiry_at": add_to_date(now, hours=TTL_HOURS),
			}
		).insert()
		frappe.db.commit()
		return {"state": "new", "scope": scope, "request": _serialize(doc)}
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		frappe.db.rollback()
		existing = get_request(scope)
		if not existing:
			raise
		return _existing_result(existing, request_hash_value)


def complete_request(scope: str, result_refs: list[str]) -> None:
	doc = frappe.get_doc(KEY, scope)
	doc.status = "COMPLETED"
	doc.result_doc_refs = json.dumps(result_refs or [])
	doc.completed_at = now_datetime()
	doc.error_code = None
	doc.error_message = None
	doc.save()
	frappe.db.commit()


def fail_request(scope: str, code: str, message: str) -> None:
	doc = frappe.get_doc(KEY, scope)
	doc.status = "FAILED"
	doc.error_code = code
	doc.error_message = message
	doc.save()
	frappe.db.commit()


def get_request(scope: str) -> dict | None:
	if not frappe.db.exists(KEY, scope):
		return None
	return _serialize(frappe.get_doc(KEY, scope))


def _existing_result(existing: dict, request_hash_value: str) -> dict:
	if existing["request_hash"] != request_hash_value:
		return {"state": "mismatch", "scope": existing["name"], "request": existing}
	if existing["status"] == "COMPLETED":
		return {"state": "replay", "scope": existing["name"], "request": existing}
	if existing["status"] == "PENDING":
		if _expired(existing):
			doc = frappe.get_doc(KEY, existing["name"])
			_reset_pending(doc)
			return {"state": "new", "scope": existing["name"], "request": _serialize(doc)}
		return {"state": "in_progress", "scope": existing["name"], "request": existing}
	doc = frappe.get_doc(KEY, existing["name"])
	_reset_pending(doc)
	return {"state": "new", "scope": existing["name"], "request": _serialize(doc)}


def _reset_pending(doc) -> None:
	doc.status = "PENDING"
	doc.error_code = None
	doc.error_message = None
	doc.result_doc_refs = None
	doc.completed_at = None
	doc.expiry_at = add_to_date(now_datetime(), hours=TTL_HOURS)
	doc.save()
	frappe.db.commit()


def _expired(existing: dict) -> bool:
	expiry = existing.get("expiry_at")
	if not expiry:
		return False
	return now_datetime() > frappe.utils.get_datetime(expiry)


def _serialize(doc) -> dict:
	refs = doc.result_doc_refs
	if isinstance(refs, str) and refs:
		try:
			refs = json.loads(refs)
		except ValueError:
			refs = []
	return {
		"name": doc.name,
		"scope_key": doc.scope_key,
		"idempotency_key": doc.idempotency_key,
		"actor": doc.actor,
		"company": doc.company,
		"sales_order": doc.sales_order,
		"request_type": doc.request_type,
		"request_hash": doc.request_hash,
		"status": doc.status,
		"result_doc_refs": refs or [],
		"created_at": str(doc.created_at) if doc.created_at else None,
		"expiry_at": str(doc.expiry_at) if doc.expiry_at else None,
		"completed_at": str(doc.completed_at) if doc.completed_at else None,
		"error_code": doc.error_code,
		"error_message": doc.error_message,
	}


def _normalize(value) -> str:
	return str(value or "").strip()
