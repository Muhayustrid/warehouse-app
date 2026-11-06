// Test runner for Stock Reconciliation client script
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const defaultNativeScript = path.resolve(__dirname, "fixtures/native_stock_reconciliation.js");
const defaultAppScript = path.resolve(__dirname, "../public/js/stock_reconciliation.js");

const nativeScriptPath = process.env.NATIVE_SR_SCRIPT || (fs.existsSync(defaultNativeScript) ? defaultNativeScript : null);
const appScriptPath = process.env.SR_SCRIPT || defaultAppScript;

const nativeScriptCode = nativeScriptPath && fs.existsSync(nativeScriptPath)
	? fs.readFileSync(nativeScriptPath, "utf8")
	: null;
const scriptCode = fs.readFileSync(appScriptPath, "utf8");

function setupEnvironment(options = {}) {
	const childHandlerMap = {};
	const formHandlerMap = {};
	const customButtons = {};
	const setValueCalls = [];
	const xcallCalls = [];
	const callCalls = [];
	const pendingBalanceCalls = [];
	const msgprintCalls = [];
	const activeElementBlurCalls = [];
	const dialogCalls = [];
	const fileUploaderCalls = [];

	let xcallHandler = async (method, args) => ({});
	let callHandler = null;

	const locals = {
		"Stock Reconciliation Item": {},
		"Stock Reconciliation": {},
	};

	const frm = {
		doc: {
			name: "SR-TEST",
			doctype: "Stock Reconciliation",
			posting_date: "2026-11-03",
			posting_time: "10:00:00",
			set_posting_time: 0,
			docstatus: 0,
			company: "Test Company",
			purpose: "Stock Reconciliation",
			items: [],
		},
		fields_dict: {
			items: {
				grid: {
					column_disp_overrides: {},
					grid_rows_by_docname: {},
					set_column_disp: (field, disp) => {
						frm.fields_dict.items.grid.column_disp_overrides[field] = disp;
					},
					set_column_disp_in_list_view: (field, disp) => {
						frm.fields_dict.items.grid.column_disp_overrides[field] = disp;
					},
				},
			},
			expense_account: {},
			cost_center: {},
		},
		events: {},
		set_df_property: () => {},
		trigger: function (event, ...args) {
			if (formHandlerMap[event]) {
				return Promise.all(formHandlerMap[event].map((fn) => fn(frm, ...args)));
			}
			if (frm.events[event]) {
				return Promise.resolve(frm.events[event](frm, ...args));
			}
			return Promise.resolve();
		},
		clear_table: (field) => {
			frm.doc[field] = [];
		},
		add_child: (field) => {
			const row = {
				doctype: "Stock Reconciliation Item",
				name: "row_" + ((frm.doc[field] || []).length + 1),
			};
			if (!frm.doc[field]) frm.doc[field] = [];
			frm.doc[field].push(row);
			if (!locals[row.doctype]) locals[row.doctype] = {};
			locals[row.doctype][row.name] = row;
			return row;
		},
		refresh_field: () => {},
		add_fetch: () => {},
		set_query: () => {},
		is_new: () => true,
		add_custom_button: (label, action) => {
			customButtons[label] = action;
		},
		toggle_display: () => {},
		dashboard: {
			headline: null,
			headline_indicator: null,
			clear_headline: () => {
				frm.dashboard.headline = null;
				frm.dashboard.headline_indicator = null;
			},
			set_headline: (msg) => {
				frm.dashboard.headline = msg;
			},
			set_headline_alert: (msg, indicator) => {
				frm.dashboard.headline = msg;
				frm.dashboard.headline_indicator = indicator;
			},
		},
	};

	const childHandlers = new Proxy(childHandlerMap, {
		get(target, prop) {
			if (typeof prop === "string" && prop in target) {
				return async function (frm, cdt, cdn) {
					for (const fn of target[prop]) {
						await fn(frm, cdt, cdn);
					}
				};
			}
			return target[prop];
		},
		set(target, prop, value) {
			target[prop] = Array.isArray(value) ? value : [value];
			return true;
		},
	});

	const frappe = {
		user: {
			has_role: () => true,
		},
		ui: {
			Dialog: class {
				constructor(opts) {
					this.opts = opts;
					this.values = {};
					this.visible = false;
					dialogCalls.push(this);
				}
				show() {
					this.visible = true;
				}
				hide() {
					this.visible = false;
				}
				get_value(fieldname) {
					return this.values[fieldname];
				}
				set_value(fieldname, value) {
					this.values[fieldname] = value;
				}
			},
			FileUploader: class {
				constructor(opts) {
					this.opts = opts;
					fileUploaderCalls.push(this);
				}
			},
			form: {
				on(doctype, handlers) {
					if (doctype === "Stock Reconciliation Item") {
						for (const [field, fn] of Object.entries(handlers)) {
							if (!childHandlerMap[field]) childHandlerMap[field] = [];
							childHandlerMap[field].push(fn);
						}
					} else if (doctype === "Stock Reconciliation") {
						for (const [event, fn] of Object.entries(handlers)) {
							if (!formHandlerMap[event]) formHandlerMap[event] = [];
							formHandlerMap[event].push(fn);
							frm.events[event] = fn;
						}
					}
				},
			},
		},
		model: {
			set_value(cdt, cdn, fieldname, value) {
				if (!locals[cdt]) locals[cdt] = {};
				if (!locals[cdt][cdn]) locals[cdt][cdn] = {};
				if (typeof fieldname === "object" && fieldname !== null) {
					Object.assign(locals[cdt][cdn], fieldname);
					setValueCalls.push({ cdt, cdn, fieldname, value: undefined });
					return Promise.resolve();
				}
				locals[cdt][cdn][fieldname] = value;
				setValueCalls.push({ cdt, cdn, fieldname, value });
				if (cdt === "Stock Reconciliation Item" && childHandlerMap[fieldname]) {
					let p = Promise.resolve();
					for (const handler of childHandlerMap[fieldname]) {
						p = p.then(() => handler(frm, cdt, cdn));
					}
					return p;
				}
				return Promise.resolve();
			},
			get_doc(cdt, cdn) {
				return (locals[cdt] && locals[cdt][cdn]) || null;
			},
		},
		get_doc(cdt, cdn) {
			return (locals[cdt] && locals[cdt][cdn]) || null;
		},
		call(opts) {
			callCalls.push(opts);
			if (opts.method && opts.method.includes("get_stock_balance_for")) {
				pendingBalanceCalls.push(opts);
				if (callHandler) return callHandler(opts);
				return;
			}
			if (callHandler) return callHandler(opts);
			if (opts.callback) {
				opts.callback({ message: {} });
			}
		},
		xcall(method, args) {
			xcallCalls.push({ method, args });
			return xcallHandler(method, args);
		},
		after_ajax(fn) {
			fn();
		},
		db: {
			get_value: () => Promise.resolve({ message: {} }),
		},
		show_alert(msg) {},
		msgprint(msg) {
			msgprintCalls.push(msg);
		},
		confirm(message, on_confirm) {
			on_confirm();
		},
		flags: {},
		validated: true,
		user_defaults: {
			use_serial_batch_fields: 1,
		},
		provide(ns) {
			const parts = ns.split(".");
			let cur = sandbox;
			for (const part of parts) {
				cur[part] = cur[part] || {};
				cur = cur[part];
			}
		},
	};

	const erpnext = {
		stock: {
			StockController: class {
				constructor(opts) {
					this.frm = opts.frm;
				}
				setup_posting_date_time_check() {}
				show_stock_ledger() {}
				show_general_ledger() {}
			},
		},
		accounts: {
			dimensions: {
				setup_dimension_filters() {},
				update_dimension() {},
			},
		},
		utils: {
			BarcodeScanner: class {
				constructor(opts) {
					this.frm = opts.frm;
				}
				process_scan() {}
			},
			view_serial_batch_nos() {},
			pick_serial_and_batch_bundle() {},
		},
		queries: {
			setup_queries() {},
			warehouse() {},
		},
		is_perpetual_inventory_enabled: () => false,
		toggle_serial_batch_fields: () => {},
		TransactionController: class {
			constructor(opts) {
				this.frm = opts.frm;
			}
			autofill_warehouse() {}
		},
	};

	const flt = (v, precision) => {
		if (v == null || v === "") return 0;
		const n = Number(v);
		if (Number.isNaN(n)) return 0;
		if (precision != null) {
			return Number(Math.round(Number(n + "e" + precision)) + "e-" + precision);
		}
		return n;
	};

	const cint = (v) => parseInt(v, 10) || 0;

	const __ = (text, args) => {
		if (!args) return text;
		let res = text;
		args.forEach((val, i) => {
			res = res.replace(`{${i}}`, val);
		});
		return res;
	};

	const eventListeners = [];
	const $ = function (target) {
		return {
			on: (event, selector, handler) => {
				eventListeners.push({
					target,
					event,
					selector: typeof selector === "string" ? selector : null,
					handler: typeof selector === "function" ? selector : handler,
				});
			},
			closest: (selector) => {
				if (target && typeof target.closest === "function") {
					const el = target.closest(selector);
					return $(el);
				}
				return {
					attr: (attr) => (target && typeof target.getAttribute === "function" ? target.getAttribute(attr) : null),
					data: () => null,
				};
			},
			attr: (attr) => (target && typeof target.getAttribute === "function" ? target.getAttribute(attr) : null),
			data: (key) => (target && target.data ? target.data[key] : null),
		};
	};
	$.extend = Object.assign;

	const document = {
		activeElement: {
			blur() {
				activeElementBlurCalls.push(true);
			},
		},
	};

	const sandbox = {
		frappe,
		erpnext,
		cur_frm: frm,
		locals,
		flt,
		cint,
		__,
		$,
		document,
		console,
		setTimeout,
		clearTimeout,
		Promise,
		Math,
		Object,
		Set,
		Map,
		Array,
	};

	vm.createContext(sandbox);

	if (nativeScriptCode) {
		vm.runInContext(nativeScriptCode, sandbox);
	}
	// appScript: false loads only the installed native script (behaviour baseline).
	if (options.appScript !== false) {
		vm.runInContext(scriptCode, sandbox);
	}

	return {
		childHandlers,
		formHandlers: formHandlerMap,
		setValueCalls,
		xcallCalls,
		callCalls,
		pendingBalanceCalls,
		msgprintCalls,
		activeElementBlurCalls,
		customButtons,
		dialogCalls,
		fileUploaderCalls,
		locals,
		frm,
		frappe,
		sandbox,
		setCurFrm: (newFrm) => {
			sandbox.cur_frm = newFrm;
		},
		setXcallHandler: (fn) => {
			xcallHandler = fn;
		},
		setCallHandler: (fn) => {
			callHandler = fn;
		},
		eventListeners,
		setActiveElement: (el) => {
			document.activeElement = el;
		},
		// Mirrors frappe/public/js/frappe/form/form.js validate_and_save: every
		// save action except "Update" runs the validate handlers before saving.
		triggerSave: async (action = "Save") => {
			frappe.validated = true;
			await frm.trigger("validate");
			return { action, validated: frappe.validated };
		},
		triggerInputEvent: (el) => {
			for (const l of eventListeners) {
				if (l.event === "input") {
					l.handler.call(el, { target: el });
				}
			}
		},
	};
}

test("late_native_balance_preserves_count_1056", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		stock_uom: "Pcs",
		custom_qty_before: 0,
		custom_qty_after: "",
		qty: null,
		valuation_rate: 10,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];

	// Finding 9: Exercise real lifecycle registration (setup/onload)
	await env.frm.trigger("setup");
	assert.equal(env.frm._sr_valuation_adapter_installed, true, "Adapter must be installed during setup lifecycle");

	// 1. Native balance request triggered and left pending (deferred)
	env.frm.events.set_valuation_rate_and_qty(env.frm, cdt, cdn);
	assert.equal(env.pendingBalanceCalls.length, 1);
	const balanceCall = env.pendingBalanceCalls[0];

	// 2. User enters 1056 Pack while balance request is pending
	env.setXcallHandler(async (method, args) => {
		if (method === "warehouse_app.warehouse_app.stock_reconciliation.compute_row") {
			const factor = 6;
			const after = args.qty_after != null ? args.qty_after : (args.qty != null ? args.qty / factor : 1056);
			const derived_qty = after != null ? Math.round(after * factor) : args.qty;
			return {
				custom_uom: "Pack",
				custom_conversion_factor: factor,
				custom_qty_before: 1051,
				custom_qty_after: after,
				custom_qty_difference_per_uom: after != null ? after - 1051 : 0,
				custom_valuation_rate_per_uom: 60,
				qty: derived_qty,
				valuation_rate: 10,
				custom_count_confirmation: "token123",
			};
		}
		return {};
	});

	await env.frappe.model.set_value(cdt, cdn, "custom_qty_after", 1056);
	await new Promise((r) => setTimeout(r, 20));

	// After typing, row has 1056 Pack and derived native qty 6336
	const rowBefore = env.locals[cdt][cdn];
	assert.equal(rowBefore.custom_qty_after, 1056);
	assert.equal(rowBefore.qty, 6336);

	// 3. Stale native balance callback arrives with qty: 6306
	balanceCall.callback({
		message: {
			qty: 6306,
			rate: 10,
			serial_nos: null,
			use_serial_batch_fields: 1,
		},
	});
	await new Promise((r) => setTimeout(r, 20));

	// Finding 9: Assert write order / that native callback never wrote 6306 to qty
	const wroteBalanceToQty = env.setValueCalls.some((c) => c.fieldname === "qty" && c.value === 6306);
	assert.equal(wroteBalanceToQty, false, "Adapter must prevent balance callback from writing balance qty to qty on custom row");

	// 4. Assert After remains 1056 and native qty remains 6336
	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_qty_after, 1056);
	assert.equal(row.qty, 6336);
});

