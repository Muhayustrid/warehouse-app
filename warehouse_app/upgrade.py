# Copyright (c) 2026, Muhammad Yusuf Tri Daryanto
# License: MIT

# Pemasangan idempoten non-doctype warehouse_app (after_install & after_migrate).
# Pola mengikuti production_app.upgrade (satu app satu kepemilikan data; R7).
#
# W34 (2026-10-02, keputusan user "hapus semua halaman lama"): UI Desk klasik
# dipensiunkan — Page gudang_request/gudang_settings + cangkang Workspace
# "Gudang" (workspace, Workspace Sidebar, Desktop Icon grup) dihapus; SPA
# /gudang satu-satunya wajah warehouse_app. retire_legacy_desk_ui() adalah
# jaring pengaman idempotennya setelah file JSON dihapus dari repo (sync file
# tidak menghapus record DB milik file yang hilang).

import frappe

SIDEBAR = "Gudang"
APP = "warehouse_app"


def apply():
    retire_legacy_desk_ui()
    ensure_single_desk_entry()
    ensure_item_fields()
    ensure_profile_dry_exceptions()
    ensure_sr_fields()
    ensure_pl_fields()
    ensure_pl_fulfillment_fields()
    ensure_fulfillment_lineage_fields()
    ensure_delivery_note_letterhead_koli()
    ensure_format_print_pick_list()
    ensure_format_print_packing_slip()
    retire_client_scripts()
    ensure_client_scripts()
    migrate_legacy_uom_field()
    backfill_run_short_pick_snapshot()


def retire_legacy_desk_ui():
    """W34: pensiunkan seluruh UI Desk klasik milik app ini. Idempoten —
    tanpa record = no-op. Backend gudang_request.py/gudang_settings.py TIDAK
    disentuh (dipakai SPA + gate w9/w19); Report Serah Terima Gudang tetap
    hidup (report Desk — SPA Monitoring-nya dihapus W43)."""
    retired = []
    for doctype, name in (
        ("Page", "gudang_request"),
        ("Page", "gudang_settings"),
        ("Workspace", "Gudang"),
        ("Workspace Sidebar", "Gudang"),  # child Workspace Sidebar Item ikut terhapus
    ):
        if frappe.db.exists(doctype, name):
            frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            retired.append(f"{doctype}:{name}")
    icon = frappe.db.get_value("Desktop Icon", {"label": SIDEBAR, "app": APP}, "name")
    if icon:
        frappe.delete_doc("Desktop Icon", icon, force=True, ignore_permissions=True)
        retired.append(f"Desktop Icon:{icon}")
    if retired:
        for key in ("bootinfo", "desktop_icons"):
            frappe.cache.delete_key(key)
        frappe.db.commit()
    return "retired " + (", ".join(retired) if retired else "none")


# ------------------------------------------------------- W22 (diperbarui W34) ----
# Satu pintu desk. W22 dulu MENYEMBUNYIKAN ikon App "Warehouse App" (dibuat
# native dari add_to_apps_screen) karena pintunya grup workspace "Gudang" —
# dua ikon menuju tempat sama. Sejak W34 grup workspace dipensiunkan
# (retire_legacy_desk_ui), jadi ikon App itu kini SATU-SATUNYA pintu dari
# Desk home ke SPA /gudang dan wajib TAMPIL. Entri apps screen Frappe Cloud
# (hook add_to_apps_screen) tidak terpengaruh — itu bukan Desktop Icon.
APP_TITLE_ICON = "Warehouse App"


def ensure_single_desk_entry():
    name = frappe.db.exists(
        "Desktop Icon", {"label": APP_TITLE_ICON, "icon_type": "App", "app": APP}
    )
    if not name:
        return "absent"
    if not frappe.db.get_value("Desktop Icon", name, "hidden"):
        return "unchanged"
    frappe.db.set_value("Desktop Icon", name, "hidden", 0)
    # db.set_value tidak lewat on_update — ikuti pola cache-clear ikon standard
    frappe.cache.delete_key("desktop_icons")
    frappe.cache.delete_key("bootinfo")
    frappe.db.commit()
    return "shown"


def on_app_installed(app_name=None):
    """after_app_install: native auto_generate_icons_and_sidebar membuat ikon
    App SETELAH after_install kita (installer.py memanggil hook ini sesudah
    hook frappe, dgn arg nama app), jadi fresh install butuh titik ini agar
    langsung satu pintu tanpa menunggu migrate pertama."""
    ensure_single_desk_entry()


# ---------------------------------------------------------------- W21 ----
# "Default Inventory UOM" per Item + kolom rate per UOM di Stock Entry Detail
# (W32: INPUT yang men-drive basic_rate native; kolom native basic_rate
# disembunyikan dari grid utk role gate) + 3 Client Script (native users tetap
# tak terpengaruh: field kosong = perilaku native, script ber-role gate).

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

ITEM_FULFILLMENT_CATEGORY_SPEC = {
    "dt": "Item",
    "fieldname": "custom_fulfillment_category",
    "label": "Fulfillment Category",
    "fieldtype": "Select",
    "options": "\nDry\nFrozen",
    "insert_after": "item_group",
    "description": "Fulfillment category override. Leave empty to follow Item Group.",
}

