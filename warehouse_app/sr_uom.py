# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto and contributors
# For license information, please see license.txt

"""Stock Reconciliation per-UOM conversion and row math module.

Consolidates all per-UOM calculation logic for Stock Reconciliation items,
ensuring consistent behavior between grid edits, Fetch Items, data import,
and document submission.
"""

from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from typing import Iterable

import frappe
from frappe import _
from frappe.utils import cint, flt

try:
    from frappe.utils import getdate, get_time
except ImportError:
    import datetime

    def getdate(string_date):
        if isinstance(string_date, datetime.datetime):
            return string_date.date()
        if isinstance(string_date, datetime.date):
            return string_date
        return datetime.date.fromisoformat(str(string_date)[:10])

    def get_time(string_time):
        if isinstance(string_time, datetime.datetime):
            return string_time.time()
        if isinstance(string_time, datetime.time):
            return string_time
        if isinstance(string_time, datetime.timedelta):
            total_seconds = int(string_time.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            return datetime.time(hours, minutes, seconds, string_time.microseconds)
        s = str(string_time).strip()
        parts = s.split(":")
        sec_parts = parts[2].split(".") if len(parts) > 2 else ["0"]
        sec = int(sec_parts[0])
        microsec = int(sec_parts[1].ljust(6, "0")[:6]) if len(sec_parts) > 1 else 0
        return datetime.time(
            int(parts[0]), int(parts[1]), sec, microsec
        )

SR_UOM_FIELD = "custom_uom"
SR_FACTOR_FIELD = "custom_conversion_factor"
SR_BEFORE_FIELD = "custom_qty_before"
SR_AFTER_FIELD = "custom_qty_after"
SR_RATE_FIELD = "custom_valuation_rate_per_uom"
SR_DIFF_FIELD = "custom_qty_difference_per_uom"
SR_CONFIRMATION_FIELD = "custom_count_confirmation"
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
        "qty_uom": _get_prec(SR_BEFORE_FIELD, 3),
    }


def validate_representable_qty(qty_after, factor, stock_uom=None, prec_qty=6) -> float:
    """Validate numeric finite input, positive factor, integer UOM, and precision representability.

    Returns float target qty in stock UOM, or throws actionable ValidationError.
    """
    try:
        d_after = Decimal(str(qty_after))
        d_factor = Decimal(str(factor))
    except (InvalidOperation, TypeError, ValueError):
        frappe.throw(
            _("Nilai After {0} atau faktor {1} tidak valid: harus berupa angka.").format(
                qty_after, factor
            )
        )

    f_after = float(d_after)
    f_factor = float(d_factor)
    if not math.isfinite(f_after) or not math.isfinite(f_factor):
        frappe.throw(
            _("Nilai After {0} atau faktor {1} tidak valid: harus finite.").format(
                qty_after, factor
            )
        )

    if d_factor <= 0:
        frappe.throw(_("Faktor konversi {0} harus positif.").format(factor))

    target = d_after * d_factor

    if stock_uom:
        must_be_whole = (
            frappe.get_cached_value("UOM", stock_uom, "must_be_whole_number")
            if hasattr(frappe, "get_cached_value")
            else None
        )
        if must_be_whole and (target % 1 != 0):
            frappe.throw(
                _(
                    "Hasil hitungan {0} {1} tidak dapat direpresentasikan: Stock UOM {2} harus berupa bilangan bulat."
                ).format(float(target), stock_uom, stock_uom)
            )

    rounded = round(target, prec_qty)
    if target != rounded:
        frappe.throw(
            _(
                "Target quantity {0} tidak dapat direpresentasikan dengan presisi {1} desimal."
            ).format(float(target), prec_qty)
        )

    return float(target)


