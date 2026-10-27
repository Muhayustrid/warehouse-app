import { call, callGet } from '@/lib/api'

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

export function generateFulfillmentRun({ salesOrder, idempotencyKey, expectedSoModified }) {
	return call('warehouse_app.warehouse_app.fulfillment.api.generate_fulfillment_run', {
		sales_order: salesOrder,
		idempotency_key: idempotencyKey,
		expected_so_modified: expectedSoModified,
	})
}
