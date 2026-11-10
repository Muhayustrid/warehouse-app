<script setup>
import { computed, ref } from 'vue'
import {
	ArrowLeft,
	CheckCircle2,
	Clock,
	ExternalLink,
	Send,
	Truck,
} from 'lucide-vue-next'
import { fmtDate, fmtDateTime, fmtQty } from '@/lib/format'
import ConfirmDialog from '@/components/ConfirmDialog.vue'

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

const emit = defineEmits(['submit-dn', 'go-packing', 'go-delivery', 'refresh'])

const showSubmitConfirm = ref(false)

const isDispatched = computed(() => props.workspace?.run?.status === 'DISPATCHED')
const deliveryNote = computed(() => props.workspace?.delivery_note)
const packing = computed(() => props.workspace?.packing || {})

const enablePackingSlip = computed(() => {
	const val = props.workspace?.profile?.enable_packing_slip
	if (val === 0 || val === false || val === '0') return false
	return true
})

const activePickLists = computed(() => {
	const list = []
	if (props.workspace?.groups?.dry?.pick_list) {
		list.push(props.workspace.groups.dry)
	}
	if (props.workspace?.groups?.frozen?.pick_list) {
		list.push(props.workspace.groups.frozen)
	}
	return list
})

const isPlSubmitted = computed(() => {
	if (activePickLists.value.length === 0) return false
	return activePickLists.value.every((pl) => pl.docstatus === 1)
})

const isShortPickClear = computed(() => {
	const shortRows = props.workspace?.short_pick?.rows || []
	if (shortRows.length === 0) return true
	if (props.workspace?.short_pick?.blocker) return false
	return props.workspace?.run?.short_pick_status === 'Approved'
})

const hasDeliveryNote = computed(() => Boolean(props.workspace?.delivery_note))
const isDnSubmitted = computed(() => props.workspace?.delivery_note?.docstatus === 1)
const isDnDraft = computed(() => props.workspace?.delivery_note?.docstatus === 0)

const isAllPacked = computed(() => {
	return Boolean(props.workspace?.packing?.fully_packed)
})

const checklist = computed(() => {
	const items = [
		{
			id: 'pl',
			title: 'Pick List Selesai',
			ok: isPlSubmitted.value,
			desc: isPlSubmitted.value
				? `Seluruh Pick List (${activePickLists.value.length}) telah diselesaikan.`
				: 'Pick List belum selesai.',
		},
		{
			id: 'short_pick',
			title: 'Kuantitas Sesuai',
			ok: isShortPickClear.value,
			desc: !props.workspace?.short_pick?.rows?.length
				? 'Barang diambil penuh tanpa kekurangan.'
				: props.workspace?.run?.short_pick_status === 'Approved' && !props.workspace?.short_pick?.blocker
					? `Kekurangan disetujui oleh ${props.workspace?.run?.short_pick_approved_by || 'Supervisor'}.`
					: props.workspace?.short_pick?.blocker
						? ACTION_REASONS[props.workspace.short_pick.blocker] || props.workspace.short_pick.blocker
						: 'Kekurangan memerlukan persetujuan.',
		},
	]

	if (enablePackingSlip.value) {
		items.push({
			id: 'packing',
			title: 'Packing Selesai',
			ok: isAllPacked.value,
			desc: isAllPacked.value
				? `Barang telah dikemas (${props.workspace?.packing?.submitted?.length || 1} Koli).`
				: 'Item belum lengkap dikemas.',
		})
	}

	items.push({
		id: 'dn',
		title: isDnSubmitted.value ? 'Surat Jalan Submitted' : 'Surat Jalan Siap',
		ok: hasDeliveryNote.value,
		desc: hasDeliveryNote.value
			? isDnSubmitted.value
				? 'Surat Jalan telah resmi disubmit.'
				: 'Surat Jalan siap disubmit.'
			: 'Surat Jalan belum dibuat.',
	})

	return items
})

const isChecklistComplete = computed(() => {
	return checklist.value.every((item) => item.ok)
})

const canSubmitDn = computed(() => {
	return (
		isChecklistComplete.value &&
		isDnDraft.value &&
		!isDispatched.value &&
		!props.busy
	)
})

const submitDisabledReason = computed(() => {
	if (props.busy) return 'Sedang memproses…'
	if (isDispatched.value) return 'Pengiriman sudah selesai.'
	if (!hasDeliveryNote.value) return 'Surat Jalan belum dibuat.'
	if (!isDnDraft.value) return 'Surat Jalan sudah disubmit atau dibatalkan.'
	if (!isChecklistComplete.value) return 'Lengkapi seluruh tahapan checklist sebelum submit.'
	return ''
})

const submitConfirmOptions = {
	title: 'Submit Surat Jalan & Kurangi Stok',
	message:
		'Mensubmit Surat Jalan ini akan secara resmi memotong stok fisik barang di ERPNext dan menyelesaikan alur pengiriman. Lanjutkan?',
	confirmLabel: 'Submit & Kirim Barang',
	theme: 'warning',
	confirmClass: 'btn-primary',
}

function onPromptSubmit() {
	if (!canSubmitDn.value) return
	showSubmitConfirm.value = true
}

