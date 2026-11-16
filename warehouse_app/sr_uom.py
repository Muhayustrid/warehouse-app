# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto and contributors
# For license information, please see license.txt

"""Stock Reconciliation per-UOM conversion and row math module.

Consolidates all per-UOM calculation logic for Stock Reconciliation items,
ensuring consistent behavior between grid edits, Fetch Items, data import,
and document submission.
"""

from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import math
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
# Holds a hash of the ledger stock-UOM qty the count was checked against at the last save
# (hashed so blind-count outlet users cannot read system stock; field name kept from the
# retired confirmation token, whose old values simply never match).
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


def _master_stock_uom(item_code) -> str | None:
    """Item master is the only source of truth for the stock UOM; row payloads are not trusted."""
    if not hasattr(frappe, "get_cached_value"):
        return None
    return frappe.get_cached_value("Item", item_code, "stock_uom")


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


def _get_prec(field, default, target=None) -> int:
    """Field precision from the doc/row metadata, else the default.

    target=None resolves against a blank Stock Reconciliation Item, so the
    installed metadata (which already folds in the system float_precision) wins.
    """
    if target is None:
        target = frappe.new_doc("Stock Reconciliation Item")
    if hasattr(target, "precision"):
        p = target.precision(field)
        if p is not None:
            return p
    return default


def precisions(row=None) -> dict[str, int]:
    """Return precision dict for qty, valuation_rate, and rate_per_uom."""
    target = row if row is not None else frappe.new_doc("Stock Reconciliation Item")
    return {
        "qty": _get_prec("qty", 6, target),
        "valuation_rate": _get_prec("valuation_rate", 6, target),
        "rate_per_uom": _get_prec(SR_RATE_FIELD, 2, target),
        "qty_uom": _get_prec(SR_BEFORE_FIELD, 3, target),
    }


def validate_representable_after(row, qty_after) -> None:
    """Reject a counted qty that cannot be held exactly at its own field precision.

    The confirmation token never covers After, so an After that changes on
    storage/display (1.234 -> 1.23) would silently move the derived native qty
    after a reload. Reject instead of rounding: the user's count is authoritative.
    """
    prec_after = _get_prec(SR_AFTER_FIELD, 3, row)
    try:
        d_after = Decimal(str(qty_after))
    except (InvalidOperation, TypeError, ValueError):
        return  # malformed input is reported by validate_representable_qty

    if not d_after.is_finite() or d_after == round(d_after, prec_after):
        return

    frappe.throw(
        _(
            "Baris {0} ({1}): Qty After {2} tidak dapat disimpan tepat pada presisi {3} desimal. "
            "Bulatkan hitungan ke {3} desimal atau kurang."
        ).format(
            _get_val(row, "idx") or "",
            _get_val(row, "item_code"),
            qty_after,
            prec_after,
        )
    )


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


def _validated_custom_rows(doc):
    """Validate every custom-UOM count row; return (custom_rows, master factors).

    Rejects serial/bundle rows, empty After, a UOM without a master factor and
    an After or stock-UOM qty that cannot be stored exactly.
    """
    rows = _get_val(doc, "items") or []
    custom_rows = [r for r in rows if _get_val(r, SR_UOM_FIELD)]
    if not custom_rows:
        return [], {}

    for row in custom_rows:
        if _get_val(row, "serial_no") or _get_val(row, "serial_and_batch_bundle"):
            frappe.throw(
                _(
                    "Baris {0} ({1}) menggunakan custom UOM dengan serial number atau bundle yang belum didukung."
                ).format(_get_val(row, "idx") or "", _get_val(row, "item_code"))
            )

    for row in custom_rows:
        if _get_val(row, SR_AFTER_FIELD) in (None, ""):
            frappe.throw(
                _("Baris {0} ({1}) belum dihitung: Qty After wajib diisi.").format(
                    _get_val(row, "idx") or "", _get_val(row, "item_code")
                )
            )

    factors = resolve_factors(
        [
            (_get_val(r, "item_code"), _get_val(r, SR_UOM_FIELD), _master_stock_uom(_get_val(r, "item_code")))
            for r in custom_rows
        ]
    )

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
        validate_representable_after(row, qa)
        validate_representable_qty(
            qa, factor, stock_uom=_master_stock_uom(item_code), prec_qty=precisions(row)["qty"]
        )

    return custom_rows, factors


