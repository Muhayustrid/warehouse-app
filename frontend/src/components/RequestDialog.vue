<script setup>
// Dialog konfirmasi request massal (N WO) — tanpa input: qty = alokasi
// preview tiap WO (server otoritatif). Submit berurutan per item + company
// (grup bila >= 2 WO); hasil parsial ditampilkan apa adanya.
// Bahasa visual production_workspace: <dialog class="dialog"> + .dlg-*.
import { ref, computed, watch, nextTick } from 'vue'
import { ClipboardCheck, CircleAlert } from 'lucide-vue-next'
import { createRequest, createGroupRequest, previewHandoverRequest } from '@/data/board'
import { fmtNum, fmtUomQty } from '@/lib/format'

const props = defineProps({
	rows: { type: Array, required: true }, // WO terpilih
})
const emit = defineEmits(['done'])
const show = defineModel({ type: Boolean, default: false })

const dlg = ref(null)
const phase = ref('confirm') // confirm | result
const submitting = ref(false)
const previewLoading = ref(false)
const preview = ref(null)
const previewError = ref('')
const okList = ref([])
const failList = ref([])

const externalReservations = computed(() => {
	if (!preview.value || !preview.value.groups) return []
	return preview.value.groups.flatMap((g) => g.external_reservations || [])
})

const title = computed(() =>
	phase.value === 'result'
		? !failList.value.length
			? 'Request created'
			: okList.value.length
				? 'Partially created'
				: 'All failed'
		: `Handover Request (${props.rows.length} Work Orders)`,
)

function rowQty(r) {
	if (r.unsupported_conversion) {
		return `${fmtNum(r.produced_qty || 0)} ${r.stock_uom || ''} (konversi tidak didukung)`
	}
	const alloc = preview.value?.allocations?.find((a) => a.work_order === r.name)
	if (alloc) {
		const rem = alloc.unrequested_remainder
		const main = fmtUomQty(alloc.allocated_qty, r)
		return rem > 0 ? `${main} (sisa ${fmtUomQty(rem, r)})` : main
	}
	const qty = r.expected_units != null ? r.expected_units : Math.round(Number(r.produced_qty || 0))
	return `${fmtNum(qty)} ${r.display_uom || r.stock_uom || ''}`
}

async function submit() {
	if (submitting.value || previewLoading.value || !preview.value || previewError.value) return
	submitting.value = true
	okList.value = []
	failList.value = []

	// One submit per item + company: each earlier MR changes the pool, so every
	// partition is re-previewed just before its own call and must still match
	// the allocation the user confirmed.
	const partitions = new Map()
	for (const r of props.rows) {
		const key = `${r.production_item}\u0000${r.company || ''}`
		partitions.set(key, [...(partitions.get(key) || []), r.name])
	}
	const confirmed = Object.fromEntries((preview.value.allocations || []).map((a) => [a.work_order, a.allocated_qty]))
	for (const names of partitions.values()) {
		const fail = (error) => names.forEach((wo) => failList.value.push({ wo, error }))
		try {
			const fresh = await previewHandoverRequest(names)
			const allocs = Object.fromEntries((fresh.allocations || []).map((a) => [a.work_order, a]))
			if (names.some((n) => !allocs[n] || Number(allocs[n].allocated_qty) !== Number(confirmed[n]))) {
				fail('Status alokasi atau stok telah berubah sejak preview. Muat ulang halaman.')
				continue
			}
			if (names.every((n) => Number(allocs[n].allocated_qty) <= 0)) {
				fail('Alokasi stok 0 (stok habis atau tereservasi)')
				continue
			}
			const res = names.length >= 2
				? await createGroupRequest(names, Object.fromEntries(names.map((n) => [n, allocs[n].allocated_qty])), fresh.fingerprint)
				: await createRequest(names[0], allocs[names[0]].allocated_qty, allocs[names[0]].fingerprint || fresh.fingerprint)
			okList.value.push(`${(res && res.material_request) || ''} (${names.join(', ')})`)
		} catch (e) {
			fail(e.message)
		}
	}
	submitting.value = false
	phase.value = 'result'
	emit('done', { ok: okList.value.length, fail: failList.value.length })
}

function close() {
	show.value = false
}

watch(show, async (v) => {
	if (v) {
		phase.value = 'confirm'
		preview.value = null
		previewError.value = ''
		previewLoading.value = true
		nextTick(() => dlg.value?.showModal())
		try {
			const res = await previewHandoverRequest(props.rows.map((r) => r.name))
			preview.value = res
		} catch (e) {
			previewError.value = e.message || 'Gagal memuat preview serah terima'
		} finally {
			previewLoading.value = false
		}
	} else {
		dlg.value?.close()
	}
})