test("qty_after edit calls endpoint once and applies reply", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_before: 1.0,
		custom_qty_after: 1.0,
		qty: 12,
		valuation_rate: 10,
	};

	env.setXcallHandler(async (method, args) => {
		assert.equal(
			method,
			"warehouse_app.warehouse_app.stock_reconciliation.compute_row"
		);
		assert.equal(args.item_code, "ITEM-001");
		assert.equal(args.warehouse, "Stores - RR");
		assert.equal(args.posting_date, "2026-11-03");
		assert.equal(args.posting_time, "10:00:00");
		assert.equal(args.uom, "Pack");
		assert.equal(args.qty_after, 2.0);

		return {
			custom_uom: "Pack",
			custom_conversion_factor: 12,
			custom_qty_before: 1.0,
			custom_qty_after: 2.0,
			custom_qty_difference_per_uom: 1.0,
			custom_valuation_rate_per_uom: 120,
			qty: 24,
			valuation_rate: 10,
		};
	});

	await env.frappe.model.set_value(cdt, cdn, "custom_qty_after", 2.0);
	await new Promise((r) => setTimeout(r, 10));

	assert.equal(env.xcallCalls.length, 1);
	const row = env.locals[cdt][cdn];
	assert.equal(row.qty, 24);
	assert.equal(row.custom_qty_difference_per_uom, 1.0);
	assert.equal(row.custom_valuation_rate_per_uom, 120);
});

test("stale reply is ignored", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_before: 1.0,
		custom_qty_after: 2.0,
		qty: 12,
	};

	let resolvePromise;
	const pendingPromise = new Promise((resolve) => {
		resolvePromise = resolve;
	});

	env.setXcallHandler(() => pendingPromise);

	// Start sync for qty_after = 2.0
	env.childHandlers.custom_qty_after(env.frm, cdt, cdn);
	assert.equal(env.xcallCalls.length, 1);

	// User changes custom_qty_after to 3.0 before promise resolves
	env.locals[cdt][cdn].custom_qty_after = 3.0;

	// Now resolve the earlier call
	resolvePromise({
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_before: 1.0,
		custom_qty_after: 2.0,
		custom_qty_difference_per_uom: 1.0,
		custom_valuation_rate_per_uom: 120,
		qty: 24,
		valuation_rate: 10,
	});

	await new Promise((r) => setTimeout(r, 10));

	// Reply for 2.0 should have been dropped; qty not updated to 24
	const row = env.locals[cdt][cdn];
	assert.equal(row.qty, 12);
	assert.equal(row.custom_qty_after, 3.0);
});

test("barcode scan on custom row blocked, derives native qty from custom_qty_after", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_before: 1.0,
		custom_qty_after: 1.0,
		qty: 12,
		valuation_rate: 10,
	};

	env.setXcallHandler(async () => {
		assert.fail("compute_row should not be called with reverse calculation from barcode scan");
	});

	// Simulate barcode scan flag and scan bumping native qty 12 -> 13
	env.frappe.flags.trigger_from_barcode_scanner = true;
	env.setValueCalls.length = 0;
	await env.frappe.model.set_value(cdt, cdn, "qty", 13);

	// Let chained promises resolve
	await new Promise((r) => setTimeout(r, 10));

	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_qty_after, 1.0);
	assert.equal(row.qty, 12);
	assert.ok(env.msgprintCalls.length > 0);
	assert.match(env.msgprintCalls[0].message, /Barcode scanning tidak didukung/);
});

test("endpoint rejection preserves user custom_uom and custom_qty_after, clears confirmation", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "InvalidUOM",
		custom_qty_after: 1.0,
		custom_count_confirmation: "old_token",
		qty: 12,
	};

	env.setXcallHandler(async () => {
		throw new Error("Invalid UOM");
	});

	await env.frappe.model.set_value(cdt, cdn, "custom_qty_after", 2.0);
	await new Promise((r) => setTimeout(r, 10));

	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_uom, "InvalidUOM");
	assert.equal(row.custom_qty_after, 2.0);
	assert.equal(row.custom_count_confirmation, null);
	assert.ok(env.msgprintCalls.length > 0);
});

test("cleared UOM blanks derived fields and unsets qty/valuation_rate", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_before: 1.0,
		custom_qty_after: 2.0,
		custom_qty_difference_per_uom: 1.0,
		custom_valuation_rate_per_uom: 120,
		qty: 24,
		valuation_rate: 10,
	};

	await env.frappe.model.set_value(cdt, cdn, "custom_uom", "");
	await new Promise((r) => setTimeout(r, 10));

	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_conversion_factor, "");
	assert.equal(row.custom_qty_before, "");
	// Per Defect F: clearing UOM keeps visible custom_qty_after
	assert.equal(row.custom_qty_after, 2.0);
	assert.equal(row.custom_qty_difference_per_uom, "");
	assert.equal(row.custom_valuation_rate_per_uom, "");
	assert.equal(row.qty, null);
	assert.equal(row.valuation_rate, null);
});

test("serial row is skipped", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-SERIAL",
		warehouse: "Stores - RR",
		serial_no: "SR-001",
		custom_uom: "Nos",
		custom_qty_after: 1.0,
		qty: 1,
	};

	env.setXcallHandler(async () => {
		assert.fail("xcall should not be called for serial row");
	});

	await env.childHandlers.custom_qty_after(env.frm, cdt, cdn);
	await env.childHandlers.qty(env.frm, cdt, cdn);

	assert.equal(env.xcallCalls.length, 0);
});

test("reply backfilling rate makes exactly one call", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_before: 1.0,
		custom_qty_after: 1.0,
		custom_valuation_rate_per_uom: "",
		qty: 12,
		current_valuation_rate: 10,
	};

	env.setXcallHandler(async (method, args) => {
		return {
			custom_uom: "Pack",
			custom_conversion_factor: 12,
			custom_qty_before: 1.0,
			custom_qty_after: 2.0,
			custom_qty_difference_per_uom: 1.0,
			custom_valuation_rate_per_uom: 120,
			qty: 24,
			valuation_rate: 10,
		};
	});

	await env.frappe.model.set_value(cdt, cdn, "custom_qty_after", 2.0);
	await new Promise((r) => setTimeout(r, 20));

	assert.equal(env.xcallCalls.length, 1);
	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_valuation_rate_per_uom, 120);
	assert.equal(row.qty, 24);
});

test("barcode scan on native-only row retains native behavior", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		qty: 12,
		valuation_rate: 10,
	};

	env.setXcallHandler(async () => {
		assert.fail("custom compute_row should not be called for native-only row");
	});

	await env.frappe.model.set_value(cdt, cdn, "qty", 13);
	await new Promise((r) => setTimeout(r, 10));

	const row = env.locals[cdt][cdn];
	assert.equal(row.qty, 13);
	assert.equal(env.xcallCalls.length, 0);
	assert.equal(env.msgprintCalls.length, 0);
});

test("old request fails after newer warehouse+qty request succeeds; newer values survive", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "WH-Old",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_before: 1.0,
		custom_qty_after: 1.0,
		qty: 12,
	};

	let rejectOld;
	const oldPromise = new Promise((_, reject) => {
		rejectOld = reject;
	});

	let callCount = 0;
	env.setXcallHandler((method, args) => {
		callCount++;
		if (callCount === 1) {
			return oldPromise;
		}
		// Newer request succeeds
		return Promise.resolve({
			custom_uom: "Pack",
			custom_conversion_factor: 12,
			custom_qty_before: 5.0,
			custom_qty_after: 5.0,
			custom_qty_difference_per_uom: 0.0,
			custom_valuation_rate_per_uom: 120,
			qty: 60,
			valuation_rate: 10,
		});
	});

	// Request 1: custom_qty_after edit on WH-Old
	env.childHandlers.custom_qty_after(env.frm, cdt, cdn);
	assert.equal(env.xcallCalls.length, 1);

	// User changes warehouse to WH-New and custom_qty_after to 5.0
	env.locals[cdt][cdn].warehouse = "WH-New";
	env.locals[cdt][cdn].custom_qty_after = 5.0;
	await env.childHandlers.warehouse(env.frm, cdt, cdn);
	assert.equal(env.xcallCalls.length, 2);

	// Newer request succeeded, check row values
	const row = env.locals[cdt][cdn];
	assert.equal(row.qty, 60);
	assert.equal(row.warehouse, "WH-New");
	assert.equal(row.custom_uom, "Pack");

	// Now old request rejects
	rejectOld(new Error("Old warehouse SLE failed"));
	await new Promise((r) => setTimeout(r, 20));

	// Rejection from stale request must NOT clear custom_uom or overwrite newer values
	assert.equal(row.custom_uom, "Pack");
	assert.equal(row.warehouse, "WH-New");
	assert.equal(row.qty, 60);
});

test("snapshot avoids old response overwriting changed posting context", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_before: 1.0,
		custom_qty_after: 1.0,
		qty: 12,
	};

	let resolveOld;
	const oldPromise = new Promise((resolve) => {
		resolveOld = resolve;
	});

	env.setXcallHandler(() => oldPromise);

	// Request 1 starts with posting_time = 10:00:00
	env.childHandlers.custom_qty_after(env.frm, cdt, cdn);
	assert.equal(env.xcallCalls.length, 1);

	// Context changes: posting_time updated to 15:00:00
	env.frm.doc.posting_time = "15:00:00";

	// Request 1 resolves with values from 10:00:00
	resolveOld({
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_before: 1.0,
		custom_qty_after: 1.0,
		custom_qty_difference_per_uom: 0.0,
		custom_valuation_rate_per_uom: 120,
		qty: 999, // stale qty
		valuation_rate: 10,
	});

	await new Promise((r) => setTimeout(r, 20));

	// Stale response must be dropped; qty not overwritten with 999
	const row = env.locals[cdt][cdn];
	assert.equal(row.qty, 12);
});

test("current_qty event triggers refresh on complete row", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_before: 1.0,
		custom_qty_after: 1.0,
		qty: 12,
	};

	env.setXcallHandler(async (method, args) => {
		return {
			custom_uom: "Pack",
			custom_conversion_factor: 12,
			custom_qty_before: 5.0,
			custom_qty_after: 1.0,
			custom_qty_difference_per_uom: -4.0,
			custom_valuation_rate_per_uom: 120,
			qty: 12,
			valuation_rate: 10,
		};
	});

	await env.childHandlers.current_qty(env.frm, cdt, cdn);
	await new Promise((r) => setTimeout(r, 10));

	assert.equal(env.xcallCalls.length, 1);
	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_qty_before, 5.0);
	assert.equal(row.custom_qty_difference_per_uom, -4.0);
});

test("incomplete row does not call endpoint or clear user values", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	// Missing warehouse
	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "",
		custom_uom: "Pack",
		custom_qty_after: 2.0,
		qty: 24,
	};

	env.setXcallHandler(async () => {
		assert.fail("endpoint should not be called for incomplete row");
	});

	await env.childHandlers.custom_qty_after(env.frm, cdt, cdn);
	await env.childHandlers.current_qty(env.frm, cdt, cdn);

	assert.equal(env.xcallCalls.length, 0);
	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_uom, "Pack");
	assert.equal(row.custom_qty_after, 2.0);
	assert.equal(row.qty, 24);

	// Missing posting_date on doc
	row.warehouse = "Stores - RR";
	env.frm.doc.posting_date = "";

	await env.childHandlers.custom_qty_after(env.frm, cdt, cdn);
	assert.equal(env.xcallCalls.length, 0);
	assert.equal(row.custom_uom, "Pack");
});

test("rejection after newer edit that sends NO request does not clear custom_uom", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_before: 1.0,
		custom_qty_after: 1.0,
		qty: 12,
	};

	let rejectOld;
	const oldPromise = new Promise((_, reject) => {
		rejectOld = reject;
	});

	env.setXcallHandler(() => oldPromise);

	// In-flight request 1 starts with complete context
	env.childHandlers.custom_qty_after(env.frm, cdt, cdn);
	assert.equal(env.xcallCalls.length, 1);

	// Posting time is cleared, then user edits custom_qty_after = 2.0
	env.frm.doc.posting_time = "";
	await env.frappe.model.set_value(cdt, cdn, "custom_qty_after", 2.0);

	// Because context is incomplete, no second xcall is dispatched
	assert.equal(env.xcallCalls.length, 1);
	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_qty_after, 2.0);

	// In-flight request 1 rejects
	rejectOld(new Error("Network / validation failure"));
	await new Promise((r) => setTimeout(r, 20));

	// Old rejection must NOT clear custom_uom
	assert.equal(row.custom_uom, "Pack");
	assert.equal(row.custom_qty_after, 2.0);
});

