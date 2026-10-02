import { reactive } from 'vue'

// Host toast mini di atas komponen <Toast> frappe-ui (versi 0.1.278 tidak
// mengekspor renderer koleksinya dari root — ini penggantinya).
let seq = 0
export const toasts = reactive([])

function show(message, type = 'info', duration = 4000) {
	const id = ++seq
	toasts.push({ id, message: String(message || ''), type, duration })
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