def confirm_count_rows(doc) -> None:
    """Validate custom count rows and stamp the master factor (kept for POSNext callers).

    No confirmation step is needed any more: apply_to_doc validates on every save.
    """
    custom_rows, factors = _validated_custom_rows(doc)
    for row in custom_rows:
        _set_val(row, SR_FACTOR_FIELD, factors[(_get_val(row, "item_code"), _get_val(row, SR_UOM_FIELD))])


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


def _ledger_rate(item_code, warehouse, posting_date, posting_time) -> float:
    """Valuation rate of the last SLE at the posting timestamp (what native compares)."""
    from erpnext.stock.stock_ledger import get_previous_sle

    prev = get_previous_sle(
        {"item_code": item_code, "warehouse": warehouse, "posting_date": posting_date, "posting_time": posting_time}
    )
    return flt(prev.get("valuation_rate")) if prev else 0.0


def _dimension_fields() -> list[str]:
    from erpnext.stock.doctype.inventory_dimension.inventory_dimension import get_inventory_dimensions

    return [d.get("fieldname") for d in get_inventory_dimensions() if d.get("fieldname")]


def _match_unchanged_to_ledger(res, l_qty, l_rate, factor, prec) -> None:
    """Snap a no-change row onto the exact ledger values so the native filter removes it.

    Compared in stock UOM at qty precision. The rate counts as unchanged only when it is
    empty or equal to the ledger rate at valuation precision, so any revaluation is kept.
    Zero stock is left to native, which keeps rows that must clear a residual stock value.
    """
    if not flt(l_qty, prec["qty"]) or flt(res["qty"], prec["qty"]) != flt(l_qty, prec["qty"]):
        return
    rate = res["valuation_rate"]
    if rate not in (None, "") and flt(rate, prec["valuation_rate"]) != flt(l_rate, prec["valuation_rate"]):
        return
    res["qty"] = l_qty
    res["valuation_rate"] = l_rate


def _assert_factor_current(row, factor) -> None:
    """Reject a row converted with a factor that no longer matches the Item master.

    The row carries the factor its count was entered with (compute_row, Fetch Items, import,
    confirm_count_rows). A master change since then fails clearly instead of silently
    re-scaling the stock qty (e.g. at HQ approval); re-entering the UOM or After, or the
    POSNext outlet re-confirm, stamps the current factor.
    """
    entered = _get_val(row, SR_FACTOR_FIELD)
    if entered in (None, "") or not flt(entered) or abs(flt(entered) - flt(factor)) < 1e-9:
        return
    frappe.throw(
        _(
            "Konfirmasi hitungan untuk baris {0} ({1}) tidak cocok dengan konteks dokumen saat ini: "
            "faktor konversi {2} berubah dari {3} menjadi {4} di master item. "
            "Pilih ulang UOM atau isi ulang Qty After, lalu simpan lagi."
        ).format(
            _get_val(row, "idx") or "",
            _get_val(row, "item_code"),
            _get_val(row, SR_UOM_FIELD),
            flt(entered),
            flt(factor),
        )
    )


def _ledger_mark(row, l_qty, prec_qty) -> str:
    """Opaque mark of the ledger qty a row was checked against (no stock value exposed)."""
    payload = f"{_get_val(row, 'item_code')}|{_get_val(row, 'warehouse')}|{flt(l_qty, prec_qty):.9f}"
    # Keyed with the site secret so a small qty range cannot be brute-forced back.
    conf = getattr(getattr(frappe, "local", None), "conf", None) or {}
    key = str(conf.get("encryption_key") or "warehouse_app").encode("utf-8")
    return "L" + hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:31]


