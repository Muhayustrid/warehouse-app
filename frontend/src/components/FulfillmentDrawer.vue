<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
	AlertTriangle,
	Check,
	ChevronDown,
	ExternalLink,
	LoaderCircle,
	Package,
	Printer,
	RefreshCw,
	X,
} from 'lucide-vue-next'
import {
	completePicking,
	createDeliveryNote,
	fetchOrderPreview,
	fetchRunWorkspace,
	generateFulfillmentRun,
	packAll,
	resetPacking,
	savePicking,
	stageLabel,
	submitDeliveryNote,
} from '@/data/fulfillment'
import { fmtDate, fmtQty } from '@/lib/format'
import { toast } from '@/lib/toast'

import SplitConfirmationModal from '@/components/fulfillment/SplitConfirmationModal.vue'
import PickingPanel from '@/components/fulfillment/PickingPanel.vue'
import DeliveryPanel from '@/components/fulfillment/DeliveryPanel.vue'
import PackingPanel from '@/components/fulfillment/PackingPanel.vue'
import ReviewPanel from '@/components/fulfillment/ReviewPanel.vue'

const props = defineProps({
	open: { type: Boolean, default: false },
	salesOrder: { type: String, default: null },
})
const emit = defineEmits(['close', 'generated'])

const data = ref(null)
const workspace = ref(null)

const enablePackingSlip = computed(() => {
	const prof = workspace.value?.profile || data.value?.profile
	if (!prof) return true
	if (prof.enable_packing_slip === 0 || prof.enable_packing_slip === false || prof.enable_packing_slip === '0') {
		return false
	}
	return true
})

const STEPS = computed(() => {
	if (!enablePackingSlip.value) {
		return [
			{ key: 'picking', label: '1. Picking' },
			{ key: 'delivery', label: '2. Delivery' },
			{ key: 'review', label: '3. Review' },
		]
	}
	return [
		{ key: 'picking', label: '1. Picking' },
		{ key: 'delivery', label: '2. Delivery' },
		{ key: 'packing', label: '3. Packing' },
		{ key: 'review', label: '4. Review' },
	]
})
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const closeBtn = ref(null)
const drawer = ref(null)
const generating = ref(false)
const generateError = ref('')
const idempotencyKey = ref('')
const activeTab = ref('picking')
const showSplitModal = ref(false)
const reviewPanelRef = ref(null)

let loadToken = 0

const REASON_LABELS = {
	PROFILE_INVALID: 'Fulfillment profile is invalid.',
	PROFILE_DISABLED: 'Fulfillment profile is disabled.',
	PROFILE_MISSING: 'Fulfillment profile is not configured.',
	GENERATE_PERMISSION: 'You do not have permission to generate Pick Lists.',
	SO_NOT_ELIGIBLE: 'This Sales Order is not eligible for generation.',
	NO_OUTSTANDING: 'There is no outstanding quantity to pick.',
	STOCK_RESERVED: 'Stock is reserved; release it before generating.',
	ITEM_GROUP_MISSING: 'An item has no valid Item Group.',
	ITEM_NOT_PICKABLE: 'An item is not pickable.',
}
const GROUP_LABELS = {
	dry: 'Dry',
	frozen: 'Frozen',
	unclassified: 'Needs attention',
}
const DOC_GROUPS = [
	{ key: 'pick_lists', label: 'Pick Lists', doctype: 'Pick List' },
	{ key: 'delivery_notes', label: 'Delivery Notes', doctype: 'Delivery Note' },
	{ key: 'packing_slips', label: 'Packing Slips', doctype: 'Packing Slip' },
]
const DOC_SLUGS = {
	'Pick List': 'pick-list',
	'Delivery Note': 'delivery-note',
	'Packing Slip': 'packing-slip',
}
const REASONS = {
	profile_missing: 'Fulfillment profile is not configured.',
	profile_disabled: 'Fulfillment profile is disabled.',
	profile_invalid: 'Fulfillment profile is invalid.',
	item_group_missing: 'Item Group is missing or unknown.',
}

const ACTION_REASONS = {
	NO_PICK_LIST: 'No active Pick Lists exist.',
	PL_NOT_SUBMITTED: 'All Pick Lists must be submitted first.',
	SHORT_PICK_BLOCKED: 'Short pick is blocked by policy.',
	SHORT_PICK_APPROVAL_PENDING: 'Waiting for short-pick approval.',
	SHORT_PICK_APPROVAL_REJECTED: 'Short pick request was rejected.',
	SHORT_PICK_STALE_APPROVAL: 'Pick quantities changed since approval.',
}

const dryLabel = computed(
	() =>
		workspace.value?.profile?.dry_display_name ||
		data.value?.profile?.dry_display_name ||
		'Dry',
)
const frozenLabel = computed(
	() =>
		workspace.value?.profile?.frozen_display_name ||
		data.value?.profile?.frozen_display_name ||
		'Frozen',
)
const groups = computed(() =>
	['dry', 'frozen', 'unclassified'].map((key) => ({
		key,
		label:
			key === 'dry'
				? dryLabel.value
				: key === 'frozen'
					? frozenLabel.value
					: GROUP_LABELS[key],
		items: data.value?.groups?.[key] || [],
	})),
)

