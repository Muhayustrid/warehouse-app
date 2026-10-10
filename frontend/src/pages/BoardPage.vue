<script setup>
// Papan Serah Terima Gudang (SPA, W33) — port paritas penuh dari page
// klasik gudang_request: search, filter builder, UOM switcher, pemilih
// kolom, kepadatan, checklist + deteksi grup, dialog bulk/group (qty-only,
// semantik W30), cancel tunggal/grup, Load more.
// Bahasa visual production_workspace: .page-head/.toolbar/.wo-body/.wo-row.
import { ref, computed, watch, onMounted } from 'vue'
import { Search, RefreshCw, SearchX } from 'lucide-vue-next'
import { toast } from '@/lib/toast'
import { fetchWorkOrders, fetchFilterFields, cancelRequest, cancelGroupRequest } from '@/data/board'
import { loadPref, savePref } from '@/lib/prefs'
import { fmtNum } from '@/lib/format'
import dayjs from 'dayjs'
import FilterBuilder from '@/components/FilterBuilder.vue'
import RequestDialog from '@/components/RequestDialog.vue'
import GroupRequestDialog from '@/components/GroupRequestDialog.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'

// pilihan jumlah baris per halaman (permintaan user: 20/50/100/250)
const PAGE_SIZES = [20, 50, 100, 250]

// ---- state
const rows = ref([])
const total = ref(0)
const loading = ref(false)
const search = ref('')
const filters = ref([])
const fieldMeta = ref(null)
const selectedNames = ref([])
const qtyUom = ref(loadPref('qty_uom', ''))
const savedSize = loadPref('page_size', 50)
const pageSize = ref(PAGE_SIZES.includes(savedSize) ? savedSize : 50)

const bulkDialog = ref(false)
const groupDialog = ref(false)
const cancelOpen = ref(false)
const cancelTarget = ref(null) // { mr, plan, size } | null
// baris Requested yang dilibatkan utk cancel — tampil di bar mengapung,
// gaya yang sama dgn bar Create Request (saling eksklusif dgn seleksi)
const cancelPick = ref(null)

// ---- UOM kolom Qty
const uomOptions = computed(() => {
	const opts = []
	rows.value.forEach((r) => {
		if (r.stock_uom && !opts.includes(r.stock_uom)) opts.push(r.stock_uom)
	})
	rows.value.forEach((r) => {
		if (r.display_uom && !opts.includes(r.display_uom)) opts.push(r.display_uom)
	})
	return opts
})

function isDisplayUom(r, uom) {
	const factor = Number(r.display_conversion_factor)
	return !!(
		r.display_uom &&
		r.display_uom !== r.stock_uom &&
		isFinite(factor) &&
		factor > 0 &&
		uom === r.display_uom
	)
}

function qtyValue(r) {
	if (isDisplayUom(r, qtyUom.value)) {
		return { n: fmtNum(r.expected_units != null ? r.expected_units : 0), uom: r.display_uom }
	}
	return { n: fmtNum(r.produced_qty || 0), uom: r.stock_uom }
}

// ---- status & kelompok hari
const stateOf = (r) => (r.request_active ? 'requested' : r.request_shipped ? 'shipped' : 'ready')
const VIEWS = [
	{ key: 'all', label: 'All' },
	{ key: 'ready', label: 'Ready' },
	{ key: 'requested', label: 'Requested' },
	{ key: 'shipped', label: 'Shipped' },
]
const view = ref('all')
const counts = computed(() => {
	const c = { all: rows.value.length, ready: 0, requested: 0, shipped: 0 }
	rows.value.forEach((r) => c[stateOf(r)]++)
	return c
})
const shownRows = computed(() =>
	view.value === 'all' ? rows.value : rows.value.filter((r) => stateOf(r) === view.value),
)
const days = computed(() => {
	const out = []
	for (const r of shownRows.value) {
		const d = String(r.creation || '').slice(0, 10)
		if (out.at(-1)?.date !== d) out.push({ date: d, rows: [] })
		out.at(-1).rows.push(r)
	}
	return out
})
const dayLabel = (d) => {
	const x = dayjs(d)
	if (x.isSame(dayjs(), 'day')) return 'Today'
	if (x.isSame(dayjs().subtract(1, 'day'), 'day')) return 'Yesterday'
	return x.format('dddd')
}
const isSelectable = (r) => !r.request_active && !r.request_shipped
function dayState(day) {
	const sel = day.rows.filter(isSelectable)
	const n = sel.filter((r) => selectedNames.value.includes(r.name)).length
	return { any: sel.length > 0, all: sel.length > 0 && n === sel.length, some: n > 0 && n < sel.length }
}
function toggleDay(day, checked) {
	cancelPick.value = null
	const names = day.rows.filter(isSelectable).map((r) => r.name)
	selectedNames.value = checked
		? [...new Set([...selectedNames.value, ...names])]
		: selectedNames.value.filter((n) => !names.includes(n))
}

