<script setup>
// Menu Display: pemilih kolom tabel + kepadatan baris (persist di prefs).
// Popover di-rolled sendiri — reka Popover tak terbuka utk komponen ini
// (FilterBuilder jalan, ini tidak; pola manual lebih deterministik).
import { ref, onMounted, onUnmounted } from 'vue'
import { Button } from '@frappe-ui/components/Button'
import { Checkbox } from '@frappe-ui/components/Checkbox'
import { TabButtons } from '@frappe-ui/components/TabButtons'

defineProps({
	columns: { type: Array, required: true }, // [{key,label}]
})
const visible = defineModel('visible', { type: Array, required: true })
const density = defineModel('density', { type: String, required: true })

const open = ref(false)
const root = ref(null)

function onDocClick(e) {
	if (open.value && root.value && !root.value.contains(e.target)) {
		open.value = false
	}
}
function onKey(e) {
	if (e.key === 'Escape') {
		open.value = false
	}
}
onMounted(() => {
	document.addEventListener('click', onDocClick)
	document.addEventListener('keydown', onKey)
})
onUnmounted(() => {
	document.removeEventListener('click', onDocClick)
	document.removeEventListener('keydown', onKey)
})

function toggleColumn(key, checked) {
	const set = new Set(visible.value)
	if (checked) {
		set.add(key)
	} else {
		set.delete(key)
	}
	visible.value = [...set]
}
</script>

<template>
	<div ref="root" class="relative">
		<Button
			variant="subtle"
			label="Display"
			icon-left="sliders"
			@click="open = !open"
		/>
		<div
			v-if="open"
			class="absolute right-0 top-full z-50 mt-1 w-56 rounded-lg border border-outline-gray-2 bg-surface-modal p-2 shadow-xl"
		>
			<p class="px-1.5 pb-1 pt-0.5 text-xs font-semibold text-ink-gray-5">Columns</p>
			<div class="space-y-0.5">
				<div v-for="c in columns" :key="c.key" class="flex items-center px-1.5 py-1">
					<Checkbox
						:label="c.label"
						:model-value="visible.includes(c.key)"
						@update:model-value="(v) => toggleColumn(c.key, v)"
					/>
				</div>
			</div>
			<div class="my-2 border-t border-outline-gray-1" />
			<p class="px-1.5 pb-1.5 text-xs font-semibold text-ink-gray-5">Density</p>
			<div class="px-1.5 pb-1">
				<TabButtons
					:buttons="[
						{ label: 'Comfort', value: 'comfort' },
						{ label: 'Compact', value: 'compact' },
					]"
					v-model="density"
				/>
			</div>
		</div>
	</div>
</template>