const activeRunName = computed(() => {
	if (workspace.value?.run?.name) return workspace.value.run.name
	if (data.value?.run?.name) return data.value.run.name
	if (typeof data.value?.run === 'string') return data.value.run
	return null
})
const hasActiveRun = computed(() => Boolean(activeRunName.value))
const isWorkspaceMode = computed(() => Boolean(workspace.value?.run))

const canGenerate = computed(
	() =>
		Boolean(data.value?.can_generate) &&
		!generating.value &&
		!hasActiveRun.value,
)
const generateDisabledReason = computed(
	() =>
		REASON_LABELS[data.value?.can_generate_reason] ||
		data.value?.can_generate_reason ||
		(hasActiveRun.value ? 'An active Fulfillment Run already exists.' : ''),
)

onMounted(() => {
	window.addEventListener('keydown', onKey)
})

onBeforeUnmount(() => {
	window.removeEventListener('keydown', onKey)
	document.body.style.overflow = ''
})

watch(
	() => [props.open, props.salesOrder],
	async ([open, salesOrder]) => {
		if (!open || !salesOrder) {
			loadToken += 1
			data.value = null
			workspace.value = null
			error.value = ''
			generateError.value = ''
			generating.value = false
			showSplitModal.value = false
			idempotencyKey.value = ''
			loading.value = false
			document.body.style.overflow = ''
			return
		}
		document.body.style.overflow = 'hidden'
		idempotencyKey.value = newIdempotencyKey()
		generateError.value = ''
		activeTab.value = 'picking'

		await loadInitial(salesOrder)
		await nextTick()
		closeBtn.value?.focus()
	},
	{ immediate: true },
)

async function loadInitial(salesOrder) {
	if (!salesOrder) return
	const token = ++loadToken
	loading.value = true
	error.value = ''
	try {
		const res = await fetchOrderPreview(salesOrder)
		if (token !== loadToken) return
		data.value = res

		const existingRun = res.run?.name || (typeof res.run === 'string' ? res.run : null)
		if (existingRun) {
			const ws = await fetchRunWorkspace(existingRun)
			if (token !== loadToken) return
			workspace.value = ws
			syncTabToRunState(ws)
		} else {
			workspace.value = null
		}
	} catch (e) {
		if (token !== loadToken) return
		error.value = e.message || 'Failed to load details.'
	} finally {
		if (token === loadToken) {
			loading.value = false
		}
	}
}

async function refreshWorkspace() {
	if (!activeRunName.value) {
		await loadInitial(props.salesOrder)
		return
	}
	try {
		const ws = await fetchRunWorkspace(activeRunName.value)
		workspace.value = ws
		syncTabToRunState(ws)
	} catch (e) {
		toast.error(e.message || 'Failed to refresh workspace.')
	}
}

function syncTabToRunState(ws) {
	if (!ws) return
	const actionKey = ws.next_action?.key || ws.next_action?.action
	if (actionKey === 'create_delivery_note') {
		activeTab.value = 'delivery'
	} else if (actionKey === 'pack_all') {
		activeTab.value = 'packing'
	} else if (actionKey === 'submit_delivery_note' || actionKey === 'done') {
		activeTab.value = 'review'
	} else {
		activeTab.value = 'picking'
	}
}

function close() {
	emit('close')
}

async function generate() {
	if (!canGenerate.value || !props.salesOrder) return
	if (!idempotencyKey.value) {
		idempotencyKey.value = newIdempotencyKey()
	}
	generating.value = true
	generateError.value = ''
	try {
		const result = await generateFulfillmentRun({
			salesOrder: props.salesOrder,
			idempotencyKey: idempotencyKey.value,
			expectedSoModified:
				data.value?.modified || data.value?.sales_order?.modified || '',
		})

		const runName = typeof result?.run === 'string' ? result.run : (result?.run?.name || result?.name)
		if (runName) {
			const ws = await fetchRunWorkspace(runName)
			workspace.value = ws
			showSplitModal.value = true
			activeTab.value = 'picking'
		}

		emit('generated', result)
		toast.success(
			result.reused
				? 'Existing Fulfillment Run reused.'
				: 'Draft Dry/Frozen Pick Lists generated.',
		)
	} catch (e) {
		const message = e.message || 'Failed to generate Pick Lists.'
		if (message.startsWith('SO_CHANGED')) {
			idempotencyKey.value = newIdempotencyKey()
			await loadInitial(props.salesOrder)
			generateError.value = 'The Sales Order changed. Review the refreshed detail and try again.'
		} else {
			generateError.value = generateErrorMessage(message)
		}
		toast.error(generateError.value)
	} finally {
		generating.value = false
	}
}

