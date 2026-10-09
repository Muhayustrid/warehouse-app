<script setup>
// Dialog Group Request (N WO satu item grup, satu permintaan bersama) —
// tanpa input: total = hasil penuh semua anggota; server membentuk Handover
// Box Plan-nya sendiri. Server menolak → dialog tetap terbuka dgn error.
// Bahasa visual production_workspace: <dialog class="dialog"> + .dlg-*.
import { ref, computed, watch, nextTick } from 'vue'
import { Boxes } from 'lucide-vue-next'
import { createGroupRequest } from '@/data/board'
import { fmtNum } from '@/lib/format'

const props = defineProps({
	rows: { type: Array, required: true }, // anggota grup (≥2, satu item grup)
})
const emit = defineEmits(['done'])
const show = defineModel({ type: Boolean, default: false })

const dlg = ref(null)
const submitting = ref(false)
const error = ref('')

const r0 = computed(() => props.rows[0] || {})
const itemName = computed(() => r0.value.item_name || r0.value.production_item || '')
const uom = computed(() => r0.value.display_uom || r0.value.stock_uom || '')
const total = computed(() =>
	props.rows.reduce(
		(s, r) =>
			s + Number(r.expected_units != null ? r.expected_units : Math.round(Number(r.produced_qty || 0))),
		0,
	),
)
const title = computed(() => `Group Request (${itemName.value} · ${props.rows.length} Work Orders)`)

watch(show, (v) => {
	if (v) {
		error.value = ''
		nextTick(() => dlg.value?.showModal())
	} else {
		dlg.value?.close()
	}
})

function close() {
	dlg.value?.close()
}

function onCancel() {
	show.value = false
}

async function submit() {
	if (submitting.value) {
		return
	}
	submitting.value = true
	error.value = ''
	try {
		const res = await createGroupRequest(props.rows.map((r) => r.name))
		show.value = false
		// frappeRequest mengembalikan message endpoint langsung
		emit('done', { boxPlan: (res && res.box_plan) || '', size: props.rows.length })
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
			<p class="dlg-note">
				One request for {{ rows.length }} Work Orders of {{ itemName }}. The qty is their
				full produced output.
			</p>
			<div class="dlg-context">
				<strong>{{ fmtNum(total) }} {{ uom }}</strong>
				<span> total from {{ rows.length }} Work Orders</span>
			</div>
			<p v-if="error" class="err" role="alert">{{ error }}</p>
			<div class="dlg-actions">
				<button type="button" class="btn" @click="close">Cancel</button>
				<button
					type="button"
					class="btn btn-primary"
					:disabled="submitting"
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
