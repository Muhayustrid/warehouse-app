<script setup>
import { computed } from 'vue'
import {
	AlertTriangle,
	ArrowLeft,
	ArrowRight,
	CheckCircle2,
	ExternalLink,
	FileText,
	Plus,
	Truck,
} from 'lucide-vue-next'
import { fmtDate, fmtQty } from '@/lib/format'

const ACTION_REASONS = {
	NO_PICK_LIST: 'Belum ada Pick List aktif.',
	PL_NOT_SUBMITTED: 'Seluruh Pick List harus diselesaikan terlebih dahulu.',
	SHORT_PICK_BLOCKED: 'Kekurangan kuantitas dicegah oleh kebijakan.',
	SHORT_PICK_APPROVAL_PENDING: 'Menunggu persetujuan supervisor.',
	SHORT_PICK_APPROVAL_REJECTED: 'Permintaan persetujuan ditolak.',
	SHORT_PICK_STALE_APPROVAL: 'Kuantitas berubah sejak disetujui.',
}

const props = defineProps({
	workspace: { type: Object, required: true },
	busy: { type: Boolean, default: false },
})

const emit = defineEmits(['create-dn', 'go-packing', 'go-review', 'go-picking', 'refresh'])

const enablePackingSlip = computed(() => {
	const val = props.workspace?.profile?.enable_packing_slip
	if (val === 0 || val === false || val === '0') return false
	return true
})

const deliveryNote = computed(() => props.workspace?.delivery_note)
const hasDeliveryNote = computed(() => Boolean(deliveryNote.value))
const isDnDraft = computed(() => deliveryNote.value?.docstatus === 0)
const isDnSubmitted = computed(() => deliveryNote.value?.docstatus === 1)

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

const allPlSubmitted = computed(() => {
	if (activePickLists.value.length === 0) return false
	return activePickLists.value.every((pl) => pl.docstatus === 1)
})

const shortPickBlocker = computed(() => props.workspace?.short_pick?.blocker)

const isReadyToCreate = computed(() => {
	return allPlSubmitted.value && !shortPickBlocker.value
})

const createDisabledReason = computed(() => {
	if (props.busy) return 'Sedang memproses…'
	if (activePickLists.value.length === 0) return ACTION_REASONS.NO_PICK_LIST
	if (shortPickBlocker.value) {
		return ACTION_REASONS[shortPickBlocker.value] || shortPickBlocker.value
	}
	if (!allPlSubmitted.value) return ACTION_REASONS.PL_NOT_SUBMITTED
	return ''
})

const totalDnQty = computed(() => {
	if (props.workspace?.packing?.dn_qty) {
		return props.workspace.packing.dn_qty
	}
	return (deliveryNote.value?.items || []).reduce((acc, row) => acc + (Number(row.qty) || 0), 0)
})

function dnStatusBadge(docstatus) {
	if (docstatus === 1) return { label: 'Submitted', class: 'b-done' }
	if (docstatus === 2) return { label: 'Cancelled', class: 'b-draft' }
	return { label: 'Draft', class: 'b-draft' }
}

function onCreateDeliveryNote() {
	if (props.busy || !isReadyToCreate.value) return
	emit('create-dn')
}
</script>