function printSingle(groupKey) {
	const group = workspace.value?.groups?.[groupKey]
	if (!group?.pick_list) {
		toast.error(`No ${groupKey} Pick List available.`)
		return
	}
	const formatKey = groupKey === 'dry' ? 'dry_print_format' : 'frozen_print_format'
	const format = workspace.value?.profile?.[formatKey]
	let url = `/printview?doctype=Pick List&name=${encodeURIComponent(group.pick_list)}`
	if (format) {
		url += `&format=${encodeURIComponent(format)}`
	}
	window.open(url, '_blank', 'noopener')
}

function printBoth() {
	if (workspace.value?.groups?.dry?.pick_list) {
		printSingle('dry')
	}
	if (workspace.value?.groups?.frozen?.pick_list) {
		setTimeout(() => {
			printSingle('frozen')
		}, 300)
	}
}

// Stepper status helpers
function isStepComplete(stepKey) {
	if (!workspace.value) return false
	if (stepKey === 'picking') {
		const drySubmitted =
			!workspace.value.groups?.dry?.pick_list ||
			workspace.value.groups.dry.docstatus === 1
		const frozenSubmitted =
			!workspace.value.groups?.frozen?.pick_list ||
			workspace.value.groups.frozen.docstatus === 1
		return (
			drySubmitted &&
			frozenSubmitted &&
			Boolean(
				workspace.value.groups?.dry?.pick_list ||
				workspace.value.groups?.frozen?.pick_list,
			)
		)
	}
	if (stepKey === 'delivery') {
		return Boolean(workspace.value.delivery_note)
	}
	if (stepKey === 'packing') {
		return Boolean(workspace.value.packing?.fully_packed)
	}
	if (stepKey === 'review') {
		return workspace.value.run?.status === 'DISPATCHED'
	}
	return false
}

function getStepStatus(stepKey) {
	if (isStepComplete(stepKey)) return 'Selesai'
	if (activeTab.value === stepKey) return 'Aktif'
	return 'Menunggu'
}

// Workspace panel action handlers
async function handleSavePicking({ rows, expected_modified }) {
	if (busy.value || loading.value) return
	busy.value = true
	try {
		await savePicking(workspace.value.run.name, rows, expected_modified)
		toast.success('Picking quantities saved.')
		await refreshWorkspace()
	} catch (e) {
		toast.error(e.message || 'Failed to save picking.')
	} finally {
		busy.value = false
	}
}

async function handleFinishPicking(payload = {}) {
	if (busy.value || loading.value) return
	const shortPickReason = payload?.short_pick_reason || null
	if (workspace.value?.short_pick?.blocker && !shortPickReason) {
		toast.error(ACTION_REASONS[workspace.value.short_pick.blocker] || workspace.value.short_pick.blocker)
		activeTab.value = 'picking'
		return
	}
	busy.value = true
	try {
		if (payload?.rows && payload.rows.length) {
			await savePicking(workspace.value.run.name, payload.rows, payload.expected_modified)
			await refreshWorkspace()
		}

		let expectedModified = payload?.expected_modified
		if (!expectedModified || (payload?.rows && payload.rows.length)) {
			expectedModified = {}
			for (const group of [workspace.value?.groups?.dry, workspace.value?.groups?.frozen]) {
				if (group?.pick_list && group.docstatus === 0 && group.modified) {
					expectedModified[group.pick_list] = group.modified
				}
			}
		}
		await completePicking(workspace.value.run.name, expectedModified, shortPickReason)
		toast.success(shortPickReason ? 'Picking completed with short stock note.' : 'Picking completed successfully.')
		await refreshWorkspace()
		activeTab.value = 'delivery'
	} catch (e) {
		toast.error(e.message || 'Failed to finish picking.')
	} finally {
		busy.value = false
	}
}

async function handleCreateDeliveryNote() {
	if (busy.value || loading.value) return
	busy.value = true
	try {
		const key = newIdempotencyKey()
		await createDeliveryNote(workspace.value.run.name, key)
		toast.success('Delivery Note created.')
		await refreshWorkspace()
		activeTab.value = enablePackingSlip.value ? 'packing' : 'review'
	} catch (e) {
		toast.error(e.message || 'Failed to create Delivery Note.')
	} finally {
		busy.value = false
	}
}

async function handlePackAll() {
	if (busy.value || loading.value) return
	busy.value = true
	try {
		await packAll(workspace.value.run.name, workspace.value.delivery_note?.modified)
		toast.success('All items packed.')
		await refreshWorkspace()
		if (workspace.value?.packing?.fully_packed) {
			activeTab.value = 'review'
		}
	} catch (e) {
		toast.error(e.message || 'Failed to pack items.')
	} finally {
		busy.value = false
	}
}

async function handleResetPacking() {
	if (busy.value || loading.value) return
	busy.value = true
	try {
		await resetPacking(workspace.value.run.name, workspace.value.delivery_note?.modified)
		toast.success('Packing reset.')
		await refreshWorkspace()
	} catch (e) {
		toast.error(e.message || 'Failed to reset packing.')
	} finally {
		busy.value = false
	}
}

