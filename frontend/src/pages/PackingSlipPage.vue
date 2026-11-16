<script setup>
// Halaman Packing Slip per Sales Order: daftar semua Packing Slip, editor
// koli (Frozen kiri / Dry kanan, satu baris per koli), cetak A4 + label 60x40.
// Edit terkunci setelah Delivery Note disubmit.
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Printer, Save, Tag, X } from 'lucide-vue-next'
import PrintPreviewModal from '@/components/fulfillment/PrintPreviewModal.vue'
import {
	fetchPackingSlip,
	fetchPackingSlipLabelsHtml,
	fetchPackingSlipPrintHtml,
	fetchPackingSlips,
	savePackingSlip,
} from '@/data/fulfillment'

const route = useRoute()
const router = useRouter()

const company = ref(route.query.company || '')
const fromDate = ref(route.query.from_date || '')
const toDate = ref(route.query.to_date || route.query.from_date || '')
const slips = ref([])
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const notice = ref('')

const editing = ref(null) // editor payload

const printModalOpen = ref(false)
const printModalTitle = ref('')
const printModalItems = ref([])

onMounted(load)

async function load() {
	loading.value = true
	error.value = ''
	try {
		const res = await fetchPackingSlips(company.value, fromDate.value, toDate.value)
		company.value = res.company || company.value
		slips.value = res.slips || []
	} catch (e) {
		error.value = e.message || 'Gagal memuat daftar packing slip.'
	} finally {
		loading.value = false
	}
}

async function openSlip(row) {
	error.value = ''
	notice.value = ''
	try {
		editing.value = await fetchPackingSlip(row.name)
	} catch (e) {
		error.value = e.message || 'Gagal membuka packing slip.'
	}
}

function closeSlip() {
	editing.value = null
	load()
}

const frozenLines = computed(() => (editing.value?.lines || []).filter((l) => l.category === 'frozen'))
const dryLines = computed(() => (editing.value?.lines || []).filter((l) => l.category === 'dry'))

const totals = computed(() => {
	const lines = editing.value?.lines || []
	const sum = (cat) =>
		lines
			.filter((l) => l.category === cat)
			.reduce(
				(acc, l) => ({
					colly: acc.colly + (Number(l.koli) || 1),
					weight: acc.weight + (Number(l.berat) || Number(l.estimated_weight) || 0),
				}),
				{ colly: 0, weight: 0 },
			)
	const dry = sum('dry')
	const frozen = sum('frozen')
	return {
		dryColly: dry.colly,
		dryWeight: Math.round(dry.weight * 100) / 100,
		frozenColly: frozen.colly,
		frozenWeight: Math.round(frozen.weight * 100) / 100,
	}
})

function nextKoliNo() {
	const nums = (editing.value?.lines || []).map((l) => Number(l.koli_no) || 1)
	return (nums.length ? Math.max(...nums) : 0) + 1
}

function addLine(category) {
	editing.value.lines.push({
		item_code: '',
		item_name: '',
		qty: 0,
		uom: '',
		koli_no: nextKoliNo(),
		koli: 1,
		berat: '',
		category,
	})
}

function removeLine(index) {
	editing.value.lines.splice(index, 1)
}

async function save() {
	if (saving.value || !editing.value?.editable) return
	saving.value = true
	error.value = ''
	try {
		await savePackingSlip(editing.value.name, editing.value.lines)
		notice.value = 'Packing slip tersimpan.'
	} catch (e) {
		error.value = e.message || 'Gagal menyimpan packing slip.'
	} finally {
		saving.value = false
	}
}

async function printPaper() {
	try {
		const html = await fetchPackingSlipPrintHtml(editing.value.name)
		openPrint('Packing List', [{ label: 'Packing List', name: editing.value.name, html }])
	} catch (e) {
		error.value = e.message || 'Gagal membuat cetakan packing list.'
	}
}

async function printLabels() {
	try {
		const html = await fetchPackingSlipLabelsHtml(editing.value.name)
		openPrint('Label Koli', [{ label: 'Label Koli', name: editing.value.name, html }])
	} catch (e) {
		error.value = e.message || 'Gagal membuat label koli.'
	}
}

function openPrint(title, items) {
	printModalTitle.value = title
	printModalItems.value = items
	printModalOpen.value = true
}

function fmtQty(value) {
	const n = Number(value) || 0
	return Number.isInteger(n) ? String(n) : String(Math.round(n * 100) / 100)
}
</script>

