import { reactive } from 'vue'

// Toast mini custom — dirender oleh Toasts.vue,
// fixed bottom-right (lihat .toastbox di gudang.css).
let seq = 0
export const toasts = reactive([])

function show(message, type = 'info', duration = 4000) {
	const id = ++seq
	toasts.push({ id, message: String(message || ''), type })
	if (duration) {
		setTimeout(() => dismiss(id), duration)
	}
	return id
}

export function dismiss(id) {
	const i = toasts.findIndex((t) => t.id === id)
	if (i >= 0) {
		toasts.splice(i, 1)
	}
}

export const toast = {
	success: (m) => show(m, 'success'),
	error: (m) => show(m, 'error', 6000),
	warning: (m) => show(m, 'warning'),
	info: (m) => show(m, 'info'),
}