async function handleSubmitDeliveryNote() {
	if (busy.value || loading.value) return
	busy.value = true
	try {
		const key = newIdempotencyKey()
		await submitDeliveryNote(
			workspace.value.run.name,
			key,
			workspace.value.delivery_note?.modified,
		)
		toast.success('Delivery Note submitted. Run dispatched.')
		await refreshWorkspace()
	} catch (e) {
		toast.error(e.message || 'Failed to submit Delivery Note.')
	} finally {
		busy.value = false
	}
}

function generateErrorMessage(message) {
	const code = String(message).split(':')[0]
	const labels = {
		STOCK_SHORTAGE: 'Stock is insufficient for this Sales Order.',
		PROFILE_DISABLED: 'The Fulfillment profile is disabled.',
		PROFILE_MISSING: 'The Fulfillment profile is not configured.',
		PROFILE_INVALID: 'The Fulfillment profile is invalid.',
		ITEM_GROUP_MISSING: 'An item has no valid Item Group.',
		GENERATE_PERMISSION: 'You do not have permission to generate Pick Lists.',
		STALE_SO: 'Reload the Sales Order before generating.',
		IDEMPOTENCY_MISMATCH: 'This request was already used for different data. Reload and try again.',
	}
	return labels[code] || message
}

function newIdempotencyKey() {
	if (typeof crypto !== 'undefined' && crypto.randomUUID) {
		return crypto.randomUUID()
	}
	return `w49-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`
}

function onKey(event) {
	if (props.open && event.key === 'Escape') {
		if (showSplitModal.value) {
			showSplitModal.value = false
			return
		}
		close()
	}
}

function openNative(doctype, name) {
	const slug = DOC_SLUGS[doctype]
	if (!slug) return
	window.open(`/app/${slug}/${encodeURIComponent(name)}`, '_blank', 'noopener')
}

function statusText(doc) {
	return doc?.docstatus === 0 ? 'Draft' : 'Submitted'
}

function reasonText(reason) {
	return REASONS[reason] || reason || ''
}
</script>