def count_confirmation(
    *,
    company=None,
    item_code=None,
    warehouse=None,
    posting_date=None,
    posting_time=None,
    set_posting_time=0,
    uom=None,
    factor=None,
    batch_no=None,
) -> str:
    """Generate a deterministic bounded fingerprint of confirmed count context.

    Context rules:
    - set_posting_time=0: posting_context token is 'now' (timestamps changing on save/submit do not invalidate).
    - set_posting_time=1: normalized explicit date and time string.
    - Toggling set_posting_time invalidates.
    - Never stores After or native Qty.
    """
    if factor is None or flt(factor) <= 0 or not math.isfinite(flt(factor)):
        frappe.throw(
            _("Faktor konversi tidak valid untuk konfirmasi hitungan: {0}").format(factor)
        )

    clean_company = (company or "").strip()
    clean_item = (item_code or "").strip()
    clean_wh = (warehouse or "").strip()
    clean_uom = (uom or "").strip()
    clean_batch = (batch_no or "").strip() if batch_no else ""

    factor_str = f"{flt(factor):.9f}".rstrip("0").rstrip(".")

    is_explicit_time = bool(cint(set_posting_time))
    if is_explicit_time:
        if posting_date in (None, "") or posting_time in (None, ""):
            frappe.throw(
                _("Posting Date dan Posting Time wajib diisi untuk explicit posting time.")
            )
        d_str = getdate(posting_date).isoformat()
        t_str = get_time(posting_time).isoformat()
        posting_ctx = f"{d_str} {t_str}"
    else:
        posting_ctx = "now"

    canonical_payload = json.dumps(
        [
            clean_company,
            clean_item,
            clean_wh,
            posting_ctx,
            clean_uom,
            factor_str,
            clean_batch,
        ],
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()[:32]


def confirm_count_rows(doc) -> None:
    """Internal helper to validate explicit count rows and set custom_count_confirmation.

    Validates explicit non-empty custom_qty_after, resolves master factor,
    verifies precision representability, and sets custom_count_confirmation.
    Never returns balances or rates.
    """
    rows = _get_val(doc, "items") or []
    custom_rows = [r for r in rows if _get_val(r, SR_UOM_FIELD)]
    if not custom_rows:
        return

    company = _get_val(doc, "company")
    set_posting_time = _get_val(doc, "set_posting_time", 0)
    posting_date = _get_val(doc, "posting_date")
    posting_time = _get_val(doc, "posting_time")

    # Check unsupported serial / bundle combinations on custom rows
    for row in custom_rows:
        if _get_val(row, "serial_no") or _get_val(row, "serial_and_batch_bundle"):
            frappe.throw(
                _(
                    "Baris {0} ({1}) menggunakan custom UOM dengan serial number atau bundle yang belum didukung."
                ).format(_get_val(row, "idx") or "", _get_val(row, "item_code"))
            )

    # Check explicit non-empty custom_qty_after
    for row in custom_rows:
        qa = _get_val(row, SR_AFTER_FIELD)
        if qa in (None, ""):
            frappe.throw(
                _("Baris {0} ({1}) belum dihitung: Qty After wajib diisi.").format(
                    _get_val(row, "idx") or "", _get_val(row, "item_code")
                )
            )

    # Resolve master factors
    pairs = []
    for row in custom_rows:
        item_code = _get_val(row, "item_code")
        uom = _get_val(row, SR_UOM_FIELD)
        stock_uom = _get_val(row, "stock_uom") or frappe.get_cached_value(
            "Item", item_code, "stock_uom"
        )
        pairs.append((item_code, uom, stock_uom))

    factors = resolve_factors(pairs)

    for row in custom_rows:
        item_code = _get_val(row, "item_code")
        uom = _get_val(row, SR_UOM_FIELD)
        factor = factors.get((item_code, uom))
        if not factor or factor <= 0:
            frappe.throw(
                _(
                    "UOM {0} untuk Item {1} pada Stock Reconciliation tidak valid: harus sama "
                    "dengan Stock UOM, atau ditambahkan dulu ke tabel UOM Conversion item "
                    "tersebut."
                ).format(frappe.bold(uom), frappe.bold(item_code))
            )

        qa = _get_val(row, SR_AFTER_FIELD)
        stock_uom = _get_val(row, "stock_uom") or frappe.get_cached_value(
            "Item", item_code, "stock_uom"
        )
        prec = precisions(row)
        validate_representable_qty(qa, factor, stock_uom=stock_uom, prec_qty=prec["qty"])

        token = count_confirmation(
            company=company,
            item_code=item_code,
            warehouse=_get_val(row, "warehouse"),
            posting_date=posting_date,
            posting_time=posting_time,
            set_posting_time=set_posting_time,
            uom=uom,
            factor=factor,
            batch_no=_get_val(row, "batch_no"),
        )
        _set_val(row, SR_CONFIRMATION_FIELD, token)
        _set_val(row, SR_FACTOR_FIELD, factor)


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
    stock_uom: str | None = None,
) -> dict:
    """Compute per-UOM and native values for a single Stock Reconciliation row.

    One-way: After x factor -> native Qty. No rounded-equality preservation of stale native qty.
    Empty qty_after is not prefilled from ledger.
    """
    factor = flt(factor)
    ledger_q = flt(ledger_qty)
    prec_uom = prec.get("qty_uom", 3)
    before = flt(ledger_q / factor, prec_uom)

    if qty_after in (None, ""):
        final_after = None
        diff = None
        final_qty = qty if qty not in (None, "") else ledger_q
    else:
        final_after = flt(qty_after)
        final_qty = validate_representable_qty(
            qty_after, factor, stock_uom=stock_uom, prec_qty=prec["qty"]
        )
        diff = flt(final_after - before, prec_uom)
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
        "custom_qty_after": final_after,
        "custom_qty_difference_per_uom": diff,
        "custom_valuation_rate_per_uom": final_rate_per_uom,
        "qty": final_qty,
        "valuation_rate": final_val_rate,
    }


