# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto
# License: MIT

# Pemasangan idempoten non-doctype warehouse_app (after_install & after_migrate).
# Pola mengikuti production_app.upgrade (satu app satu kepemilikan data; R7).
#
# Konteks W6: nav atas /desk dirender dari dokumen Desktop Icon yang menunjuk
# Workspace Sidebar (link_type "Workspace Sidebar"); grup "Gudang" hanya tampak
# bila keduanya ada. File JSON workspace_sidebar/gudang/gudang.json tetap sumber
# sync; fungsi di sini jaring pengaman idempoten.

import frappe

SIDEBAR = "Gudang"
APP = "warehouse_app"
ROLE = "Gudang Barang Jadi"
SIDEBAR_ICON = "package"

# Nav grup "Gudang" di sidebar Desk. Icon = nama set lucide frappe v16
# (icon-<name> di public/icons/lucide/icons.svg); "package" dipakai bersama
# Desktop Icon & workspace agar satu identitas. Selaras JSON sync:
# warehouse_app/warehouse_app/workspace_sidebar/gudang/gudang.json
SIDEBAR_ITEMS = [
    {
        "label": "Gudang",
        "link_to": "Gudang",
        "link_type": "Workspace",
        "type": "Link",
        "icon": "package",
        "idx": 1,
    },
    {
        "label": "Handover Requests",
        "link_to": "gudang_request",
        "link_type": "Page",
        "type": "Link",
        "icon": "clipboard-list",
        "idx": 2,
    },
    {
        "label": "Serah Terima Gudang",
        "link_to": "Serah Terima Gudang",
        "link_type": "Report",
        "type": "Link",
        "icon": "truck",
        "idx": 3,
    },
    {
        "label": "Settings",
        "link_to": "gudang_settings",
        "link_type": "Page",
        "type": "Link",
        "icon": "settings",
        "idx": 4,
    },
]


def apply():
    ensure_role()
    ensure_workspace_sidebar()
    ensure_desktop_icon()
    ensure_single_desk_entry()
    ensure_item_fields()
    ensure_client_scripts()
    migrate_legacy_uom_field()


def ensure_role():
    # Site baru (mis. Frappe Cloud) belum punya role ini, padahal workspace
    # dan Page gudang di-scope ke role ini — jamin ada sejak install/migrate.
    if frappe.db.exists("Role", ROLE):
        return "unchanged"
    doc = frappe.get_doc({"doctype": "Role", "role_name": ROLE, "desk_access": 1})
    doc.flags.ignore_permissions = 1
    doc.insert()
    frappe.db.commit()
    return "created"


def ensure_workspace_sidebar():
    if not frappe.db.exists("Workspace Sidebar", SIDEBAR):
        doc = frappe.get_doc(
            {
                "doctype": "Workspace Sidebar",
                "title": SIDEBAR,
                "header_icon": SIDEBAR_ICON,
                "app": APP,
                "standard": 1,
                "items": [dict(item, doctype="Workspace Sidebar Item") for item in SIDEBAR_ITEMS],
            }
        )
        doc.flags.ignore_permissions = 1
        doc.insert()
        frappe.db.commit()
        return "created"

    row = frappe.db.get_value(
        "Workspace Sidebar", SIDEBAR, ["app", "standard", "header_icon"], as_dict=1
    )
    if row and (row.app != APP or not row.standard):
        frappe.log_error(
            title="warehouse_app.upgrade",
            message=f"Workspace Sidebar {SIDEBAR!r} sudah ada tapi app={row.app!r} "
            f"standard={row.standard!r} — tidak diubah (satu pemilik data).",
        )
        return "unchanged"

    # bench migrate tidak men-sync JSON workspace_sidebar, jadi record DB yang
    # sudah ada disinkronkan di sini (tambah item/ubah icon hasil W16 dst).
    doc = frappe.get_doc("Workspace Sidebar", SIDEBAR)
    changed = []
    if row.header_icon != SIDEBAR_ICON:
        doc.header_icon = SIDEBAR_ICON
        changed.append("header_icon")
    if not _sidebar_items_match(doc.items):
        doc.set("items", [dict(item, doctype="Workspace Sidebar Item") for item in SIDEBAR_ITEMS])
        changed.append("items")
    if not changed:
        return "unchanged"
    doc.flags.ignore_permissions = 1
    doc.save()
    frappe.db.commit()
    return "synced"


