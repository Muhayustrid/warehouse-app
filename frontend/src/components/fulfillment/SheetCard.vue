<script setup>
// Kartu sheet ala excel (satu kategori per kartu) — dipakai bersama oleh
// tab Packing (sheet gabungan) dan step 3 Packing Slip per-SO, supaya
// tampilan & perilaku (drag kolom/baris, + Baris, merge/split koli klik kanan)
// selalu identik di kedua halaman.
import { computed, ref } from 'vue'

const props = defineProps({
	// Slip sheet: { name, customer_name, lines: [{item_code,item_name,qty,uom,koli_no,koli,berat,category}], dn_items: [...], editable }
	slip: { type: Object, required: true },
	// Kategori kartu ini: 'dry' | 'frozen'
	sheetTab: { type: String, required: true },
})

const emit = defineEmits(['save'])

const catLabel = computed(() => (props.sheetTab === 'dry' ? 'Dry' : 'Frozen'))

// Urutan kolom bisa di-drag per kategori (persist selama sesi).
const colOrder = ref({
	dry: ['item', 'qty', 'uom', 'koli', 'berat'],
	frozen: ['item', 'qty', 'uom', 'koli', 'berat'],
})
const COL_LABELS = { item: 'Item', qty: 'Qty', uom: 'Unit', koli: 'Colly', berat: 'Weight (Kg)' }
const cols = computed(() => colOrder.value[props.sheetTab].map((key) => ({ key, label: COL_LABELS[key] })))

const dragCol = ref(null)

function onColDragStart(key, event) {
	dragCol.value = { cat: props.sheetTab, key }
	event.dataTransfer.effectAllowed = 'move'
	event.stopPropagation()
}

function onColDrop(key) {
	if (!dragCol.value || dragCol.value.cat !== props.sheetTab || dragCol.value.key === key) return
	const order = colOrder.value[props.sheetTab]
	const from = order.indexOf(dragCol.value.key)
	const to = order.indexOf(key)
	if (from < 0 || to < 0) return
	order.splice(from, 1)
	order.splice(to, 0, dragCol.value.key)
	dragCol.value = null
}

