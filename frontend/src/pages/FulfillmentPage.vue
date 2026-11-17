<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
	AlertTriangle,
	ChevronRight,
	Filter,
	Inbox,
	Printer,
	RefreshCw,
	Search,
	Tag,
	X,
} from 'lucide-vue-next'
import {
	fetchOrderQueue,
	fetchPackingSlips,
	fetchPackingSlipsLabelsHtml,
} from '@/data/fulfillment'
import { fmtDate } from '@/lib/format'
import PrintPreviewModal from '@/components/fulfillment/PrintPreviewModal.vue'
import PackingSlipPage from '@/pages/PackingSlipPage.vue'

const router = useRouter()

// Tab = tahap flow native (SO -> Picking List -> Packing Slip -> DN).
// Tab mengarahkan filter stage queue; dokumen tetap per-SO di workspace.
const TABS = [
	{ label: 'Order', value: 'order', stages: 'open' },
	{ label: 'Picking', value: 'picking', stages: 'picking' },
	{ label: 'Packing', value: 'packing', stages: 'packing,ready' },
	{ label: 'Delivery', value: 'delivery', stages: 'partially_delivered,completed' },
]

const VALID_TABS = new Set(TABS.map((t) => t.value))

const PAGE_SIZES = [10, 25, 50]

const company = ref('')
const companies = ref([])
const profile = ref(null)
const counts = ref({ all: 0 })
const rows = ref([])
const total = ref(0)
const page = ref(1)
const pageLength = ref(10)
const search = ref('')
const fromDate = ref('')
const toDate = ref('')
const loading = ref(false)
const error = ref('')
const filterOpen = ref(false)
const filterPopoverRef = ref(null)

const route = useRoute()

function tabFromQuery() {
	const v = String(route.query.view || 'order')
	return VALID_TABS.has(v) ? v : 'order'
}

const activeTab = ref(tabFromQuery())
const pickDate = ref(new Date(Date.now() + 86400000).toISOString().slice(0, 10))

const printModalOpen = ref(false)
const printModalTitle = ref('')
const printModalItems = ref([])

// Tab Packing: ringkasan hasil packing per SO (dari Packing Slip).
const packingBySo = ref({})

async function loadPackingSummary() {
	try {
		const res = await fetchPackingSlips(company.value || undefined, '', '')
		const map = {}
		for (const row of res.slips || []) map[row.sales_order] = row
		packingBySo.value = map
	} catch {
		packingBySo.value = {}
	}
}

function packingStatus(row) {
	const p = packingBySo.value[row.sales_order]
	if (!p) return null
	if (!p.editable) return { label: 'Read-only (DN submit)', cls: 'b-ro' }
	if (p.packing?.packed) return { label: 'Sudah Diinput', cls: 'b-edit' }
	return { label: 'Belum Packing', cls: 'b-draft' }
}

// Tab "Semua" hilang: aktif tab = filter stage. Counts per tab dihitung dari
// counts per stage backend.
function tabCount(tab) {
	return tab.stages
		.split(',')
		.reduce((sum, s) => sum + (counts.value[s] || 0), 0)
}

let loadToken = 0

const dryLabel = computed(() => profile.value?.dry_display_name || 'Dry')
const frozenLabel = computed(() => profile.value?.frozen_display_name || 'Frozen')
const activeFilterCount = computed(() => {
	let c = 0
	if (fromDate.value || toDate.value) c++
	if (search.value) c++
	return c
})

// Tab Packing: tombol Filter di toolbar membuka panel filter ala ERPNext
// pada list Packing Slip (komunikasi lewat ref + defineExpose).
const packingRef = ref(null)
const packingFilterCount = ref(0)

function onFilterClick() {
	if (activeTab.value === 'packing') {
		packingRef.value?.toggleFilter()
	} else {
		filterOpen.value = !filterOpen.value
	}
}

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageLength.value)))
const rangeStart = computed(() => (total.value ? (page.value - 1) * pageLength.value + 1 : 0))
const rangeEnd = computed(() => Math.min(page.value * pageLength.value, total.value))

const todayFormatted = computed(() => {
	return new Date().toLocaleDateString('id-ID', {
		weekday: 'long',
		day: 'numeric',
		month: 'long',
		year: 'numeric',
	})
})

