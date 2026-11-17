<script setup>
// Halaman Packing Slip per Sales Order: daftar SO, editor bergaya Excel
// (header oranye PACKING LIST, tabel Frozen kiri / Dry kanan), drag baris &
// kolom + resize lebar kolom (HTML5, tanpa dependensi), add row mendukung
// 1 item di banyak koli dan 1 koli campuran, input Driver + No. Mobil.
// Edit terkunci setelah Delivery Note disubmit.
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, Filter, GripVertical, Plus, Printer, Save, Tag, X } from 'lucide-vue-next'
import PrintPreviewModal from '@/components/fulfillment/PrintPreviewModal.vue'
import {
	fetchPackingSheet,
	fetchPackingSheetHtml,
	fetchPackingSlip,
	fetchPackingSlipLabelsHtml,
	fetchPackingSlipPrintHtml,
	fetchPackingSlips,
	savePackingDriver,
	savePackingSlip,
} from '@/data/fulfillment'

const props = defineProps({
	// Embedded di tab Packing Fulfillment: daftar disembunyikan, Kembali = emit closed.
	embedded: { type: Boolean, default: false },
	// Nama SO yang langsung dibuka editor-nya saat mount.
	autoOpen: { type: String, default: '' },
	// Tanggal kirim tunggal (dari toolbar Fulfillment); menggantikan rentang lokal.
	date: { type: String, default: '' },
})

const emit = defineEmits(['closed', 'editing', 'filters-changed'])

const route = useRoute()

const company = ref(route.query.company || '')
const fromDate = ref(route.query.from_date || '')
const toDate = ref(route.query.to_date || route.query.from_date || '')
const slips = ref([])
const loading = ref(false)
const saving = ref(false)
const savingDriver = ref(false)
const error = ref('')
const notice = ref('')

const editing = ref(null) // editor payload
const driver = ref('')
const vehicleNo = ref('')

const printModalOpen = ref(false)
const printModalTitle = ref('')
const printModalItems = ref([])

// Filter ala ERPNext: panel dropdown, baris filter bisa ditambah bebas.
const FIELDS = [
	{ value: 'sales_order', label: 'No. SO' },
	{ value: 'customer_name', label: 'Customer' },
	{ value: 'po_no', label: 'PO No.' },
	{ value: 'status', label: 'Status' },
]
const OPERATORS = [
	{ value: 'like', label: 'Like' },
	{ value: 'not like', label: 'Not Like' },
	{ value: '=', label: 'Is' },
	{ value: '!=', label: 'Is Not' },
]
const showFilter = ref(false)
const filterDraft = ref([]) // { field, operator, value }
const appliedFilters = ref([])
watch(appliedFilters, (v) => emit('filters-changed', v.length))
const filteredSlips = computed(() => {
	let rows = slips.value
	for (const f of appliedFilters.value) {
		if (!f.field || !f.value) continue
		const needle = String(f.value).toLowerCase()
		rows = rows.filter((r) => {
			const val = String(r[f.field] ?? '').toLowerCase()
			if (f.operator === 'like') return val.includes(needle)
			if (f.operator === 'not like') return !val.includes(needle)
			if (f.operator === '=') return val === needle
			return val !== needle
		})
	}
	return rows
})
function addFilterRow() {
	filterDraft.value.push({ field: 'customer_name', operator: 'like', value: '' })
}
// Toolbar Fulfillment (tombol Filter) buka/tutup panel ini.
function toggleFilter() {
	showFilter.value = !showFilter.value
}
defineExpose({ toggleFilter, printSheet })

// ===== Sheet view (embedded): edit Koli/Berat langsung di kartu customer =====
function cardKoli(s) {
	return (s.lines || []).reduce((sum, l) => sum + (Number(l.koli) || 0), 0)
}

// ===== Drag & drop kiriman ke driver =====
// Satu kiriman area bisa dibawakan beberapa driver: assignment per kartu
// (per SO/DN) via custom_driver di Packing Slip, bukan satu driver per hari.
const dayDrivers = ref([])
const dragSlip = ref(null)
const newDriver = ref('')
const newVehicle = ref('')