def _sidebar_items_match(rows):
    current = [
        {
            "label": r.label,
            "link_to": r.link_to,
            "link_type": r.link_type,
            "type": r.type,
            "icon": r.icon or None,
            "idx": r.idx,
        }
        for r in sorted(rows, key=lambda r: r.idx or 0)
    ]
    return current == SIDEBAR_ITEMS


def ensure_desktop_icon():
    name = frappe.db.get_value("Desktop Icon", {"label": SIDEBAR}, "name")
    if name:
        row = frappe.db.get_value("Desktop Icon", name, ["link_to", "app"], as_dict=1)
        if row and (row.link_to != SIDEBAR or row.app != APP):
            frappe.log_error(
                title="warehouse_app.upgrade",
                message=f"Desktop Icon {SIDEBAR!r} sudah ada tapi link_to={row.link_to!r} "
                f"app={row.app!r} — tidak diubah (satu pemilik data).",
            )
        return "unchanged"
    doc = frappe.get_doc(
        {
            "doctype": "Desktop Icon",
            "label": SIDEBAR,
            "icon_type": "Link",
            "link_type": "Workspace Sidebar",
            "link_to": SIDEBAR,
            "icon": "package",
            "standard": 0,
            "app": APP,
        }
    )
    doc.flags.ignore_permissions = 1
    doc.insert()
    frappe.db.commit()
    return "created"


# ---------------------------------------------------------------- W22 ----
# Satu pintu desk. Native membuat ikon App dari add_to_apps_screen berlabel
# JUDUL app ("Warehouse App" -> /app/gudang) DAN ikon Workspace berlabel NAMA
# workspace ("Gudang" -> group sidebar); dedup native hanya jalan saat keduanya
# bernama sama (create_desktop_icons_from_workspace: label == app_title ->
# hidden) — workspace kita "Gudang" ≠ "Warehouse App", jadi keduanya tampil
# dan menuju halaman yang sama. Ikon grup "Gudang" (mekanisme nav W6) yang
# dipertahankan; ikon App disembunyikan dari desk. Entri apps screen Frappe
# Cloud (hook add_to_apps_screen) tidak terpengaruh — itu bukan Desktop Icon.
APP_TITLE_ICON = "Warehouse App"


def ensure_single_desk_entry():
    name = frappe.db.exists(
        "Desktop Icon", {"label": APP_TITLE_ICON, "icon_type": "App", "app": APP}
    )
    if not name:
        return "absent"
    if frappe.db.get_value("Desktop Icon", name, "hidden"):
        return "unchanged"
    frappe.db.set_value("Desktop Icon", name, "hidden", 1)
    # db.set_value tidak lewat on_update — ikuti pola cache-clear ikon standard
    frappe.cache.delete_key("desktop_icons")
    frappe.cache.delete_key("bootinfo")
    frappe.db.commit()
    return "hidden"


def on_app_installed(app_name=None):
    """after_app_install: native auto_generate_icons_and_sidebar membuat ikon
    App SETELAH after_install kita (installer.py memanggil hook ini sesudah
    hook frappe, dgn arg nama app), jadi fresh install butuh titik ini agar
    langsung satu pintu tanpa menunggu migrate pertama."""
    ensure_single_desk_entry()


# ---------------------------------------------------------------- W21 ----
# "Default Inventory UOM" per Item + kolom display rate per UOM di Stock
# Entry Detail + 3 Client Script (native users tetap tak terpengaruh: field
# kosong = perilaku native, script ber-role gate).

ITEM_UOM_FIELD = "custom_default_inventory_unit_of_measure"
SE_RATE_FIELD = "custom_basic_rate_per_uom"
LEGACY_UOM_FIELD = "custom_default_uom_warehouse"  # milik production_app
SCRIPT_MARKER = "// warehouse_app W21 inventory-uom"