function onDocClick(e) {
	if (filterPopoverRef.value && !filterPopoverRef.value.contains(e.target)) {
		filterOpen.value = false
	}
}

onMounted(() => {
	window.addEventListener('click', onDocClick)
	load()
})

// Klik sidebar ?view=... saat sudah di halaman ini: query berubah tanpa remount.
watch(
	() => route.query.view,
	() => {
		setTab(tabFromQuery(), false)
	},
)

onBeforeUnmount(() => {
	window.removeEventListener('click', onDocClick)
})

async function load() {
	const token = ++loadToken
	loading.value = true
	error.value = ''
	try {
		const res = await fetchOrderQueue({
			company: company.value || undefined,
			search: search.value.trim() || undefined,
			stages: TABS.find((t) => t.value === activeTab.value)?.stages,
			stage: undefined,
			from_date: fromDate.value || undefined,
			to_date: toDate.value || undefined,
			page: page.value,
			page_length: pageLength.value,
		})
		if (token !== loadToken) return
		company.value = res.company || company.value
		companies.value = res.companies || []
		profile.value = res.profile || null
		counts.value = res.counts || { all: 0 }
		rows.value = res.rows || []
		total.value = res.total || 0
		page.value = res.page || page.value
		pageLength.value = res.page_length || pageLength.value
		if (activeTab.value === 'packing') await loadPackingSummary()
	} catch (e) {
		if (token === loadToken) {
			error.value = e.message || 'Gagal memuat daftar order.'
		}
	} finally {
		if (token === loadToken) {
			loading.value = false
		}
	}
}

function applyFilters() {
	page.value = 1
	load()
}

function setTab(value, syncQuery = true) {
	if (activeTab.value === value) return
	activeTab.value = value
	page.value = 1
	if (syncQuery) {
		router.replace({ query: { ...route.query, view: value === 'order' ? undefined : value } })
	}
	load()
}

watch(activeTab, (v) => {
	if (v === 'packing') loadPackingSummary()
})

// Semua label koli untuk packing slip yang sudah diinput pada tanggal kirim terpilih.
const labelPrinting = ref(false)
async function printAllLabels() {
	if (labelPrinting.value) return
	labelPrinting.value = true
	try {
		const res = await fetchPackingSlipsLabelsHtml(company.value, pickDate.value)
		printModalTitle.value = 'Label Koli Gabungan'
		printModalItems.value = [{ label: 'Label Koli', name: pickDate.value, html: res }]
		printModalOpen.value = true
	} catch (e) {
		error.value = e.message || 'Gagal memuat label gabungan.'
	} finally {
		labelPrinting.value = false
	}
}

function setPageSize(n) {
	if (pageLength.value === n) return
	pageLength.value = n
	page.value = 1
	load()
}

function goPage(next) {
	const target = Math.min(Math.max(1, next), pageCount.value)
	if (target === page.value) return
	page.value = target
	load()
}

function clearFilters() {
	search.value = ''
	fromDate.value = ''
	toDate.value = ''
	page.value = 1
	load()
}

function openOrder(row) {
	router.push({ name: 'fulfillment-workspace', params: { id: row.sales_order } })
}

function statusBadgeClass(row) {
	if (row.stage === 'completed' || row.stage === 'ready' || row.run?.status === 'DISPATCHED') return 'b-done'
	if (row.stage === 'picking' || row.stage === 'packing') return 'b-run'
	return 'b-draft'
}

function statusLabel(row) {
	if (row.stage === 'completed' || row.run?.status === 'DISPATCHED') return 'Completed'
	if (row.stage === 'ready') return 'Ready'
	if (row.stage === 'packing') return 'In Packing'
	if (row.stage === 'picking') return 'In Picking'
	if (row.stage === 'partially_delivered') return 'Partially Delivered'
	if (row.stage === 'exception') return 'Exceptions'
	return 'Open'
}
</script>

