<script setup>
// Halaman Serah Terima Gudang (SPA, W33-r8) — pengganti shortcut Desk ke
// report klasik. Data dari report standar via query_report.run; tabel memakai
// PrimeVue DataTable (paginator + sort client-side), status & aksi memakai
// pola papan: pill warna sama (Belum Dikirim/Sebagian/Terkirim) dan tombol
// mapper native make_stock_entry (hasil DRAFT SE dibuka di tab Desk).
import { computed, onMounted, ref, watch } from 'vue'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Select from 'primevue/select'
import { Button } from '@frappe-ui/components/Button'
import { TextInput } from '@frappe-ui/components/TextInput'
import { TabButtons } from '@frappe-ui/components/TabButtons'
import FeatherIcon from '@frappe-ui/components/FeatherIcon.vue'
import { fetchSerahTerima, searchWarehouses, makeStockEntry } from '@/data/serahTerima'
import { fmtNum, fmtDate } from '@/lib/format'
import { toast } from '@/lib/toast'

const rows = ref([])
const loading = ref(false)
const search = ref('')
const statusTab = ref('all')
const warehouse = ref(null)
const making = ref('') // _key baris yang sedang membuat draft SE

// bucket status berasal dari report (per_ordered native) — label Indonesia
// adalah nilai datanya; tab hanya memfilternya, dgn label Inggris.
const statusTabs = [
	{ label: 'All', value: 'all' },
	{ label: 'Not Shipped', value: 'Belum Dikirim' },
	{ label: 'Partial', value: 'Sebagian' },
	{ label: 'Shipped', value: 'Terkirim' },
]

const PILL = {
	'Belum Dikirim':
		'bg-orange-100 text-orange-800 dark:bg-orange-500/15 dark:text-orange-300',
	Sebagian: 'bg-blue-100 text-blue-800 dark:bg-blue-500/15 dark:text-blue-300',
	Terkirim: 'bg-green-100 text-green-800 dark:bg-green-500/15 dark:text-green-300',
}

const DOT = {
	'Belum Dikirim': 'bg-orange-500',
	Sebagian: 'bg-blue-500',
	Terkirim: 'bg-green-500',
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
	return out
})

