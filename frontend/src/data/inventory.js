import { callGet } from '@/lib/api'

// Lapisan data halaman Inventory (W40) — endpoint read-only
// warehouse_app.warehouse_app.inventory (SLE + Bin, paginasi server-side).
const API = 'warehouse_app.warehouse_app.inventory.'

export function fetchStockCards(params) {
	return callGet(API + 'stock_cards', params)
}

export function fetchMovements(params) {
	return callGet(API + 'movements', params)
}

export function fetchStockBalance(params) {
	return callGet(API + 'stock_balance', params)
}

export function fetchInventoryInfo(item_code, warehouse) {
	return callGet(API + 'inventory_info', { item_code, warehouse })
}

export function fetchFilterOptions() {
	return callGet(API + 'filter_options')
}

// Unduh file (xlsx/csv) dari endpoint export — fetch blob agar error server
// tampil sebagai toast, bukan halaman JSON mentah.
export async function downloadExport(params) {
	const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== ''))
	const res = await fetch('/api/method/' + API + 'export?' + qs, { credentials: 'include' })
	if (!res.ok) {
		const body = await res.json().catch(() => ({}))
		let msg = 'HTTP ' + res.status
		try {
			msg = JSON.parse(JSON.parse(body._server_messages)[0]).message
		} catch {
			msg = body.exception || msg
		}
		throw new Error(String(msg).replace(/<[^>]*>/g, ''))
	}
	const name = /filename="?([^";]+)"?/.exec(res.headers.get('Content-Disposition') || '')?.[1]
	const a = document.createElement('a')
	a.href = URL.createObjectURL(await res.blob())
	a.download = decodeURIComponent(name || 'export.' + params.file_format)
	a.click()
	URL.revokeObjectURL(a.href)
}
