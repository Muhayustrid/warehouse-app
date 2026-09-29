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
    ensure_sr_fields()
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

# ---- W23 ----
# Kolom UOM di baris Stock Reconciliation: hitung stok dalam UOM pilihan
# baris (default = Default Inventory UOM item, W21). Native qty &
# valuation_rate tetap sumber kebenaran ledger — dikonversi server-side oleh
# warehouse_app.inventory_uom.apply_sr_inventory_uom (before_validate). Field
# kosong = native murni; client script di-gate role (SR_GATE_ROLES).

SR_SCRIPT_MARKER = "// warehouse_app W23 stock-reconciliation-uom"
SR_UOM_FIELD = "custom_uom"
SR_FACTOR_FIELD = "custom_conversion_factor"
SR_BEFORE_FIELD = "custom_qty_before"
SR_AFTER_FIELD = "custom_qty_after"
SR_RATE_FIELD = "custom_valuation_rate_per_uom"

SR_FIELD_SPECS = [
    {
        "dt": "Stock Reconciliation Item",
        "fieldname": SR_UOM_FIELD,
        "label": "UOM",
        "fieldtype": "Link",
        "options": "UOM",
        "in_list_view": 1,
        "insert_after": "qty",
        "description": "UOM for counting this row. Defaults to the item's Default Inventory UOM "
        "and can be changed. Empty = stock UOM.",
    },
    {
        "dt": "Stock Reconciliation Item",
        "fieldname": SR_FACTOR_FIELD,
        "label": "Conversion Factor",
        "fieldtype": "Float",
        "read_only": 1,
        "in_list_view": 1,
        "insert_after": "qty",
        "description": "Multiplier from the selected UOM to the item's stock UOM.",
    },
    {
        "dt": "Stock Reconciliation Item",
        "fieldname": SR_BEFORE_FIELD,
        "label": "Qty Before (as per UOM)",
        "fieldtype": "Float",
        "read_only": 1,
        "in_list_view": 1,
        "insert_after": "qty",
        "description": "Current stock quantity expressed in the selected UOM.",
    },
    {
        "dt": "Stock Reconciliation Item",
        "fieldname": SR_AFTER_FIELD,
        "label": "Qty After (as per UOM)",
        "fieldtype": "Float",
        "in_list_view": 1,
        "insert_after": "qty",
        "description": "Counted quantity in the selected UOM. Drives the native Qty (stock UOM) "
        "via the Conversion Factor.",
    },
    {
        "dt": "Stock Reconciliation Item",
        "fieldname": SR_RATE_FIELD,
        "label": "Valuation Rate (as per UOM)",
        "fieldtype": "Currency",
        "in_list_view": 1,
        "insert_after": "qty",
        "description": "Valuation rate per the selected UOM. Empty = keep the native Valuation "
        "Rate; an explicit 0 is a real revaluation.",
    },
]

# Role gate: gudang boleh, tapi Stock Manager/User & System Manager juga — SR
# dokumen stok umum, bukan milik gudang saja. Dirangkai literal ke JS di bawah.
SR_GATE_ROLES = ["Gudang Barang Jadi", "Stock Manager", "Stock User", "System Manager"]

_SR_ROLES_JS = "[" + ", ".join('"' + role + '"' for role in SR_GATE_ROLES) + "]"