// Grup koli = baris berurutan dengan koli_no sama; hanya run berurutan yang
// di-merge (rowspan). Baris normal tidak pernah ikut tergabung.
function decorate(lines) {
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

const section = computed(() => {
	const lines = props.slip.lines.filter((l) => l.category === props.sheetTab)
	return { label: catLabel.value, cat: props.sheetTab, lines, rows: decorate(lines) }
})

function secKoli(sec) {
	return sec.lines.reduce((a, l) => a + (Number(l.koli) || 0), 0)
}

// colspan label Total = kolom awal yang bukan koli/berat (tahan reorder kolom).
const leadSpan = computed(() => {
	let n = 0
	for (const key of colOrder.value[props.sheetTab]) {
		if (key === 'item' || key === 'qty' || key === 'uom') n++
		else break
	}
	return n || 1
})

// Drag baris: urutkan di dalam kategori kartu ini.
const dragRow = ref(null)

function onRowDragStart(idx, event) {
	if (!props.slip.editable) return
	// Row, bukan kartu: hentikan bubble agar kartu tidak ikut ter-drag.
	event.stopPropagation()
	dragRow.value = idx
	event.dataTransfer.effectAllowed = 'move'
}

function onRowDrop(idx) {
	const from = dragRow.value
	dragRow.value = null
	const lines = section.value.lines
	if (from === null || from === idx || !props.slip.editable) return
	const [moved] = lines.splice(from, 1)
	lines.splice(idx, 0, moved)
	emit('save', props.slip)
}

// + Baris inline: item dari daftar DN, masuk koli baru.
const addRow = ref(null) // { item_code, qty }

function confirmAddRow() {
	const row = addRow.value
	if (!row) return
	const dnItem = (props.slip.dn_items || []).find((it) => it.item_code === row.item_code)
	if (!dnItem || !(Number(row.qty) > 0)) return
	const nums = section.value.lines.map((l) => Number(l.koli_no) || 1)
	props.slip.lines.push({
		item_code: dnItem.item_code,
		item_name: dnItem.item_name || dnItem.item_code,
		qty: Number(row.qty),
		uom: dnItem.stock_uom || dnItem.uom || '',
		koli_no: (nums.length ? Math.max(...nums) : 0) + 1,
		koli: 1,
		berat: '',
		category: props.sheetTab,
	})
	addRow.value = null
	emit('save', props.slip)
}

// Klik kanan baris: gabung dengan baris di atas / pisah jadi koli sendiri.
const rowMenu = ref(null) // { idx, x, y }

function onRowContextMenu(idx, e) {
	if (!props.slip.editable) return
	e.preventDefault()
	rowMenu.value = { idx, x: e.clientX, y: e.clientY }
}

function mergeRowUp() {
	const m = rowMenu.value
	rowMenu.value = null
	if (!m || m.idx === 0) return
	const lines = section.value.lines
	const prev = lines[m.idx - 1]
	const cur = lines[m.idx]
	cur.koli_no = prev.koli_no
	cur.koli = 0 // anggota grup: koli dihitung sekali di baris pertama grup
	emit('save', props.slip)
}

function splitRow() {
	const m = rowMenu.value
	rowMenu.value = null
	if (!m) return
	const cur = section.value.lines[m.idx]
	const nums = section.value.lines.map((l) => Number(l.koli_no) || 1)
	cur.koli_no = Math.max(...nums) + 1
	cur.koli = 1
	emit('save', props.slip)
}
</script>

<template>
	<div class="sc-cap">
		<b class="sc-cust">{{ slip.customer_name }}</b>
		<span class="sc-dry">{{ catLabel }} :</span>
		<span class="sc-blank" title="Koli tulis tangan"></span>
		<span class="sc-dry">Koli</span>
		<span v-if="slip.driver" class="sc-driver">{{ slip.driver }}</span>
	</div>
	<div class="sc-sect">{{ catLabel }}</div>
	<table class="sc-tbl">
		<thead>
			<tr>
				<th
					v-for="col in cols"
					:key="col.key"
					:draggable="!!slip.editable"
					@dragstart="onColDragStart(col.key, $event)"
					@dragover.prevent
					@drop.prevent="onColDrop(col.key)"
				>
					{{ col.label }}
				</th>
			</tr>
		</thead>
		<tbody>
			<tr
				v-for="(r, i) in section.rows"
				:key="i"
				:draggable="!!slip.editable"
				@dragstart="onRowDragStart(r.idx, $event)"
				@dragover.prevent
				@drop.prevent="onRowDrop(r.idx)"
				@contextmenu="onRowContextMenu(r.idx, $event)"
			>
				<template v-for="col in cols" :key="col.key">
					<!-- Baris anggota grup merge: sel koli/berat tidak dirender (ditelan rowspan) -->
					<template v-if="col.key === 'koli' && r.covered"></template>
					<template v-else-if="col.key === 'berat' && r.covered"></template>
					<td v-else-if="col.key === 'koli'" class="num" :rowspan="r.span > 0 ? r.span : undefined">
						<input v-model="r.l.koli" class="sc-in" type="number" min="1" :disabled="!slip.editable" @change="emit('save', slip)" />
					</td>
					<td v-else-if="col.key === 'berat'" class="num">
						<input v-model="r.l.berat" class="sc-in" type="text" :disabled="!slip.editable" @change="emit('save', slip)" />
					</td>
					<td v-else-if="col.key === 'qty'" class="num">
						<input v-model.number="r.l.qty" class="sc-in" :class="{ 'qty-hl': r.l.category === 'frozen' }" type="number" min="1" :disabled="!slip.editable" @change="emit('save', slip)" />
					</td>
					<td v-else>{{ col.key === 'item' ? r.l.item_name : (r.l.uom || '') }}</td>
				</template>
			</tr>
			<tr class="tf">
				<td v-for="(col, ci) in cols" :key="col.key" :colspan="ci === 0 ? leadSpan : undefined">
					<template v-if="ci === 0">Total {{ section.label }}</template>
					<template v-else-if="col.key === 'koli'">{{ secKoli(section) }}</template>
				</td>
			</tr>
		</tbody>
	</table>
	<div v-if="slip.editable" class="sc-addrow">
		<template v-if="addRow">
			<select v-model="addRow.item_code" class="input input-sm">
				<option value="" disabled>Item…</option>
				<option v-for="it in slip.dn_items || []" :key="it.item_code" :value="it.item_code">{{ it.item_name || it.item_code }}</option>
			</select>
			<input v-model.number="addRow.qty" class="input input-sm" type="number" min="1" title="Qty" />
			<button type="button" class="btn btn-sm" @click="confirmAddRow">OK</button>
			<button type="button" class="btn btn-sm" @click="addRow = null">Batal</button>
		</template>
		<button v-else type="button" class="btn btn-sm" @click="addRow = { item_code: '', qty: 1 }">+ Baris</button>
	</div>

	<div v-if="rowMenu" class="ctx-wrap">
		<div class="ctx-overlay" @click="rowMenu = null" @contextmenu.prevent="rowMenu = null"></div>
		<div class="ctx-menu" :style="{ left: rowMenu.x + 'px', top: rowMenu.y + 'px' }">
			<button type="button" class="ctx-item" :disabled="rowMenu.idx === 0" @click="mergeRowUp">Gabung dengan baris di atas</button>
			<button type="button" class="ctx-item" @click="splitRow">Pisah jadi koli sendiri</button>
		</div>
	</div>
</template>

<style scoped>
.sc-cap { display: flex; align-items: center; gap: 8px; background: #ffe94a; border: 1.5px solid #111; border-bottom: 0; padding: 4px 8px; }
.sc-cust { flex: 1; font-weight: bold; font-size: 12.5px; text-align: left; }
.sc-dry { white-space: nowrap; font-size: 11px; }
.sc-blank { width: 48px; height: 14px; background: #fff; border: 1.5px solid #111; display: inline-block; }
.sc-driver { font-size: 10.5px; font-weight: 700; background: #111; color: #fff; padding: 1px 7px; border-radius: 9px; white-space: nowrap; }
.sc-sect { font-weight: 700; font-size: 12px; margin: 0; background: #ffc000; border: 1px solid #111; border-top: 0; text-align: center; padding: 3px 6px; letter-spacing: 1px; text-transform: uppercase; }
.sc-tbl { width: 100%; border-collapse: collapse; font-size: 10.5px; }
.sc-tbl th, .sc-tbl td { border: 1px solid #111; padding: 2px 4px; text-align: left; }
.sc-tbl th { background: #ffc000; font-size: 10px; font-weight: 700; text-align: center; }
.sc-tbl th[draggable='true'] { cursor: grab; }
.sc-tbl tbody tr[draggable='true'] { cursor: grab; }
.sc-tbl tbody tr[draggable='true']:hover { background: #fff8d6; }
.sc-tbl .num { text-align: center; }
.sc-in { width: 100%; border: 0; background: #f8f8f8; text-align: center; font: inherit; padding: 0; }
.sc-in:focus { background: #fff; outline: 1px solid #111; }
.sc-in.qty-hl { background: #ffe94a; font-weight: 600; }
.sc-tbl .tf td { background: #ffe94a; font-weight: bold; }
.sc-addrow { margin-top: 6px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.ctx-wrap { position: relative; }
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
.ctx-item:disabled { color: #aaa; cursor: not-allowed; }
</style>
