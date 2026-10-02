<script setup>
import Toast from '@frappe-ui/components/Toast/Toast.vue'
import { toasts, dismiss } from '@/lib/toast'
</script>

<template>
	<div class="pointer-events-none fixed bottom-4 right-4 z-[100] flex list-none flex-col items-end gap-2">
		<Toast
			v-for="t in toasts"
			:key="t.id"
			:open="true"
			:message="t.message"
			:type="t.type"
			:duration="t.duration"
			@update:open="dismiss(t.id)"
		/>
	</div>
</template>
