<script setup>
// Halaman Serah Terima Gudang (SPA, W33-r8) — pengganti shortcut Desk ke
// report klasik. Data dari report standar via query_report.run; tabel memakai
// PrimeVue DataTable (paginator + sort client-side), status & aksi memakai
// pola papan: pill warna sama (Belum Dikirim/Sebagian/Terkirim) dan tombol
// mapper native make_stock_entry (hasil DRAFT SE dibuka di tab Desk).
import { computed, onMounted, ref, watch } from 'vue'
import Select from 'primevue/select'
import { Button } from '@frappe-ui/components/Button'
import FeatherIcon from '@frappe-ui/components/FeatherIcon.vue'
import { fetchSerahTerima, searchWarehouses, makeStockEntry } from '@/data/serahTerima'
import { fmtNum } from '@/lib/format'
import { dayjs } from '@frappe-ui/utils/dayjs'
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
	{ label: 'Not shipped', value: 'Belum Dikirim', dot: 'bg-orange-500' },
	{ label: 'Partial', value: 'Sebagian', dot: 'bg-blue-500' },
	{ label: 'Shipped', value: 'Terkirim', dot: 'bg-green-500' },
]
const STRIP = { 'Belum Dikirim': 'bg-orange-500', Sebagian: 'bg-blue-500', Terkirim: 'bg-green-500' }
const BAR = { 'Belum Dikirim': 'bg-orange-400', Sebagian: 'bg-blue-500', Terkirim: 'bg-green-500' }

const counts = computed(() => {
	const c = { all: rows.value.length }
	rows.value.forEach((r) => (c[r.status_papan] = (c[r.status_papan] || 0) + 1))
	return c
})
const pct = (r) =>
	Number(r.qty_diminta) > 0 ? Math.min(100, (Number(r.qty_dikirim) / Number(r.qty_diminta)) * 100) : 0

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