test("stale success after newer edit that sends NO request does not overwrite values", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_before: 1.0,
		custom_qty_after: 1.0,
		qty: 12,
	};

	let resolveOld;
	const oldPromise = new Promise((resolve) => {
		resolveOld = resolve;
	});

	env.setXcallHandler(() => oldPromise);

	// In-flight request 1 starts with complete context
	env.childHandlers.custom_qty_after(env.frm, cdt, cdn);
	assert.equal(env.xcallCalls.length, 1);

	// Posting time is cleared, then user edits custom_qty_after = 2.0
	env.frm.doc.posting_time = "";
	await env.frappe.model.set_value(cdt, cdn, "custom_qty_after", 2.0);

	// Because context is incomplete, no second xcall is dispatched
	assert.equal(env.xcallCalls.length, 1);
	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_qty_after, 2.0);

	// In-flight request 1 resolves with stale data for custom_qty_after = 1.0
	resolveOld({
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_before: 1.0,
		custom_qty_after: 1.0,
		custom_qty_difference_per_uom: 0.0,
		custom_valuation_rate_per_uom: 120,
		qty: 12,
		valuation_rate: 10,
	});
	await new Promise((r) => setTimeout(r, 20));

	// Stale success must NOT overwrite custom_qty_after with 1.0
	assert.equal(row.custom_qty_after, 2.0);
	assert.equal(row.custom_uom, "Pack");
});

test("F1: batch_no is threaded in snapshot and args to compute_row", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-BATCH",
		warehouse: "Stores - RR",
		batch_no: "B1",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_before: 2.0,
		custom_qty_after: 2.0,
		qty: 24,
		valuation_rate: 10,
	};

	env.setXcallHandler(async (method, args) => {
		assert.equal(args.batch_no, "B1");
		return {
			custom_uom: "Pack",
			custom_conversion_factor: 12,
			custom_qty_before: 2.0,
			custom_qty_after: 2.0,
			custom_qty_difference_per_uom: 0.0,
			custom_valuation_rate_per_uom: 120,
			qty: 24,
			valuation_rate: 10,
		};
	});

	await env.childHandlers.custom_qty_after(env.frm, cdt, cdn);
	await new Promise((r) => setTimeout(r, 10));

	assert.equal(env.xcallCalls.length, 1);
	assert.equal(env.xcallCalls[0].args.batch_no, "B1");
});

test("F2: custom_uom change omits rate_per_uom and derives display from preserved native rate", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_before: 2.0,
		custom_qty_after: 2.0,
		custom_valuation_rate_per_uom: 120,
		qty: 24,
		valuation_rate: 10,
	};

	env.setXcallHandler(async (method, args) => {
		// On UOM change, rate_per_uom and qty_after must be omitted
		assert.equal(args.uom, "Nos");
		assert.equal(args.qty_after, undefined);
		assert.equal(args.rate_per_uom, undefined);
		assert.equal(args.valuation_rate, 10);
		assert.equal(args.qty, 24);

		return {
			custom_uom: "Nos",
			custom_conversion_factor: 1,
			custom_qty_before: 24.0,
			custom_qty_after: 24.0,
			custom_qty_difference_per_uom: 0.0,
			custom_valuation_rate_per_uom: 10,
			qty: 24,
			valuation_rate: 10,
		};
	});

	// User edits custom_uom to Nos
	env.locals[cdt][cdn].custom_uom = "Nos";
	await env.childHandlers.custom_uom(env.frm, cdt, cdn);
	await new Promise((r) => setTimeout(r, 10));

	assert.equal(env.xcallCalls.length, 1);
	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_uom, "Nos");
	assert.equal(row.custom_conversion_factor, 1);
	assert.equal(row.custom_qty_after, 24.0);
	assert.equal(row.custom_valuation_rate_per_uom, 10);
	assert.equal(row.qty, 24);
	assert.equal(row.valuation_rate, 10);
});

test("F3: item change resets obsolete custom metadata and seeds/syncs for new item", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	// Row was previously Item A with Pack factor 12: qty 24, rate 10, after 2, rate_per_uom 120
	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-A",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_before: 2.0,
		custom_qty_after: 2.0,
		custom_valuation_rate_per_uom: 120,
		qty: 24,
		valuation_rate: 10,
	};

	// Item B db get_value returns default UOM "Pack"
	env.frappe.db.get_value = async (doctype, itemCode, fields) => {
		if (itemCode === "ITEM-B") {
			return { message: { custom_default_inventory_unit_of_measure: "Pack", stock_uom: "Nos" } };
		}
		return { message: {} };
	};

	env.setXcallHandler(async (method, args) => {
		if (args.item_code === "ITEM-B") {
			// Item B factor is 6: 24/6 = 4.0, rate 10 * 6 = 60
			return {
				custom_uom: "Pack",
				custom_conversion_factor: 6,
				custom_qty_before: 4.0,
				custom_qty_after: 4.0,
				custom_qty_difference_per_uom: 0.0,
				custom_valuation_rate_per_uom: 60,
				qty: 24,
				valuation_rate: 10,
			};
		}
		return {};
	});

	// User changes item_code to ITEM-B (native fetch keeps qty=24, valuation_rate=10)
	env.locals[cdt][cdn].item_code = "ITEM-B";
	await env.childHandlers.item_code(env.frm, cdt, cdn);
	await new Promise((r) => setTimeout(r, 20));

	const row = env.locals[cdt][cdn];
	assert.equal(row.item_code, "ITEM-B");
	assert.equal(row.custom_uom, "Pack");
	assert.equal(row.custom_conversion_factor, 6);
	assert.equal(row.custom_qty_after, 4.0);
	assert.equal(row.custom_valuation_rate_per_uom, 60);
	assert.equal(row.qty, 24);
	assert.equal(row.valuation_rate, 10);
});

test("F3: out-of-order default lookup does not overwrite newer item", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-A",
		warehouse: "Stores - RR",
		qty: 10,
		valuation_rate: 5,
	};

	let resolveItemA;
	const itemAPromise = new Promise((resolve) => {
		resolveItemA = resolve;
	});

	env.frappe.db.get_value = (doctype, itemCode) => {
		if (itemCode === "ITEM-A") {
			return itemAPromise;
		}
		if (itemCode === "ITEM-B") {
			return Promise.resolve({
				message: { custom_default_inventory_unit_of_measure: "Box", stock_uom: "Nos" },
			});
		}
		return Promise.resolve({ message: {} });
	};

	env.setXcallHandler(async (method, args) => ({
		custom_uom: args.uom,
		custom_conversion_factor: 1,
		custom_qty_before: 10,
		custom_qty_after: 10,
		qty: 10,
		valuation_rate: 5,
	}));

	// User selects ITEM-A first
	const p1 = env.childHandlers.item_code(env.frm, cdt, cdn);

	// Then immediately switches to ITEM-B before ITEM-A resolves
	env.locals[cdt][cdn].item_code = "ITEM-B";
	const p2 = env.childHandlers.item_code(env.frm, cdt, cdn);
	await p2;
	await new Promise((r) => setTimeout(r, 10));

	// Now Item B should have its UOM "Box"
	assert.equal(env.locals[cdt][cdn].item_code, "ITEM-B");
	assert.equal(env.locals[cdt][cdn].custom_uom, "Box");

	// Item A now resolves out-of-order with UOM "Pack"
	resolveItemA({
		message: { custom_default_inventory_unit_of_measure: "Pack", stock_uom: "Nos" },
	});
	await p1;
	await new Promise((r) => setTimeout(r, 10));

	// Item B's UOM must NOT be overwritten by Item A's "Pack"
	assert.equal(env.locals[cdt][cdn].item_code, "ITEM-B");
	assert.equal(env.locals[cdt][cdn].custom_uom, "Box");
});

test("F2: UOM transition with native 0 valuation_rate, allow_zero=1, current_valuation_rate=10 retains 0", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_before: 2.0,
		custom_qty_after: 2.0,
		custom_valuation_rate_per_uom: 0,
		qty: 24,
		valuation_rate: 0,
		current_valuation_rate: 10,
		allow_zero_valuation_rate: 1,
	};

	env.setXcallHandler(async (method, args) => {
		assert.equal(args.uom, "Nos");
		assert.equal(args.qty_after, undefined);
		assert.equal(args.rate_per_uom, undefined);
		assert.equal(args.valuation_rate, 0);
		assert.equal(args.allow_zero_valuation_rate, 1);
		assert.equal(args.qty, 24);

		return {
			custom_uom: "Nos",
			custom_conversion_factor: 1,
			custom_qty_before: 24.0,
			custom_qty_after: 24.0,
			custom_qty_difference_per_uom: 0.0,
			custom_valuation_rate_per_uom: 0,
			qty: 24,
			valuation_rate: 0,
		};
	});

	// User edits custom_uom to Nos
	env.locals[cdt][cdn].custom_uom = "Nos";
	await env.childHandlers.custom_uom(env.frm, cdt, cdn);
	await new Promise((r) => setTimeout(r, 10));

	assert.equal(env.xcallCalls.length, 1);
	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_uom, "Nos");
	assert.equal(row.custom_conversion_factor, 1);
	assert.equal(row.custom_qty_after, 24.0);
	assert.equal(row.custom_valuation_rate_per_uom, 0);
	assert.equal(row.qty, 24);
	assert.equal(row.valuation_rate, 0);
});

test("reversed_responses_drops_older_token", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_before: 1.0,
		custom_qty_after: 1.0,
		qty: 12,
	};

	let resolveOld;
	const oldPromise = new Promise((resolve) => {
		resolveOld = resolve;
	});

	let callCount = 0;
	env.setXcallHandler((method, args) => {
		callCount++;
		if (callCount === 1) {
			return oldPromise;
		}
		return Promise.resolve({
			custom_uom: "Pack",
			custom_conversion_factor: 12,
			custom_qty_before: 1.0,
			custom_qty_after: 2.0,
			custom_qty_difference_per_uom: 1.0,
			custom_valuation_rate_per_uom: 120,
			qty: 24,
			custom_count_confirmation: "token_newer_2",
		});
	});

	// Request 1: custom_qty_after edit to 1.5
	env.locals[cdt][cdn].custom_qty_after = 1.5;
	env.childHandlers.custom_qty_after(env.frm, cdt, cdn);
	assert.equal(env.xcallCalls.length, 1);

	// Request 2: user quickly types custom_qty_after to 2.0
	env.locals[cdt][cdn].custom_qty_after = 2.0;
	await env.childHandlers.custom_qty_after(env.frm, cdt, cdn);
	assert.equal(env.xcallCalls.length, 2);

	const row = env.locals[cdt][cdn];
	assert.equal(row.qty, 24);
	assert.equal(row.custom_qty_after, 2.0);
	assert.equal(row.custom_count_confirmation, "token_newer_2");

	// Old request 1 resolves late with token_older_1
	resolveOld({
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_before: 1.0,
		custom_qty_after: 1.5,
		custom_qty_difference_per_uom: 0.5,
		custom_valuation_rate_per_uom: 120,
		qty: 18,
		custom_count_confirmation: "token_older_1",
	});
	await new Promise((r) => setTimeout(r, 20));

	// Newer values and newer token MUST survive
	assert.equal(row.qty, 24);
	assert.equal(row.custom_qty_after, 2.0);
	assert.equal(row.custom_count_confirmation, "token_newer_2");
});

test("same_value_zero_dom_input sends explicit 0 and acquires confirmation", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_before: 1.0,
		custom_qty_after: "",
		qty: null,
	};

	env.setXcallHandler(async (method, args) => {
		assert.equal(args.qty_after, 0);
		return {
			custom_uom: "Pack",
			custom_conversion_factor: 12,
			custom_qty_before: 1.0,
			custom_qty_after: 0,
			custom_qty_difference_per_uom: -1.0,
			custom_valuation_rate_per_uom: 120,
			qty: 0,
			valuation_rate: 10,
			custom_count_confirmation: "token_zero_confirmed",
		};
	});

	await env.frappe.model.set_value(cdt, cdn, "custom_qty_after", 0);
	await new Promise((r) => setTimeout(r, 10));

	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_qty_after, 0);
	assert.equal(row.qty, 0);
	assert.equal(row.custom_count_confirmation, "token_zero_confirmed");
});

test("active_editor_save flushes editor, waits for sync promise, and validates", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_before: 1.0,
		custom_qty_after: "",
		qty: null,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];

	let resolveSync;
	const syncPromise = new Promise((resolve) => {
		resolveSync = resolve;
	});
	env.setXcallHandler(() => syncPromise);

	// User types 5.0 into editor and sync is dispatched
	env.locals[cdt][cdn].custom_qty_after = 5.0;
	env.childHandlers.custom_qty_after(env.frm, cdt, cdn);

	// User immediately hits Save, triggering frm validate
	let validateFinished = false;
	const valPromise = env.frm.trigger("validate").then(() => {
		validateFinished = true;
	});

	// Active editor was blurred
	assert.equal(env.activeElementBlurCalls.length, 1);
	// Validate should still be waiting on the pending sync promise
	assert.equal(validateFinished, false);

	// Sync finishes with confirmed token
	resolveSync({
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_before: 1.0,
		custom_qty_after: 5.0,
		custom_qty_difference_per_uom: 4.0,
		custom_valuation_rate_per_uom: 120,
		qty: 60,
		valuation_rate: 10,
		custom_count_confirmation: "token_save_5",
	});

	await valPromise;
	assert.equal(validateFinished, true);
	assert.equal(env.frappe.validated, true);
	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_count_confirmation, "token_save_5");
});