CLIENT_SCRIPT_STOCK_RECONCILIATION = SR_SCRIPT_MARKER + """ — UOM columns on Stock Reconciliation.
// Gudang-only: every handler returns early without one of the gate roles, so
// native users are unaffected. Native Qty / Valuation Rate stay the ledger's
// source of truth; the custom columns only drive them. Serial/batch rows are
// left to the native flow entirely.
// Race-safety: standard doctype JS evaluates before Client Scripts, so the
// native item_code handler (get_stock_balance_for) runs first;
// frappe.after_ajax queues our default-UOM step behind it, hence current_qty
// is already populated when the custom_uom handler resolves the factor.

(function () {
	const SR_GATE_ROLES = """ + _SR_ROLES_JS + """;

	function enabled() {
		return SR_GATE_ROLES.some((role) => frappe.user.has_role(role));
	}

		// use_serial_batch_fields sengaja TIDAK di-skip: form native menyalakan
		// flag itu di row baru walau item tak ber-serial/batch — konversi aman
		// selama serial/bundle kosong.
		function skip_row(row) {
			return !!(row.serial_no || row.serial_and_batch_bundle);
		}

	// Default UOM = the item's Default Inventory UOM (W21). Seeding the field
	// only — the custom_uom handler resolves factor/qty from there.
	function apply_default_uom(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row || !row.item_code || row.custom_uom || skip_row(row)) return;
		frappe.db
			.get_value("Item", row.item_code, "custom_default_inventory_unit_of_measure")
			.then((r) => {
				const target = r.message && r.message.custom_default_inventory_unit_of_measure;
				const live = locals[cdt][cdn];
				// re-guard: refresh may fire several promises in parallel
				if (!target || !live || live.custom_uom || skip_row(live)) return;
				frappe.model.set_value(cdt, cdn, "custom_uom", target);
			});
	}

	function apply_defaults(frm) {
		// "Fetch Items from Warehouse" appends rows via add_child + $.extend
		// without the item_code event — redo the default flow for rows whose
		// custom_uom is still empty (anti-loop guard: only those are processed)
		(frm.doc.items || []).forEach((d) => {
			if (d.item_code && !d.custom_uom && !skip_row(d)) {
				apply_default_uom(frm, d.doctype, d.name);
			}
		});
	}

	// Whitelist client: native get_conversion_factor falls back to 1.0 for UOMs
	// outside the item's table — reject those before any math happens (server
	// hook stays the hard guard). Sumber: frappe.client.get Item (read Item
	// dimiliki role stock) membawa tabel uoms; frappe.db.get_list pada child
	// table istable 403 utk non-Administrator dan promisenya menggantung —
	// JANGAN pakai get_list child di sini.
	const UOM_CACHE = {};
	function allowed_uoms(item_code) {
		if (UOM_CACHE[item_code]) return Promise.resolve(UOM_CACHE[item_code]);
		return Promise.all([
			frappe.db.get_value("Item", item_code, "stock_uom"),
			frappe.xcall("frappe.client.get", { doctype: "Item", name: item_code }),
		])
			.then(([iv, doc]) => {
				const list = [iv.message.stock_uom].concat((doc.uoms || []).map((r) => r.uom));
				UOM_CACHE[item_code] = list;
				return list;
			})
			.catch(() => null);
	}

	function apply_uom(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row || skip_row(row)) return;
		if (!row.custom_uom || !row.item_code) {
			// UOM cleared = back to native-unset state: blank the derived columns
			// and unset native qty/valuation_rate — native treats an empty qty as
			// "keep current stock"; a stale 0 or stale converted value would
			// silently reconcile the bin on save.
			frappe.model.set_value(cdt, cdn, "custom_conversion_factor", "");
			frappe.model.set_value(cdt, cdn, "custom_qty_before", "");
			frappe.model.set_value(cdt, cdn, "custom_qty_after", "");
			frappe.model.set_value(cdt, cdn, "qty", null);
			frappe.model.set_value(cdt, cdn, "valuation_rate", null);
			return;
		}
		allowed_uoms(row.item_code).then((allowed) => {
			const live = locals[cdt][cdn];
			if (!live || live.custom_uom !== row.custom_uom) return; // stale resolve
			if (allowed && allowed.indexOf(live.custom_uom) === -1) {
				frappe.msgprint(
					__(
						"UOM {0} is not valid for Item {1}: use the Stock UOM or add it to the item's UOM Conversion table.",
						[live.custom_uom, live.item_code]
					)
				);
				frappe.model.set_value(cdt, cdn, "custom_uom", "");
				return;
			}
			frappe.xcall("erpnext.stock.get_item_details.get_conversion_factor", {
				item_code: live.item_code,
				uom: live.custom_uom,
			}).then((res) => {
				const factor = flt(res && res.conversion_factor);
				if (!factor) return; // server-side validation rejects it on save
				frappe.model.set_value(cdt, cdn, "custom_conversion_factor", factor).then(() => {
					const cur = locals[cdt][cdn];
					if (!cur) return;
					const before = flt(cur.current_qty) / factor;
					frappe.model
						.set_value(cdt, cdn, "custom_qty_before", before)
						// recount starts from current stock in the chosen UOM; the
						// custom_qty_after handler drives the native qty
						.then(() => frappe.model.set_value(cdt, cdn, "custom_qty_after", before))
						// explicit sync: native qty remains the ledger's source of truth
						.then(() => frappe.model.set_value(cdt, cdn, "qty", flt(cur.current_qty)));
				});
			});
		});
	}

	frappe.ui.form.on("Stock Reconciliation Item", {
		item_code(frm, cdt, cdn) {
			if (!enabled()) return;
			frappe.after_ajax(() => apply_default_uom(frm, cdt, cdn));
		},
		custom_uom(frm, cdt, cdn) {
			if (!enabled()) return;
			apply_uom(frm, cdt, cdn);
		},
		custom_qty_after(frm, cdt, cdn) {
			if (!enabled()) return;
			const row = locals[cdt][cdn];
			if (!row || !row.custom_uom || skip_row(row)) return;
			const factor = flt(row.custom_conversion_factor);
			if (!factor) return;
			// the native qty handler computes amount/quantity_difference
			frappe.model.set_value(cdt, cdn, "qty", flt(row.custom_qty_after) * factor);
		},
		custom_valuation_rate_per_uom(frm, cdt, cdn) {
			if (!enabled()) return;
			const row = locals[cdt][cdn];
			const rate = row && row.custom_valuation_rate_per_uom;
			if (!row || !row.custom_uom || skip_row(row)) return;
			const factor = flt(row.custom_conversion_factor);
			// 0 is a valid rate (real revaluation) — only empty passes through
			if (!factor || rate == null || rate === "") return;
			frappe.model.set_value(cdt, cdn, "valuation_rate", flt(rate) / factor);
		},
		qty(frm, cdt, cdn) {
			if (!enabled()) return;
			const row = locals[cdt][cdn];
			if (!row || !row.custom_uom || skip_row(row)) return;
			const factor = flt(row.custom_conversion_factor);
			if (!factor) return;
			const expected = flt(row.custom_qty_after) * factor;
			// anti ping-pong: our own custom_qty_after handler lands exactly on
			// expected; a mismatch means the change came from outside (barcode
			// scan +1, manual edit on the native qty field) -> resync the column
			if (Math.abs(flt(row.qty) - expected) > 1e-6) {
				frappe.model.set_value(cdt, cdn, "custom_qty_after", flt(row.qty) / factor);
			}
		},
	});

	frappe.ui.form.on("Stock Reconciliation", {
		refresh(frm) {
			if (!enabled()) return;
			apply_defaults(frm);
		},
		items_on_form_rendered(frm) {
			if (!enabled()) return;
			apply_defaults(frm);
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
    {
        "name": "warehouse-app-w23-stock-reconciliation-uom",
        "dt": "Stock Reconciliation",
        "script": CLIENT_SCRIPT_STOCK_RECONCILIATION,
        "marker": SR_SCRIPT_MARKER,
    },
]


def ensure_item_fields():
    results = [_ensure_custom_field(ITEM_FIELD_SPEC), _ensure_custom_field(SE_FIELD_SPEC)]
    frappe.clear_cache(doctype="Item")
    frappe.clear_cache(doctype="Stock Entry Detail")
    if "created" in results or "updated" in results:
        frappe.db.commit()
    return "created" if "created" in results else ("updated" if "updated" in results else "unchanged")


def ensure_sr_fields():
    """W23: kolom UOM di baris Stock Reconciliation (spec di seksi W23)."""
    results = [_ensure_custom_field(spec) for spec in SR_FIELD_SPECS]
    for dt in ("Stock Reconciliation", "Stock Reconciliation Item"):
        frappe.clear_cache(doctype=dt)
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
        marker = spec.get("marker", SCRIPT_MARKER)
        name = frappe.db.get_value(
            "Client Script",
            {"dt": spec["dt"], "script": ("like", "%" + marker + "%")},
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
    for dt in ("Item", "Stock Entry", "Material Request", "Stock Reconciliation"):
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
