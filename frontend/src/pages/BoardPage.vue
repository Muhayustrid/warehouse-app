<script setup>
// Papan Serah Terima Gudang (SPA, W33) — port paritas penuh dari page
// klasik gudang_request: search, filter builder, UOM switcher, pemilih
// kolom, kepadatan, checklist + deteksi grup, dialog bulk/group (qty-only,
// semantik W30), cancel tunggal/grup, pill status, Load more.
import { ref, computed, watch, onMounted } from 'vue'
import { Button } from '@frappe-ui/components/Button'
import { TextInput } from '@frappe-ui/components/TextInput'
import FeatherIcon from '@frappe-ui/components/FeatherIcon.vue'
import { toast } from '@/lib/toast'
import { fetchWorkOrders, fetchFilterFields, cancelRequest, cancelGroupRequest } from '@/data/board'
import { loadPref, savePref } from '@/lib/prefs'
import { fmtNum } from '@/lib/format'
import { dayjs } from '@frappe-ui/utils/dayjs'
import FilterBuilder from '@/components/FilterBuilder.vue'
import DisplayMenu from '@/components/DisplayMenu.vue'
import RequestDialog from '@/components/RequestDialog.vue'
import GroupRequestDialog from '@/components/GroupRequestDialog.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'

const PAGE_SIZE = 50

// Item & Qty selalu tampil; sisanya bisa disembunyikan lewat Display
// (item_code/warehouse = baris kedua di sel Item/Work Order).
const ALL_COLUMNS = [
	{ key: 'batch', label: 'Batch' },
	{ key: 'item_code', label: 'Item Code' },
	{ key: 'wo', label: 'Work Order' },
	{ key: 'warehouse', label: 'Warehouse' },
	{ key: 'status', label: 'Status' },
]

// ---- state
const rows = ref([])
const lastFetchCount = ref(0)
const loading = ref(false)
const search = ref('')
const filters = ref([])
const fieldMeta = ref(null)
const selectedNames = ref([])
const qtyUom = ref(loadPref('qty_uom', ''))
const visibleCols = ref(loadPref('columns', ALL_COLUMNS.map((c) => c.key)).filter((k) => ALL_COLUMNS.some((c) => c.key === k)))
const density = ref(loadPref('density', 'comfort'))

const bulkDialog = ref(false)
const groupDialog = ref(false)
const cancelOpen = ref(false)
const cancelTarget = ref(null) // { mr, plan, size } | null
// baris Requested yang dilibatkan utk cancel — tampil di bar mengapung,
// gaya yang sama dgn bar Create Request (saling eksklusif dgn seleksi)
const cancelPick = ref(null)

const show = (key) => visibleCols.value.includes(key)
const pad = computed(() => (density.value === 'compact' ? 'py-1.5' : 'py-3'))

function setCols(keys) {
  // render ulang tanpa fetch; seleksi dikosongkan (pola klasik);
  // simpan dalam urutan kanonik ALL_COLUMNS
  const canonical = ALL_COLUMNS.filter((c) => keys.includes(c.key)).map((c) => c.key)
  selectedNames.value = []
  cancelPick.value = null
  visibleCols.value = canonical
  savePref('columns', canonical)
}

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
	{ key: 'ready', label: 'Ready', dot: 'bg-blue-500' },
	{ key: 'requested', label: 'Requested', dot: 'bg-orange-500' },
	{ key: 'shipped', label: 'Shipped', dot: 'bg-green-500' },
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
	return x.format(x.isSame(dayjs(), 'year') ? 'dddd, D MMMM' : 'dddd, D MMMM YYYY')
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

// ---- muat data
function activeFilters() {
	return filters.value.filter((f) =>
		Array.isArray(f.value)
			? f.value.some((x) => String(x || '').trim() !== '')
			: String(f.value || '').trim() !== '',
	)
}