test("uncounted_row_blocks_save with descriptive message", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		idx: 1,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_after: "",
		custom_count_confirmation: null,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];

	await env.frm.trigger("validate");

	assert.equal(env.frappe.validated, false);
	assert.ok(env.msgprintCalls.length > 0);
	assert.match(env.msgprintCalls[0].message, /Qty After belum diisi/);
});

test("unconfirmed_row_blocks_save with descriptive message", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		idx: 1,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_after: 5.0,
		custom_count_confirmation: null,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];

	await env.frm.trigger("validate");

	assert.equal(env.frappe.validated, false);
	assert.ok(env.msgprintCalls.length > 0);
	assert.match(env.msgprintCalls[0].message, /Konfirmasi hitungan belum valid/);
});

test("context_change_invalidates_confirmation and preserves inputs", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_after: 10.0,
		custom_count_confirmation: "token_prior",
		qty: 120,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];

	// Changing posting_time
	env.frm.doc.posting_time = "12:00:00";
	await env.frm.trigger("posting_time");

	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_qty_after, 10.0);
	assert.equal(row.custom_uom, "Pack");
	assert.equal(row.custom_count_confirmation, null);
});

test("row_delete_and_re_add does not corrupt new row with old response", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn1 = "row1";
	const cdn2 = "row2";

	env.locals[cdt][cdn1] = {
		name: cdn1,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_after: 1.0,
	};

	let resolveRow1;
	const row1Promise = new Promise((resolve) => {
		resolveRow1 = resolve;
	});
	env.setXcallHandler(() => row1Promise);

	// Request for row1 starts
	env.childHandlers.custom_qty_after(env.frm, cdt, cdn1);
	assert.equal(env.xcallCalls.length, 1);

	// User deletes row1
	env.childHandlers.items_remove(env.frm, cdt, cdn1);
	delete env.locals[cdt][cdn1];

	// User adds row2 with different count 5.0
	env.locals[cdt][cdn2] = {
		name: cdn2,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_after: 5.0,
		qty: 60,
	};

	// Old row1 response resolves
	resolveRow1({
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_after: 1.0,
		qty: 12,
		custom_count_confirmation: "token_row1",
	});
	await new Promise((r) => setTimeout(r, 20));

	// row2 must remain unchanged
	assert.equal(env.locals[cdt][cdn2].qty, 60);
	assert.equal(env.locals[cdt][cdn2].custom_qty_after, 5.0);
	assert.equal(env.locals[cdt][cdn1], undefined);
});

test("form_navigation drops in-flight response when active form changed", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_after: 1.0,
		qty: 12,
	};

	let resolveSR1;
	const sr1Promise = new Promise((resolve) => {
		resolveSR1 = resolve;
	});
	env.setXcallHandler(() => sr1Promise);

	// Start request while form is SR-TEST
	env.childHandlers.custom_qty_after(env.frm, cdt, cdn);

	// User switches to another form
	env.frm.doc.name = "SR-ANOTHER";

	// Request resolves
	resolveSR1({
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_after: 1.0,
		qty: 999,
		custom_count_confirmation: "token_sr1",
	});
	await new Promise((r) => setTimeout(r, 20));

	// Response dropped, qty not updated to 999
	const row = env.locals[cdt][cdn];
	assert.equal(row.qty, 12);
	assert.equal(row.custom_count_confirmation, undefined);
});

test("submitted_and_cancelled_refresh is non-mutating", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_before: 1.0,
		custom_qty_after: 10.0,
		qty: 120,
		valuation_rate: 10,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];
	env.frm.doc.docstatus = 1; // Submitted

	env.setXcallHandler(async () => {
		assert.fail("No xcall allowed on submitted doc");
	});

	await env.frm.trigger("refresh");
	await new Promise((r) => setTimeout(r, 10));

	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_qty_after, 10.0);
	assert.equal(row.qty, 120);
	assert.equal(env.xcallCalls.length, 0);

	// Same for cancelled
	env.frm.doc.docstatus = 2;
	await env.frm.trigger("refresh");
	assert.equal(env.xcallCalls.length, 0);
});

test("posting_mode_headline_indicator explains now vs explicit mode", async () => {
	const env = setupEnvironment();

	// Mode 0: now
	env.frm.doc.set_posting_time = 0;
	await env.frm.trigger("refresh");
	assert.equal(env.frm.dashboard.headline_indicator, "green");
	assert.match(env.frm.dashboard.headline, /Waktu Nyata \(now\)/);

	// Mode 1: explicit
	env.frm.doc.set_posting_time = 1;
	await env.frm.trigger("refresh");
	assert.equal(env.frm.dashboard.headline_indicator, "blue");
	assert.match(env.frm.dashboard.headline, /Waktu Spesifik/);
});

test("finding_1_warehouse_change_on_unconfirmed_zero_row_does_not_confirm", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		custom_qty_after: 0,
		custom_count_confirmation: null,
		qty: null,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];

	// User only changes warehouse
	env.locals[cdt][cdn].warehouse = "Finished Goods - RR";
	await env.childHandlers.warehouse(env.frm, cdt, cdn);
	await new Promise((r) => setTimeout(r, 20));

	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_count_confirmation, null, "Warehouse change must not generate confirmation token");
	assert.equal(row.qty, null, "Warehouse change must not derive qty 0 without explicit count");
});

test("finding_2_posting_time_change_leaves_confirmation_invalid_until_explicit_action", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		custom_qty_after: 1056,
		custom_count_confirmation: "token_at_10am",
		qty: 6336,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];
	env.frm.doc.set_posting_time = 1;
	env.frm.doc.posting_time = "10:00:00";

	// User changes posting_time to 12:00:00
	env.frm.doc.posting_time = "12:00:00";
	await env.frm.trigger("posting_time");
	await new Promise((r) => setTimeout(r, 20));

	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_qty_after, 1056, "Visible count must be preserved");
	assert.equal(row.custom_count_confirmation, null, "Confirmation must be invalidated and NOT auto-reacquired");

	// Save attempt without reconfirming must be blocked
	env.frappe.validated = true;
	await env.formHandlers.validate[0](env.frm);
	assert.equal(env.frappe.validated, false, "Save must be blocked when confirmation was invalidated by time change");
});

test("finding_3_uom_change_preserves_visible_qty_after", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		custom_qty_after: 1056,
		custom_count_confirmation: "token123",
		qty: 6336,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];

	env.setXcallHandler(async (method, args) => {
		if (method === "warehouse_app.warehouse_app.stock_reconciliation.compute_row") {
			return {
				custom_uom: args.uom,
				custom_conversion_factor: 12,
				custom_qty_before: 500,
				custom_qty_after: null,
				custom_qty_difference_per_uom: null,
				qty: null,
				custom_count_confirmation: null,
			};
		}
		return {};
	});

	// User changes custom_uom to Box
	env.locals[cdt][cdn].custom_uom = "Box";
	await env.childHandlers.custom_uom(env.frm, cdt, cdn);
	await new Promise((r) => setTimeout(r, 20));

	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_qty_after, 1056, "Visible custom_qty_after must be preserved when UOM changes");
	assert.equal(row.custom_count_confirmation, null, "Confirmation must be cleared on UOM change");
});

test("finding_3_item_change_preserves_visible_qty_after", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		custom_qty_after: 1056,
		custom_count_confirmation: "token123",
		qty: 6336,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];

	// User changes item_code to ITEM-002
	env.locals[cdt][cdn].item_code = "ITEM-002";
	await env.childHandlers.item_code(env.frm, cdt, cdn);
	await new Promise((r) => setTimeout(r, 20));

	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_qty_after, 1056, "Item change must preserve visible custom_qty_after");
	assert.equal(row.custom_count_confirmation, null, "Item change must invalidate confirmation");
});

test("finding_5_input_change_during_save_barrier_aborts_save", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		custom_qty_after: 1056,
		custom_count_confirmation: "token_1056",
		qty: 6336,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];

	let resolveConversionA;
	const promiseA = new Promise((resolve) => {
		resolveConversionA = resolve;
	});
	env.setXcallHandler(() => promiseA);

	// Start sync for 1056
	env.childHandlers.custom_qty_after(env.frm, cdt, cdn);

	// Save barrier begins while sync is pending
	env.frappe.validated = true;
	const savePromise = env.formHandlers.validate[0](env.frm);

	// User modifies input to 2000 while Save is waiting
	env.locals[cdt][cdn].custom_qty_after = 2000;
	env.childHandlers.custom_qty_after(env.frm, cdt, cdn);

	// Resolve initial conversion
	resolveConversionA({
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		custom_qty_after: 1056,
		qty: 6336,
		custom_count_confirmation: "token_1056",
	});

	await savePromise;
	assert.equal(env.frappe.validated, false, "Save must abort if input changed while waiting for sync barrier");
});

test("finding_6_explicit_confirmation_action_for_unchanged_zero_count", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	// Draft reloaded with After 0 and empty confirmation
	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		custom_qty_after: 0,
		custom_count_confirmation: null,
		qty: null,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];

	env.setXcallHandler(async (method, args) => {
		if (method === "warehouse_app.warehouse_app.stock_reconciliation.compute_row") {
			return {
				custom_uom: "Pack",
				custom_conversion_factor: 6,
				custom_qty_before: 10,
				custom_qty_after: args.qty_after,
				custom_qty_difference_per_uom: -10,
				qty: 0,
				custom_count_confirmation: "zero_confirmed_token",
			};
		}
		return {};
	});

	// Trigger explicit confirmation action
	assert.ok(typeof env.frm.confirm_count_rows === "function", "frm.confirm_count_rows must be exposed");
	await env.frm.confirm_count_rows();
	await new Promise((r) => setTimeout(r, 20));

	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_count_confirmation, "zero_confirmed_token");
	assert.equal(row.qty, 0);

	// Now validate should pass
	env.frappe.validated = true;
	await env.formHandlers.validate[0](env.frm);
	assert.equal(env.frappe.validated, true);
});

test("finding_7_refresh_draft_does_not_add_custom_uom_to_native_row", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row_native";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: null,
		qty: 100,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];

	// Mock DB returns custom_default_inventory_unit_of_measure: "Pack" for ITEM-001
	env.frappe.db.get_value = () =>
		Promise.resolve({ message: { custom_default_inventory_unit_of_measure: "Pack", stock_uom: "Pcs" } });

	// Refresh draft
	await env.frm.trigger("refresh");
	await new Promise((r) => setTimeout(r, 20));

	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_uom, null, "Native row must NOT have custom_uom added on refresh");
});

test("finding_8_navigation_to_other_form_instance_drops_in_flight_response", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_after: 1.0,
		qty: 12,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];

	let resolveSR1;
	const sr1Promise = new Promise((resolve) => {
		resolveSR1 = resolve;
	});
	env.setXcallHandler(() => sr1Promise);

	// Start request on env.frm (SR-TEST)
	env.childHandlers.custom_qty_after(env.frm, cdt, cdn);

	// User navigates to a different form instance (cur_frm points to other form)
	const otherFrm = {
		doc: {
			name: "SR-OTHER",
			doctype: "Stock Reconciliation",
			items: [],
		},
	};
	env.setCurFrm(otherFrm);

	// Request for SR-TEST arrives
	resolveSR1({
		custom_uom: "Pack",
		custom_conversion_factor: 12,
		custom_qty_after: 1.0,
		qty: 999,
		custom_count_confirmation: "token_sr1",
	});
	await new Promise((r) => setTimeout(r, 20));

	// Response must be dropped because active form is now otherFrm
	const row = env.locals[cdt][cdn];
	assert.equal(row.qty, 12, "Response must not mutate document after navigation to another form instance");
	assert.equal(row.custom_count_confirmation, undefined);
});

