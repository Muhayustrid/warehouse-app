<script setup>
// Halaman Serah Terima Gudang (SPA) — redesign bahasa visual production_workspace:
// .page-head + .toolbar + tabel custom .wo-body/.wo-row (sort 3-klik, paginasi
// client-side) + panel kaca. Data tetap dari report standar via data/serahTerima.js.
import { computed, onMounted, ref, watch } from 'vue'
import { ArrowDown, Check, ChevronLeft, ChevronRight, RefreshCw, Search, SearchX, Truck } from 'lucide-vue-next'
import { fetchSerahTerima, searchWarehouses, makeStockEntry } from '@/data/serahTerima'
import { fmtNum } from '@/lib/format'
import { toast } from '@/lib/toast'

const rows = ref([])
const loading = ref(false)
const search = ref('')
const statusTab = ref('all')
const warehouse = ref('')
const making = ref('') // _key baris yang sedang membuat draft SE

// bucket status berasal dari report (per_ordered native) — label Indonesia
// adalah nilai datanya; tab hanya memfilternya, dgn label Inggris.
const statusTabs = [
	{ label: 'All', value: 'all' },
	{ label: 'Not shipped', value: 'Belum Dikirim', dot: 'st-not' },
	{ label: 'Partial', value: 'Sebagian', dot: 'st-part' },
	{ label: 'Shipped', value: 'Terkirim', dot: 'st-done' },
]
const STRIP = { 'Belum Dikirim': 'strip-not', Sebagian: 'strip-part', Terkirim: 'strip-done' }
const FILL = { 'Belum Dikirim': 'fill-not', Sebagian: 'fill-part', Terkirim: 'fill-done' }

const counts = computed(() => {
	const c = { all: rows.value.length }
	rows.value.forEach((r) => (c[r.status_papan] = (c[r.status_papan] || 0) + 1))
	return c
})
const pct = (r) =>
	Number(r.qty_diminta) > 0 ? Math.min(100, (Number(r.qty_dikirim) / Number(r.qty_diminta)) * 100) : 0

// ---- sort 3-klik (pola FU94 production_workspace: asc → desc → normal) ----
const sortKey = ref('')
const sortDir = ref('')
function setSort(key) {
	if (sortKey.value !== key) {
		sortKey.value = key
		sortDir.value = 'asc'
	} else if (sortDir.value === 'asc') {
		sortDir.value = 'desc'
	} else {
		sortDir.value = ''
		sortKey.value = '' // klik ke-3 = normal: ikon header ikut hilang
	}
}
const SORT_FNS = {
	item: (r) => r.item_name,
	qty: (r) => Number(r.qty_diminta) || 0,
	mr: (r) => r.material_request,
}
function applySort(list) {
	if (!sortKey.value || !sortDir.value) return list
	const get = SORT_FNS[sortKey.value]
	const mul = sortDir.value === 'asc' ? 1 : -1
	const numeric = sortKey.value === 'qty'
	return [...list].sort((a, b) => {
		const x = get(a)
		const y = get(b)
		if (numeric) return (x - y) * mul
		return String(x || '').localeCompare(String(y || '')) * mul
	})
}

const filteredRows = computed(() => {
	let out = rows.value
	if (statusTab.value !== 'all') {
		out = out.filter((r) => r.status_papan === statusTab.value)
	}
	const q = search.value.trim().toLowerCase()
	if (q) {
		out = out.filter((r) =>
			[r.material_request, r.item_name, r.item_code, r.work_order, r.adonan].some((v) =>
				String(v || '').toLowerCase().includes(q),
			),
		)
	}
	return applySort(out)
})

// ---- paginasi client-side ala cold-pagination (25/50/100) ----
const PAGE_SIZES = [25, 50, 100]
const pageSize = ref(50)
const page = ref(1)
const totalPages = computed(() => Math.max(1, Math.ceil(filteredRows.value.length / pageSize.value)))
const pagedRows = computed(() =>
	filteredRows.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value),
)
function goPage(p) {
	page.value = Math.min(Math.max(1, p), totalPages.value)
}
watch([search, statusTab, rows, pageSize], () => (page.value = 1))

