# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto and contributors
# For license information, please see license.txt

"""Stock Reconciliation per-UOM conversion and row math module.

Consolidates all per-UOM calculation logic for Stock Reconciliation items,
ensuring consistent behavior between grid edits, Fetch Items, data import,
and document submission.
"""

from typing import Iterable

import frappe
from frappe import _
from frappe.utils import flt

SR_UOM_FIELD = "custom_uom"
SR_FACTOR_FIELD = "custom_conversion_factor"
SR_BEFORE_FIELD = "custom_qty_before"
SR_AFTER_FIELD = "custom_qty_after"
SR_RATE_FIELD = "custom_valuation_rate_per_uom"
SR_DIFF_FIELD = "custom_qty_difference_per_uom"
QTY_UOM_DECIMALS = 3


def _get_val(obj, key, default=None):
    if hasattr(obj, "get"):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _set_val(obj, key, val):
    if hasattr(obj, "set"):
        obj.set(key, val)
    elif isinstance(obj, dict):
        obj[key] = val
    else:
        setattr(obj, key, val)


def is_convertible(row) -> bool:
    """Return True if row has item_code, custom_uom, and custom_qty_after is not empty,
    and has no serial numbers or serial/batch bundles."""
    item_code = _get_val(row, "item_code")
    uom = _get_val(row, SR_UOM_FIELD)
    after = _get_val(row, SR_AFTER_FIELD)
    serial_no = _get_val(row, "serial_no")
    bundle = _get_val(row, "serial_and_batch_bundle")

    if not item_code or not uom:
        return False
    if after in (None, ""):
        return False
    if serial_no or bundle:
        return False
    return True


def resolve_factors(pairs: Iterable[tuple[str, str, str]]) -> dict[tuple[str, str], float | None]:
    """Resolve conversion factors for (item_code, uom, stock_uom) pairs.

    Returns dict mapping (item_code, uom) -> factor or None.
    Factor is 1.0 when uom == stock_uom, otherwise queried in a single batch
    from UOM Conversion Detail. Factor <= 0 or missing resolves to None.
    """
    pairs_list = list(pairs)
    result = {}
    items_to_fetch = set()
    for item_code, uom, stock_uom in pairs_list:
        if uom == stock_uom:
            result[(item_code, uom)] = 1.0
        else:
            items_to_fetch.add(item_code)

    uom_map = {}
    if items_to_fetch:
        records = frappe.get_all(
            "UOM Conversion Detail",
            filters={"parent": ("in", sorted(items_to_fetch))},
            fields=["parent", "uom", "conversion_factor"],
        )
        for r in records or []:
            parent = _get_val(r, "parent")
            u = _get_val(r, "uom")
            cf = _get_val(r, "conversion_factor")
            val = flt(cf)
            if val > 0:
                uom_map[(parent, u)] = val

    for item_code, uom, stock_uom in pairs_list:
        if uom != stock_uom:
            result[(item_code, uom)] = uom_map.get((item_code, uom), None)

    return result


def ledger_qty(
    item_code, warehouse, posting_date, posting_time, cache: dict, batch_no: str | None = None
) -> float:
    """Return ledger balance at doc posting timestamp, cached per (item, warehouse, batch)."""
    batch = batch_no.strip() if isinstance(batch_no, str) and batch_no.strip() else None
    key = (item_code, warehouse, batch)
    if key not in cache:
        if batch:
            from erpnext.stock.doctype.batch.batch import get_batch_qty

            val = get_batch_qty(
                batch_no=batch,
                warehouse=warehouse,
                item_code=item_code,
                posting_date=posting_date,
                posting_time=posting_time,
                for_stock_levels=True,
                consider_negative_batches=True,
                do_not_check_future_batches=True,
                ignore_reserved_stock=True,
            )
            cache[key] = flt(val or 0.0)
        else:
            from erpnext.stock.stock_ledger import get_previous_sle

            prev = get_previous_sle(
                {
                    "item_code": item_code,
                    "warehouse": warehouse,
                    "posting_date": posting_date,
                    "posting_time": posting_time,
                }
            )
            if prev:
                val = (
                    prev.get("qty_after_transaction")
                    if hasattr(prev, "get")
                    else getattr(prev, "qty_after_transaction", 0)
                )
                cache[key] = flt(val)
            else:
                cache[key] = 0.0
    return cache[key]


def precisions(row=None) -> dict[str, int]:
    """Return precision dict for qty, valuation_rate, and rate_per_uom."""
    target = row if row is not None else frappe.new_doc("Stock Reconciliation Item")

    def _get_prec(field, default):
        if hasattr(target, "precision"):
            p = target.precision(field)
            if p is not None:
                return p
        return default

    return {
        "qty": _get_prec("qty", 6),
        "valuation_rate": _get_prec("valuation_rate", 6),
        "rate_per_uom": _get_prec(SR_RATE_FIELD, 2),
    }