function setUom(uom) {
	selectedNames.value = []
	cancelPick.value = null
	qtyUom.value = uom
	savePref('qty_uom', uom)
}

// ---- seleksi
const selectableRows = computed(() => shownRows.value.filter(isSelectable))
const selectedRows = computed(() => rows.value.filter((r) => selectedNames.value.includes(r.name)))
const nSelected = computed(() => selectedRows.value.length)
const cancelPickRow = computed(() => rows.value.find((r) => r.name === cancelPick.value) || null)

// W19: trigger grup — ≥2 baris, satu item yang sama, item terdaftar grup
const groupSelection = computed(() => {
	if (
		nSelected.value >= 2 &&
		selectedRows.value.every((r) => r.group_item) &&
		new Set(selectedRows.value.map((r) => r.production_item)).size === 1
	) {
		return selectedRows.value
	}
	return null
})

function toggleRow(r) {
	if (r.request_shipped) {
		return
	}
	if (r.request_active) {
		// klik baris Requested: libatkan utk cancel di bar mengapung
		// (bersihkan seleksi biasa supaya dua bar tidak tampil bersamaan)
		selectedNames.value = []
		cancelPick.value = cancelPick.value === r.name ? null : r.name
		return
	}
	cancelPick.value = null
	const i = selectedNames.value.indexOf(r.name)
	if (i >= 0) {
		selectedNames.value.splice(i, 1)
	} else {
		selectedNames.value.push(r.name)
	}
}

const allChecked = computed(
	() =>
		selectableRows.value.length > 0 &&
		nSelected.value >= selectableRows.value.length,
)
const someChecked = computed(() => nSelected.value > 0 && nSelected.value < selectableRows.value.length)

function toggleAll(checked) {
	cancelPick.value = null
	if (checked) {
		selectedNames.value = selectableRows.value.map((r) => r.name)
	} else {
		selectedNames.value = []
	}
}

// ---- muat data (pagination server-side)
function activeFilters() {
	return filters.value.filter((f) =>
		Array.isArray(f.value)
			? f.value.some((x) => String(x || '').trim() !== '')
			: String(f.value || '').trim() !== '',
	)
}

// halaman dimuat dari awal setiap kali filter/ukuran berubah (offset aman)
async function load(page = 1) {
	loading.value = true
	try {
		const res = await fetchWorkOrders({
			search: search.value,
			filters: activeFilters(),
			limitStart: (page - 1) * pageSize.value,
			pageLen: pageSize.value,
		})
		// server balas {rows, total} — bentuk baru pagination
		rows.value = Array.isArray(res?.rows) ? res.rows : []
		total.value = Number(res?.total || 0)
		selectedNames.value = []
		cancelPick.value = null
		// normalisasi pilihan uom tersimpan (tak ada di opsi → stock uom)
		if (rows.value.length) {
			const opts = uomOptions.value
			if (!qtyUom.value || !opts.includes(qtyUom.value)) {
				qtyUom.value = opts[0] || ''
				savePref('qty_uom', qtyUom.value)
			}
		}
	} catch (e) {
		toast.error(e.message)
	} finally {
		loading.value = false
	}
}

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const page = ref(1)
function goPage(p) {
	const next = Math.min(Math.max(1, p), totalPages.value)
	page.value = next
	load(next)
}
function setPageSize(n) {
	pageSize.value = n
	savePref('page_size', n)
	goPage(1)
}

let searchTimer = null
watch(search, () => {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(() => load(1), 350)
})

// filter berubah: FilterBuilder emit 'change' (bukan watch deep — see quirk)
let filterTimer = null
function onFilterChange() {
	clearTimeout(filterTimer)
	filterTimer = setTimeout(() => load(1), 300)
}

function refresh() {
	clearTimeout(searchTimer)
	clearTimeout(filterTimer)
	load(page.value)
}

