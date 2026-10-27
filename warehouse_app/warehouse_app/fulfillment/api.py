# Copyright (c) 2026, Vany Eka Karunia
# License: MIT

"""Whitelisted read-only F1 fulfillment endpoints."""

from __future__ import annotations

import frappe

from warehouse_app.warehouse_app.fulfillment.loader import (
	load_order_preview,
	load_order_queue,
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