def apply_to_doc(doc) -> None:
    """Convert every custom row in doc.items after validating confirmation against doc context.

    Native-only rows are left untouched.
    """
    rows = _get_val(doc, "items") or []
    if not rows:
        return

    # Check against get_doc_before_save: removing custom_uom/confirmation from
    # a previously saved counted row is not a silent fallback to native.
    get_before = getattr(doc, "get_doc_before_save", None)
    prev_doc = get_before() if callable(get_before) else None
    if prev_doc:
        prev_items = _get_val(prev_doc, "items") or []
        prev_rows = {
            _get_val(r, "name"): r
            for r in prev_items
            if _get_val(r, "name")
        }
        for row in rows:
            rname = _get_val(row, "name")
            if not rname or rname not in prev_rows:
                continue
            prev_r = prev_rows[rname]
            if _get_val(prev_r, SR_UOM_FIELD) or _get_val(prev_r, SR_CONFIRMATION_FIELD):
                curr_uom = _get_val(row, SR_UOM_FIELD)
                if not curr_uom:
                    frappe.throw(
                        _(
                            "Baris {0} ({1}) adalah baris hitungan yang tersimpan. Menghapus UOM tidak diizinkan; hapus baris jika tidak diperlukan."
                        ).format(_get_val(row, "idx") or "", _get_val(row, "item_code"))
                    )

    custom_rows = [r for r in rows if _get_val(r, SR_UOM_FIELD)]
    if not custom_rows:
        return

    company = _get_val(doc, "company")
    set_posting_time = _get_val(doc, "set_posting_time", 0)
    posting_date = _get_val(doc, "posting_date")
    posting_time = _get_val(doc, "posting_time")

    # Check unsupported serial / bundle combinations on custom rows
    for row in custom_rows:
        if _get_val(row, "serial_no") or _get_val(row, "serial_and_batch_bundle"):
            frappe.throw(
                _(
                    "Baris {0} ({1}) menggunakan custom UOM dengan serial number atau bundle yang belum didukung."
                ).format(_get_val(row, "idx") or "", _get_val(row, "item_code"))
            )

    # Check uncounted custom rows
    for row in custom_rows:
        qa = _get_val(row, SR_AFTER_FIELD)
        if qa in (None, ""):
            frappe.throw(
                _("Baris {0} ({1}) belum dihitung: Qty After wajib diisi.").format(
                    _get_val(row, "idx") or "", _get_val(row, "item_code")
                )
            )

    # Check missing confirmation on custom rows
    for row in custom_rows:
        conf = _get_val(row, SR_CONFIRMATION_FIELD)
        if not conf:
            frappe.throw(
                _(
                    "Baris {0} ({1}) belum dikonfirmasi. Periksa dan konfirmasi hitungan fisik terlebih dahulu."
                ).format(_get_val(row, "idx") or "", _get_val(row, "item_code"))
            )

    # Resolve master factors atomically
    pairs = []
    for row in custom_rows:
        item_code = _get_val(row, "item_code")
        uom = _get_val(row, SR_UOM_FIELD)
        stock_uom = _get_val(row, "stock_uom") or frappe.get_cached_value(
            "Item", item_code, "stock_uom"
        )
        pairs.append((item_code, uom, stock_uom))

    factors = resolve_factors(pairs)

    # Validate master factors and confirmation matches current context
    for row in custom_rows:
        item_code = _get_val(row, "item_code")
        uom = _get_val(row, SR_UOM_FIELD)
        factor = factors.get((item_code, uom))
        if not factor or factor <= 0:
            frappe.throw(
                _(
                    "UOM {0} untuk Item {1} pada Stock Reconciliation tidak valid: harus sama "
                    "dengan Stock UOM, atau ditambahkan dulu ke tabel UOM Conversion item "
                    "tersebut."
                ).format(frappe.bold(uom), frappe.bold(item_code))
            )

        expected_conf = count_confirmation(
            company=company,
            item_code=item_code,
            warehouse=_get_val(row, "warehouse"),
            posting_date=posting_date,
            posting_time=posting_time,
            set_posting_time=set_posting_time,
            uom=uom,
            factor=factor,
            batch_no=_get_val(row, "batch_no"),
        )
        current_conf = _get_val(row, SR_CONFIRMATION_FIELD)
        if current_conf != expected_conf:
            frappe.throw(
                _(
                    "Konfirmasi hitungan untuk baris {0} ({1}) tidak cocok dengan konteks dokumen saat ini "
                    "(konteks atau faktor master berubah). Periksa dan konfirmasi ulang hitungan fisik."
                ).format(_get_val(row, "idx") or "", item_code)
            )

        qa = _get_val(row, SR_AFTER_FIELD)
        stock_uom = _get_val(row, "stock_uom") or frappe.get_cached_value(
            "Item", item_code, "stock_uom"
        )
        prec = precisions(row)
        validate_representable_qty(qa, factor, stock_uom=stock_uom, prec_qty=prec["qty"])

    # All custom rows validated! Now compute and apply atomically
    ledger_cache = {}
    computed = []
    for row in custom_rows:
        item_code = _get_val(row, "item_code")
        uom = _get_val(row, SR_UOM_FIELD)
        warehouse = _get_val(row, "warehouse")
        batch_no = _get_val(row, "batch_no")
        factor = factors[(item_code, uom)]
        l_qty = ledger_qty(
            item_code,
            warehouse,
            posting_date,
            posting_time,
            ledger_cache,
            batch_no=batch_no,
        )
        prec = precisions(row)
        qty_after = _get_val(row, SR_AFTER_FIELD)
        rate_per_uom = _get_val(row, SR_RATE_FIELD)
        qty = _get_val(row, "qty")
        val_rate = _get_val(row, "valuation_rate")
        allow_zero = bool(_get_val(row, "allow_zero_valuation_rate", False))
        stock_uom = _get_val(row, "stock_uom") or frappe.get_cached_value(
            "Item", item_code, "stock_uom"
        )

        res = compute_row(
            factor=factor,
            ledger_qty=l_qty,
            qty_after=qty_after,
            rate_per_uom=rate_per_uom,
            qty=qty,
            valuation_rate=val_rate,
            allow_zero_valuation_rate=allow_zero,
            prec=prec,
            stock_uom=stock_uom,
        )
        computed.append((row, res))

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