// tampil bertahap (client-side) + dikelompokkan per tanggal MR
const PAGE = 50
const limit = ref(PAGE)
watch([search, statusTab, rows], () => (limit.value = PAGE))
const days = computed(() => {
	const out = []
	for (const r of filteredRows.value.slice(0, limit.value)) {
		const d = String(r.transaction_date || '').slice(0, 10)
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

onMounted(() => {
	load()
})
</script>

<template>
	<div class="space-y-5">
		<div>
			<h1 class="text-2xl font-semibold tracking-tight text-ink-gray-9">Handover Monitoring</h1>
			<p class="mt-1 text-sm text-ink-gray-5">
				Material Requests from production and how much has reached the warehouse.
			</p>
		</div>

		<div class="overflow-hidden rounded-lg border border-outline-gray-2 bg-surface-modal">
			<!-- tab status -->
			<div class="flex gap-6 overflow-x-auto border-b border-outline-gray-2 px-4" role="tablist" aria-label="Status">
				<button
					v-for="t in statusTabs"
					:key="t.value"
					role="tab"
					:aria-selected="statusTab === t.value"
					class="-mb-px flex h-11 shrink-0 items-center gap-2 border-b-2 text-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-outline-gray-4"
					:class="statusTab === t.value ? 'border-gray-900 font-medium text-ink-gray-9 dark:border-gray-100' : 'border-transparent text-ink-gray-5 hover:text-ink-gray-8'"
					@click="statusTab = t.value"
				>
					<span v-if="t.dot" class="h-2 w-2 rounded-full" :class="t.dot" />
					{{ t.label }}
					<span
						class="rounded-full px-1.5 text-xs tabular-nums"
						:class="statusTab === t.value ? 'bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900' : 'bg-surface-gray-2 text-ink-gray-6'"
						>{{ counts[t.value] || 0 }}</span
					>
				</button>
			</div>

			<!-- toolbar -->
			<div class="flex flex-wrap items-center gap-2 border-b border-outline-gray-2 bg-surface-gray-1 px-4 py-3">
				<label class="relative min-w-0 flex-1 basis-64">
					<span class="sr-only">Search</span>
					<FeatherIcon name="search" class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-gray-5" />
					<input
						v-model="search"
						type="search"
						placeholder="Search MR, batch, item, or work order"
						class="h-9 w-full rounded-md border border-outline-gray-2 bg-surface-white pl-9 pr-3 text-sm text-ink-gray-8 placeholder:text-ink-gray-4 focus:border-outline-gray-4 focus:outline-none focus:ring-2 focus:ring-outline-gray-2 dark:bg-surface-gray-2"
					/>
				</label>
				<Select
					v-model="warehouse"
					:options="warehouseOptions"
					placeholder="All warehouses"
					class="pv-select !h-9 min-w-52"
					showClear
					filter
					filterPlaceholder="Search warehouse"
					aria-label="Destination warehouse"
					@filter="onWarehouseFilter"
				/>
				<Button variant="ghost" icon="refresh-cw" :loading="loading" aria-label="Refresh" title="Refresh" @click="load()" />
			</div>

			<!-- daftar per tanggal MR -->
			<div class="overflow-x-auto transition-opacity" :class="{ 'opacity-50': loading }">
				<table class="w-full text-sm">
					<thead>
						<tr class="border-b border-outline-gray-2 text-left text-xs text-ink-gray-5">
							<th class="w-20 py-2.5 pl-5 pr-2 font-medium">Batch</th>
							<th class="px-3 py-2.5 font-medium">Item</th>
							<th class="w-56 px-3 py-2.5 font-medium">Shipped</th>
							<th class="hidden px-3 py-2.5 font-medium lg:table-cell">Destination</th>
							<th class="hidden px-3 py-2.5 font-medium md:table-cell">Material Request</th>
							<th class="py-2.5 pl-3 pr-4"><span class="sr-only">Action</span></th>
						</tr>
					</thead>
					<tbody v-for="day in days" :key="day.date">
						<tr class="border-b border-outline-gray-1 bg-surface-gray-1">
							<td colspan="6" class="py-2 pl-5 pr-4 text-xs">
								<span class="font-semibold text-ink-gray-8">{{ dayLabel(day.date) }}</span>
								<span class="ml-2 text-ink-gray-5">{{ day.rows.length }} {{ day.rows.length === 1 ? 'line' : 'lines' }}</span>
							</td>
						</tr>
						<tr v-for="r in day.rows" :key="r._key" class="border-b border-outline-gray-1 last:border-b-0">
							<td class="relative py-3 pl-5 pr-2">
								<span class="absolute inset-y-0 left-0 w-[3px]" :class="STRIP[r.status_papan] || 'bg-gray-300'" />
								<span
									v-if="r.adonan != null && r.adonan !== ''"
									class="inline-flex h-8 min-w-[2.5rem] items-center justify-center rounded-md border border-outline-gray-2 px-2 text-base font-semibold tabular-nums text-ink-gray-9"
									>{{ r.adonan }}</span
								>
								<span v-else class="pl-3 text-ink-gray-4">–</span>
							</td>
							<td class="px-3 py-3">
								<div class="font-medium text-ink-gray-9">{{ r.item_name }}</div>
								<div class="text-xs text-ink-gray-5">{{ r.item_code }}</div>
							</td>
							<td class="px-3 py-3">
								<div class="flex items-baseline gap-1 whitespace-nowrap tabular-nums">
									<span class="text-base font-semibold text-ink-gray-9">{{ fmtNum(r.qty_dikirim) }}</span>
									<span class="text-ink-gray-5">/ {{ fmtNum(r.qty_diminta) }} {{ r.stock_uom }}</span>
								</div>
								<div
									class="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-surface-gray-3"
									role="progressbar"
									:aria-valuenow="Math.round(pct(r))"
									aria-valuemin="0"
									aria-valuemax="100"
									:aria-label="`${r.item_name} shipped`"
								>
									<div class="h-full rounded-full" :class="BAR[r.status_papan] || 'bg-gray-400'" :style="{ width: pct(r) + '%' }" />
								</div>
								<div v-if="Number(r.qty_sisa) > 0" class="mt-1 text-xs text-orange-700 dark:text-orange-400">
									{{ fmtNum(r.qty_sisa) }} {{ r.stock_uom }} left to ship
								</div>
							</td>
							<td class="hidden px-3 py-3 lg:table-cell">
								<div class="whitespace-nowrap text-ink-gray-7">{{ r.gudang_tujuan }}</div>
								<a
									v-if="r.work_order"
									:href="`/app/work-order/${encodeURIComponent(r.work_order)}`"
									target="_blank"
									class="whitespace-nowrap text-xs text-ink-gray-5 underline decoration-transparent underline-offset-2 hover:decoration-current"
									>{{ r.work_order }}</a
								>
							</td>
							<td class="hidden px-3 py-3 md:table-cell">
								<a
									:href="`/app/material-request/${encodeURIComponent(r.material_request)}`"
									target="_blank"
									class="whitespace-nowrap text-ink-gray-7 underline decoration-transparent underline-offset-2 hover:decoration-current"
									>{{ r.material_request }}</a
								>
								<div class="whitespace-nowrap text-xs text-ink-gray-5">{{ r.status_mr }}</div>
							</td>
							<td class="py-3 pl-3 pr-4 text-right">
								<template v-if="r.status_papan !== 'Terkirim'">
									<Button
										class="hidden sm:inline-flex"
										variant="subtle"
										size="sm"
										icon-left="truck"
										label="Create Stock Entry"
										:title="`Create a draft Stock Entry for ${r.material_request}`"
										:loading="making === r._key"
										@click="makeSE(r)"
									/>
									<Button
										class="sm:hidden"
										variant="subtle"
										icon="truck"
										:aria-label="`Create Stock Entry for ${r.material_request}`"
										:loading="making === r._key"
										@click="makeSE(r)"
									/>
								</template>
								<FeatherIcon v-else name="check" class="ml-auto h-4 w-4 text-green-600" aria-label="Shipped" />
							</td>
						</tr>
					</tbody>
				</table>
			</div>

			<div v-if="!filteredRows.length && !loading" class="flex flex-col items-center gap-2 px-6 py-16 text-center">
				<FeatherIcon name="truck" class="h-8 w-8 text-ink-gray-3" />
				<p class="text-sm text-ink-gray-6">
					{{
						rows.length
							? 'Nothing matches. Try a different search or status.'
							: 'No handover requests yet. They appear here once the warehouse requests finished batches.'
					}}
				</p>
			</div>
			<div v-if="filteredRows.length" class="flex items-center justify-between border-t border-outline-gray-2 px-4 py-2">
				<span class="text-xs text-ink-gray-5">
					Showing {{ fmtNum(Math.min(limit, filteredRows.length)) }} of {{ fmtNum(filteredRows.length) }}
				</span>
				<Button
					v-if="filteredRows.length > limit"
					variant="ghost"
					size="sm"
					label="Show more"
					@click="limit += PAGE"
				/>
			</div>
		</div>
	</div>
</template>