# Anchor (item.json v16, Inventory tab): tabel `uoms` (line ~442) langsung
# mengikuti Section Break `unit_of_measure_conversion` (line ~438) — bukan
# Column Break, jadi insert_after ke Section Break tsb menempatkan field kita
# di dalam section konversi, tepat di atas tabel UOM Conversion.
ITEM_FIELD_SPEC = {
    "dt": "Item",
    "fieldname": ITEM_UOM_FIELD,
    "label": "Default Inventory UOM",
    "fieldtype": "Link",
    "options": "UOM",
    "insert_after": "unit_of_measure_conversion",
    "description": "UOM used for internal transactions (Stock Entry, Material Request). "
    "Must exist in the UOM Conversion table below. Empty = stock UOM.",
}

SE_FIELD_SPEC = {
    "dt": "Stock Entry Detail",
    "fieldname": SE_RATE_FIELD,
    "label": "Basic Rate (as per UOM)",
    "fieldtype": "Currency",
    "read_only": 1,
    "in_list_view": 1,
    "insert_after": "basic_rate",
    "allow_on_submit": 1,
    "description": "Rate per this row's UOM (display only) = Basic Rate × conversion factor",
}

# Role "Gudang Barang Jadi" — konsisten dengan konstanta ROLE di atas; ditulis
# literal di JS karena script berjalan di sisi klien.
ROLE_JS = "Gudang Barang Jadi"

CLIENT_SCRIPT_ITEM = SCRIPT_MARKER + """ — Default Inventory UOM helpers on Item.
// Link query for the custom field is limited to stock UOM + UOM Conversion
// rows; when stock UOM changes, native clears the UOM Conversion table —
// clear the field too if it is no longer a valid choice. Server-side
// validation (warehouse_app.inventory_uom) stays the hard guard.

(function () {
	function allowed_uoms(frm) {
		return [frm.doc.stock_uom]
			.concat((frm.doc.uoms || []).map((row) => row.uom))
			.filter(Boolean);
	}

	function set_uom_query(frm) {
		// compute inside the callback: frm.doc is live, so UOMs picked/rows
		// added after form load are included without waiting for a refresh
		frm.set_query("custom_default_inventory_unit_of_measure", () => ({
			filters: { name: ["in", allowed_uoms(frm)] },
		}));
	}

	function clear_invalid_uom(frm) {
		const value = frm.doc.custom_default_inventory_unit_of_measure;
		if (!value || allowed_uoms(frm).includes(value)) return;
		frm.set_value("custom_default_inventory_unit_of_measure", "");
		frappe.msgprint(
			__("Default Inventory UOM {0} was cleared: it is neither the Stock UOM nor in the UOM Conversion table.", [value])
		);
	}

	frappe.ui.form.on("Item", {
		refresh(frm) {
			set_uom_query(frm);
		},
		stock_uom(frm) {
			if (!frm.doc.custom_default_inventory_unit_of_measure) return;
			frappe.after_ajax(() => clear_invalid_uom(frm));
		},
	});
})();
"""