<template>
	<div class="delivery-panel">
		<!-- State 1: No Delivery Note created yet -->
		<template v-if="!hasDeliveryNote">
			<!-- Ready to create DN -->
			<div v-if="isReadyToCreate" class="panel dn-ready-card">
				<div class="dn-card-hero">
					<div class="hero-icon hero-icon-ready">
						<Truck :size="24" :stroke-width="2" />
					</div>
					<div class="hero-body">
						<div class="hero-title-row">
							<h4>Siap Membuat Surat Jalan (Delivery Note)</h4>
							<span class="badge b-done">Picking Selesai</span>
						</div>
						<p class="hero-desc">
							Seluruh Pick List Dry dan Frozen telah diselesaikan. Buat draf Surat Jalan (Delivery Note) gabungan untuk dipersiapkan ke tahapan {{ enablePackingSlip ? 'pengepakan (Packing Slip)' : 'pengiriman (Review & Kirim)' }}.
						</p>
					</div>
				</div>

				<div class="dn-card-actions">
					<button
						type="button"
						class="btn btn-primary"
						:disabled="busy || Boolean(createDisabledReason)"
						:title="createDisabledReason || 'Buat draf Surat Jalan'"
						@click="onCreateDeliveryNote"
					>
						<Plus :size="15" :stroke-width="2" />
						<span>Buat Surat Jalan (Draft DN)</span>
					</button>
				</div>
			</div>

			<!-- Not ready yet (picking draft or blocked) -->
			<div v-else class="panel dn-warning-card">
				<div class="dn-card-hero">
					<div class="hero-icon hero-icon-warn">
						<AlertTriangle :size="24" :stroke-width="2" />
					</div>
					<div class="hero-body">
						<div class="hero-title-row">
							<h4>Menunggu Penyelesaian Picking</h4>
							<span class="badge b-run">Picking Berjalan</span>
						</div>
						<p class="hero-desc">
							{{ createDisabledReason || 'Pick List harus diselesaikan terlebih dahulu sebelum Surat Jalan dapat dibuat.' }}
						</p>
					</div>
				</div>

				<div class="dn-card-actions">
					<button
						type="button"
						class="btn"
						disabled
						:title="createDisabledReason"
					>
						<Plus :size="15" :stroke-width="2" />
						<span>Buat Surat Jalan (Draft DN)</span>
					</button>
				</div>
			</div>
		</template>

		<!-- State 2: Delivery Note exists -->
		<template v-else>
			<div class="panel dn-summary-card">
				<!-- Header -->
				<div class="panel-head dn-head">
					<div class="dn-title-col">
						<div class="dn-name-row">
							<FileText :size="17" :stroke-width="2" class="dn-icon" />
							<span class="dn-name mono font-bold">{{ deliveryNote.name }}</span>
						</div>
						<span class="badge" :class="dnStatusBadge(deliveryNote.docstatus).class">
							{{ dnStatusBadge(deliveryNote.docstatus).label }}
						</span>
						<span class="dn-meta-inline text-muted text-xs">
							· {{ deliveryNote.items?.length || 0 }} item ({{ fmtQty(totalDnQty) }} unit)
						</span>
					</div>

					<div class="dn-audit-col">
						<a
							class="audit-link"
							:href="`/app/delivery-note/${encodeURIComponent(deliveryNote.name)}`"
							target="_blank"
							rel="noopener"
							title="Buka dokumen di Desk"
						>
							<span>Buka di Desk</span>
							<ExternalLink :size="13" :stroke-width="2" />
						</a>
					</div>
				</div>

				<!-- Items Table (Simplified & Clean) -->
				<div class="table-wrap">
					<table class="pl-table">
						<thead>
							<tr>
								<th class="th-no" style="width: 48px; text-align: center;">No</th>
								<th class="th-item">Item & Deskripsi</th>
								<th class="th-qty text-right" style="width: 150px;">Qty Surat Jalan</th>
								<th class="th-batch mono" style="width: 150px;">Batch No</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="(item, idx) in deliveryNote.items" :key="item.name">
								<td class="td-no text-muted" style="text-align: center;">{{ idx + 1 }}</td>
								<td class="td-item">
									<div class="item-name font-semibold">{{ item.item_name || item.item_code }}</div>
									<div class="item-sub mono text-muted text-xs">{{ item.item_code }}</div>
								</td>
								<td class="td-qty text-right">
									<strong class="qty-val">{{ fmtQty(item.qty) }}</strong>
									<span class="uom-val text-muted text-xs">&nbsp;{{ item.uom }}</span>
								</td>
								<td class="td-batch mono text-muted text-xs">
									{{ item.batch_no || '—' }}
								</td>
							</tr>
						</tbody>
					</table>
				</div>

				<!-- Navigation Footer -->
				<div class="dn-card-foot">
					<button type="button" class="btn btn-outline btn-sm" @click="$emit('go-picking')">
						<ArrowLeft :size="14" :stroke-width="2" />
						<span>Kembali ke Picking</span>
					</button>
					<div class="dn-foot-actions">
						<button
							v-if="enablePackingSlip"
							type="button"
							class="btn btn-primary"
							@click="$emit('go-packing')"
						>
							<span>Lanjut ke Packing Slip</span>
							<ArrowRight :size="14" :stroke-width="2" />
						</button>
						<button
							v-else
							type="button"
							class="btn btn-primary"
							@click="$emit('go-review')"
						>
							<span>Lanjut ke Review & Kirim</span>
							<ArrowRight :size="14" :stroke-width="2" />
						</button>
					</div>
				</div>
			</div>
		</template>
	</div>
</template>

