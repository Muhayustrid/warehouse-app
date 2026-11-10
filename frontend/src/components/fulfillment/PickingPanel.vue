<script setup>
import { computed, ref, watch } from 'vue'
import {
	AlertTriangle,
	ArrowRight,
	Check,
	CheckCircle2,
	Clock,
	ExternalLink,
	Printer,
	Save,
	X,
} from 'lucide-vue-next'
import { fmtQty } from '@/lib/format'
import { toast } from '@/lib/toast'

const ACTION_REASONS = {
	SHORT_PICK_BLOCKED: 'Short pick is blocked by policy.',
	SHORT_PICK_APPROVAL_PENDING: 'Waiting for short-pick approval.',
	SHORT_PICK_APPROVAL_REJECTED: 'Short pick request was rejected.',
	SHORT_PICK_STALE_APPROVAL: 'Pick quantities changed since approval.',
}

const props = defineProps({
	workspace: { type: Object, required: true },
	busy: { type: Boolean, default: false },
})

const emit = defineEmits([
	'refresh',
	'pick-all',
	'save-picking',
	'finish-picking',
	'request-approval',
	'approve-short-pick',
	'reject-short-pick',
	'print',
	'go-delivery',
])

const pickedQtys = ref({})
const approvalReason = ref('')

const groups = computed(() => {
	const list = []
	if (props.workspace?.groups?.dry?.pick_list) {
		list.push({
			key: 'dry',
			displayName: props.workspace.profile?.dry_display_name || 'Dry',
			formatKey: 'dry_print_format',
			...props.workspace.groups.dry,
		})
	}
	if (props.workspace?.groups?.frozen?.pick_list) {
		list.push({
			key: 'frozen',
			displayName: props.workspace.profile?.frozen_display_name || 'Frozen',
			formatKey: 'frozen_print_format',
			...props.workspace.groups.frozen,
		})
	}
	return list
})

const draftGroups = computed(() => groups.value.filter((g) => g.docstatus === 0))

const draftRows = computed(() => {
	const rows = []
	for (const grp of draftGroups.value) {
		for (const row of grp.rows || []) {
			rows.push({ ...row, groupPickList: grp.pick_list })
		}
	}
	return rows
})

const hasDraftPl = computed(() => draftGroups.value.length > 0)

watch(
	() => props.workspace,
	(ws) => {
		if (!ws) return
		const next = {}
		for (const grp of [ws.groups?.dry, ws.groups?.frozen]) {
			if (!grp?.pick_list) continue
			for (const row of grp.rows || []) {
				const val =
					row.custom_picked_qty && Number(row.custom_picked_qty) > 0
						? Number(row.custom_picked_qty)
						: row.picked_qty && Number(row.picked_qty) > 0
							? Number(row.picked_qty)
							: Number(row.qty)
				next[row.name] = val
			}
		}
		pickedQtys.value = next
	},
	{ immediate: true, deep: true },
)

function onQtyInput(row, rawVal) {
	pickedQtys.value[row.name] = rawVal
}

function getRowError(row) {
	const val = pickedQtys.value[row.name]
	if (val === '' || val === null || val === undefined) {
		return 'Enter a positive quantity. Zero is not supported.'
	}
	const num = Number(val)
	if (isNaN(num) || num <= 0) {
		return 'Enter a positive quantity. Zero is not supported.'
	}
	if (num - Number(row.qty) > 0.0001) {
		return `Exceeds target quantity (${fmtQty(row.qty)}).`
	}
	return ''
}

function isRowInvalid(row) {
	return Boolean(getRowError(row))
}

function getRowStatus(row) {
	const val = pickedQtys.value[row.name]
	if (val === '' || val === null || val === undefined) {
		return { label: 'Invalid', class: 'pill-invalid' }
	}
	const num = Number(val)
	if (isNaN(num) || num <= 0) {
		return { label: 'Invalid', class: 'pill-invalid' }
	}
	if (num >= Number(row.qty) - 0.0001) {
		return { label: '✓ Sesuai', class: 'pill-full' }
	}
	return { label: 'Kurang', class: 'pill-short' }
}

const isAllFull = computed(() => {
	if (draftRows.value.length === 0) return false
	return draftRows.value.every((row) => {
		const val = Number(pickedQtys.value[row.name])
		return !isNaN(val) && val >= Number(row.qty) - 0.0001
	})
})