function syncDayDrivers() {
	const seen = new Map()
	const add = (name, vehicle) => {
		const key = String(name || '').trim()
		if (!key || seen.has(key)) return
		seen.set(key, { driver: key, vehicle_no: String(vehicle || '').trim() })
	}
	for (const s of slips.value) add(s.driver, s.vehicle_no)
	add(driver.value, vehicleNo.value)
	dayDrivers.value = [...seen.values()]
}

function addDriver() {
	const key = newDriver.value.trim()
	if (!key) return
	const existing = dayDrivers.value.find((d) => d.driver.toLowerCase() === key.toLowerCase())
	if (existing) {
		if (newVehicle.value.trim()) existing.vehicle_no = newVehicle.value.trim()
	} else {
		dayDrivers.value.push({ driver: key, vehicle_no: newVehicle.value.trim() })
	}
	newDriver.value = ''
	newVehicle.value = ''
}

function onCardDragStart(s, event) {
	dragSlip.value = s
	event.dataTransfer.effectAllowed = 'move'
	event.dataTransfer.setData('text/plain', s.name || '')
}

// ===== Section per driver: tampilan sheet terduplikasi untuk tiap driver/mobil =====
const driverGroups = computed(() => {
	const groups = dayDrivers.value.map((d) => ({
		driver: d.driver,
		vehicle_no: d.vehicle_no,
		slips: filteredSlips.value.filter((s) => s.driver && s.driver === d.driver),
	}))
	const assigned = new Set(groups.flatMap((g) => g.slips.map((s) => s.name)))
	const un = filteredSlips.value.filter((s) => !assigned.has(s.name))
	if (un.length) groups.push({ driver: '', vehicle_no: '', slips: un })
	return groups
})

// Kartu: tabel DRY dan FROZEN terpisah (seperti picking list), masing-masing ada Total.
function cardSections(s) {
	// Grup koli = baris berurutan dengan koli_no sama; hanya run berurutan
	// yang di-merge (rowspan), jadi baris normal tidak pernah ikut tergabung.
	const decorate = (lines) => {
		const rows = lines.map((l, idx) => ({ l, idx, span: 0, covered: false }))
		let i = 0
		while (i < rows.length) {
			const k = Number(rows[i].l.koli_no) || 1
			let j = i
			while (j + 1 < rows.length && (Number(rows[j + 1].l.koli_no) || 1) === k) j++
			if (j > i) {
				rows[i].span = j - i + 1
				for (let x = i + 1; x <= j; x++) rows[x].covered = true
			}
			i = j + 1
		}
		return rows
	}
	return [
		{ label: 'Dry', cat: 'dry', lines: s.lines.filter((l) => l.category !== 'frozen'), rows: decorate(s.lines.filter((l) => l.category !== 'frozen')) },
		{ label: 'Frozen', cat: 'frozen', lines: s.lines.filter((l) => l.category === 'frozen'), rows: decorate(s.lines.filter((l) => l.category === 'frozen')) },
	].filter((sec) => sec.lines.length)
}

// Klik kanan baris kartu: gabung/pisah koli tanpa buka editor penuh.
const rowMenu = ref(null) // { s, sec, idx, x, y }
function onRowContextMenu(s, sec, idx, e) {
	if (!s.editable) return
	e.preventDefault()
	rowMenu.value = { s, sec, idx, x: e.clientX, y: e.clientY }
}
function mergeRowUp() {
	const m = rowMenu.value
	rowMenu.value = null
	if (!m || m.idx === 0) return
	const prev = m.sec.lines[m.idx - 1]
	const cur = m.sec.lines[m.idx]
	cur.koli_no = prev.koli_no
	cur.koli = 0 // anggota grup: koli dihitung sekali di baris pertama grup
	saveCard(m.s)
}
function splitRow() {
	const m = rowMenu.value
	rowMenu.value = null
	if (!m) return
	const cur = m.sec.lines[m.idx]
	const frozen = cur.category === 'frozen'
	const nos = m.s.lines.filter((l) => (l.category === 'frozen') === frozen).map((l) => Number(l.koli_no) || 1)
	cur.koli_no = Math.max(...nos) + 1
	cur.koli = 1
	saveCard(m.s)
}