test("finding_9_adapter_balance_callback_with_current_request_id_does_not_write_qty_or_after", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		stock_uom: "Pcs",
		custom_qty_before: 0,
		custom_qty_after: 1056,
		qty: 6336,
		valuation_rate: 10,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];

	await env.frm.trigger("setup");
	assert.equal(env.frm._sr_valuation_adapter_installed, true);
	// Before/difference come from compute_row (server precision), not from client rounding.
	env.setXcallHandler(async () => ({ custom_qty_before: 1051, custom_qty_difference_per_uom: 5, qty: 6336 }));

	// Trigger set_valuation_rate_and_qty on custom row
	env.frm.events.set_valuation_rate_and_qty(env.frm, cdt, cdn);
	assert.equal(env.pendingBalanceCalls.length, 1);
	const balanceCall = env.pendingBalanceCalls[0];

	// Execute balance callback WHILE request id is still current (no intervening edits)
	balanceCall.callback({
		message: {
			qty: 6306,
			rate: 10,
			serial_nos: null,
			use_serial_batch_fields: 1,
		},
	});
	await new Promise((r) => setTimeout(r, 20));

	// Verify that neither qty nor custom_qty_after were written by the callback
	const wroteQty = env.setValueCalls.some((c) => c.fieldname === "qty");
	const wroteAfter = env.setValueCalls.some((c) => c.fieldname === "custom_qty_after");
	assert.equal(wroteQty, false, "Balance callback must never write to qty on custom row");
	assert.equal(wroteAfter, false, "Balance callback must never write to custom_qty_after");

	// Verify allowed fields were updated
	const row = env.locals[cdt][cdn];
	assert.equal(row.current_qty, 6306);
	assert.equal(row.custom_qty_before, 1051);
	assert.equal(row.custom_qty_difference_per_uom, 5);
	assert.equal(row.custom_qty_after, 1056);
	assert.equal(row.qty, 6336);
});

test("defect_c_delegated_native_balance_callback_guards_row_that_became_custom", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: null,
		qty: null,
		valuation_rate: null,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];

	await env.frm.trigger("setup");

	// Call set_valuation_rate_and_qty while row is native
	env.frm.events.set_valuation_rate_and_qty(env.frm, cdt, cdn);
	assert.equal(env.pendingBalanceCalls.length, 1);
	const balanceCall = env.pendingBalanceCalls[0];

	// Before balance arrives, row becomes custom!
	env.locals[cdt][cdn].custom_uom = "Pack";
	env.locals[cdt][cdn].custom_conversion_factor = 6;
	env.locals[cdt][cdn].custom_qty_after = 10;
	env.locals[cdt][cdn].qty = 60;

	// Delayed native balance callback arrives with qty 100, rate 15
	balanceCall.callback({
		message: {
			qty: 100,
			rate: 15,
			serial_nos: null,
			use_serial_batch_fields: 1,
		},
	});
	await new Promise((r) => setTimeout(r, 20));

	// The callback must NOT write qty from native balance
	const nativeWroteQty = env.setValueCalls.some((c) => c.fieldname === "qty" && c.value === 100);
	assert.equal(nativeWroteQty, false, "Native callback must NOT be allowed to write qty on row that became custom");

	const row = env.locals[cdt][cdn];
	assert.equal(row.qty, 60, "Native balance callback must NOT overwrite qty once row became custom");
	assert.equal(row.custom_qty_after, 10, "After must remain untouched");
	assert.equal(row.current_qty, 100, "current_qty must be updated from balance");
});

test("defect_c_balance_callback_aborts_if_docstatus_is_submitted_or_cancelled", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		custom_qty_after: 10,
		qty: 60,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];

	await env.frm.trigger("setup");

	env.frm.events.set_valuation_rate_and_qty(env.frm, cdt, cdn);
	assert.equal(env.pendingBalanceCalls.length, 1);
	const balanceCall = env.pendingBalanceCalls[0];

	// Document is submitted or cancelled before callback arrives
	env.frm.doc.docstatus = 1;

	balanceCall.callback({
		message: {
			qty: 100,
			rate: 15,
			serial_nos: null,
			use_serial_batch_fields: 1,
		},
	});
	await new Promise((r) => setTimeout(r, 20));

	assert.equal(
		env.setValueCalls.length,
		0,
		"Callback must drop response without any mutations if docstatus > 0"
	);
});

test("defect_d_toggle_posting_time_mode_drops_old_response_from_reinstalling_token", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		custom_qty_after: 10,
		custom_count_confirmation: null,
		qty: 60,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];
	env.frm.doc.set_posting_time = 0;

	let resolveOld;
	const oldPromise = new Promise((resolve) => {
		resolveOld = resolve;
	});
	env.setXcallHandler(() => oldPromise);

	// Start sync under set_posting_time = 0
	env.childHandlers.custom_qty_after(env.frm, cdt, cdn);

	// User toggles set_posting_time to 1 then back to 0
	env.frm.doc.set_posting_time = 1;
	await env.frm.trigger("set_posting_time");
	env.frm.doc.set_posting_time = 0;
	await env.frm.trigger("set_posting_time");

	// Now old response from initial sync resolves
	resolveOld({
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		custom_qty_after: 10,
		qty: 60,
		custom_count_confirmation: "old_token_0",
	});
	await new Promise((r) => setTimeout(r, 20));

	const row = env.locals[cdt][cdn];
	assert.equal(
		row.custom_count_confirmation,
		null,
		"Old response must NOT reinstall confirmation token after toggle 0->1->0"
	);
});

test("defect_d_reload_of_same_named_doc_drops_pre_reload_response_by_object_identity", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	const oldDoc = env.frm.doc;
	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		custom_qty_after: 10,
		qty: 60,
	};
	oldDoc.items = [env.locals[cdt][cdn]];

	let resolveOld;
	const oldPromise = new Promise((resolve) => {
		resolveOld = resolve;
	});
	env.setXcallHandler(() => oldPromise);

	// Start sync on oldDoc
	env.childHandlers.custom_qty_after(env.frm, cdt, cdn);

	// Reload happens: same docname "SR-TEST", but new doc object instance
	const reloadedRow = { ...env.locals[cdt][cdn], custom_qty_after: 99, qty: 594, custom_count_confirmation: null };
	const newDoc = {
		name: "SR-TEST",
		doctype: "Stock Reconciliation",
		posting_date: "2026-11-03",
		posting_time: "10:00:00",
		set_posting_time: 0,
		docstatus: 0,
		company: "Test Company",
		items: [reloadedRow],
	};
	env.locals[cdt][cdn] = reloadedRow;
	env.frm.doc = newDoc;
	env.setCurFrm(env.frm);
	await env.frm.trigger("refresh");

	// Old response arrives
	resolveOld({
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		custom_qty_after: 10,
		qty: 60,
		custom_count_confirmation: "stale_token",
	});
	await new Promise((r) => setTimeout(r, 20));

	// New doc rows and locals must not be overwritten
	assert.equal(newDoc.items[0].custom_qty_after, 99);
	assert.equal(newDoc.items[0].qty, 594);
	assert.equal(reloadedRow.custom_qty_after, 99);
	assert.equal(reloadedRow.qty, 594);
	assert.equal(reloadedRow.custom_count_confirmation, null);
});

test("defect_e_confirm_unconfirmed_rows_reconfirms_stale_token_row", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		custom_qty_after: 10,
		custom_count_confirmation: "stale_token_due_to_factor_change",
		qty: 60,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];

	env.setXcallHandler(async (method, args) => {
		if (method === "warehouse_app.warehouse_app.stock_reconciliation.compute_row") {
			return {
				custom_uom: "Pack",
				custom_conversion_factor: 12,
				custom_qty_after: 10,
				qty: 120,
				custom_count_confirmation: "fresh_token_120",
			};
		}
		return {};
	});

	await env.frm.trigger("setup");
	await env.frm.confirm_count_rows();
	await new Promise((r) => setTimeout(r, 20));

	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_count_confirmation, "fresh_token_120", "Konfirmasi Hitungan must re-confirm stale token rows");
	assert.equal(row.qty, 120);
});

test("defect_e_company_change_invalidates_all_confirmations", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		custom_qty_after: 10,
		custom_count_confirmation: "valid_token_for_co1",
		qty: 60,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];

	// User changes company
	env.frm.doc.company = "Company 2";
	await env.frm.trigger("company");

	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_count_confirmation, null, "Company change must invalidate confirmations");
});

test("defect_f_clearing_uom_preserves_visible_after_and_blocks_save", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		custom_qty_after: 10,
		custom_count_confirmation: "token123",
		qty: 60,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];

	// User clears custom_uom
	env.locals[cdt][cdn].custom_uom = "";
	await env.childHandlers.custom_uom(env.frm, cdt, cdn);

	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_qty_after, 10, "Clearing UOM must preserve visible custom_qty_after");
	assert.equal(row.custom_count_confirmation, null, "Clearing UOM must clear confirmation token");

	// Attempt save: must be blocked because row has count without UOM
	env.frappe.validated = true;
	await env.formHandlers.validate[0](env.frm);
	assert.equal(env.frappe.validated, false, "Save must be blocked when row has count but no UOM");
	assert.match(env.msgprintCalls[env.msgprintCalls.length - 1].message, /UOM wajib diisi/);
});

function createMockGridInput({ rowName, fieldname, value, isFormView = false, onBlur = () => {} }) {
	const gridRow = {
		tagName: "DIV",
		className: "grid-row",
		attributes: { "data-name": rowName, "data-idx": "1" },
		getAttribute(attr) {
			return this.attributes[attr] || null;
		},
	};
	let container = gridRow;
	if (isFormView) {
		const formInGrid = {
			tagName: "DIV",
			className: "form-in-grid",
			attributes: {},
			getAttribute(attr) {
				return this.attributes[attr] || null;
			},
			parent: gridRow,
		};
		container = formInGrid;
	} else {
		const dataRow = {
			tagName: "DIV",
			className: "data-row row m-0",
			attributes: {},
			getAttribute(attr) {
				return this.attributes[attr] || null;
			},
			parent: gridRow,
		};
		const col = {
			tagName: "DIV",
			className: "col grid-static-col",
			attributes: { "data-fieldname": fieldname, "data-fieldtype": "Float" },
			getAttribute(attr) {
				return this.attributes[attr] || null;
			},
			parent: dataRow,
		};
		container = col;
	}
	const ctrl = {
		tagName: "DIV",
		className: "frappe-control",
		attributes: { "data-fieldname": fieldname, "data-fieldtype": "Float" },
		getAttribute(attr) {
			return this.attributes[attr] || null;
		},
		parent: container,
	};
	const input = {
		tagName: "INPUT",
		className: "input-with-feedback form-control",
		value: value,
		attributes: {},
		getAttribute(attr) {
			return this.attributes[attr] || null;
		},
		blur: onBlur,
		parent: ctrl,
		closest(selector) {
			let curr = this;
			while (curr) {
				if (selector === ".grid-row" && curr.className && curr.className.includes("grid-row")) return curr;
				if (selector === ".frappe-control" && curr.className && curr.className.includes("frappe-control")) return curr;
				if (selector === "[data-fieldname]" && curr.attributes && curr.attributes["data-fieldname"]) return curr;
				curr = curr.parent;
			}
			return null;
		},
	};
	return input;
}

test("defect_a_unflushed_count_editor_in_inline_grid_aborts_save", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		custom_qty_after: 5,
		custom_count_confirmation: null,
		qty: 30,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];

	let resolveSync5;
	const sync5Promise = new Promise((resolve) => {
		resolveSync5 = resolve;
	});
	env.setXcallHandler(() => sync5Promise);

	// Start sync for 5
	env.childHandlers.custom_qty_after(env.frm, cdt, cdn);

	await env.frm.trigger("setup");

	// Real DOM inline grid editor: data-name is on .grid-row, data-fieldname is on column/control, NOT on input!
	const editorInput = createMockGridInput({
		rowName: cdn,
		fieldname: "custom_qty_after",
		value: "6",
		isFormView: false,
		onBlur: () => {
			env.activeElementBlurCalls.push(true);
		},
	});
	env.setActiveElement(editorInput);
	env.triggerInputEvent(editorInput);

	// Sync for 5 resolves while 6 was typed
	resolveSync5({
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		custom_qty_after: 5,
		qty: 30,
		custom_count_confirmation: "token_for_5",
	});

	// Save is attempted without prior blur
	env.frappe.validated = true;
	await env.formHandlers.validate[0](env.frm);

	// Save must NOT pass with model 5 and token 5!
	assert.equal(env.frappe.validated, false, "Save must abort when inline grid count editor has unflushed value differing from model");
});

test("defect_a_unflushed_count_editor_in_row_form_aborts_save", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		custom_qty_after: 5,
		custom_count_confirmation: null,
		qty: 30,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];

	let resolveSync5;
	const sync5Promise = new Promise((resolve) => {
		resolveSync5 = resolve;
	});
	env.setXcallHandler(() => sync5Promise);

	env.childHandlers.custom_qty_after(env.frm, cdt, cdn);
	await env.frm.trigger("setup");

	// Real DOM row form editor
	const formInput = createMockGridInput({
		rowName: cdn,
		fieldname: "custom_qty_after",
		value: "7",
		isFormView: true,
		onBlur: () => {
			env.activeElementBlurCalls.push(true);
		},
	});
	env.setActiveElement(formInput);
	env.triggerInputEvent(formInput);

	resolveSync5({
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		custom_qty_after: 5,
		qty: 30,
		custom_count_confirmation: "token_for_5",
	});

	env.frappe.validated = true;
	await env.formHandlers.validate[0](env.frm);

	assert.equal(env.frappe.validated, false, "Save must abort when row form count editor has unflushed value differing from model");
});

