// Test runner for W23 Stock Reconciliation client script
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const scriptCode = fs.readFileSync(process.env.SR_SCRIPT, "utf8");

function setupEnvironment() {
	const childHandlers = {};
	const formHandlers = {};
	const setValueCalls = [];
	const xcallCalls = [];

	let xcallHandler = async (method, args) => ({});

	const locals = {
		"Stock Reconciliation Item": {},
		"Stock Reconciliation": {},
	};

	const frm = {
		doc: {
			name: "SR-TEST",
			posting_date: "2026-11-03",
			posting_time: "10:00:00",
			items: [],
		},
		fields_dict: {
			items: {
				grid: {
					column_disp_overrides: {},
					set_column_disp: () => {},
					set_column_disp_in_list_view: () => {},
				},
			},
		},
	};

	const frappe = {
		user: {
			has_role: () => true,
		},
		ui: {
			form: {
				on(doctype, handlers) {
					if (doctype === "Stock Reconciliation Item") {
						Object.assign(childHandlers, handlers);
					} else if (doctype === "Stock Reconciliation") {
						Object.assign(formHandlers, handlers);
					}
				},
			},
		},
		model: {
			set_value(cdt, cdn, fieldname, value) {
				if (!locals[cdt]) locals[cdt] = {};
				if (!locals[cdt][cdn]) locals[cdt][cdn] = {};
				locals[cdt][cdn][fieldname] = value;
				setValueCalls.push({ cdt, cdn, fieldname, value });
				if (cdt === "Stock Reconciliation Item" && childHandlers[fieldname]) {
					return Promise.resolve().then(() =>
						childHandlers[fieldname](frm, cdt, cdn)
					);
				}
				return Promise.resolve();
			},
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

	const __ = (text, args) => {
		if (!args) return text;
		let res = text;
		args.forEach((val, i) => {
			res = res.replace(`{${i}}`, val);
		});
		return res;
	};

	const sandbox = {
		frappe,
		locals,
		flt,
		__,
		console,
		setTimeout,
		clearTimeout,
		Promise,
		Math,
		Object,
		Set,
		Map,
	};

	vm.createContext(sandbox);
	vm.runInContext(scriptCode, sandbox);

	return {
		childHandlers,
		formHandlers,
		setValueCalls,
		xcallCalls,
		locals,
		frm,
		frappe,
		setXcallHandler: (fn) => {
			xcallHandler = fn;
		},
	};
}

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

test("barcode +1 resyncs without ping-pong", async () => {
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
		assert.equal(args.qty, 13);
		assert.equal(args.qty_after, 1.083);

		return {
			custom_uom: "Pack",
			custom_conversion_factor: 12,
			custom_qty_before: 1.0,
			custom_qty_after: 1.083,
			custom_qty_difference_per_uom: 0.083,
			custom_valuation_rate_per_uom: 120,
			qty: 13,
			valuation_rate: 10,
		};
	});

	// Barcode scan bumps native qty 12 -> 13
	env.setValueCalls.length = 0;
	await env.frappe.model.set_value(cdt, cdn, "qty", 13);

	// Let all chained promises resolve
	await new Promise((r) => setTimeout(r, 10));

	assert.equal(env.xcallCalls.length, 1);
	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_qty_after, 1.083);
	assert.equal(row.qty, 13);

	// Verify reply qty: 13 produces no further set_value("qty")
	const qtySetCalls = env.setValueCalls.filter((c) => c.fieldname === "qty");
	assert.equal(qtySetCalls.length, 1); // Only the initial barcode scan set_value
});

test("endpoint rejection clears custom_uom", async () => {
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
		qty: 12,
	};

	env.setXcallHandler(async () => {
		throw new Error("Invalid UOM");
	});

	await env.frappe.model.set_value(cdt, cdn, "custom_qty_after", 2.0);
	await new Promise((r) => setTimeout(r, 10));

	const row = env.locals[cdt][cdn];
	assert.equal(row.custom_uom, "");
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
	assert.equal(row.custom_qty_after, "");
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

test("barcode qty13 retains 13 with exactly one call", async () => {
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
		return {
			custom_uom: "Pack",
			custom_conversion_factor: 12,
			custom_qty_before: 1.0,
			custom_qty_after: 1.083,
			custom_qty_difference_per_uom: 0.083,
			custom_valuation_rate_per_uom: 120,
			qty: 13,
			valuation_rate: 10,
		};
	});

	await env.frappe.model.set_value(cdt, cdn, "qty", 13);
	await new Promise((r) => setTimeout(r, 20));

	assert.equal(env.xcallCalls.length, 1);
	const row = env.locals[cdt][cdn];
	assert.equal(row.qty, 13);
	assert.equal(row.custom_qty_after, 1.083);
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
