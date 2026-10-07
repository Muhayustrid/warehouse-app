<script setup>
// Halaman Inventory (W40). Empat tab di atas ledger native (SLE + Bin);
// semua tabel lazy — paginasi, filter, dan agregasi di server
// (warehouse_app.warehouse_app.inventory). Qty tampil dalam Default
// Inventory UOM item, nilai dalam Rupiah.
import { computed, onMounted, ref, watch } from 'vue'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Select from 'primevue/select'
import { Button } from '@frappe-ui/components/Button'
import { TextInput } from '@frappe-ui/components/TextInput'
import { TabButtons } from '@frappe-ui/components/TabButtons'
import FeatherIcon from '@frappe-ui/components/FeatherIcon.vue'
import { dayjs } from '@frappe-ui/utils/dayjs'
import DateRangeField from '@/components/DateRangeField.vue'
import { fetchStockCards, fetchFilterOptions } from '@/data/inventory'
import { fmtQty, fmtRp, fmtDateTime } from '@/lib/format'
import { toast } from '@/lib/toast'

const tabs = [
	{ label: 'Current Stock', value: 'current', disabled: true },
	{ label: 'Stock Cards', value: 'cards' },
	{ label: 'Inventory Movements', value: 'movements', disabled: true },
	{ label: 'Inventory Costs', value: 'costs', disabled: true },
]
const tab = ref('cards')

// ---- filter bersama ----
const warehouse = ref(null)
const warehouseOptions = ref([])
const itemGroupOptions = ref([])
const item = ref('')
const itemGroup = ref(null)
const showFilters = ref(false)

const RANGES = ['Today', 'Yesterday', 'This Week', 'This Month', 'Custom']
const range = ref('This Month')
const customFrom = ref('')
const customTo = ref('')

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

// ---- tabel lazy ----
const rows = ref([])
const total = ref(0)
const loading = ref(false)
const first = ref(0)
const pageLen = ref(20)
let seq = 0

async function load() {
	const mine = ++seq
	loading.value = true
	try {
		const res = await fetchStockCards({
			...filters.value,
			page: Math.floor(first.value / pageLen.value) + 1,
			page_len: pageLen.value,
		})
		if (mine !== seq) {
			return // respons basi dari filter sebelumnya
		}
		rows.value = res?.rows || []
		total.value = res?.total || 0
	} catch (e) {
		if (mine === seq) {
			toast.error(e.message)
		}
	} finally {
		if (mine === seq) {
			loading.value = false
		}
	}
}

function onPage(e) {
	first.value = e.first
	pageLen.value = e.rows
	load()
}

// ketik item: debounce; filter lain: langsung. Selalu kembali ke halaman 1.
let typing = null
watch(
	filters,
	(now, before) => {
		clearTimeout(typing)
		const reload = () => {
			first.value = 0
			load()
		}
		if (before && now.item !== before.item) {
			typing = setTimeout(reload, 350)
		} else {
			reload()
		}
	},
	{ deep: true },
)

onMounted(async () => {
	load()
	try {
		const opts = await fetchFilterOptions()
		warehouseOptions.value = opts?.warehouses || []
		itemGroupOptions.value = opts?.item_groups || []
	} catch (e) {
		toast.error(e.message)
	}
})

const desk = (doctype, name) =>
	`/app/${doctype.toLowerCase().replace(/ /g, '-')}/${encodeURIComponent(name)}`
</script>