// dikelompokkan per tanggal MR (barisan consecutive pada halaman aktif)
const days = computed(() => {
	const out = []
	for (const r of pagedRows.value) {
		const d = String(r.transaction_date || '').slice(0, 10)
		if (out.at(-1)?.date !== d) out.push({ date: d, rows: [] })
		out.at(-1).rows.push(r)
	}
	return out
})
const dayLabel = (d) => {
	if (!d) return ''
	const x = new Date(d + 'T00:00:00')
	const today = new Date()
	const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
	const yesterday = new Date(today)
	yesterday.setDate(today.getDate() - 1)
	if (sameDay(x, today)) return 'Today'
	if (sameDay(x, yesterday)) return 'Yesterday'
	const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
	const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
	return `${DAYS[x.getDay()]}, ${x.getDate()} ${MONTHS[x.getMonth()]}${x.getFullYear() !== today.getFullYear() ? ' ' + x.getFullYear() : ''}`
}

async function load() {
	loading.value = true
	try {
		const res = await fetchSerahTerima(warehouse.value ? { gudang_tujuan: warehouse.value } : {})
		const data = Array.isArray(res?.result) ? res.result : []
		// baris total (non-dict) dari report dibuang; _key unik utk baris tabel
		rows.value = data
			.filter((r) => r && typeof r === 'object')
			.sort((a, b) => String(b.transaction_date).localeCompare(String(a.transaction_date)))
			.map((r, i) => ({
				...r,
				_key: `${r.material_request}|${r.item_code}|${r.work_order}|${i}`,
			}))
		syncWarehouseOptionsFromData()
	} catch (e) {
		toast.error(e.message)
	} finally {
		loading.value = false
	}
}

// opsi warehouse: site produksi punya 600+ gudang — dropdown diawali gudang
// yang muncul di data report; fokus di select menambah hasil pencarian
// server-side (like, limit 20) via searchWarehouses.
const warehouseOptions = ref([])

function mergeWarehouseOptions(names) {
	warehouseOptions.value = [
		...new Set([...names.filter(Boolean), ...warehouseOptions.value]),
	].sort((a, b) => a.localeCompare(b))
}

function syncWarehouseOptionsFromData() {
	mergeWarehouseOptions([...new Set(rows.value.map((r) => r.gudang_tujuan))])
}

let whLoaded = false
async function augmentWarehouseOptions() {
	if (whLoaded) return
	whLoaded = true
	try {
		const res = await searchWarehouses('')
		mergeWarehouseOptions((res || []).map((w) => w.name))
	} catch {
		/* biarkan opsi yg ada */
	}
}

watch(warehouse, () => load())

async function makeSE(row) {
	if (making.value) {
		return
	}
	making.value = row._key
	// buka tab sinkron SEBELUM await — window.open setelah await dianggap
	// popup spam oleh browser dan diblok diam-diam
	const win = window.open('about:blank', '_blank')
	try {
		const doc = await makeStockEntry(row.material_request)
		if (!doc?.name) {
			throw new Error('Mapper did not return a document')
		}
		if (win) {
			win.location = `/app/stock-entry/${encodeURIComponent(doc.name)}`
		} else {
			// popup diblok (langka pada klik nyata) — buka di tab yang sama
			toast.success(`Draft Stock Entry ${doc.name} created`)
			window.location.href = `/app/stock-entry/${encodeURIComponent(doc.name)}`
			return
		}
		toast.success(`Draft Stock Entry ${doc.name} created`)
	} catch (e) {
		win?.close()
		toast.error(e.message)
	} finally {
		making.value = ''
	}
}

onMounted(() => {
	load()
})
</script>

