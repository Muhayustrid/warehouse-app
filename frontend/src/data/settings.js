import { call, callGet } from '@/lib/api'

export async function fetchWarehouseOptions() {
	return callGet('warehouse_app.warehouse_app.gudang_settings.warehouse_options')
}

export async function fetchHandoverSettings() {
	return call('warehouse_app.warehouse_app.gudang_settings.get_handover_settings')
}

export function saveHandoverWarehouses(source, target) {
	return call('warehouse_app.warehouse_app.gudang_settings.set_handover_warehouses', {
		source: source || '',
		target: target || '',
	})
}

export async function fetchGroupItems() {
	return call('warehouse_app.warehouse_app.gudang_settings.get_group_items')
}

export function saveGroupItems(items) {
	return call('warehouse_app.warehouse_app.gudang_settings.set_group_items', { items })
}

// Pencarian item untuk input Add — endpoint pencarian standar Desk.
export async function searchItems(txt) {
	const res = await callGet('frappe.desk.search.search_link', {
		txt,
		doctype: 'Item',
	})
	return (res || []).map((r) => ({ label: r.description || r.value, value: r.value }))
}

export async function fetchItemName(item) {
	const res = await callGet('frappe.client.get_value', {
		doctype: 'Item',
		filters: JSON.stringify({ name: item }),
		fieldname: 'item_name',
	})
	return (res && res.message && res.message.item_name) || item
}