<template>
	<div class="ff-page-container">
		<!-- Header matching Hand Request style -->
		<div class="page-head">
			<div class="ph-left">
				<h1>Fulfillment</h1>
				<p class="sub">
					Antrean per tahap: order, picking, packing, hingga delivery.
				</p>
			</div>
			<div class="ff-date-badge">
				<span>{{ todayFormatted }}</span>
			</div>
		</div>

		<!-- Card: Tab Tahap, Toolbar, Table, Pagination -->
		<div class="board-card">
			<!-- Tab tahap flow di kepala kartu -->
			<div class="board-tabs" role="tablist" aria-label="Tahap fulfillment">
				<button
					v-for="item in TABS"
					:key="item.value"
					type="button"
					role="tab"
					class="board-tab"
					:class="{ on: activeTab === item.value }"
					:aria-selected="activeTab === item.value"
					@click="setTab(item.value)"
				>
					{{ item.label }}
					<span v-if="tabCount(item)" class="board-tab-count">{{ tabCount(item) }}</span>
				</button>
			</div>

			<!-- Toolbar persis Hand Request -->
			<div class="toolbar board-toolbar">
				<div class="searchbox">
					<Search :size="15" :stroke-width="2" class="search-ico" />
					<input
						v-model="search"
						class="input"
						type="search"
						placeholder="Cari No. SO atau customer..."
						aria-label="Cari No. SO atau customer"
						@keydown.enter="applyFilters"
					/>
					<button v-if="search" type="button" class="search-clear-btn" @click="search = ''; applyFilters()">
						<X :size="13" :stroke-width="2" />
					</button>
				</div>

				<div class="ff-toolbar-actions">
					<!-- Cetak gabungan: hanya di tab Packing (kertas = satuan kerja) -->
					<template v-if="activeTab === 'packing'">
						<input
							v-model="pickDate"
							class="input input-sm ff-pick-date"
							type="date"
							aria-label="Tanggal kirim"
							title="Tanggal kirim"
						/>
						<button
							type="button"
							class="btn ff-packing-btn"
							@click="packingRef?.printSheet()"
						>
							<Printer :size="14" :stroke-width="2" />
							<span>Cetak Packing List</span>
						</button>
						<button
							type="button"
							class="btn ff-manifest-btn"
							:disabled="labelPrinting"
							@click="printAllLabels"
						>
							<Tag :size="14" :stroke-width="2" />
							<span>Cetak Label Gabungan</span>
						</button>
					</template>
					<!-- Filter: di tab Packing membuka panel filter ala ERPNext pada list Packing Slip -->
				<div ref="filterPopoverRef" class="ff-filter-popover-wrap">
					<button
						type="button"
						class="btn ff-filter-btn"
						:class="{ 'has-filters': activeFilterCount > 0 || (activeTab === 'packing' && packingFilterCount > 0), 'is-open': filterOpen }"
						@click.stop="onFilterClick"
					>
						<Filter :size="14" :stroke-width="2" />
						<span>Filter</span>
						<span v-if="activeFilterCount" class="ff-filter-badge">{{ activeFilterCount }}</span>
					</button>

					<!-- Floating Filter Popover (bukan tab Packing: di sana pakai filter ala ERPNext pada list) -->
					<div v-if="filterOpen && activeTab !== 'packing'" class="ff-floating-popover" role="dialog" aria-label="Filter antrean">
							<div class="popover-head">
								<span class="popover-title">Filter Lanjutan</span>
								<button v-if="activeFilterCount" type="button" class="popover-reset-btn" @click="clearFilters">
									Reset
								</button>
							</div>

							<div class="popover-body">
								<div class="popover-field">
									<label class="popover-label">Rentang Tanggal Pengiriman</label>
									<div class="popover-date-grid">
										<div class="date-input-wrap">
											<span class="date-hint">Dari:</span>
											<input v-model="fromDate" class="input input-sm" type="date" @change="applyFilters" />
										</div>
										<div class="date-input-wrap">
											<span class="date-hint">Sampai:</span>
											<input v-model="toDate" class="input input-sm" type="date" @change="applyFilters" />
										</div>
									</div>
								</div>
							</div>

							<div class="popover-foot">
								<button type="button" class="btn btn-primary btn-sm w-full" @click="filterOpen = false">
									Terapkan Filter
								</button>
							</div>
						</div>
					</div>

					<button
						type="button"
						class="btn iconbtn"
						:disabled="loading"
						aria-label="Refresh"
						title="Refresh"
						@click="load()"
					>
						<RefreshCw :size="14" :stroke-width="2" :class="{ spin: loading }" />
					</button>
				</div>
			</div>

			<!-- Editor Packing Slip embedded (tab Packing) -->
			<template v-if="activeTab !== 'packing'">
			<!-- Error State -->
			<div v-if="error" class="ff-state ff-error" role="alert">
				<AlertTriangle :size="22" :stroke-width="1.8" />
				<div>
					<strong>Gagal memuat daftar order</strong>
					<p>{{ error }}</p>
				</div>
				<button type="button" class="btn btn-sm" @click="load">Coba lagi</button>
			</div>

			<!-- Loading Skeletons -->
			<div v-else-if="loading && !rows.length" class="ff-body is-loading">
				<div class="ff-thead">
					<span>NO. SO</span>
					<span>CUSTOMER / OUTLET</span>
					<span>JADWAL</span>
					<span>STATUS</span>
					<span>DRY / FROZEN</span>
					<span></span>
				</div>
				<div v-for="n in 5" :key="n" class="ff-trow ff-skel-row">
					<span class="skel-box w-25"></span>
					<span class="skel-box w-50"></span>
					<span class="skel-box w-20"></span>
					<span class="skel-box w-15"></span>
					<span class="skel-box w-20"></span>
					<span></span>
				</div>
			</div>

			<!-- Empty State -->
			<div v-else-if="!rows.length" class="ff-state ff-empty">
				<Inbox :size="32" :stroke-width="1.5" />
				<div>
					<strong>Tidak ada order di tahap ini</strong>
					<p v-if="activeFilterCount">Coba bersihkan kata kunci pencarian atau filter tanggal.</p>
					<p v-else>Order pada tahap {{ activeTab }} akan muncul di sini.</p>
				</div>
				<button v-if="activeFilterCount" type="button" class="btn btn-sm" @click="clearFilters">
					Hapus filter
				</button>
			</div>

			<!-- Table Body (Kolom TAHAP dihapus, cukup STATUS) -->
			<div v-else class="ff-body">
				<div class="ff-thead">
					<span>NO. SO</span>
					<span>CUSTOMER / OUTLET</span>
					<span>JADWAL</span>
					<span>STATUS</span>
					<span>DRY / FROZEN</span>
					<span></span>
				</div>

				<div class="ff-tbody">
					<div
						v-for="row in rows"
						:key="row.sales_order"
						class="ff-trow"
						role="button"
						tabindex="0"
						@click="openOrder(row)"
						@keydown.enter="openOrder(row)"
					>
						<!-- NO. SO -->
						<div class="ff-cell ff-cell-so">
							<strong class="mono">{{ row.sales_order }}</strong>
						</div>

						<!-- Customer / Outlet -->
						<div class="ff-cell ff-cell-customer">
							<span class="customer-name">{{ row.customer_name || row.customer }}</span>
							<small v-if="row.customer && row.customer_name && row.customer !== row.customer_name" class="customer-code mono">
								{{ row.customer }}
							</small>
						</div>

						<!-- Jadwal Pengiriman -->
						<div class="ff-cell ff-cell-date">
							<span>{{ fmtDate(row.delivery_date) || '—' }}</span>
						</div>

						<!-- Status (Mewakili tahap & progres secara visual) -->
						<div class="ff-cell">
							<span class="badge" :class="activeTab === 'packing' && packingStatus(row) ? packingStatus(row).cls : statusBadgeClass(row)">
								{{ activeTab === 'packing' && packingStatus(row) ? packingStatus(row).label : statusLabel(row) }}
							</span>
						</div>

						<!-- Hasil Packing (tab Packing) / Dry-Frozen (tab lain) -->
						<div class="ff-cell ff-cell-groups">
							<template v-if="activeTab === 'packing'">
								<template v-if="packingBySo[row.sales_order]?.packing?.packed">
									<span class="group-pill pill-dry">{{ packingBySo[row.sales_order].packing.koli_dry }} Dry koli</span>
									<span class="group-pill pill-frozen">{{ packingBySo[row.sales_order].packing.koli_frozen }} Frozen koli</span>
									<span class="group-pill pill-weight">
										{{ packingBySo[row.sales_order].packing.weight_dry + packingBySo[row.sales_order].packing.weight_frozen }} kg
									</span>
									<span v-if="packingBySo[row.sales_order].packing.driver" class="group-pill pill-driver">
										{{ packingBySo[row.sales_order].packing.driver }}
									</span>
								</template>
								<span class="group-pill pill-none">Belum diinput</span>
							</template>
							<template v-else>
								<span class="group-pill pill-dry">{{ row.dry_count }} {{ dryLabel }}</span>
								<span class="group-pill pill-frozen">{{ row.frozen_count }} {{ frozenLabel }}</span>
							</template>
						</div>

						<!-- Chevron Arrow -->
						<div class="ff-cell ff-cell-arrow">
							<ChevronRight :size="16" :stroke-width="2" />
						</div>
					</div>
				</div>
			</div>

			<!-- Pagination persis Hand Request -->
			<div v-if="!error && total" class="pagination-bar board-pagination">
				<span>
					Menampilkan {{ rangeStart }}-{{ rangeEnd }} dari {{ total }} order
				</span>
				<label class="page-size-control">
					<span>Per halaman</span>
					<select
						class="select"
						:value="pageLength"
						aria-label="Baris per halaman"
						@change="setPageSize(Number($event.target.value))"
					>
						<option v-for="n in PAGE_SIZES" :key="n" :value="n">{{ n }}</option>
					</select>
				</label>
				<div class="pagination-buttons">
					<button
						type="button"
						class="btn btn-sm"
						:disabled="loading || page <= 1"
						aria-label="Halaman sebelumnya"
						@click="goPage(page - 1)"
					>
						‹ Prev
					</button>
					<span class="pg-num">{{ page }} / {{ pageCount }}</span>
					<button
						type="button"
						class="btn btn-sm"
						:disabled="loading || page >= pageCount"
						aria-label="Halaman berikutnya"
						@click="goPage(page + 1)"
					>
						Next ›
					</button>
				</div>
			</div>
			</template>
			<PackingSlipPage v-else ref="packingRef" :date="pickDate" embedded @closed="loadPackingSummary" @filters-changed="packingFilterCount = $event" />
		</div>

		<PrintPreviewModal
			:open="printModalOpen"
			:title="printModalTitle"
			:items="printModalItems"
			@close="printModalOpen = false"
		/>
	</div>