SE_FIELD_SPEC = {
    "dt": "Stock Entry Detail",
    "fieldname": SE_RATE_FIELD,
    "label": "Basic Rate (as per UOM)",
    "fieldtype": "Currency",
    # W32: input (bukan display-only) — men-drive basic_rate native ÷ faktor.
    "read_only": 0,
    "in_list_view": 1,
    "insert_after": "basic_rate",
    "allow_on_submit": 1,
    "description": "Rate per this row's UOM. When filled it drives the native Basic Rate "
    "(divided by the conversion factor).",
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
# W32: custom_basic_rate_per_uom is now the INPUT (drives native basic_rate =
# custom / factor, guarded anti ping-pong) and the native Basic Rate column
# (stock UOM) is hidden from the grid for gate roles only — the field stays
# and keeps being set programmatically; non-gate users see it unchanged.
CLIENT_SCRIPT_STOCK_ENTRY = SCRIPT_MARKER + """ — default row UOM + rate per UOM on Stock Entry.
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
		const value = flt(row.basic_rate) * flt(row.conversion_factor || 1);
		if (Math.abs(flt(row.custom_basic_rate_per_uom) - value) > 1e-9) {
			frappe.model.set_value(cdt, cdn, "custom_basic_rate_per_uom", value);
		}
	}

	// W32: the per-UOM rate is the input — drive the native basic_rate.
	// Empty/0 leaves the native rate alone (never silently zeroes it).
	function apply_custom_rate(cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row || !row.item_code) return;
		const factor = flt(row.conversion_factor || 1);
		const custom = flt(row.custom_basic_rate_per_uom);
		if (custom <= 0) return;
		const target = custom / factor;
		if (Math.abs(flt(row.basic_rate) - target) > 1e-9) {
			frappe.model.set_value(cdt, cdn, "basic_rate", target);
		}
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

	// W32: hide the native Basic Rate (stock UOM) column from the grid so the
	// per-UOM column is the single input — display-only, the field itself is
	// never removed and still receives set_value (native flows included).
	// Dua API dipakai bersamaan (belt & braces, beda perilaku antar versi
	// frappe): set_column_disp untuk editable-grid/row editor,
	// set_column_disp_in_list_view untuk kolom list view grid.
	function hide_native_rate_column(frm) {
		const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
		if (!grid) return;
		// sudah tersembunyi = jangan ulang: set_column_disp_in_list_view
		// membongkar semua .grid-row — dipanggil dari items_on_form_rendered
		// ia ikut menghapus baris yang sedang dibuka (layar gelap tanpa form)
		if (grid.column_disp_overrides && grid.column_disp_overrides.basic_rate) return;
		grid.set_column_disp("basic_rate", false);
		grid.set_column_disp_in_list_view("basic_rate", false);
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
		custom_basic_rate_per_uom(frm, cdt, cdn) {
			if (!enabled()) return;
			apply_custom_rate(cdt, cdn);
		},
	});

	frappe.ui.form.on("Stock Entry", {
		refresh(frm) {
			if (!enabled()) return;
			hide_native_rate_column(frm);
		},
		items_on_form_rendered(frm) {
			if (!enabled()) return;
			hide_native_rate_column(frm);
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
# kosong = native murni; client script di-gate role (SR_GATE_ROLES). W32:
# kolom native Quantity & Valuation Rate disembunyikan dari grid utk role
# gate — input pemilik user = kolom per-UOM.

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
			frappe.model.set_value(cdt, cdn, "custom_valuation_rate_per_uom", "");
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
						.then(() => frappe.model.set_value(cdt, cdn, "qty", flt(cur.current_qty)))
						.then(() => {
							const r = locals[cdt][cdn];
							if (!r) return;
							const has_rate =
								r.custom_valuation_rate_per_uom != null &&
								r.custom_valuation_rate_per_uom !== "";
							if (!has_rate && flt(r.current_valuation_rate)) {
								// backfill: rate cell empty & system rate exists; fetch rows arrive pre-filled
								frappe.model.set_value(
									cdt,
									cdn,
									"custom_valuation_rate_per_uom",
									flt(r.current_valuation_rate) * factor
								);
							} else if (has_rate) {
								// pending-rate drive: rate typed before factor arrived; preserves explicit 0
								frappe.model.set_value(
									cdt,
									cdn,
									"valuation_rate",
									flt(r.custom_valuation_rate_per_uom) / factor
								);
							}
						});
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

	// W32: hide the native Quantity & Valuation Rate columns (stock UOM) from
	// the grid so counting happens in the per-UOM columns (Qty After /
	// Valuation Rate as per UOM) — display-only; both fields stay, keep being
	// driven by the custom handlers + server hook, and remain visible for
	// non-gate users. Dua API per-fieldname (lihat catatan di script SE).
	function hide_native_qty_columns(frm) {
		const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
		if (!grid) return;
		// idempoten — lihat hide_native_rate_column di script SE (form baris
		// yang terbuka ikut terhapus bila list view dibongkar ulang)
		if (grid.column_disp_overrides && grid.column_disp_overrides.qty) return;
		for (const field of ["qty", "valuation_rate"]) {
			grid.set_column_disp(field, false);
			grid.set_column_disp_in_list_view(field, false);
		}
	}

	frappe.ui.form.on("Stock Reconciliation", {
		refresh(frm) {
			if (!enabled()) return;
			apply_defaults(frm);
			hide_native_qty_columns(frm);
		},
		items_on_form_rendered(frm) {
			if (!enabled()) return;
			apply_defaults(frm);
			hide_native_qty_columns(frm);
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

PL_RUN_FIELD_SPEC = {
    "dt": "Pick List",
    "fieldname": "custom_fulfillment_run",
    "label": "Fulfillment Run",
    "fieldtype": "Link",
    "options": "Warehouse Fulfillment Run",
    "insert_after": "purpose",
}

PL_GROUP_FIELD_SPEC = {
    "dt": "Pick List",
    "fieldname": "custom_fulfillment_group",
    "label": "Fulfillment Group",
    "fieldtype": "Select",
    "options": "Dry\nFrozen",
    "insert_after": "custom_fulfillment_run",
}

# F3/F4: reverse audit links from the native delivery documents to the Run.
DN_RUN_FIELD_SPEC = {
    "dt": "Delivery Note",
    "fieldname": "custom_fulfillment_run",
    "fieldtype": "Link",
    "label": "Fulfillment Run",
    "options": "Warehouse Fulfillment Run",
    "read_only": 1,
    "insert_after": "customer",
}

DN_DRY_PACKAGES_SPEC = {
    "dt": "Delivery Note",
    "fieldname": "custom_dry_packages",
    "fieldtype": "Int",
    "label": "Dry Packages",
    "read_only": 1,
    "default": 0,
    "insert_after": "custom_fulfillment_run",
}

DN_FROZEN_PACKAGES_SPEC = {
    "dt": "Delivery Note",
    "fieldname": "custom_frozen_packages",
    "fieldtype": "Int",
    "label": "Frozen Packages",
    "read_only": 1,
    "default": 0,
    "insert_after": "custom_dry_packages",
}

DN_TOTAL_PACKAGES_SPEC = {
    "dt": "Delivery Note",
    "fieldname": "custom_total_packages",
    "fieldtype": "Int",
    "label": "Total Packages",
    "read_only": 1,
    "default": 0,
    "insert_after": "custom_frozen_packages",
}

PS_RUN_FIELD_SPEC = {
    "dt": "Packing Slip",
    "fieldname": "custom_fulfillment_run",
    "fieldtype": "Link",
    "label": "Fulfillment Run",
    "options": "Warehouse Fulfillment Run",
    "read_only": 1,
    "insert_after": "delivery_note",
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
    results = [
        _ensure_custom_field(ITEM_FIELD_SPEC),
        _ensure_custom_field(SE_FIELD_SPEC),
        _ensure_custom_field(ITEM_FULFILLMENT_CATEGORY_SPEC),
    ]
    frappe.clear_cache(doctype="Item")
    frappe.clear_cache(doctype="Stock Entry Detail")
    if "created" in results or "updated" in results:
        frappe.db.commit()
    return "created" if "created" in results else ("updated" if "updated" in results else "unchanged")


def ensure_profile_dry_exceptions():
    if frappe.db.exists("DocType", "Warehouse Fulfillment Profile"):
        frappe.reload_doc("warehouse_app", "doctype", "warehouse_fulfillment_profile")
        changed = False
        if not frappe.db.has_column("Warehouse Fulfillment Profile", "dry_item_exceptions"):
            frappe.db.sql("ALTER TABLE `tabWarehouse Fulfillment Profile` ADD COLUMN `dry_item_exceptions` TEXT")
            changed = True
        if not frappe.db.has_column("Warehouse Fulfillment Profile", "enable_packing_slip"):
            frappe.db.sql("ALTER TABLE `tabWarehouse Fulfillment Profile` ADD COLUMN `enable_packing_slip` INT(1) NOT NULL DEFAULT 1")
            changed = True
        frappe.clear_cache(doctype="Warehouse Fulfillment Profile")


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


def ensure_pl_fulfillment_fields():
    """F2: optional lineage fields on native Pick List (never required)."""
    results = [
        _ensure_custom_field(PL_RUN_FIELD_SPEC),
        _ensure_custom_field(PL_GROUP_FIELD_SPEC),
    ]
    frappe.clear_cache(doctype="Pick List")
    if "created" in results or "updated" in results:
        frappe.db.commit()
    if "created" in results:
        return "created"
    if "updated" in results:
        return "updated"
    return "unchanged"


def ensure_fulfillment_lineage_fields():
    """F3/F4: reverse lineage from Delivery Note / Packing Slip to the Run, and package count fields."""
    results = [
        _ensure_custom_field(DN_RUN_FIELD_SPEC),
        _ensure_custom_field(DN_DRY_PACKAGES_SPEC),
        _ensure_custom_field(DN_FROZEN_PACKAGES_SPEC),
        _ensure_custom_field(DN_TOTAL_PACKAGES_SPEC),
        _ensure_custom_field(PS_RUN_FIELD_SPEC),
    ]
    for dt in ("Delivery Note", "Packing Slip"):
        frappe.clear_cache(doctype=dt)
    if "created" in results or "updated" in results:
        frappe.db.commit()
    if "created" in results:
        return "created"
    if "updated" in results:
        return "updated"
    return "unchanged"


def ensure_delivery_note_letterhead_koli():
    """Ensure Company Letterhead - Grey includes the Dry / Frozen Koli box for Delivery Note
    and prominent DRY / FROZEN badge for Pick List."""
    if not frappe.db.exists("Letter Head", "Company Letterhead - Grey"):
        return "skipped"

    doc = frappe.get_doc("Letter Head", "Company Letterhead - Grey")
    canonical_content = """<style>
    /* Header Global Ropi — dipakai sebagai Letter Head default site (docs/11).
       Prefix jh- agar tidak bentrok dengan CSS body format. */
    .jh-header {
        font-family: Arial, Helvetica, sans-serif;
        color: #1a1a1a;
        background: #ffffff;
        padding: 0 0 12px 0;
        margin-bottom: 12px;
        line-height: 1.4;
    }
    .jh-header table {
        width: 100%;
        border-collapse: collapse;
    }
    .jh-header td {
        vertical-align: top;
        padding: 0;
    }
    .jh-header td.jh-logo-cell {
        width: 250px;
    }
    .jh-header td.jh-info-cell {
        text-align: right;
    }

    /* Kiri: logo + info perusahaan (sisi atas logo = sisi atas judul) */
    .jh-logo-box {
        width: 120px;
        height: auto;
        border: none;
        text-align: left;
        margin: 0 0 14px 0;
        padding: 0;
        line-height: 0;
    }
    .jh-logo-box img {
        display: block;
        max-width: 100%;
        max-height: 80px;
        object-fit: contain;
    }
    .jh-company {
        text-align: left;
        line-height: 1.6;
    }
    .jh-company .jh-company-name {
        font-weight: bold;
        font-size: 15px;
        margin-bottom: 4px;
    }
    .jh-company div {
        font-size: 11.5px;
        color: #333;
    }

    /* Khusus Pick List: badge penanda DRY / FROZEN di atas judul */
    .jh-group-badge-wrap {
        text-align: right;
        margin-bottom: 4px;
    }
    .jh-group-badge {
        display: inline-block;
        font-size: 13.5px;
        font-weight: 800;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        padding: 3.5px 14px;
        border-radius: 4px;
        border: 1.5px solid #111111;
        background: #f8fafc;
        color: #111111;
        -webkit-print-color-adjust: exact !important;
        print-color-adjust: exact !important;
    }
    .jh-group-badge.badge-frozen {
        background: #0284c7;
        color: #ffffff;
        border-color: #0369a1;
    }
    .jh-group-badge.badge-dry {
        background: #334155;
        color: #ffffff;
        border-color: #1e293b;
    }

    /* Kanan: judul + meta */
    .jh-title {
        font-size: 24px;
        font-weight: bold;
        text-align: right;
        margin: 0 0 14px 0;
        padding: 0;
        line-height: 1;
    }
    .jh-meta {
        text-align: right;
    }
    .jh-meta .jh-row {
        margin-bottom: 7px;
        white-space: nowrap;
    }
    .jh-meta .jh-label {
        display: inline-block;
        width: 90px;
        color: #666;
        font-size: 11.5px;
        text-align: right;
        margin-right: 10px;
        vertical-align: middle;
        border: none;
        background: none;
        padding: 0;
        border-radius: 0;
    }
    .jh-meta .jh-val {
        display: inline-block;
        font-weight: 600;
        font-size: 11.5px;
        text-align: left;
        min-width: 130px;
        vertical-align: middle;
        border: none;
        background: none;
        padding: 0;
        border-radius: 0;
    }

    /* Khusus Delivery Note: isian jumlah koli, Frozen di kiri dan Dry di kanan dalam satu kotak */
    .jh-koli {
        display: block;
        width: 240px;
        margin: 12px 16px 0 auto;
        padding: 9px 12px;
        border: 1.5px solid #1a1a1a;
    }
    .jh-koli table {
        width: 100%;
        border-collapse: collapse;
    }
    .jh-koli td {
        width: 50%;
        font-size: 13.5px;
        font-weight: 600;
        white-space: nowrap;
        vertical-align: bottom;
    }
    .jh-koli td.jh-koli-left {
        text-align: left;
    }
    .jh-koli td.jh-koli-right {
        text-align: right;
    }
    .jh-koli .jh-line {
        display: inline-block;
        width: 36px;
        border-bottom: 1px solid #1a1a1a;
        margin: 0 0 0 6px;
    }
</style>

{# Header global: logo + info company + judul + meta kondisional per DocType.
   Context render = {"doc": doc.as_dict()} — pakai doc.get(...), jangan
   doc.items (bentrok dengan method dict). #}
{% set _company = doc.get("company") %}
{% set _cd = frappe.db.get_value("Company", _company, ["company_logo", "phone_no", "email", "website"], as_dict=True) if _company else None %}
{% set _items = doc.get("items") or [] %}
{% set _doctype = doc.get("doctype") %}
{% set _status = "Draft" if doc.get("docstatus") == 0 else doc.get("status") %}

{% if _doctype == "Purchase Order" %}
    {% set _title = "Purchase Order" %}
    {% set _rows = [
        ("Status", _status),
        ("PO No.", doc.get("name")),
        ("PO Date", frappe.utils.formatdate(doc.get("transaction_date"))),
        ("Required By", frappe.utils.formatdate(doc.get("schedule_date"))),
        ("Supplier Quotation", doc.get("supplier_quotation")),
        ("Payment Terms", doc.get("payment_terms_template")),
    ] %}
{% elif _doctype == "Purchase Receipt" %}
    {% set _po_refs = _items | map(attribute='purchase_order') | select | unique | list %}
    {% set _title = "Purchase Receipt" %}
    {% set _rows = [
        ("Status", _status),
        ("PR No.", doc.get("name")),
        ("Posting Date", frappe.utils.formatdate(doc.get("posting_date"))),
        ("Delivery Note", doc.get("supplier_delivery_note")),
        ("Against PO", (_po_refs | join(", ")) if _po_refs else "-"),
        ("Payment Terms", doc.get("payment_terms_template")),
    ] %}
{% elif _doctype == "Purchase Invoice" %}
    {% set _po_refs = _items | map(attribute='purchase_order') | select | unique | list %}
    {% set _pr_refs = _items | map(attribute='purchase_receipt') | select | unique | list %}
    {% set _title = "Purchase Invoice" %}
    {% set _rows = [
        ("Status", _status),
        ("Invoice No.", doc.get("name")),
        ("Posting Date", frappe.utils.formatdate(doc.get("posting_date"))),
        ("Due Date", frappe.utils.formatdate(doc.get("due_date"))),
        ("Supplier Inv. No.", doc.get("bill_no")),
        ("Against PO", (_po_refs | join(", ")) if _po_refs else "-"),
        ("Against PR", (_pr_refs | join(", ")) if _pr_refs else "-"),
        ("Payment Terms", doc.get("payment_terms_template")),
    ] %}
{% elif _doctype == "Sales Order" %}
    {% set _title = "Sales Order" %}
    {% set _rows = [
        ("Status", _status),
        ("SO No.", doc.get("name")),
        ("SO Date", frappe.utils.formatdate(doc.get("transaction_date"))),
        ("Delivery Date", frappe.utils.formatdate(doc.get("delivery_date"))),
        ("Customer PO No.", doc.get("po_no")),
        ("Payment Terms", doc.get("payment_terms_template")),
    ] %}
{% elif _doctype == "Delivery Note" %}
    {% set _so_refs = _items | map(attribute='against_sales_order') | select | unique | list %}
    {% set _title = "Delivery Note" %}
    {% set _rows = [
        ("Status", _status),
        ("DN No.", doc.get("name")),
        ("Posting Date", frappe.utils.formatdate(doc.get("posting_date"))),
        ("Customer PO No.", doc.get("po_no")),
        ("Against SO", (_so_refs | join(", ")) if _so_refs else "-"),
        ("Payment Terms", doc.get("payment_terms_template")),
    ] %}
{% elif _doctype == "Pick List" %}
    {% set _so_refs = [] %}
    {% for _loc in (doc.get("locations") or []) %}
        {% if _loc.sales_order and _loc.sales_order not in _so_refs %}
            {% set _ = _so_refs.append(_loc.sales_order) %}
        {% endif %}
    {% endfor %}
    {% set _group_name = (doc.get("custom_fulfillment_group") or "").upper() %}
    {% if not _group_name and doc.get("custom_fulfillment_run") %}
        {% set _run_doc = frappe.db.get_value("Warehouse Fulfillment Run", doc.get("custom_fulfillment_run"), ["dry_pick_list", "frozen_pick_list"], as_dict=True) %}
        {% if _run_doc %}
            {% if _run_doc.dry_pick_list == doc.get("name") %}
                {% set _group_name = "DRY" %}
            {% elif _run_doc.frozen_pick_list == doc.get("name") %}
                {% set _group_name = "FROZEN" %}
            {% endif %}
        {% endif %}
    {% endif %}
    {% set _title = "PICKING LIST" %}
    {% set _rows = [
        ("Status", _status),
        ("Pick List No.", doc.get("name")),
        ("Date", frappe.utils.formatdate(doc.get("creation"))),
        ("Purpose", doc.get("purpose") or "Delivery"),
        ("Against SO", (_so_refs | join(", ")) if _so_refs else "-"),
    ] %}
{% elif _doctype == "Material Request" %}
    {% set _title = "Material Request" %}
    {% set _rows = [
        ("Status", _status),
        ("MR No.", doc.get("name")),
        ("Transaction Date", frappe.utils.formatdate(doc.get("transaction_date"))),
        ("Required By", frappe.utils.formatdate(doc.get("schedule_date"))),
        ("Purpose", doc.get("material_request_type")),
    ] %}
{% elif _doctype == "Stock Entry" %}
    {% set _status = "Draft" if doc.get("docstatus") == 0 else ("Submitted" if doc.get("docstatus") == 1 else "Cancelled") %}
    {% set _title = "Stock Entry" %}
    {% set _rows = [
        ("Status", _status),
        ("STE No.", doc.get("name")),
        ("Posting Date", frappe.utils.formatdate(doc.get("posting_date"))),
        ("Purpose", doc.get("purpose")),
    ] %}
{% else %}
    {% set _title = _doctype or "" %}
    {% set _rows = [
        ("No.", doc.get("name")),
        ("Date", frappe.utils.formatdate(doc.get("posting_date") or doc.get("creation"))),
    ] %}
{% endif %}

<div class="jh-header">
    <table>
        <tr>
            <td class="jh-logo-cell">
                {% if _cd and _cd.company_logo %}
                <div class="jh-logo-box"><img src="{{ _cd.company_logo }}" alt="Company Logo"></div>
                {% endif %}
                {% if _company %}
                <div class="jh-company">
                    <div class="jh-company-name">{{ _company }}</div>
                    {% if _cd and _cd.phone_no %}<div>Phone: {{ _cd.phone_no }}</div>{% endif %}
                    {% if _cd and _cd.email %}<div>Email: {{ _cd.email }}</div>{% endif %}
                    {% if _cd and _cd.website %}<div>WEB: {{ _cd.website }}</div>{% endif %}
                </div>
                {% endif %}
            </td>
            <td class="jh-info-cell">
                {% if _doctype == "Pick List" and _group_name %}
                <div class="jh-group-badge-wrap">
                    <span class="jh-group-badge {% if 'FROZEN' in _group_name %}badge-frozen{% else %}badge-dry{% endif %}">
                        {{ _group_name }}
                    </span>
                </div>
                {% endif %}
                <div class="jh-title">{{ _title }}</div>
                <div class="jh-meta">
                    {% for _label, _value in _rows %}{% if _value %}
                    <div class="jh-row"><span class="jh-label">{{ _label }}</span><span class="jh-val">{{ _value }}</span></div>
                    {% endif %}{% endfor %}
                </div>
                {% if _doctype == "Delivery Note" %}
                <div class="jh-koli">
                    <table>
                        <tr>
                            <td class="jh-koli-left">Dry :<span class="jh-line"></span></td>
                            <td class="jh-koli-right">Frozen :<span class="jh-line"></span></td>
                        </tr>
                    </table>
                </div>
                {% endif %}
            </td>
        </tr>
    </table>
</div>"""

    if (doc.content or "").strip() != canonical_content.strip():
        doc.content = canonical_content
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return "updated"

    return "unchanged"


def ensure_format_print_pick_list():
    """Ensure standard Pick List print format matches the clean corporate layout
    with logo, phone, customer details, clean table with PICKER, PACKER, CHECKER,
    summary for Time & Total Koli, and 3-column signature block."""
    template_html = """<div class="pl-print-format">
<style>
    @page {
        size: A4 portrait;
        margin: 10mm;
    }

    .pl-print-format {
        font-family: Arial, Helvetica, sans-serif;
        color: #1a1a1a;
        font-size: 12px;
        background: #ffffff;
        padding: 0;
        line-height: 1.4;
    }
    .pl-print-format table {
        width: 100%;
        border-collapse: collapse;
    }

    /* HEADER + TITLE + META */
    .pl-header {
        padding-bottom: 12px;
        margin-bottom: 12px;
    }
    .pl-header table {
        width: 100%;
    }
    .pl-header td {
        vertical-align: top;
    }
    .pl-header td.logo-cell {
        width: 200px;
    }
    .pl-header td.info-cell {
        text-align: right;
    }
    .pl-logo-box {
        width: 90px;
        height: 70px;
        border: none;
        text-align: center;
        font-size: 10px;
        color: #999;
        line-height: 70px;
        margin-bottom: 10px;
    }
    .pl-logo-box img {
        max-width: 85px !important;
        max-height: 65px !important;
        width: auto !important;
        height: auto !important;
        object-fit: contain !important;
        vertical-align: middle;
        display: block !important;
    }
    .company-info {
        text-align: left;
        line-height: 1.5;
    }
    .company-info .company-name {
        font-weight: bold;
        font-size: 15px;
        margin-bottom: 2px;
    }
    .company-info div {
        font-size: 11.5px;
        color: #333;
    }
    .pl-group-badge-wrap {
        text-align: right;
        margin-bottom: 4px;
    }
    .pl-group-badge {
        display: inline-block;
        font-size: 13.5px;
        font-weight: 800;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        padding: 3.5px 14px;
        border-radius: 4px;
        border: 1.5px solid #111111;
        background: #f8fafc;
        color: #111111;
        -webkit-print-color-adjust: exact !important;
        print-color-adjust: exact !important;
    }
    .pl-group-badge.badge-frozen {
        background: #0284c7;
        color: #ffffff;
        border-color: #0369a1;
    }
    .pl-group-badge.badge-dry {
        background: #334155;
        color: #ffffff;
        border-color: #1e293b;
    }
    .pl-page-subhead {
        border-bottom: 1.5px solid #1a1a1a;
        margin-bottom: 12px;
        padding-bottom: 4px;
    }
    .pl-page-subhead table {
        width: 100%;
        border-collapse: collapse;
    }
    .pl-group-badge-sub {
        display: inline-block;
        font-size: 11px;
        font-weight: 800;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        padding: 1.5px 8px;
        border-radius: 3px;
        border: 1px solid #111111;
        margin-left: 6px;
        vertical-align: middle;
        -webkit-print-color-adjust: exact !important;
        print-color-adjust: exact !important;
    }
    .pl-group-badge-sub.badge-frozen {
        background: #0284c7;
        color: #ffffff;
        border-color: #0369a1;
    }
    .pl-group-badge-sub.badge-dry {
        background: #334155;
        color: #ffffff;
        border-color: #1e293b;
    }
    .pl-title {
        font-size: 24px;
        font-weight: bold;
        text-align: right;
        margin-top: 0;
        margin-bottom: 10px;
        line-height: 1.2;
    }
    .pl-meta {
        text-align: right;
    }
    .pl-meta .meta-row {
        margin-bottom: 4px;
        white-space: nowrap;
    }
    .pl-meta .pl-label {
        display: inline-block;
        width: 100px;
        color: #666;
        font-size: 11.5px;
        text-align: right;
        margin-right: 10px;
        vertical-align: middle;
    }
    .pl-meta .pl-val {
        display: inline-block;
        font-weight: 600;
        font-size: 11.5px;
        text-align: left;
        min-width: 140px;
        vertical-align: middle;
    }

    /* CUSTOMER & REF INFO SECTION */
    .pl-parties {
        border-top: 1px solid #1a1a1a;
        padding: 10px 0;
        margin-bottom: 12px;
    }
    .pl-parties table td {
        width: 50%;
        vertical-align: top;
        padding-right: 24px;
    }
    .pl-parties .section-title {
        font-weight: bold;
        font-size: 11px;
        letter-spacing: 0.03em;
        text-transform: uppercase;
        color: #555;
        margin-bottom: 4px;
    }
    .pl-parties .party-name {
        font-weight: bold;
        font-size: 13px;
        margin-bottom: 2px;
    }
    .pl-parties .party-line {
        font-size: 12px;
        color: #333;
    }

    /* ITEMS TABLE */
    .pl-items table {
        border-top: 1px solid #1a1a1a;
        border-bottom: 1px solid #1a1a1a;
        table-layout: fixed;
    }
    .pl-items th {
        text-align: left;
        padding: 6px 5px;
        border-bottom: 1px solid #1a1a1a;
        font-size: 10.5px;
        letter-spacing: 0.03em;
        text-transform: uppercase;
        color: #444;
    }
    .pl-items td {
        padding: 7px 5px;
        vertical-align: middle;
        font-size: 12px;
        border-bottom: 1px solid #eee;
    }
    .pl-items tr:last-child td {
        border-bottom: none;
    }
    .pl-items th.text-right, .pl-items td.text-right {
        text-align: right;
        white-space: nowrap;
    }
    .pl-items th.text-center, .pl-items td.text-center {
        text-align: center;
    }
    .item-code {
        font-weight: normal;
    }
    .item-desc {
        color: #666;
        font-weight: 400;
    }
    .batch-box {
        display: inline-block;
        border: 1px solid #ccc;
        padding: 1px 4px;
        font-size: 10px;
        margin-top: 3px;
        color: #555;
    }

    /* FOOTER (Time / Total Koli) */
    .pl-summary-wrap {
        margin-top: 10px;
    }
    .pl-summary-left {
        font-size: 11.5px;
        color: #555;
        padding-top: 4px;
        font-weight: bold;
    }

    /* SIGNATURES */
    .pl-signatures {
        margin-top: 45px;
    }
    .pl-signatures table td {
        width: 33.33%;
        text-align: center;
        padding: 0 10px;
        vertical-align: top;
    }
    .pl-signatures .sig-role {
        font-size: 12px;
        color: #555;
        margin-bottom: 70px;
    }
    .pl-signatures .sig-name {
        font-size: 11.5px;
        color: #444;
    }

    .pl-page {
        page-break-after: always;
        break-after: page;
    }
    .pl-page:last-child {
        page-break-after: auto;
        break-after: auto;
    }
    .manual-line {
        display: inline-block;
        min-width: 170px;
        border-bottom: 1px dotted #777;
        height: 13px;
        vertical-align: top;
    }
    .manual-line.short {
        min-width: 90px;
    }
    .packing-footer-table td {
        vertical-align: top;
    }

    @media print {
        .pl-page {
            page-break-after: always;
            break-after: page;
        }
        .pl-page:last-child {
            page-break-after: auto;
            break-after: auto;
        }
    }
</style>

{# Read company logo and contact safely #}
{% set company_doc = frappe.get_doc("Company", doc.company) if doc.company else None %}
{% set location_rows = doc.locations or [] %}
{% set group_name = (doc.custom_fulfillment_group or '').upper() %}
{% if not group_name and doc.custom_fulfillment_run %}
    {% set run_doc = frappe.get_doc("Warehouse Fulfillment Run", doc.custom_fulfillment_run) if frappe.db.exists("Warehouse Fulfillment Run", doc.custom_fulfillment_run) else None %}
    {% if run_doc %}
        {% if run_doc.dry_pick_list == doc.name %}
            {% set group_name = "DRY" %}
        {% elif run_doc.frozen_pick_list == doc.name %}
            {% set group_name = "FROZEN" %}
        {% endif %}
    {% endif %}
{% endif %}

{# Referensi Sales Order hanya dibaca dari child table bila memang tersedia. #}
{% set sales_order_refs = [] %}
{% for row in location_rows %}
    {% if row.sales_order and row.sales_order not in sales_order_refs %}
        {% set _ = sales_order_refs.append(row.sales_order) %}
    {% endif %}
{% endfor %}

{% if sales_order_refs %}
    {% set reference_label = "Sales Order" %}
    {% set reference_value = sales_order_refs | join(", ") %}
{% elif doc.work_order %}
    {% set reference_label = "Work Order" %}
    {% set reference_value = doc.work_order %}
{% elif doc.material_request %}
    {% set reference_label = "Material Request" %}
    {% set reference_value = doc.material_request %}
{% else %}
    {% set reference_label = "Reference" %}
    {% set reference_value = "-" %}
{% endif %}

{% set displayed_customer = doc.customer_name or doc.customer or "Internal / N/A" %}
{% set displayed_status = "Draft" if doc.docstatus == 0 else (doc.status or "-") %}
{% set rows_per_page = 24 %}
{% set item_count = location_rows | length %}
{% set total_pages = (((item_count - 1) // rows_per_page) + 1) if item_count > 0 else 1 %}
{% set page_starts = range(0, item_count, rows_per_page) if item_count > 0 else [0] %}

{% for start_index in page_starts %}
{% set page_rows = location_rows[start_index:start_index + rows_per_page] %}

<div class="pl-page">
    {% if loop.first %}
    <div class="pl-header">
        <table>
            <tr>
                <td class="logo-cell">
                    {% if company_doc and company_doc.company_logo and company_doc.company_logo.strip() %}
                    <div class="pl-logo-box">
                        <img src="{{ company_doc.company_logo }}">
                    </div>
                    {% endif %}
                    <div class="company-info">
                        <div class="company-name">{{ doc.company or (company_doc.name if company_doc else "PT. JUARA ROTI INDONESIA") }}</div>
                        {% if company_doc and company_doc.phone_no %}
                            <div>Phone: {{ company_doc.phone_no }}</div>
                        {% else %}
                            <div>Phone: 08114232789</div>
                        {% endif %}
                        {% if company_doc and company_doc.email %}
                            <div>Email: {{ company_doc.email }}</div>
                        {% endif %}
                        {% if company_doc and company_doc.website %}
                            <div>WEB: {{ company_doc.website }}</div>
                        {% endif %}
                    </div>
                </td>

                <td class="info-cell">
                    {% if group_name %}
                    <div class="pl-group-badge-wrap">
                        <span class="pl-group-badge {% if 'FROZEN' in group_name %}badge-frozen{% else %}badge-dry{% endif %}">
                            {{ group_name }}
                        </span>
                    </div>
                    {% endif %}
                    <div class="pl-title">PICKING LIST</div>

                    <div class="pl-meta">
                        <div class="meta-row">
                            <span class="pl-label">Status</span>
                            <span class="pl-val">{{ displayed_status }}</span>
                        </div>
                        <div class="meta-row">
                            <span class="pl-label">Pick List No.</span>
                            <span class="pl-val">{{ doc.name }}</span>
                        </div>
                        <div class="meta-row">
                            <span class="pl-label">Date</span>
                            <span class="pl-val">{{ frappe.utils.formatdate(doc.creation) }}</span>
                        </div>
                        <div class="meta-row">
                            <span class="pl-label">Purpose</span>
                            <span class="pl-val">{{ doc.purpose or "-" }}</span>
                        </div>
                        <div class="meta-row">
                            <span class="pl-label">Page</span>
                            <span class="pl-val">{{ loop.index }} / {{ total_pages }}</span>
                        </div>
                    </div>
                </td>
            </tr>
        </table>
    </div>

    <div class="pl-parties">
        <table>
            <tr>
                <td>
                    <div class="section-title">Customer Details</div>
                    <div class="party-name">{{ displayed_customer }}</div>
                    {% if doc.customer and doc.customer_name and doc.customer != doc.customer_name %}
                        <div class="party-line">{{ doc.customer }}</div>
                    {% endif %}
                </td>

                <td>
                    <div class="section-title">{{ reference_label }}</div>
                    <div class="party-line">{{ reference_value }}</div>
                    {% if doc.parent_warehouse %}
                        <div class="section-title" style="margin-top:8px;">Warehouse</div>
                        <div class="party-line">{{ doc.parent_warehouse }}</div>
                    {% endif %}
                </td>
            </tr>
        </table>
    </div>
    {% else %}
    <div class="pl-page-subhead">
        <table>
            <tr>
                <td style="font-size: 12px; font-weight: bold; text-align: left; padding: 4px 0;">
                    PICKING LIST — {{ doc.name }}
                    {% if group_name %}
                        <span class="pl-group-badge-sub {% if 'FROZEN' in group_name %}badge-frozen{% else %}badge-dry{% endif %}">
                            {{ group_name }}
                        </span>
                    {% endif %}
                </td>
                <td style="font-size: 11.5px; text-align: right; color: #555; padding: 4px 0;">
                    Page {{ loop.index }} / {{ total_pages }}
                </td>
            </tr>
        </table>
    </div>
    {% endif %}

    <div class="pl-items">
        <table>
            <thead>
                <tr>
                    <th class="text-center" style="width:6%;">No</th>
                    <th class="text-center" style="width:34%;">Item</th>
                    <th class="text-right" style="width:10%;">Qty</th>
                    <th class="text-center" style="width:10%;">Satuan</th>
                    <th class="text-center" style="width:13%;">Picker</th>
                    <th class="text-center" style="width:13%;">Packer</th>
                    <th class="text-center" style="width:14%;">Checker</th>
                </tr>
            </thead>
            <tbody>
                {% for row in page_rows %}
                {% if row.uom and row.qty %}
                    {% set displayed_qty = row.qty %}
                    {% set displayed_uom = row.uom %}
                {% else %}
                    {% set displayed_qty = row.stock_qty %}
                    {% set displayed_uom = row.stock_uom or "-" %}
                {% endif %}
                <tr>
                    <td class="text-center" style="vertical-align:top;">
                        {{ start_index + loop.index }}
                    </td>
                    <td style="vertical-align:top;">
                        <span class="item-code">{{ row.item_name or row.item_code }}</span>
                        {% if row.batch_no %}
                            <br><span class="batch-box">Batch: {{ row.batch_no }}</span>
                        {% endif %}
                    </td>
                    <td class="text-right" style="vertical-align:top;">
                        {{ displayed_qty | int if displayed_qty == displayed_qty | int else displayed_qty }}
                    </td>
                    <td class="text-center" style="vertical-align:top;">
                        {{ displayed_uom }}
                    </td>
                    <td class="text-center"></td>
                    <td class="text-center"></td>
                    <td class="text-center"></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    {% if loop.last %}
    <div class="pl-summary-wrap">
        <table class="packing-footer-table">
            <tr>
                <td style="width:50%;"></td>
                <td style="width:25%; text-align:right; padding-right:12px;">
                    <div class="pl-summary-left">Time:</div>
                </td>
                <td style="width:25%;">
                    <span class="manual-line short"></span>
                </td>
            </tr>
            <tr>
                <td></td>
                <td style="text-align:right; padding-right:12px;">
                    <div class="pl-summary-left">Total Koli:</div>
                </td>
                <td>
                    <span class="manual-line short"></span>
                </td>
            </tr>
        </table>
    </div>

    <div class="pl-signatures">
        <table>
            <tr>
                <td>
                    <div class="sig-role">Picker Name</div>
                    <div class="sig-name">( ................................ )</div>
                </td>
                <td>
                    <div class="sig-role">Packer Name</div>
                    <div class="sig-name">( ................................ )</div>
                </td>
                <td>
                    <div class="sig-role" style="margin-bottom:4px;">Checker Name</div>
                    <div class="sig-name" style="margin-bottom:50px;">...... / ...... / ............</div>
                    <div class="sig-name">( ................................ )</div>
                </td>
            </tr>
        </table>
    </div>
    {% endif %}
</div>
{% endfor %}
</div>"""

    name = "Format Print Pick List"
    if not frappe.db.exists("Print Format", name):
        doc = frappe.get_doc({
            "doctype": "Print Format",
            "name": name,
            "doc_type": "Pick List",
            "module": "Stock",
            "standard": "No",
            "custom_format": 1,
            "print_format_type": "Jinja",
            "html": template_html,
        })
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return "created"

    doc = frappe.get_doc("Print Format", name)
    doc.html = template_html
    doc.custom_format = 1
    doc.print_format_type = "Jinja"
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return "updated"


def ensure_format_print_packing_slip():
    """Ensure standard Packing Slip print format matches the clean corporate layout in Image 3
    with logo, phone, customer details, clean table with PICKER, PACKER, CHECKER,
    summary for Time & Total Koli, and 3-column signature block."""
    template_html = """<div class="ps-print-format">
<style>
    @page {
        size: A4 portrait;
        margin: 10mm;
    }

    .ps-print-format {
        font-family: Arial, "Helvetica Neue", Helvetica, sans-serif;
        color: #111111;
        font-size: 13px;
        background: #ffffff;
        padding: 0;
        line-height: 1.4;
    }
    .ps-print-format table {
        width: 100%;
        border-collapse: collapse;
    }

    /* HEADER */
    .ps-header {
        margin-bottom: 12px;
    }
    .ps-header td {
        vertical-align: top;
    }
    .ps-header td.logo-cell {
        width: 50%;
        text-align: left;
    }
    .ps-header td.info-cell {
        width: 50%;
        text-align: right;
    }
    .ps-logo-wrap {
        display: inline-block;
        max-width: 105px;
        margin-bottom: 6px;
    }
    .ps-print-format .ps-logo-img,
    .ps-logo-img {
        max-height: 50px !important;
        max-width: 105px !important;
        width: auto !important;
        height: auto !important;
        object-fit: contain !important;
        display: block !important;
    }
    .company-name {
        font-weight: bold;
        font-size: 15px;
        margin-bottom: 4px;
        color: #1a1a1a;
    }
    .company-phone {
        font-size: 11.5px;
        color: #333333;
        line-height: 1.5;
    }
    .ps-title {
        font-size: 22px;
        font-weight: bold;
        text-align: right;
        margin: 0 0 10px 0;
        line-height: 1.1;
        color: #1a1a1a;
    }
    .ps-meta {
        text-align: right;
        font-size: 11.5px;
    }
    .ps-meta .meta-row {
        margin-bottom: 6px;
        white-space: nowrap;
    }
    .ps-meta .ps-label {
        display: inline-block;
        width: 110px;
        color: #666666;
        font-size: 11.5px;
        text-align: right;
        margin-right: 10px;
        vertical-align: middle;
    }
    .ps-meta .ps-val {
        display: inline-block;
        font-weight: 600;
        font-size: 11.5px;
        text-align: left;
        min-width: 130px;
        color: #1a1a1a;
        vertical-align: middle;
    }

    .ps-divider {
        border-top: 1.8px solid #111111;
        margin: 12px 0 16px 0;
    }

    /* CUSTOMER & DETAILS */
    .ps-parties {
        margin-bottom: 14px;
    }
    .ps-parties td {
        width: 50%;
        vertical-align: top;
        padding-right: 20px;
    }
    .ps-section-title {
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        color: #4b5563;
        margin-bottom: 3px;
        letter-spacing: 0.04em;
    }
    .ps-party-name {
        font-weight: 700;
        font-size: 14px;
        color: #111111;
        margin-bottom: 2px;
    }
    .ps-party-sub {
        font-size: 12px;
        color: #4b5563;
    }
    .ps-order-val {
        font-size: 13px;
        font-weight: 700;
        color: #111111;
        margin-bottom: 8px;
    }

    /* TABLE */
    .ps-items-table {
        width: 100%;
        border-collapse: collapse;
        border-top: 1.8px solid #111111;
        border-bottom: 1.8px solid #111111;
        margin-top: 14px;
    }
    .ps-items-table th {
        font-size: 11.5px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: #111111;
        padding: 8px 6px;
        border-bottom: 1px solid #111111;
    }
    .ps-items-table td {
        padding: 9px 6px;
        font-size: 12.5px;
        border-bottom: 1px solid #e5e7eb;
        vertical-align: middle;
    }
    .ps-items-table tr:last-child td {
        border-bottom: none;
    }
    .text-center { text-align: center; }
    .text-right { text-align: right; }
    .text-left { text-align: left; }

    /* SUMMARY */
    .ps-summary-wrap {
        margin-top: 16px;
        margin-bottom: 30px;
        display: table;
        width: 100%;
    }
    .ps-summary-spacer {
        display: table-cell;
        width: 60%;
    }
    .ps-summary-box {
        display: table-cell;
        width: 40%;
        text-align: right;
    }
    .ps-summary-row {
        margin-bottom: 8px;
        font-size: 13px;
        font-weight: 700;
        color: #111111;
    }
    .ps-dotted-line {
        display: inline-block;
        width: 150px;
        border-bottom: 1px dotted #888888;
        vertical-align: bottom;
        height: 14px;
        margin-left: 6px;
    }

    /* SIGNATURES */
    .ps-signatures {
        margin-top: 40px;
        width: 100%;
    }
    .ps-signatures td {
        width: 33.33%;
        text-align: center;
        vertical-align: top;
        padding: 0 10px;
    }
    .sig-role {
        font-size: 12.5px;
        font-weight: 700;
        color: #111111;
        margin-bottom: 48px;
    }
    .sig-name {
        font-size: 12px;
        color: #222222;
    }
    .sig-date {
        font-size: 11px;
        color: #666666;
        margin-bottom: 24px;
    }

    .ps-page {
        page-break-after: always;
        break-after: page;
    }
    .ps-page:last-child {
        page-break-after: auto;
        break-after: auto;
    }
</style>

{% set dn_doc = frappe.get_doc("Delivery Note", doc.delivery_note) if doc.delivery_note else None %}
{% set company_name = (dn_doc.company if dn_doc else "") or "PT. JUARA ROTI INDONESIA" %}
{% set company_doc = frappe.get_doc("Company", company_name) if company_name else None %}
{% set total_pkgs = dn_doc.custom_total_packages if dn_doc and dn_doc.custom_total_packages else (doc.to_case_no or 1) %}
{% set displayed_customer = (dn_doc.customer_name if dn_doc else "") or (dn_doc.customer if dn_doc else "") or "Internal / Outlet" %}
{% set displayed_status = "Draft" if doc.docstatus == 0 else "Submitted" %}

{# Referensi Sales Order dari Delivery Note #}
{% set sales_order_ref = "" %}
{% if dn_doc and dn_doc.items %}
    {% for it in dn_doc.items %}
        {% if it.against_sales_order and not sales_order_ref %}
            {% set sales_order_ref = it.against_sales_order %}
        {% endif %}
    {% endfor %}
{% endif %}

<div class="ps-page">
    <div class="ps-header">
        <table>
            <tr>
                <td class="logo-cell">
                    {% if company_doc and company_doc.company_logo and company_doc.company_logo.strip() %}
                        <div class="ps-logo-wrap">
                            <img src="{{ company_doc.company_logo }}" class="ps-logo-img">
                        </div>
                    {% endif %}
                    <div class="company-name">{{ company_name }}</div>
                    <div class="company-phone">Phone: {{ (company_doc.phone_no if company_doc else "") or "08114232789" }}</div>
                    {% if company_doc and company_doc.email %}<div class="company-phone">Email: {{ company_doc.email }}</div>{% endif %}
                    {% if company_doc and company_doc.website %}<div class="company-phone">WEB: {{ company_doc.website }}</div>{% endif %}
                </td>
                <td class="info-cell">
                    <div class="ps-title">PACKING LIST</div>
                    <div class="ps-meta">
                        <div class="meta-row">
                            <span class="ps-label">Status</span>
                            <span class="ps-val">{{ "Draft" if (dn_doc and dn_doc.docstatus == 0) else displayed_status }}</span>
                        </div>
                        <div class="meta-row">
                            <span class="ps-label">Delivery Note No.</span>
                            <span class="ps-val">{{ doc.delivery_note }}</span>
                        </div>
                        <div class="meta-row">
                            <span class="ps-label">Koli / Kemasan</span>
                            <span class="ps-val">Koli {{ doc.from_case_no }}{% if total_pkgs %} / {{ total_pkgs }}{% endif %}</span>
                        </div>
                        <div class="meta-row">
                            <span class="ps-label">Date</span>
                            <span class="ps-val">{{ frappe.utils.formatdate(dn_doc.posting_date if (dn_doc and dn_doc.posting_date) else doc.creation) }}</span>
                        </div>
                        <div class="meta-row">
                            <span class="ps-label">Purpose</span>
                            <span class="ps-val">Delivery</span>
                        </div>
                        <div class="meta-row">
                            <span class="ps-label">Page</span>
                            <span class="ps-val">1 / 1</span>
                        </div>
                    </div>
                </td>
            </tr>
        </table>
    </div>

    <div class="ps-divider"></div>

    <div class="ps-parties">
        <table>
            <tr>
                <td>
                    <div class="ps-section-title">CUSTOMER DETAILS</div>
                    <div class="ps-party-name">{{ displayed_customer }}</div>
                    {% if dn_doc and dn_doc.customer and dn_doc.customer != displayed_customer %}
                        <div class="ps-party-sub">{{ dn_doc.customer }}</div>
                    {% endif %}
                </td>
                <td>
                    <div class="ps-section-title">SALES ORDER</div>
                    <div class="ps-order-val">{{ sales_order_ref or "-" }}</div>
                    <div class="ps-section-title">WAREHOUSE</div>
                    <div class="ps-order-val">{{ (dn_doc.set_warehouse if dn_doc else "") or "Gudang Barang Jadi - JURI" }}</div>
                </td>
            </tr>
        </table>
    </div>

    <table class="ps-items-table">
        <thead>
            <tr>
                <th class="text-center" style="width: 6%;">NO</th>
                <th class="text-left" style="width: 44%;">ITEM</th>
                <th class="text-right" style="width: 10%;">QTY</th>
                <th class="text-center" style="width: 10%;">SATUAN</th>
                <th class="text-center" style="width: 10%;">PICKER</th>
                <th class="text-center" style="width: 10%;">PACKER</th>
                <th class="text-center" style="width: 10%;">CHECKER</th>
            </tr>
        </thead>
        <tbody>
            {% for row in doc.items %}
            <tr>
                <td class="text-center">{{ loop.index }}</td>
                <td class="text-left">
                    <span style="font-weight: 600;">{{ row.item_name or row.item_code }}</span>
                    {% if row.batch_no %}
                        <div style="font-size: 11px; color: #555;">Batch: {{ row.batch_no }}</div>
                    {% endif %}
                </td>
                <td class="text-right">{{ row.qty | int if row.qty == row.qty | int else row.qty }}</td>
                <td class="text-center">{{ row.stock_uom or row.uom or "Pack" }}</td>
                <td class="text-center"></td>
                <td class="text-center"></td>
                <td class="text-center"></td>
            </tr>
            {% endfor %}
        </tbody>
    </table>

    <div class="ps-summary-wrap">
        <div class="ps-summary-spacer"></div>
        <div class="ps-summary-box">
            <div class="ps-summary-row">
                Time: <span class="ps-dotted-line"></span>
            </div>
            <div class="ps-summary-row">
                Total Koli: <span class="ps-dotted-line"></span>
            </div>
        </div>
    </div>

    <div class="ps-signatures">
        <table>
            <tr>
                <td>
                    <div class="sig-role">Picker Name</div>
                    <div class="sig-name">( .................... )</div>
                </td>
                <td>
                    <div class="sig-role">Packer Name</div>
                    <div class="sig-name">( .................... )</div>
                </td>
                <td>
                    <div class="sig-role" style="margin-bottom: 12px;">Checker Name</div>
                    <div class="sig-date">....../....../..........</div>
                    <div class="sig-name">( .................... )</div>
                </td>
            </tr>
        </table>
    </div>
</div>
</div>"""

    name = "Format Print Packing Slip"
    if not frappe.db.exists("Print Format", name):
        doc = frappe.get_doc({
            "doctype": "Print Format",
            "name": name,
            "doc_type": "Packing Slip",
            "module": "Stock",
            "standard": "No",
            "custom_format": 1,
            "print_format_type": "Jinja",
            "html": template_html,
        })
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return "created"

    doc = frappe.get_doc("Print Format", name)
    doc.html = template_html
    doc.custom_format = 1
    doc.print_format_type = "Jinja"
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return "updated"


def backfill_run_short_pick_snapshot():
    """F3/F4: only PLANNING Runs with no snapshot follow their Profile value.
    Reviewed Runs (any short_pick_status other than None) and every other
    status stay untouched, so a later Profile change cannot rewrite history."""
    frappe.db.sql(
        """
        UPDATE `tabWarehouse Fulfillment Run` run
        LEFT JOIN `tabWarehouse Fulfillment Profile` profile ON profile.name = run.profile
        SET run.short_pick_approval_required_snapshot =
            IFNULL(profile.short_pick_approval_required, 1)
        WHERE run.status = 'PLANNING'
            AND IFNULL(run.short_pick_approval_required_snapshot, 0) = 0
            AND IFNULL(run.short_pick_status, 'None') = 'None'
        """
    )
    frappe.db.commit()


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
