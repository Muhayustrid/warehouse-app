import { callGet } from '@/lib/api'

export const STAGE_LABELS = {
	open: 'Open',
	picking: 'In Picking',
	packing: 'In Packing',
	ready: 'Ready',
	partially_delivered: 'Partially Delivered',
	exception: 'Exceptions',
}

export function stageLabel(value) {
	return STAGE_LABELS[value] || value || '—'
}

export function fetchOrderQueue(params = {}) {
	return callGet('warehouse_app.warehouse_app.fulfillment.api.get_order_queue', params)
}

export function fetchOrderPreview(salesOrder) {
	return callGet('warehouse_app.warehouse_app.fulfillment.api.get_order_preview', {
		sales_order: salesOrder,
	})
}
