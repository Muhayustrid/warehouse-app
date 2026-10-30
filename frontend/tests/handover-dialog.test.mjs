import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'

import { fmtNum, fmtUomQty } from '../src/lib/format.js'

const require = createRequire(import.meta.url)
const { parse, compileScript } = require('@vue/compiler-sfc')

const plain = (v) => JSON.parse(JSON.stringify(v))

function loadDialog(name, rows = [{ name: 'WO', production_item: 'ITEM', company: 'COMPANY' }]) {
	const file = new URL(`../src/components/${name}.vue`, import.meta.url)
	const { descriptor } = parse(readFileSync(file, 'utf8'))
	const compiled = compileScript(descriptor, { id: 'dialog-test' }).content
	const context = {
		ref: (value) => ({ value }),
		computed: (fn) => ({ get value() { return fn() } }),
		watch() {}, nextTick() {}, _useModel: () => ({ value: true }),
		_mergeModels: (a, b) => ({ ...a, ...b }),
		createGroupRequest: async () => { context.calls++; return { material_request: 'MR' } },
		createRequest: async () => { context.calls++; return { material_request: 'MR' } },
		previewHandoverRequest: async () => ({}), fmtNum, fmtUomQty, calls: 0,
	}
	vm.createContext(context)
	vm.runInContext(compiled.replace(/^import .*$/gm, '').replace('export default', 'globalThis.component ='), context)
	const state = context.component.setup({ rows }, { expose() {}, emit() {} })
	return { state, context, descriptor }
}

for (const name of ['RequestDialog', 'GroupRequestDialog']) {
	test(`${name} refuses submit without a successful preview`, async () => {
		const { state, context } = loadDialog(name)
		await state.submit()
		assert.equal(context.calls, 0)
	})
}

test('RequestDialog never groups same-item rows from different companies', async () => {
	const rows = ['A', 'B'].map((company) => ({ name: `WO-${company}`, production_item: 'ITEM', company }))
	const { state, context } = loadDialog('RequestDialog', rows)
	context.createGroupRequest = async () => { throw new Error('must not group') }
	state.preview.value = { allocations: rows.map((r) => ({ work_order: r.name, allocated_qty: 1, fingerprint: r.name })) }
	context.previewHandoverRequest = async (names) => ({ allocations: names.map((n) => ({ work_order: n, allocated_qty: 1, fingerprint: n })) })
	await state.submit()
	assert.equal(context.calls, 2)
	assert.equal(state.failList.value.length, 0)
})

test('both dialogs disclose unresolved-source reservations without inventing a source', () => {
	for (const name of ['RequestDialog', 'GroupRequestDialog']) {
		const { descriptor } = loadDialog(name)
		assert.ok(descriptor.template.content.includes('unresolved_reservations'), name)
		assert.ok(descriptor.template.content.includes('Gudang asal belum diketahui'), name)
	}
})

test('fmtUomQty converts stock qty to the display UOM and never relabels without a valid factor', () => {
	const r = { stock_uom: 'Pcs', display_uom: 'Pack', display_conversion_factor: 12 }
	assert.equal(fmtUomQty(468, r), '39 Pack · 468 Pcs')
	assert.equal(fmtUomQty(21, { ...r, display_conversion_factor: 0 }), '21 Pcs')
	assert.equal(fmtUomQty(21, { stock_uom: 'Pcs', display_uom: 'Pcs', display_conversion_factor: 1 }), '21 Pcs')
})

test('both dialogs show allocations in the display UOM (Pack) with stock qty as sub', () => {
	const rows = ['A1', 'A2'].map((name) => ({
		name, production_item: 'A', company: 'C', stock_uom: 'Pcs', display_uom: 'Pack', display_conversion_factor: 12,
	}))
	const preview = { allocations: rows.map((r) => ({ work_order: r.name, allocated_qty: 24, unrequested_remainder: 12 })) }
	const bulk = loadDialog('RequestDialog', rows).state
	bulk.preview.value = preview
	assert.equal(bulk.rowQty(rows[0]), '2 Pack · 24 Pcs (sisa 1 Pack · 12 Pcs)')
	const group = loadDialog('GroupRequestDialog', rows).state
	group.preview.value = preview
	assert.equal(group.qtyLabel(group.total.value), '4 Pack · 48 Pcs')
})

test('RequestDialog submits a mixed-item selection per item with that item\'s own preview fingerprint', async () => {
	const row = (name, item) => ({ name, production_item: item, company: 'C' })
	const rows = [row('A1', 'A'), row('B1', 'B'), row('A2', 'A')]
	const { state, context } = loadDialog('RequestDialog', rows)
	const alloc = (names) => names.map((n) => ({ work_order: n, allocated_qty: 5, fingerprint: `wo:${n}` }))
	state.preview.value = { fingerprint: 'all', allocations: alloc(['A1', 'B1', 'A2']) }
	const calls = []
	context.previewHandoverRequest = async (names) => ({ fingerprint: `fp:${names.join(',')}`, allocations: alloc(names) })
	context.createGroupRequest = async (names, allocs, fp) => { calls.push(['group', names, allocs, fp]); return { material_request: 'MR-A' } }
	context.createRequest = async (name, qty, fp) => { calls.push(['single', name, qty, fp]); return { material_request: 'MR-B' } }
	await state.submit()
	assert.deepEqual(JSON.parse(JSON.stringify(calls)), [
		['group', ['A1', 'A2'], { A1: 5, A2: 5 }, 'fp:A1,A2'],
		['single', 'B1', 5, 'wo:B1'],
	])
	assert.deepEqual(plain(state.failList.value), [])
	assert.deepEqual(plain(state.okList.value), ['MR-A (A1, A2)', 'MR-B (B1)'])
	assert.equal(state.title.value, 'Request created')
})

test('RequestDialog refuses a partition whose fresh allocation differs from what the user confirmed', async () => {
	const rows = [{ name: 'A1', production_item: 'A', company: 'C' }, { name: 'B1', production_item: 'B', company: 'C' }]
	const { state, context } = loadDialog('RequestDialog', rows)
	state.preview.value = { allocations: rows.map((r) => ({ work_order: r.name, allocated_qty: 5 })) }
	context.previewHandoverRequest = async (names) => ({ allocations: names.map((n) => ({ work_order: n, allocated_qty: n === 'A1' ? 3 : 5 })) })
	await state.submit()
	assert.equal(context.calls, 1)
	assert.deepEqual(plain(state.failList.value.map((f) => f.wo)), ['A1'])
	assert.deepEqual(plain(state.okList.value), ['MR (B1)'])
})

test('call() returns message even when the response also carries _server_messages', async () => {
	const src = readFileSync(new URL('../src/lib/api.js', import.meta.url), 'utf8')
	const body = JSON.stringify({ message: { material_request: 'MR-1' }, _server_messages: '["{}"]' })
	const context = {
		window: { csrf_token: 't' }, URLSearchParams, ensureCSRFToken: async () => false,
		fetch: async () => ({ ok: true, text: async () => body }),
	}
	vm.createContext(context)
	vm.runInContext(src.replace(/^import .*$/gm, '').replace(/^export /gm, '') + '\nglobalThis.call = call', context)
	assert.deepEqual(plain(await context.call('x')), { material_request: 'MR-1' })
})