<template>
	<Teleport to="body">
		<Transition name="ff-drawer">
			<div v-if="open" class="ff-drawer-layer" @click.self="close">
				<aside
					ref="drawer"
					class="ff-drawer"
					:class="{ 'ff-drawer-wide': isWorkspaceMode }"
					role="dialog"
					aria-modal="true"
					aria-labelledby="ff-drawer-title"
				>
					<!-- Drawer Header -->
					<header class="ff-drawer-head">
						<div class="ff-drawer-title">
							<p class="ff-eyebrow">
								Sales Order
								<span v-if="workspace?.run?.name"> · Run {{ workspace.run.name }}</span>
							</p>
							<h2 id="ff-drawer-title">
								{{ salesOrder }}
								<a
									class="ff-so-desk-link"
									:href="`/app/sales-order/${encodeURIComponent(salesOrder)}`"
									target="_blank"
									rel="noopener"
									title="Buka Sales Order di Desk"
								>
									<ExternalLink :size="14" :stroke-width="2" />
								</a>
							</h2>
							<p v-if="workspace || data" class="ff-drawer-customer">
								{{ (workspace?.sales_order?.customer_name || data?.sales_order?.customer_name || workspace?.run?.customer || data?.sales_order?.customer) }}
								<span v-if="workspace?.run?.company || data?.sales_order?.company">
									· {{ workspace?.run?.company || data?.sales_order?.company }}
								</span>
								<span v-if="workspace?.run?.delivery_date || data?.sales_order?.delivery_date">
									· Pengiriman: {{ fmtDate(workspace?.run?.delivery_date || data?.sales_order?.delivery_date) }}
								</span>
							</p>
						</div>

						<div class="ff-drawer-actions">
							<span
								v-if="workspace?.run?.status"
								class="badge"
								:class="workspace.run.status === 'DISPATCHED' ? 'b-done' : 'b-run'"
							>
								{{ workspace.run.status }}
							</span>
							<span v-else-if="data" class="ff-stage" :class="`ff-stage-${data.stage}`">
								{{ stageLabel(data.stage) }}
							</span>

							<button
								v-if="isWorkspaceMode"
								type="button"
								class="btn iconbtn"
								title="Muat ulang area kerja"
								:disabled="loading || busy"
								@click="refreshWorkspace"
							>
								<RefreshCw :size="14" :stroke-width="2" :class="{ spin: loading || busy }" />
							</button>

							<button
								ref="closeBtn"
								type="button"
								class="btn iconbtn"
								aria-label="Tutup"
								@click="close"
							>
								<X :size="16" :stroke-width="2" />
							</button>
						</div>
					</header>

					<!-- Progress Stepper (Shown only when in Workspace Mode) -->
					<nav v-if="isWorkspaceMode" class="ff-stepper" aria-label="Progress Tahapan Fulfillment">
						<div
							v-for="(step, idx) in STEPS"
							:key="step.key"
							class="ff-step-wrapper"
						>
							<button
								type="button"
								class="ff-step-btn"
								:class="{
									'is-active': activeTab === step.key,
									'is-complete': isStepComplete(step.key),
								}"
								@click="activeTab = step.key"
							>
								<div class="ff-step-circle">
									<Check v-if="isStepComplete(step.key)" :size="13" :stroke-width="2.6" />
									<span v-else>{{ idx + 1 }}</span>
								</div>
								<div class="ff-step-info">
									<span class="ff-step-label">{{ step.label }}</span>
									<span class="ff-step-status">{{ getStepStatus(step.key) }}</span>
								</div>
							</button>
							<div v-if="idx < STEPS.length - 1" class="ff-step-divider" :class="{ 'is-complete': isStepComplete(step.key) }" />
						</div>
					</nav>

					<!-- Drawer Body -->
					<div class="ff-drawer-body">
						<!-- Loading -->
						<div v-if="loading && !workspace && !data" class="ff-drawer-loading" aria-label="Loading detail">
							<div class="ff-skel ff-skel-title"></div>
							<div class="ff-skel"></div>
							<div class="ff-skel"></div>
							<div class="ff-skel"></div>
						</div>

						<!-- Error -->
						<div v-else-if="error" class="ff-drawer-state ff-error" role="alert">
							<AlertTriangle :size="22" :stroke-width="1.8" />
							<div>
								<strong>Gagal memuat detail</strong>
								<p>{{ error }}</p>
							</div>
							<button type="button" class="btn btn-sm" @click="loadInitial(salesOrder)">
								<RefreshCw :size="14" :stroke-width="2" />
								Coba lagi
							</button>
						</div>

						<!-- WORKSPACE MODE PANELS (WHEN RUN EXISTS) -->
						<template v-else-if="isWorkspaceMode">
							<!-- Tab 1: Picking -->
							<PickingPanel
								v-if="activeTab === 'picking'"
								:workspace="workspace"
								:busy="busy"
								@refresh="refreshWorkspace"
								@save-picking="handleSavePicking"
								@finish-picking="handleFinishPicking"
								@request-approval="handleRequestApproval"
								@approve-short-pick="handleApproveShortPick"
								@reject-short-pick="handleRejectShortPick"
							/>

							<!-- Tab 2: Delivery -->
							<DeliveryPanel
								v-else-if="activeTab === 'delivery'"
								:workspace="workspace"
								:busy="busy"
								@create-dn="handleCreateDeliveryNote"
								@go-packing="activeTab = 'packing'"
								@go-review="activeTab = 'review'"
								@go-picking="activeTab = 'picking'"
								@refresh="refreshWorkspace"
							/>

							<!-- Tab 3: Packing -->
							<PackingPanel
								v-else-if="activeTab === 'packing' && enablePackingSlip"
								:workspace="workspace"
								:busy="busy"
								@pack-all="handlePackAll"
								@reset-packing="handleResetPacking"
								@go-delivery="activeTab = 'delivery'"
								@go-review="activeTab = 'review'"
								@refresh="refreshWorkspace"
							/>

							<!-- Tab 4: Review -->
							<ReviewPanel
								v-else-if="activeTab === 'review'"
								ref="reviewPanelRef"
								:workspace="workspace"
								:busy="busy"
								@submit-dn="handleSubmitDeliveryNote"
								@go-packing="activeTab = 'packing'"
								@go-delivery="activeTab = 'delivery'"
								@refresh="refreshWorkspace"
							/>
						</template>

						<!-- PREVIEW MODE (BEFORE RUN GENERATION) -->
						<template v-else-if="data">
							<!-- Metadata -->
							<div class="ff-meta">
								<div>
									<span>Tanggal SO</span>
									<strong>{{ fmtDate(data.sales_order?.transaction_date) || '—' }}</strong>
								</div>
								<div>
									<span>Tanggal Pengiriman</span>
									<strong>{{ fmtDate(data.sales_order?.delivery_date) || '—' }}</strong>
								</div>
								<div>
									<span>Status Native</span>
									<strong>{{ data.sales_order?.status || '—' }}</strong>
								</div>
							</div>

							<!-- Summary -->
							<div class="ff-summary">
								<div class="ff-summary-item ff-summary-dry">
									<span>Item {{ dryLabel }}</span>
									<strong>{{ data.groups.dry.length }}</strong>
								</div>
								<div class="ff-summary-item ff-summary-frozen">
									<span>Item {{ frozenLabel }}</span>
									<strong>{{ data.groups.frozen.length }}</strong>
								</div>
								<div class="ff-summary-item ff-summary-warn">
									<span>Perlu Perhatian</span>
									<strong>{{ data.groups.unclassified.length }}</strong>
								</div>
							</div>

							<!-- Warnings -->
							<div v-if="data.warnings?.length" class="ff-inline-warn" role="status">
								<AlertTriangle :size="15" :stroke-width="2" />
								<span v-for="warning in data.warnings" :key="warning">{{ reasonText(warning) }}</span>
							</div>

							<!-- Generate Row -->
							<section class="ff-section ff-run-section">
								<div class="ff-section-head">
									<h3>Fulfillment Run</h3>
								</div>

								<div class="ff-generate-row">
									<button
										type="button"
										class="btn btn-primary ff-generate-btn"
										:disabled="!canGenerate || generating"
										@click="generate"
									>
										<LoaderCircle
											v-if="generating"
											:size="14"
											:stroke-width="2"
											class="spin"
										/>
										{{ generating ? 'Membuat Pick List…' : 'Generate Pick Lists' }}
									</button>
									<p v-if="!canGenerate && !generating" class="ff-muted ff-generate-reason">
										{{ generateDisabledReason || 'Order ini belum dapat diproses.' }}
									</p>
									<p v-else class="ff-muted ff-generate-reason">
										Membuat Pick List Dry & Frozen secara terpisah tanpa memindahkan stok gudang.
									</p>
								</div>
								<p v-if="generateError" class="ff-generate-error" role="alert">
									{{ generateError }}
								</p>
							</section>

							<!-- DAFTAR ITEM LENGKAP SALES ORDER (DRY & FROZEN) -->
							<section v-for="group in groups" :key="group.key" class="ff-section">
								<template v-if="group.items.length || group.key !== 'unclassified'">
									<div class="ff-section-head">
										<h3>Daftar Item {{ group.label }}</h3>
										<span class="ff-count">{{ group.items.length }} Item</span>
									</div>
									<div v-if="group.items.length" class="ff-items">
										<div class="ff-items-head">
											<span>Item</span>
											<span>UOM</span>
											<span>Dipesan</span>
											<span>Terkirim</span>
											<span>Sisa Pick</span>
										</div>
										<div v-for="item in group.items" :key="item.sales_order_item" class="ff-item-row">
											<div class="ff-item-main">
												<strong>{{ item.item_name || item.item_code }}</strong>
												<span>{{ item.item_code }} · {{ item.item_group || 'No Item Group' }}</span>
												<span v-if="item.reason" class="ff-item-reason">{{ reasonText(item.reason) }}</span>
											</div>
											<span data-label="UOM">{{ item.uom || '—' }}</span>
											<span data-label="Ordered">{{ fmtQty(item.ordered) }}</span>
											<span data-label="Delivered">{{ fmtQty(item.delivered) }}</span>
											<span data-label="Outstanding">{{ fmtQty(item.outstanding) }}</span>
										</div>
									</div>
									<p v-else class="ff-muted">Tidak ada item {{ group.label.toLowerCase() }}.</p>
								</template>
							</section>

							<!-- Dokumen Terkait -->
							<section class="ff-section">
								<div class="ff-section-head">
									<h3>Dokumen Terkait</h3>
								</div>
								<div v-for="docGroup in DOC_GROUPS" :key="docGroup.key" class="ff-doc-group">
									<h4>{{ docGroup.label }}</h4>
									<div v-if="data.documents[docGroup.key]?.length" class="ff-doc-list">
										<button
											v-for="doc in data.documents[docGroup.key]"
											:key="doc.name"
											type="button"
											class="ff-doc-row"
											@click="openNative(docGroup.doctype, doc.name)"
										>
											<span class="ff-doc-name">{{ doc.name }}</span>
											<span class="ff-doc-status" :class="{ draft: doc.docstatus === 0 }">
												{{ statusText(doc) }}
											</span>
											<span class="ff-doc-date">{{ fmtDate(doc.date) || '—' }}</span>
											<ExternalLink :size="14" :stroke-width="2" />
										</button>
									</div>
									<p v-else class="ff-muted">Belum ada {{ docGroup.label.toLowerCase() }}.</p>
								</div>
							</section>
						</template>
					</div>
				</aside>

				<!-- Split Confirmation Modal with Dropdown Print -->
				<SplitConfirmationModal
					:open="showSplitModal"
					:workspace="workspace"
					:sales-order="salesOrder"
					@close="showSplitModal = false"
					@print-both="printBoth"
					@print-dry="printSingle('dry')"
					@print-frozen="printSingle('frozen')"
				/>
			</div>
		</Transition>
	</Teleport>
