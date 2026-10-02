<script setup>
import { computed } from 'vue'

// Pill status baris: available (WO status) / Requested / Shipped —
// semantik sama dengan indicator-pill halaman klasik.
const props = defineProps({
	row: { type: Object, required: true },
})

const state = computed(() => {
	if (props.row.request_active) return 'requested'
	if (props.row.request_shipped) return 'shipped'
	return 'available'
})

const label = computed(() => {
	if (state.value === 'requested') return 'Requested'
	if (state.value === 'shipped') return 'Shipped'
	return props.row.status || ''
})

const mr = computed(() => props.row.custom_handover_material_request || '')
</script>

<template>
	<span
		class="inline-flex max-w-full items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium"
		:class="{
			'bg-surface-gray-3 text-ink-gray-6': state === 'available',
			'bg-orange-100 text-orange-800 dark:bg-orange-500/15 dark:text-orange-300':
				state === 'requested',
			'bg-green-100 text-green-800 dark:bg-green-500/15 dark:text-green-300':
				state === 'shipped',
		}"
	>
		<span
			class="h-1.5 w-1.5 shrink-0 rounded-full"
			:class="{
				'bg-ink-gray-4': state === 'available',
				'bg-orange-500': state === 'requested',
				'bg-green-500': state === 'shipped',
			}"
		/>
		<span>{{ label }}</span>
		<template v-if="mr">
			<span class="opacity-50">·</span>
			<a
				:href="`/app/material-request/${encodeURIComponent(mr)}`"
				target="_blank"
				class="underline decoration-transparent underline-offset-2 hover:decoration-current"
				>{{ mr }}</a
			>
		</template>
		<span v-if="row.box_plan" class="text-ink-gray-5">
			· Group ({{ row.group_size || 0 }} WO)</span
		>
	</span>
</template>
