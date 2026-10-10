# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto
# License: MIT

# Gate W16 — sejak W34 (2026-10-02) berubah fungsi: verifikasi PENSIUNAN UI
# Desk klasik (sebelumnya: verifikasi isi Workspace Sidebar "Gudang").
#
# Jalankan:
#   docker exec 1oktober2026-backend-1 bench --site 1oktober2026 execute \
#       "frappe.get_attr('warehouse_app.tests.w16_gate.run_gate')()"
#
# Kontrak output: TEPAT satu baris GATE_JSON:{...} (pola w5_gate).
#
# Invarian yang dijaga (W34, keputusan user "hapus semua halaman lama"):
# 1. Record lama LENYAP dari DB dan tetap lenyap setelah apply() dijalankan
#    lagi (idempoten): Page gudang_request/gudang_settings, Workspace "Gudang",
#    Workspace Sidebar "Gudang" (+ 0 child items), Desktop Icon grup.
# 2. Kontrak SPA TETAP HIDUP: 6 endpoint whitelisted (requestable_work_orders,
#    filter_fields, warehouse_options, get/set_handover_warehouses,
#    get/set_group_items) — frappe 16 memakai global set `whitelisted` (bukan
#    atribut per-fungsi); requestable_work_orders callable dan mengembalikan
#    list; Report "Serah Terima Gudang" ada (report Desk; SPA Monitoring-nya
#    dihapus W43 — requests + Inventory Movements dianggap cukup user).
# 3. Redirect konfigurasi lengkap: hooks website_redirects memuat
#    /app/gudang, /app/gudang_request, /app/gudang_settings.
# 4. Render Desk nyata via frappe.boot.get_sidebar_items dgn fixture user
#    SM+SU ber-email UNIK per run: TIDAK ada lagi item grup Gudang/URL SPA
#    maupun workspace "Gudang" di sidebar Desk. Teardown residu ZZTEST-W16 = 0.

import json
import time
import traceback

import frappe
from frappe.boot import get_sidebar_items
from frappe.desk.desktop import get_workspaces as get_sidebar_workspaces

from warehouse_app.tests.guard import count_residue
from warehouse_app.upgrade import APP, SIDEBAR, retire_legacy_desk_ui

PREFIX = "ZZTEST-W16"
ROLE_PAIR = ["Stock Manager", "Stock User"]

SPA_URLS = {"/gudang", "/gudang/settings"}

REDIRECT_MAP = {
    "/app/gudang": "/gudang",
    "/app/gudang_request": "/gudang",
    "/app/gudang_settings": "/gudang/settings",
}

SPA_ENDPOINTS = [
    "warehouse_app.warehouse_app.gudang_request.requestable_work_orders",
    "warehouse_app.warehouse_app.gudang_request.filter_fields",
    "warehouse_app.warehouse_app.gudang_settings.warehouse_options",
    "warehouse_app.warehouse_app.gudang_settings.get_handover_settings",
    "warehouse_app.warehouse_app.gudang_settings.set_handover_warehouses",
    "warehouse_app.warehouse_app.gudang_settings.get_group_items",
    "warehouse_app.warehouse_app.gudang_settings.set_group_items",
]


def run_gate():
    checks = {}
    error = None

    def check(name, ok, evidence):
        checks[name] = str(evidence) if ok else f"GAGAL: {evidence}"

    try:
        _run_gate(check)
    except Exception:
        error = traceback.format_exc()
    finally:
        try:
            _teardown(check)
        except Exception as te:
            check("teardown", False, f"teardown error {type(te).__name__}: {te}")
        payload = {
            "ok": error is None and not any(v.startswith("GAGAL") for v in checks.values()),
            "checks": checks,
        }
        if error:
            payload["error"] = error[-2000:]
        print("GATE_JSON:" + json.dumps(payload, ensure_ascii=False))

    if error:
        raise SystemExit(1)


