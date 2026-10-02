import { call, callGet } from '@/lib/api'

// Lapisan data halaman Serah Terima Gudang (W33-r8). Sumber data TETAP report
// standar "Serah Terima Gudang" via query_report.run, dan pembuatan SE tetap
// lewat mapper native erpnext (make_stock_entry) — endpoint yang sama dengan
// tombol Desk (open_mapped_doc). Nol endpoint baru di server.

export function fetchSerahTerima(filters = {}) {
	return call('frappe.desk.query_report.run', {
		report_name: 'Serah Terima Gudang',
		filters: JSON.stringify(filters),
	})
}

export function fetchWarehouses() {
	return callGet('frappe.client.get_list', {
		doctype: 'Warehouse',
		fields: JSON.stringify(['name']),
		filters: JSON.stringify({ is_group: 0 }),
		limit_page_length: 0,
		order_by: 'name',
	})
}

// Cari warehouse by nama (site produksi punya 600+ gudang per-outlet —
// dropdown tak mungkin memuat semua; diketik → dicari server-side).
export function searchWarehouses(query) {
	return callGet('frappe.client.get_list', {
		doctype: 'Warehouse',
		fields: JSON.stringify(['name']),
		filters: JSON.stringify({ is_group: 0, name: ['like', `%${query}%`] }),
		limit_page_length: 20,
		order_by: 'name',
	})
}

// Mapper native yang sama dengan tombol Desk (open_mapped_doc). Bedanya,
// hasil mapper Desk hanya hidup di memori halaman asal (set_route internal)
// — tak bisa dibuka dari tab baru. Karena itu DRAFT SE disimpan dulu lewat
// frappe.client.insert (endpoint native; validasi SE tetap penuh), lalu form
// review dibuka di tab Desk; dokumen yatim bisa dihapus dari form.
export async function makeStockEntry(materialRequest) {
	const mapped = await call('frappe.model.mapper.make_mapped_doc', {
		method: 'erpnext.stock.doctype.material_request.material_request.make_stock_entry',
		source_name: materialRequest,
	})
	// v16: message = dokumen hasil mapper langsung (tanpa pembungkus docs)
	const doc = mapped?.docs || mapped
	if (!doc || !doc.doctype) {
		throw new Error('Mapper did not return a document')
	}
	const saved = await call('frappe.client.insert', { doc: JSON.stringify(doc) })
	return saved?.data || saved
}