# Race-safety: standard doctype JS evaluates before Client Scripts, so the
# native item_code handler runs first and issues get_item_details whose
# callback resets row.uom to stock_uom. frappe.after_ajax queues our override
# behind every ajax pending at handler time (request.js drains
# waiting_for_ajax after ajax_count reaches 0), so it strictly runs after the
# native callback. Setting row uom then reuses the native `uom` handler chain
# (get_uom_details -> conversion_factor + transfer_qty -> set_basic_rate ->
# basic_amount); conversion_factor is passed explicitly as belt and braces.
# custom_basic_rate_per_uom is live-updated on uom/conversion_factor/basic_rate
# changes (display-only, mirrors server-side compute_rate_per_uom).
CLIENT_SCRIPT_STOCK_ENTRY = SCRIPT_MARKER + """ — default row UOM + display rate on Stock Entry.
// Gudang-only: every handler returns early without the warehouse role, so
// native users are unaffected.

(function () {
	const W21_ROLE = """ + '"' + ROLE_JS + '"' + """;

	function update_rate_per_uom(cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row) return;
		frappe.model.set_value(
			cdt,
			cdn,
			"custom_basic_rate_per_uom",
			flt(row.basic_rate) * flt(row.conversion_factor || 1)
		);
	}

	function apply_inventory_uom(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row || !row.item_code) return;
		frappe.db
			.get_value("Item", row.item_code, "custom_default_inventory_unit_of_measure")
			.then((r) => {
				const target = r.message && r.message.custom_default_inventory_unit_of_measure;
				const current = locals[cdt][cdn];
				if (!target || !current || current.uom === target) return;
				frappe.xcall("erpnext.stock.get_item_details.get_conversion_factor", {
					item_code: current.item_code,
					uom: target,
				}).then((res) => {
					const factor = flt(res && res.conversion_factor);
					const live = locals[cdt][cdn];
					if (!factor || !live || live.uom === target) return;
					frappe.model.set_value(cdt, cdn, "uom", target);
					frappe.model.set_value(cdt, cdn, "conversion_factor", factor);
				});
			});
	}

	frappe.ui.form.on("Stock Entry Detail", {
		item_code(frm, cdt, cdn) {
			if (!frappe.user.has_role(W21_ROLE)) return;
			frappe.after_ajax(() => apply_inventory_uom(frm, cdt, cdn));
		},
		uom(frm, cdt, cdn) {
			if (!frappe.user.has_role(W21_ROLE)) return;
			update_rate_per_uom(cdt, cdn);
		},
		conversion_factor(frm, cdt, cdn) {
			if (!frappe.user.has_role(W21_ROLE)) return;
			update_rate_per_uom(cdt, cdn);
		},
		basic_rate(frm, cdt, cdn) {
			if (!frappe.user.has_role(W21_ROLE)) return;
			update_rate_per_uom(cdt, cdn);
		},
	});
})();
"""

# Race-safety: same frappe.after_ajax pattern as Stock Entry — native item_code
# handler (standard JS first) clears row.uom and fires get_item_data; its
# callback writes uom = stock_uom DIRECTLY on the row (not via set_value) and
# Material Request Item has no `uom` change handler, so after overriding
# uom + conversion_factor we re-drive the native conversion_factor handler
# (frm.events.get_item_data with the new uom in ctx) so rate/stock_qty
# reconvert to the chosen UOM.
CLIENT_SCRIPT_MATERIAL_REQUEST = SCRIPT_MARKER + """ — default row UOM on Material Request.
// Gudang-only: handler returns early without the warehouse role.

(function () {
	const W21_ROLE = """ + '"' + ROLE_JS + '"' + """;

	function apply_inventory_uom(frm, doctype, name) {
		const row = locals[doctype][name];
		if (!row || !row.item_code) return;
		frappe.db
			.get_value("Item", row.item_code, "custom_default_inventory_unit_of_measure")
			.then((r) => {
				const target = r.message && r.message.custom_default_inventory_unit_of_measure;
				const current = locals[doctype][name];
				if (!target || !current || current.uom === target) return;
				frappe.xcall("erpnext.stock.get_item_details.get_conversion_factor", {
					item_code: current.item_code,
					uom: target,
				}).then((res) => {
					const factor = flt(res && res.conversion_factor);
					const live = locals[doctype][name];
					if (!factor || !live || live.uom === target) return;
					frappe.model
						.set_value(doctype, name, "uom", target)
						.then(() => {
							// triggers the native conversion_factor handler ->
							// get_item_data with the new uom in ctx, converting
							// rate/stock_qty to the chosen UOM
							frappe.model.set_value(doctype, name, "conversion_factor", factor);
						});
				});
			});
	}

	frappe.ui.form.on("Material Request Item", {
		item_code(frm, doctype, name) {
			if (!frappe.user.has_role(W21_ROLE)) return;
			frappe.after_ajax(() => apply_inventory_uom(frm, doctype, name));
		},
	});
})();
"""

CLIENT_SCRIPTS = [
    # name eksplisit: autoname Client Script = "Prompt" (naming.py menolak
    # insert tanpa name). Lookup idempoten tetap via marker, bukan name.
    {"name": "warehouse-app-w21-item-uom", "dt": "Item", "script": CLIENT_SCRIPT_ITEM},
    {"name": "warehouse-app-w21-stock-entry-uom", "dt": "Stock Entry", "script": CLIENT_SCRIPT_STOCK_ENTRY},
    {
        "name": "warehouse-app-w21-material-request-uom",
        "dt": "Material Request",
        "script": CLIENT_SCRIPT_MATERIAL_REQUEST,
    },
]