function setAllToTarget() {
	for (const row of draftRows.value) {
		pickedQtys.value[row.name] = Number(row.qty)
	}
}

const hasInvalidRows = computed(() => {
	return draftRows.value.some((row) => isRowInvalid(row))
})

const hasUnsavedChanges = computed(() => {
	return draftRows.value.some((row) => {
		const currentVal = Number(pickedQtys.value[row.name])
		const serverVal =
			row.custom_picked_qty && Number(row.custom_picked_qty) > 0
				? Number(row.custom_picked_qty)
				: null
		if (serverVal === null) return true
		return Math.abs(currentVal - serverVal) > 0.0001
	})
})

const shortItemsList = computed(() => {
	const list = []
	for (const row of draftRows.value) {
		const picked = Number(pickedQtys.value[row.name] || 0)
		const target = Number(row.qty || 0)
		if (picked < target) {
			list.push({
				name: row.name,
				item_code: row.item_code,
				item_name: row.item_name || row.item_code,
				target,
				picked,
				shortQty: Math.max(0, target - picked),
				uom: row.uom || 'Pcs',
			})
		}
	}
	return list
})

const showShortPickModal = ref(false)
const shortPickReasonInput = ref('Stok fisik di gudang tidak mencukupi')

const allDraftRowsSaved = computed(() => {
	if (draftRows.value.length === 0) return false
	return !hasUnsavedChanges.value && !hasInvalidRows.value
})

const finishDisabledReason = computed(() => {
	if (props.busy) return 'Operasi sedang berlangsung...'
	if (!hasDraftPl.value) return 'Tidak ada Pick List draf untuk diselesaikan.'
	if (hasInvalidRows.value) return 'Masukkan kuantitas valid (lebih dari 0).'
	return ''
})

function onPrint(group) {
	const format = props.workspace?.profile?.[group.formatKey]
	if (!format || !String(format).trim()) {
		toast.warning('Print format is not configured.')
		return
	}
	const url = `/printview?doctype=Pick List&name=${encodeURIComponent(group.pick_list)}&format=${encodeURIComponent(format)}`
	window.open(url, '_blank', 'noopener')
	emit('print', { group: group.key, pick_list: group.pick_list, format })
}

function onSavePicking() {
	if (props.busy || !hasDraftPl.value || hasInvalidRows.value) return
	const rows = []
	const expectedModified = {}
	for (const grp of draftGroups.value) {
		expectedModified[grp.pick_list] = grp.modified
		for (const row of grp.rows || []) {
			rows.push({
				pick_list: grp.pick_list,
				row: row.name,
				picked_qty: Number(pickedQtys.value[row.name]),
			})
		}
	}
	emit('save-picking', { rows, expected_modified: expectedModified })
}

function onFinishPicking() {
	if (props.busy) return
	if (hasInvalidRows.value) {
		toast.warning('Masukkan kuantitas valid (lebih dari 0).')
		return
	}
	if (shortItemsList.value.length > 0) {
		shortPickReasonInput.value =
			props.workspace?.run?.short_pick_reason || 'Stok fisik di gudang tidak mencukupi'
		showShortPickModal.value = true
		return
	}

	const rows = []
	const expectedModified = {}
	for (const grp of draftGroups.value) {
		expectedModified[grp.pick_list] = grp.modified
		for (const row of grp.rows || []) {
			rows.push({
				pick_list: grp.pick_list,
				row: row.name,
				picked_qty: Number(pickedQtys.value[row.name]),
			})
		}
	}
	emit('finish-picking', { rows, expected_modified: expectedModified })
}

function confirmShortPickFinish() {
	showShortPickModal.value = false
	const rows = []
	const expectedModified = {}
	for (const grp of draftGroups.value) {
		expectedModified[grp.pick_list] = grp.modified
		for (const row of grp.rows || []) {
			rows.push({
				pick_list: grp.pick_list,
				row: row.name,
				picked_qty: Number(pickedQtys.value[row.name]),
			})
		}
	}
	emit('finish-picking', {
		rows,
		expected_modified: expectedModified,
		short_pick_reason: shortPickReasonInput.value.trim() || 'Stok fisik di gudang tidak mencukupi',
	})
}

function onRequestApproval() {
	const reason = approvalReason.value.trim()
	if (!reason) {
		toast.warning('Reason is required to request short-pick approval.')
		return
	}
	emit('request-approval', reason)
	approvalReason.value = ''
}

