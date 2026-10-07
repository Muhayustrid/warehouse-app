import { callGet } from '@/lib/api'

// Lapisan data halaman Inventory (W40) — endpoint read-only
// warehouse_app.warehouse_app.inventory (SLE + Bin, paginasi server-side).
const API = 'warehouse_app.warehouse_app.inventory.'

export function fetchStockCards(params) {
	return callGet(API + 'stock_cards', params)
}

export function fetchFilterOptions() {
	return callGet(API + 'filter_options')
}
