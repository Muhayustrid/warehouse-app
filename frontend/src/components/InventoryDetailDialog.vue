<script setup>
// Modal detail Inventory Movements (W40-3): satu item+gudang dalam periode
// aktif. Ringkasan dari baris tabel induk (tanpa fetch ulang); Stock Cards
// lazy per halaman (endpoint stock_cards + item_code persis); Inventory
// Information dimuat saat accordion pertama kali dibuka.
import { computed, ref, watch } from 'vue'
import Dialog from 'primevue/dialog'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Tooltip from 'primevue/tooltip'
import { Button } from '@frappe-ui/components/Button'
import FeatherIcon from '@frappe-ui/components/FeatherIcon.vue'
import { Dropdown } from '@frappe-ui/components/Dropdown'
import { dayjs } from '@frappe-ui/utils/dayjs'
import { fetchStockCards, fetchInventoryInfo, downloadExport } from '@/data/inventory'
import { fmtQty, fmtRp, fmtDate } from '@/lib/format'
import { toast } from '@/lib/toast'

const vTooltip = Tooltip

const props = defineProps({
	row: { type: Object, default: null }, // baris Movements
	period: { type: Object, required: true }, // { from_date, to_date }
	can: { type: Object, default: () => ({}) }, // { export }
})
const show = defineModel({ type: Boolean, default: false })

const maximized = ref(false)
const open = ref({ info: false, summary: true, cards: true })
const info = ref(null)
const cards = ref({ rows: [], total: 0, first: 0, pageLen: 20, loading: false })

const dateLabel = computed(() => {
	const f = (d) => dayjs(d).format('ddd, D MMM YYYY')
	const { from_date, to_date } = props.period
	return `${f(from_date)} 00:00 ~ ${f(to_date)} 23:59`
})

const SUMMARY = [
	{ key: 'begin', label: 'Beginning', icon: null },
	{ key: 'in', label: 'In', icon: 'log-in' },
	{ key: 'out', label: 'Out', icon: 'log-out' },
	{ key: 'end', label: 'Ending', icon: null },
]

const VOUCHER_ICON = {
	'Stock Entry': 'repeat',
	'Purchase Receipt': 'truck',
	'Purchase Invoice': 'file-text',
	'Delivery Note': 'send',
	'Sales Invoice': 'shopping-cart',
	'POS Invoice': 'shopping-cart',
	'Stock Reconciliation': 'check-square',
}

let seq = 0
async function loadCards() {
	const mine = ++seq
	cards.value.loading = true
	try {
		const res = await fetchStockCards({
			...props.period,
			item_code: props.row.item_code,
			warehouse: props.row.warehouse,
			page: Math.floor(cards.value.first / cards.value.pageLen) + 1,
			page_len: cards.value.pageLen,
		})
		if (mine !== seq) return
		cards.value.rows = res?.rows || []
		cards.value.total = res?.total || 0
	} catch (e) {
		if (mine === seq) toast.error(e.message)
	} finally {
		if (mine === seq) cards.value.loading = false
	}
}

function onPage(e) {
	cards.value.first = e.first
	cards.value.pageLen = e.rows
	loadCards()
}

async function toggleInfo() {
	open.value.info = !open.value.info
	if (open.value.info && !info.value) {
		try {
			info.value = (await fetchInventoryInfo(props.row.item_code, props.row.warehouse)) || {}
		} catch (e) {
			toast.error(e.message)
		}
	}
}

watch(show, (v) => {
	if (!v || !props.row) return
	maximized.value = false
	open.value = { info: false, summary: true, cards: true }
	info.value = null
	cards.value = { rows: [], total: 0, first: 0, pageLen: 20, loading: false }
	loadCards()
})

const pair = () => ({ ...props.period, item_code: props.row.item_code, warehouse: props.row.warehouse })

const exporting = ref(false)
async function exportAs(file_format) {
	exporting.value = true
	try {
		await downloadExport({ kind: 'cards', file_format, ...pair() })
	} catch (e) {
		toast.error(e.message)
	} finally {
		exporting.value = false
	}
}
const exportOptions = [
	{ label: 'Excel (.xlsx)', icon: 'file', onClick: () => exportAs('xlsx') },
	{ label: 'CSV (.csv)', icon: 'file-text', onClick: () => exportAs('csv') },
]