function onConfirmSubmit() {
	emit('submit-dn')
}

defineExpose({
	openSubmitConfirm: onPromptSubmit,
})
</script>

<template>
	<div class="review-panel">
		<!-- Delivery Summary Card -->
		<div v-if="deliveryNote" class="panel dn-summary-card">
			<div class="panel-head dn-head">
				<div class="dn-head-title">
					<Truck :size="17" :stroke-width="2" class="dn-ico" />
					<span class="dn-title-text">Surat Jalan</span>
					<strong class="mono dn-name">{{ deliveryNote.name }}</strong>
				</div>
				<div class="dn-head-right">
					<span v-if="deliveryNote.docstatus === 1" class="badge b-done">Submitted</span>
					<span v-else class="badge b-draft">Draft (Siap Kirim)</span>

					<a
						class="audit-link"
						:href="`/app/delivery-note/${encodeURIComponent(deliveryNote.name)}`"
						target="_blank"
						rel="noopener"
						title="Buka dokumen di Desk"
					>
						<span>Buka di Desk</span>
						<ExternalLink :size="12" :stroke-width="2" />
					</a>
				</div>
			</div>

			<!-- Compact Meta Strip (Shown only in draft before submit) -->
			<div v-if="!isDispatched" class="dn-meta-grid">
				<div class="dn-meta-item">
					<span class="m-label">Customer / Outlet</span>
					<span class="m-val">{{ workspace.sales_order?.customer_name || workspace.run?.customer }}</span>
				</div>
				<div class="dn-meta-item">
					<span class="m-label">Tanggal Kirim</span>
					<span class="m-val">{{ fmtDate(deliveryNote.posting_date || workspace.run?.delivery_date) }}</span>
				</div>
				<div class="dn-meta-item">
					<span class="m-label">Total Barang</span>
					<span class="m-val">{{ deliveryNote.items?.length || 0 }} Item · {{ fmtQty(packing.dn_qty || 0) }} Pcs</span>
				</div>
				<div v-if="enablePackingSlip || packing.submitted?.length" class="dn-meta-item">
					<span class="m-label">Kemasan</span>
					<span class="m-val">{{ packing.submitted?.length ? `${packing.submitted.length} Koli Packing Slip` : '1 Koli Packing Slip' }}</span>
				</div>
			</div>

			<!-- Compact Checklist Strip (Shown only in draft before submit) -->
			<div v-if="!isDispatched" class="checklist-bar">
				<div
					v-for="item in checklist"
					:key="item.id"
					class="check-pill"
					:class="{ ok: item.ok, pending: !item.ok }"
					:title="item.desc"
				>
					<CheckCircle2 v-if="item.ok" :size="14" :stroke-width="2.2" />
					<Clock v-else :size="14" :stroke-width="2" />
					<span>{{ item.title }}</span>
				</div>
			</div>

			<!-- Compact Items Table -->
			<div class="table-wrap">
				<table class="compact-items-table">
					<thead>
						<tr>
							<th class="th-no">No</th>
							<th class="th-item">Item</th>
							<th class="th-qty text-right">Qty</th>
							<th class="th-batch">Batch</th>
							<th v-if="!isDispatched" class="th-status text-center">Status</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="(item, idx) in deliveryNote.items" :key="item.name">
							<td class="td-no">{{ idx + 1 }}</td>
							<td class="td-item">
								<strong>{{ item.item_name || item.item_code }}</strong>
							</td>
							<td class="td-qty text-right">
								<strong>{{ fmtQty(item.qty) }}</strong> {{ item.uom }}
							</td>
							<td class="td-batch mono">
								{{ item.batch_no || '—' }}
							</td>
							<td v-if="!isDispatched" class="td-status text-center">
								<span v-if="Number(item.packed_qty) >= Number(item.qty)" class="badge-status-ok">
									Lengkap
								</span>
								<span v-else class="badge-status-warn">
									{{ fmtQty(item.packed_qty) }}/{{ fmtQty(item.qty) }}
								</span>
							</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>

		<!-- Action Footer: When in Draft stage -->
		<div v-if="!isDispatched" class="panel-foot review-footer">
			<button
				type="button"
				class="btn btn-outline btn-sm"
				@click="$emit(enablePackingSlip ? 'go-packing' : 'go-delivery')"
			>
				<ArrowLeft :size="14" :stroke-width="2" />
				<span>{{ enablePackingSlip ? 'Kembali ke Packing Slip' : 'Kembali ke Surat Jalan' }}</span>
			</button>

			<button
				type="button"
				class="btn btn-primary btn-submit-dn"
				:disabled="!canSubmitDn"
				:title="submitDisabledReason || 'Submit Surat Jalan dan potong stok'"
				@click="onPromptSubmit"
			>
				<Send :size="14" :stroke-width="2" />
				<span>Submit Delivery Note & Kirim Barang</span>
			</button>
		</div>

		<!-- Clean Footer: When already Dispatched -->
		<div v-else class="review-footer-done">
			<RouterLink to="/fulfillment" class="btn btn-primary">
				<ArrowLeft :size="14" :stroke-width="2" />
				<span>Kembali ke Order Queue</span>
			</RouterLink>
		</div>

		<!-- Confirmation Dialog -->
		<ConfirmDialog
			v-model="showSubmitConfirm"
			:options="submitConfirmOptions"
			:on-confirm="onConfirmSubmit"
		/>
	</div>