test("regression_native_scan_mode_skips_qty_write", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: null, // native row!
		qty: 5,
		valuation_rate: 10,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];
	env.frm.doc.scan_mode = 1; // scan_mode is ON

	await env.frm.trigger("setup");

	env.frm.events.set_valuation_rate_and_qty(env.frm, cdt, cdn);
	assert.equal(env.pendingBalanceCalls.length, 1);
	const balanceCall = env.pendingBalanceCalls[0];

	// Balance response arrives with qty 100
	balanceCall.callback({
		message: {
			qty: 100,
			rate: 15,
			serial_nos: null,
			use_serial_batch_fields: 1,
		},
	});
	await new Promise((r) => setTimeout(r, 20));

	const wroteQty = env.setValueCalls.some((c) => c.fieldname === "qty");
	assert.equal(wroteQty, false, "Native scan_mode must skip writing qty");
	assert.equal(env.locals[cdt][cdn].qty, 5, "Existing qty must remain unchanged under scan_mode");
});

test("regression_native_serial_or_bundle_row_fetches_stock_balance", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		custom_uom: null, // native row!
		serial_no: "SR-001,SR-002", // native serial item
		qty: 2,
		valuation_rate: 10,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];

	await env.frm.trigger("setup");

	env.frm.events.set_valuation_rate_and_qty(env.frm, cdt, cdn);
	assert.equal(
		env.pendingBalanceCalls.length,
		1,
		"Native serial or bundle row without custom UOM must fetch stock balance on warehouse/balance events"
	);
});

test("native_serial_item_does_not_autofill_custom_uom", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-SN-001",
		warehouse: "Stores - RR",
		custom_uom: null,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];

	// Mock db.get_value returning serialized item without custom default UOM
	env.frappe.db.get_value = (dt, name, fields) => {
		return Promise.resolve({
			message: {
				stock_uom: "Pcs",
				custom_default_inventory_unit_of_measure: null,
				has_serial_no: 1,
			},
		});
	};

	await env.frm.trigger("setup");
	await env.childHandlers.item_code(env.frm, cdt, cdn);
	await new Promise((r) => setTimeout(r, 20));

	assert.equal(
		env.locals[cdt][cdn].custom_uom || "",
		"",
		"Native serial item must not auto-fill custom_uom (fallback to stock UOM must be blocked)"
	);
});

test("native_serial_item_with_configured_default_uom_does_not_autofill_custom_uom", async () => {
	const env = setupEnvironment();
	const cdt = "Stock Reconciliation Item";
	const cdn = "row1";

	env.locals[cdt][cdn] = {
		name: cdn,
		doctype: cdt,
		item_code: "ITEM-SN-002",
		warehouse: "Stores - RR",
		custom_uom: null,
	};
	env.frm.doc.items = [env.locals[cdt][cdn]];

	// Mock db.get_value returning serialized item WITH custom default UOM configured
	env.frappe.db.get_value = (dt, name, fields) => {
		return Promise.resolve({
			message: {
				stock_uom: "Nos",
				custom_default_inventory_unit_of_measure: "Box",
				has_serial_no: 1,
			},
		});
	};

	await env.frm.trigger("setup");
	await env.childHandlers.item_code(env.frm, cdt, cdn);
	await new Promise((r) => setTimeout(r, 20));

	assert.equal(
		env.locals[cdt][cdn].custom_uom || "",
		"",
		"Native serial item must not auto-fill custom_uom even if default inventory UOM is configured"
	);
});


// ---------------------------------------------------------------------------
// Round 5: seam equivalence, native->custom transitions, persisted-zero native
// rows, typed-value snapshot barrier, per-row qty/rate protection.
// ---------------------------------------------------------------------------

const R5_CDT = "Stock Reconciliation Item";
const tick = () => new Promise((r) => setTimeout(r, 20));
const flt = (v) => (v == null || v === "" ? 0 : Number(v));

function r5_newRow(overrides = {}) {
	return {
		name: "row1",
		doctype: R5_CDT,
		idx: 1,
		item_code: "ITEM-001",
		warehouse: "Stores - RR",
		batch_no: null,
		qty: 5,
		valuation_rate: 10,
		...overrides,
	};
}

function r5_balanceResponse() {
	return { message: { qty: 6306, rate: 12.5, serial_nos: null, use_serial_batch_fields: 1 } };
}

// The installed native callback (fixture) writes these fields in this order.
function r5_writes(env) {
	return env.setValueCalls.map((c) => [c.fieldname, c.value]);
}

test("r4_seam_adapter_request_and_writes_match_native_callback", async () => {
	for (const scan_mode of [0, 1]) {
		for (const purpose of ["Stock Reconciliation", "Opening Stock"]) {
			// Baseline: installed native script only, no app script.
			const native_env = setupEnvironment({ appScript: false });
			native_env.frm.doc.scan_mode = scan_mode;
			native_env.frm.doc.purpose = purpose;
			native_env.locals[R5_CDT].row1 = r5_newRow();
			native_env.frm.doc.items = [native_env.locals[R5_CDT].row1];
			native_env.frm.events.set_valuation_rate_and_qty(native_env.frm, R5_CDT, "row1");
			assert.equal(native_env.pendingBalanceCalls.length, 1);
			const nativeCall = native_env.pendingBalanceCalls[0];
			const nativeArgs = { ...nativeCall.args };
			delete nativeArgs.row;
			nativeCall.callback(r5_balanceResponse());
			await tick();

			// Adapter: same row, same doc context, same balance response.
			const env = setupEnvironment();
			env.frm.doc.scan_mode = scan_mode;
			env.frm.doc.purpose = purpose;
			env.locals[R5_CDT].row1 = r5_newRow();
			env.frm.doc.items = [env.locals[R5_CDT].row1];
			await env.frm.trigger("setup");
			assert.equal(env.frm._sr_valuation_adapter_installed, true);
			env.frm.events.set_valuation_rate_and_qty(env.frm, R5_CDT, "row1");
			assert.equal(env.pendingBalanceCalls.length, 1);
			const call = env.pendingBalanceCalls[0];
			const args = { ...call.args };
			delete args.row;

			const label = `scan_mode=${scan_mode} purpose=${purpose}`;
			assert.equal(call.method, nativeCall.method, `method mismatch (${label})`);
			assert.deepEqual(args, nativeArgs, `request args mismatch (${label})`);
			assert.equal(
				call.args.row === env.locals[R5_CDT].row1,
				nativeCall.args.row === native_env.locals[R5_CDT].row1,
				`row arg identity mismatch (${label})`
			);

			call.callback(r5_balanceResponse());
			await tick();

			assert.deepEqual(r5_writes(env), r5_writes(native_env), `set_value sequence mismatch (${label})`);
			assert.deepEqual(
				env.locals[R5_CDT].row1,
				native_env.locals[R5_CDT].row1,
				`resulting row mismatch (${label})`
			);
		}
	}
});

test("r4_seam_adapter_never_reassigns_frappe_call", async () => {
	const env = setupEnvironment();
	let reassignments = 0;
	const original = env.frappe.call;
	Object.defineProperty(env.frappe, "call", {
		configurable: true,
		get: () => original,
		set: () => {
			reassignments++;
		},
	});

	env.locals[R5_CDT].row1 = r5_newRow();
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	await env.frm.trigger("setup");

	// native row -> adapter issues its own request and applies native writes
	env.frm.events.set_valuation_rate_and_qty(env.frm, R5_CDT, "row1");
	// custom row -> adapter issues its own request too
	env.locals[R5_CDT].row1.custom_uom = "Pack";
	env.locals[R5_CDT].row1.custom_conversion_factor = 6;
	env.frm.events.set_valuation_rate_and_qty(env.frm, R5_CDT, "row1");

	for (const call of env.pendingBalanceCalls) {
		call.callback(r5_balanceResponse());
	}
	await tick();

	assert.equal(reassignments, 0, "adapter must never reassign the global frappe.call");
	assert.equal(env.frappe.call, original);
	assert.equal(env.pendingBalanceCalls.length, 2, "adapter must issue the balance request itself for both rows");
});

test("p2_late_native_balance_after_custom_transition_and_warehouse_change_writes_nothing", async () => {
	const env = setupEnvironment();
	env.locals[R5_CDT].row1 = r5_newRow({ warehouse: "WH-1" });
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	await env.frm.trigger("setup");

	env.frm.events.set_valuation_rate_and_qty(env.frm, R5_CDT, "row1");
	assert.equal(env.pendingBalanceCalls.length, 1);
	const wh1Call = env.pendingBalanceCalls[0];
	assert.equal(wh1Call.args.warehouse, "WH-1");

	// The row becomes a counted row and its warehouse changes before the WH-1 reply lands.
	const row = env.locals[R5_CDT].row1;
	row.custom_uom = "Pack";
	row.custom_conversion_factor = 6;
	row.custom_qty_after = 100;
	row.qty = 600;
	row.warehouse = "WH-2";

	wh1Call.callback({ message: { qty: 594, rate: 10, serial_nos: null, use_serial_batch_fields: 1 } });
	await tick();

	assert.equal(row.current_qty, undefined, "stale WH-1 balance must not populate current_qty");
	assert.equal(row.custom_qty_before, undefined, "stale WH-1 balance must not become the WH-2 Before value");
	assert.equal(row.qty, 600, "stale balance must not overwrite the derived native qty");
	assert.equal(row.warehouse, "WH-2");
});

test("p2_in_order_native_to_custom_transition_applies_custom_update", async () => {
	const env = setupEnvironment();
	env.locals[R5_CDT].row1 = r5_newRow();
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	await env.frm.trigger("setup");

	env.frm.events.set_valuation_rate_and_qty(env.frm, R5_CDT, "row1");
	assert.equal(env.pendingBalanceCalls.length, 1);
	const call = env.pendingBalanceCalls[0];

	// Row becomes counted with unchanged document/row context before the reply lands.
	const row = env.locals[R5_CDT].row1;
	row.custom_uom = "Pack";
	row.custom_conversion_factor = 6;
	row.custom_qty_after = 100;
	row.qty = 600;
	// Before/difference come from compute_row (server precision), not from client rounding.
	env.setXcallHandler(async () => ({ custom_qty_before: 99, custom_qty_difference_per_uom: 1, qty: 600 }));

	call.callback({ message: { qty: 594, rate: 10, serial_nos: null, use_serial_batch_fields: 1 } });
	await tick();

	assert.equal(row.current_qty, 594, "custom update must apply the balance");
	assert.equal(row.custom_qty_before, 99, "Before must be balance / factor");
	assert.equal(row.custom_qty_difference_per_uom, 1);
	assert.equal(row.qty, 600, "custom update must not overwrite the derived native qty");
	assert.equal(
		env.setValueCalls.some((c) => c.fieldname === "qty"),
		false,
		"native qty write must never happen once the row is counted"
	);
});

test("p2_balance_response_dropped_when_row_object_replaced", async () => {
	const env = setupEnvironment();
	env.locals[R5_CDT].row1 = r5_newRow();
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	await env.frm.trigger("setup");

	env.frm.events.set_valuation_rate_and_qty(env.frm, R5_CDT, "row1");
	const call = env.pendingBalanceCalls[0];

	// Row object replaced under the same name (re-add / rebuild of the grid).
	env.locals[R5_CDT].row1 = r5_newRow({ qty: 7 });
	call.callback(r5_balanceResponse());
	await tick();

	assert.equal(env.locals[R5_CDT].row1.current_qty, undefined);
	assert.equal(env.locals[R5_CDT].row1.qty, 7);
});

test("p1_persisted_zero_after_on_native_row_passes_validate", async () => {
	const env = setupEnvironment();
	// A saved native-only draft reloads with custom_qty_after sanitized to 0 by the Float field.
	env.locals[R5_CDT].row1 = r5_newRow({ custom_uom: "", custom_qty_after: 0, qty: 5 });
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	await env.frm.trigger("setup");

	const result = await env.triggerSave("Save");
	assert.equal(result.validated, true, "persisted 0 on an untouched native row must not block Save");
	assert.equal(env.msgprintCalls.length, 0);
});

test("p1_persisted_null_after_on_native_row_passes_validate", async () => {
	const env = setupEnvironment();
	env.locals[R5_CDT].row1 = r5_newRow({ custom_uom: "", custom_qty_after: null, qty: 5 });
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	await env.frm.trigger("setup");

	const result = await env.triggerSave("Save");
	assert.equal(result.validated, true, "an uncounted native row must not require a UOM");
	assert.equal(env.msgprintCalls.length, 0);
});

test("p1_typed_nonzero_after_without_uom_blocks_validate", async () => {
	const env = setupEnvironment();
	env.locals[R5_CDT].row1 = r5_newRow({ custom_uom: "", custom_qty_after: null, qty: 5 });
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	await env.frm.trigger("setup");

	env.locals[R5_CDT].row1.custom_qty_after = 5;
	const result = await env.triggerSave("Save");

	assert.equal(result.validated, false);
	assert.match(env.msgprintCalls[env.msgprintCalls.length - 1].message, /UOM wajib diisi/);
});

