<script setup>
// Halaman Packing List Harian (rebuild 2026-11-16): per tanggal kirim, per
// customer Dry/Frozen, editable koli/berat/B-K/picker, simpan ke Delivery
// Manifest (page_state), cetak kertas A4 + label koli 60x40mm.
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Printer, Save, Tag, X } from 'lucide-vue-next'
import PrintPreviewModal from '@/components/fulfillment/PrintPreviewModal.vue'
import {
	fetchPackingListLabelsHtml,
	fetchPackingListPage,
	fetchPackingListPrintHtml,
	savePackingListPage,
} from '@/data/fulfillment'

const route = useRoute()

const company = ref(route.query.company || '')
const fromDate = ref(route.query.from_date || '')
const toDate = ref(route.query.to_date || route.query.from_date || '')
const groups = ref([])
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const notice = ref('')

const printModalOpen = ref(false)
const printModalTitle = ref('Packing List')
const printModalItems = ref([])

const printDate = ref(route.query.from_date || '')

onMounted(load)

async function load() {
	loading.value = true
	error.value = ''
	notice.value = ''
	try {
		const res = await fetchPackingListPage(company.value, fromDate.value, toDate.value)
		company.value = res.company || company.value
		groups.value = res.groups || []
		if (!printDate.value && groups.value.length) printDate.value = groups.value[0].delivery_date
	} catch (e) {
		error.value = e.message || 'Gagal memuat packing list.'
	} finally {
		loading.value = false
	}
}

function applyFilters() {
	notice.value = ''
	load()
}

async function save() {
	if (saving.value || !groups.value.length) return
	saving.value = true
	error.value = ''
	notice.value = ''
	try {
		for (const group of groups.value) {
			await savePackingListPage(company.value, group.delivery_date, [group])
		}
		notice.value = 'Packing list tersimpan.'
	} catch (e) {
		error.value = e.message || 'Gagal menyimpan packing list.'
	} finally {
		saving.value = false
	}
}

async function printPaper() {
	if (!printDate.value) return
	try {
		const html = await fetchPackingListPrintHtml(company.value, printDate.value)
		openPrint('Packing List', [{ label: 'Packing List', name: printDate.value, html }])
	} catch (e) {
		error.value = e.message || 'Gagal membuat cetakan packing list.'
	}
}

async function printLabels() {
	if (!printDate.value) return
	try {
		const html = await fetchPackingListLabelsHtml(company.value, printDate.value)
		openPrint('Label Koli', [{ label: 'Label Koli', name: printDate.value, html }])
	} catch (e) {
		error.value = e.message || 'Gagal membuat label koli.'
	}
}

async function printGroupLabels(group) {
	try {
		const html = await fetchPackingListLabelsHtml(company.value, group.delivery_date)
		openPrint(`Label Koli ${group.day_name}`, [{ label: 'Label Koli', name: group.delivery_date, html }])
	} catch (e) {
		error.value = e.message || 'Gagal membuat label koli.'
	}
}

function openPrint(title, items) {
	printModalTitle.value = title
	printModalItems.value = items
	printModalOpen.value = true
}

function collyCount(rows) {
	return (rows || []).reduce((sum, row) => sum + (Number(row.koli) || 1), 0)
}

function qtyTotal(rows) {
	return (rows || []).reduce((sum, row) => sum + (Number(row.qty) || 0), 0)
}

function removeRow(customer, category, index) {
	customer[category].splice(index, 1)
}

function addRow(customer, category) {
	customer[category].push({
		item_code: '',
		item_name: '',
		qty: 0,
		uom: '',
		koli: 1,
		berat: '',
		box_size: '',
		picker: customer.picker || '',
	})
}

function fmtQty(value) {
	const n = Number(value) || 0
	return Number.isInteger(n) ? String(n) : String(Math.round(n * 100) / 100)
}
</script>

