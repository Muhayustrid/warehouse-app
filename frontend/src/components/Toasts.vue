<script setup>
import Toast from '@frappe-ui/components/Toast/Toast.vue'
// Toast frappe-ui = ToastRoot reka-ui: wajib di dalam ToastProvider, tanpa
// itu setiap toast melempar 'Injection ToastProviderContext not found'.
// ToastRoot di-teleport ke ToastViewport — tanpa viewport toast tak tampil.
import { ToastProvider, ToastViewport } from 'reka-ui'
import { toasts, dismiss } from '@/lib/toast'
</script>

<template>
	<ToastProvider>
		<Toast
			v-for="t in toasts"
			:key="t.id"
			:open="true"
			:message="t.message"
			:type="t.type"
			:duration="t.duration"
			@update:open="dismiss(t.id)"
		/>
		<ToastViewport class="pointer-events-none fixed bottom-4 right-4 z-[1300] flex list-none flex-col items-end gap-2 outline-none" />
	</ToastProvider>
</template>