test("p1_typed_zero_after_without_uom_blocks_validate", async () => {
	const env = setupEnvironment();
	env.locals[R5_CDT].row1 = r5_newRow({ custom_uom: "", custom_qty_after: null, qty: 5 });
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	await env.frm.trigger("setup");

	// User explicitly types 0 into After for this row of this form session.
	const editor = createMockGridInput({
		rowName: "row1",
		fieldname: "custom_qty_after",
		value: "0",
		isFormView: true,
		onBlur: () => {},
	});
	env.setActiveElement(editor);
	env.triggerInputEvent(editor);
	env.locals[R5_CDT].row1.custom_qty_after = 0;
	env.childHandlers.custom_qty_after(env.frm, R5_CDT, "row1");

	env.setActiveElement({ tagName: "BODY" });
	const result = await env.triggerSave("Save");

	assert.equal(result.validated, false, "an explicitly typed 0 count must still require a UOM");
	assert.match(env.msgprintCalls[env.msgprintCalls.length - 1].message, /UOM wajib diisi/);
});

test("r3a_typed_after_with_focus_left_save_aborts", async () => {
	const env = setupEnvironment();
	env.locals[R5_CDT].row1 = r5_newRow({
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		custom_qty_after: 5,
		custom_count_confirmation: "token_for_5",
		qty: 30,
	});
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	await env.frm.trigger("setup");

	// Typed but the editor never blurred: the raw value lives only in the DOM/snapshot.
	const editor = createMockGridInput({
		rowName: "row1",
		fieldname: "custom_qty_after",
		value: "6",
		isFormView: false,
		onBlur: () => {},
	});
	env.setActiveElement(editor);
	env.triggerInputEvent(editor);
	// Focus moves to the Save button without committing the editor.
	env.setActiveElement({ tagName: "BUTTON", blur: () => {} });

	const result = await env.triggerSave("Save");

	assert.equal(result.validated, false, "Save must abort while a typed count differs from the model");
	assert.equal(env.msgprintCalls[env.msgprintCalls.length - 1].title, "Perubahan Input Terdeteksi");
});

test("r3a_typed_after_with_focus_left_submit_aborts", async () => {
	const env = setupEnvironment();
	env.locals[R5_CDT].row1 = r5_newRow({
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		custom_qty_after: 5,
		custom_count_confirmation: "token_for_5",
		qty: 30,
	});
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	await env.frm.trigger("setup");

	const editor = createMockGridInput({
		rowName: "row1",
		fieldname: "custom_qty_after",
		value: "7",
		isFormView: true,
		onBlur: () => {},
	});
	env.setActiveElement(editor);
	env.triggerInputEvent(editor);
	env.setActiveElement({ tagName: "BUTTON", blur: () => {} });

	const result = await env.triggerSave("Submit");

	assert.equal(result.action, "Submit");
	assert.equal(result.validated, false, "Submit must abort while a typed count differs from the model");
	assert.equal(env.msgprintCalls[env.msgprintCalls.length - 1].title, "Perubahan Input Terdeteksi");
});

test("r3a_typed_rate_with_focus_left_save_aborts", async () => {
	const env = setupEnvironment();
	env.locals[R5_CDT].row1 = r5_newRow({
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		custom_qty_after: 5,
		custom_valuation_rate_per_uom: 60,
		custom_count_confirmation: "token_for_5",
		qty: 30,
	});
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	await env.frm.trigger("setup");

	const editor = createMockGridInput({
		rowName: "row1",
		fieldname: "custom_valuation_rate_per_uom",
		value: "75",
		isFormView: false,
		onBlur: () => {},
	});
	env.setActiveElement(editor);
	env.triggerInputEvent(editor);
	env.setActiveElement({ tagName: "BUTTON", blur: () => {} });

	const result = await env.triggerSave("Save");

	assert.equal(result.validated, false, "Save must abort while a typed rate differs from the model");
	assert.equal(env.msgprintCalls[env.msgprintCalls.length - 1].title, "Perubahan Input Terdeteksi");
});

test("r3a_committed_typed_value_does_not_abort_save", async () => {
	const env = setupEnvironment();
	env.locals[R5_CDT].row1 = r5_newRow({
		custom_uom: "Pack",
		custom_conversion_factor: 6,
		custom_qty_after: 5,
		custom_count_confirmation: "token_for_6",
		qty: 36,
	});
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	await env.frm.trigger("setup");

	const editor = createMockGridInput({
		rowName: "row1",
		fieldname: "custom_qty_after",
		value: "6",
		isFormView: false,
		onBlur: () => {},
	});
	env.setActiveElement(editor);
	env.triggerInputEvent(editor);
	// Blur commits 6 to the model, then focus leaves.
	await env.frappe.model.set_value(R5_CDT, "row1", "custom_qty_after", 6);
	env.setActiveElement({ tagName: "BODY" });

	const result = await env.triggerSave("Save");

	assert.equal(result.validated, true, "a committed typed value must not block Save");
	assert.equal(env.msgprintCalls.length, 0);
});

test("p2_qty_columns_not_hidden_and_custom_rows_locked_per_row", async () => {
	const env = setupEnvironment();
	env.locals[R5_CDT].row1 = r5_newRow({ custom_uom: "Pack", custom_conversion_factor: 6, custom_qty_after: 5, qty: 30 });
	env.locals[R5_CDT].row2 = r5_newRow({ name: "row2", idx: 2, custom_uom: "", custom_qty_after: 0, qty: 5 });
	env.frm.doc.items = [env.locals[R5_CDT].row1, env.locals[R5_CDT].row2];
	const locks = [];
	env.frm.set_df_property = (table, prop, value, docname, field, row) => locks.push([row, field, value]);

	await env.frm.trigger("refresh");
	await env.frm.trigger("items_on_form_rendered");

	const overrides = env.frm.fields_dict.items.grid.column_disp_overrides;
	assert.equal(overrides.qty, undefined, "qty column must not be hidden for the whole grid");
	assert.equal(overrides.valuation_rate, undefined, "valuation_rate column must not be hidden for the whole grid");

	const lock = (row, field) => locks.filter((l) => l[0] === row && l[1] === field).pop()?.[2];
	assert.equal(lock("row1", "qty"), 1, "counted rows keep qty read-only");
	assert.equal(lock("row1", "valuation_rate"), 1, "counted rows keep valuation_rate read-only");
	assert.equal(lock("row2", "qty"), 0, "native rows must keep qty editable");
	assert.equal(lock("row2", "valuation_rate"), 0, "native rows must keep valuation_rate editable");
});

// ---------------------------------------------------------------------------
// Round 6: R5-1 posting refresh on native rows, R5-2 per-row docfield lock,
// R5-3 Float expressions parsed by the native control.
// ---------------------------------------------------------------------------

test("r6_posting_date_change_refreshes_native_row_balance", async () => {
	const env = setupEnvironment();
	env.locals[R5_CDT].row1 = r5_newRow();
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	await env.frm.trigger("setup");

	// Native posting_date handler (fixture) requests balances first, then the app handler runs.
	env.frm.doc.posting_date = "2020-01-01";
	await env.frm.trigger("posting_date");
	assert.equal(env.pendingBalanceCalls.length, 1, "native posting trigger must request the balance");
	assert.equal(env.pendingBalanceCalls[0].args.posting_date, "2020-01-01");

	env.pendingBalanceCalls[0].callback({ message: { qty: 0, rate: 0, serial_nos: null, use_serial_batch_fields: 1 } });
	await tick();
	assert.equal(env.locals[R5_CDT].row1.current_qty, 0, "balance for the new posting date must be applied");
});

test("r6_posting_date_change_still_drops_balance_requested_for_old_date", async () => {
	const env = setupEnvironment();
	env.locals[R5_CDT].row1 = r5_newRow();
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	await env.frm.trigger("setup");

	env.frm.events.set_valuation_rate_and_qty(env.frm, R5_CDT, "row1");
	const old_call = env.pendingBalanceCalls[0];
	env.frm.doc.posting_date = "2020-01-01";
	await env.frm.trigger("posting_date");
	old_call.callback(r5_balanceResponse());
	await tick();
	assert.equal(env.locals[R5_CDT].row1.current_qty, undefined, "balance for the old date must be dropped");
});

test("r6_counted_row_lock_uses_per_row_docfield", async () => {
	const env = setupEnvironment();
	const calls = [];
	env.frm.set_df_property = (...args) => calls.push(args);
	env.locals[R5_CDT].row1 = r5_newRow({ custom_uom: "Pack", custom_conversion_factor: 6, custom_qty_after: 5, qty: 30 });
	env.locals[R5_CDT].row2 = r5_newRow({ name: "row2", idx: 2, custom_uom: "" });
	env.frm.doc.items = [env.locals[R5_CDT].row1, env.locals[R5_CDT].row2];

	await env.frm.trigger("refresh");

	// frm.set_df_property(table, prop, value, docname, table_field, row) edits the row's docfield copy,
	// which grid_row.make_control reads when it creates an editor later.
	const lock = (row, field) =>
		calls.find((c) => c[0] === "items" && c[1] === "read_only" && c[4] === field && c[5] === row);
	assert.equal(lock("row1", "qty")?.[2], 1);
	assert.equal(lock("row1", "valuation_rate")?.[2], 1);
	assert.equal(lock("row2", "qty")?.[2], 0);
	assert.equal(lock("row2", "valuation_rate")?.[2], 0);
	assert.equal(lock("row1", "qty")[3], "SR-TEST");
});

function r6_expressionEditor(rowName, value) {
	const editor = createMockGridInput({ rowName, fieldname: "custom_qty_after", value, isFormView: false });
	// Native ControlFloat.parse evaluates expressions such as "2+3" before committing.
	editor.parent.fieldobj = { parse: (v) => (v === "2+3" ? 5 : Number(v)) };
	return editor;
}

test("r6_committed_float_expression_does_not_block_save", async () => {
	const env = setupEnvironment();
	env.locals[R5_CDT].row1 = r5_newRow({
		custom_uom: "Pack", custom_conversion_factor: 6, custom_qty_after: 5,
		custom_count_confirmation: "token_for_5", qty: 30,
	});
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	await env.frm.trigger("setup");

	const editor = r6_expressionEditor("row1", "2+3");
	env.setActiveElement(editor);
	env.triggerInputEvent(editor);
	env.setActiveElement({ tagName: "BODY" });

	const result = await env.triggerSave("Submit");
	assert.equal(result.validated, true, "committed expression value 5 must not block Submit");
});

test("r6_uncommitted_float_expression_still_blocks_save", async () => {
	const env = setupEnvironment();
	env.locals[R5_CDT].row1 = r5_newRow({
		custom_uom: "Pack", custom_conversion_factor: 6, custom_qty_after: 4,
		custom_count_confirmation: "token_for_4", qty: 24,
	});
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	await env.frm.trigger("setup");

	const editor = r6_expressionEditor("row1", "2+3");
	env.setActiveElement(editor);
	env.triggerInputEvent(editor);
	env.setActiveElement({ tagName: "BODY" });

	const result = await env.triggerSave("Save");
	assert.equal(result.validated, false, "expression value 5 differs from model 4 and must block Save");
});

test("r6_balance_before_factor_known_never_seeds_rate_with_factor_1", async () => {
	const env = setupEnvironment();
	let resolveSync;
	env.setXcallHandler(() => new Promise((r) => (resolveSync = r)));
	// UOM chosen before the warehouse: factor still unknown when the balance reply lands.
	env.locals[R5_CDT].row1 = r5_newRow({ custom_uom: "Pack", custom_conversion_factor: "", qty: null, valuation_rate: null });
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	await env.frm.trigger("setup");

	// The warehouse change runs the native handler (balance request) and the app handler (compute_row).
	env.childHandlers.warehouse(env.frm, R5_CDT, "row1");
	env.pendingBalanceCalls[env.pendingBalanceCalls.length - 1].callback({ message: { qty: 6336, rate: 1000, serial_nos: null, use_serial_batch_fields: 1 } });
	await tick();
	const row = env.locals[R5_CDT].row1;
	assert.ok(is_unset(row.custom_valuation_rate_per_uom), "rate per UOM must not be seeded while the factor is unknown");

	// The follow-up compute_row carries the stock-UOM rate seed, so the server derives the per-UOM
	// rate with the real factor (rate_per_uom = valuation_rate x factor).
	const follow = env.xcallCalls[env.xcallCalls.length - 1];
	assert.equal(follow.method, "warehouse_app.warehouse_app.stock_reconciliation.compute_row");
	assert.equal(follow.args.valuation_rate, 1000);
	assert.ok(is_unset(follow.args.rate_per_uom));
	assert.ok(is_unset(row.custom_qty_before), "Before must not be computed with factor 1");
});

function is_unset(v) {
	return v == null || v === "";
}

test("r6_factor_unknown_preserves_explicit_rate_per_uom", async () => {
	const env = setupEnvironment();
	env.setXcallHandler(() => new Promise(() => {}));
	env.locals[R5_CDT].row1 = r5_newRow({
		custom_uom: "Pack", custom_conversion_factor: "", custom_valuation_rate_per_uom: 7200,
		qty: null, valuation_rate: null,
	});
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	await env.frm.trigger("setup");

	env.childHandlers.warehouse(env.frm, R5_CDT, "row1");
	env.pendingBalanceCalls[env.pendingBalanceCalls.length - 1].callback({ message: { qty: 6336, rate: 1000, serial_nos: null, use_serial_batch_fields: 1 } });
	await tick();

	const row = env.locals[R5_CDT].row1;
	assert.equal(row.custom_valuation_rate_per_uom, 7200, "explicit rate per UOM must be kept");
	assert.ok(is_unset(row.valuation_rate), "balance rate must not override an explicit per-UOM rate");
	const follow = env.xcallCalls[env.xcallCalls.length - 1];
	assert.equal(follow.args.rate_per_uom, 7200, "compute_row derives valuation_rate from the explicit per-UOM rate");
});