</template>

<style scoped>
.ff-page-container {
	max-width: 1400px; /* sama lebar dengan halaman Inventory Report (.content) */
	margin: 0 auto;
	padding: 24px 28px;
	display: flex;
	flex-direction: column;
	gap: 16px;
}

.ff-date-badge {
	padding: 6px 14px;
	background: #ffffff;
	border: 1px solid var(--line, #e2e8f0);
	border-radius: 20px;
	font-size: 12.5px;
	color: var(--muted, #64748b);
	font-weight: 550;
	box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
}

/* Kartu utama persis Hand Request */
.board-card {
	border: 1px solid #e5e7eb;
	border-radius: 8px;
	background: #fff;
	overflow: hidden;
}

/* Tabs status di kepala kartu */
.board-tabs {
	display: flex;
	gap: 26px;
	padding: 0 18px;
	overflow-x: auto;
	border-bottom: 1px solid #e5e7eb;
	scrollbar-width: none;
}
.board-tabs::-webkit-scrollbar {
	display: none;
}
.board-tab {
	flex: none;
	display: inline-flex;
	align-items: center;
	gap: 7px;
	height: 44px;
	padding: 0 1px;
	border: 0;
	border-bottom: 2px solid transparent;
	background: none;
	color: #6b7280;
	font: inherit;
	font-size: 14px;
	cursor: pointer;
}
.board-tab:hover {
	color: #111827;
}
.board-tab.on {
	border-bottom-color: #111827;
	color: #111827;
	font-weight: 600;
}
.board-tab-count {
	min-width: 20px;
	padding: 0 6px;
	border-radius: 999px;
	background: #f3f4f6;
	color: #6b7280;
	font-size: 11px;
	line-height: 18px;
	text-align: center;
}
.board-tab.on .board-tab-count {
	background: #111827;
	color: #fff;
}

/* Toolbar di bawah tabs */
.board-toolbar {
	margin: 0;
	padding: 12px 18px;
	border-bottom: 1px solid #e5e7eb;
	background: #f9fafb;
	display: flex;
	gap: 12px;
	align-items: center;
	justify-content: space-between;
}
.board-toolbar .searchbox {
	flex: 1 1 280px;
	max-width: none;
	position: relative;
}
.searchbox .search-ico {
	position: absolute;
	left: 11px;
	top: 50%;
	transform: translateY(-50%);
	color: var(--faint, #94a3b8);
	pointer-events: none;
}
.searchbox .input {
	padding-left: 33px;
	padding-right: 30px;
	width: 100%;
	height: 34px;
	font-size: 13px;
	border-radius: 6px;
}
.search-clear-btn {
	position: absolute;
	right: 8px;
	top: 50%;
	transform: translateY(-50%);
	background: none;
	border: none;
	color: var(--muted, #64748b);
	cursor: pointer;
	padding: 4px;
	display: grid;
	place-items: center;
}

.ff-toolbar-actions {
	display: flex;
	align-items: center;
	gap: 8px;
}

/* Filter Popover */
.ff-filter-popover-wrap {
	position: relative;
}

.ff-filter-btn {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	height: 34px;
	padding: 0 12px;
	font-size: 13px;
	font-weight: 600;
	border-radius: 6px;
	border: 1px solid var(--line, #e2e8f0);
	background: #ffffff;
}

.ff-filter-btn.has-filters,
.ff-filter-btn.is-open {
	border-color: var(--brand, #3368a0);
	color: var(--brand, #3368a0);
	background: var(--brand-softer, #eff5f9);
}

.ff-filter-badge {
	width: 18px;
	height: 18px;
	border-radius: 50%;
	background: var(--brand, #3368a0);
	color: #ffffff;
	font-size: 10.5px;
	font-weight: 700;
	display: grid;
	place-items: center;
}

.ff-floating-popover {
	position: absolute;
	top: calc(100% + 8px);
	right: 0;
	z-index: 50;
	width: 320px;
	background: #ffffff;
	border: 1px solid var(--line, #e2e8f0);
	border-radius: 12px;
	box-shadow: 0 16px 36px rgba(15, 23, 42, 0.14);
	display: flex;
	flex-direction: column;
	overflow: hidden;
}

.popover-head {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 12px 16px;
	border-bottom: 1px solid var(--line, #f1f5f9);
	background: #ffffff;
}

.popover-title {
	font-size: 13px;
	font-weight: 700;
	color: var(--ink, #1e293b);
}

.popover-reset-btn {
	background: none;
	border: none;
	color: #ef4444;
	font-size: 12px;
	font-weight: 600;
	cursor: pointer;
}

.popover-body {
	padding: 14px 16px;
	display: flex;
	flex-direction: column;
	gap: 12px;
}

.popover-label {
	font-size: 11.5px;
	font-weight: 700;
	text-transform: uppercase;
	letter-spacing: 0.04em;
	color: var(--muted, #64748b);
	margin-bottom: 6px;
	display: block;
}

.popover-date-grid {
	display: flex;
	flex-direction: column;
	gap: 8px;
}

.date-input-wrap {
	display: flex;
	align-items: center;
	gap: 8px;
}

.date-hint {
	font-size: 12px;
	color: var(--muted, #64748b);
	width: 55px;
}

.popover-foot {
	padding: 10px 16px 14px;
}

.w-full {
	width: 100%;
}

.iconbtn {
	width: 34px;
	height: 34px;
	padding: 0;
	display: grid;
	place-items: center;
}
.iconbtn .spin {
	animation: spin 0.8s linear infinite;
}
@keyframes spin {
	from { transform: rotate(0deg); }
	to { transform: rotate(360deg); }
}

/* Grid Kolom Tabel (5 kolom data + 1 chevron) */
.ff-thead {
	display: grid;
	grid-template-columns: 200px minmax(220px, 1fr) 130px 140px 160px 32px;
	gap: 16px;
	padding: 12px 20px;
	background: #ffffff;
	border-bottom: 1px solid #e5e7eb;
	font-size: 11px;
	font-weight: 750;
	color: var(--muted, #64748b);
	text-transform: uppercase;
	letter-spacing: 0.05em;
}

.ff-tbody {
	display: flex;
	flex-direction: column;
}

.ff-trow {
	display: grid;
	grid-template-columns: 200px minmax(220px, 1fr) 130px 140px 160px 32px;
	gap: 16px;
	padding: 13px 20px;
	align-items: center;
	border-bottom: 1px solid #f1f5f9;
	cursor: pointer;
	transition: background 0.12s ease;
}

.ff-trow:last-child {
	border-bottom: none;
}

.ff-trow:hover {
	background: #f8fafc;
}

.ff-cell {
	display: flex;
	align-items: center;
	min-width: 0;
	font-size: 13px;
	color: var(--ink, #1e293b);
}

.ff-cell-so strong {
	color: var(--ink, #1e293b);
	font-size: 13.5px;
	letter-spacing: -0.01em;
}

.ff-cell-customer {
	display: flex;
	flex-direction: column;
	align-items: flex-start;
	gap: 2px;
}

.customer-name {
	font-weight: 600;
	color: var(--ink, #1e293b);
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
	max-width: 100%;
}

.customer-code {
	font-size: 11px;
	color: var(--muted, #64748b);
}

.ff-cell-date {
	color: var(--muted, #64748b);
	font-size: 12.5px;
}

.ff-cell-groups {
	display: flex;
	align-items: center;
	gap: 6px;
}

.group-pill {
	font-size: 11px;
	font-weight: 600;
	padding: 2px 8px;
	border-radius: 4px;
}

.pill-dry {
	background: #e0f2fe;
	color: #0369a1;
}

.pill-frozen {
	background: #e0f2fe;
	color: #0284c7;
}

.pill-weight {
	background: #fef3c7;
	color: #92400e;
}

.pill-driver {
	background: #ede9fe;
	color: #5b21b6;
}

.pill-none {
	background: #f1f5f9;
	color: #64748b;
}

.ff-cell-arrow {
	color: var(--muted, #94a3b8);
	display: grid;
	place-items: center;
}

/* Pagination Bar persis Hand Request */
.board-pagination {
	border-top: 1px solid #e5e7eb;
	background: #fff;
}
.pg-num {
	font-size: 12.5px;
	color: var(--muted, inherit);
	font-variant-numeric: tabular-nums;
	min-width: 52px;
	text-align: center;
}

/* Empty / State */
.ff-state {
	padding: 56px 20px;
	background: #ffffff;
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	gap: 12px;
	text-align: center;
	color: var(--muted, #64748b);
}

.ff-state strong {
	color: var(--ink, #1e293b);
	font-size: 16px;
}

.skel-box {
	height: 14px;
	border-radius: 4px;
	background: var(--line, #f1f5f9);
	animation: pulse 1.5s infinite ease-in-out;
}
.w-15 { width: 15%; }
.w-20 { width: 20%; }
.w-25 { width: 25%; }
.w-50 { width: 50%; }

@keyframes pulse {
	0%, 100% { opacity: 1; }
	50% { opacity: 0.5; }
}

@media (max-width: 820px) {
	.board-tabs { gap: 12px; padding: 0 12px; }
	.board-tab { gap: 5px; font-size: 13px; }
	.board-toolbar { padding: 10px 14px; }
	.board-toolbar .searchbox { flex: 1 1 100%; }
}

/* Tombol Cetak Pick List Gabungan + input tanggal */
.ff-manifest-btn {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	height: 34px;
	padding: 0 12px;
	font-size: 13px;
	font-weight: 600;
	border-radius: 6px;
	border: 1px solid var(--brand, #3368a0);
	background: var(--brand, #3368a0);
	color: #ffffff;
}
.ff-manifest-btn:hover {
	background: var(--brand-dark, #2a567f);
	border-color: var(--brand-dark, #2a567f);
}
/* Tombol Cetak Packing List: kuning ala sheet packing (label tetap hitam-putih) */
.ff-packing-btn {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	height: 34px;
	padding: 0 12px;
	font-size: 13px;
	font-weight: 600;
	border-radius: 6px;
	border: 1.5px solid #111;
	background: #ffe94a;
	color: #111;
}
.ff-packing-btn:hover {
	background: #f5dd35;
}
.ff-manifest-btn:disabled {
	opacity: 0.6;
	cursor: not-allowed;
}
.ff-pick-date {
	height: 34px;
	font-size: 13px;
	width: 150px;
}
</style>