async function load() {
	loading.value = true
	try {
		const res = await fetchSerahTerima(
			warehouse.value ? { gudang_tujuan: warehouse.value } : {},
		)
		const data = Array.isArray(res?.result) ? res.result : []
		// baris total (non-dict) dari report dibuang; _key unik utk DataTable
		rows.value = data
			.filter((r) => r && typeof r === 'object')
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
// yang muncul di data report, mengetik mencari ke server (like, limit 20)
const warehouseOptions = ref([])

function mergeWarehouseOptions(names) {
	warehouseOptions.value = [
		...new Set([...names.filter(Boolean), ...warehouseOptions.value]),
	].sort((a, b) => a.localeCompare(b))
}

function syncWarehouseOptionsFromData() {
	mergeWarehouseOptions([...new Set(rows.value.map((r) => r.gudang_tujuan))])
}

let whFilterTimer = null
function onWarehouseFilter(e) {
	clearTimeout(whFilterTimer)
	const q = String(e?.value || '').trim()
	if (!q) {
		return
	}
	whFilterTimer = setTimeout(async () => {
		try {
			const res = await searchWarehouses(q)
			mergeWarehouseOptions((res || []).map((w) => w.name))
		} catch {
			/* biarkan opsi yg ada; jangan blokir dropdown */
		}
	}, 250)
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

function boxVal(v) {
	return v == null || v === '' ? '—' : fmtNum(v)
}

onMounted(() => {
	load()
})
</script>

<template>
	<div class="space-y-4">
		<!-- header -->
		<div class="flex flex-wrap items-end justify-between gap-3">
			<div>
				<h1 class="text-2xl font-semibold tracking-tight text-ink-gray-9">
					Serah Terima Gudang
				</h1>
				<p class="mt-0.5 text-sm text-ink-gray-5">
					Delivery status of Material Requests from production to the warehouse.
				</p>
			</div>
			<Button variant="subtle" label="Refresh" icon-left="refresh-cw" @click="load()" />
		</div>

		<!-- toolbar -->
		<div class="flex flex-wrap items-center gap-2">
			<TextInput
				v-model="search"
				class="w-full sm:w-64"
				type="text"
				placeholder="Search MR, item, or work order..."
			/>
			<TabButtons v-model="statusTab" :buttons="statusTabs" />
			<Select
				v-model="warehouse"
				:options="warehouseOptions"
				placeholder="All warehouses"
				class="pv-select min-w-44"
				showClear
				filter
				filterPlaceholder="Search warehouse..."
				@filter="onWarehouseFilter"
			/>
		</div>

		<!-- tabel — loading = dim ala papan (overlay mask PrimeVue meninggalkan
		     elemen hantu saat enter/leave beruntun di environment ini) -->
		<div
			class="overflow-hidden rounded-lg border border-outline-gray-1 bg-surface-modal transition-opacity"
			:class="{ 'opacity-50': loading }"
		>
			<DataTable
				:value="filteredRows"
				dataKey="_key"
				paginator
				:rows="25"
				:rowsPerPageOptions="[25, 50, 100]"
				paginatorTemplate="CurrentPageReport FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown"
				currentPageReportTemplate="Showing {first} to {last} of {totalRecords} rows"
				class="pv-table"
				sortMode="single"
				removableSort
			>
				<template #empty>
					<div class="flex flex-col items-center gap-2 px-6 py-14 text-center">
						<FeatherIcon name="package" class="h-8 w-8 text-ink-gray-3" />
						<p class="text-sm text-ink-gray-4">
							No matching rows. Try a different search or clear the filters.
						</p>
					</div>
				</template>

				<Column field="material_request" header="Material Request" sortable>
					<template #body="{ data }">
						<a
							:href="`/app/material-request/${encodeURIComponent(data.material_request)}`"
							target="_blank"
							class="whitespace-nowrap text-ink-gray-8 underline decoration-transparent underline-offset-2 hover:decoration-current"
							>{{ data.material_request }}</a
						>
					</template>
				</Column>
				<Column field="transaction_date" header="Date" sortable>
					<template #body="{ data }">
						<span class="whitespace-nowrap text-ink-gray-5">{{ fmtDate(data.transaction_date) }}</span>
					</template>
				</Column>
				<Column field="adonan" header="Batch" sortable>
					<template #body="{ data }">
						<span class="whitespace-nowrap font-medium text-ink-gray-7">{{
							data.adonan == null || data.adonan === '' ? '—' : data.adonan
						}}</span>
					</template>
				</Column>
				<Column field="item_name" header="Item" sortable>
					<template #body="{ data }">
						<span class="whitespace-nowrap text-ink-gray-8">{{ data.item_name }}</span>
					</template>
				</Column>
				<Column field="item_code" header="Item Code" sortable>
					<template #body="{ data }">
						<span class="whitespace-nowrap text-ink-gray-6">{{ data.item_code }}</span>
					</template>
				</Column>
				<Column field="work_order" header="Work Order" sortable>
					<template #body="{ data }">
						<span class="whitespace-nowrap font-mono text-xs text-ink-gray-6">{{
							data.work_order || '—'
						}}</span>
					</template>
				</Column>
				<Column field="qty_diminta" header="Requested" sortable>
					<template #body="{ data }">
						<span class="whitespace-nowrap tabular-nums text-ink-gray-8">{{ fmtNum(data.qty_diminta) }}</span>
					</template>
				</Column>
				<Column field="qty_dikirim" header="Shipped" sortable>
					<template #body="{ data }">
						<span class="whitespace-nowrap tabular-nums text-ink-gray-8">{{ fmtNum(data.qty_dikirim) }}</span>
					</template>
				</Column>
				<Column field="qty_sisa" header="Remaining" sortable>
					<template #body="{ data }">
						<span
							class="whitespace-nowrap tabular-nums"
							:class="Number(data.qty_sisa) > 0 ? 'font-medium text-orange-600 dark:text-orange-400' : 'text-ink-gray-5'"
							>{{ fmtNum(data.qty_sisa) }}</span
						>
					</template>
				</Column>
				<Column field="stock_uom" header="UOM">
					<template #body="{ data }">
						<span class="whitespace-nowrap text-ink-gray-6">{{ data.stock_uom }}</span>
					</template>
				</Column>
				<Column field="gudang_tujuan" header="Destination Warehouse" sortable>
					<template #body="{ data }">
						<span class="whitespace-nowrap text-ink-gray-6">{{ data.gudang_tujuan }}</span>
					</template>
				</Column>
				<Column field="box_1" header="Box 1 (kg)" sortable>
					<template #body="{ data }">
						<span class="whitespace-nowrap tabular-nums text-ink-gray-6">{{ boxVal(data.box_1) }}</span>
					</template>
				</Column>
				<Column field="box_2" header="Box 2 (kg)" sortable>
					<template #body="{ data }">
						<span class="whitespace-nowrap tabular-nums text-ink-gray-6">{{ boxVal(data.box_2) }}</span>
					</template>
				</Column>
				<Column field="box_3" header="Box 3 (kg)" sortable>
					<template #body="{ data }">
						<span class="whitespace-nowrap tabular-nums text-ink-gray-6">{{ boxVal(data.box_3) }}</span>
					</template>
				</Column>
				<Column field="status_papan" header="Status" sortable>
					<template #body="{ data }">
						<span
							v-if="data.status_papan"
							class="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium"
							:class="PILL[data.status_papan] || 'bg-surface-gray-3 text-ink-gray-6'"
						>
							<span
								class="h-1.5 w-1.5 shrink-0 rounded-full"
								:class="DOT[data.status_papan] || 'bg-ink-gray-4'"
							/>
							{{ data.status_papan }}
						</span>
					</template>
				</Column>
				<Column field="status_mr" header="MR Status">
					<template #body="{ data }">
						<span class="whitespace-nowrap text-ink-gray-5">{{ data.status_mr }}</span>
					</template>
				</Column>
				<Column header="">
					<template #body="{ data }">
						<Button
							v-if="data.status_papan !== 'Terkirim'"
							variant="subtle"
							size="sm"
							label="Make Stock Entry"
							:loading="making === data._key"
							@click="makeSE(data)"
						/>
					</template>
				</Column>
			</DataTable>
		</div>
	</div>
</template>