function secKoli(sec) {
	return sec.lines.reduce((a, l) => a + (Number(l.koli) || 0), 0)
}

function groupKoli(g) {
	return g.slips.reduce((sum, s) => sum + cardKoli(s), 0)
}

// Drag baris item: urutkan di dalam kategori yang sama pada kartu yang sama.
const dragRow = ref(null) // { name, catFrozen, idx }
const dropHot = ref(null) // index section yang sedang di-hover saat drag kartu
function onSheetRowDragStart(s, sec, idx, e) {
	// Row, bukan kartu: hentikan bubble agar kartu tidak ikut ter-drag.
	e.stopPropagation()
	dragRow.value = { name: s.name, catFrozen: sec.cat === 'frozen', idx }
	e.dataTransfer.effectAllowed = 'move'
	e.dataTransfer.setData('text/plain', `${s.name}:${idx}`)
}

function onSheetRowDrop(s, sec, idx) {
	const d = dragRow.value
	dragRow.value = null
	if (!d || !s.editable || d.name !== s.name || d.catFrozen !== (sec.cat === 'frozen') || d.idx === idx) return
	const subset = []
	s.lines.forEach((l, i) => {
		if ((l.category === 'frozen') === d.catFrozen) subset.push(i)
	})
	const [moved] = s.lines.splice(subset[d.idx], 1)
	s.lines.splice(subset[idx], 0, moved)
	saveCard(s)
}

// Add-row langsung di kartu sheet: item beda koli tanpa buka editor penuh.
const addRowCard = ref(null) // { name, item_code, qty, category }

async function confirmCardRow(s) {
	const row = addRowCard.value
	if (!row) return
	const dnItem = (s.dn_items || []).find((it) => it.item_code === row.item_code)
	if (!dnItem) {
		error.value = 'Pilih item dari daftar DN terlebih dahulu.'
		return
	}
	if (!(Number(row.qty) > 0)) {
		error.value = 'Qty harus lebih dari 0.'
		return
	}
	const frozen = row.category === 'frozen'
	const koliNos = s.lines
		.filter((l) => (l.category === 'frozen') === frozen)
		.map((l) => Number(l.koli_no) || 1)
	s.lines.push({
		item_code: dnItem.item_code,
		item_name: dnItem.item_name || dnItem.item_code,
		qty: Number(row.qty),
		uom: dnItem.stock_uom || dnItem.uom || '',
		koli_no: (koliNos.length ? Math.max(...koliNos) : 0) + 1,
		koli: 1,
		berat: '',
		category: row.category,
	})
	addRowCard.value = null
	await saveCard(s)
}

async function onDropToDriver(d) {
	const s = dragSlip.value
	dragSlip.value = null
	if (!s || !s.editable) return
	error.value = ''
	try {
		await savePackingSlip(s.sales_order, s.lines, d.driver, d.vehicle_no)
		s.driver = d.driver
		s.vehicle_no = d.vehicle_no
	} catch (e) {
		error.value = e.message || `Gagal menugaskan driver untuk ${s.customer_name}.`
	}
}

async function saveCard(s) {
	if (!s.editable) return
	error.value = ''
	try {
		// Pertahankan driver per kartu; global hanya fallback untuk kartu tanpa driver.
		await savePackingSlip(s.sales_order, s.lines, s.driver || driver.value, s.vehicle_no || vehicleNo.value)
	} catch (e) {
		error.value = e.message || `Gagal menyimpan ${s.customer_name}.`
	}
}

