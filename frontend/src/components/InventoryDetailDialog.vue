<script setup>
// Modal detail Inventory Movements (W40-3, redesign W41): satu item+gudang
// dalam periode aktif. Ringkasan dari baris tabel induk (tanpa fetch ulang);
// Stock Cards lazy per halaman (endpoint stock_cards + item_code persis);
// Inventory Information dimuat saat accordion pertama kali dibuka.
// Dialog/DataTable/Tooltip tetap PrimeVue; chrome (header/accordion/tombol)
// native gudang.css + ikon lucide. Tanpa Tailwind — styling via gudang.css +
// <style> lokal ber-prefix .inv- (skin .pv-table/.pv-select/.inv-dialog
// didefinisikan non-scoped di InventoryPage.vue).
import { computed, ref, watch } from 'vue'
import Dialog from 'primevue/dialog'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Tooltip from 'primevue/tooltip'
import dayjs from 'dayjs'
import { fetchStockCards, fetchInventoryInfo, downloadExport } from '@/data/inventory'
import { fmtQty, fmtRp, fmtDate } from '@/lib/format'
import { toast } from '@/lib/toast'

import {
	Maximize2 as MaximizeIcon,
	Minimize2 as MinimizeIcon,
	X as XIcon,
	ChevronDown as ChevronDownIcon,
	ChevronUp as ChevronUpIcon,
	Calendar as CalendarIcon,
	Clock as ClockIcon,
	Download as DownloadIcon,
	FileSpreadsheet as FileSpreadsheetIcon,
	FileText as FileTextIcon,
	LogIn as LogInIcon,
	LogOut as LogOutIcon,
	Repeat as RepeatIcon,
	Truck as TruckIcon,
	Send as SendIcon,
	ShoppingCart as ShoppingCartIcon,
	ClipboardCheck as ClipboardCheckIcon,
	File as FileIcon,
} from 'lucide-vue-next'

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
const exportOpen = ref(false)

const dateLabel = computed(() => {
	const f = (d) => dayjs(d).format('ddd, D MMM YYYY')
	const { from_date, to_date } = props.period
	return `${f(from_date)} 00:00 ~ ${f(to_date)} 23:59`
})

const SUMMARY = [
	{ key: 'begin', label: 'Beginning', icon: null },
	{ key: 'in', label: 'In', icon: LogInIcon },
	{ key: 'out', label: 'Out', icon: LogOutIcon },
	{ key: 'end', label: 'Ending', icon: null },
]