<template>
	<div class="pl-page">
		<div class="pl-toolbar">
			<div class="pl-filters">
				<input v-model="company" class="input input-sm" type="hidden" />
				<input v-model="fromDate" class="input input-sm" type="date" aria-label="Dari tanggal" @change="applyFilters" />
				<input v-model="toDate" class="input input-sm" type="date" aria-label="Sampai tanggal" @change="applyFilters" />
			</div>
			<div class="pl-actions">
				<button type="button" class="btn" :disabled="saving || !groups.length" @click="save">
					<Save :size="15" :stroke-width="2" />
					<span>Simpan</span>
				</button>
				<input v-model="printDate" class="input input-sm" type="date" aria-label="Tanggal cetak" title="Tanggal cetak" />
				<button type="button" class="btn btn-primary" :disabled="!printDate" @click="printPaper">
					<Printer :size="15" :stroke-width="2" />
					<span>Cetak Packing List</span>
				</button>
				<button type="button" class="btn" :disabled="!printDate" @click="printLabels">
					<Tag :size="15" :stroke-width="2" />
					<span>Cetak Label Semua</span>
				</button>
			</div>
		</div>

		<p v-if="notice" class="pl-notice">{{ notice }}</p>
		<p v-if="error" class="pl-error">{{ error }}</p>
		<p v-if="loading" class="pl-empty">Memuat…</p>
		<p v-else-if="!groups.length" class="pl-empty">Tidak ada order yang sudah di-pick pada rentang tanggal ini.</p>

		<div v-else class="pl-paper">
			<header class="pl-paper-head">
				<div>
					<h1>PACKING LIST</h1>
					<p class="pl-company">{{ company }}</p>
				</div>
				<p class="pl-tanggal">
					Tanggal: <strong>{{ groups[0]?.delivery_date }}</strong>
				</p>
			</header>

			<section v-for="group in groups" :key="group.delivery_date" class="pl-day">
				<div class="pl-dayhead">
					<span class="pl-dayname">{{ group.day_name }}</span>
					<label class="pl-dayfield">MOBIL <input v-model="group.vehicle" class="input input-sm" type="text" /></label>
					<label class="pl-dayfield">DRIVER <input v-model="group.driver" class="input input-sm" type="text" /></label>
					<button type="button" class="btn btn-sm" @click="printGroupLabels(group)">
						<Tag :size="13" :stroke-width="2" />
						<span>Cetak Label</span>
					</button>
				</div>

				<div v-for="customer in group.customers" :key="customer.customer" class="pl-customer">
					<div
						v-for="(category, catLabel) in { frozen: 'FROZEN', dry: 'DRY' }"
						:key="category"
						class="pl-card"
					>
						<div class="pl-cardhead">
							<span>{{ customer.customer_name }}</span>
							<span>{{ catLabel }} : {{ collyCount(customer[category]) }} COLLY</span>
						</div>
						<table v-if="customer[category].length" class="pl-table">
							<thead>
								<tr>
									<th>Item</th>
									<th class="num">Qty</th>
									<th class="num">Koli</th>
									<th>Berat</th>
									<th>B / K</th>
									<th>Picker</th>
									<th class="num">Estimasi</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="(row, index) in customer[category]" :key="index">
									<td>
										<template v-if="row.item_code">{{ row.item_name || row.item_code }}</template>
										<input v-else v-model="row.item_name" class="input input-sm" type="text" placeholder="Nama item" />
									</td>
									<td class="num">
										<input v-model.number="row.qty" class="input input-sm pl-num-input" type="number" min="0" />
									</td>
									<td class="num pl-koli-cell">
										<button type="button" class="pl-koli-del" title="Hapus baris" @click="removeRow(customer, category, index)">
											<X :size="11" :stroke-width="2" />
										</button>
										<input v-model.number="row.koli" class="input input-sm pl-num-input" type="number" min="1" />
									</td>
									<td><input v-model="row.berat" class="input input-sm pl-wide" type="text" /></td>
									<td>
										<select v-model="row.box_size" class="input input-sm pl-wide">
											<option value=""></option>
											<option value="B">B</option>
											<option value="K">K</option>
										</select>
									</td>
									<td><input v-model="row.picker" class="input input-sm pl-wide" type="text" /></td>
									<td class="num">{{ category === 'frozen' && row.estimated_weight != null ? fmtQty(row.estimated_weight) : '' }}</td>
								</tr>
								<tr class="pl-total">
									<td>Total</td>
									<td class="num">{{ fmtQty(qtyTotal(customer[category])) }}</td>
									<td class="num">{{ collyCount(customer[category]) }}</td>
									<td colspan="4"></td>
								</tr>
							</tbody>
						</table>
						<button type="button" class="pl-add" @click="addRow(customer, category)">+ Tambah {{ catLabel.charAt(0) + catLabel.slice(1).toLowerCase() }}</button>
					</div>
				</div>
			</section>
		</div>

		<PrintPreviewModal :open="printModalOpen" :title="printModalTitle" :items="printModalItems" @close="printModalOpen = false" />
	</div>
</template>

<style scoped>
.pl-page { padding: 16px; }
.pl-toolbar { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.pl-filters, .pl-actions { display: flex; gap: 8px; align-items: center; }
.pl-notice { color: #1a7f37; font-size: 13px; }
.pl-error { color: #c0392b; font-size: 13px; }
.pl-empty { color: #666; padding: 32px 0; text-align: center; }
.pl-paper { background: #fff; border: 1px solid #ddd; padding: 20px 24px; max-width: 1100px; margin: 0 auto; }
.pl-paper-head { display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid #222; padding-bottom: 8px; }
.pl-paper-head h1 { font-size: 22px; letter-spacing: 0.04em; margin: 0; }
.pl-company { margin: 2px 0 0; color: #444; font-size: 13px; }
.pl-tanggal { font-size: 13px; margin: 0; }
.pl-dayhead { display: flex; align-items: center; gap: 14px; background: #fdf3d3; border: 1px solid #e6d3a2; padding: 6px 10px; margin: 14px 0 8px; font-weight: bold; }
.pl-dayname { font-size: 15px; }
.pl-dayfield { display: flex; align-items: center; gap: 6px; font-weight: normal; font-size: 13px; }
.pl-cardhead { display: flex; justify-content: space-between; background: #fdf3d3; border: 1px solid #e6d3a2; border-bottom: none; padding: 4px 10px; font-weight: bold; font-size: 13px; }
.pl-card { margin-bottom: 10px; }
.pl-cardhead + .pl-table { margin-top: 0; }
.pl-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.pl-table th, .pl-table td { border: 1px solid #999; padding: 3px 6px; text-align: left; }
.pl-table th { background: #fdf3d3; text-transform: uppercase; font-size: 11px; }
.pl-table .num { text-align: right; }
.pl-table .pl-num-input { width: 64px; text-align: right; }
.pl-wide { width: 100%; min-width: 60px; }
.pl-koli-cell { white-space: nowrap; }
.pl-koli-del { color: #c0392b; border: none; background: none; cursor: pointer; margin-right: 4px; padding: 0 2px; }
.pl-total td { font-weight: bold; background: #fafafa; }
.pl-add { border: none; background: none; color: #2563eb; cursor: pointer; font-size: 12px; padding: 4px 2px; }
</style>
