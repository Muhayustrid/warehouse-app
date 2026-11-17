<script setup>
import { computed, ref, watch, watchEffect } from 'vue'
import {
	AlertTriangle,
	ArrowLeft,
	ArrowRight,
	ArrowRightLeft,
	Boxes,
	CheckCircle2,
	ExternalLink,
	LoaderCircle,
	Minus,
	Package,
	PackageCheck,
	Plus,
	RotateCcw,
	X,
} from 'lucide-vue-next'
import { fmtDate, fmtDateTime, fmtQty } from '@/lib/format'
import { toast } from '@/lib/toast'
import ConfirmDialog from '@/components/ConfirmDialog.vue'

const props = defineProps({
	workspace: { type: Object, required: true },
	busy: { type: Boolean, default: false },
})

const emit = defineEmits(['pack-all', 'reset-packing', 'go-delivery', 'go-review', 'refresh'])

const showResetConfirm = ref(false)

const deliveryNote = computed(() => props.workspace?.delivery_note)
const hasDeliveryNote = computed(() => Boolean(deliveryNote.value))

const isDnDraft = computed(() => deliveryNote.value?.docstatus === 0)
const isDnSubmitted = computed(() => deliveryNote.value?.docstatus === 1)

const packing = computed(() => props.workspace?.packing || {})
const submittedSlips = computed(() => packing.value.submitted || [])
const isFullyPacked = computed(() => Boolean(packing.value.fully_packed))
const dnQty = computed(() => Number(packing.value.dn_qty || 0))
const packedQty = computed(() => Number(packing.value.packed_qty || 0))
const dnItemsCount = computed(() => deliveryNote.value?.items?.length || 0)

const dryPickList = computed(() => props.workspace?.groups?.dry?.pick_list)
const frozenPickList = computed(() => props.workspace?.groups?.frozen?.pick_list)
const frozenRows = computed(() => props.workspace?.groups?.frozen?.rows || [])
const frozenItemCodes = computed(() => new Set(frozenRows.value.map((r) => r.item_code)))
const dryItemExceptions = computed(() => new Set(props.workspace?.profile?.dry_item_exceptions || []))

const frozenItems = computed(() => {
	const items = deliveryNote.value?.items || []
	return items.filter((it) => {
		if (dryItemExceptions.value.has(it.item_code)) return false
		if (frozenPickList.value && it.against_pick_list === frozenPickList.value) return true
		if (dryPickList.value && it.against_pick_list === dryPickList.value) return false
		if (frozenItemCodes.value.has(it.item_code)) return true
		return false
	})
})

const dryItems = computed(() => {
	const items = deliveryNote.value?.items || []
	return items.filter((it) => {
		if (dryItemExceptions.value.has(it.item_code)) return true
		if (dryPickList.value && it.against_pick_list === dryPickList.value) return true
		if (frozenPickList.value && it.against_pick_list === frozenPickList.value) return false
		if (frozenItemCodes.value.has(it.item_code)) return false
		return true
	})
})

const hasDryItems = computed(() => dryItems.value.length > 0)
const hasFrozenItems = computed(() => frozenItems.value.length > 0)

const dryQty = computed(() => dryItems.value.reduce((acc, it) => acc + Number(it.qty || 0), 0))
const frozenQty = computed(() => frozenItems.value.reduce((acc, it) => acc + Number(it.qty || 0), 0))

const dryPackages = ref(1)
const frozenPackages = ref(1)

watchEffect(() => {
	if (!hasDryItems.value) {
		dryPackages.value = 0
	} else if (dryPackages.value < 1) {
		dryPackages.value = 1
	}

	if (!hasFrozenItems.value) {
		frozenPackages.value = 0
	} else if (frozenPackages.value < 1) {
		frozenPackages.value = 1
	}
})

const totalPackages = computed(() => {
	return (hasDryItems.value ? dryPackages.value : 0) + (hasFrozenItems.value ? frozenPackages.value : 0)
})

function simulateSequentialBins(items, numPackages, startCaseNo, categoryLabel) {
	if (numPackages <= 0 || !items?.length) return []
	if (numPackages === 1) {
		return [
			{
				case_no: startCaseNo,
				category: categoryLabel,
				box_size: '',
				total_qty: items.reduce((acc, it) => acc + Number(it.qty || 0), 0),
				items: items.map((it) => ({
					item_code: it.item_code,
					item_name: it.item_name || it.item_code,
					qty: Number(it.qty || 0),
					dn_detail: it.name,
					uom: it.uom,
				})),
			},
		]
	}

	const totalQty = items.reduce((acc, it) => acc + Number(it.qty || 0), 0)
	const targetPerPkg = totalQty / numPackages
	const packages = Array.from({ length: numPackages }, (_, i) => ({
		case_no: startCaseNo + i,
		category: categoryLabel,
		box_size: '',
		total_qty: 0,
		items: [],
	}))

	let currentPkg = 0

	for (const item of items) {
		let remaining = Number(item.qty || 0)
		if (remaining <= 0) continue

		while (remaining > 0.0001) {
			if (currentPkg >= numPackages - 1) {
				const take = Math.round(remaining)
				packages[currentPkg].items.push({
					item_code: item.item_code,
					item_name: item.item_name || item.item_code,
					qty: take,
					dn_detail: item.name,
					uom: item.uom,
				})
				packages[currentPkg].total_qty += take
				break
			}

			const capLeft = targetPerPkg - packages[currentPkg].total_qty
			if (capLeft <= 0.0001) {
				currentPkg++
				continue
			}

			if (remaining <= capLeft) {
				const take = Math.round(remaining)
				packages[currentPkg].items.push({
					item_code: item.item_code,
					item_name: item.item_name || item.item_code,
					qty: take,
					dn_detail: item.name,
					uom: item.uom,
				})
				packages[currentPkg].total_qty += take
				remaining = 0
			} else {
				if (packages[currentPkg].total_qty > 0.0001) {
					currentPkg++
					continue
				} else {
					const take = Math.min(Math.round(remaining), Math.max(1, Math.ceil(capLeft)))
					packages[currentPkg].items.push({
						item_code: item.item_code,
						item_name: item.item_name || item.item_code,
						qty: take,
						dn_detail: item.name,
						uom: item.uom,
					})
					packages[currentPkg].total_qty += take
					remaining -= take
					currentPkg++
				}
			}
		}
	}

	return packages
}

