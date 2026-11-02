import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'

const require = createRequire(import.meta.url)
const { parse, compileScript } = require('@vue/compiler-sfc')

function loadInventoryModule(contextOverrides = {}) {
	const src = readFileSync(new URL('../src/data/inventory.js', import.meta.url), 'utf8')
	const context = {
		URLSearchParams,
		setTimeout,
		clearTimeout,
		callGet: async () => ({}),
		...contextOverrides,
	}
	vm.createContext(context)
	vm.runInContext(
		src.replace(/^import .*$/gm, '').replace(/^export /gm, '') +
			'\nglobalThis.downloadExport = downloadExport;\nglobalThis.fetchFilterOptions = fetchFilterOptions;',
		context,
	)
	return context
}

test('downloadExport attaches anchor to DOM and defers URL revocation safely', async () => {
	let appendCalled = false
	let removeCalled = false
	let clickCalled = false
	let revokeCalls = []
	let anchorInDocAtClick = false

	const fakeAnchor = {
		href: '',
		download: '',
		click() {
			clickCalled = true
			if (appendCalled && !removeCalled) {
				anchorInDocAtClick = true
			}
		},
		remove() {
			removeCalled = true
		},
	}

	const context = loadInventoryModule({
		document: {
			createElement(tag) {
				assert.equal(tag, 'a')
				return fakeAnchor
			},
			body: {
				appendChild(el) {
					assert.equal(el, fakeAnchor)
					appendCalled = true
				},
			},
		},
		URL: {
			createObjectURL(blob) {
				return 'blob:mock-url-123'
			},
			revokeObjectURL(url) {
				revokeCalls.push(url)
			},
		},
		fetch: async (url) => ({
			ok: true,
			status: 200,
			headers: {
				get(name) {
					if (name === 'Content-Disposition') return 'attachment; filename="Stock_Cards.xlsx"'
					return null
				},
			},
			blob: async () => ({ size: 1024, type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }),
		}),
	})

	await context.downloadExport({ kind: 'cards', file_format: 'xlsx' })

	assert.ok(appendCalled, 'anchor must be appended to document.body')
	assert.ok(clickCalled, 'anchor click must be called')
	assert.ok(removeCalled, 'anchor must be removed after click')
	assert.ok(anchorInDocAtClick, 'anchor must be in document when clicked')
	assert.equal(revokeCalls.length, 0, 'revokeObjectURL must NOT be called synchronously')
})

test('downloadExport preserves server error reporting', async () => {
	const context = loadInventoryModule({
		fetch: async () => ({
			ok: false,
			status: 403,
			json: async () => ({
				_server_messages: JSON.stringify([JSON.stringify({ message: '<b>Not permitted</b> to export ledger' })]),
			}),
		}),
	})

	await assert.rejects(
		async () => {
			await context.downloadExport({ kind: 'cards', file_format: 'xlsx' })
		},
		(err) => {
			assert.equal(err.message, 'Not permitted to export ledger')
			return true
		},
	)
})

test('InventoryDetailDialog fixes menu overlay z-index so panel is above overlay', () => {
	const content = readFileSync(new URL('../src/components/InventoryDetailDialog.vue', import.meta.url), 'utf8')
	// Popoverlay has z-index 60, so filterpanel must have z-index > 60
	const hasFilterpanelZIndex = /\.inv-dialog\s+\.filterpanel\s*\{[^}]*z-index:\s*(6[1-9]|[7-9]\d|\d{3,})/i.test(content)
	assert.ok(hasFilterpanelZIndex, 'expected .inv-dialog .filterpanel to have z-index > 60 to prevent overlay obstruction')
})

test('InventoryPage loads company options and maps filtered warehouses', () => {
	const file = new URL('../src/pages/InventoryPage.vue', import.meta.url)
	const raw = readFileSync(file, 'utf8')
	const { descriptor } = parse(raw)

	// Template checks:
	// 1. Header has Company select before Warehouse select
	const headerCompanyIdx = descriptor.template.content.indexOf('companyOptions')
	const headerWarehouseIdx = descriptor.template.content.indexOf('filteredWarehouseOptions')
	assert.ok(headerCompanyIdx > 0, 'header should contain company select with companyOptions')
	assert.ok(headerWarehouseIdx > headerCompanyIdx, 'company select must appear before warehouse select in header')

	// 2. Both warehouse selects use filteredWarehouseOptions
	const matches = [...descriptor.template.content.matchAll(/:options="filteredWarehouseOptions"/g)]
	assert.equal(matches.length, 2, 'both header and popover warehouse selects must use filteredWarehouseOptions')

	// 3. Popover also has company before warehouse
	const popoverCompanyIdx = descriptor.template.content.indexOf('companyOptions', headerCompanyIdx + 1)
	assert.ok(popoverCompanyIdx > headerCompanyIdx, 'popover should contain company select')
	assert.ok(matches[1].index > popoverCompanyIdx, 'company select must appear before warehouse select in popover')

	// 4. Script loads opts.companies and opts.warehouse_company
	assert.ok(raw.includes('opts?.companies'), 'InventoryPage must load opts.companies')
	assert.ok(raw.includes('opts?.warehouse_company'), 'InventoryPage must load opts.warehouse_company')
})

