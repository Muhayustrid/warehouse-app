<script setup>
// Halaman Inventory (W40). Dua tab di atas ledger native (SLE): Stock Cards
// (satu baris per SLE) dan Inventory Movements (Beginning/IN/OUT/Ending per
// item+gudang). Semua tabel lazy — paginasi, filter, agregasi di server
// (warehouse_app.warehouse_app.inventory). Qty dalam Default Inventory UOM
// item, nilai dalam Rupiah.
import { computed, onMounted, reactive, ref, watch } from 'vue'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import ColumnGroup from 'primevue/columngroup'
import Row from 'primevue/row'
import Select from 'primevue/select'
import { Button } from '@frappe-ui/components/Button'
import { TextInput } from '@frappe-ui/components/TextInput'
import { TabButtons } from '@frappe-ui/components/TabButtons'
import FeatherIcon from '@frappe-ui/components/FeatherIcon.vue'
import { Dropdown } from '@frappe-ui/components/Dropdown'
import { dayjs } from '@frappe-ui/utils/dayjs'
import DateRangeField from '@/components/DateRangeField.vue'
import InventoryDetailDialog from '@/components/InventoryDetailDialog.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import {
	fetchStockCards,
	fetchMovements,
	fetchFilterOptions,
	downloadExport,
	runRecalculate,
} from '@/data/inventory'
import { fmtQty, fmtRp, fmtDateTime } from '@/lib/format'
import { toast } from '@/lib/toast'

const tabs = [
	{ label: 'Stock Cards', value: 'cards' },
	{ label: 'Inventory Movements', value: 'movements' },
]
const tab = ref('cards')

// ---- filter bersama ----
const warehouse = ref(null)
const warehouseOptions = ref([])
const itemGroupOptions = ref([])
const can = ref({ export: false, recalculate: false })
const item = ref('')
const itemGroup = ref(null)
const showFilters = ref(false)

const RANGES = ['Today', 'Yesterday', 'This Week', 'This Month', 'Custom']
const range = ref('This Month')
const customFrom = ref('')
const customTo = ref('')

// khusus Movements: cari per Name/Item Code/Item Group
const SEARCH_BY = [
	{ label: 'Name', value: 'name' },
	{ label: 'Item Code', value: 'sku' },
	{ label: 'Item Group', value: 'item_group' },
]
const searchBy = ref('name')
const search = ref('')

const period = computed(() => {
	const d = dayjs()
	const iso = (x) => x.format('YYYY-MM-DD')
	switch (range.value) {
		case 'Today':
			return { from_date: iso(d), to_date: iso(d) }
		case 'Yesterday':
			return { from_date: iso(d.subtract(1, 'day')), to_date: iso(d.subtract(1, 'day')) }
		case 'This Week':
			return { from_date: iso(d.startOf('week')), to_date: iso(d) }
		case 'This Month':
			return { from_date: iso(d.startOf('month')), to_date: iso(d) }
		default:
			return { from_date: customFrom.value, to_date: customTo.value || customFrom.value }
	}
})

const periodLabel = computed(() => {
	const { from_date, to_date } = period.value
	if (!from_date) return ''
	const f = (x) => dayjs(x).format('DD MMM YYYY')
	return from_date === to_date ? f(from_date) : `${f(from_date)} – ${f(to_date)}`
})

const activeFilterCount = computed(
	() => [item.value.trim(), itemGroup.value, warehouse.value].filter(Boolean).length,
)

const filters = computed(() => ({
	...period.value,
	warehouse: warehouse.value || '',
	item: item.value.trim(),
	item_group: itemGroup.value || '',
}))

function clearFilters() {
	item.value = ''
	itemGroup.value = null
	warehouse.value = null
}

// ---- tabel lazy per tab ----
function lazyTable(fetcher, extra = () => ({})) {
	const t = reactive({ rows: [], total: 0, totals: null, loading: false, first: 0, pageLen: 20 })
	let seq = 0
	t.load = async () => {
		const mine = ++seq
		t.loading = true
		try {
			const res = await fetcher({
				...filters.value,
				...extra(),
				page: Math.floor(t.first / t.pageLen) + 1,
				page_len: t.pageLen,
			})
			if (mine !== seq) return // respons basi dari filter sebelumnya
			t.rows = res?.rows || []
			t.total = res?.total || 0
			t.totals = res?.totals || null
		} catch (e) {
			if (mine === seq) toast.error(e.message)
		} finally {
			if (mine === seq) t.loading = false
		}
	}
	t.onPage = (e) => {
		t.first = e.first
		t.pageLen = e.rows
		t.load()
	}
	t.reset = () => {
		t.first = 0
		t.load()
	}
	return t
}