async function printSheet() {
	try {
		const html = await fetchPackingSheetHtml(company.value, fromDate.value)
		printModalTitle.value = `Cetak Packing List (${fromDate.value})`
		printModalItems.value = [{ label: 'Packing List', name: fromDate.value, html }]
		printModalOpen.value = true
	} catch (e) {
		error.value = e.message || 'Gagal memuat packing list gabungan.'
	}
}
function applyFilters() {
	appliedFilters.value = filterDraft.value.filter((f) => f.field && f.value)
	showFilter.value = false
}
function clearFilters() {
	filterDraft.value = []
	appliedFilters.value = []
}

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

// Tanggal tunggal dari toolbar Fulfillment: paksa rentang = hari itu saja.
watch(
	() => props.date,
	(d) => {
		if (!d) return
		fromDate.value = d
		toDate.value = d
		load()
	},
)

onMounted(async () => {
	// Tanggal dari toolbar Fulfillment menang sebelum muat pertama.
	if (props.date) {
		fromDate.value = props.date
		toDate.value = props.date
	}
	await load()
	// Langsung buka editor: dari prop embedded atau query ?open=<SO>.
	const target = props.autoOpen || route.query.open
	if (target) {
		const row = slips.value.find((s) => s.sales_order === target)
		await openSlip(row || { name: target })
	}
})

async function load() {
	loading.value = true
	error.value = ''
	try {
		// Embedded (tab Packing): sheet gabungan dengan lines per SO.
		const res = props.embedded
			? await fetchPackingSheet(company.value, fromDate.value)
			: await fetchPackingSlips(company.value, fromDate.value, toDate.value)
		company.value = res.company || company.value
		slips.value = res.slips || []
		// Driver per hari: prefill dari data existing, jangan menimpa yang sedang diedit.
		if (typeof res.driver === 'string' && res.driver && !driver.value) driver.value = res.driver
		if (typeof res.vehicle_no === 'string' && res.vehicle_no && !vehicleNo.value) vehicleNo.value = res.vehicle_no
		syncDayDrivers()
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
		emit('editing', true)
	} catch (e) {
		error.value = e.message || 'Gagal membuka packing slip.'
	}
}

