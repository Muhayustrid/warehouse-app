// Copyright (c) 2026, Muhammad Yusuf Tri Daryanto and contributors
// For license information, please see license.txt

/**
 * Stock Reconciliation Custom UOM and Count Input Protection.
 * Replaces W23 and owns custom-row synchronization, instance-local valuation balance adapter,
 * input snapshot, and Save/Submit barrier.
 */

(function () {
	const SR_GATE_ROLES = ["Stock Manager", "Stock User", "System Manager"];

	function enabled() {
		return SR_GATE_ROLES.some((role) => frappe.user.has_role(role));
	}

	function skip_row(row) {
		return !!(
			row &&
			(row.serial_no ||
				row.current_serial_no ||
				row.serial_and_batch_bundle ||
				row.current_serial_and_batch_bundle)
		);
	}

	function is_empty(val) {
		return val == null || val === "";
	}

	function same_value(a, b) {
		if (is_empty(a) && is_empty(b)) return true;
		if (is_empty(a) || is_empty(b)) return false;
		if (typeof a === "number" || typeof b === "number") {
			return Math.abs(flt(a) - flt(b)) <= 1e-9;
		}
		return a === b;
	}

	function values_differ(a, b) {
		return !same_value(a, b);
	}

	function resolve_val_rate(row) {
		if (!row) return null;
		return is_empty(row.valuation_rate) ? row.current_valuation_rate : row.valuation_rate;
	}

	const syncing_rows = new Set();
	const request_ids = new Map();
	const pending_sync_promises = new Map();
	// Last raw value typed per row field (pending until the model commits it), so unblurred
	// input is still detected at Save/Submit. count_touched records rows where the user entered
	// an After value in this form session, which distinguishes a real 0 from a sanitized one.
	const typed_inputs = new Map();
	const count_touched = new Set();
	const SR_ITEM_DOCTYPE = "Stock Reconciliation Item";
	const COUNT_FIELDS = ["custom_qty_after", "custom_valuation_rate_per_uom"];
	const BALANCE_METHOD =
		"erpnext.stock.doctype.stock_reconciliation.stock_reconciliation.get_stock_balance_for";
	let form_input_generation = 0;
	// Bumped on posting/company changes; drops in-flight compute_row replies (and their tokens)
	// without touching the per-row ids the native posting refresh depends on.
	let context_generation = 0;

	function typed_key(row_name, fieldname) {
		return row_name + "\u0000" + fieldname;
	}

	function get_active_field_info(el) {
		if (!el) return null;
		let fieldname = null;
		let row_name = null;

		// 1. Resolve fieldname: direct attribute, or closest element with data-fieldname, or control's df
		if (typeof el.getAttribute === "function" && el.getAttribute("data-fieldname")) {
			fieldname = el.getAttribute("data-fieldname");
		} else if (typeof el.closest === "function") {
			const fn_el = el.closest("[data-fieldname]");
			if (fn_el && typeof fn_el.getAttribute === "function") {
				fieldname = fn_el.getAttribute("data-fieldname");
			}
		}

		// 2. Resolve row identity: closest .grid-row wrapper (installed Frappe grid_row.js sets data-name on this wrapper)
		if (typeof el.closest === "function") {
			const grid_row = el.closest(".grid-row");
			if (grid_row) {
				if (typeof grid_row.getAttribute === "function") {
					row_name = grid_row.getAttribute("data-name");
				}
				if (!row_name && typeof $ !== "undefined") {
					const $gr = $(grid_row);
					row_name = (typeof $gr.attr === "function" ? $gr.attr("data-name") : null) ||
						(typeof $gr.data === "function" ? ($gr.data("name") || ($gr.data("doc") && $gr.data("doc").name)) : null);
				}
			}
			if (!row_name) {
				const ctrl = el.closest(".frappe-control");
				if (ctrl && ctrl.fieldobj) {
					row_name = ctrl.fieldobj.docname || (ctrl.fieldobj.doc && ctrl.fieldobj.doc.name);
					if (!fieldname && ctrl.fieldobj.df) {
						fieldname = ctrl.fieldobj.df.fieldname;
					}
				}
			}
		}

		// Fallback: direct attribute on element
		if (!row_name && typeof el.getAttribute === "function") {
			row_name = el.getAttribute("data-name");
		}

		return { fieldname, row_name };
	}

	// The value the native control will commit (ControlFloat.parse evaluates expressions like "2+3").
	function parsed_input_value(el) {
		const raw = el.value == null ? "" : String(el.value);
		const ctrl = typeof el.closest === "function" ? el.closest(".frappe-control") : null;
		const parse = ctrl && ctrl.fieldobj && ctrl.fieldobj.parse;
		if (typeof parse !== "function" || raw === "") return raw;
		const parsed = parse.call(ctrl.fieldobj, raw);
		return parsed == null ? "" : parsed;
	}

	function snapshot_typed_input(target) {
		const info = get_active_field_info(target);
		if (!info || !info.row_name || COUNT_FIELDS.indexOf(info.fieldname) === -1) return;
		const value = parsed_input_value(target);
		typed_inputs.set(typed_key(info.row_name, info.fieldname), value);
		if (info.fieldname === "custom_qty_after") count_touched.add(info.row_name);
		form_input_generation++;
	}

	if (typeof $ !== "undefined") {
		$(document).on("input", function (e) {
			const target = (e && e.target) || this;
			if (!target) return;
			snapshot_typed_input(target);
		});
	}

	// True while any count field holds a raw value the model has not committed yet.
	function raw_input_pending() {
		const active_el = typeof document !== "undefined" ? document.activeElement : null;
		if (active_el && (active_el.tagName === "INPUT" || active_el.tagName === "TEXTAREA")) {
			const info = get_active_field_info(active_el);
			if (info && info.row_name && COUNT_FIELDS.indexOf(info.fieldname) !== -1) {
				const live = locals[SR_ITEM_DOCTYPE] && locals[SR_ITEM_DOCTYPE][info.row_name];
				if (live && values_differ(live[info.fieldname], parsed_input_value(active_el))) return true;
			}
		}
		for (const [key, raw] of Array.from(typed_inputs)) {
			const [row_name, fieldname] = key.split("\u0000");
			const live = locals[SR_ITEM_DOCTYPE] && locals[SR_ITEM_DOCTYPE][row_name];
			if (!live) {
				typed_inputs.delete(key);
				continue;
			}
			if (values_differ(live[fieldname], raw)) return true;
			typed_inputs.delete(key); // committed
		}
		return false;
	}

	function row_has_typed_count(row_name) {
		return count_touched.has(row_name);
	}

	function next_request_id(cdn) {
		const req_id = (request_ids.get(cdn) || 0) + 1;
		request_ids.set(cdn, req_id);
		return req_id;
	}

	function update_posting_indicator(frm) {
		if (!frm || !frm.doc) return;
		const is_explicit = cint(frm.doc.set_posting_time) === 1;
		const msg = is_explicit
			? __("Posting Mode: Waktu Spesifik ({0} {1}). Target hitungan diterapkan pada timestamp ini.", [
					frm.doc.posting_date,
					frm.doc.posting_time,
			  ])
			: __("Posting Mode: Waktu Nyata (now). Target hitungan diterapkan pada waktu posting aktual saat submit.");
		const indicator = is_explicit ? "blue" : "green";
		if (frm.dashboard && frm.dashboard.set_headline_alert) {
			frm.dashboard.set_headline_alert(msg, indicator);
		} else if (frm.dashboard && frm.dashboard.set_headline) {
			frm.dashboard.set_headline(msg);
		}
	}

	// Counted rows derive qty/valuation_rate from After, so only those rows are locked;
	// native rows keep both columns editable. The per-row docfield copy is what grid_row.make_control
	// and the row form read, so editors created later inherit the lock too.
	function apply_row_qty_protection(frm) {
		if (!frm.doc || typeof frm.set_df_property !== "function") return;
		for (const row of frm.doc.items || []) {
			const locked = row.custom_uom ? 1 : 0;
			frm.set_df_property("items", "read_only", locked, frm.doc.name, "qty", row.name);
			frm.set_df_property("items", "read_only", locked, frm.doc.name, "valuation_rate", row.name);
		}
	}

	function apply_default_uom(frm, cdt, cdn, fallback_stock, expected_item, req_id) {
		const captured_doc = frm.doc;
		const captured_row = locals[cdt] && locals[cdt][cdn];
		if (!captured_row || !captured_row.item_code || captured_row.custom_uom || skip_row(captured_row)) return;
		const item = expected_item || captured_row.item_code;
		if (expected_item && captured_row.item_code !== expected_item) return;

		return frappe.db
			.get_value("Item", item, [
				"custom_default_inventory_unit_of_measure",
				"stock_uom",
				"has_serial_no",
			])
			.then((r) => {
				if (typeof cur_frm !== "undefined" && cur_frm && cur_frm.doc && cur_frm.doc !== captured_doc) return;
				if (frm.doc !== captured_doc) return;
				if (req_id != null && request_ids.get(cdn) !== req_id) return;
				const live = locals[cdt] && locals[cdt][cdn];
				if (!live || live !== captured_row || live.item_code !== item || live.custom_uom || skip_row(live)) return;
				const m = r.message || {};
				if (cint(m.has_serial_no)) return;
				const target = m.custom_default_inventory_unit_of_measure || (fallback_stock && m.stock_uom);
				if (!target || !live || live.custom_uom || skip_row(live)) return;
				return frappe.model.set_value(cdt, cdn, "custom_uom", target);
			});
	}

	function apply_defaults(frm) {
		if (frm.doc.docstatus > 0) return;
		(frm.doc.items || []).forEach((d) => {
			if (d.item_code && !d.custom_uom && !skip_row(d)) {
				apply_default_uom(frm, d.doctype, d.name);
			}
		});
	}

	function snapshot_matches(live, frm, snapshot, opts) {
		if (!live || !frm || !frm.doc) return false;
		return (
			live.name === snapshot.row_name &&
			live.item_code === snapshot.item_code &&
			live.warehouse === snapshot.warehouse &&
			(live.batch_no || null) === snapshot.batch_no &&
			live.custom_uom === snapshot.uom &&
			(!!opts?.omit_qty_after || same_value(live.custom_qty_after, snapshot.qty_after)) &&
			(!!opts?.omit_rate_per_uom || same_value(live.custom_valuation_rate_per_uom, snapshot.rate_per_uom)) &&
			(live.allow_zero_valuation_rate ? 1 : 0) === snapshot.allow_zero &&
			frm.doc.name === snapshot.form_name &&
			frm.doc.posting_date === snapshot.posting_date &&
			frm.doc.posting_time === snapshot.posting_time &&
			(cint(frm.doc.set_posting_time) === 1 ? 1 : 0) === snapshot.set_posting_time &&
			(frm.doc.company || null) === snapshot.company
		);
	}

	function sync_row(frm, cdt, cdn, opts) {
		const row = locals[cdt] && locals[cdt][cdn];
		if (!row || skip_row(row) || frm.doc.docstatus > 0) return;

		const captured_doc = frm.doc;
		const captured_row = row;
		const req_id = next_request_id(cdn);
		const ctx_gen = context_generation;
		const posting_date = frm.doc && frm.doc.posting_date;
		const posting_time = frm.doc && frm.doc.posting_time;

		if (
			!row.item_code ||
			!row.warehouse ||
			!row.custom_uom ||
			!posting_date ||
			!posting_time
		) {
			// Incomplete context: clear confirmation token, keep user inputs
			if (row.custom_count_confirmation) {
				frappe.model.set_value(cdt, cdn, "custom_count_confirmation", null);
			}
			return;
		}

		const snapshot = {
			form_name: frm.doc.name,
			row_name: cdn,
			item_code: row.item_code,
			warehouse: row.warehouse,
			batch_no: row.batch_no || null,
			uom: row.custom_uom,
			qty_after: row.custom_qty_after,
			rate_per_uom: row.custom_valuation_rate_per_uom,
			qty: row.qty,
			valuation_rate: resolve_val_rate(row),
			posting_date: posting_date,
			posting_time: posting_time,
			set_posting_time: cint(frm.doc.set_posting_time) === 1 ? 1 : 0,
			company: frm.doc.company || null,
			allow_zero: row.allow_zero_valuation_rate ? 1 : 0,
		};

		const args = {
			item_code: snapshot.item_code,
			warehouse: snapshot.warehouse,
			batch_no: snapshot.batch_no,
			posting_date: snapshot.posting_date,
			posting_time: snapshot.posting_time,
			set_posting_time: snapshot.set_posting_time,
			company: snapshot.company,
			uom: snapshot.uom,
			allow_zero_valuation_rate: snapshot.allow_zero,
			valuation_rate: snapshot.valuation_rate,
			qty: snapshot.qty,
			omit_confirmation: (opts && opts.omit_confirmation) ? 1 : 0,
		};
		if (!opts || !opts.omit_qty_after) {
			args.qty_after = snapshot.qty_after;
		}
		if (!opts || !opts.omit_rate_per_uom) {
			args.rate_per_uom = snapshot.rate_per_uom;
		}

		const sync_promise = frappe
			.xcall("warehouse_app.warehouse_app.stock_reconciliation.compute_row", args)
			.then((reply) => {
				if (typeof cur_frm !== "undefined" && cur_frm && cur_frm.doc && cur_frm.doc !== captured_doc) return;
				if (frm.doc !== captured_doc || frm.doc.docstatus > 0) return;
				if (request_ids.get(cdn) !== req_id || context_generation !== ctx_gen) return;
				const live = locals[cdt] && locals[cdt][cdn];
				if (!live || live !== captured_row) return;
				if (!snapshot_matches(live, frm, snapshot, opts)) return;

				syncing_rows.add(cdn);
				const promises = [];
				for (const [key, val] of Object.entries(reply || {})) {
					if (val == null && key === "custom_qty_after" && live.custom_qty_after != null && live.custom_qty_after !== "") continue;
					if (val == null && key === "custom_valuation_rate_per_uom" && live.custom_valuation_rate_per_uom != null && live.custom_valuation_rate_per_uom !== "") continue;
					if (values_differ(live[key], val)) {
						promises.push(frappe.model.set_value(cdt, cdn, key, val));
					}
				}
				return Promise.all(promises).finally(() => {
					syncing_rows.delete(cdn);
				});
			})
			.catch((err) => {
				if (typeof cur_frm !== "undefined" && cur_frm && cur_frm.doc && cur_frm.doc !== captured_doc) return;
				if (frm.doc !== captured_doc || frm.doc.docstatus > 0) return;
				if (request_ids.get(cdn) !== req_id || context_generation !== ctx_gen) return;
				const live = locals[cdt] && locals[cdt][cdn];
				if (!live || live !== captured_row) return;
				// Invalidate confirmation token, preserve user's typed After and UOM
				frappe.model.set_value(cdt, cdn, "custom_count_confirmation", null);
				if (err && err.message) {
					frappe.msgprint({
						title: __("Kesalahan Konversi Baris"),
						indicator: "red",
						message: err.message,
					});
				}
			})
			.finally(() => {
				if (pending_sync_promises.get(cdn) === sync_promise) {
					pending_sync_promises.delete(cdn);
				}
			});

		pending_sync_promises.set(cdn, sync_promise);
		return sync_promise;
	}

	function apply_custom_balance_update(frm, cdt, cdn, r, live) {
		const bal_qty = flt(r.message.qty);
		const bal_rate = flt(r.message.rate);

		syncing_rows.add(cdn);
		const updates = [
			frappe.model.set_value(cdt, cdn, "current_qty", bal_qty),
			frappe.model.set_value(cdt, cdn, "current_valuation_rate", bal_rate),
			frappe.model.set_value(cdt, cdn, "current_amount", bal_rate * bal_qty),
			frappe.model.set_value(cdt, cdn, "current_serial_no", r.message.serial_nos),
			frappe.model.set_value(
				cdt,
				cdn,
				"use_serial_batch_fields",
				r.message.use_serial_batch_fields
			),
		];
		if (live.qty != null && live.qty !== "") {
			updates.push(frappe.model.set_value(cdt, cdn, "quantity_difference", flt(live.qty) - bal_qty));
			updates.push(
				frappe.model.set_value(cdt, cdn, "amount_difference", flt(live.amount) - bal_rate * bal_qty)
			);
		}
		// Seed only the stock-UOM rate; Before, difference and rate per UOM come from compute_row,
		// which rounds with the installed field precision (sr_uom.precisions), never client constants.
		if (is_empty(live.custom_valuation_rate_per_uom) && is_empty(live.valuation_rate)) {
			updates.push(frappe.model.set_value(cdt, cdn, "valuation_rate", bal_rate));
			if (live.qty != null && live.qty !== "") {
				updates.push(frappe.model.set_value(cdt, cdn, "amount", flt(live.qty) * bal_rate));
			}
		}
		return Promise.all(updates)
			.finally(() => syncing_rows.delete(cdn))
			.then(() => sync_row(frm, cdt, cdn, { omit_confirmation: true }));
	}

	// Native-equivalent writes, mirroring the installed ERPNext callback field for field and in order.
	// set_value mutates the doc synchronously, so `amount` must be read after qty/rate are written.
	function apply_native_balance_update(frm, cdt, cdn, r) {
		const row = locals[cdt] && locals[cdt][cdn];
		if (!row) return;
		const calls = [];
		if (!frm.doc.scan_mode) {
			calls.push(frappe.model.set_value(cdt, cdn, "qty", r.message.qty));
		}
		calls.push(frappe.model.set_value(cdt, cdn, "valuation_rate", r.message.rate));
		calls.push(frappe.model.set_value(cdt, cdn, "current_qty", r.message.qty));
		calls.push(frappe.model.set_value(cdt, cdn, "current_valuation_rate", r.message.rate));
		calls.push(frappe.model.set_value(cdt, cdn, "current_amount", r.message.rate * r.message.qty));
		calls.push(frappe.model.set_value(cdt, cdn, "amount", row.qty * row.valuation_rate));
		calls.push(frappe.model.set_value(cdt, cdn, "current_serial_no", r.message.serial_nos));
		calls.push(
			frappe.model.set_value(cdt, cdn, "use_serial_batch_fields", r.message.use_serial_batch_fields)
		);
		if (frm.doc.purpose === "Stock Reconciliation" && !frm.doc.scan_mode) {
			calls.push(frappe.model.set_value(cdt, cdn, "serial_no", r.message.serial_nos));
		}
		return Promise.all(calls);
	}

	function install_valuation_adapter(frm) {
		if (!frm || frm._sr_valuation_adapter_installed) return;
		frm._sr_valuation_adapter_installed = true;

		const native_fn = frm.events.set_valuation_rate_and_qty;
		frm.events.set_valuation_rate_and_qty = function (frm, cdt, cdn) {
			if (!enabled()) {
				return native_fn ? native_fn.apply(this, arguments) : undefined;
			}
			const captured_doc = frm.doc;
			const captured_row = locals[cdt] && locals[cdt][cdn];
			if (!captured_row || !captured_row.item_code || !captured_row.warehouse) return;

			// The adapter always issues the balance request itself and decides what to do
			// with the reply at response time, so a row switching native <-> counted mid-flight
			// can never apply the wrong write set.
			const req_id = next_request_id(cdn);
			const snapshot = {
				item_code: captured_row.item_code,
				warehouse: captured_row.warehouse,
				batch_no: captured_row.batch_no || null,
				posting_date: captured_doc.posting_date,
				posting_time: captured_doc.posting_time,
				set_posting_time: cint(captured_doc.set_posting_time) === 1 ? 1 : 0,
				company: captured_doc.company || null,
			};

			frappe.call({
				method: BALANCE_METHOD,
				args: {
					item_code: snapshot.item_code,
					warehouse: snapshot.warehouse,
					posting_date: snapshot.posting_date,
					posting_time: snapshot.posting_time,
					batch_no: captured_row.batch_no,
					row: captured_row,
					company: snapshot.company,
				},
				callback: function (r) {
					if (!r || !r.message) return;
					if (typeof cur_frm !== "undefined" && cur_frm && cur_frm.doc && cur_frm.doc !== captured_doc) return;
					if (frm.doc !== captured_doc || frm.doc.docstatus > 0) return;
					if (request_ids.get(cdn) !== req_id) return;
					const live = locals[cdt] && locals[cdt][cdn];
					if (!live || live !== captured_row) return;
					if (
						live.item_code !== snapshot.item_code ||
						live.warehouse !== snapshot.warehouse ||
						(live.batch_no || null) !== snapshot.batch_no ||
						frm.doc.posting_date !== snapshot.posting_date ||
						frm.doc.posting_time !== snapshot.posting_time ||
						(cint(frm.doc.set_posting_time) === 1 ? 1 : 0) !== snapshot.set_posting_time ||
						(frm.doc.company || null) !== snapshot.company
					) {
						return;
					}

					if (live.custom_uom) {
						if (skip_row(live)) return;
						return apply_custom_balance_update(frm, cdt, cdn, r, live);
					}
					return apply_native_balance_update(frm, cdt, cdn, r);
				},
			});
		};
	}

	// Per-row request ids are not bumped: the native posting handlers already issued fresh balance
	// requests, and older balance replies are dropped by their context snapshot.
	function invalidate_all_confirmations(frm) {
		if (!frm || !frm.doc || !frm.doc.items) return;
		context_generation++;
		for (const row of frm.doc.items) {
			if (row.custom_uom && row.custom_count_confirmation) {
				frappe.model.set_value(row.doctype, row.name, "custom_count_confirmation", null);
			}
		}
	}

	function confirm_unconfirmed_rows(frm) {
		frm = frm || (typeof cur_frm !== "undefined" ? cur_frm : null);
		if (!frm || !frm.doc || frm.doc.docstatus > 0) return Promise.resolve();
		const items = frm.doc.items || [];
		const promises = [];
		for (const row of items) {
			if (!row.custom_uom || skip_row(row)) continue;
			if (row.custom_qty_after != null && row.custom_qty_after !== "") {
				promises.push(sync_row(frm, row.doctype, row.name));
			}
		}
		return Promise.all(promises);
	}

	frappe.ui.form.on("Stock Reconciliation", {
		setup(frm) {
			if (!enabled()) return;
			install_valuation_adapter(frm);
			frm.confirm_count_rows = () => confirm_unconfirmed_rows(frm);
		},
		onload(frm) {
			if (!enabled()) return;
			install_valuation_adapter(frm);
			frm.confirm_count_rows = () => confirm_unconfirmed_rows(frm);
		},
		refresh(frm) {
			if (!enabled()) return;
			if (frm._current_doc_instance !== frm.doc) {
				frm._current_doc_instance = frm.doc;
				form_input_generation++;
				typed_inputs.clear();
				count_touched.clear();
				(frm.doc.items || []).forEach((row) => next_request_id(row.name));
			}
			install_valuation_adapter(frm);
			frm.confirm_count_rows = () => confirm_unconfirmed_rows(frm);
			update_posting_indicator(frm);

			if (frm.doc.docstatus === 0) {
				frm.add_custom_button(__("Import Stock Count"), () => open_import_dialog(frm));
				frm.add_custom_button(__("Konfirmasi Hitungan"), () => frm.confirm_count_rows());
			}
			apply_row_qty_protection(frm);
		},
		items_on_form_rendered(frm) {
			if (!enabled()) return;
			apply_row_qty_protection(frm);
		},
		company(frm) {
			if (!enabled()) return;
			form_input_generation++;
			if (frm.doc.docstatus === 0) {
				invalidate_all_confirmations(frm);
			}
		},
		posting_date(frm) {
			if (!enabled()) return;
			form_input_generation++;
			update_posting_indicator(frm);
			if (frm.doc.docstatus === 0) {
				invalidate_all_confirmations(frm);
			}
		},
		posting_time(frm) {
			if (!enabled()) return;
			form_input_generation++;
			update_posting_indicator(frm);
			if (frm.doc.docstatus === 0) {
				invalidate_all_confirmations(frm);
			}
		},
		set_posting_time(frm) {
			if (!enabled()) return;
			form_input_generation++;
			update_posting_indicator(frm);
			if (frm.doc.docstatus === 0) {
				invalidate_all_confirmations(frm);
			}
		},
		scan_mode(frm) {
			if (!enabled()) return;
			if (frm.doc.scan_mode) {
				const has_custom = (frm.doc.items || []).some((r) => r.custom_uom);
				if (has_custom) {
					frappe.msgprint({
						title: __("Scan Mode"),
						indicator: "orange",
						message: __("Scan mode hanya didukung untuk item Stock UOM native, bukan custom UOM."),
					});
				}
			}
		},
		// Runs for Save and Submit alike (frappe form.validate_and_save).
		validate(frm) {
			if (!enabled() || frm.doc.docstatus > 0) return;

			const active_el = typeof document !== "undefined" ? document.activeElement : null;

			// Flush the focused editor so its value reaches the model.
			if (active_el && active_el.blur) {
				active_el.blur();
			}

			const start_generation = form_input_generation;
			const unblurred = raw_input_pending();

			function verify_save() {
				if (unblurred || raw_input_pending() || form_input_generation !== start_generation) {
					frappe.msgprint({
						title: __("Perubahan Input Terdeteksi"),
						indicator: "orange",
						message: __("Input hitungan berubah saat proses validasi. Simpan dibatalkan; silakan simpan ulang."),
					});
					frappe.validated = false;
					return false;
				}
				return check_custom_row_confirmations(frm);
			}

			// Save barrier: wait for any pending sync calls
			if (pending_sync_promises.size > 0) {
				return Promise.all(Array.from(pending_sync_promises.values())).then(() => {
					return verify_save();
				});
			}

			return verify_save();
		},
	});

	function check_custom_row_confirmations(frm) {
		const items = frm.doc.items || [];
		for (let i = 0; i < items.length; i++) {
			const row = items[i];
			if (skip_row(row)) continue;

			if (!row.custom_uom) {
				// Float fields sanitize empty to 0 on save, so a reloaded native row looks "counted".
				// Only a value the user actually entered in this form session is a real count.
				const has_count =
					row.custom_qty_after != null &&
					row.custom_qty_after !== "" &&
					(row_has_typed_count(row.name) || flt(row.custom_qty_after) !== 0);
				if (has_count) {
					frappe.msgprint({
						title: __("UOM Diperlukan"),
						indicator: "red",
						message: __("Baris #{0} ({1}): UOM wajib diisi jika Qty After memiliki nilai.", [
							row.idx || i + 1,
							row.item_code || "",
						]),
					});
					frappe.validated = false;
					return false;
				}
				continue;
			}

			// Check uncounted row
			if (row.custom_qty_after == null || row.custom_qty_after === "") {
				frappe.msgprint({
					title: __("Hitungan Belum Lengkap"),
					indicator: "red",
					message: __("Baris #{0} ({1}): Qty After belum diisi. Isi hitungan atau hapus baris.", [
						row.idx || i + 1,
						row.item_code,
					]),
				});
				frappe.validated = false;
				return false;
			}

			// Check confirmation token
			if (!row.custom_count_confirmation) {
				frappe.msgprint({
					title: __("Konfirmasi Hitungan Diperlukan"),
					indicator: "red",
					message: __(
						"Baris #{0} ({1}): Konfirmasi hitungan belum valid untuk konteks saat ini. Mohon periksa kembali.",
						[row.idx || i + 1, row.item_code]
					),
				});
				frappe.validated = false;
				return false;
			}
		}
	}

	frappe.ui.form.on("Stock Reconciliation Item", {
		items_remove(frm, cdt, cdn) {
			form_input_generation++;
			request_ids.delete(cdn);
			pending_sync_promises.delete(cdn);
			syncing_rows.delete(cdn);
			typed_inputs.delete(typed_key(cdn, "custom_qty_after"));
			typed_inputs.delete(typed_key(cdn, "custom_valuation_rate_per_uom"));
			count_touched.delete(cdn);
		},
		item_code(frm, cdt, cdn) {
			if (!enabled() || frm.doc.docstatus > 0) return;
			form_input_generation++;
			const row = locals[cdt] && locals[cdt][cdn];
			const req_id = next_request_id(cdn);
			const expected_item = row && row.item_code;

			syncing_rows.add(cdn);
			const reset_promises = [
				frappe.model.set_value(cdt, cdn, "custom_uom", ""),
				frappe.model.set_value(cdt, cdn, "custom_conversion_factor", ""),
				frappe.model.set_value(cdt, cdn, "custom_qty_before", ""),
				frappe.model.set_value(cdt, cdn, "custom_qty_difference_per_uom", ""),
				frappe.model.set_value(cdt, cdn, "custom_valuation_rate_per_uom", ""),
				frappe.model.set_value(cdt, cdn, "custom_count_confirmation", null),
			];

			return Promise.all(reset_promises)
				.finally(() => {
					syncing_rows.delete(cdn);
				})
				.then(() => {
					if (!expected_item) return;
					return new Promise((resolve) => {
						frappe.after_ajax(() => {
							if (request_ids.get(cdn) !== req_id) return resolve();
							const live = locals[cdt] && locals[cdt][cdn];
							if (!live || live.item_code !== expected_item || skip_row(live)) return resolve();
							resolve(apply_default_uom(frm, cdt, cdn, true, expected_item, req_id));
						});
					});
				});
		},
		custom_uom(frm, cdt, cdn) {
			if (!enabled() || syncing_rows.has(cdn) || frm.doc.docstatus > 0) return;
			form_input_generation++;
			apply_row_qty_protection(frm);
			const row = locals[cdt] && locals[cdt][cdn];
			if (!row || skip_row(row)) return;

			if (!row.custom_uom || !row.item_code) {
				next_request_id(cdn);
				return Promise.all([
					frappe.model.set_value(cdt, cdn, "custom_conversion_factor", ""),
					frappe.model.set_value(cdt, cdn, "custom_qty_before", ""),
					frappe.model.set_value(cdt, cdn, "custom_qty_difference_per_uom", ""),
					frappe.model.set_value(cdt, cdn, "custom_valuation_rate_per_uom", ""),
					frappe.model.set_value(cdt, cdn, "custom_count_confirmation", null),
					frappe.model.set_value(cdt, cdn, "qty", null),
					frappe.model.set_value(cdt, cdn, "valuation_rate", null),
				]);
			}
			return sync_row(frm, cdt, cdn, { omit_qty_after: true, omit_rate_per_uom: true, omit_confirmation: true });
		},
		custom_qty_after(frm, cdt, cdn) {
			if (!enabled() || syncing_rows.has(cdn) || frm.doc.docstatus > 0) return;
			form_input_generation++;
			return sync_row(frm, cdt, cdn);
		},
		custom_valuation_rate_per_uom(frm, cdt, cdn) {
			if (!enabled() || syncing_rows.has(cdn) || frm.doc.docstatus > 0) return;
			form_input_generation++;
			return sync_row(frm, cdt, cdn, { omit_confirmation: true });
		},
		warehouse(frm, cdt, cdn) {
			if (!enabled() || syncing_rows.has(cdn) || frm.doc.docstatus > 0) return;
			form_input_generation++;
			return sync_row(frm, cdt, cdn, { omit_confirmation: true });
		},
		batch_no(frm, cdt, cdn) {
			if (!enabled() || syncing_rows.has(cdn) || frm.doc.docstatus > 0) return;
			form_input_generation++;
			return sync_row(frm, cdt, cdn, { omit_confirmation: true });
		},
		current_qty(frm, cdt, cdn) {
			if (!enabled() || syncing_rows.has(cdn) || frm.doc.docstatus > 0) return;
			form_input_generation++;
			return sync_row(frm, cdt, cdn, { omit_confirmation: true });
		},
		qty(frm, cdt, cdn) {
			if (!enabled() || syncing_rows.has(cdn) || frm.doc.docstatus > 0) return;
			const row = locals[cdt] && locals[cdt][cdn];
			if (!row || !row.custom_uom || skip_row(row)) return;

			// Native qty is strictly one-way derived for custom rows.
			// Any external event (e.g. barcode scanner) attempting to change native qty directly is blocked.
			const factor = flt(row.custom_conversion_factor) || 1.0;
			const expected_qty =
				row.custom_qty_after != null && row.custom_qty_after !== ""
					? flt(row.custom_qty_after) * factor
					: null;

			if (frappe.flags && frappe.flags.trigger_from_barcode_scanner) {
				frappe.msgprint({
					title: __("Barcode Scan"),
					indicator: "orange",
					message: __("Barcode scanning tidak didukung untuk baris custom UOM. Isi Qty After langsung."),
				});
			}

			// Restore derived qty
			if (values_differ(row.qty, expected_qty)) {
				syncing_rows.add(cdn);
				frappe.model.set_value(cdt, cdn, "qty", expected_qty).finally(() => {
					syncing_rows.delete(cdn);
				});
			}
		},
	});

	// ---------------------------------------------------------------------------
	// W26 Form Import Dialog & Controller
	// ---------------------------------------------------------------------------
	const SR_IMPORT = "warehouse_app.warehouse_app.sr_import.";

	function download_template(frm, d, file_type) {
		const warehouse = d.get_value("warehouse");
		if (!warehouse) {
			frappe.msgprint(__("Please choose a Warehouse first."));
			return;
		}
		open_url_post("/api/method/" + SR_IMPORT + "download_stock_count_template", {
			warehouse: warehouse,
			include_zero_stock: d.get_value("include_zero_stock") ? 1 : 0,
			file_type: file_type,
			company: frm.doc.company,
			posting_date: frm.doc.posting_date,
			posting_time: frm.doc.posting_time,
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

	function finish_import(frm, d, res, upload_ctx) {
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
				() => {
					// Stale check before replacement
					if (
						!frm.doc ||
						frm.doc.name !== upload_ctx.doc_name ||
						frm.doc.docstatus > 0 ||
						frm.doc.company !== upload_ctx.company ||
						frm.doc.posting_date !== upload_ctx.posting_date ||
						frm.doc.posting_time !== upload_ctx.posting_time ||
						(cint(frm.doc.set_posting_time) === 1 ? 1 : 0) !== upload_ctx.set_posting_time
					) {
						frappe.msgprint({
							title: __("Penggantian Dibatalkan"),
							indicator: "orange",
							message: __(
								"Konteks dokumen berubah sebelum konfirmasi. Penggantian tabel dibatalkan."
							),
						});
						return;
					}
					fill_grid(frm, d, res);
				}
			);
		} else {
			fill_grid(frm, d, res);
		}
	}

	function upload_count_file(frm, d) {
		const upload_ctx = {
			doc_name: frm.doc.name,
			company: frm.doc.company,
			posting_date: frm.doc.posting_date,
			posting_time: frm.doc.posting_time,
			set_posting_time: cint(frm.doc.set_posting_time) === 1 ? 1 : 0,
		};

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
						company: upload_ctx.company,
						posting_date: upload_ctx.posting_date,
						posting_time: upload_ctx.posting_time,
						set_posting_time: upload_ctx.set_posting_time,
					},
					callback(r) {
						// Stale upload guard: reject if form changed in flight
						if (
							!frm.doc ||
							frm.doc.name !== upload_ctx.doc_name ||
							frm.doc.docstatus > 0 ||
							frm.doc.company !== upload_ctx.company ||
							frm.doc.posting_date !== upload_ctx.posting_date ||
							frm.doc.posting_time !== upload_ctx.posting_time ||
							(cint(frm.doc.set_posting_time) === 1 ? 1 : 0) !== upload_ctx.set_posting_time
						) {
							frappe.msgprint({
								title: __("Upload Dibatalkan"),
								indicator: "orange",
								message: __(
									"Konteks dokumen (posting date/time/company) telah berubah selama proses upload. Upload dibatalkan untuk mencegah data basi."
								),
							});
							return;
						}
						finish_import(frm, d, r && r.message, upload_ctx);
					},
				});
			},
		});
	}

	function open_import_dialog(frm) {
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
					click: () => download_template(frm, d, "xlsx"),
				},
				{
					fieldname: "dl_csv",
					label: __("Download CSV Template"),
					fieldtype: "Button",
					click: () => download_template(frm, d, "csv"),
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
						__("Target hitungan diterapkan sesuai mode posting saat upload.") +
						"</li>" +
						"</ul>",
				},
				{
					fieldname: "upload_btn",
					label: __("Upload Count File"),
					fieldtype: "Button",
					click: () => upload_count_file(frm, d),
				},
			],
		});
		d.show();
	}

	if (typeof cur_frm !== "undefined" && cur_frm) {
		cur_frm.confirm_count_rows = () => confirm_unconfirmed_rows(cur_frm);
	}
})();