const cards = lazyTable(fetchStockCards)
const moves = lazyTable(fetchMovements, () => ({
	search: search.value.trim(),
	search_by: searchBy.value,
}))
const active = computed(() => (tab.value === 'cards' ? cards : moves))

// filter berubah -> tab aktif dimuat ulang, tab lain ditandai basi
const stale = { cards: true, movements: true }
let typing = null
watch(
	[filters, () => search.value.trim(), searchBy],
	([now, s, by], [before, sBefore, byBefore] = []) => {
		clearTimeout(typing)
		stale.cards = true
		stale.movements = true
		const reload = () => {
			stale[tab.value] = false
			active.value.reset()
		}
		const typed = before && (now.item !== before.item || s !== sBefore)
		if (typed) {
			typing = setTimeout(reload, 350)
		} else {
			reload()
		}
	},
	{ deep: true },
)
watch(tab, (t) => {
	if (stale[t]) {
		stale[t] = false
		active.value.reset()
	}
})

onMounted(async () => {
	stale.cards = false
	cards.load()
	try {
		const opts = await fetchFilterOptions()
		warehouseOptions.value = opts?.warehouses || []
		itemGroupOptions.value = opts?.item_groups || []
		can.value = { export: !!opts?.can_export, recalculate: !!opts?.can_recalculate }
	} catch (e) {
		toast.error(e.message)
	}
})

const desk = (doctype, name) =>
	`/app/${doctype.toLowerCase().replace(/ /g, '-')}/${encodeURIComponent(name)}`

const MOVE_COLS = [
	{ key: 'begin', label: 'Beginning' },
	{ key: 'in', label: 'IN (+)' },
	{ key: 'out', label: 'OUT (-)' },
	{ key: 'end', label: 'Ending' },
]
const isEmpty = (r, k) => !r[k + '_qty'] && !r[k + '_value']
const isNegative = (r) => r.end_qty < 0 || r.end_value < 0

// klik baris Movements -> modal detail (periode dibekukan saat dibuka)
const detail = ref({ show: false, row: null, period: {} })
function openDetail({ data }) {
	detail.value = { show: true, row: data, period: { ...period.value } }
}

// ---- Export + Recalculate (W40-6) ----
const exporting = ref(false)
async function exportAs(file_format) {
	exporting.value = true
	try {
		const extra = tab.value === 'movements' ? { search: search.value.trim(), search_by: searchBy.value } : {}
		await downloadExport({ kind: tab.value, file_format, ...filters.value, ...extra })
	} catch (e) {
		toast.error(e.message)
	} finally {
		exporting.value = false
	}
}
const exportOptions = [
	{ label: 'Excel (.xlsx)', icon: 'file', onClick: () => exportAs('xlsx') },
	{ label: 'CSV (.csv)', icon: 'file-text', onClick: () => exportAs('csv') },
]

const confirmRecalc = ref(false)
const recalculating = ref(false)
async function doRecalculate() {
	recalculating.value = true
	await runRecalculate(
		{ ...filters.value, search: search.value.trim(), search_by: searchBy.value },
		() => moves.load(),
	)
	recalculating.value = false
}

const PAGINATOR =
	'CurrentPageReport FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown'
const PAGE_REPORT = 'Showing {first} to {last} of {totalRecords} results'
</script>