<template>
	<div class="ps-page">
		<!-- ================= List ================= -->
		<template v-if="!editing">
			<div class="ps-toolbar">
				<div class="ps-filters">
					<input v-model="fromDate" class="input input-sm" type="date" aria-label="Dari tanggal" @change="load" />
					<input v-model="toDate" class="input input-sm" type="date" aria-label="Sampai tanggal" @change="load" />
				</div>
			</div>

			<p v-if="error" class="ps-error">{{ error }}</p>
			<p v-if="loading" class="ps-empty">Memuat…</p>
			<p v-else-if="!slips.length" class="ps-empty">Belum ada Packing Slip pada rentang tanggal ini.</p>

			<div v-else class="board-card">
				<div class="ps-thead">
					<span>NO. SO</span>
					<span>CUSTOMER</span>
					<span>TANGGAL KIRIM</span>
					<span>STATUS</span>
					<span>TERAKHIR DIUBAH</span>
					<span></span>
				</div>
				<div
					v-for="row in slips"
					:key="row.name"
					class="ps-trow"
					role="button"
					tabindex="0"
					@click="openSlip(row)"
					@keydown.enter="openSlip(row)"
				>
					<span class="mono"><strong>{{ row.sales_order }}</strong></span>
					<span>{{ row.customer_name }}</span>
					<span class="muted">{{ row.delivery_date }}</span>
					<span>
						<span class="badge" :class="row.editable ? 'b-edit' : 'b-ro'">{{ row.status }}</span>
					</span>
					<span class="muted">{{ row.modified }}</span>
					<span class="chev">›</span>
				</div>
			</div>
		</template>

		<!-- ================= Editor ================= -->
		<template v-else>
			<div class="ps-toolbar">
				<button type="button" class="btn" @click="closeSlip">
					<ArrowLeft :size="15" :stroke-width="2" />
					<span>Kembali</span>
				</button>
				<div class="ps-actions">
					<template v-if="editing.editable">
						<button type="button" class="btn btn-primary" :disabled="saving" @click="save">
							<Save :size="15" :stroke-width="2" />
							<span>Simpan</span>
						</button>
						<button type="button" class="btn" @click="printPaper">
							<Printer :size="15" :stroke-width="2" />
							<span>Cetak Packing List</span>
						</button>
						<button type="button" class="btn" @click="printLabels">
							<Tag :size="15" :stroke-width="2" />
							<span>Cetak Label</span>
						</button>
					</template>
					<template v-else>
						<span class="ps-ro-note">Read-only — Delivery Note sudah disubmit</span>
						<button type="button" class="btn" @click="printPaper">
							<Printer :size="15" :stroke-width="2" />
							<span>Cetak Packing List</span>
						</button>
						<button type="button" class="btn" @click="printLabels">
							<Tag :size="15" :stroke-width="2" />
							<span>Cetak Label</span>
						</button>
					</template>
				</div>
			</div>

			<p v-if="notice" class="ps-notice">{{ notice }}</p>
			<p v-if="error" class="ps-error">{{ error }}</p>

			<div class="ps-paper">
				<header class="ps-paper-head">
					<h1>PACKING LIST</h1>
					<div class="ps-to">
						<span class="ps-to-label">TO:</span>
						<strong>{{ editing.header.customer_name }}</strong>
					</div>
				</header>
				<div class="ps-meta">
					<span>PO No: <strong>{{ editing.header.po_no || '-' }}</strong></span>
					<span>Delivery date: <strong>{{ editing.header.delivery_date || '-' }}</strong></span>
					<span>No: <strong>{{ editing.name }}</strong></span>
				</div>

				<div class="ps-cols">
					<!-- FROZEN kiri -->
					<div class="ps-col">
						<div class="ps-colh">FROZEN</div>
						<table class="ps-table">
							<thead>
								<tr><th>Item</th><th class="num">Qty</th><th>Unit</th><th class="num">Koli</th><th class="num">Weight (Kg)</th><th v-if="editing.editable"></th></tr>
							</thead>
							<tbody>
								<tr v-for="(row, index) in frozenLines" :key="index">
									<td>{{ row.item_name || row.item_code || '-' }}</td>
									<td class="num"><input v-model.number="row.qty" class="input input-sm ps-num" type="number" min="0" :disabled="!editing.editable" /></td>
									<td>{{ row.uom }}</td>
									<td class="num">{{ row.koli_no }}</td>
									<td class="num">
										<input v-model="row.berat" class="input input-sm ps-num" type="text" :disabled="!editing.editable" />
									</td>
									<td v-if="editing.editable" class="num">
										<button type="button" class="ps-del" title="Hapus baris" @click="removeLine(editing.lines.indexOf(row))">
											<X :size="11" :stroke-width="2" />
										</button>
									</td>
								</tr>
								<tr v-if="!frozenLines.length"><td colspan="5" class="ps-none">—</td></tr>
							</tbody>
						</table>
						<button v-if="editing.editable" type="button" class="ps-add" @click="addLine('frozen')">+ Tambah Frozen</button>
					</div>

					<!-- DRY kanan -->
					<div class="ps-col">
						<div class="ps-colh">DRY</div>
						<table class="ps-table">
							<thead>
								<tr><th>Item</th><th class="num">Qty</th><th>Unit</th><th class="num">Koli</th><th class="num">Weight (Kg)</th><th v-if="editing.editable"></th></tr>
							</thead>
							<tbody>
								<tr v-for="(row, index) in dryLines" :key="index">
									<td>{{ row.item_name || row.item_code || '-' }}</td>
									<td class="num"><input v-model.number="row.qty" class="input input-sm ps-num" type="number" min="0" :disabled="!editing.editable" /></td>
									<td>{{ row.uom }}</td>
									<td class="num">{{ row.koli_no }}</td>
									<td class="num"><input v-model="row.berat" class="input input-sm ps-num" type="text" :disabled="!editing.editable" /></td>
									<td v-if="editing.editable" class="num">
										<button type="button" class="ps-del" title="Hapus baris" @click="removeLine(editing.lines.indexOf(row))">
											<X :size="11" :stroke-width="2" />
										</button>
									</td>
								</tr>
								<tr v-if="!dryLines.length"><td colspan="5" class="ps-none">—</td></tr>
								<tr class="ps-total">
									<td colspan="4">Total Dry (colly)</td>
									<td class="num">{{ totals.dryColly }}</td>
									<td v-if="editing.editable"></td>
								</tr>
								<tr class="ps-total">
									<td colspan="4">Net Weight Dry (kg)</td>
									<td class="num">{{ fmtQty(totals.dryWeight) }}</td>
									<td v-if="editing.editable"></td>
								</tr>
							</tbody>
						</table>
						<button v-if="editing.editable" type="button" class="ps-add" @click="addLine('dry')">+ Tambah Dry</button>
					</div>
				</div>
			</div>
		</template>

		<PrintPreviewModal :open="printModalOpen" :title="printModalTitle" :items="printModalItems" @close="printModalOpen = false" />
	</div>