const isCustomized = ref(false)
const allocatedKoliList = ref([])

function generateAutoAllocation() {
	const list = []
	let caseNo = 1
	if (hasDryItems.value && dryPackages.value > 0) {
		const dryKolis = simulateSequentialBins(dryItems.value, dryPackages.value, caseNo, 'Dry')
		list.push(...dryKolis)
		caseNo += dryKolis.length
	}
	if (hasFrozenItems.value && frozenPackages.value > 0) {
		const frozenKolis = simulateSequentialBins(frozenItems.value, frozenPackages.value, caseNo, 'Frozen')
		list.push(...frozenKolis)
	}
	return list
}

watch(
	[
		() => dryPackages.value,
		() => frozenPackages.value,
		() => deliveryNote.value?.name,
		() => dryItems.value.length,
		() => frozenItems.value.length,
	],
	() => {
		isCustomized.value = false
		allocatedKoliList.value = generateAutoAllocation()
	},
	{ immediate: true },
)

function recalcKoliTotals(koli) {
	if (!koli) return
	koli.total_qty = (koli.items || []).reduce((sum, it) => sum + Number(it.qty || 0), 0)
}

function kolisOf(cat) {
	return allocatedKoliList.value.filter((k) => k.category === cat)
}

function koliIdxOf(koli) {
	return allocatedKoliList.value.indexOf(koli)
}

function resetToAuto() {
	isCustomized.value = false
	allocatedKoliList.value = generateAutoAllocation()
	toast.info('Alokasi barang dikembalikan ke hitungan otomatis.')
}

// Drag & Drop State & Handlers
const draggedItem = ref(null)
const activeDropTarget = ref(null)

function onDragStart(event, koliIdx, itemIdx, item) {
	draggedItem.value = { koliIndex: koliIdx, itemIndex: itemIdx, item: { ...item } }
	if (event.dataTransfer) {
		event.dataTransfer.effectAllowed = 'move'
		event.dataTransfer.setData('text/plain', JSON.stringify({ koliIdx, itemIdx }))
	}
}

function onDragEnd() {
	draggedItem.value = null
	activeDropTarget.value = null
}

function onDragOver(koliIdx) {
	if (draggedItem.value && draggedItem.value.koliIndex !== koliIdx) {
		activeDropTarget.value = koliIdx
	}
}

function onDragLeave(koliIdx) {
	if (activeDropTarget.value === koliIdx) {
		activeDropTarget.value = null
	}
}

function onDrop(targetKoliIdx) {
	if (!draggedItem.value) return
	const sourceKoliIdx = draggedItem.value.koliIndex
	const itemIdx = draggedItem.value.itemIndex
	activeDropTarget.value = null

	if (sourceKoliIdx === targetKoliIdx) return

	const sourceKoli = allocatedKoliList.value[sourceKoliIdx]
	const targetKoli = allocatedKoliList.value[targetKoliIdx]
	if (!sourceKoli || !targetKoli) return

	if (sourceKoli.category !== targetKoli.category) {
		toast.warning(`Item ${sourceKoli.category} tidak dapat dipindahkan ke koli ${targetKoli.category}.`)
		draggedItem.value = null
		return
	}

	const itemToMove = sourceKoli.items[itemIdx]
	if (!itemToMove) return

	sourceKoli.items.splice(itemIdx, 1)

	const existing = targetKoli.items.find((it) => it.item_code === itemToMove.item_code)
	if (existing) {
		existing.qty += itemToMove.qty
	} else {
		targetKoli.items.push(itemToMove)
	}

	recalcKoliTotals(sourceKoli)
	recalcKoliTotals(targetKoli)

	isCustomized.value = true
	toast.success(`${itemToMove.item_name} dipindahkan ke Koli ${targetKoli.case_no}.`)
	draggedItem.value = null
}

// Click-to-Move Modal State & Handlers
const moveModalOpen = ref(false)
const moveState = ref({
	sourceKoliIdx: 0,
	itemIdx: 0,
	item: null,
	sourceKoli: null,
	moveQty: 1,
	targetKoliIdx: null,
	eligibleTargets: [],
})

function openMoveModal(koliIdx, itemIdx, item) {
	const sourceKoli = allocatedKoliList.value[koliIdx]
	if (!sourceKoli) return

	const eligible = allocatedKoliList.value
		.map((k, idx) => ({ ...k, originalIdx: idx }))
		.filter((k) => k.originalIdx !== koliIdx && k.category === sourceKoli.category)

	if (!eligible.length) {
		toast.info(`Hanya ada 1 koli untuk kategori ${sourceKoli.category}. Tambahkan koli pada pengaturan di atas jika ingin membagi barang.`)
		return
	}

	moveState.value = {
		sourceKoliIdx: koliIdx,
		itemIdx: itemIdx,
		item: item,
		sourceKoli: sourceKoli,
		moveQty: item.qty,
		targetKoliIdx: eligible[0].originalIdx,
		eligibleTargets: eligible,
	}
	moveModalOpen.value = true
}

