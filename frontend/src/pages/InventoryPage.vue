<script setup>
// Halaman Inventory Report (W40, redesign W41). Tiga tab di atas ledger
// native: Stock Cards (satu baris per SLE), Inventory Movements
// (Beginning/IN/OUT/Ending per item+gudang) dan Stock Balance (saldo Bin saat
// ini). Semua tabel lazy — paginasi, filter, agregasi di server
// (warehouse_app.warehouse_app.inventory). Qty dalam Default Inventory UOM
// item, nilai dalam Rupiah. Chrome (toolbar/filter/tab) pakai class native
// gudang.css + ikon lucide; tabel & Select tetap PrimeVue. Tanpa Tailwind —
// styling via gudang.css + <style> lokal ber-prefix .inv-.
import { computed, onMounted, reactive, ref, watch } from 'vue'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import ColumnGroup from 'primevue/columngroup'
import Row from 'primevue/row'
import Select from 'primevue/select'
import dayjs from 'dayjs'
import DateRangeField from '@/components/DateRangeField.vue'
import InventoryDetailDialog from '@/components/InventoryDetailDialog.vue'
import {
	fetchStockCards,
	fetchMovements,
	fetchStockBalance,
	fetchFilterOptions,
	downloadExport,
} from '@/data/inventory'
import { fmtQty, fmtRp, fmtDateTime } from '@/lib/format'
import { toast } from '@/lib/toast'

import {
	Search as SearchIcon,
	Filter as FilterIcon,
	RefreshCw as RefreshIcon,
	Download as DownloadIcon,
	FileSpreadsheet as FileSpreadsheetIcon,
	FileText as FileTextIcon,
	Layers as LayersIcon,
} from 'lucide-vue-next'

const tabs = [
	{ label: 'Stock Balance', value: 'balance' },
	{ label: 'Stock Cards', value: 'cards' },
	{ label: 'Inventory Movements', value: 'movements' },
]
const tab = ref('balance')

// ---- filter bersama ----
const warehouse = ref(null)
const warehouseOptions = ref([])
const itemGroupOptions = ref([])
const can = ref({ export: false })
const item = ref('')
const itemGroup = ref(null)
const showFilters = ref(false)
const exportOpen = ref(false)

const RANGES = ['Today', 'Yesterday', 'This Week', 'This Month', 'Custom']
const range = ref('This Month')
const customFrom = ref('')
const customTo = ref('')

// kotak cari toolbar (semua tab): cari per nama item; kode/group lewat Filters
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
	range.value = 'This Month'
	customFrom.value = ''
	customTo.value = ''
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

const searchArgs = () => ({ search: search.value.trim(), search_by: 'name' })
const cards = lazyTable(fetchStockCards, searchArgs)
const moves = lazyTable(fetchMovements, searchArgs)
const balance = lazyTable(fetchStockBalance, searchArgs)
const tables = { cards, movements: moves, balance }
const active = computed(() => tables[tab.value])

// filter berubah -> tab aktif dimuat ulang, tab lain ditandai basi
const stale = { cards: true, movements: true, balance: true }
let typing = null
watch([filters, () => search.value.trim()], ([now, s], [before, sBefore] = []) => {
	clearTimeout(typing)
	for (const k in stale) stale[k] = true
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
}, { deep: true })
watch(tab, (t) => {
	if (stale[t]) {
		stale[t] = false
		active.value.reset()
	}
})