</template>

<style scoped>
.review-panel {
	display: flex;
	flex-direction: column;
	gap: 16px;
}

.panel {
	background: #ffffff;
	border: 1px solid var(--line, #e2e8f0);
	border-radius: 10px;
	overflow: hidden;
}

/* Dispatched Banner */
.dispatched-simple {
	background: #f0fdf4;
	border-color: #bbf7d0;
	padding: 16px 20px;
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 16px;
}

.dispatched-left {
	display: flex;
	align-items: center;
	gap: 12px;
}

.ico-done {
	color: #16a34a;
	flex-shrink: 0;
}

.dispatched-left h4 {
	font-size: 15px;
	font-weight: 700;
	color: #15803d;
	margin: 0;
}

.dispatched-sub {
	font-size: 12.5px;
	color: #166534;
	margin: 2px 0 0;
}

/* Delivery Summary Card */
.dn-head {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 12px 18px;
	border-bottom: 1px solid #f1f5f9;
	background: #ffffff;
}

.dn-head-title {
	display: flex;
	align-items: center;
	gap: 8px;
}

.dn-head-right {
	display: flex;
	align-items: center;
	gap: 12px;
}

.audit-link {
	display: inline-flex;
	align-items: center;
	gap: 5px;
	font-size: 12px;
	color: var(--brand, #3368a0);
	text-decoration: none;
}

.audit-link:hover {
	text-decoration: underline;
}

.dn-ico {
	color: var(--brand, #3368a0);
}

.dn-title-text {
	font-size: 13px;
	font-weight: 600;
	color: var(--muted, #64748b);
}

.dn-name {
	font-size: 14px;
	color: var(--ink, #1e293b);
}

/* Meta Grid */
.dn-meta-grid {
	display: grid;
	grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
	gap: 12px 18px;
	padding: 14px 18px;
	background: #f8fafc;
	border-bottom: 1px solid #e2e8f0;
}

.dn-meta-item {
	display: flex;
	flex-direction: column;
	gap: 3px;
}

.m-label {
	font-size: 11px;
	font-weight: 600;
	text-transform: uppercase;
	letter-spacing: 0.04em;
	color: var(--muted, #64748b);
}

.m-val {
	font-size: 13px;
	font-weight: 600;
	color: var(--ink, #1e293b);
}

/* Compact Checklist Bar */
.checklist-bar {
	display: flex;
	flex-wrap: wrap;
	gap: 8px;
	padding: 12px 18px;
	background: #ffffff;
	border-bottom: 1px solid #f1f5f9;
}

.check-pill {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	padding: 4px 10px;
	border-radius: 6px;
	font-size: 12px;
	font-weight: 600;
	border: 1px solid transparent;
}

.check-pill.ok {
	background: #f0fdf4;
	color: #16a34a;
	border-color: #bbf7d0;
}

.check-pill.pending {
	background: #fefce8;
	color: #ca8a04;
	border-color: #fef08a;
}

/* Compact Items Table */
.table-wrap {
	overflow-x: auto;
}

.compact-items-table {
	width: 100%;
	border-collapse: collapse;
	font-size: 13px;
}

.compact-items-table th {
	padding: 9px 16px;
	font-size: 11px;
	font-weight: 700;
	text-transform: uppercase;
	letter-spacing: 0.04em;
	color: var(--muted, #64748b);
	border-bottom: 1px solid #e2e8f0;
	background: #ffffff;
	text-align: left;
}

.compact-items-table td {
	padding: 10px 16px;
	border-bottom: 1px solid #f1f5f9;
	color: var(--ink, #1e293b);
}

.compact-items-table tr:last-child td {
	border-bottom: none;
}

.th-no, .td-no {
	width: 48px;
	color: var(--muted, #64748b);
}

.td-item strong {
	font-weight: 600;
	color: var(--ink, #1e293b);
}

.td-batch {
	font-size: 12px;
	color: var(--muted, #64748b);
}

.badge-status-ok {
	display: inline-block;
	padding: 2px 8px;
	border-radius: 4px;
	background: #f0fdf4;
	color: #16a34a;
	font-size: 11px;
	font-weight: 600;
}

.badge-status-warn {
	display: inline-block;
	padding: 2px 8px;
	border-radius: 4px;
	background: #fefce8;
	color: #ca8a04;
	font-size: 11px;
	font-weight: 600;
}

/* Footer Actions */
.review-footer {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 12px 18px;
	background: #ffffff;
	border: 1px solid var(--line, #e2e8f0);
	border-radius: 10px;
}

.btn-submit-dn {
	display: inline-flex;
	align-items: center;
	gap: 8px;
	font-weight: 600;
}

.review-footer-done {
	display: flex;
	justify-content: flex-end;
	padding: 8px 0;
}

.text-success {
	color: #16a34a;
}
</style>