function onApprove() {
	const fp = props.workspace?.short_pick?.fingerprint
	emit('approve-short-pick', fp)
}

function onReject() {
	const reason = window.prompt('Enter rejection reason:')
	if (reason === null) {
		return
	}
	if (!reason.trim()) {
		toast.warning('Rejection reason is required.')
		return
	}
	emit('reject-short-pick', reason.trim())
}

defineExpose({
	hasUnsavedChanges,
	onSavePicking,
	onFinishPicking,
})
</script>

<template>
	<div class="picking-panel">
		<!-- Empty state if no pick lists -->
		<div v-if="groups.length === 0" class="panel empty-inset">
			<div class="eico">
				<AlertTriangle :size="20" :stroke-width="1.8" />
			</div>
			<div class="etitle">No Pick Lists found</div>
			<div class="ehint">Pick Lists have not been generated for this fulfillment run.</div>
		</div>

		<!-- Short-pick Banner -->
		<div
			v-if="shortItemsList.length > 0 || workspace.short_pick?.rows?.length > 0"
			class="short-banner"
			:class="workspace.run?.short_pick_status === 'Approved' ? 'short-banner-approved' : 'short-banner-pending'"
			role="region"
			aria-label="Pemberitahuan Stok Kurang"
		>
			<template v-if="workspace.run?.short_pick_status === 'Approved'">
				<CheckCircle2 :size="18" :stroke-width="2" class="banner-icon" />
				<div class="banner-body">
					<div class="banner-headline">
						<strong>Kekurangan stok telah dikonfirmasi (Short Pick).</strong>
						<span class="badge b-done">Approved</span>
					</div>
					<p v-if="workspace.run?.short_pick_reason" class="banner-sub">
						Keterangan: {{ workspace.run.short_pick_reason }}
					</p>
				</div>
			</template>
			<template v-else>
				<AlertTriangle :size="18" :stroke-width="2" class="banner-icon" />
				<div class="banner-body">
					<strong>Terdapat barang yang diambil kurang dari target (Stok Kurang).</strong>
					<p class="banner-sub">
						Klik <strong>"Selesaikan Picking"</strong> di bawah untuk memeriksa rincian kekurangan dan mengonfirmasi catatan stok kurang.
					</p>
				</div>
			</template>
		</div>

		<!-- Group Cards -->
		<div
			v-for="group in groups"
			:key="group.key"
			class="panel group-panel"
		>
			<!-- Group Header -->
			<div class="panel-head group-head">
				<div class="group-title-col">
					<span class="ws-pill" :class="group.key === 'dry' ? 'ws-dry' : 'ws-frozen'">
						{{ group.displayName }}
					</span>
					<a
						class="pl-link"
						:href="`/app/pick-list/${encodeURIComponent(group.pick_list)}`"
						target="_blank"
						rel="noopener"
						title="Open Pick List in Desk"
					>
						{{ group.pick_list }}
						<ExternalLink :size="13" :stroke-width="2" />
					</a>
				</div>

				<div class="group-meta-col">
					<span class="badge" :class="group.docstatus === 1 ? 'b-done' : 'b-draft'">
						{{ group.docstatus === 1 ? 'Submitted' : 'Draft' }}
					</span>
				</div>
			</div>

			<!-- Location Rows Table -->
			<div class="table-wrap">
				<table class="pl-table">
					<thead>
						<tr>
							<th class="th-item">Item</th>
							<th class="th-wh">Warehouse</th>
							<th class="th-qty">Target Qty</th>
							<th class="th-picked">Picked Qty</th>
							<th class="th-batch">Batch / Serial</th>
							<th class="th-status">Status</th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="row in group.rows"
							:key="row.name"
							:class="{ 'row-short': getRowStatus(row).label === 'Short' }"
						>
							<!-- Item Code & Name -->
							<td class="td-item">
								<div class="item-code">{{ row.item_code }}</div>
								<div v-if="row.item_name && row.item_name !== row.item_code" class="item-name">
									{{ row.item_name }}
								</div>
							</td>

							<!-- Warehouse -->
							<td class="td-wh">
								<span class="wh-text">{{ row.warehouse }}</span>
							</td>

							<!-- Target Qty & UOM -->
							<td class="td-qty">
								<span class="qty-val">{{ fmtQty(row.qty) }}</span>
								<span class="uom-val">{{ row.uom }}</span>
							</td>

							<!-- Picked Qty Input & Validation Error -->
							<td class="td-picked">
								<div class="picked-input-wrap">
									<input
										type="number"
										step="any"
										min="0"
										:max="row.qty"
										class="input input-sm pick-input"
										:class="{ 'is-invalid': isRowInvalid(row) }"
										:value="pickedQtys[row.name]"
										:disabled="group.docstatus === 1 || busy"
										@input="onQtyInput(row, $event.target.value)"
									/>
									<span class="input-uom">{{ row.uom }}</span>
								</div>
								<div v-if="isRowInvalid(row)" class="field-error">
									{{ getRowError(row) }}
								</div>
							</td>

							<!-- Batch / Serial Hint -->
							<td class="td-batch">
								<span class="batch-hint">{{ row.batch_no || row.serial_and_batch_bundle || '—' }}</span>
							</td>

							<!-- Row Status Pill -->
							<td class="td-status">
								<span class="row-pill" :class="getRowStatus(row).class">
									{{ getRowStatus(row).label }}
								</span>
							</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>

		<!-- Action Footer -->
		<div v-if="groups.length > 0" class="panel-foot picking-footer">
			<div class="footer-left">
				<span v-if="hasUnsavedChanges" class="status-tip tip-unsaved">
					You have unsaved quantity changes.
				</span>
				<span v-else-if="allDraftRowsSaved" class="status-tip tip-saved">
					All draft rows saved.
				</span>
			</div>

			<div class="footer-actions">
				<!-- Reset / Quick full pick button if user edited a row to be short -->
				<button
					v-if="hasDraftPl && !isAllFull"
					type="button"
					class="btn btn-outline"
					:disabled="busy"
					title="Kembalikan semua kuantitas ke target 100%"
					@click="setAllToTarget"
				>
					<span>Set Semua Penuh (100%)</span>
				</button>

				<!-- 1-Click Pick All: Happy Path (99% of normal operations) -->
				<button
					v-if="hasDraftPl && isAllFull"
					type="button"
					class="btn btn-primary btn-pick-all"
					:disabled="busy || hasInvalidRows"
					title="Simpan kuantitas penuh dan selesaikan picking dalam 1 klik tanpa harus input manual"
					@click="$emit('pick-all')"
				>
					<CheckCircle2 :size="15" :stroke-width="2.2" />
					<span>Selesaikan Picking (Ambil Lengkap)</span>
				</button>

				<template v-else-if="hasDraftPl">
					<button
						type="button"
						class="btn btn-outline"
						:disabled="busy || hasInvalidRows"
						title="Simpan kuantitas sementara"
						@click="onSavePicking"
					>
						<Save :size="14" :stroke-width="2" />
						<span>Simpan Draf Qty</span>
					</button>

					<button
						type="button"
						class="btn btn-primary"
						:disabled="busy || Boolean(finishDisabledReason)"
						title="Selesaikan picking dan konfirmasi catatan stok kurang"
						@click="onFinishPicking"
					>
						<Check :size="14" :stroke-width="2" />
						<span>Selesaikan Picking</span>
					</button>
				</template>

				<button
					v-else-if="allPlSubmitted"
					type="button"
					class="btn btn-primary"
					@click="$emit('go-delivery')"
				>
					<span>Lanjut ke Surat Jalan</span>
					<ArrowRight :size="14" :stroke-width="2" />
				</button>
			</div>
		</div>

		<!-- Short Pick Confirmation Modal -->
		<Teleport to="body">
			<div v-if="showShortPickModal" class="sp-modal-overlay" @click.self="showShortPickModal = false">
				<div class="sp-modal-card" role="dialog" aria-modal="true" aria-labelledby="sp-modal-title">
					<div class="sp-modal-head">
						<div class="sp-icon-wrap">
							<AlertTriangle :size="20" :stroke-width="2" />
						</div>
						<div class="sp-head-text">
							<h3 id="sp-modal-title">Konfirmasi Barang Kurang (Stok Kurang)</h3>
							<p class="sp-sub">
								Terdapat {{ shortItemsList.length }} barang yang diambil kurang dari target yang diminta pada Pick List.
							</p>
						</div>
						<button
							type="button"
							class="sp-close-btn"
							aria-label="Tutup"
							@click="showShortPickModal = false"
						>
							<X :size="18" :stroke-width="2" />
						</button>
					</div>

					<div class="sp-modal-body">
						<!-- Table of short items -->
						<div class="sp-table-wrap">
							<table class="sp-table">
								<thead>
									<tr>
										<th>Item</th>
										<th class="text-right">Diminta</th>
										<th class="text-right">Diambil</th>
										<th class="text-right">Kurang</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="it in shortItemsList" :key="it.name">
										<td>
											<div class="it-name font-semibold">{{ it.item_name }}</div>
											<div class="it-code text-muted text-xs mono">{{ it.item_code }}</div>
										</td>
										<td class="text-right mono font-medium">
											{{ fmtQty(it.target) }} <span class="text-xs text-muted">{{ it.uom }}</span>
										</td>
										<td class="text-right mono font-bold text-amber-700">
											{{ fmtQty(it.picked) }} <span class="text-xs text-muted">{{ it.uom }}</span>
										</td>
										<td class="text-right">
											<span class="sp-badge-short">
												-{{ fmtQty(it.shortQty) }} {{ it.uom }}
											</span>
										</td>
									</tr>
								</tbody>
							</table>
						</div>

						<!-- Keterangan / Alasan -->
						<div class="sp-reason-field">
							<label for="sp-reason-input" class="sp-label">
								<span>Keterangan Stok Kurang</span>
								<span class="text-muted text-xs">(Tercatat pada dokumen)</span>
							</label>
							<textarea
								id="sp-reason-input"
								v-model="shortPickReasonInput"
								rows="2"
								class="sp-textarea"
								placeholder="Contoh: Stok fisik di rak gudang tidak mencukupi..."
							></textarea>
						</div>
					</div>

					<div class="sp-modal-foot">
						<button type="button" class="btn btn-outline" @click="showShortPickModal = false">
							Cek Kembali
						</button>
						<button
							type="button"
							class="btn btn-primary btn-confirm-short"
							:disabled="busy"
							@click="confirmShortPickFinish"
						>
							<CheckCircle2 :size="15" :stroke-width="2.2" />
							<span>Lanjutkan dengan Stok Kurang</span>
						</button>
					</div>
				</div>
			</div>
		</Teleport>
	</div>