// ---------------------------------------------------------------------------
// Round 6b: shared precision contract (no client-side hardcoded rounding) and
// stale compute_row rejection after a context change.
// ---------------------------------------------------------------------------

test("r6b_balance_with_known_factor_uses_server_precision_and_keeps_rate", async () => {
	const env = setupEnvironment();
	// Server precision for this site is non-default (4 decimals): the client must not round itself.
	env.setXcallHandler(async (method, args) => ({
		custom_conversion_factor: 6,
		custom_qty_before: 1050.1667,
		custom_qty_difference_per_uom: 5.8333,
		custom_valuation_rate_per_uom: 6000.024,
		qty: 6336,
		valuation_rate: args.valuation_rate,
		custom_count_confirmation: null,
	}));
	env.locals[R5_CDT].row1 = r5_newRow({
		custom_uom: "Pack", custom_conversion_factor: 6, custom_qty_after: 1056, qty: 6336, valuation_rate: null,
	});
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	await env.frm.trigger("setup");

	env.frm.events.set_valuation_rate_and_qty(env.frm, R5_CDT, "row1");
	env.pendingBalanceCalls[0].callback({ message: { qty: 6301, rate: 1000.004, serial_nos: null, use_serial_batch_fields: 1 } });
	await tick();

	const row = env.locals[R5_CDT].row1;
	const client_rounded = env.setValueCalls.filter(
		(c) => ["custom_qty_before", "custom_qty_difference_per_uom", "custom_valuation_rate_per_uom"].includes(c.fieldname)
			&& [1050.167, 5.833, 6000.02].includes(c.value)
	);
	assert.deepEqual(client_rounded, [], "client must not write values rounded with hardcoded precision");
	const follow = env.xcallCalls[env.xcallCalls.length - 1];
	assert.equal(follow.method, "warehouse_app.warehouse_app.stock_reconciliation.compute_row");
	assert.equal(follow.args.valuation_rate, 1000.004, "stock-UOM rate seed goes to the server unrounded");
	assert.equal(row.custom_qty_before, 1050.1667);
	assert.equal(row.custom_valuation_rate_per_uom, 6000.024);
	assert.equal(row.valuation_rate, 1000.004, "rate round-trip must not change valuation");
	assert.equal(row.qty, 6336);
});

test("r6b_stale_compute_row_rejection_after_context_change_is_ignored", async () => {
	const env = setupEnvironment();
	let rejectOld;
	env.setXcallHandler(() => new Promise((_, reject) => (rejectOld = reject)));
	env.locals[R5_CDT].row1 = r5_newRow({ custom_uom: "Pack", custom_conversion_factor: 6, custom_qty_after: 1056, qty: 6336 });
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	await env.frm.trigger("setup");

	env.frappe.model.set_value(R5_CDT, "row1", "custom_qty_after", 1056);
	await tick();
	// Company change: the native script issues no balance request, so request ids stay unchanged.
	env.frm.doc.company = "Other Co";
	await env.frm.trigger("company");
	// A token issued for the new context without a new compute_row (e.g. save reply synced in place).
	env.locals[R5_CDT].row1.custom_count_confirmation = "token-new-context";
	const before_msgs = env.msgprintCalls.length;

	rejectOld(new Error("old context failure"));
	await tick();

	assert.equal(env.locals[R5_CDT].row1.custom_count_confirmation, "token-new-context", "stale rejection must not clear a newer token");
	assert.equal(env.msgprintCalls.length, before_msgs, "stale rejection must not show an error for the old context");
});

// ---------------------------------------------------------------------------
// Round 7: M4 stale typed snapshot after a model-only revert (native Undo),
// M5 per-row qty/rate lock after bulk fill and after item-change reset.
// ---------------------------------------------------------------------------

const COMPUTE_ROW = "warehouse_app.warehouse_app.stock_reconciliation.compute_row";

test("m4_undo_to_confirmed_value_does_not_block_save", async () => {
	const env = setupEnvironment();
	env.locals[R5_CDT].row1 = r5_newRow({
		custom_uom: "Pack", custom_conversion_factor: 6, custom_qty_after: 5,
		custom_count_confirmation: "token_for_5", qty: 30,
	});
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	env.setXcallHandler(async (method, args) => ({
		custom_uom: args.uom,
		custom_conversion_factor: 6,
		custom_qty_after: args.qty_after,
		custom_valuation_rate_per_uom: null,
		qty: flt(args.qty_after) * 6,
		custom_count_confirmation: "token_for_" + args.qty_after,
	}));
	await env.frm.trigger("setup");

	// User types 6 and the editor commits it (blur): model 6, snapshot 6.
	env.locals[R5_CDT].row1.custom_qty_after = 6;
	const editor = createMockGridInput({ rowName: "row1", fieldname: "custom_qty_after", value: "6" });
	env.setActiveElement(editor);
	env.triggerInputEvent(editor);
	env.setActiveElement({ tagName: "BODY" });
	await env.childHandlers.custom_qty_after(env.frm, R5_CDT, "row1");
	await tick();
	assert.equal(env.locals[R5_CDT].row1.custom_qty_after, 6, "committed model value is 6");
	assert.equal(env.locals[R5_CDT].row1.custom_count_confirmation, "token_for_6");

	// Native Undo restores model After to the confirmed 5 via set_value (no DOM input event).
	await env.frappe.model.set_value(R5_CDT, "row1", "custom_qty_after", 5);
	await tick();
	env.setActiveElement({ tagName: "BODY" });

	const result = await env.triggerSave("Save");

	assert.equal(result.validated, true, "a model value matching the snapshot must not block Save");
	assert.equal(env.msgprintCalls.length, 0);
});

test("m4_typed_uncommitted_value_still_blocks_save", async () => {
	const env = setupEnvironment();
	env.locals[R5_CDT].row1 = r5_newRow({
		custom_uom: "Pack", custom_conversion_factor: 6, custom_qty_after: 5,
		custom_count_confirmation: "token_for_5", qty: 30,
	});
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	env.setXcallHandler(async (method, args) => ({
		custom_uom: args.uom,
		custom_conversion_factor: 6,
		custom_qty_after: args.qty_after,
		qty: flt(args.qty_after) * 6,
		custom_count_confirmation: "token_for_" + args.qty_after,
	}));
	await env.frm.trigger("setup");

	// Operator types 6 without blurring (Ctrl+S path); the model still holds 5.
	const editor = createMockGridInput({ rowName: "row1", fieldname: "custom_qty_after", value: "6" });
	env.setActiveElement(editor);
	env.triggerInputEvent(editor);
	env.setActiveElement({ tagName: "BODY" });

	const result = await env.triggerSave("Save");

	assert.equal(result.validated, false, "text typed but not committed must still abort Save");
	assert.equal(env.msgprintCalls[env.msgprintCalls.length - 1].title, "Perubahan Input Terdeteksi");
});

test("m4_input_typed_during_inflight_sync_still_blocks_save", async () => {
	const env = setupEnvironment();
	env.locals[R5_CDT].row1 = r5_newRow({
		custom_uom: "Pack", custom_conversion_factor: 6, custom_qty_after: 5,
		custom_count_confirmation: "token_for_5", qty: 30,
	});
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	let resolveSync;
	env.setXcallHandler(() => new Promise((resolve) => (resolveSync = resolve)));
	await env.frm.trigger("setup");

	env.childHandlers.custom_qty_after(env.frm, R5_CDT, "row1");
	// The user types 7 while the reply for 5 is still in flight.
	const editor = createMockGridInput({ rowName: "row1", fieldname: "custom_qty_after", value: "7" });
	env.setActiveElement(editor);
	env.triggerInputEvent(editor);
	env.setActiveElement({ tagName: "BODY" });
	resolveSync({ custom_qty_after: 5, qty: 30 });
	await tick();

	const result = await env.triggerSave("Save");

	assert.equal(result.validated, false, "input typed during an in-flight sync must still block Save");
	assert.equal(env.msgprintCalls[env.msgprintCalls.length - 1].title, "Perubahan Input Terdeteksi");
});

test("m5_item_change_to_native_row_unlocks_qty_and_rate", async () => {
	const env = setupEnvironment();
	const locks = [];
	env.frm.set_df_property = (table, prop, value, docname, field, row) => locks.push([row, field, value]);
	env.locals[R5_CDT].row1 = r5_newRow({
		custom_uom: "Pack", custom_conversion_factor: 6, custom_qty_after: 5,
		custom_count_confirmation: "token_for_5", qty: 30,
	});
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	await env.frm.trigger("refresh");
	locks.length = 0;

	// Item changes to a native (non-serial) item: the reset clears custom_uom.
	env.locals[R5_CDT].row1.item_code = "ITEM-002";
	await env.childHandlers.item_code(env.frm, R5_CDT, "row1");
	await tick();

	assert.equal(env.locals[R5_CDT].row1.custom_uom, "", "reset must clear custom_uom");
	const lock = (field) => locks.filter((l) => l[0] === "row1" && l[1] === field).pop()?.[2];
	assert.equal(lock("qty"), 0, "a row that became native must unlock qty");
	assert.equal(lock("valuation_rate"), 0, "a row that became native must unlock valuation_rate");
});

test("m5_import_bulk_fill_locks_custom_rows", async () => {
	const env = setupEnvironment();
	const locks = [];
	env.frm.set_df_property = (table, prop, value, docname, field, row) => locks.push([row, field, value]);
	env.setCallHandler((opts) => {
		if ((opts.method || "").endsWith("upload_stock_count")) {
			opts.callback({
				message: {
					added: 1,
					rows: [
						{
							item_code: "ITEM-001",
							warehouse: "Stores - RR",
							custom_uom: "Pack",
							custom_conversion_factor: 6,
							custom_qty_after: 5,
							qty: 30,
							valuation_rate: 10,
							custom_count_confirmation: "token_for_5",
						},
					],
				},
			});
		}
	});
	await env.frm.trigger("refresh");

	env.customButtons["Import Stock Count"]();
	const d = env.dialogCalls[env.dialogCalls.length - 1];
	d.set_value("warehouse", "Stores - RR");
	d.opts.fields.find((f) => f.fieldname === "upload_btn").click();
	env.fileUploaderCalls[env.fileUploaderCalls.length - 1].opts.on_success({
		name: "count.xlsx",
		dataurl: "data:text/csv;base64,eA==",
	});
	await tick();

	const rows = env.frm.doc.items;
	assert.equal(rows.length, 1, "import must fill the grid");
	assert.equal(rows[0].custom_uom, "Pack");
	const lock = (field) => locks.filter((l) => l[0] === rows[0].name && l[1] === field).pop()?.[2];
	assert.equal(lock("qty"), 1, "an imported custom row must lock qty");
	assert.equal(lock("valuation_rate"), 1, "an imported custom row must lock valuation_rate");
});


test("m4_same_value_retype_then_undo_does_not_block_save", async () => {
	const env = setupEnvironment();
	env.locals[R5_CDT].row1 = r5_newRow({
		custom_uom: "Pack", custom_conversion_factor: 6, custom_qty_after: 5,
		custom_count_confirmation: "token_for_5", qty: 30,
	});
	env.frm.doc.items = [env.locals[R5_CDT].row1];
	env.setXcallHandler(async (method, args) => ({
		custom_uom: args.uom,
		custom_conversion_factor: 6,
		custom_qty_after: args.qty_after,
		custom_valuation_rate_per_uom: null,
		qty: flt(args.qty_after) * 6,
		custom_count_confirmation: "token_for_" + args.qty_after,
	}));
	await env.frm.trigger("setup");

	// Commit 6 normally.
	env.locals[R5_CDT].row1.custom_qty_after = 6;
	const editor = createMockGridInput({ rowName: "row1", fieldname: "custom_qty_after", value: "6" });
	env.setActiveElement(editor);
	env.triggerInputEvent(editor);
	env.setActiveElement({ tagName: "BODY" });
	await env.childHandlers.custom_qty_after(env.frm, R5_CDT, "row1");
	await tick();

	// Re-type a value that parses to the same 6; native skips the no-op commit (no field handler).
	const retype = createMockGridInput({ rowName: "row1", fieldname: "custom_qty_after", value: "6" });
	env.setActiveElement(retype);
	env.triggerInputEvent(retype);
	env.setActiveElement({ tagName: "BODY" });

	// Native Undo back to the confirmed 5 via set_value.
	await env.frappe.model.set_value(R5_CDT, "row1", "custom_qty_after", 5);
	await tick();
	env.setActiveElement({ tagName: "BODY" });

	const result = await env.triggerSave("Save");
	assert.equal(result.validated, true, "a no-op retype must not leave a snapshot that blocks Save after Undo");
	assert.equal(env.msgprintCalls.length, 0);
});
