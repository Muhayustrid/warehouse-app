<script setup>
// Halaman Packing Slip per Sales Order: daftar SO, editor bergaya Excel
// (header oranye PACKING LIST, tabel Frozen kiri / Dry kanan), drag baris &
// kolom + resize lebar kolom (HTML5, tanpa dependensi), add row mendukung
// 1 item di banyak koli dan 1 koli campuran, input Driver + No. Mobil.
// Edit terkunci setelah Delivery Note disubmit.
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, GripVertical, Plus, Printer, Save, Tag, X } from 'lucide-vue-next'
import PrintPreviewModal from '@/components/fulfillment/PrintPreviewModal.vue'
import {
	fetchPackingSlip,
	fetchPackingSlipLabelsHtml,
	fetchPackingSlipPrintHtml,
	fetchPackingSlips,
	savePackingSlip,
} from '@/data/fulfillment'

const route = useRoute()

const company = ref(route.query.company || '')
const fromDate = ref(route.query.from_date || '')
const toDate = ref(route.query.to_date || route.query.from_date || '')
const slips = ref([])
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const notice = ref('')

const editing = ref(null) // editor payload
const driver = ref('')
const vehicleNo = ref('')

const printModalOpen = ref(false)
const printModalTitle = ref('')
const printModalItems = ref([])

// add-row state: table category + pilihan item + qty + nomor koli
const addRow = ref(null) // { category, item_code, qty, koli_no }

// drag state (HTML5, manual): baris & kolom
const dragLine = ref(null) // index di editing.lines
const dragCol = ref(null) // { table: 'frozen'|'dry', key }
const dragOverCol = ref(null)

// urutan kolom per tabel (persist lokal per sesi editor)
const colOrder = ref({
	frozen: ['item', 'qty', 'uom', 'koli', 'berat'],
	dry: ['item', 'qty', 'uom', 'koli', 'berat'],
})
const colWidths = ref({
	frozen: { item: 220, qty: 70, uom: 70, koli: 60, berat: 100 },
	dry: { item: 220, qty: 70, uom: 70, koli: 60, berat: 100 },
})
const COL_LABELS = { item: 'Item', qty: 'Qty', uom: 'Unit', koli: 'Koli', berat: 'Weight (Kg)' }

onMounted(async () => {
	await load()
	// Dari tab Packing: ?open=<SO> langsung buka editor SO tersebut.
	if (route.query.open) {
		const row = slips.value.find((s) => s.sales_order === route.query.open)
		if (row) await openSlip(row)
	}
})

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
		driver.value = editing.value.driver || ''
		vehicleNo.value = editing.value.vehicle_no || ''
	} catch (e) {
		error.value = e.message || 'Gagal membuka packing slip.'
	}
}