test('InventoryPage reactivity: filteredWarehouseOptions cascades and resets correctly', async () => {
	const file = new URL('../src/pages/InventoryPage.vue', import.meta.url)
	const raw = readFileSync(file, 'utf8')
	const { descriptor } = parse(raw)
	const compiled = compileScript(descriptor, { id: 'inv-test' }).content

	const watchers = []
	let onMountedHook = null

	const context = {
		ref: (val) => {
			const r = {
				_val: val,
				get value() { return this._val },
				set value(v) {
					const old = this._val
					this._val = v
					watchers.forEach((w) => {
						if (w.source === r) w.fn(v, old)
					})
				},
			}
			return r
		},
		computed: (fn) => ({ get value() { return fn() } }),
		reactive: (obj) => obj,
		watch: (source, fn) => {
			watchers.push({ source, fn })
		},
		onMounted: (fn) => { onMountedHook = fn },
		fetchFilterOptions: async () => ({
			companies: ['Company A', 'Company B'],
			warehouses: ['Gudang A1', 'Gudang A2', 'Gudang B1'],
			warehouse_company: {
				'Gudang A1': 'Company A',
				'Gudang A2': 'Company A',
				'Gudang B1': 'Company B',
			},
			item_groups: ['All Item Groups'],
			can_export: true,
		}),
		fetchStockCards: async () => ({ rows: [], total: 0 }),
		fetchMovements: async () => ({ rows: [], total: 0 }),
		fetchStockBalance: async () => ({ rows: [], total: 0 }),
		downloadExport: async () => {},
		fmtQty: (v) => v,
		fmtRp: (v) => v,
		fmtDateTime: (v) => v,
		toast: { error() {} },
		dayjs: () => ({
			format: () => '2026-11-02',
			subtract: () => ({ format: () => '2026-11-01' }),
			startOf: () => ({ format: () => '2026-11-01' }),
		}),
		DateRangeField: {},
		InventoryDetailDialog: {},
		clearTimeout() {},
		setTimeout: () => 0,
	}

	vm.createContext(context)
	vm.runInContext(
		compiled
			.replace(/import[\s\S]*?from\s*['"][^'"]+['"]/g, '')
			.replace('export default', 'globalThis.component ='),
		context,
	)

	const state = context.component.setup({}, { expose() {}, emit() {} })

	// Run onMounted to load options
	await onMountedHook()

	assert.deepEqual(state.companyOptions.value, ['Company A', 'Company B'])
	assert.deepEqual(state.warehouseOptions.value, ['Gudang A1', 'Gudang A2', 'Gudang B1'])

	// When company is null, filteredWarehouseOptions shows all warehouses
	assert.deepEqual(state.filteredWarehouseOptions.value, ['Gudang A1', 'Gudang A2', 'Gudang B1'])

	// Select Company A -> filteredWarehouseOptions shows only warehouses for Company A
	state.company.value = 'Company A'
	assert.deepEqual(state.filteredWarehouseOptions.value, ['Gudang A1', 'Gudang A2'])

	// Select a warehouse
	state.warehouse.value = 'Gudang A1'
	assert.equal(state.filters.value.company, 'Company A')
	assert.equal(state.filters.value.warehouse, 'Gudang A1')

	// Change company to Company B -> warehouse resets to null
	state.company.value = 'Company B'
	assert.equal(state.warehouse.value, null)
	assert.deepEqual(state.filteredWarehouseOptions.value, ['Gudang B1'])

	// Clear filters resets company and warehouse
	state.clearFilters()
	assert.equal(state.company.value, null)
	assert.equal(state.warehouse.value, null)
	assert.deepEqual(state.filteredWarehouseOptions.value, ['Gudang A1', 'Gudang A2', 'Gudang B1'])
})