<style scoped>
.delivery-panel {
	display: flex;
	flex-direction: column;
	gap: 16px;
}

.panel {
	background: #ffffff;
	border: 1px solid var(--line, #e2e8f0);
	border-radius: 12px;
	overflow: hidden;
}

.dn-ready-card,
.dn-warning-card {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 16px;
	padding: 24px;
}

.dn-card-hero {
	display: flex;
	align-items: flex-start;
	gap: 16px;
}

.hero-icon {
	width: 48px;
	height: 48px;
	border-radius: 10px;
	display: grid;
	place-items: center;
	flex-shrink: 0;
}

.hero-icon-ready {
	background: #ecfdf5;
	color: #059669;
}

.hero-icon-warn {
	background: #fff7ed;
	color: #ea580c;
}

.hero-body {
	display: flex;
	flex-direction: column;
	gap: 4px;
}

.hero-title-row {
	display: flex;
	align-items: center;
	gap: 10px;
}

.hero-title-row h4 {
	font-size: 15.5px;
	font-weight: 700;
	color: var(--ink, #1e293b);
	margin: 0;
}

.hero-desc {
	font-size: 13px;
	color: var(--muted, #64748b);
	margin: 0;
	max-width: 580px;
	line-height: 1.5;
}

.dn-summary-card {
	box-shadow: 0 4px 16px rgba(0, 0, 0, 0.03);
}

.dn-head {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 14px 20px;
	border-bottom: 1px solid var(--line, #e2e8f0);
}

.dn-title-col {
	display: flex;
	align-items: center;
	gap: 12px;
}

.dn-name-row {
	display: flex;
	align-items: center;
	gap: 8px;
}

.dn-icon {
	color: var(--brand, #3368a0);
}

.dn-name {
	font-size: 15px;
	font-weight: 750;
	color: var(--ink, #1e293b);
}

.audit-link {
	display: inline-flex;
	align-items: center;
	gap: 5px;
	font-size: 12px;
	color: var(--brand, #3368a0);
	text-decoration: none;
}

.dn-draft-notice {
	padding: 10px 20px;
	background: #eff6ff;
	border-bottom: 1px solid #dbeafe;
	font-size: 12.5px;
	color: #1e40af;
}

.dn-submitted-notice {
	display: flex;
	align-items: center;
	gap: 8px;
	padding: 10px 20px;
	background: #f0fdf4;
	border-bottom: 1px solid #bbf7d0;
	font-size: 12.5px;
	color: #166534;
}

.ico-submitted {
	color: #16a34a;
	flex-shrink: 0;
}

.dn-meta-grid {
	display: grid;
	grid-template-columns: repeat(4, minmax(0, 1fr));
	gap: 16px;
	padding: 14px 20px;
	background: var(--bg, #f8fafc);
	border-bottom: 1px solid var(--line, #e2e8f0);
}

.meta-item {
	display: flex;
	flex-direction: column;
	gap: 2px;
}

.meta-label {
	font-size: 11px;
	font-weight: 700;
	text-transform: uppercase;
	color: var(--muted, #64748b);
}

.meta-val {
	font-size: 13px;
	font-weight: 600;
	color: var(--ink, #1e293b);
}

.table-wrap {
	overflow-x: auto;
}

.pl-table {
	width: 100%;
	border-collapse: collapse;
	font-size: 13px;
	text-align: left;
}

.pl-table th {
	padding: 10px 18px;
	background: #ffffff;
	font-size: 11px;
	font-weight: 700;
	text-transform: uppercase;
	color: var(--muted, #64748b);
	border-bottom: 1px solid var(--line, #e2e8f0);
}

.pl-table td {
	padding: 12px 18px;
	border-bottom: 1px solid var(--line, #f1f5f9);
}

.pl-table tbody tr:last-child td {
	border-bottom: none;
}

.item-code {
	font-weight: 600;
	color: var(--ink, #1e293b);
}

.item-sub {
	font-size: 11px;
	color: var(--muted, #64748b);
}

.dn-card-foot {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 14px 20px;
	border-top: 1px solid var(--line, #e2e8f0);
	background: #ffffff;
}

.dn-foot-actions {
	display: flex;
	align-items: center;
	gap: 12px;
}

.dn-foot-tip {
	font-size: 12.5px;
	color: var(--muted, #64748b);
}

.dn-foot-tip.text-done {
	color: #16a34a;
	font-weight: 600;
}
</style>