function setMovePercentage(pct) {
	if (!moveState.value.item) return
	const total = Number(moveState.value.item.qty)
	if (pct === 100) {
		moveState.value.moveQty = total
	} else {
		moveState.value.moveQty = Math.max(1, Math.round((total * pct) / 100))
	}
}

function confirmMove() {
	const { sourceKoliIdx, itemIdx, item, moveQty, targetKoliIdx } = moveState.value
	const qty = Number(moveQty)
	if (isNaN(qty) || qty <= 0 || qty > item.qty) {
		toast.warning('Jumlah pemindahan tidak valid.')
		return
	}
	if (targetKoliIdx === null || targetKoliIdx === undefined) {
		toast.warning('Pilih koli tujuan.')
		return
	}

	const sourceKoli = allocatedKoliList.value[sourceKoliIdx]
	const targetKoli = allocatedKoliList.value[targetKoliIdx]
	if (!sourceKoli || !targetKoli) return

	if (qty >= item.qty) {
		sourceKoli.items.splice(itemIdx, 1)
	} else {
		item.qty -= qty
	}

	const existing = targetKoli.items.find((it) => it.item_code === item.item_code)
	if (existing) {
		existing.qty += qty
	} else {
		targetKoli.items.push({
			...item,
			qty: qty,
		})
	}

	recalcKoliTotals(sourceKoli)
	recalcKoliTotals(targetKoli)

	isCustomized.value = true
	toast.success(`${qty}x ${item.item_name} dipindahkan ke Koli ${targetKoli.case_no}.`)
	moveModalOpen.value = false
}

const hasEmptyKoli = computed(() => {
	if (totalPackages.value <= 1) return false
	return allocatedKoliList.value.some((k) => !k.items || k.items.length === 0)
})

const canPackAll = computed(() => {
	return (
		hasDeliveryNote.value &&
		isDnDraft.value &&
		!isFullyPacked.value &&
		totalPackages.value > 0 &&
		!hasEmptyKoli.value &&
		!props.busy
	)
})

const canResetPacking = computed(() => {
	return hasDeliveryNote.value && isDnDraft.value && submittedSlips.value.length > 0 && !props.busy
})

const resetConfirmOptions = {
	title: 'Reset Packing Slips',
	message:
		'Reset packing akan membatalkan seluruh Packing Slip pada Surat Jalan ini dan mengembalikan status kemasan ke 0. Tindakan ini tidak dapat dibatalkan. Apakah Anda yakin?',
	confirmLabel: 'Reset Packing',
	theme: 'danger',
}

function onPackAll() {
	if (!canPackAll.value) return
	emit('pack-all', {
		dryPackages: hasDryItems.value ? dryPackages.value : 0,
		frozenPackages: hasFrozenItems.value ? frozenPackages.value : 0,
		customSlips: allocatedKoliList.value,
	})
}

function onPromptReset() {
	if (!canResetPacking.value) return
	showResetConfirm.value = true
}

function onConfirmReset() {
	emit('reset-packing')
}
</script>