def compute_row(
    *,
    factor,
    ledger_qty,
    qty_after=None,
    rate_per_uom=None,
    qty=None,
    valuation_rate=None,
    allow_zero_valuation_rate=False,
    prec: dict,
) -> dict:
    """Compute per-UOM and native values for a single Stock Reconciliation row."""
    factor = flt(factor)
    ledger_q = flt(ledger_qty)
    before = flt(ledger_q / factor, 3)

    if qty_after in (None, ""):
        qty_after = before
        if qty in (None, ""):
            final_qty = ledger_q
        elif flt(flt(qty) / factor, 3) == flt(flt(qty_after), 3):
            final_qty = qty
        else:
            final_qty = flt(flt(qty_after) * factor, prec["qty"])
    else:
        if qty not in (None, "") and flt(flt(qty) / factor, 3) == flt(flt(qty_after), 3):
            final_qty = qty
        else:
            final_qty = flt(flt(qty_after) * factor, prec["qty"])

    diff = flt(flt(qty_after) - before, 3)
    if abs(diff) < 1e-9:
        diff = 0.0

    rate_is_set = (rate_per_uom not in (None, "")) and (
        flt(rate_per_uom) != 0 or allow_zero_valuation_rate
    )

    if not rate_is_set:
        final_val_rate = valuation_rate
        if valuation_rate not in (None, "") and flt(valuation_rate) > 0:
            final_rate_per_uom = flt(flt(valuation_rate) * factor, prec["rate_per_uom"])
        else:
            final_rate_per_uom = rate_per_uom
    else:
        p_rate = prec["rate_per_uom"]
        r_uom = flt(rate_per_uom, p_rate)
        if (
            valuation_rate not in (None, "")
            and flt(flt(valuation_rate) * factor, p_rate) == r_uom
        ):
            final_val_rate = valuation_rate
        else:
            final_val_rate = flt(r_uom / factor, prec["valuation_rate"])
        final_rate_per_uom = r_uom

    return {
        "custom_conversion_factor": factor,
        "custom_qty_before": before,
        "custom_qty_after": qty_after,
        "custom_qty_difference_per_uom": diff,
        "custom_valuation_rate_per_uom": final_rate_per_uom,
        "qty": final_qty,
        "valuation_rate": final_val_rate,
    }


def apply_to_doc(doc) -> None:
    """Convert every convertible row of doc.items in place using doc posting timestamp."""
    rows = _get_val(doc, "items") or []
    if not rows:
        return

    convertible_rows = [r for r in rows if is_convertible(r)]
    if not convertible_rows:
        return

    pairs = []
    for row in convertible_rows:
        item_code = _get_val(row, "item_code")
        uom = _get_val(row, SR_UOM_FIELD)
        stock_uom = _get_val(row, "stock_uom") or frappe.get_cached_value("Item", item_code, "stock_uom")
        pairs.append((item_code, uom, stock_uom))

    factors = resolve_factors(pairs)

    # Validate factors before mutating any row (atomic)
    for row in convertible_rows:
        item_code = _get_val(row, "item_code")
        uom = _get_val(row, SR_UOM_FIELD)
        factor = factors.get((item_code, uom))
        if not factor:
            frappe.throw(
                _("UOM {0} untuk Item {1} pada Stock Reconciliation tidak valid: harus sama "
                  "dengan Stock UOM, atau ditambahkan dulu ke tabel UOM Conversion item "
                  "tersebut.").format(frappe.bold(uom), frappe.bold(item_code))
            )

    posting_date = _get_val(doc, "posting_date")
    posting_time = _get_val(doc, "posting_time")
    ledger_cache = {}

    computed = []
    for row in convertible_rows:
        item_code = _get_val(row, "item_code")
        uom = _get_val(row, SR_UOM_FIELD)
        warehouse = _get_val(row, "warehouse")
        batch_no = _get_val(row, "batch_no")
        factor = factors[(item_code, uom)]
        l_qty = ledger_qty(
            item_code, warehouse, posting_date, posting_time, ledger_cache, batch_no=batch_no
        )
        prec = precisions(row)
        qty_after = _get_val(row, SR_AFTER_FIELD)
        rate_per_uom = _get_val(row, SR_RATE_FIELD)
        qty = _get_val(row, "qty")
        val_rate = _get_val(row, "valuation_rate")
        allow_zero = bool(_get_val(row, "allow_zero_valuation_rate", False))

        res = compute_row(
            factor=factor,
            ledger_qty=l_qty,
            qty_after=qty_after,
            rate_per_uom=rate_per_uom,
            qty=qty,
            valuation_rate=val_rate,
            allow_zero_valuation_rate=allow_zero,
            prec=prec,
        )
        computed.append((row, res))

    # Assign computed values
    for row, res in computed:
        _set_val(row, SR_FACTOR_FIELD, res["custom_conversion_factor"])
        _set_val(row, SR_BEFORE_FIELD, res["custom_qty_before"])
        _set_val(row, SR_AFTER_FIELD, res["custom_qty_after"])
        _set_val(row, SR_DIFF_FIELD, res["custom_qty_difference_per_uom"])
        if res["custom_valuation_rate_per_uom"] is not None:
            _set_val(row, SR_RATE_FIELD, res["custom_valuation_rate_per_uom"])
        _set_val(row, "qty", res["qty"])
        if res["valuation_rate"] is not None:
            _set_val(row, "valuation_rate", res["valuation_rate"])