onMounted(async () => {
	try {
		fieldMeta.value = await fetchFilterFields()
	} catch (e) {
		/* filter tetap bisa dipakai tanpa meta? tidak — tapi jangan blok papan */
	}
	load(1)
})

// ---- aksi
function onPrimaryAction() {
	if (groupSelection.value) {
		groupDialog.value = true
		return
	}
	if (selectedRows.value.length) {
		bulkDialog.value = true
	}
}

function onBulkDone({ ok, fail }) {
	if (ok && !fail) {
		toast.success(`${ok} request${ok > 1 ? 's' : ''} created`)
	}
	load(page.value)
}

function onGroupDone({ materialRequest, size }) {
	toast.success(`Group request created: ${materialRequest} · ${size} Work Orders`)
	load(page.value)
}

function askCancel() {
	const r = cancelPickRow.value
	if (!r) {
		return
	}
	cancelTarget.value = {
		mr: r.custom_handover_material_request,
		plan: r.box_plan || null,
		size: Number(r.group_size || 0),
		group: !!r.box_plan || Number(r.group_size || 0) > 1,
	}
	cancelOpen.value = true
}

const cancelOptions = computed(() => {
	const t = cancelTarget.value
	if (!t) {
		return {}
	}
	return t.group
		? {
				title: 'Cancel Group Request',
				message: `Cancel the ENTIRE group (${t.size} Work Orders)? All unshipped members are cancelled together.`,
				confirmLabel: 'Cancel Group',
				theme: 'danger',
			}
		: {
				title: 'Cancel Request',
				message: `Cancel handover request ${t.mr} that has not been shipped?`,
				confirmLabel: 'Cancel Request',
				theme: 'danger',
			}
})

async function doCancel() {
	const t = cancelTarget.value
	if (!t) {
		return
	}
	try {
		if (t.plan) {
			await cancelGroupRequest(t.plan)
			toast.warning('Group request cancelled')
		} else {
			await cancelRequest(t.mr)
			toast.warning('Request cancelled')
		}
	} catch (e) {
		toast.error(e.message)
	}
	load(page.value)
}
</script>

