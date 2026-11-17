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

export function fetchCombinedPickListHtml(company, deliveryDate) {
	return call('warehouse_app.warehouse_app.fulfillment.api.get_combined_pick_list_html', {
		company: company || undefined,
		delivery_date: deliveryDate,
	})
}

export function fetchDeliverySummaryHtml(company, deliveryDate) {
	return call('warehouse_app.warehouse_app.fulfillment.api.get_delivery_summary_html', {
		company: company || undefined,
		delivery_date: deliveryDate,
	})
}

export function fetchManifestCandidates(company, deliveryDate) {
	return callGet('warehouse_app.warehouse_app.fulfillment.api.get_manifest_candidates', {
		company: company || undefined,
		delivery_date: deliveryDate,
	})
}

export function saveDeliveryManifest(payload) {
	return call('warehouse_app.warehouse_app.fulfillment.api.save_delivery_manifest', {
		payload: JSON.stringify(payload),
	})
}

export function fetchManifests(company, deliveryDate) {
	return callGet('warehouse_app.warehouse_app.fulfillment.api.get_manifests', {
		company: company || undefined,
		delivery_date: deliveryDate,
	})
}

export function fetchManifest(name) {
	return callGet('warehouse_app.warehouse_app.fulfillment.api.get_manifest', { name })
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

export function fetchPackingSlips(company, fromDate, toDate) {
	return callGet('warehouse_app.warehouse_app.fulfillment.api.get_packing_slips', {
		company: company || undefined,
		from_date: fromDate || undefined,
		to_date: toDate || undefined,
	})
}

export function fetchPackingSlip(name) {
	return callGet('warehouse_app.warehouse_app.fulfillment.api.get_packing_slip', { name })
}

export function savePackingSlip(name, lines, driver, vehicleNo) {
	return call('warehouse_app.warehouse_app.fulfillment.api.save_packing_slip', {
		name,
		lines: JSON.stringify(lines),
		driver: driver || '',
		vehicle_no: vehicleNo || '',
	})
}

export function fetchPackingSlipPrintHtml(name) {
	// GET: endpoint di-whitelist methods=["GET"] — POST ditolak Frappe.
	return callGet('warehouse_app.warehouse_app.fulfillment.api.get_packing_slip_print_html', { name })
}

export function fetchPackingSlipLabelsHtml(name) {
	return callGet('warehouse_app.warehouse_app.fulfillment.api.get_packing_slip_labels_html', { name })
}

// Semua label koli untuk packing slip yang sudah diinput pada `date` (per company).
export function fetchPackingSlipsLabelsHtml(company, date) {
	return callGet('warehouse_app.warehouse_app.fulfillment.api.get_packing_slips_labels_html', { company, date })
}

// Sheet gabungan satu hari (tampilan Image 2): slip + lines per SO.
export function fetchPackingSheet(company, date) {
	return callGet('warehouse_app.warehouse_app.fulfillment.api.get_packing_sheet', { company, date })
}

// Cetak Packing List gabungan (layout kertas papan klip).
export function fetchPackingSheetHtml(company, date, category) {
	return callGet('warehouse_app.warehouse_app.fulfillment.api.get_packing_sheet_html', { company, date, category })
}

// Driver + no. mobil dipakai bersama oleh semua packing pada `date`.
export function savePackingDriver(company, date, driver, vehicleNo) {
	return call('warehouse_app.warehouse_app.fulfillment.api.save_packing_driver', {
		company,
		date,
		driver: driver || '',
		vehicle_no: vehicleNo || '',
	})
}