const VOUCHER_ICON = {
	'Stock Entry': RepeatIcon,
	'Purchase Receipt': TruckIcon,
	'Purchase Invoice': FileTextIcon,
	'Delivery Note': SendIcon,
	'Sales Invoice': ShoppingCartIcon,
	'POS Invoice': ShoppingCartIcon,
	'Stock Reconciliation': ClipboardCheckIcon,
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
	exportOpen.value = false
	exporting.value = true
	try {
		await downloadExport({ kind: 'cards', file_format, ...pair() })
	} catch (e) {
		toast.error(e.message)
	} finally {
		exporting.value = false
	}
}

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
			<div v-if="row" class="inv-modal-body">
				<!-- header -->
				<div class="inv-modal-head">
					<div class="inv-modal-id">
						<div class="inv-modal-title">
							<span class="inv-modal-code">{{ row.item_code }}</span>
							<span class="inv-modal-name">{{ row.item_name }}</span>
							<span class="inv-modal-uom">/ {{ row.uom }}</span>
						</div>
						<div class="inv-modal-wh">at {{ row.warehouse }}</div>
						<div class="inv-modal-date">
							Date: <span class="inv-modal-period">{{ dateLabel }}</span>
						</div>
					</div>
					<div class="inv-modal-tools">
						<button type="button" class="btn" @click="maximized = !maximized">
							<component :is="maximized ? MinimizeIcon : MaximizeIcon" :size="14" :stroke-width="2" />
							{{ maximized ? 'Restore' : 'Maximize' }}
						</button>
						<button type="button" class="btn" @click="closeCallback">
							<XIcon :size="14" :stroke-width="2" /> Close
						</button>
					</div>
				</div>

				<div class="inv-modal-scroll">
					<!-- Inventory Information -->
					<section class="inv-info-box">
						<button type="button" class="inv-acc inv-acc-boxed" @click="toggleInfo">
							Inventory Information
							<component :is="open.info ? ChevronUpIcon : ChevronDownIcon" :size="16" :stroke-width="2" />
						</button>
						<div v-if="open.info" class="inv-info-body">
							<p v-if="!info" class="inv-muted">Loading...</p>
							<p v-else-if="!info.item_name" class="inv-muted">No bin found for this warehouse.</p>
							<dl v-else class="inv-info-grid">
								<div><dt>Item Group</dt><dd>{{ info.item_group }}</dd></div>
								<div><dt>Company</dt><dd>{{ info.company }}</dd></div>
								<div>
									<dt>Inventory UOM</dt>
									<dd>
										{{ info.uom }}
										<span v-if="info.factor !== 1" class="inv-faint">(1 = {{ fmtQty(info.factor, 4) }} {{ info.stock_uom }})</span>
									</dd>
								</div>
								<div><dt>Current Stock</dt><dd class="inv-num">{{ fmtQty(info.actual_qty) }} {{ info.uom }}</dd></div>
								<div><dt>Reserved</dt><dd class="inv-num">{{ fmtQty(info.reserved_qty) }} {{ info.uom }}</dd></div>
								<div><dt>Projected</dt><dd class="inv-num">{{ fmtQty(info.projected_qty) }} {{ info.uom }}</dd></div>
								<div><dt>Valuation Rate</dt><dd class="inv-num">{{ fmtRp(info.valuation_rate) }} / {{ info.uom }}</dd></div>
								<div><dt>Stock Value</dt><dd class="inv-num">{{ fmtRp(info.stock_value) }}</dd></div>
								<div v-if="info.description && info.description !== info.item_name" class="inv-info-desc">
									<dt>Description</dt>
									<dd>{{ info.description.replace(/<[^>]+>/g, ' ') }}</dd>
								</div>
							</dl>
						</div>
					</section>

					<!-- Movement Summary -->
					<section>
						<button type="button" class="inv-acc" @click="open.summary = !open.summary">
							Movement Summary
							<component :is="open.summary ? ChevronUpIcon : ChevronDownIcon" :size="16" :stroke-width="2" />
						</button>
						<div v-if="open.summary" class="inv-summary-grid">
							<div
								v-for="s in SUMMARY"
								:key="s.key"
								class="inv-sum-card"
								:class="{ 'inv-sum-neg': s.key === 'end' && (row.end_qty < 0 || row.end_value < 0) }"
							>
								<div class="inv-sum-main">
									<div class="inv-sum-label">
										<component :is="s.icon" v-if="s.icon" :size="15" :stroke-width="2" />
										{{ s.label }}
									</div>
									<div class="inv-sum-qty">
										{{ fmtQty(row[s.key + '_qty']) }}
										<span class="inv-sum-uom">{{ row.uom }}</span>
									</div>
								</div>
								<div class="inv-sum-val">{{ fmtRp(row[s.key + '_value']) }}</div>
							</div>
						</div>
					</section>

					<!-- Stock Cards -->
					<section>
						<button type="button" class="inv-acc" @click="open.cards = !open.cards">
							Stock Cards
							<component :is="open.cards ? ChevronUpIcon : ChevronDownIcon" :size="16" :stroke-width="2" />
						</button>
						<div v-if="open.cards" class="inv-cards-wrap">
							<div v-if="can.export" class="inv-cards-tools">
								<div class="filterwrap">
									<button type="button" class="btn filterbtn" :disabled="exporting" @click="exportOpen = !exportOpen">
										<DownloadIcon :size="14" :stroke-width="2" />
										<span>Export Stock Cards</span>
									</button>
									<div v-if="exportOpen" class="popoverlay" @click="exportOpen = false"></div>
									<Transition name="pop">
										<div v-if="exportOpen" class="filterpanel pop-right inv-exportpanel">
											<button type="button" class="btn" @click="exportAs('xlsx')">
												<FileSpreadsheetIcon :size="14" :stroke-width="2" /> Excel (.xlsx)
											</button>
											<button type="button" class="btn" @click="exportAs('csv')">
												<FileTextIcon :size="14" :stroke-width="2" /> CSV (.csv)
											</button>
										</div>
									</Transition>
								</div>
							</div>
							<div class="inv-cards-table" :class="{ dim: cards.loading }">
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
										<p class="inv-cards-empty">
											{{ cards.loading ? 'Loading...' : 'No stock transactions in this period.' }}
										</p>
									</template>
									<Column header="Date">
										<template #body="{ data }">
											<div class="inv-nw inv-stamp">
												<div class="inv-stamp-row">
													<CalendarIcon :size="13" :stroke-width="2" />{{ shortDate(data.posting_datetime) }}
												</div>
												<div class="inv-stamp-row">
													<ClockIcon :size="13" :stroke-width="2" />{{ time(data.posting_datetime) }}
												</div>
											</div>
										</template>
									</Column>
									<Column header="Reference">
										<template #body="{ data }">
											<div class="inv-ref">
												<span class="inv-ref-ico">
													<component :is="VOUCHER_ICON[data.voucher_type] || FileIcon" :size="15" :stroke-width="2" />
												</span>
												<div class="inv-ref-body">
													<div class="inv-ink">{{ data.voucher_type }}</div>
													<a :href="desk(data.voucher_type, data.voucher_no)" target="_blank" class="inv-link">{{ data.voucher_no }}</a>
													<div v-if="data.counterparty" class="inv-xs inv-muted">
														<span class="inv-med">{{ data.counterparty.dir === 'to' ? 'To' : 'From' }}:</span>
														{{ [data.counterparty.warehouse, data.counterparty.party, data.counterparty.company].filter(Boolean).join(' · ') }}
													</div>
													<div v-if="data.remarks" class="inv-remarks">{{ data.remarks }}</div>
												</div>
											</div>
										</template>
									</Column>
									<Column header="Beginning" headerClass="num" bodyClass="num">
										<template #body="{ data }">
											<div class="inv-num" :class="data.qty_before < 0 ? 'inv-bad' : 'inv-ink'">
												{{ fmtQty(data.qty_before) }} <span class="inv-xs inv-faint">{{ data.uom }}</span>
												<div class="inv-xs inv-muted">{{ fmtRp(data.value_before) }}</div>
											</div>
										</template>
									</Column>
									<Column header="In" headerClass="num" bodyClass="num">
										<template #body="{ data }">
											<div
												v-if="data.qty_in != null"
												v-tooltip.top="unitPrice(data, data.qty_in)"
												class="inv-num inv-help inv-ok"
											>
												{{ fmtQty(data.qty_in) }} <span class="inv-xs inv-faint">{{ data.uom }}</span>
												<div class="inv-xs inv-muted">{{ fmtRp(data.value_change) }}</div>
											</div>
											<span v-else class="inv-faint">-</span>
										</template>
									</Column>
									<Column header="Out" headerClass="num" bodyClass="num">
										<template #body="{ data }">
											<div
												v-if="data.qty_out != null"
												v-tooltip.top="unitPrice(data, data.qty_out)"
												class="inv-num inv-help inv-bad"
											>
												{{ fmtQty(data.qty_out) }} <span class="inv-xs inv-faint">{{ data.uom }}</span>
												<div class="inv-xs inv-muted">{{ fmtRp(-data.value_change) }}</div>
											</div>
											<span v-else class="inv-faint">-</span>
										</template>
									</Column>
									<Column header="Ending" headerClass="num" bodyClass="num">
										<template #body="{ data }">
											<div class="inv-num inv-med" :class="data.qty_after < 0 ? 'inv-bad' : 'inv-ink'">
												{{ fmtQty(data.qty_after) }} <span class="inv-xs inv-faint">{{ data.uom }}</span>
												<div class="inv-xs inv-muted">{{ fmtRp(data.value_after) }}</div>
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