<template>
	<div class="board">
		<!-- header -->
		<div class="page-head">
			<div class="ph-left">
				<h1>Handover Requests</h1>
				<p class="sub">
					Finished batches from production. Select the ones the warehouse should receive and create a request.
				</p>
			</div>
		</div>

		<!-- toolbar: search + tab status segmented + filter + display + uom + refresh -->
		<div class="toolbar">
			<div class="searchbox">
				<Search :size="15" :stroke-width="2" class="search-ico" />
				<input
					v-model="search"
					class="input"
					type="search"
					placeholder="Search batch, item, or work order"
					aria-label="Search batch, item, or work order"
					@keydown.enter="refresh"
				/>
			</div>
			<div class="dseg" role="tablist" aria-label="Status">
				<button
					v-for="v in VIEWS"
					:key="v.key"
					type="button"
					role="tab"
					class="dseg-btn"
					:class="{ on: view === v.key }"
					:aria-selected="view === v.key"
					@click="view = v.key; selectedNames = []; cancelPick = null"
				>
					{{ v.label }}
					<span class="dseg-count">{{ counts[v.key] }}</span>
				</button>
			</div>
			<FilterBuilder v-model="filters" :meta="fieldMeta" @change="onFilterChange" />
			<select
				v-if="uomOptions.length > 1"
				class="select uom-select"
				:value="qtyUom"
				aria-label="Qty unit"
				@change="setUom($event.target.value)"
			>
				<option v-for="o in uomOptions" :key="o" :value="o">{{ o }}</option>
			</select>
			<button
				type="button"
				class="btn iconbtn"
				:disabled="loading"
				aria-label="Refresh"
				title="Refresh"
				@click="refresh()"
			>
				<RefreshCw :size="14" :stroke-width="2" />
			</button>
		</div>

		<!-- daftar per hari produksi -->
		<div class="wo-body" :class="{ 'is-loading': loading }">
			<div v-if="days.length" class="wo-thead">
				<span></span>
				<span>Batch</span>
				<span>Item</span>
				<span class="th-kanan">Qty</span>
				<span>Work Order</span>
				<span>Status</span>
			</div>
			<template v-for="day in days" :key="day.date">
				<div class="dayhead">
					<span class="dlabel">
						{{ dayLabel(day.date) }}<span class="ddate">{{ dayjs(day.date).format('D MMM YYYY') }}</span>
					</span>
					<span class="dcount">{{ day.rows.length }} {{ day.rows.length === 1 ? 'batch' : 'batches' }}</span>
					<label v-if="dayState(day).any" class="dcheck">
						<input
							type="checkbox"
							:checked="dayState(day).all"
							:indeterminate.prop="dayState(day).some"
							:aria-label="`Select ready batches from ${dayLabel(day.date)}`"
							@change="toggleDay(day, $event.target.checked)"
						/>
					</label>
				</div>
				<div
					v-for="r in day.rows"
					:key="r.name"
					class="wo-row"
					role="button"
					tabindex="0"
					:class="{
						'is-selected': selectedNames.includes(r.name),
						'is-cancel': cancelPick === r.name,
						shipped: r.request_shipped,
						'st-ready': stateOf(r) === 'ready',
						'st-requested': stateOf(r) === 'requested',
						'st-shipped': stateOf(r) === 'shipped',
					}"
					:aria-label="`Select ${r.item_name} batch ${r.custom_adonan_ke || r.name}`"
					@click="toggleRow(r)"
					@keydown.enter.prevent="toggleRow(r)"
				>
					<span class="c-sel">
						<input
							type="checkbox"
							:disabled="!isSelectable(r)"
							:checked="selectedNames.includes(r.name)"
							:aria-label="`Select ${r.item_name} batch ${r.custom_adonan_ke || r.name}`"
							@click.stop
							@change="toggleRow(r)"
						/>
					</span>
					<span class="c-batch">
						<span v-if="r.custom_adonan_ke" class="btile">{{ r.custom_adonan_ke }}</span>
						<span v-else class="bdash">–</span>
					</span>
					<span class="c-item">
						<span class="wo-prod">
							{{ r.item_name }}
							<small>{{ r.production_item }}</small>
						</span>
					</span>
					<span class="wo-qty c-qty">
						<span class="qmain">{{ qtyValue(r).n }}</span>
						<span class="qsub">{{ qtyValue(r).uom }}</span>
					</span>
					<span class="c-wo">
						<a
							:href="`/app/work-order/${encodeURIComponent(r.name)}`"
							target="_blank"
							class="rowlink"
							@click.stop
							>{{ r.name }}</a
						>
						<small class="wsub">{{ r.fg_warehouse }}</small>
					</span>
					<span class="c-status">
						<span v-if="stateOf(r) === 'ready'" class="badge b-run">Ready</span>
						<span v-else-if="stateOf(r) === 'requested'" class="chip chip-warn">Requested</span>
						<span v-else class="badge b-done">Shipped</span>
						<span v-if="r.custom_handover_material_request" class="mrline">
							<a
								:href="`/app/material-request/${encodeURIComponent(r.custom_handover_material_request)}`"
								target="_blank"
								class="rowlink"
								@click.stop
								>{{ r.custom_handover_material_request }}</a
							>
							<template v-if="r.box_plan || r.group_size > 1">, group of {{ r.group_size || 0 }}</template>
						</span>
					</span>
				</div>
			</template>
			<div v-if="!shownRows.length && !loading" class="empty-inset">
				<span class="eico"><SearchX :size="19" :stroke-width="1.8" /></span>
				<p class="etitle">No batches here</p>
				<p class="ehint">
					{{
						rows.length
							? `No ${VIEWS.find((v) => v.key === view).label.toLowerCase()} batches in this list.`
							: 'No finished batches match. Try a different search or clear the filters.'
					}}
				</p>
				<button v-if="rows.length" type="button" class="linkbtn" @click="view = 'all'">Show all</button>
			</div>
		</div>

		<!-- pagination server-side: ukuran halaman 20/50/100/250 -->
		<div v-if="total" class="pagination-bar pagination-footer cold-pagination">
			<span>
				Showing {{ fmtNum((page - 1) * pageSize + 1) }}–{{ fmtNum(Math.min(page * pageSize, total)) }}
				of {{ fmtNum(total) }}
			</span>
			<label class="page-size-control">
				<span>Per page</span>
				<select class="select" :value="pageSize" aria-label="Rows per page" @change="setPageSize(Number($event.target.value))">
					<option v-for="n in PAGE_SIZES" :key="n" :value="n">{{ n }}</option>
				</select>
			</label>
			<div class="pagination-buttons">
				<button type="button" class="btn btn-sm" :disabled="loading || page <= 1" @click="goPage(page - 1)">
					‹ Prev
				</button>
				<span class="pg-num">{{ page }} / {{ totalPages }}</span>
				<button type="button" class="btn btn-sm" :disabled="loading || page >= totalPages" @click="goPage(page + 1)">
					Next ›
				</button>
			</div>
		</div>

		<!-- bar aksi seleksi (mengapung) -->
		<div v-if="nSelected" class="floatbar">
			<span class="fb-count">{{ nSelected }} selected</span>
			<button type="button" class="linkbtn fb-clear" @click="selectedNames = []">Clear</button>
			<button type="button" class="btn btn-sm btn-primary" @click="onPrimaryAction">
				{{
					groupSelection
						? `Create Group Request (${nSelected})`
						: `Create Request (${nSelected})`
				}}
			</button>
		</div>

		<!-- bar cancel (mengapung, gaya yang sama) — muncul saat baris Requested diklik -->
		<div v-if="cancelPickRow" class="floatbar">
			<span class="fb-count">
				{{
					cancelPickRow.box_plan || cancelPickRow.group_size > 1
						? `Group ${cancelPickRow.box_plan || cancelPickRow.custom_handover_material_request} · ${fmtNum(Number(cancelPickRow.group_size || 0))} Work Orders`
						: cancelPickRow.custom_handover_material_request
				}}
			</span>
			<button type="button" class="linkbtn fb-clear" @click="cancelPick = null">Clear</button>
			<button type="button" class="btn btn-sm btn-danger" @click="askCancel()">
				{{ cancelPickRow.box_plan || cancelPickRow.group_size > 1 ? 'Cancel Group' : 'Cancel Request' }}
			</button>
		</div>

		<!-- dialog -->
		<RequestDialog v-model="bulkDialog" :rows="selectedRows" @done="onBulkDone" />
		<GroupRequestDialog v-model="groupDialog" :rows="groupSelection || []" @done="onGroupDone" />
		<ConfirmDialog v-model="cancelOpen" :options="cancelOptions" :on-confirm="doCancel" />
	</div>