def _assert_ledger_unchanged(row, prev_row, l_qty, prec_qty) -> None:
    """Submit guard: the count was checked against the ledger at the last save."""
    saved = _get_val(prev_row, SR_CONFIRMATION_FIELD) if prev_row else None
    if not saved or not str(saved).startswith("L"):
        return  # legacy token or never saved by this version
    if saved == _ledger_mark(row, l_qty, prec_qty):
        return
    frappe.throw(
        _(
            "Stok sistem baris {0} ({1}) berubah sejak disimpan (sekarang {2} {3}). "
            "Periksa ulang hitungan, lalu Simpan lagi sebelum Submit."
        ).format(
            _get_val(row, "idx") or "",
            _get_val(row, "item_code"),
            flt(l_qty, prec_qty),
            _master_stock_uom(_get_val(row, "item_code")) or "",
        )
    )


def apply_to_doc(doc) -> None:
    """Validate and convert every custom row in doc.items (After x master factor -> stock qty).

    Stock-UOM qty is the source of truth: a row whose converted qty and rate equal the
    ledger is normalised to the exact ledger values so native remove_items_with_no_change
    drops it. A row whose entered factor no longer matches the master is rejected on any
    save; on submit, a row whose ledger qty changed since the last save is rejected.
    Native-only rows are left untouched.
    """
    rows = _get_val(doc, "items") or []
    if not rows:
        return

    # Check against get_doc_before_save: removing custom_uom/confirmation from
    # a previously saved counted row is not a silent fallback to native.
    get_before = getattr(doc, "get_doc_before_save", None)
    prev_doc = get_before() if callable(get_before) else None
    prev_rows = {}
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

    custom_rows, factors = _validated_custom_rows(doc)
    if not custom_rows:
        return

    posting_date = _get_val(doc, "posting_date")
    posting_time = _get_val(doc, "posting_time")
    is_submit = getattr(doc, "_action", None) == "submit"
    dim_fields = _dimension_fields()

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
        stock_uom = _master_stock_uom(item_code)

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
        # shortcut: ledger_qty/_ledger_rate are warehouse-level, so inventory-dimension rows skip
        # the ledger guard and the snap (native still matches them); add dimension filters if used.
        has_dim = any(_get_val(row, f) for f in dim_fields)
        _assert_factor_current(row, factor)
        if is_submit and prev_doc and not has_dim:
            _assert_ledger_unchanged(row, prev_rows.get(_get_val(row, "name")), l_qty, prec["qty"])
        # The ledger rate is only looked up when the stock qty already matches (one query saved per changed row).
        if not batch_no and not has_dim and flt(res["qty"], prec["qty"]) == flt(l_qty, prec["qty"]):
            _match_unchanged_to_ledger(
                res, l_qty, _ledger_rate(item_code, warehouse, posting_date, posting_time),
                factor, prec,
            )
        computed.append((row, res, l_qty))

    for row, res, l_qty in computed:
        _set_val(row, SR_CONFIRMATION_FIELD, _ledger_mark(row, l_qty, precisions(row)["qty"]))
        _set_val(row, SR_FACTOR_FIELD, res["custom_conversion_factor"])
        _set_val(row, SR_BEFORE_FIELD, res["custom_qty_before"])
        _set_val(row, SR_AFTER_FIELD, res["custom_qty_after"])
        _set_val(row, SR_DIFF_FIELD, res["custom_qty_difference_per_uom"])
        if res["custom_valuation_rate_per_uom"] is not None:
            _set_val(row, SR_RATE_FIELD, res["custom_valuation_rate_per_uom"])
        _set_val(row, "qty", res["qty"])
        if res["valuation_rate"] is not None:
            _set_val(row, "valuation_rate", res["valuation_rate"])
