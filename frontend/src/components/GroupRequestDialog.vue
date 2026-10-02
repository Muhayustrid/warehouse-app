<script setup>
// Dialog Group Request (N WO satu item grup, satu paket box bersama) —
// tanpa input: total = hasil penuh semua anggota; server membentuk Handover
// Box Plan-nya sendiri. Server menolak → dialog tetap terbuka dgn error.
import { ref, computed, watch } from 'vue'
import { Dialog } from '@frappe-ui/components/Dialog'
import { Button } from '@frappe-ui/components/Button'
import { createGroupRequest } from '@/data/board'
import { fmtNum } from '@/lib/format'

const props = defineProps({
	rows: { type: Array, required: true }, // anggota grup (≥2, satu item grup)
})
const emit = defineEmits(['done'])
const show = defineModel({ type: Boolean, default: false })

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
	}
})

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
	<Dialog v-model="show" :options="{ title, size: 'lg' }">
		<template #body-content>
			<p class="text-sm text-ink-gray-5">
				One request for {{ rows.length }} Work Orders of {{ itemName }}. The qty is their
				full produced output.
			</p>
			<p class="mt-3 text-sm">
				<b class="text-ink-gray-8">{{ fmtNum(total) }} {{ uom }}</b>
				<span class="text-ink-gray-5"> total from {{ rows.length }} Work Orders</span>
			</p>
			<p
				v-if="error"
				class="mt-3 rounded-md bg-surface-red-1 p-2.5 text-sm text-ink-red-4"
			>
				{{ error }}
			</p>
		</template>
		<template #actions>
			<Button variant="subtle" label="Cancel" @click="show = false" />
			<Button
				variant="solid"
				label="Create Group Request"
				:loading="submitting"
				@click="submit"
			/>
		</template>
	</Dialog>
</template>
