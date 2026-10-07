import { call, callGet } from '@/lib/api'
import { toast } from '@/lib/toast'

// Lapisan data halaman Inventory (W40) — endpoint read-only
// warehouse_app.warehouse_app.inventory (SLE + Bin, paginasi server-side).
const API = 'warehouse_app.warehouse_app.inventory.'

export function fetchStockCards(params) {
	return callGet(API + 'stock_cards', params)
}

export function fetchMovements(params) {
	return callGet(API + 'movements', params)
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

export function recalculate(params) {
	return call(API + 'recalculate', params)
}

// Pantau Repost Item Valuation sampai tak ada yang Queued/In Progress,
// lalu kembalikan peta status akhir.
export async function waitRecalculate(names, every = 4000) {
	for (;;) {
		await new Promise((r) => setTimeout(r, every))
		const st = (await callGet(API + 'recalculate_status', { names: JSON.stringify(names) })) || {}
		if (!Object.values(st).some((s) => s === 'Queued' || s === 'In Progress')) return st
	}
}

// Alur Recalculate bersama (tab Movements + modal): buat RIV, toast info,
// tunggu selesai, toast hasil, lalu onDone (muat ulang tabel).
export async function runRecalculate(params, onDone) {
	let names
	try {
		names = await recalculate(params)
	} catch (e) {
		toast.error(e.message)
		return
	}
	toast.info(`Recalculating ${names.length} item/warehouse… you'll be notified when it's done.`)
	const st = await waitRecalculate(names).catch(() => ({}))
	const failed = Object.values(st).filter((s) => s === 'Failed').length
	if (failed) toast.error(`Recalculate finished with ${failed} failed repost(s) — see Repost Item Valuation.`)
	else toast.success(`Recalculate completed (${names.length} item/warehouse).`)
	onDone?.()
}