</template>

<style scoped>
/* ---- grid kolom (desktop), satu bentuk tetap: header & baris SELALU sejajar.
   [sel][batch][item — lebar fleksibel][qty — rata kanan][work order][status]
   Qty diberi lebar cukup + gap besar sebelum Work Order supaya angka tak
   menempel ke kolom sebelahnya (keluhan proporsi). */
.wo-thead, .wo-row {
  grid-template-columns: 32px 56px minmax(220px, 1.6fr) 110px minmax(170px, 1fr) 150px;
  column-gap: 20px;
}
.wo-row .c-qty { padding-right: 4px; }
.pg-num { font-size: 12.5px; color: var(--muted, inherit); font-variant-numeric: tabular-nums; min-width: 52px; text-align: center; }

.th-kanan { text-align: right; }
.uom-select { width: auto; min-width: 96px; }
.iconbtn { width: 34px; padding: 0; display: grid; place-items: center; }
.dseg-count {
  min-width: 17px;
  height: 17px;
  border-radius: 9px;
  background: var(--grey-bg, rgba(0, 0, 0, 0.06));
  color: var(--muted, inherit);
  font-size: 10.5px;
  font-weight: 700;
  display: inline-grid;
  place-items: center;
  padding: 0 4px;
}
.dseg-btn.on .dseg-count { background: var(--brand-soft, rgba(102, 163, 191, 0.18)); color: var(--brand-strong, inherit); }

/* kepala grup hari — satu baris (nowrap), label + tanggal + jumlah sejajar */
.dayhead {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 16px;
  border-top: 1px solid var(--line, rgba(0, 0, 0, 0.08));
  background: rgba(243, 246, 249, 0.7);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted, inherit);
  flex-wrap: nowrap;
}
.dayhead .dlabel, .dayhead .dcount { white-space: nowrap; }
.dayhead .ddate {
  margin-left: 8px;
  font-weight: 500;
  letter-spacing: 0.02em;
  text-transform: none;
  color: var(--faint, inherit);
  font-variant-numeric: tabular-nums;
}
.dayhead .dcount { font-weight: 500; letter-spacing: 0; text-transform: none; color: var(--faint, inherit); }
.dayhead .dcheck { margin-left: auto; display: inline-flex; }
.dayhead input { accent-color: var(--brand, currentColor); }