function closeSlip() {
	editing.value = null
	colOrder.value = {
		frozen: ['item', 'qty', 'uom', 'koli', 'berat'],
		dry: ['item', 'qty', 'uom', 'koli', 'berat'],
	}
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

// ---------------- add row ----------------
function openAddRow(category) {
	addRow.value = { category, item_code: '', qty: 1, koli_no: nextKoliNo(category) }
}

function nextKoliNo(category) {
	const nums = (editing.value?.lines || [])
		.filter((l) => l.category === category)
		.map((l) => Number(l.koli_no) || 1)
	return (nums.length ? Math.max(...nums) : 0) + 1
}

function confirmAddRow() {
	const row = addRow.value
	if (!row) return
	const dnItem = (editing.value?.dn_items || []).find((it) => it.item_code === row.item_code)
	if (!dnItem) {
		error.value = 'Pilih item dari daftar DN terlebih dahulu.'
		return
	}
	if (!(Number(row.qty) > 0)) {
		error.value = 'Qty harus lebih dari 0.'
		return
	}
	error.value = ''
	editing.value.lines.push({
		item_code: dnItem.item_code,
		item_name: dnItem.item_name || dnItem.item_code,
		qty: Number(row.qty),
		uom: dnItem.stock_uom || dnItem.uom || '',
		koli_no: Number(row.koli_no) || nextKoliNo(row.category),
		koli: 1,
		berat: '',
		category: row.category,
	})
	addRow.value = null
}

function removeLine(line) {
	const idx = editing.value.lines.indexOf(line)
	if (idx >= 0) editing.value.lines.splice(idx, 1)
}

// ---------------- drag & drop (HTML5 manual) ----------------
function onLineDragStart(index, event) {
	dragLine.value = index
	event.dataTransfer.effectAllowed = 'move'
}

function onLineDrop(targetIndex, event) {
	event.preventDefault()
	const from = dragLine.value
	dragLine.value = null
	if (from === null || from === targetIndex) return
	const lines = editing.value.lines
	const [moved] = lines.splice(from, 1)
	lines.splice(targetIndex > from ? targetIndex - 1 : targetIndex, 0, moved)
}

function onColDragStart(table, key, event) {
	dragCol.value = { table, key }
	event.dataTransfer.effectAllowed = 'move'
}

function onColDrop(table, key) {
	if (!dragCol.value || dragCol.value.table !== table || dragCol.value.key === key) return
	const order = colOrder.value[table]
	const from = order.indexOf(dragCol.value.key)
	const to = order.indexOf(key)
	if (from < 0 || to < 0) return
	order.splice(from, 1)
	order.splice(to, 0, dragCol.value.key)
	dragCol.value = null
	dragOverCol.value = null
}

function startResize(table, key, event) {
	event.preventDefault()
	const startX = event.clientX
	const startW = colWidths.value[table][key]
	function move(e) {
		colWidths.value[table][key] = Math.max(40, startW + e.clientX - startX)
	}
	function up() {
		window.removeEventListener('mousemove', move)
		window.removeEventListener('mouseup', up)
	}
	window.addEventListener('mousemove', move)
	window.addEventListener('mouseup', up)
}

// ---------------- save & print ----------------
async function save() {
	if (saving.value || !editing.value?.editable) return
	saving.value = true
	error.value = ''
	try {
		await savePackingSlip(editing.value.name, editing.value.lines, driver.value, vehicleNo.value)
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
					<span>PACKING</span>
					<span>STATUS</span>
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
					<span class="muted ps-packing">
						<template v-if="row.packing && row.packing.packed">
							{{ row.packing.koli_dry }} Dry · {{ row.packing.koli_frozen }} Frozen koli ·
							{{ row.packing.weight_dry + row.packing.weight_frozen }} kg
							<span v-if="row.packing.driver" class="ps-driver">— Driver: {{ row.packing.driver }}</span>
						</template>
						<template v-else>Belum diinput</template>
					</span>
					<span>
						<span class="badge" :class="row.editable ? 'b-edit' : 'b-ro'">{{ row.status }}</span>
					</span>
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
					</template>
					<template v-else>
						<span class="ps-ro-note">Read-only — Delivery Note sudah disubmit</span>
					</template>
					<button type="button" class="btn" @click="printPaper">
						<Printer :size="15" :stroke-width="2" />
						<span>Cetak Packing List</span>
					</button>
					<button type="button" class="btn" @click="printLabels">
						<Tag :size="15" :stroke-width="2" />
						<span>Cetak Label</span>
					</button>
				</div>
			</div>

			<p v-if="notice" class="ps-notice">{{ notice }}</p>
			<p v-if="error" class="ps-error">{{ error }}</p>

			<div class="ps-paper">
				<!-- Header oranye penuh, teks tengah -->
				<header class="ps-paper-head">
					<h1>PACKING LIST</h1>
					<div class="ps-to">TO : <strong>{{ editing.header.customer_name }}</strong></div>
					<div class="ps-to">PO No : <strong>{{ editing.header.po_no || '-' }}</strong></div>
					<div class="ps-to">Delivery date : <strong>{{ editing.header.delivery_date || '-' }}</strong></div>
				</header>

				<!-- Driver + No. Mobil -->
				<div class="ps-driver-row">
					<label>
						<span>Driver</span>
						<input v-model="driver" class="input input-sm" type="text" :disabled="!editing.editable" placeholder="Nama driver" />
					</label>
					<label>
						<span>No. Mobil</span>
						<input v-model="vehicleNo" class="input input-sm" type="text" :disabled="!editing.editable" placeholder="B 1234 XYZ" />
					</label>
					<span v-if="editing.name" class="muted ps-no">No: {{ editing.name }}</span>
				</div>

				<div class="ps-cols">
					<!-- FROZEN kiri -->
					<div class="ps-col">
						<div class="ps-colh ps-colh-frozen">FROZEN</div>
						<table class="ps-table">
							<thead>
								<tr>
									<th v-if="editing.editable" class="ps-handle-col"></th>
									<th
										v-for="key in colOrder.frozen"
										:key="key"
										:style="{ width: colWidths.frozen[key] + 'px' }"
										draggable="true"
										@dragstart="onColDragStart('frozen', key, $event)"
										@dragover.prevent="dragOverCol = key"
										@drop="onColDrop('frozen', key)"
										:class="{ 'ps-col-dragover': dragOverCol === key }"
									>
										{{ COL_LABELS[key] }}
										<span class="ps-resize" @mousedown="startResize('frozen', key, $event)"></span>
									</th>
									<th v-if="editing.editable" class="ps-del-col"></th>
								</tr>
							</thead>
							<tbody>
								<tr
									v-for="(row, index) in frozenLines"
									:key="index"
									draggable="true"
									@dragstart="onLineDragStart(editing.lines.indexOf(row), $event)"
									@dragover.prevent
									@drop="onLineDrop(editing.lines.indexOf(row), $event)"
								>
									<td v-if="editing.editable" class="ps-handle-col"><GripVertical :size="13" class="ps-grip" /></td>
									<template v-for="key in colOrder.frozen" :key="key">
										<td v-if="key === 'item'">{{ row.item_name || row.item_code || '-' }}</td>
										<td v-else-if="key === 'qty'" class="num">
											<input v-model.number="row.qty" class="input input-sm ps-num" type="number" min="0" :disabled="!editing.editable" />
										</td>
										<td v-else-if="key === 'uom'">{{ row.uom }}</td>
										<td v-else-if="key === 'koli'" class="num">
											<input v-model.number="row.koli_no" class="input input-sm ps-num" type="number" min="1" :disabled="!editing.editable" />
										</td>
										<td v-else class="num">
											<input v-model="row.berat" class="input input-sm ps-num" type="text" :disabled="!editing.editable" />
										</td>
									</template>
									<td v-if="editing.editable" class="num ps-del-col">
										<button type="button" class="ps-del" title="Hapus baris" @click="removeLine(row)">
											<X :size="11" :stroke-width="2" />
										</button>
									</td>
								</tr>
								<tr v-if="!frozenLines.length"><td :colspan="6" class="ps-none">—</td></tr>
							</tbody>
						</table>
						<template v-if="editing.editable">
							<button type="button" class="ps-add" @click="openAddRow('frozen')"><Plus :size="12" :stroke-width="2" /> Tambah Baris</button>
							<div v-if="addRow && addRow.category === 'frozen'" class="ps-addrow">
								<select v-model="addRow.item_code" class="select select-sm">
									<option value="" disabled>Pilih item dari DN…</option>
									<option v-for="it in editing.dn_items" :key="it.item_code" :value="it.item_code">
										{{ it.item_code }} — {{ it.item_name || it.item_code }}
									</option>
								</select>
								<input v-model.number="addRow.qty" class="input input-sm ps-num" type="number" min="0" placeholder="Qty" />
								<input v-model.number="addRow.koli_no" class="input input-sm ps-num-sm" type="number" min="1" placeholder="Koli" />
								<button type="button" class="btn btn-primary btn-sm" @click="confirmAddRow">OK</button>
								<button type="button" class="btn btn-sm" @click="addRow = null">Batal</button>
							</div>
						</template>
						<div class="ps-total-line">
							Total Frozen (colly): <strong>{{ totals.frozenColly }}</strong> ·
							Net Weight Frozen (kg): <strong>{{ fmtQty(totals.frozenWeight) }}</strong>
						</div>
					</div>

					<!-- DRY kanan -->
					<div class="ps-col">
						<div class="ps-colh ps-colh-dry">DRY</div>
						<table class="ps-table">
							<thead>
								<tr>
									<th v-if="editing.editable" class="ps-handle-col"></th>
									<th
										v-for="key in colOrder.dry"
										:key="key"
										:style="{ width: colWidths.dry[key] + 'px' }"
										draggable="true"
										@dragstart="onColDragStart('dry', key, $event)"
										@dragover.prevent="dragOverCol = key"
										@drop="onColDrop('dry', key)"
										:class="{ 'ps-col-dragover': dragOverCol === key }"
									>
										{{ COL_LABELS[key] }}
										<span class="ps-resize" @mousedown="startResize('dry', key, $event)"></span>
									</th>
									<th v-if="editing.editable" class="ps-del-col"></th>
								</tr>
							</thead>
							<tbody>
								<tr
									v-for="(row, index) in dryLines"
									:key="index"
									draggable="true"
									@dragstart="onLineDragStart(editing.lines.indexOf(row), $event)"
									@dragover.prevent
									@drop="onLineDrop(editing.lines.indexOf(row), $event)"
								>
									<td v-if="editing.editable" class="ps-handle-col"><GripVertical :size="13" class="ps-grip" /></td>
									<template v-for="key in colOrder.dry" :key="key">
										<td v-if="key === 'item'">{{ row.item_name || row.item_code || '-' }}</td>
										<td v-else-if="key === 'qty'" class="num">
											<input v-model.number="row.qty" class="input input-sm ps-num" type="number" min="0" :disabled="!editing.editable" />
										</td>
										<td v-else-if="key === 'uom'">{{ row.uom }}</td>
										<td v-else-if="key === 'koli'" class="num">
											<input v-model.number="row.koli_no" class="input input-sm ps-num" type="number" min="1" :disabled="!editing.editable" />
										</td>
										<td v-else class="num">
											<input v-model="row.berat" class="input input-sm ps-num" type="text" :disabled="!editing.editable" />
										</td>
									</template>
									<td v-if="editing.editable" class="num ps-del-col">
										<button type="button" class="ps-del" title="Hapus baris" @click="removeLine(row)">
											<X :size="11" :stroke-width="2" />
										</button>
									</td>
								</tr>
								<tr v-if="!dryLines.length"><td :colspan="6" class="ps-none">—</td></tr>
							</tbody>
						</table>
						<template v-if="editing.editable">
							<button type="button" class="ps-add" @click="openAddRow('dry')"><Plus :size="12" :stroke-width="2" /> Tambah Baris</button>
							<div v-if="addRow && addRow.category === 'dry'" class="ps-addrow">
								<select v-model="addRow.item_code" class="select select-sm">
									<option value="" disabled>Pilih item dari DN…</option>
									<option v-for="it in editing.dn_items" :key="it.item_code" :value="it.item_code">
										{{ it.item_code }} — {{ it.item_name || it.item_code }}
									</option>
								</select>
								<input v-model.number="addRow.qty" class="input input-sm ps-num" type="number" min="0" placeholder="Qty" />
								<input v-model.number="addRow.koli_no" class="input input-sm ps-num-sm" type="number" min="1" placeholder="Koli" />
								<button type="button" class="btn btn-primary btn-sm" @click="confirmAddRow">OK</button>
								<button type="button" class="btn btn-sm" @click="addRow = null">Batal</button>
							</div>
						</template>
						<div class="ps-total-line">
							Total Dry (colly): <strong>{{ totals.dryColly }}</strong> ·
							Net Weight Dry (kg): <strong>{{ fmtQty(totals.dryWeight) }}</strong>
						</div>
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
	grid-template-columns: 170px minmax(160px, 1fr) 110px minmax(220px, 1fr) 110px 32px;
	gap: 14px;
	padding: 11px 16px;
	align-items: center;
}
.ps-thead { border-bottom: 1px solid #e5e7eb; font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase; }
.ps-trow { border-bottom: 1px solid #f1f5f9; cursor: pointer; font-size: 13px; }
.ps-trow:hover { background: #f8fafc; }
.ps-packing { font-size: 12px; }
.ps-driver { color: #2563eb; }
.badge { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 4px; }
.b-edit { background: #dcfce7; color: #166534; }
.b-ro { background: #f1f5f9; color: #64748b; }
.ps-ro-note { font-size: 12px; color: #64748b; }

/* Paper — gaya Excel image 2 */
.ps-paper { background: #fff; border: 1px solid #ddd; padding: 0; max-width: 1150px; margin: 0 auto; }
.ps-paper-head { background: #f7a600; color: #fff; padding: 14px; text-align: center; }
.ps-paper-head h1 { font-size: 26px; letter-spacing: 0.12em; margin: 0 0 6px; font-weight: 800; }
.ps-to { font-size: 14px; margin: 2px 0; }
.ps-driver-row { display: flex; gap: 16px; align-items: center; padding: 10px 14px; border-bottom: 1px solid #eee; flex-wrap: wrap; }
.ps-driver-row label { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; }
.ps-driver-row input { width: 180px; }
.ps-no { margin-left: auto; }
.ps-cols { display: flex; gap: 12px; padding: 14px; }
.ps-col { flex: 1; min-width: 0; }
.ps-colh { padding: 4px 8px; font-weight: bold; font-size: 13px; border: 1px solid #999; border-bottom: none; text-align: center; }
.ps-colh-frozen { background: #bfe3f7; color: #0b5e86; }
.ps-colh-dry { background: #ffe2a8; color: #8a5a00; }
.ps-table { width: 100%; border-collapse: collapse; font-size: 12px; table-layout: fixed; }
.ps-table th, .ps-table td { border: 1px solid #999; padding: 3px 6px; text-align: left; overflow: hidden; }
.ps-table th { background: #f7ecd2; text-transform: uppercase; font-size: 11px; position: relative; cursor: grab; user-select: none; }
.ps-table th.ps-col-dragover { outline: 2px dashed #f7a600; outline-offset: -2px; }
.ps-resize { position: absolute; right: 0; top: 0; height: 100%; width: 6px; cursor: col-resize; }
.ps-resize:hover { background: #f7a60055; }
.ps-handle-col { width: 22px; padding: 0 !important; text-align: center; }
.ps-grip { color: #94a3b8; cursor: grab; }
.ps-del-col { width: 26px; }
.ps-table .num { text-align: right; }
.ps-num { width: 64px; text-align: right; }
.ps-num-sm { width: 56px; }
.ps-del { color: #c0392b; border: none; background: none; cursor: pointer; padding: 0 2px; }
.ps-none { text-align: center; color: #999; }
.ps-add { border: none; background: none; color: #2563eb; cursor: pointer; font-size: 12px; padding: 6px 2px; display: inline-flex; align-items: center; gap: 3px; }
.ps-addrow { display: flex; gap: 6px; align-items: center; padding: 4px 0 8px; flex-wrap: wrap; }
.ps-addrow select { min-width: 220px; }
.ps-total-line { border: 1px solid #999; background: #f4f4f0; padding: 5px 8px; font-size: 12px; margin-top: 8px; }
@media (max-width: 820px) { .ps-cols { flex-direction: column; } }
</style>
