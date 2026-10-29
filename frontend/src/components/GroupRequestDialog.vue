<script setup>
// Dialog Group Request (N WO satu item grup, satu permintaan bersama) —
// tanpa input: total = hasil penuh semua anggota; server membentuk Handover
// Box Plan-nya sendiri. Server menolak → dialog tetap terbuka dgn error.
// Bahasa visual production_workspace: <dialog class="dialog"> + .dlg-*.
import { ref, computed, watch, nextTick } from 'vue'
import { Boxes } from 'lucide-vue-next'
import { createGroupRequest, previewHandoverRequest } from '@/data/board'
import { fmtNum } from '@/lib/format'

const props = defineProps({
	rows: { type: Array, required: true }, // anggota grup (≥2, satu item grup)
})
const emit = defineEmits(['done'])
const show = defineModel({ type: Boolean, default: false })

const dlg = ref(null)
const submitting = ref(false)
const previewLoading = ref(false)
const preview = ref(null)
const error = ref('')

const externalReservations = computed(() => {
	if (!preview.value || !preview.value.groups) return []
	return preview.value.groups.flatMap((g) => g.external_reservations || [])
})

const r0 = computed(() => props.rows[0] || {})
const itemName = computed(() => r0.value.item_name || r0.value.production_item || '')
const uom = computed(() => preview.value?.groups?.[0]?.stock_uom || r0.value.stock_uom || '')
const total = computed(() => {
	if (preview.value && preview.value.allocations) {
		return preview.value.allocations.reduce((s, a) => s + Number(a.allocated_qty || 0), 0)
	}
	return props.rows.reduce(
		(s, r) =>
			s + Number(r.expected_units != null ? r.expected_units : Math.round(Number(r.produced_qty || 0))),
		0,
	)
})
const unrequestedTotal = computed(() => {
	if (preview.value && preview.value.allocations) {
		return preview.value.allocations.reduce((s, a) => s + Number(a.unrequested_remainder || 0), 0)
	}
	return 0
})
const title = computed(() => `Group Request (${itemName.value} · ${props.rows.length} Work Orders)`)

watch(show, async (v) => {
	if (v) {
		error.value = ''
		preview.value = null
		previewLoading.value = true
		nextTick(() => dlg.value?.showModal())
		try {
			const res = await previewHandoverRequest(props.rows.map((r) => r.name))
			preview.value = res
		} catch (e) {
			error.value = e.message || 'Gagal memuat preview serah terima'
		} finally {
			previewLoading.value = false
		}
	} else {
		dlg.value?.close()
	}
})

function close() {
	show.value = false
}

function onCancel() {
	show.value = false
}

async function submit() {
	if (submitting.value || previewLoading.value || !preview.value || error.value) {
		return
	}
	submitting.value = true
	error.value = ''
	try {
		const allocMap = {}
		if (preview.value && preview.value.allocations) {
			for (const a of preview.value.allocations) {
				allocMap[a.work_order] = a.allocated_qty
			}
		}
		const res = await createGroupRequest(
			props.rows.map((r) => r.name),
			Object.keys(allocMap).length ? allocMap : null,
			preview.value?.fingerprint,
		)
		const allocatedSize = Object.keys(allocMap).length
			? Object.values(allocMap).filter((q) => Number(q) > 0).length
			: props.rows.length
		show.value = false
		emit('done', { materialRequest: (res && res.material_request) || '', size: allocatedSize })
	} catch (e) {
		error.value = e.message
	} finally {
		submitting.value = false
	}
}
</script>

<template>
	<Teleport to="body">
		<dialog ref="dlg" class="dialog" :aria-label="title" @cancel.prevent="onCancel">
			<header class="dlg-head">
				<div class="dlg-ico"><Boxes :size="17" :stroke-width="2" /></div>
				<div class="dlg-hgroup">
					<h3>{{ title }}</h3>
					<p class="dlg-sub">One request for all members — server forms the Box Plan.</p>
				</div>
			</header>
			<div
				v-if="externalReservations.length"
				class="dlg-warn"
				style="margin-bottom: 12px; padding: 8px 12px; background: #fffbeb; border: 1px solid #fde68a; border-radius: 6px; font-size: 13px; color: #92400e;"
			>
				Terdapat reservasi eksternal aktif (cth. R&D) di gudang asal. Kuantitas alokasi disesuaikan dengan stok tersedia.
			</div>
			<p class="dlg-note">
				One request for {{ rows.length }} Work Orders of {{ itemName }}.
			</p>
			<div class="dlg-context">
				<strong>{{ fmtNum(total) }} {{ uom }}</strong>
				<span> total dialokasikan dari {{ rows.length }} Work Orders</span>
				<div v-if="unrequestedTotal > 0" style="margin-top: 4px; font-size: 12px; color: #b45309;">
					Sisa {{ fmtNum(unrequestedTotal) }} {{ uom }} belum diminta (melebihi stok tersedia).
				</div>
			</div>
			<div v-for="g in preview?.groups || []" :key="`${g.item_code}:${g.source_warehouse}`" class="dlg-note">
				<strong>{{ g.source_warehouse }}</strong>: fisik {{ fmtNum(g.physical_stock) }} {{ uom }},
				reservasi {{ fmtNum(g.outstanding_reservations) }}, tersedia {{ fmtNum(g.available_pool) }}.
				<div v-for="(r, i) in g.external_reservations" :key="i">
					{{ r.material_request }} → {{ r.target_warehouse }}: {{ fmtNum(r.quantity) }} {{ uom }}
				</div>
			</div>
			<div v-for="a in preview?.allocations || []" :key="a.work_order" class="dlg-note">
				{{ a.work_order }}: {{ fmtNum(a.allocated_qty) }} {{ uom }} diminta,
				{{ fmtNum(a.unrequested_remainder) }} {{ uom }} belum diminta.
			</div>
			<p v-if="unrequestedTotal > 0" class="dlg-note">Alokasi administratif GBJ, bukan atribusi konsumsi R&amp;D ke WO tertentu.</p>
			<div v-for="g in preview?.groups || []" :key="`unresolved:${g.item_code}:${g.source_warehouse}`" class="dlg-note">
				<div v-for="(r, i) in g.unresolved_reservations || []" :key="i" role="alert">
					Gudang asal belum diketahui: {{ r.material_request }} → {{ r.target_warehouse }},
					{{ fmtNum(r.quantity) }} {{ g.stock_uom }}; tidak dialokasikan ke pool tertentu.
				</div>
			</div>
			<p v-if="error" class="err" role="alert">{{ error }}</p>
			<div class="dlg-actions">
				<button type="button" class="btn" @click="close">Cancel</button>
				<button
					type="button"
					class="btn btn-primary"
					:disabled="submitting || previewLoading || !preview || !!error"
					@click="submit"
				>
					{{ submitting ? 'Creating…' : 'Create Group Request' }}
				</button>
			</div>
		</dialog>
	</Teleport>
</template>

<style scoped>
.dlg-note { color: var(--muted, inherit); font-size: 13.5px; margin: 0; }
.dlg-context strong { font-weight: 650; }
.dlg-context span { color: var(--muted, inherit); font-size: 13px; }
</style>
