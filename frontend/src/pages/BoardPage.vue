<script setup>
// Papan Serah Terima Gudang (SPA, W33) — port paritas penuh dari page
// klasik gudang_request: search, filter builder, UOM switcher, pemilih
// kolom, kepadatan, checklist + deteksi grup, dialog bulk/group (qty-only,
// semantik W30), cancel tunggal/grup, pill status, Load more.
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { Button } from '@frappe-ui/components/Button'
import { TextInput } from '@frappe-ui/components/TextInput'
import FeatherIcon from '@frappe-ui/components/FeatherIcon.vue'
import { toast } from '@/lib/toast'
import { fetchWorkOrders, fetchFilterFields, cancelRequest, cancelGroupRequest } from '@/data/board'
import { loadPref, savePref, hasPref } from '@/lib/prefs'
import { fmtNum, fmtDate } from '@/lib/format'
import StatusPill from '@/components/StatusPill.vue'
import FilterBuilder from '@/components/FilterBuilder.vue'
import DisplayMenu from '@/components/DisplayMenu.vue'
import RequestDialog from '@/components/RequestDialog.vue'
import GroupRequestDialog from '@/components/GroupRequestDialog.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'

const PAGE_SIZE = 50

const ALL_COLUMNS = [
	{ key: 'batch', label: 'Batch' },
	{ key: 'item', label: 'Item' },
	{ key: 'item_code', label: 'Item Code' },
	{ key: 'qty', label: 'Qty' },
	{ key: 'wo', label: 'Work Order' },
	{ key: 'warehouse', label: 'Warehouse' },
	{ key: 'created', label: 'Created' },
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
const visibleCols = ref(loadPref('columns', ALL_COLUMNS.map((c) => c.key)))
const hasColPref = hasPref('columns')
const density = ref(loadPref('density', 'comfort'))

const bulkDialog = ref(false)
const groupDialog = ref(false)
const cancelOpen = ref(false)
const cancelTarget = ref(null) // { mr, plan, size } | null
// baris Requested yang dilibatkan utk cancel — tampil di bar mengapung,
// gaya yang sama dgn bar Create Request (saling eksklusif dgn seleksi)
const cancelPick = ref(null)

// layar sempit — matchMedia (bukan innerWidth langsung: nilai saat setup
// bisa terbaca sebelum layout pane siap dan tidak ada event resize susulan)
const narrowMq =
	typeof window !== 'undefined' ? window.matchMedia('(max-width: 640px)') : null
const narrow = ref(!!(narrowMq && narrowMq.matches))
const onNarrowChange = (e) => {
	narrow.value = e.matches
}
if (narrowMq) {
	narrowMq.addEventListener('change', onNarrowChange)
}
onMounted(() => {
	if (narrowMq) {
		narrow.value = narrowMq.matches
	}
})
onUnmounted(() => {
	if (narrowMq) {
		narrowMq.removeEventListener('change', onNarrowChange)
	}
})

// ---- kolom tampil
const cols = computed(() => {
  let keys = visibleCols.value
  // layar sempit & user belum pernah mengatur kolom: kolom sekunder
  // disembunyikan (aturan klasik ≤640)
  if (!hasColPref && narrow.value) {
    keys = keys.filter((k) => k !== 'item_code' && k !== 'created')
  }
  // urutan SELALU kanonik (pref hanya menentukan anggota) — header dan
  // isi baris digenerate dari `cols` yang sama sehingga tak bisa silang
  return ALL_COLUMNS.filter((c) => keys.includes(c.key))
})

// kelas sel per kolom (dipakai body v-for agar urutan = header)
function cellCls(key) {
  const pad = density.value === 'compact' ? 'py-1.5' : 'py-3'
  const byKey = {
    batch: 'whitespace-nowrap font-medium text-ink-gray-7',
    item: 'text-ink-gray-8',
    item_code: 'whitespace-nowrap text-ink-gray-6',
    qty: 'whitespace-nowrap tabular-nums text-ink-gray-8',
    wo: 'whitespace-nowrap font-mono text-xs text-ink-gray-6',
    warehouse: 'whitespace-nowrap text-ink-gray-6',
    created: 'whitespace-nowrap text-ink-gray-5',
    status: '',
  }
  return `px-3 ${pad} ${byKey[key] || ''}`
}

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
		return `${fmtNum(r.expected_units != null ? r.expected_units : 0)} ${r.display_uom}`
	}
	return `${fmtNum(r.produced_qty || 0)} ${r.stock_uom}`
}

function setUom(uom) {
	selectedNames.value = []
	cancelPick.value = null
	qtyUom.value = uom
	savePref('qty_uom', uom)
}