async function load(append = false) {
	loading.value = true
	try {
		const res = await fetchWorkOrders({
			search: search.value,
			filters: activeFilters(),
			limitStart: append ? rows.value.length : 0,
		})
		// frappeRequest sudah mengembalikan data.message — array baris langsung
		const fetched = Array.isArray(res) ? res : []
		lastFetchCount.value = fetched.length
		rows.value = append ? rows.value.concat(fetched) : fetched
		if (!append) {
			selectedNames.value = []
			cancelPick.value = null
		}
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

let searchTimer = null
watch(search, () => {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(() => load(), 350)
})

// kepadatan dipilih di DisplayMenu (v-model) — persist di sini
watch(density, (v) => savePref('density', v))

// filter berubah: FilterBuilder emit 'change' (bukan watch deep — see quirk)
let filterTimer = null
function onFilterChange() {
	clearTimeout(filterTimer)
	filterTimer = setTimeout(() => load(), 300)
}

function refresh() {
	clearTimeout(searchTimer)
	clearTimeout(filterTimer)
	load()
}

const canLoadMore = computed(() => rows.value.length > 0 && lastFetchCount.value >= PAGE_SIZE)

onMounted(async () => {
	try {
		fieldMeta.value = await fetchFilterFields()
	} catch (e) {
		/* filter tetap bisa dipakai tanpa meta? tidak — tapi jangan blok papan */
	}
	load()
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
	load()
}

function onGroupDone({ boxPlan, size }) {
	toast.success(`Group request created: ${boxPlan} · ${size} Work Orders`)
	load()
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
	}
	cancelOpen.value = true
}

const cancelOptions = computed(() => {
	const t = cancelTarget.value
	if (!t) {
		return {}
	}
	return t.plan
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
	load()
}
</script>

<template>
	<div class="space-y-5">
		<!-- header -->
		<div class="flex flex-wrap items-start justify-between gap-3">
			<div>
				<h1 class="text-2xl font-semibold tracking-tight text-ink-gray-9">Handover Requests</h1>
				<p class="mt-1 text-sm text-ink-gray-5">
					Finished batches from production. Select the ones the warehouse should receive and create a request.
				</p>
			</div>
			<Button variant="subtle" label="Refresh" icon-left="refresh-cw" :loading="loading" @click="refresh()" />
		</div>

		<!-- status + toolbar -->
		<div class="flex flex-wrap items-center justify-between gap-3">
			<div class="flex flex-wrap gap-1 rounded-lg bg-surface-gray-2 p-1" role="tablist" aria-label="Status">
				<button
					v-for="v in VIEWS"
					:key="v.key"
					role="tab"
					:aria-selected="view === v.key"
					class="flex h-7 items-center gap-2 rounded-md px-3 text-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-outline-gray-4"
					:class="view === v.key ? 'bg-surface-white font-medium text-ink-gray-9 shadow-sm dark:bg-surface-gray-4' : 'text-ink-gray-6 hover:text-ink-gray-8'"
					@click="view = v.key; selectedNames = []; cancelPick = null"
				>
					<span v-if="v.dot" class="h-2 w-2 rounded-full" :class="v.dot" />
					{{ v.label }}
					<span class="tabular-nums text-ink-gray-5">{{ counts[v.key] }}</span>
				</button>
			</div>
			<div class="flex flex-wrap items-center gap-2">
				<TextInput
					v-model="search"
					class="w-full sm:w-64"
					type="text"
					placeholder="Search batch, item, or work order"
					@keydown.enter="refresh"
				>
					<template #prefix><FeatherIcon name="search" class="h-4 w-4 text-ink-gray-5" /></template>
				</TextInput>
				<FilterBuilder v-model="filters" :meta="fieldMeta" @change="onFilterChange" />
				<DisplayMenu
					v-model:visible="visibleCols"
					v-model:density="density"
					:columns="ALL_COLUMNS"
					@update:visible="setCols"
				/>
				<select
					v-if="uomOptions.length > 1"
					class="h-8 rounded border border-outline-gray-2 bg-surface-modal py-0 pl-2.5 pr-8 text-sm text-ink-gray-7"
					:value="qtyUom"
					aria-label="Qty unit"
					@change="setUom($event.target.value)"
				>
					<option v-for="o in uomOptions" :key="o" :value="o">{{ o }}</option>
				</select>
			</div>
		</div>

		<!-- daftar per hari produksi -->
		<div
			class="overflow-hidden rounded-lg border border-outline-gray-2 bg-surface-modal transition-opacity"
			:class="{ 'opacity-50': loading }"
		>
			<div class="overflow-x-auto">
				<table class="w-full text-sm">
					<thead>
						<tr class="border-b border-outline-gray-2 text-left text-xs text-ink-gray-5">
							<th class="w-10 py-2.5 pl-4 pr-2">
								<input
									type="checkbox"
									class="h-3.5 w-3.5 accent-ink-gray-9"
									:checked="allChecked"
									:indeterminate.prop="someChecked"
									:disabled="!selectableRows.length"
									aria-label="Select all ready batches"
									@change="toggleAll($event.target.checked)"
								/>
							</th>
							<th v-if="show('batch')" class="w-20 px-2 py-2.5 font-medium">Batch</th>
							<th class="px-3 py-2.5 font-medium">Item</th>
							<th class="px-3 py-2.5 text-right font-medium">Qty</th>
							<th v-if="show('wo') || show('warehouse')" class="hidden px-3 py-2.5 font-medium md:table-cell">
								{{ show('wo') ? 'Work Order' : 'Warehouse' }}
							</th>
							<th v-if="show('status')" class="px-3 py-2.5 pr-4 font-medium">Status</th>
						</tr>
					</thead>
					<tbody v-for="day in days" :key="day.date">
						<tr class="border-b border-outline-gray-1 bg-surface-gray-1">
							<td class="py-2 pl-4 pr-2">
								<input
									v-if="dayState(day).any"
									type="checkbox"
									class="h-3.5 w-3.5 accent-ink-gray-9"
									:checked="dayState(day).all"
									:indeterminate.prop="dayState(day).some"
									:aria-label="`Select ready batches from ${dayLabel(day.date)}`"
									@change="toggleDay(day, $event.target.checked)"
								/>
							</td>
							<td colspan="5" class="py-2 pr-4 text-xs">
								<span class="font-semibold text-ink-gray-8">{{ dayLabel(day.date) }}</span>
								<span class="ml-2 text-ink-gray-5">{{ day.rows.length }} {{ day.rows.length === 1 ? 'batch' : 'batches' }}</span>
							</td>
						</tr>
						<tr
							v-for="r in day.rows"
							:key="r.name"
							class="group border-b border-outline-gray-1 last:border-b-0"
							:class="[
								r.request_shipped ? 'cursor-default' : 'cursor-pointer hover:bg-surface-gray-1',
								selectedNames.includes(r.name) && 'bg-surface-selected hover:bg-surface-selected',
								cancelPick === r.name && 'bg-orange-50 hover:bg-orange-50 dark:bg-orange-500/10',
							]"
							@click="toggleRow(r)"
						>
							<td class="relative pl-4 pr-2" :class="pad">
								<span
									class="absolute inset-y-0 left-0 w-[3px]"
									:class="{ 'bg-blue-500': stateOf(r) === 'ready', 'bg-orange-500': stateOf(r) === 'requested', 'bg-green-500': stateOf(r) === 'shipped' }"
								/>
								<input
									type="checkbox"
									class="h-3.5 w-3.5 accent-ink-gray-9"
									:disabled="!isSelectable(r)"
									:checked="selectedNames.includes(r.name)"
									:aria-label="`Select ${r.item_name} batch ${r.custom_adonan_ke || r.name}`"
									@click.stop
									@change="toggleRow(r)"
								/>
							</td>
							<td v-if="show('batch')" class="px-2" :class="pad">
								<span
									v-if="r.custom_adonan_ke"
									class="inline-flex h-8 min-w-[2.5rem] items-center justify-center rounded-md border border-outline-gray-2 px-2 text-base font-semibold tabular-nums text-ink-gray-9"
									>{{ r.custom_adonan_ke }}</span
								>
								<span v-else class="pl-3 text-ink-gray-4">–</span>
							</td>
							<td class="px-3" :class="pad">
								<div class="font-medium text-ink-gray-9">{{ r.item_name }}</div>
								<div v-if="show('item_code')" class="text-xs text-ink-gray-5">{{ r.production_item }}</div>
							</td>
							<td class="whitespace-nowrap px-3 text-right tabular-nums" :class="pad">
								<span class="text-base font-semibold text-ink-gray-9">{{ qtyValue(r).n }}</span>
								<span class="ml-1 text-xs text-ink-gray-5">{{ qtyValue(r).uom }}</span>
							</td>
							<td v-if="show('wo') || show('warehouse')" class="hidden px-3 md:table-cell" :class="pad">
								<a
									v-if="show('wo')"
									:href="`/app/work-order/${encodeURIComponent(r.name)}`"
									target="_blank"
									class="whitespace-nowrap text-ink-gray-7 underline decoration-transparent underline-offset-2 hover:decoration-current"
									@click.stop
									>{{ r.name }}</a
								>
								<div v-if="show('warehouse')" class="whitespace-nowrap text-xs text-ink-gray-5">{{ r.fg_warehouse }}</div>
							</td>
							<td v-if="show('status')" class="px-3 pr-4" :class="pad">
								<div class="whitespace-nowrap text-ink-gray-8">
									{{ stateOf(r) === 'ready' ? 'Ready' : stateOf(r) === 'requested' ? 'Requested' : 'Shipped' }}
								</div>
								<div v-if="r.custom_handover_material_request" class="whitespace-nowrap text-xs text-ink-gray-5">
									<template>
										<a
											:href="`/app/material-request/${encodeURIComponent(r.custom_handover_material_request)}`"
											target="_blank"
											class="underline decoration-transparent underline-offset-2 hover:decoration-current"
											@click.stop
											>{{ r.custom_handover_material_request }}</a
										>
										<span v-if="r.box_plan">, group of {{ r.group_size || 0 }}</span>
									</template>
								</div>
							</td>
						</tr>
					</tbody>
				</table>
			</div>
			<div v-if="!shownRows.length && !loading" class="flex flex-col items-center gap-2 px-6 py-16 text-center">
				<FeatherIcon name="inbox" class="h-8 w-8 text-ink-gray-3" />
				<p class="text-sm text-ink-gray-6">
					{{
						rows.length
							? `No ${VIEWS.find((v) => v.key === view).label.toLowerCase()} batches in this list.`
							: 'No finished batches match. Try a different search or clear the filters.'
					}}
				</p>
				<Button v-if="rows.length" variant="ghost" size="sm" label="Show all" @click="view = 'all'" />
			</div>
			<div v-if="rows.length" class="flex items-center justify-between border-t border-outline-gray-2 px-4 py-2">
				<span class="text-xs text-ink-gray-5">
					Showing {{ fmtNum(shownRows.length) }} of {{ fmtNum(rows.length) }} loaded
				</span>
				<Button v-if="canLoadMore" variant="ghost" size="sm" :loading="loading" label="Load more" @click="load(true)" />
			</div>
		</div>

		<!-- bar aksi seleksi (mengapung) -->
		<div
			v-if="nSelected"
			class="fixed bottom-6 left-1/2 z-40 flex -translate-x-1/2 items-center gap-3 rounded-full border border-outline-gray-2 bg-surface-modal py-2 pl-5 pr-2 shadow-lg"
		>
			<span class="whitespace-nowrap text-sm font-medium text-ink-gray-7">
				{{ nSelected }} selected
			</span>
			<button
				class="text-sm text-ink-gray-4 hover:text-ink-gray-7"
				@click="selectedNames = []"
			>
				Clear
			</button>
			<Button variant="solid" @click="onPrimaryAction">
				{{
					groupSelection
						? `Create Group Request (${nSelected})`
						: nSelected
							? `Create Request (${nSelected})`
							: 'Create Request'
				}}
			</Button>
		</div>

		<!-- bar cancel (mengapung, gaya yang sama) — muncul saat baris Requested diklik -->
		<div
			v-if="cancelPickRow"
			class="fixed bottom-6 left-1/2 z-40 flex -translate-x-1/2 items-center gap-3 rounded-full border border-outline-gray-2 bg-surface-modal py-2 pl-5 pr-2 shadow-lg"
		>
			<span class="text-sm font-medium text-ink-gray-7">
				{{
					cancelPickRow.box_plan
						? `Group ${cancelPickRow.box_plan} · ${fmtNum(Number(cancelPickRow.group_size || 0))} Work Orders`
						: cancelPickRow.custom_handover_material_request
				}}
			</span>
			<button class="text-sm text-ink-gray-4 hover:text-ink-gray-7" @click="cancelPick = null">
				Clear
			</button>
			<Button
				variant="subtle"
				theme="red"
				:label="cancelPickRow.box_plan ? 'Cancel Group' : 'Cancel Request'"
				@click="askCancel()"
			/>
		</div>

		<!-- dialog -->
		<RequestDialog v-model="bulkDialog" :rows="selectedRows" @done="onBulkDone" />
		<GroupRequestDialog v-model="groupDialog" :rows="groupSelection || []" @done="onGroupDone" />
		<ConfirmDialog v-model="cancelOpen" :options="cancelOptions" :on-confirm="doCancel" />
	</div>
</template>
