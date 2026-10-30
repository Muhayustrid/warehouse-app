import { call, callGet } from '@/lib/api'

export const STAGE_LABELS = {
	open: 'Open',
	picking: 'In Picking',
	packing: 'In Packing',
	ready: 'Ready',
	partially_delivered: 'Partially Delivered',
	completed: 'Completed',
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

export function fetchRunWorkspace(run) {
	return callGet('warehouse_app.warehouse_app.fulfillment.api.get_run_workspace', {
		run,
	})
}

export function savePicking(run, rows, expectedModified) {
	return call('warehouse_app.warehouse_app.fulfillment.api.save_picking', {
		run,
		rows: typeof rows === 'string' ? rows : JSON.stringify(rows ?? []),
		expected_modified:
			typeof expectedModified === 'string'
				? expectedModified
				: JSON.stringify(expectedModified ?? {}),
	})
}

export function requestShortPickApproval(run, reason) {
	return call('warehouse_app.warehouse_app.fulfillment.api.request_short_pick_approval', {
		run,
		reason,
	})
}

export function approveShortPick(run, expectedFingerprint) {
	return call('warehouse_app.warehouse_app.fulfillment.api.approve_short_pick', {
		run,
		expected_fingerprint: expectedFingerprint,
	})
}

export function rejectShortPick(run, reason) {
	return call('warehouse_app.warehouse_app.fulfillment.api.reject_short_pick', {
		run,
		reason,
	})
}

export function completePicking(run, expectedModified, shortPickReason = null) {
	return call('warehouse_app.warehouse_app.fulfillment.api.complete_picking', {
		run,
		expected_modified:
			typeof expectedModified === 'string'
				? expectedModified
				: JSON.stringify(expectedModified ?? {}),
		short_pick_reason: shortPickReason,
	})
}

export function createDeliveryNote(run, idempotencyKey, options = {}) {
	return call('warehouse_app.warehouse_app.fulfillment.api.create_delivery_note', {
		run,
		idempotency_key: idempotencyKey,
		dry_packages: options.dryPackages,
		frozen_packages: options.frozenPackages,
	})
}

export function updateDeliveryPackages(run, dryPackages, frozenPackages) {
	return call('warehouse_app.warehouse_app.fulfillment.api.update_delivery_packages', {
		run,
		dry_packages: dryPackages,
		frozen_packages: frozenPackages,
	})
}

export function packAll(run, expectedDnModified, options = {}) {
	return call('warehouse_app.warehouse_app.fulfillment.api.pack_all', {
		run,
		expected_dn_modified: expectedDnModified,
		dry_packages: options.dryPackages,
		frozen_packages: options.frozenPackages,
		custom_slips: options.customSlips ? JSON.stringify(options.customSlips) : undefined,
	})
}

export function resetPacking(run, expectedDnModified) {
	return call('warehouse_app.warehouse_app.fulfillment.api.reset_packing', {
		run,
		expected_dn_modified: expectedDnModified,
	})
}

export function submitDeliveryNote(run, idempotencyKey, expectedDnModified) {
	return call('warehouse_app.warehouse_app.fulfillment.api.submit_delivery_note', {
		run,
		idempotency_key: idempotencyKey,
		expected_dn_modified: expectedDnModified,
	})
}

export function fetchPackingSlipsPrintHtml(deliveryNote) {
	return call('warehouse_app.warehouse_app.fulfillment.api.get_packing_slips_print_html', {
		delivery_note: deliveryNote,
	})
}
