# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""Whitelisted read-only F1 fulfillment endpoints."""

from __future__ import annotations

import frappe

from warehouse_app.warehouse_app.fulfillment.loader import (
	load_order_preview,
	load_order_queue,
)
from warehouse_app.warehouse_app.fulfillment.settings_api import (
	fulfillment_settings_options as _fulfillment_settings_options,
)
from warehouse_app.warehouse_app.fulfillment.settings_api import (
	get_fulfillment_settings as _get_fulfillment_settings,
)
from warehouse_app.warehouse_app.fulfillment.settings_api import (
	save_fulfillment_settings as _save_fulfillment_settings,
)


@frappe.whitelist(methods=["GET"])
def get_order_queue(
	company=None,
	search=None,
	stage=None,
	from_date=None,
	to_date=None,
	page=1,
	page_length=20,
):
	return load_order_queue(
		company=company,
		search=search,
		stage=stage,
		from_date=from_date,
		to_date=to_date,
		page=page,
		page_length=page_length,
	)


@frappe.whitelist(methods=["GET"])
def get_order_preview(sales_order):
	return load_order_preview(sales_order)


@frappe.whitelist(methods=["GET"])
def get_fulfillment_settings(company=None):
	return _get_fulfillment_settings(company=company)


@frappe.whitelist(methods=["POST"])
def save_fulfillment_settings(payload=None):
	return _save_fulfillment_settings(payload=payload)


@frappe.whitelist(methods=["GET"])
def fulfillment_settings_options(company=None):
	return _fulfillment_settings_options(company=company)