function onCancel() {
	// Esc / cancel native: kembalikan fase konfirmasi + tutup via model
	setTimeout(() => {
		phase.value = 'confirm'
	})
	show.value = false
}
</script>

<template>
	<Teleport to="body">
		<dialog ref="dlg" class="dialog dialog-wide" :aria-label="title" @cancel.prevent="onCancel">
			<header class="dlg-head">
				<div class="dlg-ico"><ClipboardCheck :size="17" :stroke-width="2" /></div>
				<div class="dlg-hgroup">
					<h3>{{ title }}</h3>
					<p class="dlg-sub">Qty-only bulk request (W30) — server otoritatif.</p>
				</div>
			</header>
			<template v-if="phase === 'confirm'">
				<div
					v-if="previewError"
					class="failrow"
					style="margin-bottom: 12px;"
					role="alert"
				>
					<CircleAlert :size="15" :stroke-width="2" class="fico" />
					<span>{{ previewError }}</span>
				</div>
				<div
					v-if="externalReservations.length"
					class="dlg-warn"
					style="margin-bottom: 12px; padding: 8px 12px; background: #fffbeb; border: 1px solid #fde68a; border-radius: 6px; font-size: 13px; color: #92400e;"
				>
					Terdapat reservasi eksternal aktif (cth. R&D) di gudang asal. Kuantitas alokasi disesuaikan dengan stok tersedia.
				</div>
				<div v-for="g in preview?.groups || []" :key="`unresolved:${g.item_code}:${g.source_warehouse}`" class="dlg-note">
					<div v-for="(r, i) in g.unresolved_reservations || []" :key="i" role="alert">
						Gudang asal belum diketahui: {{ r.material_request }} → {{ r.target_warehouse }},
						{{ fmtNum(r.quantity) }} {{ g.stock_uom }}; tidak dialokasikan ke pool tertentu.
					</div>
				</div>
				<p class="dlg-note">
					Request qty equals the allocated output of each Work Order.
				</p>
				<div class="wo-body dlg-table">
					<div class="wo-thead hrow">
						<span>Batch · Item</span>
						<span>Work Order</span>
						<span class="th-kanan">Qty</span>
					</div>
					<div v-for="r in rows" :key="r.name" class="wo-row hrow">
						<span class="hitem">
							<strong>Batch {{ r.custom_adonan_ke || '-' }}</strong>
							{{ r.item_name }}
							<small>{{ r.name }} · yield {{ fmtNum(r.produced_qty) }} {{ r.stock_uom }}</small>
						</span>
						<span class="hwo">{{ r.name }}</span>
						<span class="wo-qty c-qty">
							<span class="qmain">{{ rowQty(r) }}</span>
						</span>
					</div>
				</div>
			</template>
			<template v-else>
				<p v-if="okList.length" class="dlg-note ok-note">
					<strong>Created:</strong> {{ okList.join(', ') }}
				</p>
				<div class="failwrap">
					<div v-for="f in failList" :key="f.wo" class="failrow" role="alert">
						<CircleAlert :size="15" :stroke-width="2" class="fico" />
						<span><strong>{{ f.wo }}</strong> — {{ f.error }}</span>
					</div>
				</div>
			</template>
			<div class="dlg-actions">
				<template v-if="phase === 'confirm'">
					<button type="button" class="btn" @click="close">Cancel</button>
					<button type="button" class="btn btn-primary" :disabled="submitting || previewLoading || !preview || !!previewError" @click="submit">
						{{ submitting ? 'Creating…' : 'Create Request' }}
					</button>
				</template>
				<template v-else>
					<button type="button" class="btn btn-primary" @click="close">Close</button>
				</template>
			</div>
		</dialog>
	</Teleport>
</template>

<style scoped>
.dlg-note { color: var(--muted, inherit); font-size: 13.5px; margin: 0 0 10px; }
.ok-note strong { color: var(--ok-strong, inherit); }
.dlg-table .wo-thead, .dlg-table .wo-row {
  grid-template-columns: minmax(160px, 1.4fr) minmax(120px, 1fr) 90px;
  cursor: default;
  padding: 9px 12px;
}
.dlg-table .wo-row:hover { background: transparent; box-shadow: none; }
.th-kanan { text-align: right; }
.hitem { display: flex; flex-direction: column; min-width: 0; font-size: 13px; }
.hitem small { color: var(--faint, inherit); font-size: 11px; }
.hwo { font-size: 12px; color: var(--muted, inherit); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.c-qty { align-items: flex-end; }
.c-qty .qmain { font-weight: 600; font-size: 13px; }
.failwrap { display: flex; flex-direction: column; gap: 8px; margin-bottom: 4px; }
.failrow {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--bad-bg, #f6e1dc);
  color: var(--bad-ink, #9c4736);
  font-size: 13px;
}
.failrow .fico { flex: none; margin-top: 2px; }
</style>