/* sel baris */
.wo-row input[type="checkbox"] { accent-color: var(--brand, currentColor); }
.c-sel { display: grid; place-items: center; }
.c-item, .c-wo { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.c-wo small, .c-wo .wsub { color: var(--faint, inherit); font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.c-status { display: flex; flex-direction: column; align-items: flex-start; gap: 3px; min-width: 0; }
.mrline { font-size: 11px; color: var(--faint, inherit); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
.rowlink { color: var(--brand-strong, inherit); text-decoration: none; }
.rowlink:hover { text-decoration: underline; }
.btile {
  display: inline-grid;
  place-items: center;
  min-width: 40px;
  height: 30px;
  padding: 0 6px;
  border: 1px solid var(--line2, var(--line, rgba(0, 0, 0, 0.1)));
  border-radius: 8px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.bdash { color: var(--faint, inherit); padding-left: 12px; }

/* warna baris per status — samakan dgn pill tab (info/warn/ok) */
.wo-row.st-ready { background: var(--info-bg, #e5eaf3); }
.wo-row.st-requested { background: var(--warn-bg, #f7ecd2); }
.wo-row.st-shipped { background: var(--ok-soft, #e3ede4); }
.wo-row.st-requested:hover { background: var(--warn-bg, #f7ecd2); box-shadow: inset 2.5px 0 0 var(--warn-ink, inherit); }
.wo-row.st-shipped:hover { background: var(--ok-soft, #e3ede4); box-shadow: none; }

/* state baris */
.wo-row.is-selected, .wo-row.is-selected:hover { background: var(--brand-soft, rgba(102, 163, 191, 0.14)); box-shadow: inset 2.5px 0 0 var(--brand, currentColor); }
.wo-row.is-cancel, .wo-row.is-cancel:hover { background: var(--warn-bg, #f7ecd2); box-shadow: inset 2.5px 0 0 var(--warn-ink, inherit); }
.wo-row.shipped { cursor: default; }
.wo-row.shipped:hover { box-shadow: none; }
.wo-body.is-loading { opacity: 0.5; pointer-events: none; }

/* mobile ≤820px: thead hilang, baris menumpuk (auto-placement: sel dgn
   grid-column 1/-1 tiap baris sendiri; status dipaksa pojok kanan atas) */
@media (max-width: 820px) {
  /* bar mengapung di atas bottom-nav HP */
  .floatbar { bottom: calc(76px + env(safe-area-inset-bottom)); }
  .wo-thead { display: none; }
  /* toolbar rapi: tumpuk — tab status geser menyamping (jangan potong
     "Shipped"), cari selebar penuh; filter + uom + refresh di baris bawah */
  .toolbar { flex-wrap: wrap; }
  .toolbar .dseg { flex: 1 1 100%; min-width: 0; max-width: 100%; overflow-x: auto; scrollbar-width: none; }
  .toolbar .dseg::-webkit-scrollbar { display: none; }
  .toolbar .dseg-btn { flex: none; }
  .toolbar .searchbox { flex: 1 1 100%; max-width: none; min-width: 0; }
  .wo-row { grid-template-columns: auto 1fr auto; gap: 3px 12px; padding: 12px 14px; }
  .c-batch, .c-item, .c-wo, .c-qty { grid-column: 1 / -1; }
  .c-status { grid-column: 3; grid-row: 1; align-items: flex-end; }
  .c-batch { order: 6; }
  .dayhead { padding: 6px 14px; }
}

/* bar aksi mengapung */
.floatbar {
  position: fixed;
  bottom: 22px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 40;
  display: flex;
  align-items: center;
  gap: 10px;
  max-width: calc(100vw - 32px);
  padding: 6px 6px 6px 16px;
  border: 1px solid var(--line, rgba(0, 0, 0, 0.08));
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.92);
  -webkit-backdrop-filter: blur(20px) saturate(160%);
  backdrop-filter: blur(20px) saturate(160%);
  box-shadow: 0 18px 48px -16px rgba(36, 48, 58, 0.3);
}
.fb-count { font-size: 12.5px; font-weight: 600; color: var(--ink, inherit); white-space: nowrap; }
.fb-clear { font-size: 12.5px; color: var(--muted, inherit); }

/* tombol merah (cancel) — production tak punya varian btn-danger */
.btn-danger { background: var(--bad-bg, #f6e1dc); border-color: transparent; color: var(--bad-ink, #9c4736); }
.btn-danger:hover:not(:disabled) { background: var(--bad-ink, #9c4736); color: #fff; }
</style>