<template>
	<div class="packing-panel">
		<!-- State 1: No Delivery Note created yet -->
		<div v-if="!hasDeliveryNote" class="panel empty-inset">
			<div class="eico">
				<AlertTriangle :size="22" :stroke-width="1.8" />
			</div>
			<div class="etitle">Surat Jalan Belum Dibuat</div>
			<div class="ehint">
				Selesaikan picking dan buat draft Surat Jalan (Delivery Note) terlebih dahulu sebelum mengemas barang ke Packing Slip.
			</div>
			<button type="button" class="btn btn-sm btn-outline mt-2" @click="$emit('go-delivery')">
				<ArrowLeft :size="14" :stroke-width="2" />
				<span>Kembali ke Tahap Surat Jalan</span>
			</button>
		</div>

		<!-- State 2: Delivery Note exists -->
		<template v-else>
			<!-- State 2A: Items NOT fully packed yet -> Summary & Multi-Koli Configuration Card -->
			<div v-if="!isFullyPacked" class="panel pack-action-card">
				<div class="panel-head pack-head">
					<div class="pack-title-col">
						<Package :size="18" :stroke-width="2" class="pack-icon" />
						<span class="pack-title">Pengepakan Barang (Packing Slip)</span>
						<span class="badge b-draft">Belum Dikemas</span>
					</div>
				</div>

				<div class="pack-body">
					<div class="pack-meta-row">
						<div class="pm-col">
							<span class="pm-label">Total Item</span>
							<strong class="pm-val">{{ dnItemsCount }} Item</strong>
						</div>
						<div class="pm-col">
							<span class="pm-label">Total Kuantitas</span>
							<strong class="pm-val">{{ fmtQty(dnQty) }} Unit / Pcs</strong>
						</div>
						<div class="pm-col">
							<span class="pm-label">Surat Jalan Asal</span>
							<strong class="pm-val mono">{{ deliveryNote.name }}</strong>
						</div>
					</div>

					<!-- Package Configurator (Split Dry & Frozen + Multi-Koli) -->
					<div class="package-config-section">
						<div class="config-section-title">
							<strong>Pengaturan Koli / Kemasan</strong>
							<span>Barang Dry dan Frozen otomatis dipisahkan. Tentukan jumlah koli fisik untuk masing-masing kategori:</span>
						</div>

						<div class="config-grid">
							<!-- Card Dry -->
							<div v-if="hasDryItems" class="pkg-category-card">
								<div class="pkg-cat-header">
									<span class="badge b-dry">Dry</span>
									<span class="pkg-cat-count">{{ dryItems.length }} Item ({{ fmtQty(dryQty) }} Unit)</span>
								</div>
								<div class="pkg-cat-body">
									<div class="pkg-counter-row">
										<label class="pkg-counter-label">Jumlah Koli:</label>
										<div class="stepper-counter">
											<button
												type="button"
												class="counter-btn"
												:disabled="dryPackages <= 1 || busy"
												@click="dryPackages--"
											>
												<Minus :size="14" :stroke-width="2.5" />
											</button>
											<span class="counter-val">{{ dryPackages }}</span>
											<button
												type="button"
												class="counter-btn"
												:disabled="busy"
												@click="dryPackages++"
											>
												<Plus :size="14" :stroke-width="2.5" />
											</button>
										</div>
									</div>
									<span class="pkg-hint">
										{{ dryPackages > 1 ? `Item Dry dikemas berurutan ke ${dryPackages} koli.` : 'Seluruh item Dry dikemas dalam 1 koli.' }}
									</span>
								</div>
							</div>

							<!-- Card Frozen -->
							<div v-if="hasFrozenItems" class="pkg-category-card">
								<div class="pkg-cat-header">
									<span class="badge b-frozen">Frozen</span>
									<span class="pkg-cat-count">{{ frozenItems.length }} Item ({{ fmtQty(frozenQty) }} Unit)</span>
								</div>
								<div class="pkg-cat-body">
									<div class="pkg-counter-row">
										<label class="pkg-counter-label">Jumlah Koli:</label>
										<div class="stepper-counter">
											<button
												type="button"
												class="counter-btn"
												:disabled="frozenPackages <= 1 || busy"
												@click="frozenPackages--"
											>
												<Minus :size="14" :stroke-width="2.5" />
											</button>
											<span class="counter-val">{{ frozenPackages }}</span>
											<button
												type="button"
												class="counter-btn"
												:disabled="busy"
												@click="frozenPackages++"
											>
												<Plus :size="14" :stroke-width="2.5" />
											</button>
										</div>
									</div>
									<span class="pkg-hint">
										{{ frozenPackages > 1 ? `Item Frozen dikemas berurutan ke ${frozenPackages} koli.` : 'Seluruh item Frozen dikemas dalam 1 koli.' }}
									</span>
								</div>
							</div>
						</div>

						<!-- Total Summary Banner -->
						<div class="total-koli-summary">
							<Package :size="16" :stroke-width="2" />
							<span>
								Total Kemasan yang akan dibuat: <strong>{{ totalPackages }} Koli</strong>
								<template v-if="hasDryItems && hasFrozenItems">
									({{ dryPackages }} Koli Dry + {{ frozenPackages }} Koli Frozen)
								</template>
							</span>
						</div>

						<!-- Live Preview of Koli Allocation: sheet excel per kategori, grup per koli -->
					<div v-if="totalPackages > 0" class="koli-preview-block">
						<div class="koli-preview-head">
							<div class="koli-preview-title">
								<Boxes :size="15" :stroke-width="2" class="preview-icon" />
								<strong>Alokasi Barang per Koli:</strong>
								<span class="badge" :class="isCustomized ? 'b-custom' : 'b-auto'">
									{{ isCustomized ? '✎ Disesuaikan Manual' : 'Otomatis' }}
								</span>
							</div>
							<button
								v-if="isCustomized"
								type="button"
								class="btn btn-xs btn-outline btn-reset-auto"
								title="Kembalikan susunan barang ke hitungan otomatis"
								@click="resetToAuto"
							>
								<RotateCcw :size="12" />
								<span>Reset ke Otomatis</span>
							</button>
						</div>

						<div class="preview-sub-row">
							<span class="preview-sub">
								💡 Seret (drag) baris barang ke koli lain, atau klik baris untuk memindahkan jumlah tertentu.
							</span>
						</div>

						<div v-if="hasEmptyKoli" class="empty-koli-warning">
							<AlertTriangle :size="14" />
							<span>Ada koli yang masih kosong. Pastikan setiap koli terisi barang sebelum mengemas.</span>
						</div>

						<div class="koli-excel-grid">
							<div v-for="cat in ['Dry', 'Frozen']" :key="cat" class="koli-excel-cat">
								<div class="ke-title">{{ cat.toUpperCase() }}</div>
								<table class="ke-tbl">
									<thead>
										<tr><th>Item</th><th>Qty</th><th>Unit</th><th>Colly</th><th>Weight (Kg)</th></tr>
									</thead>
									<tbody>
										<template v-for="koli in kolisOf(cat)" :key="koli.case_no">
											<tr
												v-if="!koli.items || !koli.items.length"
												class="ke-empty"
												@dragover.prevent="onDragOver(koliIdxOf(koli))"
												@dragleave="onDragLeave(koliIdxOf(koli))"
												@drop.prevent="onDrop(koliIdxOf(koli))"
											>
												<td colspan="5">Koli {{ koli.case_no }}/{{ totalPackages }} kosong — tarik barang ke sini</td>
											</tr>
											<tr
												v-for="(it, itemIdx) in koli.items"
												:key="it.item_code + '-' + itemIdx"
												draggable="true"
												title="Klik untuk atur jumlah atau seret ke koli lain"
												@dragstart="onDragStart($event, koliIdxOf(koli), itemIdx, it)"
												@dragend="onDragEnd"
												@dragover.prevent="onDragOver(koliIdxOf(koli))"
												@dragleave="onDragLeave(koliIdxOf(koli))"
												@drop.prevent="onDrop(koliIdxOf(koli))"
												@click="openMoveModal(koliIdxOf(koli), itemIdx, it)"
											>
												<td>{{ it.item_name }}</td>
												<td class="num">{{ it.qty }}</td>
												<td class="num">{{ it.uom || '' }}</td>
												<template v-if="itemIdx === 0">
													<td class="num ke-colly" :rowspan="koli.items.length">
														<div>Koli {{ koli.case_no }}/{{ totalPackages }}</div>
														<select v-model="koli.box_size" class="koli-box-select" title="Ukuran box (B/K)" aria-label="Ukuran box">
															<option value="">—</option>
															<option value="B">B</option>
															<option value="K">K</option>
														</select>
													</td>
													<td class="num ke-weight" :rowspan="koli.items.length"></td>
												</template>
											</tr>
										</template>
									</tbody>
								</table>
							</div>
						</div>
					</div>
					</div>
				</div>
			</div>

			<!-- State 2B: Fully Packed -> Submitted Packing Slips Card -->
			<div v-else class="panel slips-card">
				<div class="panel-head slips-head">
					<div class="slips-title-col">
						<PackageCheck :size="18" :stroke-width="2" class="pack-icon-done" />
						<span class="section-title">Packing Slip Terbit</span>
						<span class="badge b-done">Terkemas Lengkap</span>
					</div>

					<!-- Reset Button -->
					<div class="slips-actions">
						<button
							v-if="canResetPacking"
							type="button"
							class="btn btn-sm btn-ghost reset-btn"
							:disabled="busy"
							title="Batalkan Packing Slip dan reset ke 0"
							@click="onPromptReset"
						>
							<RotateCcw :size="13" :stroke-width="2" />
							<span>Reset packing</span>
						</button>
					</div>
				</div>

				<div class="slips-list">
					<div
						v-for="slip in submittedSlips"
						:key="slip.name"
						class="slip-item-card"
					>
						<div class="slip-item-header">
							<div class="slip-title-row">
								<PackageCheck :size="17" :stroke-width="2" class="slip-icon" />
								<span class="slip-name mono font-bold">{{ slip.name }}</span>
								<span v-if="slip.from_case_no" class="badge b-koli">
									Koli {{ slip.from_case_no }} / {{ slip.total_packages || submittedSlips.length }}
								</span>
								<span class="badge b-done">Submitted</span>
							</div>

							<a
								class="slip-audit-link"
								:href="`/app/packing-slip/${encodeURIComponent(slip.name)}`"
								target="_blank"
								rel="noopener"
								title="Buka dokumen di Desk"
							>
								<span>Buka di Desk</span>
								<ExternalLink :size="12" :stroke-width="2" />
							</a>
						</div>

						<div class="slip-meta-grid">
							<div class="slip-meta-item">
								<span class="sm-label">Tanggal Kemas</span>
								<span class="sm-val">{{ fmtDate(slip.creation || slip.modified) || '—' }}</span>
							</div>
							<div class="slip-meta-item">
								<span class="sm-label">Isi Kemasan</span>
								<span class="sm-val">{{ slip.items_count || 1 }} Item ({{ fmtQty(slip.items?.reduce((a, b) => a + Number(b.qty || 0), 0) || 0) }} Unit)</span>
							</div>
							<div class="slip-meta-item">
								<span class="sm-label">Nomor Paket</span>
								<span class="sm-val">Paket #{{ slip.from_case_no || 1 }}</span>
							</div>
						</div>

						<!-- Items breakdown in this package -->
						<div v-if="slip.items?.length" class="slip-items-summary">
							<span v-for="it in slip.items" :key="it.item_code" class="slip-item-pill">
								{{ it.item_name || it.item_code }} ({{ fmtQty(it.qty) }} pcs)
							</span>
						</div>
					</div>
				</div>
			</div>

			<!-- Action Footer (Single source of action buttons) -->
			<div class="panel-foot packing-footer">
				<div class="footer-left">
					<button type="button" class="btn btn-outline btn-sm" @click="$emit('go-delivery')">
						<ArrowLeft :size="14" :stroke-width="2" />
						<span>Kembali ke Surat Jalan</span>
					</button>
				</div>

				<div class="footer-actions">
					<button
						v-if="!isFullyPacked"
						type="button"
						class="btn btn-primary btn-pack-all"
						:disabled="busy || !canPackAll"
						@click="onPackAll"
					>
						<LoaderCircle v-if="busy" :size="16" :stroke-width="2" class="spin" />
						<span>{{ busy ? 'Mengemas Barang…' : `Kemas Barang (${totalPackages} Koli)` }}</span>
					</button>

					<button
						type="button"
						:class="isFullyPacked ? 'btn btn-primary' : 'btn btn-outline'"
						@click="$emit('go-review')"
					>
						<span>Lanjut ke Review & Kirim</span>
						<ArrowRight :size="15" :stroke-width="2" />
					</button>
				</div>
			</div>
		</template>

		<!-- Move Item Modal -->
		<Teleport to="body">
			<Transition name="fade">
				<div v-if="moveModalOpen" class="move-modal-layer" @click.self="moveModalOpen = false">
					<div class="move-modal-card" role="dialog" aria-modal="true" aria-labelledby="move-modal-title">
						<div class="move-modal-head">
							<div class="move-head-title">
								<ArrowRightLeft :size="16" class="move-icon" />
								<h4 id="move-modal-title">Pindahkan Barang Antar Koli</h4>
							</div>
							<button type="button" class="btn-modal-close" @click="moveModalOpen = false">
								<X :size="16" />
							</button>
						</div>

						<div class="move-modal-body">
							<div class="move-item-info">
								<span class="m-item-name">{{ moveState.item?.item_name }}</span>
								<span class="m-item-avail">
									Tersedia di <strong>Koli {{ moveState.sourceKoli?.case_no }}</strong>: {{ moveState.item?.qty }} Unit
								</span>
							</div>

							<!-- Qty to Move Input -->
							<div class="move-form-group">
								<label class="move-label">Jumlah Unit yang Dipindahkan:</label>
								<div class="move-qty-input-row">
									<input
										v-model.number="moveState.moveQty"
										type="number"
										min="1"
										:max="moveState.item?.qty"
										class="input input-sm move-number-input"
									/>
									<span class="move-uom-tag">Unit</span>
									<button type="button" class="btn btn-xs btn-outline" @click="setMovePercentage(50)">
										50%
									</button>
									<button type="button" class="btn btn-xs btn-outline" @click="setMovePercentage(100)">
										Semua (100%)
									</button>
								</div>
							</div>

							<!-- Target Koli Selection -->
							<div class="move-form-group">
								<label class="move-label">Pilih Koli Tujuan:</label>
								<div class="target-koli-options">
									<button
										v-for="target in moveState.eligibleTargets"
										:key="target.originalIdx"
										type="button"
										class="target-koli-btn"
										:class="{ 'is-selected': moveState.targetKoliIdx === target.originalIdx }"
										@click="moveState.targetKoliIdx = target.originalIdx"
									>
										<Package :size="14" />
										<span>Koli {{ target.case_no }}</span>
										<small>({{ target.items?.length || 0 }} Item · {{ target.total_qty }} Unit)</small>
									</button>
								</div>
							</div>
						</div>

						<div class="move-modal-foot">
							<button type="button" class="btn btn-sm" @click="moveModalOpen = false">
								Batal
							</button>
							<button type="button" class="btn btn-sm btn-primary" @click="confirmMove">
								<span>Pindahkan {{ moveState.moveQty }} Unit</span>
								<ArrowRight :size="13" />
							</button>
						</div>
					</div>
				</div>
			</Transition>
		</Teleport>

		<!-- Reset Confirmation Dialog -->
		<ConfirmDialog
			v-model="showResetConfirm"
			:options="resetConfirmOptions"
			:on-confirm="onConfirmReset"
		/>
	</div>