</template>

<style scoped>
.ff-drawer-layer {
	position: fixed;
	inset: 0;
	z-index: 60;
	display: flex;
	justify-content: flex-end;
	background: rgba(36, 48, 58, 0.4);
	backdrop-filter: blur(1.5px);
}

.ff-drawer {
	display: flex;
	flex-direction: column;
	width: min(780px, 100vw);
	height: 100%;
	background: var(--surface, #ffffff);
	box-shadow: -12px 0 44px rgba(36, 48, 58, 0.2);
	transition: width 0.2s ease;
}

.ff-drawer.ff-drawer-wide {
	width: min(1040px, 100vw);
}

.ff-drawer-head {
	display: flex;
	align-items: flex-start;
	justify-content: space-between;
	gap: 12px;
	padding: 16px 20px;
	border-bottom: 1px solid var(--line, #e2e8f0);
	background: var(--surface, #ffffff);
	flex-shrink: 0;
}

.ff-drawer-title {
	min-width: 0;
}

.ff-eyebrow {
	color: var(--muted, #64748b);
	font-size: 10.5px;
	font-weight: 700;
	letter-spacing: 0.06em;
	text-transform: uppercase;
}

.ff-drawer-title h2 {
	margin-top: 2px;
	display: inline-flex;
	align-items: center;
	gap: 6px;
	color: var(--brand, #2b72ba);
	font-size: 20px;
	font-weight: 750;
	letter-spacing: -0.02em;
}

.ff-so-desk-link {
	color: var(--muted, #64748b);
	display: inline-flex;
	align-items: center;
	padding: 2px;
	border-radius: 4px;
	transition: color 0.15s ease;
}

.ff-so-desk-link:hover {
	color: var(--brand, #2b72ba);
}

.ff-drawer-customer {
	margin-top: 3px;
	color: var(--muted, #64748b);
	font-size: 12.5px;
}

.ff-drawer-actions {
	display: flex;
	align-items: center;
	gap: 8px;
	flex-shrink: 0;
}

/* Stepper Progress Bar */
.ff-stepper {
	display: flex;
	align-items: center;
	padding: 10px 20px;
	background: var(--bg, #f8fafc);
	border-bottom: 1px solid var(--line, #e2e8f0);
	overflow-x: auto;
	flex-shrink: 0;
	gap: 8px;
}

.ff-step-wrapper {
	display: flex;
	align-items: center;
	gap: 8px;
	flex: 1;
	min-width: 140px;
}

.ff-step-btn {
	display: flex;
	align-items: center;
	gap: 10px;
	padding: 6px 12px;
	border: 1px solid transparent;
	border-radius: 8px;
	background: transparent;
	cursor: pointer;
	text-align: left;
	transition: all 0.15s ease;
	font-family: inherit;
}

.ff-step-btn:hover {
	background: rgba(0, 0, 0, 0.04);
}

.ff-step-btn.is-active {
	background: #ffffff;
	border-color: var(--line, #e2e8f0);
	box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

.ff-step-circle {
	width: 26px;
	height: 26px;
	border-radius: 50%;
	display: flex;
	align-items: center;
	justify-content: center;
	font-size: 12px;
	font-weight: 700;
	color: var(--muted, #64748b);
	border: 2px solid var(--line, #e2e8f0);
	background: var(--surface, #ffffff);
	flex-shrink: 0;
	transition: all 0.15s ease;
}

.ff-step-btn.is-active .ff-step-circle {
	border-color: var(--brand, #2b72ba);
	color: var(--brand, #2b72ba);
	background: rgba(43, 114, 186, 0.08);
}

.ff-step-btn.is-complete .ff-step-circle {
	border-color: #10b981;
	background: #10b981;
	color: #ffffff;
}

.ff-step-info {
	display: flex;
	flex-direction: column;
	min-width: 0;
}

.ff-step-label {
	font-size: 13px;
	font-weight: 650;
	color: var(--ink, #1e293b);
	white-space: nowrap;
}

.ff-step-status {
	font-size: 11px;
	color: var(--muted, #64748b);
}

.ff-step-divider {
	flex: 1;
	height: 2px;
	background: var(--line, #e2e8f0);
	border-radius: 2px;
	min-width: 16px;
	transition: background 0.2s ease;
}

.ff-step-divider.is-complete {
	background: #10b981;
}

/* Drawer Body */
.ff-drawer-body {
	display: flex;
	flex-direction: column;
	gap: 16px;
	padding: 18px 20px 28px;
	overflow-y: auto;
	flex: 1;
}

.ff-meta {
	display: grid;
	grid-template-columns: repeat(3, minmax(0, 1fr));
	gap: 10px;
}

.ff-meta > div {
	display: flex;
	flex-direction: column;
	gap: 2px;
	padding: 9px 10px;
	border: 1px solid var(--line, #e2e8f0);
	border-radius: 8px;
	background: var(--surface, #ffffff);
}

.ff-meta span {
	font-size: 11px;
	color: var(--muted, #64748b);
}

.ff-meta strong {
	font-size: 12.5px;
	color: var(--ink, #1e293b);
}

.ff-summary {
	display: grid;
	grid-template-columns: repeat(3, minmax(0, 1fr));
	gap: 10px;
}

.ff-summary-item {
	display: flex;
	flex-direction: column;
	gap: 4px;
	padding: 10px 12px;
	border-radius: 8px;
	border: 1px solid var(--line, #e2e8f0);
}

.ff-summary-item span {
	font-size: 11.5px;
	color: var(--muted, #64748b);
}

.ff-summary-item strong {
	font-size: 18px;
	font-weight: 700;
}

.ff-summary-dry {
	background: rgba(43, 114, 186, 0.05);
	border-color: rgba(43, 114, 186, 0.2);
}
.ff-summary-dry strong {
	color: #2b72ba;
}

.ff-summary-frozen {
	background: rgba(14, 165, 233, 0.05);
	border-color: rgba(14, 165, 233, 0.2);
}
.ff-summary-frozen strong {
	color: #0284c7;
}

.ff-summary-warn {
	background: rgba(234, 88, 12, 0.05);
	border-color: rgba(234, 88, 12, 0.2);
}
.ff-summary-warn strong {
	color: #ea580c;
}

.ff-inline-warn {
	display: flex;
	align-items: center;
	gap: 8px;
	padding: 8px 12px;
	border-radius: 6px;
	background: #fff7ed;
	border: 1px solid #fed7aa;
	color: #c2410c;
	font-size: 12.5px;
}

.ff-section {
	display: flex;
	flex-direction: column;
	gap: 10px;
}

.ff-section-head {
	display: flex;
	align-items: center;
	justify-content: space-between;
}

.ff-section-head h3 {
	font-size: 14px;
	font-weight: 700;
	color: var(--ink, #1e293b);
}

.ff-count {
	font-size: 12px;
	color: var(--muted, #64748b);
	font-weight: 600;
}

.ff-generate-row {
	display: flex;
	flex-direction: column;
	gap: 8px;
	padding: 14px;
	border: 1px solid var(--line, #e2e8f0);
	border-radius: 8px;
	background: var(--surface, #ffffff);
}

.ff-generate-btn {
	align-self: flex-start;
}

.ff-generate-reason {
	font-size: 12px;
	color: var(--muted, #64748b);
}

.ff-generate-error {
	font-size: 12px;
	color: #dc2626;
	margin-top: 4px;
}

.ff-items {
	display: flex;
	flex-direction: column;
	border: 1px solid var(--line, #e2e8f0);
	border-radius: 8px;
	overflow: hidden;
}

.ff-items-head {
	display: grid;
	grid-template-columns: 2fr 1fr 1fr 1fr 1fr;
	gap: 8px;
	padding: 8px 12px;
	background: var(--bg, #f8fafc);
	font-size: 11px;
	font-weight: 700;
	color: var(--muted, #64748b);
	text-transform: uppercase;
	letter-spacing: 0.04em;
	border-bottom: 1px solid var(--line, #e2e8f0);
}

.ff-item-row {
	display: grid;
	grid-template-columns: 2fr 1fr 1fr 1fr 1fr;
	gap: 8px;
	padding: 9px 12px;
	align-items: center;
	font-size: 12.5px;
	border-bottom: 1px solid var(--line, #f1f5f9);
}

.ff-item-row:last-child {
	border-bottom: none;
}

.ff-item-main {
	display: flex;
	flex-direction: column;
	gap: 2px;
	min-width: 0;
}

.ff-item-main strong {
	color: var(--ink, #1e293b);
	font-weight: 600;
}

.ff-item-main span {
	font-size: 11.5px;
	color: var(--muted, #64748b);
}

.ff-doc-group {
	margin-top: 6px;
}

.ff-doc-group h4 {
	font-size: 12px;
	font-weight: 650;
	color: var(--muted, #64748b);
	margin-bottom: 6px;
}

.ff-doc-list {
	display: flex;
	flex-direction: column;
	gap: 4px;
}

.ff-doc-row {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 7px 10px;
	border: 1px solid var(--line, #e2e8f0);
	border-radius: 6px;
	background: var(--surface, #ffffff);
	font-family: inherit;
	cursor: pointer;
	transition: all 0.15s ease;
}

.ff-doc-row:hover {
	background: var(--bg, #f8fafc);
	border-color: var(--brand, #2b72ba);
}

.ff-doc-name {
	font-size: 12.5px;
	font-weight: 600;
	color: var(--brand, #2b72ba);
}

.ff-doc-status {
	font-size: 11.5px;
	padding: 1px 6px;
	border-radius: 4px;
	background: #dcfce7;
	color: #15803d;
	font-weight: 600;
}

.ff-doc-status.draft {
	background: #f1f5f9;
	color: #64748b;
}

.ff-doc-date {
	font-size: 11.5px;
	color: var(--muted, #64748b);
}

.ff-skel {
	height: 38px;
	background: var(--line, #f1f5f9);
	border-radius: 6px;
	animation: pulse 1.5s infinite ease-in-out;
}

.ff-skel-title {
	height: 24px;
	width: 40%;
}

@keyframes pulse {
	0%, 100% { opacity: 1; }
	50% { opacity: 0.5; }
}

.ff-drawer-enter-active,
.ff-drawer-leave-active {
	transition: opacity 0.2s ease;
}

.ff-drawer-enter-from,
.ff-drawer-leave-to {
	opacity: 0;
}

.ff-drawer-enter-active .ff-drawer,
.ff-drawer-leave-active .ff-drawer {
	transition: transform 0.25s ease;
}

.ff-drawer-enter-from .ff-drawer,
.ff-drawer-leave-to .ff-drawer {
	transform: translateX(100%);
}
</style>