def ensure_item_fields():
    results = [_ensure_custom_field(ITEM_FIELD_SPEC), _ensure_custom_field(SE_FIELD_SPEC)]
    frappe.clear_cache(doctype="Item")
    frappe.clear_cache(doctype="Stock Entry Detail")
    if "created" in results or "updated" in results:
        frappe.db.commit()
    return "created" if "created" in results else ("updated" if "updated" in results else "unchanged")


def _ensure_custom_field(spec):
    """Upsert Custom Field idempoten: drift spec diperbarui via save (tanpa
    insert_after — penempatan sudah final, meniru pola production_app)."""
    name = frappe.db.get_value(
        "Custom Field", {"dt": spec["dt"], "fieldname": spec["fieldname"]}, "name"
    )
    if name:
        doc = frappe.get_doc("Custom Field", name)
        changed = []
        for key, val in spec.items():
            if key in ("dt", "fieldname", "insert_after"):
                continue
            if doc.get(key) != val:
                doc.set(key, val)
                changed.append(key)
        if not changed:
            return "unchanged"
        doc.flags.ignore_permissions = 1
        doc.save()
        return "updated"
    doc = frappe.get_doc(dict(spec, doctype="Custom Field"))
    doc.flags.ignore_permissions = 1
    doc.insert()
    return "created"


def ensure_client_scripts():
    results = []
    for spec in CLIENT_SCRIPTS:
        name = frappe.db.get_value(
            "Client Script",
            {"dt": spec["dt"], "script": ("like", "%" + SCRIPT_MARKER + "%")},
            "name",
        )
        if not name and frappe.db.exists("Client Script", spec["name"]):
            # marker hilang karena edit manual — adopsi doc bernama sama, jangan
            # biarkan insert duplikat menjatuhkan after_migrate (bench migrate)
            name = spec["name"]
        if name:
            doc = frappe.get_doc("Client Script", name)
            if doc.script == spec["script"] and doc.enabled:
                results.append("unchanged")
                continue
            doc.script = spec["script"]
            doc.enabled = 1
            doc.flags.ignore_permissions = 1
            doc.save()
            results.append("updated")
            continue
        doc = frappe.get_doc(
            {
                "doctype": "Client Script",
                "name": spec["name"],
                "dt": spec["dt"],
                "view": "Form",
                "enabled": 1,
                "script": spec["script"],
            }
        )
        doc.flags.ignore_permissions = 1
        doc.insert()
        results.append("created")
    for dt in ("Item", "Stock Entry", "Material Request"):
        frappe.clear_cache(doctype=dt)
    if "created" in results or "updated" in results:
        frappe.db.commit()
    return "created" if "created" in results else ("updated" if "updated" in results else "unchanged")


def migrate_legacy_uom_field():
    """W21: produksi dulu punya custom_default_uom_warehouse (production_app).
    Salin ke field baru hanya bila lolos aturan validasi yang sama (= stock UOM
    atau ada di UOM Conversion). Idempoten: run kedua selalu copied 0."""
    if not frappe.get_meta("Item").has_field(LEGACY_UOM_FIELD):
        return "legacy field absent: skipped"
    rows = frappe.get_all(
        "Item",
        filters={LEGACY_UOM_FIELD: ("is", "set"), ITEM_UOM_FIELD: ("is", "not set")},
        fields=["name", "stock_uom", LEGACY_UOM_FIELD],
    )
    allowed = {}
    if rows:
        for r in frappe.get_all(
            "UOM Conversion Detail",
            filters={"parent": ("in", [row.name for row in rows])},
            fields=["parent", "uom"],
        ):
            allowed.setdefault(r.parent, set()).add(r.uom)
    copied = skipped = 0
    for row in rows:
        value = row.get(LEGACY_UOM_FIELD)
        if value == row.stock_uom or value in allowed.get(row.name, set()):
            frappe.db.set_value("Item", row.name, ITEM_UOM_FIELD, value, update_modified=False)
            copied += 1
        else:
            skipped += 1
    if copied:
        frappe.clear_cache(doctype="Item")
        frappe.db.commit()
    return f"copied {copied}, skipped {skipped}"