</template>

<style scoped>
.picking-panel {
	display: flex;
	flex-direction: column;
	gap: 16px;
}

/* ---- Short Pick Confirmation Modal ---- */
.sp-modal-overlay {
	position: fixed;
	inset: 0;
	background: rgba(15, 23, 42, 0.55);
	backdrop-filter: blur(3px);
	display: grid;
	place-items: center;
	z-index: 9999;
	padding: 16px;
}

.sp-modal-card {
	background: #ffffff;
	border-radius: 12px;
	box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
	width: 100%;
	max-width: 560px;
	overflow: hidden;
	display: flex;
	flex-direction: column;
	border: 1px solid var(--line, #e2e8f0);
}

.sp-modal-head {
	display: flex;
	align-items: flex-start;
	gap: 12px;
	padding: 18px 20px 14px;
	border-bottom: 1px solid var(--line, #e2e8f0);
	background: #fffbeb;
}

.sp-icon-wrap {
	width: 36px;
	height: 36px;
	border-radius: 8px;
	background: #fef3c7;
	color: #d97706;
	display: grid;
	place-items: center;
	flex-shrink: 0;
}

.sp-head-text h3 {
	margin: 0 0 2px 0;
	font-size: 16px;
	font-weight: 700;
	color: #92400e;
}

.sp-sub {
	margin: 0;
	font-size: 13px;
	color: #b45309;
	line-height: 1.4;
}

.sp-close-btn {
	margin-left: auto;
	background: transparent;
	border: none;
	cursor: pointer;
	color: #94a3b8;
	padding: 4px;
	border-radius: 6px;
}
.sp-close-btn:hover {
	color: #1e293b;
	background: #f1f5f9;
}

.sp-modal-body {
	padding: 18px 20px;
	display: flex;
	flex-direction: column;
	gap: 16px;
}

.sp-table-wrap {
	border: 1px solid var(--line, #e2e8f0);
	border-radius: 8px;
	overflow: hidden;
	max-height: 220px;
	overflow-y: auto;
}

.sp-table {
	width: 100%;
	border-collapse: collapse;
	font-size: 13px;
}

.sp-table th {
	background: #f8fafc;
	font-weight: 600;
	font-size: 11.5px;
	text-transform: uppercase;
	color: #64748b;
	padding: 8px 12px;
	border-bottom: 1px solid #e2e8f0;
}

.sp-table td {
	padding: 10px 12px;
	border-bottom: 1px solid #f1f5f9;
	vertical-align: middle;
}

.sp-table tr:last-child td {
	border-bottom: none;
}

.sp-badge-short {
	display: inline-block;
	background: #fee2e2;
	color: #b91c1c;
	font-weight: 700;
	font-size: 12px;
	padding: 2px 8px;
	border-radius: 4px;
	font-family: monospace;
}

.sp-reason-field {
	display: flex;
	flex-direction: column;
	gap: 6px;
}

.sp-label {
	font-size: 13px;
	font-weight: 600;
	color: #1e293b;
	display: flex;
	justify-content: space-between;
	align-items: center;
}

.sp-textarea {
	width: 100%;
	border: 1px solid #cbd5e1;
	border-radius: 6px;
	padding: 8px 10px;
	font-size: 13px;
	color: #0f172a;
	resize: vertical;
	outline: none;
	font-family: inherit;
}
.sp-textarea:focus {
	border-color: #0284c7;
	box-shadow: 0 0 0 2px rgba(2, 132, 199, 0.15);
}

.sp-modal-foot {
	padding: 14px 20px;
	background: #f8fafc;
	border-top: 1px solid var(--line, #e2e8f0);
	display: flex;
	justify-content: flex-end;
	gap: 10px;
}

/* ---- Short-pick banner styles ---- */
.short-banner {
	display: flex;
	align-items: flex-start;
	gap: 12px;
	padding: 14px 18px;
	border-radius: 12px;
	font-size: 13px;
	line-height: 1.45;
}

.short-banner-blocked {
	background: #fdf5f3;
	border: 1px solid #f2c7be;
	color: var(--bad-ink, #c0392b);
}

.short-banner-none {
	background: #fff9ea;
	border: 1px solid #efd8a8;
	color: #7a5200;
}

.short-banner-pending {
	background: #fff9ea;
	border: 1px solid #efd8a8;
	color: #7a5200;
}

.short-banner-rejected {
	background: #fdf5f3;
	border: 1px solid #f2c7be;
	color: var(--bad-ink, #c0392b);
}

.short-banner-approved {
	background: #eafaf1;
	border: 1px solid #c2eed5;
	color: #1b7a43;
}

.banner-icon {
	flex: none;
	margin-top: 2px;
}

.banner-body {
	flex: 1;
	min-width: 0;
	display: flex;
	flex-direction: column;
	gap: 4px;
}

.banner-headline {
	display: flex;
	align-items: center;
	gap: 8px;
	flex-wrap: wrap;
}

.banner-sub {
	margin: 0;
	font-size: 12.5px;
	opacity: 0.9;
}

.banner-author {
	margin: 2px 0 0;
	font-size: 11.5px;
	opacity: 0.8;
}

.short-reason-row {
	display: flex;
	align-items: center;
	gap: 8px;
	margin-top: 8px;
	flex-wrap: wrap;
}

.reason-input {
	flex: 1;
	min-width: 220px;
	max-width: 480px;
}

.banner-actions {
	display: flex;
	align-items: center;
	gap: 8px;
	flex: none;
}

/* ---- Group panel styles ---- */
.group-panel {
	overflow: hidden;
}

.group-head {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 12px;
	padding: 12px 18px;
	background: rgba(255, 255, 255, 0.4);
}

.group-title-col {
	display: flex;
	align-items: center;
	gap: 10px;
	flex-wrap: wrap;
}

.pl-link {
	display: inline-flex;
	align-items: center;
	gap: 4px;
	font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
	font-size: 13px;
	font-weight: 600;
	color: var(--brand);
	text-decoration: none;
}

.pl-link:hover {
	text-decoration: underline;
}

.group-meta-col {
	display: flex;
	align-items: center;
	gap: 8px;
	flex: none;
}

.btn-print {
	gap: 5px;
}

/* ---- Table styles ---- */
.table-wrap {
	overflow-x: auto;
}

.pl-table {
	width: 100%;
	border-collapse: collapse;
	font-size: 13px;
}

.pl-table th {
	text-align: left;
	padding: 10px 14px;
	font-size: 11.5px;
	font-weight: 650;
	text-transform: uppercase;
	letter-spacing: 0.04em;
	color: var(--muted);
	border-bottom: 1px solid var(--line);
	background: rgba(0, 0, 0, 0.02);
	white-space: nowrap;
}

.pl-table td {
	padding: 12px 14px;
	border-bottom: 1px solid var(--line);
	vertical-align: top;
}

.pl-table tbody tr:last-child td {
	border-bottom: none;
}

.pl-table tbody tr:hover {
	background: rgba(0, 0, 0, 0.015);
}

.row-short {
	background: rgba(255, 243, 214, 0.25);
}

.th-qty,
.th-picked {
	text-align: right;
}

.td-qty {
	text-align: right;
	white-space: nowrap;
}

.td-picked {
	text-align: right;
}

.item-code {
	font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
	font-weight: 650;
	color: var(--ink);
}

.item-name {
	font-size: 12px;
	color: var(--muted);
	margin-top: 2px;
}

.wh-text {
	color: var(--ink);
	font-size: 12.5px;
}

.qty-val {
	font-weight: 600;
	color: var(--ink);
}

.uom-val {
	margin-left: 4px;
	font-size: 12px;
	color: var(--muted);
}

.picked-input-wrap {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	justify-content: flex-end;
}

.pick-input {
	width: 96px;
	text-align: right;
	font-weight: 600;
	font-variant-numeric: tabular-nums;
}

.pick-input.is-invalid {
	border-color: var(--bad-ink, #c0392b);
	background: #fdf5f3;
}

.input-uom {
	font-size: 12px;
	color: var(--muted);
	min-width: 30px;
	text-align: left;
}

.field-error {
	font-size: 11px;
	color: var(--bad-ink, #c0392b);
	margin-top: 4px;
	line-height: 1.3;
	text-align: right;
	max-width: 200px;
	margin-left: auto;
}

.batch-hint {
	font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
	font-size: 12px;
	color: var(--muted);
}

.row-pill {
	display: inline-flex;
	align-items: center;
	padding: 3px 8px;
	border-radius: 999px;
	font-size: 11.5px;
	font-weight: 650;
}

.pill-full {
	background: #e5f6f1;
	color: #146b57;
}

.pill-short {
	background: #fff3d6;
	color: #925400;
}

.pill-invalid {
	background: #fdf5f3;
	color: var(--bad-ink, #c0392b);
}

/* ---- Action footer styles ---- */
.picking-footer {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 16px;
	flex-wrap: wrap;
	padding: 14px 18px;
	background: var(--surface);
	border: 1px solid var(--line);
	border-radius: 12px;
}

.footer-left {
	display: flex;
	align-items: center;
	gap: 8px;
}

.status-tip {
	font-size: 12.5px;
	font-weight: 500;
}

.tip-unsaved {
	color: #925400;
}

.tip-saved {
	color: #1b7a43;
}

.footer-actions {
	display: flex;
	align-items: center;
	gap: 10px;
	flex-wrap: wrap;
}

.btn-pick-all {
	display: inline-flex;
	align-items: center;
	gap: 10px;
}

.btn-pick-all :deep(svg),
.btn-pick-all svg {
	flex-shrink: 0;
}

/* Custom buttons */
.btn-success {
	background: #198754;
	border-color: #198754;
	color: #fff;
}

.btn-success:hover:not(:disabled) {
	background: #157347;
}

.btn-danger {
	background: var(--bad-bg, #f6e1dc);
	border-color: transparent;
	color: var(--bad-ink, #9c4736);
}

.btn-danger:hover:not(:disabled) {
	background: var(--bad-ink, #9c4736);
	color: #fff;
}

.ws-pill {
	display: inline-flex;
	align-items: center;
	padding: 3px 9px;
	border-radius: 999px;
	font-size: 11.5px;
	font-weight: 650;
}

.ws-dry {
	background: #eaf0ff;
	color: #36519a;
}

.ws-frozen {
	background: #e5f6f1;
	color: #146b57;
}

@media (max-width: 640px) {
	.group-head {
		flex-direction: column;
		align-items: flex-start;
	}
	.group-meta-col {
		width: 100%;
		justify-content: space-between;
	}
	.picking-footer {
		flex-direction: column;
		align-items: stretch;
	}
	.footer-actions {
		width: 100%;
		justify-content: flex-end;
	}
}
</style>
