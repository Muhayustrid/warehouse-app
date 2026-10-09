import { call, callGet } from '@/lib/api'

// Lapisan data papan serah terima — endpoint SAMA dengan halaman klasik,
// tidak ada perubahan server (warehouse_app + production_app).

export async function fetchWorkOrders({ search = '', filters = [], limitStart = 0, pageLen = 50 } = {}) {
	return call('warehouse_app.warehouse_app.gudang_request.requestable_work_orders', {
		search,
		filters: JSON.stringify(filters || []),
		limit_start: limitStart,
		limit_page_length: pageLen,
		paginated: 1,
	})
}

export async function fetchFilterFields() {
	return callGet('warehouse_app.warehouse_app.gudang_request.filter_fields')
}

export function createRequest(workOrder) {
	return call('production_app.api.handover.create_request', { work_order: workOrder })
}

export function cancelRequest(materialRequest) {
	return call('production_app.api.handover.cancel_request', { material_request: materialRequest })
}

export function createGroupRequest(workOrders) {
	return call('production_app.api.handover.create_group_request', {
		work_orders: JSON.stringify(workOrders),
	})
}

export function cancelGroupRequest(boxPlan) {
	return call('production_app.api.handover.cancel_group_request', { box_plan: boxPlan })
}