function closeSlip() {
	editing.value = null
	emit('editing', false)
	colOrder.value = {
		frozen: ['item', 'qty', 'uom', 'koli', 'berat'],
		dry: ['item', 'qty', 'uom', 'koli', 'berat'],
	}
	// Embedded di Fulfillment: beri tahu parent (refresh ringkasan) lalu
	// muat ulang daftar supaya status packing terbaru langsung terlihat.
	if (props.embedded) {
		emit('closed')
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

async function saveDriver() {
	savingDriver.value = true
	notice.value = ''
	error.value = ''
	try {
		const res = await savePackingDriver(company.value, fromDate.value, driver.value, vehicleNo.value)
		notice.value = `Driver & No. Mobil tersimpan untuk ${res.updated} packing slip.`
	} catch (e) {
		error.value = e.message || 'Gagal menyimpan driver.'
	} finally {
		savingDriver.value = false
	}
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
				<div v-if="!embedded" class="ps-filters">
					<input v-model="fromDate" class="input input-sm" type="date" aria-label="Dari tanggal" @change="load" />
					<input v-model="toDate" class="input input-sm" type="date" aria-label="Sampai tanggal" @change="load" />
				</div>
				<!-- Di mode embedded tombol Filter ada di toolbar Fulfillment -->
				<div class="ps-filter-wrap">
					<button v-if="!embedded" type="button" class="btn btn-sm" :class="{ 'btn-secondary': appliedFilters.length }" @click="showFilter = !showFilter">
						<Filter :size="13" :stroke-width="2" />
						<span>Filter{{ appliedFilters.length ? ` (${appliedFilters.length})` : '' }}</span>
					</button>
					<div v-if="showFilter" class="ps-filter-panel">
						<div class="ps-filter-head">
							<strong>Filter</strong>
							<button type="button" class="ps-filter-x" @click="showFilter = false">&times;</button>
						</div>
						<div v-if="!filterDraft.length" class="ps-filter-empty">Belum ada filter. Klik "Tambah Filter".</div>
						<div v-for="(f, i) in filterDraft" :key="i" class="ps-filter-row">
							<select v-model="f.field" class="input input-sm">
								<option v-for="f2 in FIELDS" :key="f2.value" :value="f2.value">{{ f2.label }}</option>
							</select>
							<select v-model="f.operator" class="input input-sm">
								<option v-for="o in OPERATORS" :key="o.value" :value="o.value">{{ o.label }}</option>
							</select>
							<input v-model="f.value" class="input input-sm" type="text" placeholder="Nilai" @keyup.enter="applyFilters" />
							<button type="button" class="ps-filter-x" title="Hapus baris" @click="filterDraft.splice(i, 1)">&times;</button>
						</div>
						<div class="ps-filter-foot">
							<button type="button" class="btn btn-sm" @click="addFilterRow">+ Tambah Filter</button>
							<span class="ps-filter-spacer"></span>
							<button type="button" class="btn btn-sm" @click="clearFilters">Reset</button>
							<button type="button" class="btn btn-sm btn-primary" @click="applyFilters">Terapkan</button>
						</div>
					</div>
				</div>
			</div>

			<!-- Driver: default global + tambah driver baru, dua kelompok rapi -->
			<div class="ps-driver-row">
				<div class="drv-main">
					<label>
						<span>Driver</span>
						<input v-model="driver" class="input input-sm" type="text" placeholder="Nama driver" />
					</label>
					<label>
						<span>No. Mobil</span>
						<input v-model="vehicleNo" class="input input-sm" type="text" placeholder="B 1234 XYZ" />
					</label>
					<button type="button" class="btn btn-sm btn-primary" :disabled="savingDriver" @click="saveDriver">
						Simpan Driver
					</button>
					<span class="muted">Berlaku utk semua packing {{ fromDate }}</span>
				</div>
				<div class="drv-extra">
					<span class="drv-sep"></span>
					<span class="drv-add">
						<input v-model="newDriver" class="input input-sm" type="text" placeholder="Nama driver baru" />
						<input v-model="newVehicle" class="input input-sm" type="text" placeholder="No. mobil baru" @keyup.enter="addDriver" />
						<button type="button" class="btn btn-sm" @click="addDriver">+ Driver</button>
					</span>
				</div>
			</div>

			<p v-if="error" class="ps-error">{{ error }}</p>
			<p v-if="loading" class="ps-empty">Memuat…</p>
			<p v-else-if="!slips.length" class="ps-empty">Belum ada Packing Slip pada rentang tanggal ini.</p>

			<!-- ===== Sheet ala papan klip (embedded): kartu per customer, edit langsung ===== -->
			<template v-else-if="embedded">
				<div
					v-for="(g, gi) in driverGroups"
					:key="gi"
					class="drv-section"
					:class="{ 'drop-hot': dropHot === gi }"
					@dragover.prevent="dropHot = gi"
					@dragleave="dropHot === gi && (dropHot = null)"
					@drop.prevent="dropHot = null; onDropToDriver(g)"
				>
					<div class="drv-head">
						<b>{{ g.driver || 'Belum ada driver' }}</b>
						<span>{{ g.vehicle_no || '—' }}</span>
						<small>Lepas kartu kiriman di sini</small>
					</div>
					<div class="sheet-grid">
						<div v-for="s in g.slips" :key="s.name" class="sheet-card" :draggable="!!s.editable" @dragstart="onCardDragStart(s, $event)" @dragend="dragSlip = null">
							<div class="sc-cap">
								<button type="button" class="sc-name" title="Buka editor penuh" @click="openSlip(s)">
									{{ s.customer_name }}
								</button>
								<span class="sc-dry">Dry : {{ s.totals?.total_dry_colly || 0 }}</span>
								<span class="sc-blank" title="Koli tulis tangan"></span>
								<span class="sc-dry">Colly</span>
								<span v-if="s.driver" class="sc-driver">{{ s.driver }}</span>
							</div>
							<template v-for="sec in cardSections(s)" :key="sec.cat">
								<div class="sc-sect">{{ sec.label }}</div>
								<table class="sc-tbl">
									<thead>
										<tr><th>Item</th><th>Qty</th><th>Koli</th><th>Berat</th><th>B / K</th><th>Picker</th><th>Estimasi</th></tr>
									</thead>
									<tbody>
										<tr
											v-for="(r, i) in sec.rows"
											:key="i"
											:draggable="!!s.editable"
											@dragstart="onSheetRowDragStart(s, sec, r.idx, $event)"
											@dragover.prevent
											@drop.prevent="onSheetRowDrop(s, sec, r.idx)"
											@contextmenu.prevent="onRowContextMenu(s, sec, r.idx, $event)"
										>
											<td>{{ r.l.item_name }}</td>
											<td class="num" :class="{ 'qty-hl': r.l.category === 'frozen' }">
												<input v-model.number="r.l.qty" class="sc-in" type="number" min="1" :disabled="!s.editable" @change="saveCard(s)" />
											</td>
											<td v-if="r.span > 0" class="num" :rowspan="r.span"><input v-model="r.l.koli" class="sc-in" type="number" min="1" :disabled="!s.editable" @change="saveCard(s)" /></td>
											<td v-else-if="!r.covered"><input v-model="r.l.koli" class="sc-in" type="number" min="1" :disabled="!s.editable" @change="saveCard(s)" /></td>
											<td v-if="!r.covered"><input v-model="r.l.berat" class="sc-in" type="text" :disabled="!s.editable" @change="saveCard(s)" /></td>
											<td v-if="!r.covered" class="hand"></td>
											<td v-if="!r.covered" class="hand"></td>
											<td v-if="!r.covered" class="num">{{ r.l.estimated_weight || '' }}</td>
										</tr>
										<tr class="tf">
											<td colspan="2">Total {{ sec.label }}</td>
											<td>{{ secKoli(sec) }}</td>
											<td colspan="4"></td>
										</tr>
									</tbody>
								</table>
							</template>
							<div v-if="s.editable" class="sc-addrow">
								<template v-if="addRowCard && addRowCard.name === s.name">
									<select v-model="addRowCard.item_code" class="input input-sm">
										<option value="" disabled>Item…</option>
										<option v-for="it in s.dn_items || []" :key="it.item_code" :value="it.item_code">{{ it.item_name || it.item_code }}</option>
									</select>
									<select v-model="addRowCard.category" class="input input-sm">
										<option value="dry">Dry</option>
										<option value="frozen">Frozen</option>
									</select>
									<input v-model.number="addRowCard.qty" class="input input-sm" type="number" min="1" title="Qty" />
									<button type="button" class="btn btn-sm" @click="confirmCardRow(s)">OK</button>
									<button type="button" class="btn btn-sm" @click="addRowCard = null">Batal</button>
								</template>
								<button v-else type="button" class="btn btn-sm" @click="addRowCard = { name: s.name, item_code: '', qty: 1, category: 'dry' }">+ Baris</button>
							</div>
						</div>
					</div>

					<!-- Catatan per driver: total koli, tabel truk, MOBIL/DRIVER -->
					<div class="sheet-foot">
						<div class="sf-total">TOTAL {{ groupKoli(g) }} KOLI</div>
						<table class="sf-box">
							<tr><th></th><th>BERANGKAT</th><th>PULANG</th></tr>
							<tr><td>BOX ABU</td><td></td><td></td></tr>
							<tr><td>KRANJANG BESAR</td><td></td><td></td></tr>
							<tr><td>KRANJANG KECIL</td><td></td><td></td></tr>
						</table>
						<div class="sf-mobil"><span>MOBIL : {{ g.vehicle_no || '—' }}</span><span>DRIVER : {{ g.driver || '—' }}</span></div>
					</div>
				</div>
			</template>

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
					v-for="row in filteredSlips"
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

		<!-- ================= Editor (full layar: lepas dari card Fulfillment) ================= -->
		<div v-else class="ps-editor-full">
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
		</div>

		<PrintPreviewModal :open="printModalOpen" :title="printModalTitle" :items="printModalItems" @close="printModalOpen = false" />

		<!-- Menu klik kanan baris kartu: gabung/pisah koli -->
		<template v-if="rowMenu">
			<div class="ctx-overlay" @click="rowMenu = null" @contextmenu.prevent="rowMenu = null"></div>
			<div class="ctx-menu" :style="{ left: rowMenu.x + 'px', top: rowMenu.y + 'px' }">
				<button v-if="rowMenu.idx > 0" class="ctx-item" @click="mergeRowUp">Gabung ke koli di atas</button>
				<button class="ctx-item" @click="splitRow">Pisah jadi koli sendiri</button>
			</div>
		</template>
	</div>
</template>

<style scoped>
.ps-page { padding: 16px; }

/* Editor full layar saat embedded: keluar dari alur card Fulfillment. */
.ps-editor-full {
	position: fixed;
	inset: 56px 0 0 0; /* di bawah topbar aplikasi */
	background: #f7f8fa;
	overflow-y: auto;
	padding: 16px 24px 40px;
	z-index: 40; /* di atas topbar (z-30) agar tidak tertutup */
}
@media (max-width: 820px) { .ps-editor-full { inset: 0; } }
.ps-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.ps-filters, .ps-actions { display: flex; gap: 8px; align-items: center; }

/* Filter ala ERPNext: dropdown ngambang di bawah toolbar, rata kanan
	(dekat tombol Filter). Wrap-nya position:relative sebagai anchor. */
.ps-filter-wrap { position: relative; width: 100%; }
.ps-filter-panel { position: absolute; top: calc(100% + 6px); right: 0; z-index: 40; width: min(680px, 100%); background: #fff; border: 1px solid #d1d8dd; border-radius: 6px; box-shadow: 0 4px 14px rgba(0, 0, 0, 0.12); padding: 10px 12px; }
.ps-filter-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.ps-filter-x { border: 0; background: none; font-size: 16px; line-height: 1; cursor: pointer; color: #6b7280; padding: 2px 4px; }
.ps-filter-x:hover { color: #111; }
.ps-filter-empty { font-size: 12px; color: #6b6b6b; padding: 6px 0; }
.ps-filter-row { display: flex; gap: 6px; align-items: center; margin-bottom: 6px; }
.ps-filter-row select { min-width: 110px; }
.ps-filter-foot { display: flex; gap: 6px; align-items: center; margin-top: 8px; }
.ps-filter-spacer { flex: 1; }
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
.ps-paper { background: #fff; border: 1px solid #ddd; padding: 0; max-width: 100%; margin: 0 auto; }
.ps-paper-head { background: #f7a600; color: #fff; padding: 14px; text-align: center; }
.ps-paper-head h1 { font-size: 26px; letter-spacing: 0.12em; margin: 0 0 6px; font-weight: 800; }
.ps-to { font-size: 14px; margin: 2px 0; }
.ps-driver-row { display: flex; gap: 12px; align-items: center; justify-content: space-between; padding: 10px 14px; border-bottom: 1px solid #eee; flex-wrap: wrap; }
.drv-main, .drv-extra { display: flex; gap: 10px; align-items: center; flex-wrap: nowrap; }
.drv-main .muted { white-space: nowrap; }
.ps-driver-row label { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; }
.ps-driver-row input { width: 180px; }
.ps-no { margin-left: auto; }
.ps-cols { display: flex; gap: 12px; padding: 14px; }
.ps-col { flex: 1; min-width: 0; overflow-x: auto; }
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

/* ===== Sheet ala papan klip (Image 2) ===== */
.sheet-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; align-items: start; }
@media (max-width: 900px) { .sheet-grid { grid-template-columns: 1fr; } }
.sheet-card { border: 1.5px solid #111; background: #fff; break-inside: avoid; }
.sc-cap { display: flex; align-items: center; gap: 8px; background: #ffe94a; border-bottom: 1.5px solid #111; padding: 4px 8px; }
.sc-name { flex: 1; border: 0; background: none; padding: 0; font-weight: bold; font-size: 12.5px; text-align: left; cursor: pointer; color: inherit; }
.sc-name:hover { text-decoration: underline; }
.sc-dry { white-space: nowrap; font-size: 11px; }
.sc-wblank { display: inline-block; width: 42px; height: 16px; background: #fff; border: 1px solid #111; }
.sc-blank { width: 48px; height: 14px; background: #fff; border: 1.5px solid #111; display: inline-block; }
.sc-driver { margin-left: auto; font-size: 10.5px; font-weight: 700; background: #111; color: #fff; padding: 1px 7px; border-radius: 9px; white-space: nowrap; }
.sheet-card.dragging { opacity: 0.5; }
.drv-add { display: flex; gap: 6px; align-items: center; }
.sc-tbl { width: 100%; border-collapse: collapse; font-size: 10.5px; }
.sc-tbl th, .sc-tbl td { border: 1px solid #111; padding: 2px 4px; text-align: left; }
.sc-tbl th { background: #ffe94a; font-size: 9.5px; }
.sc-tbl .num { text-align: center; }
.sc-tbl .qty-hl { background: #ffe94a; font-weight: 600; }
.sc-tbl .hand { width: 34px; }
.sc-in { width: 100%; border: 0; background: #f8f8f8; text-align: center; font: inherit; padding: 0; }
.sc-in:focus { background: #fff; outline: 1px solid #111; }
.sc-tbl .tf td { background: #ffe94a; font-weight: bold; }

/* Section per driver + tabel DRY/FROZEN + add-row inline */
.drv-sep { width: 1px; height: 26px; background: #d0d5dd; margin: 0 4px; }
.drv-add { display: inline-flex; gap: 6px; align-items: center; }
.drv-add .input { width: 160px; }
.drv-section { margin-bottom: 18px; }
.drv-section.drop-hot { outline: 2px dashed #2b6cb0; outline-offset: 4px; border-radius: 8px; }
.drv-head { display: inline-flex; align-items: center; gap: 10px; border: 1.5px dashed #111; background: #fffdf2; padding: 6px 12px; border-radius: 6px; margin-bottom: 10px; cursor: default; }
.drv-head b { font-size: 12.5px; }
.drv-head span { font-size: 11px; color: #444; }
.drv-head small { font-size: 9px; color: #888; }
.sc-sect { font-weight: 700; font-size: 11px; margin: 6px 2px 2px; }
.sc-addrow { margin-top: 6px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }

.ctx-overlay { position: fixed; inset: 0; z-index: 90; }
.ctx-menu {
	position: fixed; z-index: 91; background: #fff; border: 1px solid #d1d5db;
	border-radius: 6px; box-shadow: 0 6px 18px rgba(0, 0, 0, 0.18); padding: 4px; min-width: 190px;
}
.ctx-item {
	display: block; width: 100%; text-align: left; padding: 6px 10px; border: 0;
	background: none; font-size: 12.5px; cursor: pointer; border-radius: 4px;
}
.ctx-item:hover { background: #eef2ff; }
.sc-tbl tbody tr[draggable='true']:hover { background: #fff8d6; }
.sheet-foot { margin-top: 8px; }
.sf-total { font-size: 14px; font-weight: bold; }
.sf-box { border-collapse: collapse; margin-top: 6px; }
.sf-box th, .sf-box td { border: 1px solid #111; height: 24px; min-width: 90px; font-size: 11px; padding: 2px 6px; }
.sf-mobil { margin-top: 6px; font-size: 12px; font-weight: bold; display: flex; gap: 24px; }
</style>
