<script setup>
import { computed, onMounted, ref } from 'vue'
import {
	AlertTriangle,
	ChevronLeft,
	ChevronRight,
	Inbox,
	RefreshCw,
	Search,
	X,
} from 'lucide-vue-next'
import { fetchOrderQueue, STAGE_LABELS, stageLabel } from '@/data/fulfillment'
import { fmtDate } from '@/lib/format'
import FulfillmentDrawer from '@/components/FulfillmentDrawer.vue'

const STAGE_FILTERS = [
	{ value: 'all', label: 'All' },
	...Object.entries(STAGE_LABELS).map(([value, label]) => ({ value, label })),
]
const PAGE_SIZES = [20, 50, 100]

const company = ref('')
const companies = ref([])
const profile = ref({ configured: false, enabled: false })
const counts = ref({ all: 0 })
const rows = ref([])
const total = ref(0)
const page = ref(1)
const pageLength = ref(20)
const stage = ref('all')
const search = ref('')
const fromDate = ref('')
const toDate = ref('')
const loading = ref(false)
const error = ref('')
const selectedSO = ref(null)

let loadToken = 0

const hasProfile = computed(() => Boolean(profile.value?.configured && profile.value?.enabled))
const dryLabel = computed(() => profile.value?.dry_display_name || 'Dry')
const frozenLabel = computed(() => profile.value?.frozen_display_name || 'Frozen')
const hasFilters = computed(
	() => Boolean(search.value || fromDate.value || toDate.value || stage.value !== 'all'),
)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageLength.value)))
const rangeStart = computed(() => (total.value ? (page.value - 1) * pageLength.value + 1 : 0))
const rangeEnd = computed(() => Math.min(page.value * pageLength.value, total.value))
const profileMessage = computed(() => {
	if (!profile.value?.configured && profile.value?.enabled === false && profile.value?.frozen_item_group) {
		return `The Fulfillment profile is disabled. Enable it in Settings to use ${dryLabel.value}/${frozenLabel.value} classification.`
	}
	return 'No Fulfillment profile is configured for this company. Set the Frozen Item Group in Settings.'
})

onMounted(load)

