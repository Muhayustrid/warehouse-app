<script setup>
// Dialog konfirmasi generik — pengganti frappe.confirm (cancel request /
// cancel group request).
import { Dialog } from '@frappe-ui/components/Dialog'
import { Button } from '@frappe-ui/components/Button'

const props = defineProps({
	options: { type: Object, required: true }, // { title, message, confirmLabel, theme }
	onConfirm: { type: Function, required: true },
})
const show = defineModel({ type: Boolean, default: false })

async function onPrimary() {
	props.onConfirm()
	show.value = false
}
</script>

<template>
	<Dialog v-model="show" :options="{ title: options.title, size: 'sm' }">
		<template #body-content>
			<p class="text-sm leading-relaxed text-ink-gray-6">{{ options.message }}</p>
		</template>
		<template #actions>
			<Button variant="subtle" label="Cancel" @click="show = false" />
			<Button
				variant="solid"
				:theme="options.theme === 'danger' ? 'red' : 'gray'"
				:label="options.confirmLabel || 'Confirm'"
				@click="onPrimary"
			/>
		</template>
	</Dialog>
</template>