<template>
	<div class="space-y-4">
		<!-- header -->
		<div class="flex flex-wrap items-end justify-between gap-3">
			<div>
				<h1 class="text-2xl font-semibold tracking-tight text-ink-gray-9">Inventory</h1>
				<p class="mt-0.5 text-sm text-ink-gray-5">
					Stock ledger movements per item and division
					<span v-if="periodLabel" class="text-ink-gray-7">· {{ periodLabel }}</span>
				</p>
			</div>
			<label class="flex items-center gap-2 text-sm text-ink-gray-5">
				<span>Division</span>
				<Select
					v-model="warehouse"
					:options="warehouseOptions"
					placeholder="All"
					class="pv-select min-w-64"
					showClear
					filter
					filterPlaceholder="Search warehouse..."
				/>
			</label>
		</div>

		<div class="rounded-lg border border-outline-gray-1 bg-surface-modal">
			<!-- tab + kontrol -->
			<div class="flex flex-wrap items-center gap-2 border-b border-outline-gray-1 p-3">
				<TabButtons v-model="tab" :buttons="tabs" />
				<div class="mx-1 hidden h-5 w-px bg-outline-gray-2 sm:block" />
				<select
					v-model="range"
					class="h-8 rounded border border-outline-gray-2 bg-surface-modal px-2 text-sm text-ink-gray-8"
					aria-label="Time range"
				>
					<option v-for="r in RANGES" :key="r" :value="r">{{ r }}</option>
				</select>
				<div v-if="range === 'Custom'" class="w-56">
					<DateRangeField v-model:from="customFrom" v-model:to="customTo" placeholder="Select date range" />
				</div>
				<template v-if="tab === 'movements'">
					<select
						v-model="searchBy"
						class="h-8 rounded border border-outline-gray-2 bg-surface-modal px-2 text-sm text-ink-gray-8"
						aria-label="Search by"
					>
						<option v-for="o in SEARCH_BY" :key="o.value" :value="o.value">by {{ o.label }}</option>
					</select>
					<div class="w-56">
						<TextInput v-model="search" type="text" placeholder="Find Inventory..">
							<template #prefix><FeatherIcon name="search" class="h-4 w-4" /></template>
						</TextInput>
					</div>
				</template>
				<div class="ml-auto flex items-center gap-2">
					<Button
						:variant="showFilters ? 'solid' : 'subtle'"
						:label="activeFilterCount ? `Filters (${activeFilterCount})` : 'Open Filter'"
						icon-left="filter"
						@click="showFilters = !showFilters"
					/>
					<Button
						v-if="tab === 'movements' && can.recalculate"
						variant="solid"
						theme="red"
						label="Recalculate Inventory"
						icon-left="refresh-cw"
						:loading="recalculating"
						:disabled="!moves.total"
						@click="confirmRecalc = true"
					/>
					<Dropdown v-if="can.export" :options="exportOptions" align="end">
						<Button variant="subtle" label="Export" icon-left="share" :loading="exporting" />
					</Dropdown>
					<Button variant="subtle" icon="refresh-cw" aria-label="Refresh" :loading="active.loading" @click="active.load()" />
				</div>
			</div>

			<!-- panel filter -->
			<div
				v-if="showFilters"
				class="grid gap-3 border-b border-outline-gray-1 bg-surface-gray-1 p-3 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-end"
			>
				<label class="space-y-1 text-xs text-ink-gray-5">
					<span>Item</span>
					<TextInput v-model="item" type="text" placeholder="Item code or name..." />
				</label>
				<label class="space-y-1 text-xs text-ink-gray-5">
					<span>Item Group</span>
					<Select
						v-model="itemGroup"
						:options="itemGroupOptions"
						placeholder="All item groups"
						class="pv-select w-full"
						showClear
						filter
					/>
				</label>
				<label class="space-y-1 text-xs text-ink-gray-5">
					<span>Warehouse</span>
					<Select
						v-model="warehouse"
						:options="warehouseOptions"
						placeholder="All warehouses"
						class="pv-select w-full"
						showClear
						filter
					/>
				</label>
				<Button variant="outline" label="Clear" :disabled="!activeFilterCount" @click="clearFilters" />
			</div>

			<!-- Stock Cards -->
			<div v-if="tab === 'cards'" class="transition-opacity" :class="{ 'opacity-50': cards.loading }">
				<DataTable
					:value="cards.rows"
					dataKey="name"
					lazy
					paginator
					:first="cards.first"
					:rows="cards.pageLen"
					:totalRecords="cards.total"
					:rowsPerPageOptions="[20, 50, 100]"
					:paginatorTemplate="PAGINATOR"
					:currentPageReportTemplate="PAGE_REPORT"
					class="pv-table pv-table-fit"
					@page="cards.onPage"
				>
					<template #empty>
						<div class="flex flex-col items-center gap-2 px-6 py-14 text-center">
							<FeatherIcon name="layers" class="h-8 w-8 text-ink-gray-3" />
							<p class="text-sm text-ink-gray-4">
								No stock transactions in this period. Try a different time range or clear the filters.
							</p>
						</div>
					</template>

					<Column header="Item Code">
						<template #body="{ data }">
							<span class="whitespace-nowrap font-mono text-xs text-ink-gray-6">{{ data.item_code }}</span>
						</template>
					</Column>
					<Column header="Name">
						<template #body="{ data }">
							<span class="text-ink-gray-8">{{ data.item_name }}</span>
						</template>
					</Column>
					<Column header="Division">
						<template #body="{ data }">
							<span class="whitespace-nowrap text-ink-gray-6">{{ data.warehouse }}</span>
						</template>
					</Column>
					<Column header="Date">
						<template #body="{ data }">
							<span class="whitespace-nowrap text-ink-gray-5">{{ fmtDateTime(data.posting_datetime) }}</span>
						</template>
					</Column>
					<Column header="Reference">
						<template #body="{ data }">
							<div class="whitespace-nowrap">
								<div class="text-ink-gray-8">{{ data.voucher_type }}</div>
								<a
									:href="desk(data.voucher_type, data.voucher_no)"
									target="_blank"
									class="font-mono text-xs text-ink-gray-5 underline decoration-transparent underline-offset-2 hover:decoration-current"
									>{{ data.voucher_no }}</a
								>
								<div v-if="data.counterparty" class="text-xs text-ink-gray-6">
									<span class="font-medium">{{ data.counterparty.dir === 'to' ? 'To' : 'From' }}:</span>
									{{ [data.counterparty.warehouse, data.counterparty.party, data.counterparty.company].filter(Boolean).join(' · ') }}
								</div>
							</div>
						</template>
					</Column>
					<Column header="Stock Before" headerClass="num" bodyClass="num">
						<template #body="{ data }">
							<div class="whitespace-nowrap tabular-nums" :class="data.qty_before < 0 ? 'text-red-600' : 'text-ink-gray-8'">
								{{ fmtQty(data.qty_before) }}
								<div class="text-xs text-ink-gray-4">{{ data.uom }}</div>
							</div>
						</template>
					</Column>
					<Column header="Balance Before" headerClass="num" bodyClass="num">
						<template #body="{ data }">
							<span class="whitespace-nowrap tabular-nums text-ink-gray-7">{{ fmtRp(data.value_before) }}</span>
						</template>
					</Column>
					<Column header="In" headerClass="num" bodyClass="num">
						<template #body="{ data }">
							<span v-if="data.qty_in != null" class="whitespace-nowrap tabular-nums text-green-700 dark:text-green-400">
								{{ fmtQty(data.qty_in) }}
							</span>
							<span v-else class="text-ink-gray-4">-</span>
						</template>
					</Column>
					<Column header="Out" headerClass="num" bodyClass="num">
						<template #body="{ data }">
							<span v-if="data.qty_out != null" class="whitespace-nowrap tabular-nums text-red-600 dark:text-red-400">
								{{ fmtQty(data.qty_out) }}
							</span>
							<span v-else class="text-ink-gray-4">-</span>
						</template>
					</Column>
					<Column header="Stock After" headerClass="num" bodyClass="num">
						<template #body="{ data }">
							<div class="whitespace-nowrap tabular-nums font-medium" :class="data.qty_after < 0 ? 'text-red-600' : 'text-ink-gray-9'">
								{{ fmtQty(data.qty_after) }}
								<div class="text-xs font-normal text-ink-gray-4">{{ data.uom }}</div>
							</div>
						</template>
					</Column>
					<Column header="Balance After" headerClass="num" bodyClass="num">
						<template #body="{ data }">
							<span class="whitespace-nowrap tabular-nums text-ink-gray-8">{{ fmtRp(data.value_after) }}</span>
						</template>
					</Column>
				</DataTable>
			</div>

			<!-- Inventory Movements -->
			<div v-else class="transition-opacity" :class="{ 'opacity-50': moves.loading }">
				<DataTable
					:value="moves.rows"
					:dataKey="(r) => r.item_code + '|' + r.warehouse"
					lazy
					paginator
					:first="moves.first"
					:rows="moves.pageLen"
					:totalRecords="moves.total"
					:rowsPerPageOptions="[20, 50, 100]"
					:paginatorTemplate="PAGINATOR"
					:currentPageReportTemplate="PAGE_REPORT"
					class="pv-table pv-table-fit pv-table-click"
					@page="moves.onPage"
					@row-click="openDetail"
				>
					<template #empty>
						<div class="flex flex-col items-center gap-2 px-6 py-14 text-center">
							<FeatherIcon name="layers" class="h-8 w-8 text-ink-gray-3" />
							<p class="text-sm text-ink-gray-4">
								No inventory found for this period. Try a different time range or clear the filters.
							</p>
						</div>
					</template>

					<Column header="Item Code">
						<template #body="{ data }">
							<span class="whitespace-nowrap font-mono text-xs text-ink-gray-6">{{ data.item_code }}</span>
						</template>
					</Column>
					<Column header="Inventory Name">
						<template #body="{ data }">
							<div class="text-ink-gray-8">
								{{ data.item_name }} <span class="text-ink-gray-4">/ {{ data.uom }}</span>
							</div>
							<div class="text-xs text-ink-gray-5">at {{ data.warehouse }}</div>
						</template>
					</Column>
					<Column
						v-for="c in MOVE_COLS"
						:key="c.key"
						:header="c.label"
						headerClass="num"
						bodyClass="num"
						:style="{ width: '15%' }"
					>
						<template #body="{ data }">
							<div
								class="whitespace-nowrap tabular-nums"
								:class="c.key === 'end' && isNegative(data) ? '-m-3 bg-red-800 p-3 text-white' : ''"
							>
								<template v-if="isEmpty(data, c.key)">
									<div class="text-ink-gray-4">-</div>
									<div class="text-xs text-ink-gray-4">-N/A-</div>
								</template>
								<template v-else>
									<div :class="c.key === 'end' ? 'font-medium' : ''">
										{{ fmtQty(data[c.key + '_qty']) }}
										<span class="text-xs" :class="c.key === 'end' && isNegative(data) ? 'text-red-200' : 'text-ink-gray-4'">{{ data.uom }}</span>
									</div>
									<div class="text-xs" :class="c.key === 'end' && isNegative(data) ? 'text-red-100' : 'text-ink-gray-5'">
										{{ fmtRp(data[c.key + '_value']) }}
									</div>
								</template>
							</div>
						</template>
					</Column>

					<ColumnGroup v-if="moves.total" type="footer">
						<Row>
							<Column :colspan="2">
								<template #footer>
									<div class="text-ink-gray-9">Total</div>
									<div class="text-xs font-normal text-ink-gray-5">all {{ moves.total }} results</div>
								</template>
							</Column>
							<Column v-for="c in MOVE_COLS" :key="c.key" footerClass="num">
								<template #footer>
									<div
										class="whitespace-nowrap"
										:class="moves.totals?.[c.key + '_value'] < 0 ? 'text-red-600' : 'text-ink-gray-9'"
									>
										{{ fmtRp(moves.totals?.[c.key + '_value']) }}
									</div>
									<div class="text-xs font-normal text-ink-gray-5">value</div>
								</template>
							</Column>
						</Row>
					</ColumnGroup>
				</DataTable>
			</div>
		</div>

		<InventoryDetailDialog
			v-model="detail.show"
			:row="detail.row"
			:period="detail.period"
			:can="can"
			@recalculated="moves.load()"
		/>
		<ConfirmDialog
			v-model="confirmRecalc"
			:options="{
				title: 'Recalculate Inventory',
				message: `Repost stock valuation from ${periodLabel} for the ${moves.total} item/warehouse rows matching the current filters (only those with transactions in the period). This is a heavy background job and may take several minutes. Continue?`,
				confirmLabel: 'Recalculate',
				theme: 'danger',
			}"
			:onConfirm="doRecalculate"
		/>
	</div>
</template>