onMounted(async () => {
	stale[tab.value] = false
	active.value.load()
	try {
		const opts = await fetchFilterOptions()
		warehouseOptions.value = opts?.warehouses || []
		itemGroupOptions.value = opts?.item_groups || []
		can.value = { export: !!opts?.can_export }
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
const BALANCE_QTY = [
	{ key: 'actual_qty', label: 'On Hand' },
	{ key: 'reserved_qty', label: 'Reserved' },
	{ key: 'projected_qty', label: 'Projected' },
]
const isEmpty = (r, k) => !r[k + '_qty'] && !r[k + '_value']
const isNegative = (r) => r.end_qty < 0 || r.end_value < 0

// klik baris Movements -> modal detail (periode dibekukan saat dibuka)
const detail = ref({ show: false, row: null, period: {} })
function openDetail({ data }) {
	detail.value = { show: true, row: data, period: { ...period.value } }
}

// ---- Export (W40-6) ----
const exporting = ref(false)
async function exportAs(file_format) {
	exportOpen.value = false
	exporting.value = true
	try {
		await downloadExport({ kind: tab.value, file_format, ...filters.value, ...searchArgs() })
	} catch (e) {
		toast.error(e.message)
	} finally {
		exporting.value = false
	}
}

const PAGINATOR =
	'CurrentPageReport FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown'
const PAGE_REPORT = 'Showing {first} to {last} of {totalRecords} results'
</script>

<template>
	<div class="inv-page">
		<!-- page-head -->
		<div class="page-head">
			<div class="ph-left">
				<h1>Inventory Report</h1>
				<p class="sub">
					Stock ledger movements and balances per item and warehouse
					<span v-if="periodLabel && tab !== 'balance'">· {{ periodLabel }}</span>
				</p>
			</div>
			<label class="ph-warehouse">
				<span>Warehouse</span>
				<Select
					v-model="warehouse"
					:options="warehouseOptions"
					placeholder="All"
					class="pv-select inv-warehouse-select"
					showClear
					filter
					filterPlaceholder="Search warehouse..."
				/>
			</label>
		</div>

		<div class="panel">
			<!-- toolbar -->
			<div class="toolbar inv-toolbar">
				<div class="dseg" role="tablist" aria-label="Report type">
					<button
						v-for="t in tabs"
						:key="t.value"
						type="button"
						class="dseg-btn"
						:class="{ on: tab === t.value }"
						role="tab"
						:aria-selected="tab === t.value ? 'true' : 'false'"
						@click="tab = t.value"
					>
						{{ t.label }}
					</button>
				</div>
				<div class="searchbox">
					<span class="search-ico"><SearchIcon :size="15" :stroke-width="2" /></span>
					<input v-model="search" type="search" class="input" placeholder="Find Inventory.." aria-label="Find Inventory" />
				</div>

				<!-- filter popover -->
				<div class="filterwrap">
					<button
						type="button"
						class="btn filterbtn"
						:class="{ active: showFilters }"
						:aria-expanded="showFilters ? 'true' : 'false'"
						@click="showFilters = !showFilters"
					>
						<FilterIcon :size="14" :stroke-width="2" />
						<span>Filters</span>
						<span v-if="activeFilterCount" class="filtercount">{{ activeFilterCount }}</span>
					</button>
					<div v-if="showFilters" class="popoverlay" @click="showFilters = false"></div>
					<Transition name="pop">
						<div v-if="showFilters" class="filterpanel">
							<!-- rentang waktu: hanya berguna utk ledger (cards/movements),
							     Stock Balance = posisi kini tanpa periode -->
							<div v-if="tab !== 'balance'" class="ffield">
								<label>Time Range</label>
								<select v-model="range" class="select" aria-label="Time range">
									<option v-for="r in RANGES" :key="r" :value="r">{{ r }}</option>
								</select>
								<DateRangeField
									v-if="range === 'Custom'"
									v-model:from="customFrom"
									v-model:to="customTo"
									placeholder="Select date range"
								/>
							</div>
							<div class="ffield">
								<label>Item</label>
								<input v-model="item" type="text" class="input" placeholder="Item code or name..." />
							</div>
							<div class="ffield">
								<label>Item Group</label>
								<Select
									v-model="itemGroup"
									:options="itemGroupOptions"
									placeholder="All item groups"
									class="pv-select inv-wfull"
									showClear
									filter
								/>
							</div>
							<div class="ffield">
								<label>Warehouse</label>
								<Select
									v-model="warehouse"
									:options="warehouseOptions"
									placeholder="All warehouses"
									class="pv-select inv-wfull"
									showClear
									filter
								/>
							</div>
							<button type="button" class="btn filter-clear" :disabled="!activeFilterCount" @click="clearFilters">
								Clear
							</button>
						</div>
					</Transition>
				</div>

				<!-- export popover -->
				<div v-if="can.export && tab !== 'balance'" class="filterwrap">
					<button type="button" class="btn filterbtn" :disabled="exporting" @click="exportOpen = !exportOpen">
						<DownloadIcon :size="14" :stroke-width="2" />
						<span>Export</span>
					</button>
					<div v-if="exportOpen" class="popoverlay" @click="exportOpen = false"></div>
					<Transition name="pop">
						<div v-if="exportOpen" class="filterpanel pop-right inv-exportpanel">
							<button type="button" class="btn" @click="exportAs('xlsx')">
								<FileSpreadsheetIcon :size="14" :stroke-width="2" /> Excel (.xlsx)
							</button>
							<button type="button" class="btn" @click="exportAs('csv')">
								<FileTextIcon :size="14" :stroke-width="2" /> CSV (.csv)
							</button>
						</div>
					</Transition>
				</div>

				<button
					type="button"
					class="btn"
					:disabled="active.loading"
					aria-label="Refresh"
					title="Refresh"
					@click="active.load()"
				>
					<RefreshIcon :size="15" :stroke-width="2" />
				</button>
			</div>

			<!-- Stock Cards -->
			<div v-if="tab === 'cards'" class="inv-pane" :class="{ dim: cards.loading }">
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
						<div class="empty-inset">
							<div class="eico"><LayersIcon :size="18" /></div>
							<p class="etitle">No stock transactions in this period</p>
							<p class="ehint">Try a different time range or clear the filters.</p>
						</div>
					</template>

					<Column header="Item Code">
						<template #body="{ data }">
							<span class="inv-code">{{ data.item_code }}</span>
						</template>
					</Column>
					<Column header="Item Name">
						<template #body="{ data }">
							<span class="inv-ink">{{ data.item_name }}</span>
						</template>
					</Column>
					<Column header="Warehouse">
						<template #body="{ data }">
							<span class="inv-nw inv-muted">{{ data.warehouse }}</span>
						</template>
					</Column>
					<Column header="Date">
						<template #body="{ data }">
							<span class="inv-nw inv-muted">{{ fmtDateTime(data.posting_datetime) }}</span>
						</template>
					</Column>
					<Column header="Reference">
						<template #body="{ data }">
							<div class="inv-nw">
								<div class="inv-ink">{{ data.voucher_type }}</div>
								<a :href="desk(data.voucher_type, data.voucher_no)" target="_blank" class="inv-link">{{ data.voucher_no }}</a>
								<div v-if="data.counterparty" class="inv-xs inv-muted">
									<span class="inv-med">{{ data.counterparty.dir === 'to' ? 'To' : 'From' }}:</span>
									{{ [data.counterparty.warehouse, data.counterparty.party, data.counterparty.company].filter(Boolean).join(' · ') }}
								</div>
							</div>
						</template>
					</Column>
					<Column header="Stock Before" headerClass="num" bodyClass="num">
						<template #body="{ data }">
							<div class="inv-num" :class="data.qty_before < 0 ? 'inv-bad' : 'inv-ink'">
								{{ fmtQty(data.qty_before) }}
								<div class="inv-xs inv-faint">{{ data.uom }}</div>
							</div>
						</template>
					</Column>
					<Column header="Balance Before" headerClass="num" bodyClass="num">
						<template #body="{ data }">
							<span class="inv-num inv-muted">{{ fmtRp(data.value_before) }}</span>
						</template>
					</Column>
					<Column header="In" headerClass="num" bodyClass="num">
						<template #body="{ data }">
							<span v-if="data.qty_in != null" class="inv-num inv-ok">{{ fmtQty(data.qty_in) }}</span>
							<span v-else class="inv-faint">-</span>
						</template>
					</Column>
					<Column header="Out" headerClass="num" bodyClass="num">
						<template #body="{ data }">
							<span v-if="data.qty_out != null" class="inv-num inv-bad">{{ fmtQty(data.qty_out) }}</span>
							<span v-else class="inv-faint">-</span>
						</template>
					</Column>
					<Column header="Stock After" headerClass="num" bodyClass="num">
						<template #body="{ data }">
							<div class="inv-num inv-med" :class="data.qty_after < 0 ? 'inv-bad' : 'inv-ink'">
								{{ fmtQty(data.qty_after) }}
								<div class="inv-xs inv-faint">{{ data.uom }}</div>
							</div>
						</template>
					</Column>
					<Column header="Balance After" headerClass="num" bodyClass="num">
						<template #body="{ data }">
							<span class="inv-num inv-ink">{{ fmtRp(data.value_after) }}</span>
						</template>
					</Column>
				</DataTable>
			</div>

			<!-- Stock Balance -->
			<div v-else-if="tab === 'balance'" class="inv-pane" :class="{ dim: balance.loading }">
				<DataTable
					:value="balance.rows"
					:dataKey="(r) => r.item_code + '|' + r.warehouse"
					lazy
					paginator
					:first="balance.first"
					:rows="balance.pageLen"
					:totalRecords="balance.total"
					:rowsPerPageOptions="[20, 50, 100]"
					:paginatorTemplate="PAGINATOR"
					:currentPageReportTemplate="PAGE_REPORT"
					class="pv-table pv-table-fit"
					@page="balance.onPage"
				>
					<template #empty>
						<div class="empty-inset">
							<div class="eico"><LayersIcon :size="18" /></div>
							<p class="etitle">No stock on hand</p>
							<p class="ehint">Try clearing the filters.</p>
						</div>
					</template>

					<Column header="Item Code">
						<template #body="{ data }">
							<span class="inv-code">{{ data.item_code }}</span>
						</template>
					</Column>
					<Column header="Item Name">
						<template #body="{ data }">
							<div class="inv-ink">{{ data.item_name }}</div>
							<div class="inv-xs inv-muted">{{ data.item_group }}</div>
						</template>
					</Column>
					<Column header="Warehouse">
						<template #body="{ data }">
							<span class="inv-nw inv-muted">{{ data.warehouse }}</span>
						</template>
					</Column>
					<Column header="UOM">
						<template #body="{ data }">
							<span class="inv-muted">{{ data.uom }}</span>
						</template>
					</Column>
					<Column v-for="c in BALANCE_QTY" :key="c.key" :header="c.label" headerClass="num" bodyClass="num">
						<template #body="{ data }">
							<span class="inv-num" :class="[data[c.key] < 0 ? 'inv-bad' : 'inv-ink', c.key === 'actual_qty' ? 'inv-med' : '']">
								{{ fmtQty(data[c.key]) }}
							</span>
						</template>
					</Column>
					<Column header="Valuation Rate" headerClass="num" bodyClass="num">
						<template #body="{ data }">
							<span class="inv-num inv-muted">{{ fmtRp(data.valuation_rate) }}</span>
						</template>
					</Column>
					<Column header="Stock Value" headerClass="num" bodyClass="num">
						<template #body="{ data }">
							<span class="inv-num" :class="data.stock_value < 0 ? 'inv-bad' : 'inv-ink'">{{ fmtRp(data.stock_value) }}</span>
						</template>
					</Column>

					<ColumnGroup v-if="balance.total" type="footer">
						<Row>
							<Column :colspan="8">
								<template #footer>
									<div class="inv-foot-title">Total</div>
									<div class="inv-foot-sub">all {{ balance.total }} results</div>
								</template>
							</Column>
							<Column footerClass="num">
								<template #footer>
									<div class="inv-num" :class="balance.totals?.stock_value < 0 ? 'inv-bad' : 'inv-ink'">
										{{ fmtRp(balance.totals?.stock_value) }}
									</div>
								</template>
							</Column>
						</Row>
					</ColumnGroup>
				</DataTable>
			</div>

			<!-- Inventory Movements -->
			<div v-else class="inv-pane" :class="{ dim: moves.loading }">
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
						<div class="empty-inset">
							<div class="eico"><LayersIcon :size="18" /></div>
							<p class="etitle">No inventory found for this period</p>
							<p class="ehint">Try a different time range or clear the filters.</p>
						</div>
					</template>

					<Column header="Item Code">
						<template #body="{ data }">
							<span class="inv-code">{{ data.item_code }}</span>
						</template>
					</Column>
					<Column header="Item Name">
						<template #body="{ data }">
							<div class="inv-ink">
								{{ data.item_name }} <span class="inv-faint">/ {{ data.uom }}</span>
							</div>
							<div class="inv-xs inv-muted">at {{ data.warehouse }}</div>
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
							<div class="inv-num" :class="{ 'inv-neg-block': c.key === 'end' && isNegative(data) }">
								<template v-if="isEmpty(data, c.key)">
									<div class="inv-faint">-</div>
									<div class="inv-xs inv-faint">-N/A-</div>
								</template>
								<template v-else>
									<div :class="c.key === 'end' ? 'inv-med' : ''">
										{{ fmtQty(data[c.key + '_qty']) }}
										<span
											class="inv-xs"
											:class="c.key === 'end' && isNegative(data) ? 'inv-neg-uom' : 'inv-faint'"
											>{{ data.uom }}</span
										>
									</div>
									<div class="inv-xs" :class="c.key === 'end' && isNegative(data) ? 'inv-neg-val' : 'inv-muted'">
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
									<div class="inv-foot-title">Total</div>
									<div class="inv-foot-sub">all {{ moves.total }} results</div>
								</template>
							</Column>
							<Column v-for="c in MOVE_COLS" :key="c.key" footerClass="num">
								<template #footer>
									<div class="inv-num" :class="moves.totals?.[c.key + '_value'] < 0 ? 'inv-bad' : 'inv-ink'">
										{{ fmtRp(moves.totals?.[c.key + '_value']) }}
									</div>
									<div class="inv-foot-sub">value</div>
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
		/>
	</div>
</template>

<style>
/* ===== Skin lokal Inventory (W41): tabel PrimeVue + modal detail mengikuti
   token gudang.css. Non-scoped karena juga membungkus tabel di
   InventoryDetailDialog (dialog hanya dibuka dari halaman ini). Pengganti
   skin abu primevue.css yang dibuang oleh fondasi. Tanpa Tailwind. ===== */

/* -- utilitas teks ber-prefix .inv- (dipakai juga oleh dialog) -- */
.inv-ink { color: var(--ink); }
.inv-muted { color: var(--muted); }
.inv-faint { color: var(--faint); }
.inv-bad { color: var(--bad-ink); }
.inv-ok { color: var(--ok-strong); }
.inv-med { font-weight: 500; }
.inv-xs { font-size: 12px; }
.inv-nw { white-space: nowrap; }
.inv-num { white-space: nowrap; font-variant-numeric: tabular-nums; }
.inv-wfull { width: 100%; }
.inv-code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--muted); white-space: nowrap; }
.inv-link {
	font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
	font-size: 12px; color: var(--muted);
	text-decoration: underline; text-decoration-color: transparent; text-underline-offset: 2px;
}
.inv-link:hover { text-decoration-color: currentColor; }
.inv-foot-title { font-weight: 600; color: var(--ink); }
.inv-foot-sub { font-size: 12px; font-weight: 400; color: var(--muted); }
/* ending negatif: blok merah solid menempel ke tepi sel (bg bad + teks putih) */
.inv-neg-block { margin: -12px; padding: 12px; background: var(--bad-ink, #9c4736); color: #fff; }
.inv-neg-uom { color: rgba(255, 255, 255, 0.8); }
.inv-neg-val { color: rgba(255, 255, 255, 0.9); }

/* -- pane tab: redup saat loading -- */
.inv-pane { transition: opacity 0.15s ease; }
.inv-pane.dim { opacity: 0.5; }

/* -- popover filter/export (pola styles.css production; fallback ringan
   bila gudang.css belum memuatnya, duplikat tidak konflik) -- */
.inv-page .popoverlay { position: fixed; inset: 0; z-index: 20; }
.inv-page .pop-enter-active { transition: opacity 0.18s ease, transform 0.18s cubic-bezier(0.32, 0.72, 0, 1); }
.inv-page .pop-leave-active { transition: opacity 0.12s ease; }
.inv-page .pop-enter-from { opacity: 0; transform: scale(0.96) translateY(-4px); }
.inv-page .pop-leave-to { opacity: 0; }
.inv-page .ffield { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.inv-page .ffield > label { font-size: 12px; font-weight: 600; color: var(--muted); }
.inv-page .filter-clear { margin-top: 4px; color: var(--bad-ink); }
.inv-page .filter-clear:disabled { opacity: 0.45; cursor: not-allowed; }
.pop-right { left: auto; right: 0; transform-origin: top right; }
.inv-exportpanel { width: 200px; }
.inv-exportpanel .btn { justify-content: flex-start; width: 100%; }
.inv-toolbar { margin-bottom: 0; padding: 10px 12px; border-bottom: 1px solid var(--line); }
.ph-warehouse { display: flex; align-items: center; gap: 8px; margin-top: 4px; font-size: 12.5px; font-weight: 500; color: var(--muted); white-space: nowrap; }
.ph-warehouse .inv-warehouse-select { min-width: 15rem; }

/* -- mobile ≤820px: kepala tumpuk, tab geser menyamping, paginator ringkas -- */
@media (max-width: 820px) {
  .inv-page .page-head { flex-direction: column; align-items: stretch; gap: 10px; }
  .inv-page .ph-warehouse { width: 100%; }
  .inv-page .ph-warehouse .inv-warehouse-select { flex: 1; min-width: 0; }
  .inv-page .inv-toolbar { flex-wrap: wrap; gap: 8px; }
  /* tab ledger: baris sendiri, geser menyamping sendiri — jangan potong label */
  .inv-page .dseg { flex: 1 1 100%; min-width: 0; max-width: 100%; overflow-x: auto; scrollbar-width: none; }
  .inv-page .dseg::-webkit-scrollbar { display: none; }
  .inv-page .dseg-btn { flex: none; }
  .inv-page .inv-toolbar .searchbox { flex: 1 1 100%; max-width: none; min-width: 0; }
  /* tabel ledger tetap geser menyamping di dalam kartu (sengaja) — sel dirapatkan */
  .inv-page .pv-table .p-datatable-thead > tr > th,
  .inv-page .pv-table .p-datatable-tbody > tr > td { padding: 0.5rem 0.6rem; }
  .inv-page .p-paginator .p-paginator-current { display: none; }
  /* popover mobile: sheet selebar kartu, di bawah toolbar (anchor toolbar —
     jangan ke tombol: posisinya geser saat toolbar wrap; .panel berkaca
     dengan backdrop-filter tak bisa jadi anchor fixed) */
  .inv-page .inv-toolbar { position: relative; }
  .inv-page .filterwrap { position: static; }
  .inv-page .filterpanel { position: absolute; top: calc(100% + 6px); left: 0; right: 0; width: auto; min-width: 0; }
}

/* -- DataTable: header uppercase 10.5px muted, pemisah 1px var(--line),
   hover brand-softer, angka tabular-nums kanan -- */
.pv-table .p-datatable-table {
	min-width: 1500px;
	width: 100%;
	border-collapse: collapse;
}

.pv-table .p-datatable-thead > tr > th {
	background: transparent;
	color: var(--faint);
	border: 0;
	border-bottom: 1px solid var(--line);
	padding: 0.5rem 0.75rem;
	font-size: 10.5px;
	font-weight: 650;
	letter-spacing: 0.05em;
	text-transform: uppercase;
	text-align: left;
	white-space: nowrap;
	vertical-align: middle;
}

.pv-table .p-datatable-tbody > tr > td {
	background: transparent;
	border: 0;
	border-bottom: 1px solid var(--line);
	padding: 0.7rem 0.75rem;
	font-size: 0.875rem;
	text-align: left;
	vertical-align: middle;
}

.pv-table .p-datatable-tbody > tr:last-child > td {
	border-bottom: 0;
}

.pv-table .p-datatable-tbody > tr:hover > td {
	background: var(--brand-softer);
}

.pv-table .p-datatable-tbody > tr.p-datatable-row-selected > td {
	background: var(--brand-soft);
}

.pv-table .p-datatable-empty-message > td {
	padding: 0;
	border: 0;
}

.pv-table .p-datatable-sort-icon {
	color: var(--faint);
}

.pv-table .p-datatable-tfoot > tr > td {
	background: var(--grey-bg, rgba(0, 0, 0, 0.04));
	border: 0;
	border-top: 1px solid var(--line);
	padding: 0.625rem 0.75rem;
	font-size: 0.875rem;
	font-weight: 600;
	font-variant-numeric: tabular-nums;
}

/* -- Paginator -- */
.pv-table .p-paginator {
	background: transparent;
	border: 0;
	border-top: 1px solid var(--line);
	border-radius: 0;
	padding: 0.5rem 0.75rem;
	color: var(--muted);
	font-size: 12px;
}

/* -- kolom angka rata kanan -- */
.pv-table .p-datatable-thead > tr > th.num,
.pv-table .p-datatable-tbody > tr > td.num,
.pv-table .p-datatable-tfoot > tr > td.num {
	text-align: right;
}
.pv-table .p-datatable-thead > tr > th.num .p-datatable-column-header-content {
	justify-content: flex-end;
}
.pv-table-fit .p-datatable-table {
	min-width: 1100px;
}
.pv-table-fit.pv-table-click .p-datatable-table {
	min-width: 900px;
}
/* layar sempit: tabel di-scroll di dalam card, halaman tidak ikut melebar */
.pv-table-fit .p-datatable-table-container,
.pv-table-modal .p-datatable-table-container {
	overflow-x: auto;
}

/* baris bisa diklik (Movements -> modal detail) */
.pv-table-click .p-datatable-tbody > tr {
	cursor: pointer;
}

/* tabel di dalam modal: tanpa min-width halaman */
.pv-table-modal .p-datatable-table {
	min-width: 760px;
}

/* -- Select (toolbar & filter) -- */
.pv-select.p-select {
	height: 2rem;
	border-radius: var(--radius, 8px);
	border-color: var(--line2);
	background: var(--surface);
	font: inherit;
	font-size: 0.875rem;
	box-shadow: none;
}

.pv-select.p-select:not(.p-disabled):hover {
	border-color: var(--faint);
}

.pv-select.p-select:not(.p-disabled).p-focus {
	border-color: var(--brand);
	outline: none;
	box-shadow: none;
}

.pv-select .p-select-label {
	display: flex;
	align-items: center;
	padding: 0 1.75rem 0 0.625rem;
	color: var(--ink);
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.pv-select.p-select .p-select-label.p-placeholder {
	color: var(--faint);
}

.pv-select .p-select-dropdown {
	width: 1.75rem;
	color: var(--muted);
}

/* -- modal detail Inventory: tinggi mengikuti isi, scroll di body -- */
.inv-dialog.p-dialog {
	max-height: 92vh;
	overflow: hidden;
	background: var(--surface, #ffffff);
	border-radius: 12px;
}

.inv-dialog-max.p-dialog {
	max-height: 100vh;
	border-radius: 0;
}
</style>
