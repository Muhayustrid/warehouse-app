import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'

const require = createRequire(import.meta.url)
const { parse, compileScript } = require('@vue/compiler-sfc')

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
		previewHandoverRequest: async () => ({}), fmtNum: String, calls: 0,
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

test('GroupRequestDialog displays stock-UOM allocation rather than relabelling it as display UOM', () => {
	const { state } = loadDialog('GroupRequestDialog')
	state.preview.value = { groups: [{ stock_uom: 'Nos' }], allocations: [{ allocated_qty: 21, unrequested_remainder: 4 }] }
	assert.equal(state.uom.value, 'Nos')
})