// ---- seleksi
const selectableRows = computed(() => rows.value.filter((r) => !r.request_active && !r.request_shipped))
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
				message: `Cancel the ENTIRE group (${t.size} Work Orders)? Boxes are shared, so cancel all.`,
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
	<div class="space-y-4">
		<!-- header -->
		<div class="flex flex-wrap items-end justify-between gap-3">
			<div>
				<h1 class="text-2xl font-semibold tracking-tight text-ink-gray-9">Handover Requests</h1>
				<p class="mt-0.5 text-sm text-ink-gray-5">
					Work Orders ready to be requested by the warehouse team.
				</p>
			</div>
			<Button variant="subtle" label="Refresh" icon-left="refresh-cw" @click="refresh()" />
		</div>

		<!-- toolbar -->
		<div class="flex flex-wrap items-center gap-2">
			<TextInput
				v-model="search"
				class="w-full sm:w-72"
				type="text"
				placeholder="Search batch, item, or work order..."
				@keydown.enter="refresh"
			/>
			<FilterBuilder v-model="filters" :meta="fieldMeta" @change="onFilterChange" />
			<DisplayMenu
				v-model:visible="visibleCols"
				v-model:density="density"
				:columns="ALL_COLUMNS"
				@update:visible="setCols"
			/>
			<select
				v-if="uomOptions.length > 1"
				class="h-8 min-w-[5.5rem] rounded-md border border-outline-gray-2 bg-surface-modal py-0 pl-2 pr-6 text-sm leading-none text-ink-gray-7"
				:value="qtyUom"
				title="Qty unit"
				@change="setUom($event.target.value)"
			>
				<option v-for="o in uomOptions" :key="o" :value="o">{{ o }}</option>
			</select>
		</div>

		<!-- tabel -->
		<div
			class="overflow-hidden rounded-lg border border-outline-gray-1 bg-surface-modal transition-opacity"
			:class="{ 'opacity-50': loading }"
		>
			<div class="overflow-x-auto">
				<table class="w-full text-sm">
					<thead>
						<tr class="border-b border-outline-gray-1 bg-surface-gray-1 text-left text-xs font-medium text-ink-gray-5">
							<th class="w-10 px-3 py-2">
								<input
									type="checkbox"
									class="h-3.5 w-3.5 accent-ink-gray-9"
									:checked="allChecked"
									:indeterminate.prop="someChecked"
									aria-label="Select all"
									@change="toggleAll($event.target.checked)"
								/>
							</th>
							<th
								v-for="c in cols"
								:key="c.key"
								class="whitespace-nowrap px-3 py-2 font-medium"
							>
								{{ c.key === 'qty' && qtyUom ? `Qty (${qtyUom})` : c.label }}
							</th>
							<th class="w-24 px-3 py-2"></th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="r in rows"
							:key="r.name"
							class="cursor-pointer border-b border-outline-gray-1 last:border-b-0 hover:bg-surface-gray-1"
							:class="{
								'bg-surface-selected hover:bg-surface-selected': selectedNames.includes(r.name),
								'bg-surface-gray-1': cancelPick === r.name,
								'cursor-default': r.request_shipped,
							}"
							@click="toggleRow(r)"
						>
							<td class="px-3" :class="density === 'compact' ? 'py-1.5' : 'py-3'">
								<input
									type="checkbox"
									class="h-3.5 w-3.5 accent-ink-gray-9"
									:disabled="r.request_active || r.request_shipped"
									:checked="selectedNames.includes(r.name)"
									:aria-label="r.name"
									@click.stop
									@change="toggleRow(r)"
								/>
							</td>
							<!-- sel digenerate dari `cols` yang sama dgn header — urutan tak mungkin silang -->
							<td v-for="c in cols" :key="c.key" :class="cellCls(c.key)">
								<StatusPill v-if="c.key === 'status'" :row="r" />
								<template v-else-if="c.key === 'batch'">{{ r.custom_adonan_ke || '—' }}</template>
								<template v-else-if="c.key === 'item'">{{ r.item_name }}</template>
								<template v-else-if="c.key === 'item_code'">{{ r.production_item }}</template>
								<template v-else-if="c.key === 'qty'">{{ qtyValue(r) }}</template>
								<template v-else-if="c.key === 'wo'">{{ r.name }}</template>
								<template v-else-if="c.key === 'warehouse'">{{ r.fg_warehouse }}</template>
								<template v-else-if="c.key === 'created'">{{ fmtDate(r.creation) }}</template>
							</td>
							<td class="px-3 text-right" :class="density === 'compact' ? 'py-1.5' : 'py-3'"></td>
						</tr>
					</tbody>
				</table>
			</div>
			<div
				v-if="!rows.length && !loading"
				class="flex flex-col items-center gap-2 px-6 py-14 text-center"
			>
				<FeatherIcon name="package" class="h-8 w-8 text-ink-gray-3" />
				<p class="text-sm text-ink-gray-4">
					No matching Work Orders. Try a different search or clear the filters.
				</p>
			</div>
			<div
				v-if="rows.length"
				class="flex items-center justify-between border-t border-outline-gray-1 px-3 py-2"
			>
				<span class="text-xs text-ink-gray-5">
					{{ rows.length === 1 ? '1 Work Order' : `${fmtNum(rows.length)} Work Orders` }}
				</span>
				<Button v-if="canLoadMore" variant="ghost" size="sm" :loading="loading" label="Load more" @click="load(true)" />
			</div>
		</div>

		<!-- bar aksi seleksi (mengapung) -->
		<div
			v-if="nSelected"
			class="fixed bottom-6 left-1/2 z-40 flex -translate-x-1/2 items-center gap-3 rounded-full border border-outline-gray-2 bg-surface-modal py-2 pl-5 pr-2 shadow-lg"
		>
			<span class="text-sm font-medium text-ink-gray-7">
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