const time = (dt) => String(dt || '').slice(11, 16)
const shortDate = (dt) => fmtDate(dt).slice(0, 6)
const unitPrice = (r, qty) =>
	qty ? `${fmtRp(Math.abs(r.value_change) / qty)} / ${r.uom}` : null
const desk = (doctype, name) =>
	`/app/${doctype.toLowerCase().replace(/ /g, '-')}/${encodeURIComponent(name)}`
</script>

<template>
	<Dialog
		v-model:visible="show"
		modal
		dismissableMask
		:style="maximized ? { width: '100vw', height: '100vh' } : { width: 'min(1100px, 95vw)' }"
		class="inv-dialog"
		:class="{ 'inv-dialog-max': maximized }"
	>
		<template #container="{ closeCallback }">
			<div v-if="row" class="flex max-h-full min-h-0 flex-col">
				<!-- header -->
				<div class="flex flex-wrap items-start justify-between gap-4 border-b border-outline-gray-1 px-6 py-5">
					<div class="min-w-0">
						<div class="flex flex-wrap items-center gap-2">
							<span class="rounded bg-surface-gray-2 px-2 py-0.5 font-mono text-sm text-ink-gray-7">{{ row.item_code }}</span>
							<span class="text-xl font-semibold text-ink-gray-9">{{ row.item_name }}</span>
							<span class="text-xl text-ink-gray-4">/ {{ row.uom }}</span>
						</div>
						<div class="mt-1 text-base font-semibold text-red-700 dark:text-red-400">at {{ row.warehouse }}</div>
						<div class="mt-1 text-sm text-ink-gray-5">
							Date: <span class="italic text-ink-gray-7">{{ dateLabel }}</span>
						</div>
					</div>
					<div class="flex shrink-0 gap-2">
						<Button
							variant="subtle"
							:label="maximized ? 'Restore' : 'Maximize'"
							:icon-right="maximized ? 'minimize-2' : 'maximize-2'"
							@click="maximized = !maximized"
						/>
						<Button variant="subtle" label="Close" icon-right="x" @click="closeCallback" />
					</div>
				</div>

				<div class="min-h-0 flex-1 space-y-5 overflow-y-auto px-6 py-5">
					<!-- Inventory Information -->
					<section class="rounded-lg bg-surface-gray-2">
						<button
							class="flex w-full items-center justify-between px-4 py-3 text-left text-base font-semibold text-ink-gray-8"
							@click="toggleInfo"
						>
							Inventory Information
							<FeatherIcon :name="open.info ? 'chevron-up' : 'chevron-down'" class="h-4 w-4" />
						</button>
						<div v-if="open.info" class="border-t border-outline-gray-2 px-4 py-3">
							<p v-if="!info" class="text-sm text-ink-gray-5">Loading...</p>
							<p v-else-if="!info.item_name" class="text-sm text-ink-gray-5">No bin found for this warehouse.</p>
							<dl v-else class="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
								<div><dt class="text-xs text-ink-gray-5">Item Group</dt><dd class="text-ink-gray-8">{{ info.item_group }}</dd></div>
								<div><dt class="text-xs text-ink-gray-5">Company</dt><dd class="text-ink-gray-8">{{ info.company }}</dd></div>
								<div>
									<dt class="text-xs text-ink-gray-5">Inventory UOM</dt>
									<dd class="text-ink-gray-8">
										{{ info.uom }}
										<span v-if="info.factor !== 1" class="text-ink-gray-5">(1 = {{ fmtQty(info.factor, 4) }} {{ info.stock_uom }})</span>
									</dd>
								</div>
								<div><dt class="text-xs text-ink-gray-5">Current Stock</dt><dd class="tabular-nums text-ink-gray-8">{{ fmtQty(info.actual_qty) }} {{ info.uom }}</dd></div>
								<div><dt class="text-xs text-ink-gray-5">Reserved</dt><dd class="tabular-nums text-ink-gray-8">{{ fmtQty(info.reserved_qty) }} {{ info.uom }}</dd></div>
								<div><dt class="text-xs text-ink-gray-5">Projected</dt><dd class="tabular-nums text-ink-gray-8">{{ fmtQty(info.projected_qty) }} {{ info.uom }}</dd></div>
								<div><dt class="text-xs text-ink-gray-5">Valuation Rate</dt><dd class="tabular-nums text-ink-gray-8">{{ fmtRp(info.valuation_rate) }} / {{ info.uom }}</dd></div>
								<div><dt class="text-xs text-ink-gray-5">Stock Value</dt><dd class="tabular-nums text-ink-gray-8">{{ fmtRp(info.stock_value) }}</dd></div>
								<div v-if="info.description && info.description !== info.item_name" class="sm:col-span-3">
									<dt class="text-xs text-ink-gray-5">Description</dt>
									<dd class="text-ink-gray-8">{{ info.description.replace(/<[^>]+>/g, ' ') }}</dd>
								</div>
							</dl>
						</div>
					</section>

					<!-- Movement Summary -->
					<section>
						<button
							class="flex w-full items-center justify-between border-b border-outline-gray-1 pb-2 text-left text-base font-semibold text-ink-gray-8"
							@click="open.summary = !open.summary"
						>
							Movement Summary
							<FeatherIcon :name="open.summary ? 'chevron-up' : 'chevron-down'" class="h-4 w-4" />
						</button>
						<div v-if="open.summary" class="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
							<div
								v-for="s in SUMMARY"
								:key="s.key"
								class="overflow-hidden rounded-lg border text-center"
								:class="
									s.key === 'end' && (row.end_qty < 0 || row.end_value < 0)
										? 'border-red-800 bg-red-800 text-white'
										: 'border-outline-gray-2 text-ink-gray-9'
								"
							>
								<div class="px-3 pb-3 pt-4">
									<div class="flex items-center justify-center gap-1.5 text-sm font-semibold">
										<FeatherIcon v-if="s.icon" :name="s.icon" class="h-4 w-4" />
										{{ s.label }}
									</div>
									<div class="mt-2 text-2xl tabular-nums">
										{{ fmtQty(row[s.key + '_qty']) }}
										<span class="text-base opacity-60">{{ row.uom }}</span>
									</div>
								</div>
								<div class="border-t border-current/10 px-3 py-2 text-sm tabular-nums opacity-80">
									{{ fmtRp(row[s.key + '_value']) }}
								</div>
							</div>
						</div>
					</section>

					<!-- Stock Cards -->
					<section>
						<button
							class="flex w-full items-center justify-between border-b border-outline-gray-1 pb-2 text-left text-base font-semibold text-ink-gray-8"
							@click="open.cards = !open.cards"
						>
							Stock Cards
							<FeatherIcon :name="open.cards ? 'chevron-up' : 'chevron-down'" class="h-4 w-4" />
						</button>
						<div v-if="open.cards" class="mt-3 space-y-3">
							<div class="flex justify-end gap-2">
								<Dropdown v-if="can.export" :options="exportOptions" align="end">
									<Button variant="subtle" label="Export Stock Cards" icon-left="share" :loading="exporting" />
								</Dropdown>
							</div>
							<div
								class="overflow-hidden rounded-lg border border-outline-gray-1 transition-opacity"
								:class="{ 'opacity-50': cards.loading }"
							>
								<DataTable
									:value="cards.rows"
									dataKey="name"
									lazy
									paginator
									:first="cards.first"
									:rows="cards.pageLen"
									:totalRecords="cards.total"
									:rowsPerPageOptions="[20, 50, 100]"
									paginatorTemplate="CurrentPageReport FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown"
									currentPageReportTemplate="Showing {first} to {last} of {totalRecords} results"
									class="pv-table pv-table-modal"
									@page="onPage"
								>
									<template #empty>
										<p class="px-6 py-10 text-center text-sm text-ink-gray-4">
											{{ cards.loading ? 'Loading...' : 'No stock transactions in this period.' }}
										</p>
									</template>
									<Column header="Date">
										<template #body="{ data }">
											<div class="space-y-1 whitespace-nowrap text-ink-gray-7">
												<div class="flex items-center gap-1.5">
													<FeatherIcon name="calendar" class="h-3.5 w-3.5 text-ink-gray-5" />{{ shortDate(data.posting_datetime) }}
												</div>
												<div class="flex items-center gap-1.5">
													<FeatherIcon name="clock" class="h-3.5 w-3.5 text-ink-gray-5" />{{ time(data.posting_datetime) }}
												</div>
											</div>
										</template>
									</Column>
									<Column header="Reference">
										<template #body="{ data }">
											<div class="flex items-start gap-3">
												<span class="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-surface-gray-2 text-ink-gray-6">
													<FeatherIcon :name="VOUCHER_ICON[data.voucher_type] || 'file'" class="h-4 w-4" />
												</span>
												<div class="min-w-0">
													<div class="text-ink-gray-8">{{ data.voucher_type }}</div>
													<a
														:href="desk(data.voucher_type, data.voucher_no)"
														target="_blank"
														class="font-mono text-xs text-ink-gray-5 underline decoration-transparent underline-offset-2 hover:decoration-current"
														>{{ data.voucher_no }}</a
													>
													<div v-if="data.counterparty" class="mt-1 text-xs text-ink-gray-6">
														<span class="font-medium">{{ data.counterparty.dir === 'to' ? 'To' : 'From' }}:</span>
														{{ [data.counterparty.warehouse, data.counterparty.party, data.counterparty.company].filter(Boolean).join(' · ') }}
													</div>
													<div
														v-if="data.remarks"
														class="mt-1.5 max-w-xs rounded bg-yellow-50 px-2.5 py-1.5 text-xs italic text-ink-gray-7 dark:bg-yellow-900/30"
													>
														{{ data.remarks }}
													</div>
												</div>
											</div>
										</template>
									</Column>
									<Column header="Beginning" headerClass="num" bodyClass="num">
										<template #body="{ data }">
											<div class="whitespace-nowrap tabular-nums" :class="data.qty_before < 0 ? 'text-red-600' : 'text-ink-gray-8'">
												{{ fmtQty(data.qty_before) }} <span class="text-xs text-ink-gray-4">{{ data.uom }}</span>
												<div class="text-xs text-ink-gray-5">{{ fmtRp(data.value_before) }}</div>
											</div>
										</template>
									</Column>
									<Column header="In" headerClass="num" bodyClass="num">
										<template #body="{ data }">
											<div
												v-if="data.qty_in != null"
												v-tooltip.top="unitPrice(data, data.qty_in)"
												class="cursor-help whitespace-nowrap tabular-nums text-green-700 dark:text-green-400"
											>
												{{ fmtQty(data.qty_in) }} <span class="text-xs text-ink-gray-4">{{ data.uom }}</span>
												<div class="text-xs text-ink-gray-5">{{ fmtRp(data.value_change) }}</div>
											</div>
											<span v-else class="text-ink-gray-4">-</span>
										</template>
									</Column>
									<Column header="Out" headerClass="num" bodyClass="num">
										<template #body="{ data }">
											<div
												v-if="data.qty_out != null"
												v-tooltip.top="unitPrice(data, data.qty_out)"
												class="cursor-help whitespace-nowrap tabular-nums text-red-600 dark:text-red-400"
											>
												{{ fmtQty(data.qty_out) }} <span class="text-xs text-ink-gray-4">{{ data.uom }}</span>
												<div class="text-xs text-ink-gray-5">{{ fmtRp(-data.value_change) }}</div>
											</div>
											<span v-else class="text-ink-gray-4">-</span>
										</template>
									</Column>
									<Column header="Ending" headerClass="num" bodyClass="num">
										<template #body="{ data }">
											<div class="whitespace-nowrap font-medium tabular-nums" :class="data.qty_after < 0 ? 'text-red-600' : 'text-ink-gray-9'">
												{{ fmtQty(data.qty_after) }} <span class="text-xs font-normal text-ink-gray-4">{{ data.uom }}</span>
												<div class="text-xs font-normal text-ink-gray-5">{{ fmtRp(data.value_after) }}</div>
											</div>
										</template>
									</Column>
								</DataTable>
							</div>
						</div>
					</section>
				</div>
			</div>
		</template>
	</Dialog>
</template>