<template>
	<div class="page-head">
		<div class="ph-left">
			<h1>Handover Monitoring</h1>
			<p class="sub">Material Requests from production and how much has reached the warehouse.</p>
		</div>
	</div>

	<!-- tab status -->
	<div class="st-tabs" role="tablist" aria-label="Status">
		<button
			v-for="t in statusTabs"
			:key="t.value"
			role="tab"
			type="button"
			:aria-selected="statusTab === t.value"
			class="st-tab"
			:class="{ on: statusTab === t.value }"
			@click="statusTab = t.value"
		>
			<span v-if="t.dot" class="st-dot" :class="t.dot" />
			{{ t.label }}
			<span class="st-count">{{ counts[t.value] || 0 }}</span>
		</button>
	</div>

	<div class="toolbar">
		<label class="searchbox">
			<span class="sr-only">Search</span>
			<Search :size="15" :stroke-width="2" class="search-ico" aria-hidden="true" />
			<input v-model="search" type="search" class="input" placeholder="Search MR, batch, item, or work order" />
		</label>
		<select v-model="warehouse" class="select st-wh" aria-label="Destination warehouse" @focus="augmentWarehouseOptions">
			<option value="">All warehouses</option>
			<option v-for="w in warehouseOptions" :key="w" :value="w">{{ w }}</option>
		</select>
		<button class="btn" :disabled="loading" aria-label="Refresh" title="Refresh" @click="load()">
			<RefreshCw :size="14" :stroke-width="2" :class="{ spin: loading }" />
		</button>
	</div>

	<div class="wo-body st-body" :class="{ dim: loading }">
		<template v-if="filteredRows.length">
			<div class="wo-thead st-grid">
				<span>Batch</span>
				<button type="button" class="th-sort" :class="{ on: sortKey === 'item', asc: sortDir === 'asc' }" @click="setSort('item')">
					Item<ArrowDown :size="11" :stroke-width="2.4" class="sort-ico" aria-hidden="true" />
				</button>
				<button type="button" class="th-sort" :class="{ on: sortKey === 'qty', asc: sortDir === 'asc' }" @click="setSort('qty')">
					Shipped<ArrowDown :size="11" :stroke-width="2.4" class="sort-ico" aria-hidden="true" />
				</button>
				<span>Destination</span>
				<button type="button" class="th-sort" :class="{ on: sortKey === 'mr', asc: sortDir === 'asc' }" @click="setSort('mr')">
					Material Request<ArrowDown :size="11" :stroke-width="2.4" class="sort-ico" aria-hidden="true" />
				</button>
				<span></span>
			</div>

			<template v-for="day in days" :key="day.date">
				<div class="wo-row st-grid st-day">
					<span class="st-dayname">{{ dayLabel(day.date) }}</span>
					<span class="st-daycount">{{ day.rows.length }} {{ day.rows.length === 1 ? 'line' : 'lines' }}</span>
				</div>
				<div v-for="r in day.rows" :key="r._key" class="wo-row st-grid st-row">
					<span class="c-batch" :class="STRIP[r.status_papan]">
						<span v-if="r.adonan != null && r.adonan !== ''" class="st-batch">{{ r.adonan }}</span>
						<span v-else class="st-nobatch">–</span>
					</span>
					<span class="c-item">
						<span class="st-itemname">{{ r.item_name }}</span>
						<small class="st-itemcode">{{ r.item_code }}</small>
					</span>
					<span class="c-ship">
						<span class="st-qty">{{ fmtNum(r.qty_dikirim) }} <em>/ {{ fmtNum(r.qty_diminta) }} {{ r.stock_uom }}</em></span>
						<span
							class="st-bar"
							role="progressbar"
							:aria-valuenow="Math.round(pct(r))"
							aria-valuemin="0"
							aria-valuemax="100"
							:aria-label="`${r.item_name} shipped`"
						>
							<span class="st-fill" :class="FILL[r.status_papan]" :style="{ width: pct(r) + '%' }" />
						</span>
						<small v-if="Number(r.qty_sisa) > 0" class="st-sisa">{{ fmtNum(r.qty_sisa) }} {{ r.stock_uom }} left to ship</small>
					</span>
					<span class="c-dest">
						<span class="st-dest">{{ r.gudang_tujuan }}</span>
						<a
							v-if="r.work_order"
							:href="`/app/work-order/${encodeURIComponent(r.work_order)}`"
							target="_blank"
							class="st-wo"
							>{{ r.work_order }}</a
						>
					</span>
					<span class="c-mr">
						<a :href="`/app/material-request/${encodeURIComponent(r.material_request)}`" target="_blank" class="st-mr">{{
							r.material_request
						}}</a>
						<small class="st-mrstatus">{{ r.status_mr }}</small>
					</span>
					<span class="c-act">
						<button
							v-if="r.status_papan !== 'Terkirim'"
							type="button"
							class="btn btn-sm st-se"
							:title="`Create a draft Stock Entry for ${r.material_request}`"
							:disabled="making === r._key"
							@click="makeSE(r)"
						>
							<Truck :size="13" :stroke-width="2" class="st-seico" />
							<span class="st-selabel">Create Stock Entry</span>
						</button>
						<Check v-else :size="16" :stroke-width="2.4" class="st-check" aria-label="Shipped" />
					</span>
				</div>
			</template>
		</template>

		<div v-if="!filteredRows.length && !loading" class="empty-inset">
			<span class="eico"><SearchX :size="19" :stroke-width="1.8" /></span>
			<p class="etitle">Nothing matches</p>
			<p class="ehint">
				{{
					rows.length
						? 'Try a different search or status.'
						: 'No handover requests yet. They appear here once the warehouse requests finished batches.'
				}}
			</p>
		</div>
	</div>

	<div v-if="filteredRows.length" class="pagination-bar pagination-footer cold-pagination">
		<span class="st-pageinfo">Showing {{ fmtNum((page - 1) * pageSize + 1) }}–{{ fmtNum(Math.min(page * pageSize, filteredRows.length)) }} of {{ fmtNum(filteredRows.length) }}</span>
		<label class="page-size-control">
			<span>Per page</span>
			<select class="select" :value="pageSize" aria-label="Rows per page" @change="pageSize = Number($event.target.value)">
				<option v-for="size in PAGE_SIZES" :key="size" :value="size">{{ size }}</option>
			</select>
		</label>
		<div class="pagination-buttons">
			<button class="btn btn-sm" :disabled="page <= 1" @click="goPage(page - 1)">
				<ChevronLeft :size="14" :stroke-width="2" />‹ Prev
			</button>
			<button class="btn btn-sm" :disabled="page >= totalPages" @click="goPage(page + 1)">
				Next ›<ChevronRight :size="14" :stroke-width="2" />
			</button>
		</div>
	</div>
