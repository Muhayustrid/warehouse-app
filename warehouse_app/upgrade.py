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
    ensure_workspace_sidebar()
    ensure_desktop_icon()
    ensure_single_desk_entry()
    ensure_item_fields()
    ensure_sr_fields()
    ensure_pl_fields()
    retire_client_scripts()
    ensure_client_scripts()
    migrate_legacy_uom_field()


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

# Gate role transaksi gudang — native ERPNext saja (keputusan user 2026-09-29:
# warehouse_app berhenti memakai role custom "Gudang Barang Jadi"; record
# rolenya dibiarkan hidup di site — nasibnya diatur production_app). Ditulis
# literal di JS karena script berjalan di sisi klien.
W21_GATE_ROLES = ["Stock Manager", "Stock User", "System Manager"]
_GATE_ROLES_JS = "[" + ", ".join('"' + role + '"' for role in W21_GATE_ROLES) + "]"

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
// Native stock roles only (Stock Manager / Stock User / System Manager): every
// handler returns early without one of the gate roles.

(function () {
	const W21_ROLES = """ + _GATE_ROLES_JS + """;

	function enabled() {
		return W21_ROLES.some((role) => frappe.user.has_role(role));
	}

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
			if (!enabled()) return;
			frappe.after_ajax(() => apply_inventory_uom(frm, cdt, cdn));
		},
		uom(frm, cdt, cdn) {
			if (!enabled()) return;
			update_rate_per_uom(cdt, cdn);
		},
		conversion_factor(frm, cdt, cdn) {
			if (!enabled()) return;
			update_rate_per_uom(cdt, cdn);
		},
		basic_rate(frm, cdt, cdn) {
			if (!enabled()) return;
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
// Native stock roles only (Stock Manager / Stock User / System Manager): the
// handler returns early without one of the gate roles.

(function () {
	const W21_ROLES = """ + _GATE_ROLES_JS + """;

	function enabled() {
		return W21_ROLES.some((role) => frappe.user.has_role(role));
	}

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
			if (!enabled()) return;
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
SR_DIFF_FIELD = "custom_qty_difference_per_uom"

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
    {
        "dt": "Stock Reconciliation Item",
        "fieldname": SR_DIFF_FIELD,
        "label": "Quantity Difference (as per UOM)",
        "fieldtype": "Float",
        "read_only": 1,
        "in_list_view": 1,
        "insert_after": SR_BEFORE_FIELD,
        "description": "Counted difference (Qty After − Qty Before) in the selected UOM.",
    },
]

# Role gate: native ERPNext saja (keputusan user 2026-09-29 — role custom
# "Gudang Barang Jadi" ditinggalkan; record rolenya tetap hidup di site,
# nasibnya diatur production_app). Dirangkai literal ke JS di bawah.
SR_GATE_ROLES = ["Stock Manager", "Stock User", "System Manager"]

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
		// selama serial/bundle kosong. batch_no (direct field) juga TIDAK
		// di-skip sejak W31: baris batch langsung dikonversi seperti baris
		// biasa; hanya serial_no / serial_and_batch_bundle yang passthrough.
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
			frappe.model.set_value(cdt, cdn, "custom_qty_difference_per_uom", "");
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
			frappe.model.set_value(
				cdt,
				cdn,
				"custom_qty_difference_per_uom",
				flt(flt(row.custom_qty_after) - flt(row.custom_qty_before))
			);
		},
		// native refetches current_qty (mis. ganti warehouse) setelah resync qty —
		// turunkan ulang before dari saldo baru sebelum diff dihitung, kalau tidak
		// diff live = after baru − before lama (campuran salah).
		current_qty(frm, cdt, cdn) {
			if (!enabled()) return;
			const row = locals[cdt][cdn];
			if (!row || !row.custom_uom || skip_row(row)) return;
			const factor = flt(row.custom_conversion_factor);
			if (!factor || row.current_qty == null) return;
			frappe.model
				.set_value(cdt, cdn, "custom_qty_before", flt(row.current_qty) / factor)
				.then(() => {
					const cur = locals[cdt][cdn];
					if (!cur) return; // row re-key saat refresh grid
					frappe.model.set_value(
						cdt,
						cdn,
						"custom_qty_difference_per_uom",
						flt(flt(cur.custom_qty_after) - flt(cur.custom_qty_before))
					);
				});
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

# ---- W26 ----
# "Import Stock Count" pindah dari list view (W25, DIPENSIUNKAN — script-nya
# dihapus oleh retire_client_scripts; markernya dipertahankan khusus untuk
# pensiunan) ke FORM Stock Reconciliation: dialog di dokumen, Warehouse
# difilter company dokumen (multicompany-safe), dan upload — FileUploader
# as_dataurl (v16: TANPA POST upload_file, tak ada dokumen File) → klien POST
# base64 sendiri ke endpoint MENGEMBALIKAN baris grid terhitung penuh
# server-side (fill grid programatik tidak menjalankan handler baris klien).
# Tidak ada dokumen yang dibuat endpoint. Role gate native stock sama dengan
# W21/W23; role lain tak melihat tombol.

SR_LIST_SCRIPT_MARKER = "// warehouse_app W25 stock-count-import"

SR_FORM_SCRIPT_MARKER = "// warehouse_app W26 stock-count-import-form"

CLIENT_SCRIPT_SR_FORM = SR_FORM_SCRIPT_MARKER + """ — Import Stock Count on the Stock Reconciliation FORM.
// Company comes from the document (multicompany-safe): the dialog's Warehouse
// picker is filtered to doc.company and the upload validates every row's
// warehouse against it. Grid fill mirrors the native "Fetch Items from
// Warehouse" pattern (clear_table + add_child + refresh_field); per-row client
// handlers do NOT run for programmatic fills, so the server returns every
// derived column pre-computed.

(function () {
	const W26_ROLES = """ + _SR_ROLES_JS + """;

	function enabled() {
		return W26_ROLES.some((role) => frappe.user.has_role(role));
	}

	const SR_IMPORT = "warehouse_app.warehouse_app.sr_import.";

	function download(frm, d, file_type) {
		const warehouse = d.get_value("warehouse");
		if (!warehouse) {
			frappe.msgprint(__("Please choose a Warehouse first."));
			return;
		}
		open_url_post("/api/method/" + SR_IMPORT + "download_stock_count_template", {
			warehouse: warehouse,
			include_zero_stock: d.get_value("include_zero_stock") ? 1 : 0,
			file_type: file_type,
		});
	}

	function fill_grid(frm, d, res) {
		frm.clear_table("items");
		(res.rows || []).forEach((r) => {
			$.extend(frm.add_child("items"), r);
		});
		frm.refresh_field("items");
		d.hide();
		frappe.show_alert({
			message: __("{0} rows imported. Review and Save.", [res.added]),
			indicator: "green",
		});
	}

	function finish(frm, d, res) {
		if (!res) return;
		const warnings = res.warnings || [];
		if (warnings.length) {
			frappe.msgprint({
				title: __("Import Stock Count"),
				indicator: "orange",
				message: warnings.join("<br>"),
			});
		}
		if (!res.rows || !res.rows.length) {
			frappe.msgprint(res.message || __("Nothing was imported."));
			return;
		}
		const existing = (frm.doc.items || []).filter((r) => !r.__deleted && !r.__removed).length;
		if (existing) {
			frappe.confirm(
				__("Replace the {0} rows already in the table with the imported count?", [existing]),
				() => fill_grid(frm, d, res)
			);
		} else {
			fill_grid(frm, d, res);
		}
	}

	function upload(frm, d) {
		// FileUploader's FormData is hardcoded (no custom fields), so we take the
		// file as a data URL (v16: no upload_file POST happens for as_dataurl)
		// and POST it ourselves with the document context.
		new frappe.ui.FileUploader({
			dialog_title: __("Upload Count File"),
			as_dataurl: true,
			allow_multiple: false,
			allow_web_link: false,
			restrictions: {
				max_file_size: 5 * 1024 * 1024,
				max_number_of_files: 1,
				allowed_file_types: [".csv", ".xlsx"],
			},
			upload_notes: __("Only the Counted Qty column is required."),
			on_success(file) {
				frappe.call({
					method: SR_IMPORT + "upload_stock_count",
					args: {
						filename: file.name,
						data: file.dataurl,
						company: frm.doc.company,
						posting_date: frm.doc.posting_date,
						posting_time: frm.doc.posting_time,
					},
					callback(r) {
						finish(frm, d, r && r.message);
					},
				});
			},
		});
	}

	function open_dialog(frm) {
		if (!frm.doc.company) {
			frappe.msgprint(__("Please set the Company first."));
			return;
		}
		const d = new frappe.ui.Dialog({
			title: __("Import Stock Count"),
			size: "large",
			primary_action_label: __("Close"),
			primary_action: () => d.hide(),
			fields: [
				{
					fieldname: "intro",
					fieldtype: "HTML",
					options:
						'<p class="text-muted" style="margin: -4px 0 4px;">' +
						__(
							"Download the pre-filled template, fill in Counted Qty, then upload the file here."
						) +
						"</p>",
				},
				{
					fieldname: "warehouse",
					label: __("Warehouse"),
					fieldtype: "Link",
					options: "Warehouse",
					reqd: 1,
					get_query: () => ({
						filters: { company: frm.doc.company, is_group: 0, disabled: 0 },
					}),
				},
				{
					fieldname: "include_zero_stock",
					label: __("Include zero-stock items"),
					fieldtype: "Check",
					default: 0,
					description: __("Also list items with zero stock in this warehouse."),
				},
				{ fieldname: "col_dl", fieldtype: "Column Break" },
				{
					fieldname: "dl_xlsx",
					label: __("Download Excel Template"),
					fieldtype: "Button",
					click: () => download(frm, d, "xlsx"),
				},
				{
					fieldname: "dl_csv",
					label: __("Download CSV Template"),
					fieldtype: "Button",
					click: () => download(frm, d, "csv"),
				},
				{
					fieldname: "sec_upload",
					fieldtype: "Section Break",
					label: __("Upload the completed file"),
				},
				{
					fieldname: "upload_hint",
					fieldtype: "HTML",
					options:
						'<ul class="text-muted" style="padding-left: 16px; margin: 0 0 8px;">' +
						"<li>" +
						__("Only Counted Qty (as per UOM) is required. Blank rows are skipped.") +
						"</li>" +
						"<li>" +
						__("Valuation Rate is optional. Leave it blank to keep the system rate.") +
						"</li>" +
						"<li>" +
						__("Count and upload the same day. Don't change the Posting Date afterwards.") +
						"</li>" +
						"</ul>",
				},
				{
					fieldname: "upload_btn",
					label: __("Upload Count File"),
					fieldtype: "Button",
					click: () => upload(frm, d),
				},
			],
		});
		d.show();
	}

	frappe.ui.form.on("Stock Reconciliation", {
		refresh(frm) {
			if (!enabled()) return;
			// drafts and unsaved new docs only (native Fetch button pattern)
			if (frm.doc.docstatus > 0) return;
			frm.add_custom_button(__("Import Stock Count"), () => open_dialog(frm));
		},
	});
})();
"""

# ---- W31 ----
# Pick List dalam UOM inventaris: kolom custom_picked_qty di baris locations
# (picking diucapkan dalam UOM baris; picked_qty native tetap stock UOM karena
# dipakai validate_stock_qty, cap set_item_locations, dan bundle on_submit) +
# patch klien BarcodeScanner / SerialBatchPackageSelector (prototype, simpan
# referensi original + delegasi utk konteks lain) + hint konversi display-only
# di form Batch. Konversi & clamp server-side:
# warehouse_app.inventory_uom.apply_pl_inventory_uom (before_validate).

PL_SCRIPT_MARKER = "// warehouse_app W31 pick-list-inventory-uom"
PL_SE_SCRIPT_MARKER = "// warehouse_app W31 serial-batch-selector-patch"
PL_BATCH_SCRIPT_MARKER = "// warehouse_app W31 batch-conversion-hint"
PL_PICKED_FIELD = "custom_picked_qty"

PL_FIELD_SPEC = {
    "dt": "Pick List Item",
    "fieldname": PL_PICKED_FIELD,
    "label": "Picked Qty (as per UOM)",
    "fieldtype": "Float",
    "in_list_view": 1,
    "insert_after": "picked_qty",
    # tanpa default: 0 = belum dipick (netral native), penanda konversi = uom
    # baris != stock_uom (field native), faktor = conversion_factor native.
    "description": "Picked quantity in this row's UOM. Drives Picked Qty (in Stock UOM) via the "
    "UOM Conversion Factor. Leave empty for rows that are not picked yet.",
}

# Installer patch SerialBatchPackageSelector — sama persis disematkan di script
# Pick List DAN Stock Entry (dialog batch/serial dibuka dari kedua form);
# flag proto.__w31 menjaga install tunggal walau kedua script dimuat bersama.
# Prinsip: dialog bicara dalam UOM BARIS (target qty, qty per batch, input
# scan +1), tapi entries yang ditulis ke bundle TETAP SATUAN STOCK karena
# server memvalidasi total bundle == stock_qty baris
# (serial_and_batch_bundle.validate_quantity).
_SELECTOR_PATCH_JS = """
	// Cache item -> Default Inventory UOM (null = tidak ada). Diprima oleh form
	// script (refresh + item_code); dialog membacanya sinkron.
	const UOM_CACHE = (frappe.w31_uom_cache = frappe.w31_uom_cache || {});

	function prime_uom(item_code) {
		if (!item_code || UOM_CACHE[item_code] !== undefined) return;
		UOM_CACHE[item_code] = null; // penanda in-flight / negatif
		frappe.db.get_value("Item", item_code, "custom_default_inventory_unit_of_measure").then((r) => {
			UOM_CACHE[item_code] = (r.message && r.message.custom_default_inventory_unit_of_measure) || null;
		});
	}

	function patch_selector() {
		const cls = window.erpnext && erpnext.SerialBatchPackageSelector;
		const proto = cls && cls.prototype;
		if (!proto || proto.__w31) return;
		const hooks = ["make", "get_auto_data", "get_batch_qty", "render_data", "create_bundle_entries"];
		if (hooks.some((m) => typeof proto[m] !== "function")) return; // struktur tak dikenal: diam

		// Baris yang dikonversi: dialog dibuka dari form Pick List / Stock Entry
		// saja (lingkup W31; form lain user bergate tetap native), UOM baris beda
		// dari stock UOM, item punya Default Inventory UOM, faktor sehat. Baris
		// serial tetap native (qty-nya adalah hitungan unit stock).
		const factor_for = (item, frm) => {
			const dt = frm && frm.doctype;
			if (dt !== "Pick List" && dt !== "Stock Entry") return 1;
			if (!item || !item.item_code || item.has_serial_no) return 1;
			if (!item.uom || !item.stock_uom || item.uom === item.stock_uom) return 1;
			if (!UOM_CACHE[item.item_code]) return 1;
			const factor = flt(item.conversion_factor);
			return factor > 0 ? factor : 1;
		};

		const orig_make = proto.make;
		proto.make = function () {
			const factor = factor_for(this.item, this.frm);
			if (factor === 1) return orig_make.apply(this, arguments);
			// make() mengambil target qty dari item.stock_qty/transfer_qty/qty:
			// berikan salinan dangkal yang sudah diskalakan agar dialog terbuka
			// dalam UOM baris.
			const real = this.item;
			const scaled = Object.assign({}, real);
			["stock_qty", "transfer_qty", "qty", "rejected_qty"].forEach((f) => {
				if (flt(scaled[f])) scaled[f] = flt(flt(scaled[f]) / factor, 9);
			});
			this.item = scaled;
			try {
				return orig_make.call(this);
			} finally {
				this.item = real; // callback lain memakai row hidup lagi
			}
		};

		const orig_auto = proto.get_auto_data;
		proto.get_auto_data = function () {
			const factor = factor_for(this.item, this.frm);
			const entries = this.dialog && this.dialog.fields_dict && this.dialog.fields_dict.entries;
			if (factor === 1 || !entries) return orig_auto.apply(this, arguments);
			let { qty, based_on } = this.dialog.get_values();
			if (this.item.serial_and_batch_bundle || this.item.rejected_serial_and_batch_bundle) {
				// this.qty = item.qty (UOM transaksi) — dialog hasil make() memuat
				// stock_qty/faktor yang bernilai sama, jadi bandingkan langsung
				if (this.qty && qty === Math.abs(this.qty)) return;
			}
			if (this.item.serial_no || this.item.batch_no) return;
			if (!based_on) based_on = this.based_on;
			let warehouse = this.item.warehouse || this.item.s_warehouse;
			if (this.item?.is_rejected) warehouse = this.item.rejected_warehouse;
			if (!qty) return;
			frappe.call({
				method: "erpnext.stock.doctype.serial_and_batch_bundle.serial_and_batch_bundle.get_auto_data",
				args: {
					item_code: this.item.item_code,
					warehouse: warehouse,
					has_serial_no: this.item.has_serial_no,
					has_batch_no: this.item.has_batch_no,
					qty: flt(flt(qty) * factor, 9), // server fetch dalam satuan stock
					based_on: based_on,
					posting_date: this.frm.doc.posting_date,
					posting_time: this.frm.doc.posting_time,
					scio_detail: this.item.scio_detail,
				},
				callback: (r) => {
					if (!r.message) return;
					entries.df.data = r.message.map((d) =>
						Object.assign({}, d, { qty: flt(flt(d.qty) / factor, 9) }) // tampil di UOM baris
					);
					entries.grid.refresh();
				},
			});
		};

		const orig_batch_qty = proto.get_batch_qty;
		proto.get_batch_qty = function (batch_no, callback) {
			const factor = factor_for(this.item, this.frm);
			if (factor === 1) return orig_batch_qty.apply(this, arguments);
			orig_batch_qty.call(this, batch_no, (qty) => callback(flt(flt(qty) / factor, 9)));
		};

		const orig_render = proto.render_data;
		proto.render_data = function () {
			const factor = factor_for(this.item, this.frm);
			if (factor === 1) return orig_render.apply(this, arguments);
			// HANYA jalur bundle eksisting yang dikonversi: rows ledger kembali
			// dalam satuan stock -> tampilkan dalam UOM baris. set_data sengaja
			// TIDAK dipatch: jalur upload CSV memanggilnya dengan angka yang
			// diketik user (semantik native: satuan stock, divalidasi server
			// sebagaimana adanya) dan tidak boleh ikut terbagi faktor.
			if (!(this.bundle || (this.frm.doc.is_return && this.frm.doc.return_against))) return;
			frappe
				.call({
					method: "erpnext.stock.doctype.serial_and_batch_bundle.serial_and_batch_bundle.get_serial_batch_ledgers",
					args: {
						item_code: this.item.item_code,
						name: this.bundle,
						voucher_no: !this.frm.is_new() ? this.item.parent : "",
						child_row: this.frm.doc.is_return ? this.item : "",
					},
				})
				.then((r) => {
					if (!r.message) return;
					this.set_data(
						r.message.map((d) =>
							Object.assign({}, d, { qty: flt(flt(d.qty) / factor, 9) })
						)
					);
				});
		};

		const orig_create = proto.create_bundle_entries;
		proto.create_bundle_entries = function (entries, warehouse) {
			const factor = factor_for(this.item, this.frm);
			if (factor !== 1 && Array.isArray(entries)) {
				// entries bundle ditulis dalam SATUAN STOCK: server memvalidasi
				// total bundle terhadap stock_qty baris
				entries = entries.map((d) =>
					d.qty == null ? d : Object.assign({}, d, { qty: flt(flt(d.qty) * factor, 9) })
				);
			}
			return orig_create.call(this, entries, warehouse);
		};

		proto.__w31 = true;
	}
"""

# Race-safety (i): standard doctype JS dievaluasi sebelum Client Script, jadi
# handler item_code native (get_item_details -> uom = stock_uom, factor 1)
# selesai lebih dulu; frappe.after_ajax mengantre override di belakangnya.
# Set uom memakai ulang rantai handler native (refetch conversion_factor ->
# stock_qty = qty x faktor). Batas yang diterima: scan pertama pada baris baru
# yang UOM-nya belum terset (+1 satuan stock) — server rule (2) menyelaraskan
# custom_picked_qty saat simpan.
CLIENT_SCRIPT_PICK_LIST = PL_SCRIPT_MARKER + """ — Pick List rows in the item's Default Inventory UOM.
// Native stock roles only (Stock Manager / Stock User / System Manager): every
// handler returns early without one of the gate roles, so native users are
// unaffected. (i) new rows default to the item's Default Inventory UOM (W21
// field); (ii) custom_picked_qty <-> picked_qty stay in lockstep (picked is
// always stock UOM); (iii) erpnext.utils.BarcodeScanner is patched so a scan
// adds one unit of the ROW's UOM and row matching compares stock units; (iv)
// erpnext.SerialBatchPackageSelector speaks the row's UOM while bundle rows
// stay in stock units. Every patch delegates to the original implementation
// outside its branch.

(function () {
	const W31_ROLES = """ + _GATE_ROLES_JS + """;

	function enabled() {
		return W31_ROLES.some((role) => frappe.user.has_role(role));
	}

	const PICKED = \"""" + PL_PICKED_FIELD + """\";

	function converts(row) {
		return !!(row && row.item_code && row.uom && row.stock_uom && row.uom !== row.stock_uom);
	}

	function factor_of(row) {
		return flt(row && row.conversion_factor);
	}
""" + _SELECTOR_PATCH_JS + """
	function apply_inventory_uom(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row || !row.item_code) return;
		prime_uom(row.item_code);
		frappe.db
			.get_value("Item", row.item_code, "custom_default_inventory_unit_of_measure")
			.then((r) => {
				const target = r.message && r.message.custom_default_inventory_unit_of_measure;
				const live = locals[cdt][cdn];
				// sama dengan stock UOM = tak ada yang perlu dikonversi
				if (!target || !live || live.uom === target || target === live.stock_uom) return;
				frappe.xcall("erpnext.stock.get_item_details.get_conversion_factor", {
					item_code: live.item_code,
					uom: target,
				}).then((res) => {
					const factor = flt(res && res.conversion_factor);
					const cur = locals[cdt][cdn];
					if (!factor || !cur || cur.uom === target) return;
					frappe.model.set_value(cdt, cdn, "uom", target);
					frappe.model.set_value(cdt, cdn, "conversion_factor", factor);
				});
			});
	}

	// (ii) lockstep: custom -> picked dikali faktor; picked -> custom dibagi,
	// dengan pita 1e-6 agar tulisan sendiri tidak saling memantul.
	function sync_picked(cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!converts(row)) return;
		const factor = factor_of(row);
		if (!factor) return;
		frappe.model.set_value(
			cdt,
			cdn,
			"picked_qty",
			flt(flt(row[PICKED]) * factor, precision("picked_qty", row))
		);
	}

	function sync_custom(cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!converts(row)) return;
		const factor = factor_of(row);
		if (!factor) return;
		const expected = flt(flt(row[PICKED]) * factor);
		if (Math.abs(flt(row.picked_qty) - expected) <= 1e-6) return; // tulisan sendiri
		frappe.model.set_value(
			cdt,
			cdn,
			PICKED,
			flt(flt(row.picked_qty) / factor, precision(PICKED, row))
		);
	}

	// (iii) BarcodeScanner: scan menambah SATU UNIT UOM BARIS pada baris
	// inventaris (native menambah satu unit stock, mis. satu gram). Level
	// prototype + flag di function; delegasi ke original untuk form lain /
	// user tanpa role / struktur tak dikenal.
	function patch_barcode_scanner() {
		const cls = window.erpnext && erpnext.utils && erpnext.utils.BarcodeScanner;
		const proto = cls && cls.prototype;
		if (!proto) return;
		if (typeof proto.set_item !== "function") return;
		if (typeof proto.get_row_to_modify_on_scan !== "function") return;

		if (!proto.set_item.__w31) {
			const original_set_item = proto.set_item;
			proto.set_item = function (row, item_code, barcode, batch_no, serial_no) {
				if (!(this.frm && this.frm.doctype === "Pick List" && converts(row))) {
					return original_set_item.apply(this, arguments);
				}
				return new Promise((resolve) => {
					const increment = async (value = 1) => {
						const factor = factor_of(row) || 1;
						const custom = flt(row[PICKED]) + flt(value);
						const picked = flt(custom * factor, precision("picked_qty", row));
						const item_data = { item_code: item_code, use_serial_batch_fields: 1.0 };
						frappe.flags.trigger_from_barcode_scanner = true;
						// PICKED duluan agar handler picked_qty melihat pasangan konsisten
						item_data[PICKED] = custom;
						item_data[this.qty_field] = picked;
						await frappe.model.set_value(row.doctype, row.name, item_data);
						return value;
					};
					if (this.prompt_qty) {
						frappe.prompt(__("Please enter quantity for item {0}", [item_code]), ({ value }) => {
							increment(value).then((value) => resolve(value));
						});
					} else if (this.frm.has_items) {
						this.prepare_item_for_scan(row, item_code, barcode, batch_no, serial_no);
					} else {
						increment().then((value) => resolve(value));
					}
				});
			};
			proto.set_item.__w31 = true;
		}

		if (!proto.get_row_to_modify_on_scan.__w31) {
			const original_match = proto.get_row_to_modify_on_scan;
			proto.get_row_to_modify_on_scan = function (item_code, batch_no, uom, barcode, default_warehouse) {
				if (!(this.frm && this.frm.doctype === "Pick List")) {
					return original_match.apply(this, arguments);
				}
				const field = this.frm.fields_dict[this.items_table_name];
				const cur_grid = field && field.grid;
				if (!cur_grid || typeof this.get_warehouse_field !== "function") {
					return original_match.apply(this, arguments);
				}
				const is_batch_no_scan = batch_no && frappe.meta.has_field(cur_grid.doctype, this.batch_no_field);
				const warehouse_field = this.has_last_scanned_warehouse && this.get_warehouse_field();
				const has_warehouse_field =
					warehouse_field && frappe.meta.has_field(cur_grid.doctype, warehouse_field);
				const warehouse = has_warehouse_field
					? this.frm.doc.last_scanned_warehouse || default_warehouse
					: null;
				const matching_row = (row) => {
					const item_match = row.item_code == item_code;
					const batch_match = !row[this.batch_no_field] || row[this.batch_no_field] == batch_no;
					const uom_match = !uom || this.max_qty_field || row[this.uom_field] == uom;
					const has_demand_qty = this.demand_ref_fields.some((fieldname) => row[fieldname]);
					// bug native: membandingkan picked_qty (stock UOM) dengan max
					// field (UOM transaksi). Dua sisi satuan stock di sini.
					const qty_in_limit = !has_demand_qty || flt(row.picked_qty) < flt(row.stock_qty);
					const item_scanned = row.has_item_scanned;
					let warehouse_match = true;
					if (has_warehouse_field && warehouse && row[warehouse_field]) {
						warehouse_match = row[warehouse_field] === warehouse;
					}
					return (
						item_match &&
						uom_match &&
						warehouse_match &&
						!item_scanned &&
						(!is_batch_no_scan || batch_match) &&
						qty_in_limit
					);
				};
				const items_table = this.frm.doc[this.items_table_name] || [];
				return items_table.find(matching_row) || items_table.find((d) => !d.item_code);
			};
			proto.get_row_to_modify_on_scan.__w31 = true;
		}
	}

	frappe.ui.form.on("Pick List Item", {
		item_code(frm, cdt, cdn) {
			if (!enabled()) return;
			frappe.after_ajax(() => apply_inventory_uom(frm, cdt, cdn));
		},
		picked_qty(frm, cdt, cdn) {
			if (!enabled()) return;
			sync_custom(cdt, cdn);
		},
		custom_picked_qty(frm, cdt, cdn) {
			if (!enabled()) return;
			sync_picked(cdt, cdn);
		},
		// ganti uom me-refetch faktor secara native; hitung ulang picked ikut
		// menumpang di sini. custom > 0 disyaratkan agar picked native baris
		// yang belum dipick lewat UOM tidak pernah dinoikan menjadi 0.
		conversion_factor(frm, cdt, cdn) {
			if (!enabled()) return;
			const row = locals[cdt][cdn];
			if (!converts(row) || flt(row[PICKED]) <= 0) return;
			sync_picked(cdt, cdn);
		},
	});

	frappe.ui.form.on("Pick List", {
		refresh(frm) {
			if (!enabled()) return;
			patch_barcode_scanner();
			patch_selector();
			(frm.doc.locations || []).forEach((d) => prime_uom(d.item_code));
		},
	});
})();
"""

CLIENT_SCRIPT_STOCK_ENTRY_SELECTOR = PL_SE_SCRIPT_MARKER + """ — activate the batch dialog UOM patch on Stock Entry.
// The SerialBatchPackageSelector patch is shared with the Pick List W31
// script; this loader only installs it (idempotently) and primes the item UOM
// cache so dialogs opened from Stock Entry rows convert too. The W21 Stock
// Entry script is a separate document and is not touched.

(function () {
	const W31_ROLES = """ + _GATE_ROLES_JS + """;

	function enabled() {
		return W31_ROLES.some((role) => frappe.user.has_role(role));
	}
""" + _SELECTOR_PATCH_JS + """

	frappe.ui.form.on("Stock Entry", {
		refresh(frm) {
			if (!enabled()) return;
			patch_selector();
			(frm.doc.items || []).forEach((d) => prime_uom(d.item_code));
		},
	});

	frappe.ui.form.on("Stock Entry Detail", {
		item_code(frm, cdt, cdn) {
			if (!enabled()) return;
			const row = locals[cdt][cdn];
			if (row) prime_uom(row.item_code);
		},
	});
})();
"""

CLIENT_SCRIPT_BATCH_HINT = PL_BATCH_SCRIPT_MARKER + """ — conversion hint on the Batch form.
// Display-only: when the batch's item has a Default Inventory UOM different
// from its stock UOM, a hint line under the form dashboard approximates the
// batch quantity in that UOM. Native numbers are never changed; if the
// dashboard node is missing the script bails silently.

(function () {
	const W31_ROLES = """ + _GATE_ROLES_JS + """;

	function enabled() {
		return W31_ROLES.some((role) => frappe.user.has_role(role));
	}

	function render_hint(frm, text) {
		// frappe.ui.form.Dashboard v16 hanya punya `parent` + section wrapper
		// (progress_area/links_area dst.) — TIDAK ada properti `wrapper`, jadi
		// anchor ke node dashboard itu sendiri (.form-dashboard); bila struktur
		// tak ketemu, diam.
		const dash = frm.dashboard && frm.dashboard.parent;
		if (!dash || !dash.length) return;
		dash.find(".w31-uom-hint").remove();
		$('<div class="w31-uom-hint text-muted" style="margin: 4px 0 8px 2px; font-size: 12px;"></div>')
			.text(__("approx. {0} (Default Inventory UOM)", [text]))
			.appendTo(dash);
	}

	frappe.ui.form.on("Batch", {
		refresh(frm) {
			if (!enabled() || !frm.doc.item) return;
			frappe.db
				.get_value("Item", frm.doc.item, ["stock_uom", "custom_default_inventory_unit_of_measure"])
				.then((r) => {
					const m = (r && r.message) || {};
					const inv_uom = m.custom_default_inventory_unit_of_measure;
					if (!inv_uom || inv_uom === m.stock_uom) return;
					frappe.xcall("erpnext.stock.get_item_details.get_conversion_factor", {
						item_code: frm.doc.item,
						uom: inv_uom,
					}).then((res) => {
						const factor = flt(res && res.conversion_factor);
						if (!factor) return;
						// get_batch_qty tanpa warehouse mengembalikan baris per warehouse
						return frappe
							.xcall("erpnext.stock.doctype.batch.batch.get_batch_qty", {
								batch_no: frm.doc.name,
							})
							.then((batches) => {
								const total = (batches || []).reduce((t, d) => t + flt(d.qty), 0);
								if (!flt(total)) return;
								render_hint(
									frm,
									flt(flt(total) / factor, 2) + " " + inv_uom
								);
							});
					});
				})
				.catch(() => {});
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
    {
        "name": "warehouse-app-w26-stock-count-import",
        "dt": "Stock Reconciliation",
        "script": CLIENT_SCRIPT_SR_FORM,
        "marker": SR_FORM_SCRIPT_MARKER,
        "view": "Form",
    },
    {
        "name": "warehouse-app-w31-pick-list-uom",
        "dt": "Pick List",
        "script": CLIENT_SCRIPT_PICK_LIST,
        "marker": PL_SCRIPT_MARKER,
    },
    {
        "name": "warehouse-app-w31-stock-entry-selector",
        "dt": "Stock Entry",
        "script": CLIENT_SCRIPT_STOCK_ENTRY_SELECTOR,
        "marker": PL_SE_SCRIPT_MARKER,
    },
    {
        "name": "warehouse-app-w31-batch-hint",
        "dt": "Batch",
        "script": CLIENT_SCRIPT_BATCH_HINT,
        "marker": PL_BATCH_SCRIPT_MARKER,
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


def ensure_pl_fields():
    """W31: kolom Picked Qty (as per UOM) di baris Pick List (spec W31)."""
    results = [_ensure_custom_field(PL_FIELD_SPEC)]
    for dt in ("Pick List", "Pick List Item"):
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


def retire_client_scripts():
    """Pensiunkan Client Script versi lama: docs yang skripsnya masih memuat
    marker yang sudah dihapus dari CLIENT_SCRIPTS (W25 list-view "Import Stock
    Count" diganti W26 form-view). Idempoten — tanpa docs lama = no-op."""
    names = frappe.get_all(
        "Client Script",
        filters={"script": ("like", "%" + SR_LIST_SCRIPT_MARKER + "%")},
        pluck="name",
    )
    retired = 0
    for name in names:
        try:
            frappe.delete_doc(
                "Client Script", name, force=1, ignore_permissions=1, ignore_missing=True
            )
            retired += 1
        except Exception:
            # satu doc macet (mis. hook pihak ketiga) tak boleh menjatuhkan migrate
            frappe.log_error(
                title="warehouse_app.upgrade",
                message=f"Gagal retire Client Script {name!r}.",
            )
    if retired:
        frappe.clear_cache(doctype="Stock Reconciliation")
        frappe.db.commit()
    return f"retired {retired}"


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
            view = spec.get("view", "Form")
            if doc.script == spec["script"] and doc.enabled and doc.view == view:
                results.append("unchanged")
                continue
            doc.script = spec["script"]
            doc.enabled = 1
            doc.view = view
            doc.flags.ignore_permissions = 1
            doc.save()
            results.append("updated")
            continue
        doc = frappe.get_doc(
            {
                "doctype": "Client Script",
                "name": spec["name"],
                "dt": spec["dt"],
                "view": spec.get("view", "Form"),
                "enabled": 1,
                "script": spec["script"],
            }
        )
        doc.flags.ignore_permissions = 1
        doc.insert()
        results.append("created")
    for dt in (
        "Item",
        "Stock Entry",
        "Material Request",
        "Stock Reconciliation",
        "Pick List",
        "Pick List Item",
        "Batch",
    ):
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