</template>

<style scoped>
.packing-panel {
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

.empty-inset {
	padding: 48px 24px;
	text-align: center;
	display: flex;
	flex-direction: column;
	align-items: center;
	gap: 8px;
}

.eico {
	color: #ea580c;
}

.etitle {
	font-size: 15px;
	font-weight: 700;
	color: var(--ink, #1e293b);
}

.ehint {
	font-size: 13px;
	color: var(--muted, #64748b);
	max-width: 440px;
}

/* Pack Action Card */
.pack-head {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 14px 20px;
	border-bottom: 1px solid var(--line, #e2e8f0);
}

.pack-title-col {
	display: flex;
	align-items: center;
	gap: 10px;
}

.pack-icon {
	color: var(--brand, #3368a0);
}

.pack-title {
	font-size: 14.5px;
	font-weight: 700;
	color: var(--ink, #1e293b);
}

.pack-body {
	padding: 20px;
	display: flex;
	flex-direction: column;
	gap: 16px;
}

.pack-meta-row {
	display: grid;
	grid-template-columns: repeat(3, minmax(0, 1fr));
	gap: 16px;
	padding: 14px 18px;
	background: var(--bg, #f8fafc);
	border-radius: 8px;
	border: 1px solid var(--line, #e2e8f0);
}

.pm-col {
	display: flex;
	flex-direction: column;
	gap: 2px;
}

.pm-label {
	font-size: 11px;
	font-weight: 700;
	text-transform: uppercase;
	color: var(--muted, #64748b);
}

.pm-val {
	font-size: 14px;
	color: var(--ink, #1e293b);
}

/* Package Configurator */
.package-config-section {
	display: flex;
	flex-direction: column;
	gap: 14px;
	padding-top: 4px;
}

.config-section-title {
	display: flex;
	flex-direction: column;
	gap: 3px;
}

.config-section-title strong {
	font-size: 13.5px;
	color: var(--ink, #1e293b);
}

.config-section-title span {
	font-size: 12.5px;
	color: var(--muted, #64748b);
}

.config-grid {
	display: grid;
	grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
	gap: 14px;
}

.pkg-category-card {
	border: 1px solid var(--line, #e2e8f0);
	border-radius: 10px;
	background: #ffffff;
	padding: 14px 16px;
	display: flex;
	flex-direction: column;
	gap: 12px;
	box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}

.pkg-cat-header {
	display: flex;
	align-items: center;
	justify-content: space-between;
}

.pkg-cat-count {
	font-size: 12.5px;
	font-weight: 600;
	color: var(--muted, #64748b);
}

.pkg-cat-body {
	display: flex;
	flex-direction: column;
	gap: 8px;
}

.pkg-counter-row {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 12px;
}

.pkg-counter-label {
	font-size: 13px;
	font-weight: 600;
	color: var(--ink, #1e293b);
}

.stepper-counter {
	display: inline-flex;
	align-items: center;
	border: 1px solid var(--line, #cbd5e1);
	border-radius: 6px;
	overflow: hidden;
	background: #ffffff;
}

.counter-btn {
	display: flex;
	align-items: center;
	justify-content: center;
	width: 32px;
	height: 30px;
	border: none;
	background: #f1f5f9;
	color: var(--ink, #1e293b);
	cursor: pointer;
	transition: background 0.15s;
}

.counter-btn:hover:not(:disabled) {
	background: #e2e8f0;
}

.counter-btn:disabled {
	opacity: 0.4;
	cursor: not-allowed;
}

.counter-val {
	min-width: 36px;
	text-align: center;
	font-size: 13.5px;
	font-weight: 750;
	color: var(--ink, #1e293b);
}

.pkg-hint {
	font-size: 11.5px;
	color: var(--muted, #64748b);
	line-height: 1.4;
}

.total-koli-summary {
	display: flex;
	align-items: center;
	gap: 8px;
	padding: 10px 14px;
	background: #eff6ff;
	border: 1px solid #bfdbfe;
	border-radius: 8px;
	font-size: 13px;
	color: #1e40af;
}

/* Live Simulation / Koli Allocation Preview */
.koli-preview-block {
	display: flex;
	flex-direction: column;
	gap: 10px;
	padding: 14px;
	background: #f8fafc;
	border: 1px dashed #cbd5e1;
	border-radius: 8px;
}

.koli-preview-head {
	display: flex;
	align-items: center;
	justify-content: space-between;
	flex-wrap: wrap;
	gap: 8px;
}

.koli-preview-title {
	display: flex;
	align-items: center;
	flex-wrap: wrap;
	gap: 8px;
	font-size: 13px;
	color: #1e293b;
}

.b-custom {
	background: #fef3c7;
	color: #b45309;
	font-weight: 700;
}

.b-auto {
	background: #f1f5f9;
	color: #475569;
	font-weight: 600;
}

.btn-reset-auto {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	font-size: 11px;
	padding: 3px 8px;
	border-color: #cbd5e1;
	color: #475569;
}

.btn-reset-auto :deep(svg),
.btn-reset-auto svg {
	flex-shrink: 0;
}

.btn-reset-auto:hover {
	background: #ffffff;
	color: #1e293b;
	border-color: #94a3b8;
}

.preview-sub-row {
	display: flex;
	align-items: center;
}

.preview-sub {
	font-size: 12px;
	color: #64748b;
}

.empty-koli-warning {
	display: flex;
	align-items: center;
	gap: 8px;
	padding: 8px 12px;
	background: #fffbeb;
	border: 1px solid #fde68a;
	border-radius: 6px;
	font-size: 12px;
	color: #b45309;
	font-weight: 500;
}

.preview-icon {
	color: var(--brand, #3368a0);
}

/* Excel-sheet allocation tables (ala packing sheet) */
.koli-excel-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; align-items: start; }
@media (max-width: 1000px) { .koli-excel-grid { grid-template-columns: 1fr; } }
.ke-title { background: #FFC000; border: 1.5px solid #111; border-bottom: 0; text-align: center; font-weight: 700; font-size: 12px; letter-spacing: 1px; padding: 4px; }
.ke-tbl { width: 100%; border-collapse: collapse; font-size: 12px; }
.ke-tbl th, .ke-tbl td { border: 1px solid #111; padding: 3px 6px; text-align: left; }
.ke-tbl th { background: #FFC000; font-size: 11px; font-weight: 700; text-align: center; }
.ke-tbl .num { text-align: center; }
.ke-tbl tbody tr[draggable='true'] { cursor: grab; }
.ke-tbl tbody tr[draggable='true']:hover { background: #fff8d6; }
.ke-colly { min-width: 90px; vertical-align: middle; }
.ke-colly .koli-box-select { margin-top: 4px; }
.ke-weight { min-width: 80px; }
.ke-empty td { text-align: center; color: #888; font-style: italic; background: #fafafa; }

.koli-preview-grid {
	display: flex;
	flex-direction: column;
	gap: 8px;
}

.koli-sim-card {
	background: #ffffff;
	border: 1px solid #e2e8f0;
	border-radius: 6px;
	padding: 10px 12px;
	display: flex;
	flex-direction: column;
	gap: 8px;
	transition: all 0.15s ease;
}

.drop-target-active {
	border: 2px dashed #2563eb !important;
	background: #f0f7ff !important;
	box-shadow: 0 4px 12px rgba(37, 99, 235, 0.12);
}

.koli-card-empty {
	border-style: dashed;
	background: #fafafa;
}

.empty-koli-dropzone {
	padding: 14px;
	text-align: center;
	border: 1px dashed #cbd5e1;
	border-radius: 6px;
	color: #94a3b8;
	font-size: 12px;
	font-style: italic;
	background: #ffffff;
}

.koli-sim-head {
	display: flex;
	align-items: center;
	justify-content: space-between;
}

.koli-sim-meta {
	display: flex;
	align-items: center;
	gap: 8px;
}

.koli-num-badge {
	font-size: 12px;
	font-weight: 700;
	background: #1e293b;
	color: #ffffff;
	padding: 2px 8px;
	border-radius: 4px;
}

.koli-box-select {
	font-size: 12px;
	font-weight: 700;
	padding: 2px 4px;
	border: 1px solid #cbd5e1;
	border-radius: 4px;
	background: #ffffff;
	color: #1e293b;
}

.koli-sim-count {
	font-size: 12px;
	color: #64748b;
	font-weight: 600;
}

.koli-sim-items {
	display: flex;
	flex-wrap: wrap;
	gap: 6px;
}

.draggable-pill {
	cursor: grab;
	user-select: none;
	display: inline-flex;
	align-items: center;
	gap: 4px;
	transition: all 0.15s ease;
}

.draggable-pill:hover {
	border-color: #3b82f6 !important;
	background: #eff6ff !important;
	transform: translateY(-1px);
	box-shadow: 0 2px 5px rgba(0, 0, 0, 0.08);
}

.draggable-pill:active {
	cursor: grabbing;
	opacity: 0.6;
}

.grip-icon {
	color: #94a3b8;
	flex-shrink: 0;
}

/* Click-to-Move Modal */
.move-modal-layer {
	position: fixed;
	inset: 0;
	z-index: 1050;
	background: rgba(15, 23, 42, 0.5);
	backdrop-filter: blur(2px);
	display: flex;
	align-items: center;
	justify-content: center;
	padding: 16px;
}

.move-modal-card {
	background: #ffffff;
	border-radius: 12px;
	width: 100%;
	max-width: 440px;
	box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.15);
	display: flex;
	flex-direction: column;
	overflow: hidden;
}

.move-modal-head {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 14px 18px;
	border-bottom: 1px solid #e2e8f0;
}

.move-head-title {
	display: flex;
	align-items: center;
	gap: 8px;
}

.move-head-title h4 {
	font-size: 14.5px;
	font-weight: 700;
	color: #1e293b;
	margin: 0;
}

.move-icon {
	color: var(--brand, #3368a0);
}

.btn-modal-close {
	background: transparent;
	border: none;
	color: #64748b;
	cursor: pointer;
	padding: 4px;
	display: flex;
	align-items: center;
	justify-content: center;
	border-radius: 4px;
}

.btn-modal-close:hover {
	background: #f1f5f9;
	color: #1e293b;
}

.move-modal-body {
	padding: 18px;
	display: flex;
	flex-direction: column;
	gap: 16px;
}

.move-item-info {
	display: flex;
	flex-direction: column;
	gap: 4px;
	padding: 10px 14px;
	background: #f8fafc;
	border: 1px solid #e2e8f0;
	border-radius: 6px;
}

.m-item-name {
	font-size: 13.5px;
	font-weight: 700;
	color: #1e293b;
}

.m-item-avail {
	font-size: 12px;
	color: #64748b;
}

.move-form-group {
	display: flex;
	flex-direction: column;
	gap: 6px;
}

.move-label {
	font-size: 12px;
	font-weight: 600;
	color: #475569;
}

.move-qty-input-row {
	display: flex;
	align-items: center;
	gap: 8px;
}

.move-number-input {
	max-width: 110px;
	font-weight: 650;
	font-size: 14px;
}

.move-uom-tag {
	font-size: 12px;
	color: #64748b;
	font-weight: 500;
}

.target-koli-options {
	display: grid;
	grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
	gap: 8px;
}

.target-koli-btn {
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	padding: 10px 8px;
	border: 1.5px solid #cbd5e1;
	border-radius: 8px;
	background: #ffffff;
	cursor: pointer;
	gap: 4px;
	color: #1e293b;
	transition: all 0.15s ease;
}

.target-koli-btn:hover {
	border-color: #3b82f6;
	background: #eff6ff;
}

.target-koli-btn.is-selected {
	border-color: #2563eb;
	background: #eff6ff;
	color: #1d4ed8;
	font-weight: 700;
	box-shadow: 0 0 0 1px #2563eb;
}

.target-koli-btn small {
	font-size: 10.5px;
	color: #64748b;
}

.move-modal-foot {
	display: flex;
	align-items: center;
	justify-content: flex-end;
	gap: 10px;
	padding: 12px 18px;
	background: #f8fafc;
	border-top: 1px solid #e2e8f0;
}

.b-dry {
	background: #e0f2fe;
	color: #0369a1;
	font-weight: 700;
}

.b-frozen {
	background: #e0e7ff;
	color: #4338ca;
	font-weight: 700;
}

.b-koli {
	background: #fef3c7;
	color: #b45309;
	font-weight: 700;
}

.slip-items-summary {
	display: flex;
	flex-wrap: wrap;
	gap: 6px;
	margin-top: 4px;
}

.slip-item-pill {
	display: inline-flex;
	align-items: center;
	font-size: 11.5px;
	padding: 2px 8px;
	background: #ffffff;
	border: 1px solid var(--line, #e2e8f0);
	border-radius: 4px;
	color: #334155;
}

/* Slips Card */
.slips-head {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 14px 20px;
	border-bottom: 1px solid var(--line, #e2e8f0);
}

.slips-title-col {
	display: flex;
	align-items: center;
	gap: 10px;
}

.pack-icon-done {
	color: #059669;
}

.section-title {
	font-size: 14.5px;
	font-weight: 700;
	color: var(--ink, #1e293b);
}

.reset-btn {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	color: #dc2626;
	border: 1px solid #fecaca;
	background: #ffffff;
}

.reset-btn :deep(svg),
.reset-btn svg {
	flex-shrink: 0;
}

.reset-btn:hover:not(:disabled) {
	background: #fef2f2;
	border-color: #f87171;
}

.slips-list {
	padding: 16px 20px;
	display: flex;
	flex-direction: column;
	gap: 10px;
}

.slip-item-card {
	border: 1px solid var(--line, #e2e8f0);
	border-radius: 8px;
	padding: 14px 18px;
	background: #ffffff;
	display: flex;
	flex-direction: column;
	gap: 10px;
	transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.slip-item-card:hover {
	border-color: #cbd5e1;
	box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.slip-item-header {
	display: flex;
	align-items: center;
	justify-content: space-between;
}

.slip-title-row {
	display: flex;
	align-items: center;
	gap: 8px;
}

.slip-icon {
	color: #059669;
}

.slip-name {
	font-size: 14px;
	font-weight: 750;
	color: var(--ink, #1e293b);
}

.slip-audit-link {
	display: inline-flex;
	align-items: center;
	gap: 4px;
	font-size: 11.5px;
	color: var(--brand, #3368a0);
	text-decoration: none;
}

.slip-meta-grid {
	display: flex;
	align-items: center;
	gap: 28px;
	font-size: 12.5px;
}

.sm-label {
	color: var(--muted, #64748b);
	margin-right: 6px;
}

.sm-val {
	font-weight: 600;
	color: var(--ink, #1e293b);
}

/* Footer */
.packing-footer {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 16px 20px;
	background: #ffffff;
	border: 1px solid var(--line, #e2e8f0);
	border-radius: 12px;
}

.btn-pack-all {
	display: inline-flex;
	align-items: center;
	gap: 8px;
	padding: 9px 20px;
	font-weight: 650;
	border-radius: 8px;
}
</style>