def _run_gate(check):
    check("pre_clean", *_sweep())

    # --- Jaring pengaman idempoten: dua kali retire, yang kedua no-op ---
    try:
        first = retire_legacy_desk_ui()
        check("retire_first", first.startswith("retired"), first)
        second = retire_legacy_desk_ui()
        check("retire_idempotent", second == "retired none", second)
    except Exception as e:
        check("retire_first", False, f"{type(e).__name__}: {str(e)[:200]}")
        return

    # --- Record lama lenyap dari DB ---
    pages_absent = {
        name: not frappe.db.exists("Page", name)
        for name in ("gudang_request", "gudang_settings")
    }
    check("pages_absent", all(pages_absent.values()), f"absent={pages_absent}")

    check("workspace_absent", not frappe.db.exists("Workspace", SIDEBAR),
          f"Workspace {SIDEBAR!r} exists={bool(frappe.db.exists('Workspace', SIDEBAR))}")

    sidebar_rows = frappe.get_all(
        "Workspace Sidebar Item",
        filters={"parenttype": "Workspace Sidebar", "parent": SIDEBAR},
        pluck="label",
    )
    check(
        "sidebar_absent",
        not frappe.db.exists("Workspace Sidebar", SIDEBAR) and not sidebar_rows,
        f"sidebar exists={bool(frappe.db.exists('Workspace Sidebar', SIDEBAR))} items={sidebar_rows}",
    )

    icon = frappe.db.get_value("Desktop Icon", {"label": SIDEBAR, "app": APP}, "name")
    check("desktop_icon_absent", not icon, f"Desktop Icon {SIDEBAR!r} name={icon}")

    # --- Kontrak SPA tetap hidup: endpoint whitelisted (global set frappe 16) ---
    from frappe import whitelisted

    missing = []
    for dotted in SPA_ENDPOINTS:
        try:
            fn = frappe.get_attr(dotted)
            if fn not in whitelisted:
                missing.append(dotted.rsplit(".", 1)[-1] + ":not-whitelisted")
        except Exception as e:
            missing.append(dotted.rsplit(".", 1)[-1] + f":{type(e).__name__}")
    check("spa_endpoints_whitelisted", not missing, f"missing={missing or 'tidak ada'}")

    try:
        rows = frappe.get_attr(SPA_ENDPOINTS[0])()
        check("spa_data_alive", isinstance(rows, list), f"requestable_work_orders -> list len={len(rows or [])}")
    except Exception as e:
        check("spa_data_alive", False, f"{type(e).__name__}: {str(e)[:180]}")

    check("report_alive", bool(frappe.db.exists("Report", "Serah Terima Gudang")),
          f"Report exists={bool(frappe.db.exists('Report', 'Serah Terima Gudang'))}")

    # --- Konfigurasi redirect hooks ---
    hooks = frappe.get_hooks("website_redirects") or []
    found = {
        src: [h.get("target") for h in hooks if str(h.get("source", "")).strip("/") == src.strip("/")]
        for src in REDIRECT_MAP
    }
    bad = sorted(k for k, v in found.items() if REDIRECT_MAP[k] not in v)
    check("redirects_configured", not bad, f"hooks={found} | kurang={bad or 'tidak ada'}")

    # --- Render Desk nyata: fixture SM+SU tidak lagi melihat apa pun dari app ini ---
    if not frappe.db.exists("Role", "Stock User"):
        check("fixture_role", False, "Role 'Stock User' tidak ada")
        return

    run_id = int(time.time())
    user_email = f"ZZTEST-W16-{run_id}@example.com"
    try:
        doc = frappe.get_doc(
            {
                "doctype": "User",
                "email": user_email,
                "first_name": PREFIX,
                "user_type": "System User",
                "send_welcome_email": 0,
                "new_password": frappe.generate_hash(length=16),
                "roles": [{"role": r} for r in ROLE_PAIR],
            }
        )
        doc.flags.ignore_permissions = True
        doc.insert()
        frappe.clear_cache(user=user_email)
        frappe.set_user(user_email)
        pages = get_sidebar_workspaces()["pages"]
        names = sorted(p.name for p in pages)
        sidebars = get_sidebar_items(names)
        leaked = sorted(
            f"{it.get('label')}->{it.get('link_to')}"
            for grp in sidebars.values()
            for it in grp.get("items", [])
            if it.get("link_to") in SPA_URLS or it.get("link_to") == SIDEBAR
        )
        check(
            "desk_render_clean",
            SIDEBAR not in names and not leaked,
            f"workspace_gudang_in_pages={SIDEBAR in names}; leaked_items={leaked or 'tidak ada'}",
        )
    except Exception as e:
        check("desk_render_clean", False, f"{type(e).__name__}: {str(e)[:180]}")
    finally:
        frappe.set_user("Administrator")


def _teardown(check):
    try:
        frappe.set_user("Administrator")
    except Exception:
        pass
    sweep_ok, sweep_evidence = _sweep()
    residue = count_residue(PREFIX)
    zero = all(v == 0 for v in residue.values())
    check("teardown", sweep_ok and zero, f"{sweep_evidence}; residu {PREFIX}={residue}")


def _sweep():
    """Bersihkan semua residu ber-prefix ZZTEST-W16. Idempoten (pre-clean & teardown)."""
    errors = []

    def safe(label, fn):
        try:
            fn()
        except Exception as e:
            errors.append(f"{label}: {type(e).__name__}: {str(e)[:120]}")

    for name in frappe.get_all("User", filters={"name": ("like", PREFIX + "%")}, pluck="name"):
        safe(f"User {name}", lambda n=name: frappe.delete_doc("User", n, force=1, ignore_missing=True))
    safe("Sessions", lambda: frappe.db.delete("Sessions", {"user": ("like", PREFIX + "%")}))
    safe("ActivityLog.user", lambda: frappe.db.delete("Activity Log", {"user": ("like", PREFIX + "%")}))
    if frappe.db.has_column("Activity Log", "for_user"):
        safe(
            "ActivityLog.for_user",
            lambda: frappe.db.delete("Activity Log", {"for_user": ("like", PREFIX + "%")}),
        )
    safe("Version", lambda: frappe.db.delete("Version", {"docname": ("like", PREFIX + "%")}))

    return (not errors), ("bersih" if not errors else "; ".join(errors[:5]))