</template>

<style scoped>
.ps-page { padding: 16px; }
.ps-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.ps-filters, .ps-actions { display: flex; gap: 8px; align-items: center; }
.ps-notice { color: #1a7f37; font-size: 13px; }
.ps-error { color: #c0392b; font-size: 13px; }
.ps-empty { color: #666; padding: 32px 0; text-align: center; }
.muted { color: #64748b; font-size: 12.5px; }
.chev { color: #94a3b8; text-align: right; }
.ps-thead, .ps-trow {
	display: grid;
	grid-template-columns: 170px minmax(180px, 1fr) 120px 110px 160px 32px;
	gap: 14px;
	padding: 11px 16px;
	align-items: center;
}
.ps-thead { border-bottom: 1px solid #e5e7eb; font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase; }
.ps-trow { border-bottom: 1px solid #f1f5f9; cursor: pointer; font-size: 13px; }
.ps-trow:hover { background: #f8fafc; }
.badge { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 4px; }
.b-edit { background: #dcfce7; color: #166534; }
.b-ro { background: #f1f5f9; color: #64748b; }
.ps-ro-note { font-size: 12px; color: #64748b; }

/* Paper */
.ps-paper { background: #fff; border: 1px solid #ddd; padding: 20px 24px; max-width: 1100px; margin: 0 auto; }
.ps-paper-head { background: #f7a600; color: #fff; padding: 10px 14px; display: flex; justify-content: space-between; align-items: center; }
.ps-paper-head h1 { font-size: 20px; letter-spacing: 0.08em; margin: 0; }
.ps-to-label { font-size: 12px; margin-right: 6px; }
.ps-meta { display: flex; gap: 24px; margin: 8px 0 12px; font-size: 13px; }
.ps-cols { display: flex; gap: 12px; }
.ps-col { flex: 1; min-width: 0; }
.ps-colh { background: #f7ecd2; border: 1px solid #e6d3a2; padding: 4px 8px; font-weight: bold; font-size: 12px; }
.ps-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.ps-table th, .ps-table td { border: 1px solid #999; padding: 3px 6px; text-align: left; }
.ps-table th { background: #f7ecd2; text-transform: uppercase; font-size: 11px; }
.ps-table .num { text-align: right; }
.ps-num { width: 64px; text-align: right; }
.ps-del { color: #c0392b; border: none; background: none; cursor: pointer; padding: 0 2px; }
.ps-total td { font-weight: bold; background: #fafafa; }
.ps-none { text-align: center; color: #999; }
.ps-add { border: none; background: none; color: #2563eb; cursor: pointer; font-size: 12px; padding: 4px 2px; }
@media (max-width: 820px) { .ps-cols { flex-direction: column; } }
</style>