async function load() {
	const token = ++loadToken
	loading.value = true
	error.value = ''
	try {
		const data = await fetchOrderQueue({
			company: company.value || undefined,
			search: search.value.trim() || undefined,
			stage: stage.value,
			from_date: fromDate.value || undefined,
			to_date: toDate.value || undefined,
			page: page.value,
			page_length: pageLength.value,
		})
		if (token !== loadToken) {
			return
		}
		companies.value = data.companies || []
		if (!company.value && data.company) {
			company.value = data.company
		}
		profile.value = data.profile || { configured: false, enabled: false }
		counts.value = { all: 0, ...(data.counts || {}) }
		rows.value = data.rows || []
		total.value = data.total || 0
	} catch (e) {
		if (token !== loadToken) {
			return
		}
		rows.value = []
		total.value = 0
		error.value = e.message || 'Failed to load the fulfillment queue.'
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

function setStage(value) {
	if (stage.value === value) {
		return
	}
	stage.value = value
	page.value = 1
	load()
}

function onCompanyChange() {
	page.value = 1
	load()
}

function onPageLength() {
	page.value = 1
	load()
}

function goPage(next) {
	const target = Math.min(Math.max(1, next), pageCount.value)
	if (target === page.value) {
		return
	}
	page.value = target
	load()
}

function clearFilters() {
	search.value = ''
	fromDate.value = ''
	toDate.value = ''
	stage.value = 'all'
	page.value = 1
	load()
}

function openRow(row) {
	selectedSO.value = row.sales_order
}

function docMain(doc) {
	return doc?.total ? doc.total : '—'
}

function docSub(doc) {
	if (!doc?.total) {
		return ''
	}
	if (doc.draft) {
		return `${doc.draft} draft`
	}
	if (doc.submitted) {
		return `${doc.submitted} submitted`
	}
	return ''
}

function warningTitle(row) {
	return (row.warnings || []).join(', ')
}
</script>

<template>
	<div class="ff-page">
		<div class="page-head">
			<div class="ph-left">
				<h1>Fulfillment</h1>
				<p class="sub">
					Open sales orders across Dry and Frozen fulfillment, with their native Pick Lists,
					Delivery Notes, and Packing Slips.
				</p>
			</div>
			<div class="ff-head-actions">
				<label class="ff-company">
					<span>Company</span>
					<select
						v-model="company"
						class="select"
						:disabled="companies.length < 2"
						aria-label="Company"
						@change="onCompanyChange"
					>
						<option v-for="c in companies" :key="c.name" :value="c.name">{{ c.name }}</option>
					</select>
				</label>
				<button
					type="button"
					class="btn iconbtn"
					:disabled="loading"
					title="Refresh"
					aria-label="Refresh"
					@click="load"
				>
					<RefreshCw :size="14" :stroke-width="2" :class="{ spin: loading }" />
				</button>
			</div>
		</div>

		<div v-if="!hasProfile" class="ff-banner" role="status">
			<AlertTriangle :size="18" :stroke-width="1.9" />
			<div>
				<strong>Fulfillment profile needs attention.</strong>
				<span>{{ profileMessage }}</span>
			</div>
			<a class="btn btn-sm" href="/gudang/settings">
				Configure
			</a>
		</div>

		<div class="ff-stages" role="tablist" aria-label="Fulfillment stage">
			<button
				v-for="item in STAGE_FILTERS"
				:key="item.value"
				type="button"
				role="tab"
				class="ff-chip"
				:class="{ on: stage === item.value }"
				:aria-selected="stage === item.value"
				@click="setStage(item.value)"
			>
				<span>{{ item.label }}</span>
				<span class="ff-chip-count">{{ counts[item.value] || 0 }}</span>
			</button>
		</div>

		<div class="toolbar ff-toolbar">
			<div class="searchbox">
				<Search :size="15" :stroke-width="2" class="search-ico" />
				<input
					v-model="search"
					class="input"
					type="search"
					placeholder="Search sales order or customer"
					aria-label="Search sales order or customer"
					@keydown.enter="applyFilters"
				/>
			</div>
			<label class="ff-date">
				<span>From</span>
				<input v-model="fromDate" class="input" type="date" aria-label="From SO date" @change="applyFilters" />
			</label>
			<label class="ff-date">
				<span>To</span>
				<input v-model="toDate" class="input" type="date" aria-label="To SO date" @change="applyFilters" />
			</label>
			<button v-if="hasFilters" type="button" class="linkbtn ff-clear" @click="clearFilters">
				<X :size="14" :stroke-width="2" />
				Clear
			</button>
		</div>

		<div v-if="error" class="ff-state ff-error" role="alert">
			<AlertTriangle :size="22" :stroke-width="1.8" />
			<div>
				<strong>Could not load the queue</strong>
				<p>{{ error }}</p>
			</div>
			<button type="button" class="btn btn-sm" @click="load">Retry</button>
		</div>

		<div v-else-if="loading && !rows.length" class="ff-table ff-skeleton" aria-label="Loading queue">
			<div class="ff-thead">
				<span>SO / Customer</span>
				<span>Delivery</span>
				<span>{{ dryLabel }} / {{ frozenLabel }}</span>
				<span>Pick Lists</span>
				<span>DN Draft</span>
				<span>Packing Slips</span>
				<span>Stage</span>
				<span></span>
			</div>
			<div v-for="n in 5" :key="n" class="ff-row ff-skeleton-row">
				<span class="ff-skel ff-skel-wide"></span>
				<span class="ff-skel"></span>
				<span class="ff-skel"></span>
				<span class="ff-skel"></span>
				<span class="ff-skel"></span>
				<span class="ff-skel"></span>
				<span class="ff-skel"></span>
				<span></span>
			</div>
		</div>

		<div v-else-if="!rows.length" class="ff-state ff-empty">
			<Inbox :size="30" :stroke-width="1.5" />
			<div>
				<strong>No sales orders in this view</strong>
				<p v-if="hasFilters">Try clearing the search, date range, or stage filter.</p>
				<p v-else>Open sales orders will appear here once they are available.</p>
			</div>
			<button v-if="hasFilters" type="button" class="btn btn-sm" @click="clearFilters">
				Clear filters
			</button>
		</div>

		<div v-else class="ff-table" :class="{ 'is-loading': loading }">
			<div class="ff-thead" role="row">
				<span>SO / Customer</span>
				<span>Delivery</span>
				<span>{{ dryLabel }} / {{ frozenLabel }}</span>
				<span>Pick Lists</span>
				<span>DN Draft</span>
				<span>Packing Slips</span>
				<span>Stage</span>
				<span></span>
			</div>
			<button
				v-for="row in rows"
				:key="row.sales_order"
				type="button"
				class="ff-row"
				:aria-label="`Open ${row.sales_order}`"
				@click="openRow(row)"
			>
				<span class="ff-cell ff-so">
					<span class="ff-soname">{{ row.sales_order }}</span>
					<span class="ff-customer">{{ row.customer_name || row.customer || '—' }}</span>
				</span>
				<span class="ff-cell" data-label="Delivery">{{ fmtDate(row.delivery_date) || '—' }}</span>
				<span class="ff-cell" :data-label="`${dryLabel} / ${frozenLabel}`">
					<span class="ff-pill ff-dry">{{ row.dry_count }} {{ dryLabel }}</span>
					<span class="ff-pill ff-frozen">{{ row.frozen_count }} {{ frozenLabel }}</span>
					<span v-if="row.unclassified_count" class="ff-pill ff-warn">
						{{ row.unclassified_count }} needs attention
					</span>
				</span>
				<span class="ff-cell" data-label="Pick Lists">
					<span class="ff-doc">{{ docMain(row.pick_lists) }}</span>
					<small>{{ docSub(row.pick_lists) }}</small>
				</span>
				<span class="ff-cell" data-label="DN Draft">
					<span class="ff-doc">{{ docMain(row.delivery_notes) }}</span>
					<small>{{ docSub(row.delivery_notes) }}</small>
				</span>
				<span class="ff-cell" data-label="Packing Slips">
					<span class="ff-doc">{{ docMain(row.packing_slips) }}</span>
					<small>{{ docSub(row.packing_slips) }}</small>
				</span>
				<span class="ff-cell" data-label="Stage">
					<span class="ff-stage" :class="`ff-stage-${row.stage}`">{{ stageLabel(row.stage) }}</span>
					<AlertTriangle
						v-if="row.warnings?.length"
						:size="14"
						:stroke-width="2"
						class="ff-warning"
						:title="warningTitle(row)"
					/>
				</span>
				<span class="ff-arrow"><ChevronRight :size="16" :stroke-width="2" /></span>
			</button>
		</div>

		<div v-if="!error && total" class="ff-foot">
			<span class="ff-range">Showing {{ rangeStart }}–{{ rangeEnd }} of {{ total }}</span>
			<div class="ff-pager">
				<button
					type="button"
					class="btn iconbtn"
					:disabled="loading || page <= 1"
					aria-label="Previous page"
					@click="goPage(page - 1)"
				>
					<ChevronLeft :size="14" :stroke-width="2" />
				</button>
				<span>Page {{ page }} / {{ pageCount }}</span>
				<button
					type="button"
					class="btn iconbtn"
					:disabled="loading || page >= pageCount"
					aria-label="Next page"
					@click="goPage(page + 1)"
				>
					<ChevronRight :size="14" :stroke-width="2" />
				</button>
				<select
					v-model.number="pageLength"
					class="select ff-pagesize"
					aria-label="Rows per page"
					@change="onPageLength"
				>
					<option v-for="size in PAGE_SIZES" :key="size" :value="size">{{ size }} / page</option>
				</select>
			</div>
		</div>

		<FulfillmentDrawer
			:open="Boolean(selectedSO)"
			:sales-order="selectedSO"
			@close="selectedSO = null"
			@generated="load"
		/>
	</div>
</template>

<style scoped>
.ff-page {
	display: flex;
	flex-direction: column;
	gap: 16px;
}

.ff-head-actions,
.ff-company,
.ff-banner,
.ff-stages,
.ff-date,
.ff-foot,
.ff-pager {
	display: flex;
	align-items: center;
}

.ff-head-actions {
	gap: 8px;
	flex: none;
}

.ff-company {
	gap: 8px;
	font-size: 12px;
	font-weight: 600;
	color: var(--muted);
}

.ff-company .select {
	min-width: 180px;
	max-width: 240px;
}

.ff-banner {
	gap: 10px;
	padding: 12px 14px;
	border: 1px solid #efd8a8;
	border-radius: 12px;
	background: #fff9ea;
	color: #7a5200;
	font-size: 13px;
}

.ff-banner > div {
	display: flex;
	flex-direction: column;
	gap: 2px;
	min-width: 0;
	flex: 1;
}

.ff-banner strong {
	color: #5f4000;
}

.ff-stages {
	gap: 8px;
	flex-wrap: wrap;
}

.ff-chip {
	display: inline-flex;
	align-items: center;
	gap: 7px;
	padding: 7px 10px;
	border: 1px solid var(--line);
	border-radius: 999px;
	background: var(--surface);
	color: var(--ink);
	font: inherit;
	font-size: 12.5px;
	cursor: pointer;
}

.ff-chip:hover {
	border-color: var(--brand-light);
}

.ff-chip.on {
	border-color: var(--brand);
	background: var(--brand-soft);
	color: var(--brand);
	font-weight: 650;
}

.ff-chip-count {
	min-width: 18px;
	padding: 0 5px;
	border-radius: 999px;
	background: var(--grey-bg);
	color: var(--muted);
	font-size: 11px;
	line-height: 18px;
	text-align: center;
}

.ff-chip.on .ff-chip-count {
	background: var(--brand);
	color: #fff;
}

.ff-toolbar {
	gap: 8px;
	align-items: center;
}

.ff-toolbar .searchbox {
	flex: 1 1 260px;
}

.ff-date {
	gap: 6px;
	font-size: 12px;
	color: var(--muted);
	font-weight: 600;
}

.ff-date .input {
	width: 145px;
}

.ff-clear {
	display: inline-flex;
	align-items: center;
	gap: 4px;
}

.ff-table {
	border: 1px solid var(--line);
	border-radius: 14px;
	background: rgba(255, 255, 255, 0.66);
	overflow: hidden;
}

.ff-thead,
.ff-row {
	display: grid;
	grid-template-columns:
		minmax(190px, 1.45fr)
		100px
		minmax(170px, 1.2fr)
		minmax(90px, 0.8fr)
		minmax(90px, 0.8fr)
		minmax(105px, 0.9fr)
		minmax(112px, 0.9fr)
		24px;
	gap: 10px;
	align-items: center;
}

.ff-thead {
	padding: 10px 14px;
	border-bottom: 1px solid var(--line);
	background: var(--grey-bg);
	color: var(--muted);
	font-size: 10.5px;
	font-weight: 700;
	letter-spacing: 0.055em;
	text-transform: uppercase;
}

.ff-row {
	width: 100%;
	padding: 11px 14px;
	border: 0;
	border-top: 1px solid var(--line);
	background: transparent;
	color: var(--ink);
	font: inherit;
	text-align: left;
	cursor: pointer;
}

.ff-thead + .ff-row {
	border-top: 0;
}

.ff-row:hover {
	background: var(--brand-softer);
	box-shadow: inset 2.5px 0 0 var(--brand-light);
}

.ff-row:focus-visible {
	outline-offset: -2px;
}

.ff-table.is-loading {
	opacity: 0.66;
	pointer-events: none;
}

.ff-cell {
	display: flex;
	flex-direction: column;
	min-width: 0;
	font-size: 13px;
}

.ff-so {
	gap: 2px;
}

.ff-soname {
	font-weight: 700;
	color: var(--brand);
}

.ff-customer {
	overflow: hidden;
	color: var(--muted);
	font-size: 12px;
	text-overflow: ellipsis;
	white-space: nowrap;
}

.ff-cell small {
	margin-top: 2px;
	color: var(--muted);
	font-size: 11px;
}

.ff-doc {
	font-weight: 650;
}

.ff-pill {
	display: inline-flex;
	align-items: center;
	width: fit-content;
	margin: 1px 0;
	padding: 2px 7px;
	border-radius: 999px;
	font-size: 11px;
	font-weight: 600;
	line-height: 16px;
}

.ff-dry {
	background: #eaf0ff;
	color: #36519a;
}

.ff-frozen {
	background: #e5f6f1;
	color: #146b57;
}

.ff-warn {
	background: #fff1d6;
	color: #8a5a00;
}

.ff-stage {
	display: inline-flex;
	width: fit-content;
	padding: 3px 8px;
	border-radius: 999px;
	font-size: 11px;
	font-weight: 650;
	line-height: 16px;
}

.ff-stage-open {
	background: var(--grey-bg);
	color: var(--muted);
}

.ff-stage-picking {
	background: #e9f2ff;
	color: #1d5d9e;
}

.ff-stage-packing {
	background: #fff2d9;
	color: #8a5a00;
}

.ff-stage-ready {
	background: #e4f6e9;
	color: #1f6b3a;
}

.ff-stage-partially_delivered {
	background: #f0eaff;
	color: #5d3f9e;
}

.ff-stage-exception {
	background: #ffe9e6;
	color: #9b2c1f;
}

.ff-warning {
	margin-left: 5px;
	color: #a15c00;
}

.ff-arrow {
	display: grid;
	place-items: center;
	color: var(--faint);
}

.ff-row:hover .ff-arrow {
	color: var(--brand-light);
	transform: translateX(1px);
}

.ff-state {
	display: flex;
	align-items: center;
	gap: 12px;
	padding: 24px;
	border: 1px solid var(--line);
	border-radius: 14px;
	background: rgba(255, 255, 255, 0.66);
	color: var(--muted);
}

.ff-state > div {
	flex: 1;
}

.ff-state strong {
	display: block;
	color: var(--ink);
}

.ff-state p {
	margin-top: 3px;
}

.ff-error {
	color: #9b2c1f;
	border-color: #f0c7c0;
	background: #fff6f4;
}

.ff-error strong {
	color: #7e2117;
}

.ff-empty {
	justify-content: center;
	text-align: left;
}

.ff-skeleton-row {
	cursor: default;
	pointer-events: none;
}

.ff-skel {
	height: 12px;
	border-radius: 6px;
	background: linear-gradient(90deg, var(--grey-bg) 25%, #f7f8fa 50%, var(--grey-bg) 75%);
	background-size: 200% 100%;
	animation: ff-shimmer 1.2s linear infinite;
}

.ff-skel-wide {
	width: 70%;
}

.ff-foot {
	justify-content: space-between;
	gap: 12px;
	font-size: 12px;
	color: var(--muted);
}

.ff-pager {
	gap: 8px;
}

.ff-pagesize {
	width: auto;
	min-width: 100px;
}

.spin {
	animation: ff-spin 0.9s linear infinite;
}

@keyframes ff-shimmer {
	to {
		background-position: -200% 0;
	}
}

@keyframes ff-spin {
	to {
		transform: rotate(360deg);
	}
}

@media (max-width: 1100px) {
	.ff-page > .page-head {
		flex-wrap: wrap;
		align-items: flex-start;
	}

	.ff-page > .page-head .ph-left {
		flex: 1 1 100%;
		min-width: 0;
	}

	.ff-head-actions {
		width: 100%;
		justify-content: space-between;
	}

	.ff-company {
		flex: 1;
	}

	.ff-company .select {
		flex: 1;
		max-width: none;
	}

	.ff-banner {
		align-items: flex-start;
		flex-wrap: wrap;
	}

	.ff-banner .btn {
		margin-left: 28px;
	}

	.ff-stages {
		flex-wrap: wrap;
		overflow: visible;
	}

	.ff-chip {
		flex: 0 1 auto;
	}

	.ff-toolbar {
		flex-wrap: wrap;
	}

	.ff-toolbar .searchbox {
		flex: 1 1 100%;
		max-width: none;
	}

	.ff-date {
		flex: 1;
	}

	.ff-date .input {
		flex: 1;
		width: auto;
		min-width: 0;
	}

	.ff-table {
		border: 0;
		background: transparent;
		overflow: visible;
	}

	.ff-thead {
		display: none;
	}

	.ff-row {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 8px 12px;
		margin-bottom: 10px;
		padding: 14px;
		border: 1px solid var(--line);
		border-radius: 14px;
		background: rgba(255, 255, 255, 0.76);
	}

	.ff-row:hover {
		box-shadow: none;
	}

	.ff-so {
		grid-column: 1 / -1;
	}

	.ff-cell::before {
		content: attr(data-label);
		display: block;
		margin-bottom: 2px;
		color: var(--muted);
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.045em;
		text-transform: uppercase;
	}

	.ff-so::before,
	.ff-arrow::before {
		display: none;
	}

	.ff-arrow {
		display: none;
	}

	.ff-foot {
		flex-wrap: wrap;
	}

	.ff-pager {
		width: 100%;
		flex-wrap: wrap;
		justify-content: space-between;
	}

	@media (prefers-reduced-motion: reduce) {
		.ff-skel,
		.spin {
			animation: none;
		}
	}
}

@media (min-width: 901px) and (max-width: 1100px) {
	.ff-row {
		grid-template-columns: repeat(3, minmax(0, 1fr));
	}

	.ff-so {
		grid-column: 1 / -1;
	}
}

@media (max-width: 560px) {
	.ff-page {
		gap: 12px;
	}

	.ff-head-actions {
		gap: 10px;
	}

	.ff-company {
		min-width: 0;
	}

	.ff-company .select {
		min-width: 0;
	}

	.ff-banner .btn {
		margin-left: 0;
	}

	.ff-toolbar {
		gap: 10px;
	}

	.ff-date {
		flex: 1 1 100%;
	}

	.ff-row {
		grid-template-columns: 1fr;
		gap: 6px;
		padding: 12px;
	}

	.ff-so {
		grid-column: auto;
	}

	.ff-cell {
		display: grid;
		grid-template-columns: 92px minmax(0, 1fr);
		align-items: start;
		gap: 8px;
	}

	.ff-cell::before {
		grid-column: 1;
		grid-row: 1 / span 4;
		margin-bottom: 0;
		padding-top: 2px;
	}

	.ff-cell > * {
		grid-column: 2;
	}

	.ff-so {
		display: flex;
	}

	.ff-foot {
		flex-direction: column;
		align-items: flex-start;
	}

	.ff-pager {
		justify-content: flex-start;
	}
}
</style>