<style>
/* chrome modal yang butuh class gudang.css namun tak lewat InventoryPage:
   popover export + panel kanan (skin .pv-table/.pv-select/.inv-dialog sendiri
   sudah didefinisikan di InventoryPage.vue, non-scoped, berlaku di sini) */
.inv-dialog .popoverlay { position: fixed; inset: 0; z-index: 60; }
.inv-dialog .pop-enter-active { transition: opacity 0.18s ease, transform 0.18s cubic-bezier(0.32, 0.72, 0, 1); }
.inv-dialog .pop-leave-active { transition: opacity 0.12s ease; }
.inv-dialog .pop-enter-from { opacity: 0; transform: scale(0.96) translateY(-4px); }
.inv-dialog .pop-leave-to { opacity: 0; }
.inv-dialog .inv-exportpanel { width: 220px; }
.inv-dialog .inv-exportpanel .btn { justify-content: flex-start; width: 100%; }

/* -- kerangka modal -- */
.inv-modal-body { display: flex; flex-direction: column; max-height: 100%; min-height: 0; }
.inv-modal-head {
	display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between;
	gap: 16px; padding: 20px 24px; border-bottom: 1px solid var(--line);
}
.inv-modal-id { min-width: 0; }
.inv-modal-title { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.inv-modal-code {
	padding: 2px 8px; border-radius: 6px; background: var(--grey-bg, rgba(0, 0, 0, 0.05));
	font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 14px; color: var(--muted);
}
.inv-modal-name { font-size: 20px; font-weight: 600; color: var(--ink); }
.inv-modal-uom { font-size: 20px; color: var(--faint); }
.inv-modal-wh { margin-top: 4px; font-size: 16px; font-weight: 600; color: var(--bad-ink); }
.inv-modal-date { margin-top: 4px; font-size: 13px; color: var(--muted); }
.inv-modal-period { font-style: italic; color: var(--muted); }
.inv-modal-tools { display: flex; flex: none; gap: 8px; }
.inv-modal-tools .btn { gap: 6px; display: inline-flex; align-items: center; }
.inv-modal-scroll { flex: 1; min-height: 0; overflow-y: auto; padding: 20px 24px; }

/* -- accordion (Inventory Information / Movement Summary / Stock Cards) -- */
.inv-acc {
	display: flex; width: 100%; align-items: center; justify-content: space-between;
	border: 0; background: none; cursor: pointer; font: inherit; text-align: left;
	padding: 0 0 8px; margin-bottom: 0; font-size: 16px; font-weight: 600; color: var(--ink);
	border-bottom: 1px solid var(--line);
}
.inv-acc-boxed { padding: 12px 16px; border-bottom: 0; }
.inv-info-box { border-radius: 10px; background: var(--grey-bg, rgba(0, 0, 0, 0.04)); }
.inv-acc-boxed { border-bottom: 0; }
.inv-info-box .inv-info-body { border-top: 1px solid var(--line); padding: 12px 16px; }

/* -- Inventory Information -- */
.inv-info-body > p { margin: 0; font-size: 13px; color: var(--muted); }
.inv-info-grid {
	display: grid; gap: 12px 24px; margin: 0; font-size: 13px;
	grid-template-columns: repeat(2, 1fr);
}
@media (min-width: 640px) { .inv-info-grid { grid-template-columns: repeat(3, 1fr); } }
.inv-info-grid dt { font-size: 12px; color: var(--muted); }
.inv-info-grid dd { margin: 0; color: var(--ink); }
.inv-info-desc { grid-column: 1 / -1; }

/* -- Movement Summary: 4 kartu -- */
.inv-summary-grid {
	display: grid; gap: 12px; margin-top: 16px; grid-template-columns: repeat(2, 1fr);
}
@media (min-width: 1024px) { .inv-summary-grid { grid-template-columns: repeat(4, 1fr); } }
.inv-sum-card {
	overflow: hidden; text-align: center; border: 1px solid var(--line);
	border-radius: 10px; color: var(--ink); background: var(--surface);
}
.inv-sum-card.inv-sum-neg { border-color: transparent; background: var(--bad-ink, #9c4736); color: #fff; }
.inv-sum-main { padding: 16px 12px 12px; }
.inv-sum-label {
	display: flex; align-items: center; justify-content: center; gap: 6px;
	font-size: 13px; font-weight: 600;
}
.inv-sum-qty { margin-top: 8px; font-size: 24px; font-variant-numeric: tabular-nums; }
.inv-sum-uom { font-size: 16px; opacity: 0.6; }
.inv-sum-val {
	padding: 8px 12px; font-size: 13px; font-variant-numeric: tabular-nums; opacity: 0.8;
	border-top: 1px solid rgba(127, 127, 127, 0.25);
}

/* -- Stock Cards di modal -- */
.inv-cards-wrap { margin-top: 12px; }
.inv-cards-tools { display: flex; justify-content: flex-end; margin-bottom: 12px; }
.inv-cards-table {
	overflow: hidden; border: 1px solid var(--line); border-radius: 10px;
	transition: opacity 0.15s ease;
}
.inv-cards-table.dim { opacity: 0.5; }
.inv-cards-empty { margin: 0; padding: 40px 24px; text-align: center; font-size: 13px; color: var(--faint); }
.inv-stamp { color: var(--muted); }
.inv-stamp-row { display: flex; align-items: center; gap: 6px; }
.inv-stamp-row svg { color: var(--faint); }
.inv-ref { display: flex; align-items: flex-start; gap: 12px; }
.inv-ref-ico {
	display: flex; flex: none; width: 36px; height: 36px; margin-top: 2px;
	align-items: center; justify-content: center; border-radius: 50%;
	background: var(--grey-bg, rgba(0, 0, 0, 0.05)); color: var(--muted);
}
.inv-ref-body { min-width: 0; }
.inv-remarks {
	max-width: 20rem; margin-top: 6px; padding: 6px 10px; border-radius: 8px;
	background: var(--warn-bg, #f7ecd2); font-size: 12px; font-style: italic; color: var(--warn-ink, #7a5a14);
}
.inv-help { cursor: help; }
</style>