<template>
	<div class="space-y-4">
		<!-- header -->
		<div class="flex flex-wrap items-end justify-between gap-3">
			<div>
				<h1 class="text-2xl font-semibold tracking-tight text-ink-gray-9">Inventory</h1>
				<p class="mt-0.5 text-sm text-ink-gray-5">
					Stock levels and movements from the stock ledger.
				</p>
			</div>
			<Select
				v-model="warehouse"
				:options="warehouseOptions"
				placeholder="All"
				class="pv-select min-w-56"
				showClear
				filter
				filterPlaceholder="Search warehouse..."
			/>
		</div>

		<TabButtons v-model="tab" :buttons="tabs" />

		<!-- kontrol bersama -->
		<div class="flex flex-wrap items-center gap-2">
			<Button variant="subtle" label="Refresh" icon-left="refresh-cw" @click="load()" />
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
			<Button
				:variant="showFilters ? 'solid' : 'subtle'"
				:label="activeFilterCount ? `Filters (${activeFilterCount})` : 'Open Filter'"
				icon-left="filter"
				@click="showFilters = !showFilters"
			/>
		</div>

		<!-- panel filter -->
		<div
			v-if="showFilters"
			class="grid gap-3 rounded-lg border border-outline-gray-1 bg-surface-modal p-3 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-end"
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
		<div
			v-if="tab === 'cards'"
			class="overflow-hidden rounded-lg border border-outline-gray-1 bg-surface-modal transition-opacity"
			:class="{ 'opacity-50': loading }"
		>
			<DataTable
				:value="rows"
				dataKey="name"
				lazy
				paginator
				:first="first"
				:rows="pageLen"
				:totalRecords="total"
				:rowsPerPageOptions="[20, 50, 100]"
				paginatorTemplate="CurrentPageReport FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown"
				currentPageReportTemplate="Showing {first} to {last} of {totalRecords} results"
				class="pv-table"
				@page="onPage"
			>
				<template #empty>
					<div class="flex flex-col items-center gap-2 px-6 py-14 text-center">
						<FeatherIcon name="layers" class="h-8 w-8 text-ink-gray-3" />
						<p class="text-sm text-ink-gray-4">
							No stock transactions in this period. Try a different time range or clear the filters.
						</p>
					</div>
				</template>

				<Column header="SKU">
					<template #body="{ data }">
						<span class="whitespace-nowrap text-ink-gray-6">{{ data.item_code }}</span>
					</template>
				</Column>
				<Column header="Name">
					<template #body="{ data }">
						<span class="whitespace-nowrap text-ink-gray-8">{{ data.item_name }}</span>
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
						</div>
					</template>
				</Column>
				<Column header="Stock Before">
					<template #body="{ data }">
						<div class="whitespace-nowrap tabular-nums" :class="data.qty_before < 0 ? 'text-red-600' : 'text-ink-gray-8'">
							{{ fmtQty(data.qty_before) }}
							<div class="text-xs text-ink-gray-4">{{ data.uom }}</div>
						</div>
					</template>
				</Column>
				<Column header="Balance Before">
					<template #body="{ data }">
						<span class="whitespace-nowrap tabular-nums text-ink-gray-7">{{ fmtRp(data.value_before) }}</span>
					</template>
				</Column>
				<Column header="In">
					<template #body="{ data }">
						<span v-if="data.qty_in != null" class="whitespace-nowrap tabular-nums text-green-700 dark:text-green-400">
							{{ fmtQty(data.qty_in) }}
						</span>
						<span v-else class="text-ink-gray-4">-</span>
					</template>
				</Column>
				<Column header="Out">
					<template #body="{ data }">
						<span v-if="data.qty_out != null" class="whitespace-nowrap tabular-nums text-red-600 dark:text-red-400">
							{{ fmtQty(data.qty_out) }}
						</span>
						<span v-else class="text-ink-gray-4">-</span>
					</template>
				</Column>
				<Column header="Stock After">
					<template #body="{ data }">
						<div class="whitespace-nowrap tabular-nums font-medium" :class="data.qty_after < 0 ? 'text-red-600' : 'text-ink-gray-9'">
							{{ fmtQty(data.qty_after) }}
							<div class="text-xs font-normal text-ink-gray-4">{{ data.uom }}</div>
						</div>
					</template>
				</Column>
				<Column header="Balance After">
					<template #body="{ data }">
						<span class="whitespace-nowrap tabular-nums text-ink-gray-8">{{ fmtRp(data.value_after) }}</span>
					</template>
				</Column>
			</DataTable>
		</div>
	</div>
</template>