</template>

<style scoped>
.sr-only {
	position: absolute;
	width: 1px;
	height: 1px;
	padding: 0;
	margin: -1px;
	overflow: hidden;
	clip: rect(0, 0, 0, 0);
	white-space: nowrap;
	border: 0;
}

/* tab status: underline ala panel-head production_workspace */
.st-tabs {
	display: flex;
	gap: 4px;
	margin-bottom: 12px;
	border-bottom: 1px solid var(--line, #e5e5e0);
	overflow-x: auto;
}
.st-tab {
	display: inline-flex;
	align-items: center;
	gap: 7px;
	flex: none;
	height: 38px;
	padding: 0 12px;
	border: 0;
	border-bottom: 2px solid transparent;
	background: none;
	font: inherit;
	font-size: 13px;
	color: var(--muted, #73726e);
	cursor: pointer;
	white-space: nowrap;
}
.st-tab:hover { color: var(--ink, #1f2937); }
.st-tab.on {
	border-bottom-color: var(--ink, #1f2937);
	color: var(--ink, #1f2937);
	font-weight: 600;
}
.st-dot { width: 7px; height: 7px; border-radius: 50%; flex: none; }
.st-not { background: #f97316; }
.st-part { background: #3b82f6; }
.st-done { background: #22c55e; }
.st-count {
	min-width: 20px;
	padding: 0 5px;
	border-radius: 999px;
	background: var(--grey-bg, #f1f1ec);
	color: var(--faint, #98978f);
	font-size: 11px;
	font-weight: 600;
	text-align: center;
}
.st-tab.on .st-count { background: var(--ink, #1f2937); color: #fff; }

.st-wh { width: auto; min-width: 180px; max-width: 280px; }
.spin { animation: st-spin 0.8s linear infinite; }
@keyframes st-spin { to { transform: rotate(360deg); } }

/* grid tabel: Batch | Item | Shipped | Destination | Material Request | Action */
.st-grid {
	display: grid;
	grid-template-columns: 72px minmax(160px, 1.4fr) minmax(160px, 1fr) minmax(120px, 0.7fr) minmax(130px, 0.7fr) 172px;
	gap: 14px;
	align-items: center;
}
.st-body { user-select: text; }
.st-body.dim { opacity: 0.55; pointer-events: none; }
.wo-row { cursor: default; }
.st-day {
	padding: 8px 16px;
	background: rgba(243, 246, 249, 0.7);
	font-size: 11.5px;
	color: var(--muted, #73726e);
	cursor: default;
}
.st-day:hover { background: rgba(243, 246, 249, 0.7); box-shadow: none; }
.st-dayname { font-weight: 700; color: var(--ink, #1f2937); grid-column: 1 / span 3; }
.st-daycount { grid-column: 4 / -1; text-align: right; }

/* strip warna status pada kolom batch */
.c-batch { display: flex; align-items: center; }
.st-batch {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	min-width: 40px;
	height: 30px;
	padding: 0 8px;
	border: 1px solid var(--line2, #e2e2dd);
	border-radius: 8px;
	background: rgba(255, 255, 255, 0.82);
	font-size: 15px;
	font-weight: 700;
	font-variant-numeric: tabular-nums;
}
.st-nobatch { color: var(--faint, #98978f); }
.strip-not { position: relative; padding-left: 10px; }
.strip-not::before,
.strip-part::before,
.strip-done::before {
	content: '';
	position: absolute;
	left: -16px;
	top: -10px;
	bottom: -10px;
	width: 3px;
	border-radius: 2px;
}
.strip-not::before { background: #f97316; }
.strip-part::before { background: #3b82f6; }
.strip-done::before { background: #22c55e; }

.c-item { min-width: 0; }
.st-itemname { display: block; font-weight: 600; font-size: 13.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.st-itemcode { display: block; font-size: 11.5px; color: var(--faint, #98978f); }

.c-ship { min-width: 0; }
.st-qty { display: block; white-space: nowrap; font-variant-numeric: tabular-nums; }
.st-qty em { font-style: normal; color: var(--muted, #73726e); font-size: 12.5px; }
.st-bar {
	display: block;
	margin-top: 5px;
	height: 5px;
	border-radius: 999px;
	background: var(--grey-bg, #f1f1ec);
	overflow: hidden;
}
.st-fill { display: block; height: 100%; border-radius: 999px; }
.fill-not { background: #fb923c; }
.fill-part { background: #3b82f6; }
.fill-done { background: #22c55e; }
.st-sisa { display: block; margin-top: 3px; font-size: 11.5px; color: #c2410c; }

.c-dest, .c-mr { min-width: 0; }
.st-dest, .st-mr { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.st-mr, .st-wo { color: inherit; text-decoration: underline transparent; text-underline-offset: 2px; }
.st-mr:hover, .st-wo:hover { text-decoration-color: currentColor; }
.st-wo, .st-mrstatus { display: block; font-size: 11.5px; color: var(--faint, #98978f); }

.c-act { text-align: right; }
.st-se { display: inline-flex; align-items: center; gap: 6px; }
.st-seico { flex: none; }
.st-check { color: #16a34a; vertical-align: middle; }

/* mobile ≤820px: grid-areas */
@media (max-width: 820px) {
	.wo-thead { display: none; }
	.st-row {
		grid-template-columns: 1fr auto;
		grid-template-areas:
			'batch act'
			'item item'
			'ship ship'
			'dest mr';
		row-gap: 7px;
	}
	.st-row .c-batch { grid-area: batch; }
	.st-row .c-item { grid-area: item; }
	.st-row .c-ship { grid-area: ship; }
	.st-row .c-dest { grid-area: dest; }
	.st-row .c-mr { grid-area: mr; text-align: right; }
	.st-row .c-act { grid-area: act; text-align: right; }
	.st-selabel { display: none; }
	.strip-not::before, .strip-part::before, .strip-done::before { top: 0; bottom: 0; }
	.pagination-bar > span { flex-basis: 100%; order: -1; }
	.pagination-buttons { width: 100%; }
	.pagination-buttons .btn { flex: 1; }
}
</style>
