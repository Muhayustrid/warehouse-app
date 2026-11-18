<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import {
	AlertTriangle,
	ArrowRight,
	Check,
	CheckCircle2,
	ChevronDown,
	ChevronLeft,
	ExternalLink,
	FileText,
	LoaderCircle,
	Package,
	Printer,
	RefreshCw,
} from 'lucide-vue-next'
import {
	approveShortPick,
	completePicking,
	createDeliveryNote,
	fetchOrderPreview,
	fetchOrderQueue,
	fetchPackingSlipsPrintHtml,
	fetchRunWorkspace,
	generateFulfillmentRun,
	packAll,
	rejectShortPick,
	requestShortPickApproval,
	resetPacking,
	savePicking,
	stageLabel,
	submitDeliveryNote,
	updateDeliveryPackages,
} from '@/data/fulfillment'
import { fmtDate, fmtQty } from '@/lib/format'
import { toast } from '@/lib/toast'

import SplitConfirmationModal from '@/components/fulfillment/SplitConfirmationModal.vue'
import PrintPreviewModal from '@/components/fulfillment/PrintPreviewModal.vue'
import ManifestDialog from '@/components/fulfillment/ManifestDialog.vue'
import PickingPanel from '@/components/fulfillment/PickingPanel.vue'
import DeliveryPanel from '@/components/fulfillment/DeliveryPanel.vue'
import PackingPanel from '@/components/fulfillment/PackingPanel.vue'
import ReviewPanel from '@/components/fulfillment/ReviewPanel.vue'

const route = useRoute()
const router = useRouter()

const ACTION_REASONS = {
	NO_PICK_LIST: 'Belum ada Pick List aktif.',
	PL_NOT_SUBMITTED: 'Seluruh Pick List harus diselesaikan terlebih dahulu.',
	SHORT_PICK_BLOCKED: 'Kekurangan kuantitas dicegah oleh kebijakan.',
	SHORT_PICK_APPROVAL_PENDING: 'Menunggu persetujuan supervisor.',
	SHORT_PICK_APPROVAL_REJECTED: 'Permintaan persetujuan ditolak.',
	SHORT_PICK_STALE_APPROVAL: 'Kuantitas berubah sejak disetujui.',
}

// Route param can be Sales Order (SAL-ORD-...) or Run (WFR-...)
const paramId = computed(() => route.params.id || route.params.run)

const orderQueue = ref([])
const workspace = ref(null)
const previewData = ref(null)

const enablePackingSlip = computed(() => {
	const prof = workspace.value?.profile || previewData.value?.profile
	if (!prof) return true
	if (prof.enable_packing_slip === 0 || prof.enable_packing_slip === false || prof.enable_packing_slip === '0') {
		return false
	}
	return true
})

watch(enablePackingSlip, (enabled) => {
	if (!enabled && activeTab.value === 'packing') {
		activeTab.value = 'review'
	}
}, { immediate: true })

const STEPS = computed(() => {
	if (!enablePackingSlip.value) {
		return [
			{ key: 'picking', label: '1. Picking' },
			{ key: 'delivery', label: '2. Surat Jalan (DN)' },
			{ key: 'review', label: '3. Review & Kirim' },
		]
	}
	return [
		{ key: 'picking', label: '1. Picking' },
		{ key: 'packing', label: '2. Packing Slip' },
		{ key: 'review', label: '3. Surat Jalan' },
	]
})
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const activeTab = ref('picking')
const generating = ref(false)
const generateError = ref('')
const showSplitModal = ref(false)
const printDropdownOpen = ref(false)
const printDropdownRef = ref(null)
const switchEl = ref(null)
const reviewPanelRef = ref(null)

// Print Preview Modal State (Zero new tabs)
const showPrintModal = ref(false)
const printModalTitle = ref('Cetak Dokumen')
const printModalItems = ref([])

const manifestOpen = ref(false)

let loadToken = 0

const currentSO = computed(() => {
	if (workspace.value?.sales_order?.name) return workspace.value.sales_order.name
	if (previewData.value?.sales_order?.name) return previewData.value.sales_order.name
	if (paramId.value && paramId.value.startsWith('SAL-ORD-')) return paramId.value
	return workspace.value?.run?.sales_order || ''
})

const customerName = computed(() => {
	return (
		workspace.value?.sales_order?.customer_name ||
		previewData.value?.sales_order?.customer_name ||
		workspace.value?.run?.customer ||
		previewData.value?.sales_order?.customer ||
		'—'
	)
})

// Manifest harian: tanggal & outlet diambil dari SO yang sedang dibuka.
const manifestCompany = computed(
	() =>
		workspace.value?.run?.company ||
		workspace.value?.sales_order?.company ||
		previewData.value?.sales_order?.company ||
		'',
)
const manifestDate = computed(
	() =>
		workspace.value?.run?.delivery_date ||
		previewData?.sales_order?.delivery_date ||
		workspace.value?.sales_order?.delivery_date ||
		'',
)
const manifestCustomer = computed(
	() => workspace.value?.sales_order?.customer || previewData.value?.sales_order?.customer || '',
)

function onManifestSaved(name) {
	manifestOpen.value = false
	printModalTitle.value = 'Packing List Harian'
	printModalItems.value = [
		{ label: 'Packing List', doctype: 'Delivery Manifest', name, format: 'Format Print Packing List' },
	]
	showPrintModal.value = true
}

const dryLabel = computed(
	() =>
		workspace.value?.profile?.dry_display_name ||
		previewData.value?.profile?.dry_display_name ||
		'Dry',
)
const frozenLabel = computed(
	() =>
		workspace.value?.profile?.frozen_display_name ||
		previewData.value?.profile?.frozen_display_name ||
		'Frozen',
)

const displayWarehouse = computed(() => {
	const dryWh = workspace.value?.profile?.dry_parent_warehouse || previewData.value?.profile?.dry_parent_warehouse
	const frozenWh = workspace.value?.profile?.frozen_parent_warehouse || previewData.value?.profile?.frozen_parent_warehouse
	if (dryWh && frozenWh && dryWh !== frozenWh) {
		return `${dryWh} · ${frozenWh}`
	}
	return dryWh || frozenWh || 'Gudang Barang Jadi - JURI'
})

const hasRun = computed(() => Boolean(workspace.value?.run))
const isDispatched = computed(() => workspace.value?.run?.status === 'DISPATCHED')
const isDone = computed(() => ['READY', 'DISPATCHED'].includes(workspace.value?.run?.status))

// Read-only document rows shown once packing is complete
const doneRows = computed(() => {
	if (!isDone.value) return []
	const rows = [{
		name: workspace.value?.delivery_note?.name,
		kind: 'Surat Jalan (DN)',
		detail: `${workspace.value?.delivery_note?.items?.length || 0} item`,
		status: isDispatched.value ? 'Submitted' : 'Draft',
	}]
	for (const ps of workspace.value?.packing?.submitted || []) {
		rows.push({
			name: ps.name,
			kind: 'Packing Slip',
			detail: `Koli ${ps.from_case_no || '—'}${ps.total_packages ? ` / ${ps.total_packages}` : ''} · ${ps.items_count || 0} item`,
			status: 'Submitted',
		})
	}
	return rows
})

// Item Surat Jalan (DN) utk step 3 ketika packing selesai — read-only.

const statusBadgeClass = computed(() => {
	if (isDispatched.value) return 'b-done'
	if (previewData.value?.stage === 'completed' || previewData.value?.stage === 'ready') return 'b-done'
	if (workspace.value?.run?.status) return 'b-run'
	if (previewData.value?.stage === 'picking' || previewData.value?.stage === 'packing') return 'b-run'
	return 'b-draft'
})

const statusBadgeText = computed(() => {
	if (isDispatched.value) return 'Completed'
	if (previewData.value?.stage === 'completed') return 'Completed'
	if (workspace.value?.run?.status === 'PLANNING') return 'Planning'
	if (workspace.value?.run?.status === 'PICKING') return 'Picking'
	if (workspace.value?.run?.status === 'PICKED') return 'Picked'
	if (workspace.value?.run?.status === 'PACKING') return 'Packing'
	if (workspace.value?.run?.status === 'READY') return 'Ready'
	if (previewData.value?.stage === 'ready') return 'Ready'
	if (previewData.value?.stage === 'packing') return 'In Packing'
	if (previewData.value?.stage === 'picking') return 'In Picking'
	if (previewData.value?.stage === 'partially_delivered') return 'Partially Delivered'
	return 'Open'
})

const CANNOT_GENERATE_REASONS = {
	PROFILE_INVALID: 'Profil pemisahan Dry/Frozen belum dikonfigurasi atau dinonaktifkan.',
	GENERATE_PERMISSION: 'Anda tidak memiliki hak akses untuk membuat Pick List.',
	SO_NOT_ELIGIBLE: 'Sales Order ini tidak memenuhi syarat untuk membuat Pick List baru (sudah dipick penuh 100% atau sudah terkirim).',
	NO_OUTSTANDING: 'Seluruh kuantitas barang pada Sales Order ini sudah selesai diambil (Sisa Pick = 0).',
	ITEM_GROUP_MISSING: 'Terdapat barang yang belum terklasifikasi kategori item group-nya.',
	STOCK_RESERVED: 'Terdapat stok yang direservasi pada order ini.',
	ITEM_NOT_PICKABLE: 'Barang tidak dapat dipick di gudang.',
}

const canGenerateDisabledReason = computed(() => {
	if (!previewData.value) return ''
	if (previewData.value.can_generate) return ''
	const reasonKey = previewData.value.can_generate_reason
	return (
		CANNOT_GENERATE_REASONS[reasonKey] ||
		`Tidak dapat membuat Pick List baru (${reasonKey || 'Tidak Memenuhi Syarat'}).`
	)
})

// Item count totals
const totalItemCount = computed(() => {
	if (workspace.value?.groups) {
		const dryRows = workspace.value.groups.dry?.rows?.length || 0
		const frozenRows = workspace.value.groups.frozen?.rows?.length || 0
		return dryRows + frozenRows
	}
	if (previewData.value?.groups) {
		const dryRows = previewData.value.groups.dry?.length || 0
		const frozenRows = previewData.value.groups.frozen?.length || 0
		return dryRows + frozenRows
	}
	return 0
})

const totalUnits = computed(() => {
	let sum = 0
	if (workspace.value?.groups) {
		for (const g of [workspace.value.groups.dry, workspace.value.groups.frozen]) {
			if (g?.rows) {
				for (const r of g.rows) sum += Number(r.qty || 0)
			}
		}
	} else if (previewData.value?.groups) {
		for (const key of ['dry', 'frozen']) {
			if (previewData.value.groups[key]) {
				for (const r of previewData.value.groups[key]) sum += Number(r.ordered || 0)
			}
		}
	}
	return sum
})

// Preview Groups
const previewGroups = computed(() => {
	if (!previewData.value?.groups) return []
	return ['dry', 'frozen', 'unclassified'].map((key) => ({
		key,
		label:
			key === 'dry'
				? dryLabel.value
				: key === 'frozen'
					? frozenLabel.value
					: 'Perlu Perhatian',
		items: previewData.value.groups[key] || [],
	}))
})

// Watch route changes to load order
watch(
	() => paramId.value,
	async (id) => {
		if (id) {
			await loadOrder(id, true)
			scrollToActiveOrder()
		}
	},
	{ immediate: true },
)

onMounted(async () => {
	window.addEventListener('click', onDocClick)
	await loadSidebarQueue()
	scrollToActiveOrder()
})

function onDocClick(e) {
	if (printDropdownRef.value && !printDropdownRef.value.contains(e.target)) {
		printDropdownOpen.value = false
	}
}

function scrollToActiveOrder() {
	nextTick(() => {
		switchEl.value
			?.querySelector('.soc.on')
			?.scrollIntoView({ block: 'center', inline: 'nearest' })
	})
}

async function loadSidebarQueue() {
	try {
		const res = await fetchOrderQueue({ page: 1, page_length: 50 })
		const rows = res.rows || []
		if (
			currentSO.value &&
			!rows.some((r) => r.sales_order === currentSO.value) &&
			previewData.value?.sales_order
		) {
			rows.unshift({
				sales_order: currentSO.value,
				customer: previewData.value.sales_order.customer,
				customer_name: previewData.value.sales_order.customer_name,
				delivery_date: previewData.value.sales_order.delivery_date,
				dry_count: previewData.value.groups?.dry?.length || 0,
				frozen_count: previewData.value.groups?.frozen?.length || 0,
				stage: previewData.value.stage || 'ready',
				run: workspace.value?.run || previewData.value.run,
			})
		}
		orderQueue.value = rows
	} catch {
		orderQueue.value = []
	}
}

async function loadOrder(id, initialLoad = false) {
	const token = ++loadToken
	loading.value = true
	error.value = ''
	generateError.value = ''
	try {
		if (id.startsWith('WFR-')) {
			// Direct Run
			const ws = await fetchRunWorkspace(id)
			if (token !== loadToken) return
			workspace.value = ws
			previewData.value = null
			if (initialLoad) syncTabToRunState(ws)
		} else {
			// Sales Order ID
			const preview = await fetchOrderPreview(id)
			if (token !== loadToken) return
			previewData.value = preview

			const existingRun = preview.run?.name || (typeof preview.run === 'string' ? preview.run : null)
			if (existingRun) {
				const ws = await fetchRunWorkspace(existingRun)
				if (token !== loadToken) return
				workspace.value = ws
				if (initialLoad) syncTabToRunState(ws)
			} else {
				workspace.value = null
				activeTab.value = 'picking'
			}
		}
	} catch (e) {
		if (token !== loadToken) return
		error.value = e.message || 'Gagal memuat data order.'
	} finally {
		if (token === loadToken) {
			loading.value = false
		}
	}
}

async function refresh() {
	if (paramId.value) {
		await loadOrder(paramId.value, false)
		await loadSidebarQueue()
	}
}

function syncTabToRunState(ws) {
	if (!ws) return
	const actionKey = ws.next_action?.key || ws.next_action?.action
	if (actionKey === 'create_delivery_note') {
		if (enablePackingSlip.value) {
			// Step "Surat Jalan (DN)" hidden: create draft DN automatically, land on packing.
			activeTab.value = 'packing'
			autoCreateDraftDn()
		} else {
			activeTab.value = 'delivery'
		}
	} else if (actionKey === 'pack_all') {
		activeTab.value = enablePackingSlip.value ? 'packing' : 'review'
	} else if (actionKey === 'submit_delivery_note' || actionKey === 'done') {
		activeTab.value = 'review'
	} else {
		activeTab.value = 'picking'
	}
}

// Stepper Navigation - Freedom to navigate back and forth
function isStepAccessible(stepKey) {
	if (!workspace.value?.run) {
		if (!previewData.value) return false
		if (stepKey === 'picking') return true
		if (stepKey === 'delivery')
			return Boolean(
				previewData.value.documents?.delivery_notes?.length ||
				previewData.value.documents?.pick_lists?.length,
			)
		if (stepKey === 'packing')
			return (
				enablePackingSlip.value &&
				Boolean(
					previewData.value.documents?.packing_slips?.length ||
					previewData.value.documents?.delivery_notes?.length,
				)
			)
		if (stepKey === 'review')
			return Boolean(previewData.value.documents?.delivery_notes?.length)
		return false
	}
	if (isDispatched.value) return true
	if (stepKey === 'picking') return true
	if (stepKey === 'delivery') return true
	if (stepKey === 'packing') return enablePackingSlip.value && Boolean(workspace.value.delivery_note)
	if (stepKey === 'review') return Boolean(workspace.value.delivery_note)
	return false
}

function stepState(stepKey) {
	if (isDispatched.value) return 'done'
	if (!workspace.value?.run && !previewData.value) return 'locked'

	if (isStepComplete(stepKey)) return 'done'
	if (stepKey === activeTab.value) return 'active'
	if (isStepAccessible(stepKey)) return 'active'
	return 'locked'
}

function isStepComplete(stepKey) {
	if (workspace.value) {
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
	} else if (previewData.value?.documents) {
		const docs = previewData.value.documents
		if (stepKey === 'picking') {
			return Boolean(docs.pick_lists?.some((pl) => pl.docstatus === 1))
		}
		if (stepKey === 'delivery') {
			return Boolean(docs.delivery_notes?.length > 0)
		}
		if (stepKey === 'packing') {
			return Boolean(docs.packing_slips?.length > 0)
		}
		if (stepKey === 'review') {
			return Boolean(docs.delivery_notes?.some((dn) => dn.docstatus === 1))
		}
	}
	return false
}

function clickStep(stepKey) {
	if (!isStepAccessible(stepKey)) return
	activeTab.value = stepKey
}

function switchOrder(soName) {
	router.push({ name: 'fulfillment-workspace', params: { id: soName } })
}

// Generate Pick Lists
async function handleGenerateRun() {
	if (!currentSO.value || generating.value) return
	generating.value = true
	generateError.value = ''
	try {
		const idempotencyKey = `w49-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
		const result = await generateFulfillmentRun({
			salesOrder: currentSO.value,
			idempotencyKey,
			expectedSoModified: previewData.value?.modified || '',
		})

		const runName = typeof result?.run === 'string' ? result.run : (result?.run?.name || result?.name)
		if (runName) {
			const ws = await fetchRunWorkspace(runName)
			workspace.value = ws
			previewData.value = null
			showSplitModal.value = true
			activeTab.value = 'picking'
		}
		await loadSidebarQueue()
		toast.success(
			result.reused
				? 'Existing Fulfillment Run reused.'
				: 'Draft Dry/Frozen Pick Lists generated.',
		)
	} catch (e) {
		generateError.value = e.message || 'Failed to generate Pick Lists.'
		toast.error(generateError.value)
	} finally {
		generating.value = false
	}
}

// Print Handlers - Open Clean Popup Modal (ZERO new browser tabs!)
function openPrintPopup(type) {
	printDropdownOpen.value = false
	const dry = workspace.value?.groups?.dry
	const frozen = workspace.value?.groups?.frozen
	const items = []

	if (type === 'both' || type === 'dry') {
		if (dry?.pick_list) {
			items.push({
				label: `Pick List ${dryLabel.value}`,
				doctype: 'Pick List',
				name: dry.pick_list,
				format: workspace.value?.profile?.dry_print_format,
			})
		}
	}
	if (type === 'both' || type === 'frozen') {
		if (frozen?.pick_list) {
			items.push({
				label: `Pick List ${frozenLabel.value}`,
				doctype: 'Pick List',
				name: frozen.pick_list,
				format: workspace.value?.profile?.frozen_print_format,
			})
		}
	}

	if (!items.length) {
		toast.error('Tidak ada dokumen Pick List untuk dicetak.')
		return
	}

	printModalTitle.value = type === 'both' ? 'Cetak Pick List (Dry & Frozen)' : `Cetak ${items[0].label}`
	printModalItems.value = items
	showPrintModal.value = true
}

function openPrintDeliveryNote() {
	if (!workspace.value?.delivery_note?.name) return
	printModalTitle.value = `Cetak Surat Jalan (${workspace.value.delivery_note.name})`
	printModalItems.value = [
		{
			label: 'Surat Jalan (Delivery Note)',
			doctype: 'Delivery Note',
			name: workspace.value.delivery_note.name,
		},
	]
	showPrintModal.value = true
}

async function openPrintPackingSlip() {
	const slips = workspace.value?.packing?.submitted || []
	if (!slips.length) {
		toast.error('Belum ada Packing Slip yang terbit.')
		return
	}

	const dnName = workspace.value?.delivery_note?.name
	let combinedHtml = ''
	if (slips.length > 1 && dnName) {
		try {
			combinedHtml = await fetchPackingSlipsPrintHtml(dnName)
		} catch (e) {
			console.error('Failed to load combined packing slips html:', e)
		}
	}

	const modalItems = []
	if (slips.length > 1 && combinedHtml) {
		modalItems.push({
			label: `Semua Koli (1 - ${slips.length})`,
			doctype: 'Packing Slip',
			name: `Semua (${slips.length} Koli)`,
			html: combinedHtml,
		})
	}

	for (let idx = 0; idx < slips.length; idx++) {
		const ps = slips[idx]
		modalItems.push({
			label: `Koli ${ps.from_case_no || idx + 1}`,
			doctype: 'Packing Slip',
			name: ps.name,
			format: 'Format Print Packing Slip',
		})
	}

	printModalTitle.value = dnName
		? `Cetak Packing Slip (${dnName})`
		: (slips.length > 1 ? `Cetak Packing Slip (${slips.length} Koli)` : `Cetak ${slips[0].name}`)
	printModalItems.value = modalItems
	showPrintModal.value = true
}

// Actions
async function handlePickAll() {
	if (busy.value || loading.value) return
	busy.value = true
	try {
		const draftGroups = [workspace.value?.groups?.dry, workspace.value?.groups?.frozen].filter(
			(g) => g?.pick_list && g.docstatus === 0
		)
		if (!draftGroups.length) {
			toast.warning('Tidak ada Pick List draf untuk diselesaikan.')
			return
		}

		// 1. Build 100% full target quantity rows
		const rows = []
		const expectedModified = {}
		for (const grp of draftGroups) {
			expectedModified[grp.pick_list] = grp.modified
			for (const row of grp.rows || []) {
				rows.push({
					pick_list: grp.pick_list,
					row: row.name,
					picked_qty: Number(row.qty),
				})
			}
		}

		// 2. Save full picking quantities
		const savedWs = await savePicking(workspace.value.run.name, rows, expectedModified)

		// 3. Complete picking immediately
		const updatedExpected = {}
		const updatedDraftGroups = [savedWs?.groups?.dry, savedWs?.groups?.frozen].filter(
			(g) => g?.pick_list && g.docstatus === 0
		)
		for (const grp of updatedDraftGroups) {
			updatedExpected[grp.pick_list] = grp.modified
		}

		await completePicking(workspace.value.run.name, updatedExpected)
		toast.success('Picking selesai (100% lengkap).')
		await refresh()
		if (enablePackingSlip.value) {
			await autoCreateDraftDn()
			activeTab.value = 'packing'
		} else {
			activeTab.value = 'delivery'
		}
	} catch (e) {
		toast.error(e.message || 'Gagal menyelesaikan picking.')
	} finally {
		busy.value = false
	}
}

async function handleSavePicking({ rows, expected_modified }) {
	if (busy.value || loading.value) return
	busy.value = true
	try {
		await savePicking(workspace.value.run.name, rows, expected_modified)
		toast.success('Picking quantities saved.')
		await refresh()
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
			await refresh()
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
		toast.success(shortPickReason ? 'Picking selesai dengan konfirmasi stok kurang.' : 'Picking berhasil diselesaikan.')
		await refresh()
		if (enablePackingSlip.value) {
			await autoCreateDraftDn()
			activeTab.value = 'packing'
		} else {
			activeTab.value = 'delivery'
		}
	} catch (e) {
		toast.error(e.message || 'Gagal menyelesaikan picking.')
	} finally {
		busy.value = false
	}
}

async function handleRequestApproval(reason) {
	if (busy.value || loading.value) return
	busy.value = true
	try {
		await requestShortPickApproval(workspace.value.run.name, reason)
		toast.success('Persetujuan short-pick diajukan.')
		await refresh()
	} catch (e) {
		toast.error(e.message || 'Gagal mengajukan persetujuan short-pick.')
	} finally {
		busy.value = false
	}
}

async function handleApproveShortPick(fingerprint) {
	if (busy.value || loading.value) return
	busy.value = true
	try {
		await approveShortPick(workspace.value.run.name, fingerprint)
		toast.success('Short-pick disetujui.')
		await refresh()
	} catch (e) {
		toast.error(e.message || 'Gagal menyetujui short-pick.')
	} finally {
		busy.value = false
	}
}

async function handleRejectShortPick(reason) {
	if (busy.value || loading.value) return
	busy.value = true
	try {
		await rejectShortPick(workspace.value.run.name, reason)
		toast.info('Short-pick ditolak.')
		await refresh()
	} catch (e) {
		toast.error(e.message || 'Gagal menolak short-pick.')
	} finally {
		busy.value = false
	}
}

// Draft DN is created in the background; the "Surat Jalan (DN)" step is hidden
// from the stepper (flow: Picking -> Packing Slip -> Surat Jalan submit).
const autoDnAttempted = new Set()
async function autoCreateDraftDn() {
	const run = workspace.value?.run?.name
	if (!run || autoDnAttempted.has(run) || workspace.value?.delivery_note?.name) return
	autoDnAttempted.add(run)
	try {
		await createDeliveryNote(run, `auto-${Date.now()}`, {})
		toast.success('Draft Surat Jalan otomatis dibuat.')
		await refresh()
	} catch (e) {
		toast.error(e.message || 'Gagal membuat draft Surat Jalan otomatis.')
	}
}

// "Lanjut ke Surat Jalan": with packing slip flow, land on packing (auto-create draft DN).
function goAfterPicking() {
	if (enablePackingSlip.value) {
		autoCreateDraftDn()
		activeTab.value = 'packing'
	} else {
		activeTab.value = 'delivery'
	}
}

async function handleCreateDeliveryNote(options = {}) {
	if (busy.value || loading.value) return
	busy.value = true
	try {
		const key = `w49-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
		await createDeliveryNote(workspace.value.run.name, key, options)
		toast.success('Surat Jalan (Draft DN) berhasil dibuat.')
		await refresh()
	} catch (e) {
		toast.error(e.message || 'Gagal membuat Delivery Note.')
	} finally {
		busy.value = false
	}
}

async function handleUpdateDeliveryPackages({ dryPackages, frozenPackages }) {
	if (busy.value || loading.value) return
	busy.value = true
	try {
		await updateDeliveryPackages(workspace.value.run.name, dryPackages, frozenPackages)
		toast.success('Jumlah koli Surat Jalan berhasil disimpan.')
		await refresh()
	} catch (e) {
		toast.error(e.message || 'Gagal menyimpan jumlah koli.')
	} finally {
		busy.value = false
	}
}

async function handlePackAll(packageOptions = {}) {
	if (busy.value || loading.value) return
	busy.value = true
	try {
		await packAll(workspace.value.run.name, workspace.value.delivery_note?.modified, packageOptions)
		toast.success('Semua barang berhasil dikemas ke Packing Slip.')
		await refresh()
	} catch (e) {
		toast.error(e.message || 'Gagal mengemas barang.')
	} finally {
		busy.value = false
	}
}

async function handleResetPacking() {
	if (busy.value || loading.value) return
	busy.value = true
	try {
		await resetPacking(workspace.value.run.name, workspace.value.delivery_note?.modified)
		toast.success('Packing berhasil di-reset.')
		await refresh()
	} catch (e) {
		toast.error(e.message || 'Gagal reset packing.')
	} finally {
		busy.value = false
	}
}

async function handleSubmitDeliveryNote() {
	if (busy.value || loading.value) return
	busy.value = true
	try {
		const key = `w49-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
		await submitDeliveryNote(
			workspace.value.run.name,
			key,
			workspace.value.delivery_note?.modified,
		)
		toast.success('Delivery Note submitted. Stok gudang telah dipotong.')
		await refresh()
	} catch (e) {
		toast.error(e.message || 'Gagal submit Delivery Note.')
	} finally {
		busy.value = false
	}
}
</script>

<template>
	<div class="ws-page-container">
		<!-- Back link matching PRODAPP Image 1 -->
		<div class="ws-topbar">
			<RouterLink to="/fulfillment" class="back">
				<ChevronLeft :size="16" :stroke-width="2" />
				<span>Order Queue</span>
			</RouterLink>
			<button type="button" class="btn btn-sm ws-manifest-btn" @click="manifestOpen = true">
				<Package :size="15" :stroke-width="2" />
				<span>Packing List Harian</span>
			</button>
		</div>

		<!-- 2-Column Grid Layout matching PRODAPP Image 1 -->
		<div class="ws-layout">
			<!-- LEFT COLUMN: Sales Order Switcher -->
			<nav ref="switchEl" class="so-switch" aria-label="Pindah Sales Order">
				<div
					v-for="order in orderQueue"
					:key="order.sales_order"
					class="soc"
					:class="{ on: order.sales_order === currentSO }"
					role="button"
					tabindex="0"
					@click="switchOrder(order.sales_order)"
					@keydown.enter="switchOrder(order.sales_order)"
				>
					<span class="soc-ref mono">{{ order.sales_order }}</span>
					<span class="soc-name">{{ order.customer_name || order.customer }}</span>
					<span class="soc-sub">
						{{ order.dry_count }} {{ dryLabel }} · {{ order.frozen_count }} {{ frozenLabel }}
						<template v-if="order.delivery_date">· {{ fmtDate(order.delivery_date) }}</template>
					</span>
				</div>
			</nav>

			<!-- RIGHT COLUMN: Main Workspace Content -->
			<div class="ws-main">
				<!-- Hero Panel matching Image 1 -->
				<header class="panel ws-hero">
					<div class="ws-hero-main">
						<div class="ws-eyebrow">
							<span class="ws-ref mono">{{ currentSO }}</span>
							<span class="badge" :class="statusBadgeClass">{{ statusBadgeText }}</span>
							<span v-if="workspace?.run?.name" class="chip-gudang run">
								Run {{ workspace.run.name }}
							</span>
						</div>
						<h1>{{ customerName }}</h1>
						<p class="ws-meta">
							<span>{{ workspace?.run?.company || 'PT. JUARA ROTI INDONESIA' }} · </span>
							<span>Jadwal Pengiriman: {{ fmtDate(workspace?.run?.delivery_date || previewData?.sales_order?.delivery_date) || '—' }}</span>
							<span v-if="displayWarehouse"> · Gudang: {{ displayWarehouse }}</span>
						</p>
					</div>

					<div class="ws-plan">
						<span class="ws-plan-label">Rencana Pengiriman</span>
						<span class="ws-plan-pack">{{ totalItemCount }} Item</span>
						<span class="ws-plan-pcs">{{ fmtQty(totalUnits) }} Units</span>
					</div>
				</header>

				<!-- Dispatched Banner matching Image 1 -->
				<div v-if="isDispatched" class="banner-done">
					<CheckCircle2 :size="17" :stroke-width="2" />
					<div>
						Fulfillment selesai
						<span v-if="workspace?.delivery_note?.name">
							· Surat Jalan <strong>{{ workspace.delivery_note.name }}</strong> telah disubmit
						</span>
						· Stok barang telah resmi dipotong dan dipindahkan ke customer.
					</div>
				</div>

				<!-- Connected Stepper matching Image 1 -->
				<nav class="stepper" aria-label="Tahap Fulfillment">
					<template v-for="(s, i) in STEPS" :key="s.key">
						<span
							v-if="i > 0"
							class="sep"
							:class="{ on: isStepComplete(STEPS[i - 1].key) }"
						/>
						<button
							type="button"
							class="step"
							:class="{
								'step-active': activeTab === s.key,
								'step-done': isStepComplete(s.key),
								'step-locked': !isStepAccessible(s.key),
							}"
							:disabled="!isStepAccessible(s.key)"
							@click="clickStep(s.key)"
						>
							<span class="dot">
								<Check v-if="isStepComplete(s.key)" :size="12" :stroke-width="3" />
								<span v-else-if="activeTab === s.key" class="dot-inner" />
							</span>
							<span class="step-text">{{ s.label }}</span>
						</button>
					</template>
				</nav>

				<!-- Contextual Action Toolbar matching Active Stepper Tab -->
				<div class="toolbar ws-label-actions">
					<!-- Step 1: Picking -> Cetak Pick List Dropdown -->
					<div
						v-if="activeTab === 'picking' && (workspace?.groups?.dry?.pick_list || workspace?.groups?.frozen?.pick_list)"
						ref="printDropdownRef"
						class="split-print-dropdown"
					>
						<button
							type="button"
							class="btn btn-outline ws-label-print"
							@click="printDropdownOpen = !printDropdownOpen"
						>
							<Printer :size="14" :stroke-width="2" />
							<span>Cetak Pick List</span>
							<ChevronDown :size="13" :stroke-width="2" />
						</button>

						<div v-if="printDropdownOpen" class="split-dropdown-menu" role="menu">
							<button
								v-if="workspace.groups?.dry?.pick_list && workspace.groups?.frozen?.pick_list"
								type="button"
								class="split-menu-item"
								@click="openPrintPopup('both')"
							>
								<Printer :size="14" :stroke-width="2" class="menu-icon" />
								<div class="menu-text">
									<strong>Cetak Keduanya</strong>
									<span>Buka pop-up cetak Pick List {{ dryLabel }} & {{ frozenLabel }}</span>
								</div>
							</button>
							<button
								v-if="workspace.groups?.dry?.pick_list"
								type="button"
								class="split-menu-item"
								@click="openPrintPopup('dry')"
							>
								<Printer :size="14" :stroke-width="2" class="menu-icon" />
								<div class="menu-text">
									<strong>Cetak {{ dryLabel }} saja</strong>
									<span>{{ workspace.groups?.dry?.pick_list }}</span>
								</div>
							</button>
							<button
								v-if="workspace.groups?.frozen?.pick_list"
								type="button"
								class="split-menu-item"
								@click="openPrintPopup('frozen')"
							>
								<Printer :size="14" :stroke-width="2" class="menu-icon" />
								<div class="menu-text">
									<strong>Cetak {{ frozenLabel }} saja</strong>
									<span>{{ workspace.groups?.frozen?.pick_list }}</span>
								</div>
							</button>
						</div>
					</div>

					<!-- Step 2: Surat Jalan (DN) -> Cetak Surat Jalan -->
					<div v-else-if="activeTab === 'delivery' && workspace?.delivery_note?.name" class="single-print-btn">
						<button
							type="button"
							class="btn btn-outline ws-label-print"
							@click="openPrintDeliveryNote"
						>
							<Printer :size="14" :stroke-width="2" />
							<span>Cetak Surat Jalan</span>
						</button>
					</div>

					<!-- Step 3: Packing Slip -> Cetak Packing Slip -->
					<div v-else-if="activeTab === 'packing' && workspace?.packing?.submitted?.length" class="single-print-btn">
						<button
							type="button"
							class="btn btn-outline ws-label-print"
							@click="openPrintPackingSlip"
						>
							<Printer :size="14" :stroke-width="2" />
							<span>Cetak Packing Slip</span>
						</button>
					</div>

					<!-- Step Review/Surat Jalan -> Cetak Surat Jalan -->
					<div v-else-if="activeTab === 'review' && workspace?.delivery_note?.name" class="single-print-btn">
						<button
							type="button"
							class="btn btn-outline ws-label-print"
							@click="openPrintDeliveryNote"
						>
							<Printer :size="14" :stroke-width="2" />
							<span>Cetak Surat Jalan</span>
						</button>
					</div>
				</div>

				<!-- Loading state -->
				<div v-if="loading" class="panel ws-loading-panel">
					<LoaderCircle :size="24" :stroke-width="2" class="spin" />
					<span>Memuat area kerja…</span>
				</div>

				<!-- Error state -->
				<div v-else-if="error" class="panel ws-error-panel" role="alert">
					<AlertTriangle :size="22" :stroke-width="1.8" />
					<p>{{ error }}</p>
					<button type="button" class="btn btn-sm" @click="refresh">Coba lagi</button>
				</div>

				<!-- CASE 1: Open Sales Order (Belum ada Run) -->
				<div v-else-if="!hasRun && previewData" class="panel ws-open-panel">
					<!-- Picking Tab View -->
					<template v-if="activeTab === 'picking'">
						<div class="open-panel-head">
							<div>
								<h3 v-if="previewData.can_generate">Fulfillment Run Belum Dibuat</h3>
								<h3 v-else>Tidak Dapat Membuat Pick List Baru</h3>
								<p v-if="previewData.can_generate">
									Sales Order ini belum memiliki Pick List. Silakan periksa daftar item di bawah ini lalu buat Pick List terpisah untuk kategori Dry dan Frozen.
								</p>
								<p v-else class="reason-warn-text">
									{{ canGenerateDisabledReason }}
								</p>
							</div>
							<button
								type="button"
								class="btn btn-primary btn-lg"
								:disabled="generating || !previewData.can_generate"
								:title="previewData.can_generate ? 'Generate Pick Lists' : canGenerateDisabledReason"
								@click="handleGenerateRun"
							>
								<LoaderCircle v-if="generating" :size="16" :stroke-width="2" class="spin" />
								<span>{{ generating ? 'Membuat Pick List…' : 'Generate Pick Lists' }}</span>
							</button>
						</div>

						<!-- Existing Documents Notice if any exist -->
						<div v-if="previewData.documents?.pick_lists?.length" class="existing-docs-callout">
							<AlertTriangle :size="18" :stroke-width="2" class="callout-icon" />
							<div class="callout-body">
								<strong>Dokumen Pick List Sudah Ada di ERPNext</strong>
								<p>
									Sales Order ini tercatat telah memiliki dokumen Pick List sebelumnya:
									<span v-for="pl in previewData.documents.pick_lists" :key="pl.name" class="mono font-bold">
										{{ pl.name }} ({{ pl.status }})
									</span>.
									Kuantitas barang telah diambil penuh sehingga sisa pick saat ini adalah 0.
								</p>
							</div>
						</div>

						<p v-if="generateError" class="gen-error-msg" role="alert">
							{{ generateError }}
						</p>

						<!-- Preview Item Tables -->
						<div class="open-items-container">
							<section v-for="group in previewGroups" :key="group.key" class="preview-group-section">
								<div class="preview-group-head">
									<h4>Daftar Item {{ group.label }}</h4>
									<span class="preview-count">{{ group.items.length }} Item</span>
								</div>

								<div v-if="group.items.length" class="preview-table">
									<div class="preview-thead">
										<span>Item</span>
										<span>UOM</span>
										<span>Dipesan</span>
										<span>Terkirim</span>
										<span>Sisa Pick</span>
									</div>
									<div v-for="item in group.items" :key="item.sales_order_item" class="preview-trow">
										<div class="preview-item-info">
											<strong>{{ item.item_name || item.item_code }}</strong>
											<span class="mono">{{ item.item_code }} · {{ item.item_group || 'No Group' }}</span>
										</div>
										<span>{{ item.uom || '—' }}</span>
										<span>{{ fmtQty(item.ordered) }}</span>
										<span>{{ fmtQty(item.delivered) }}</span>
										<span><strong>{{ fmtQty(item.outstanding) }}</strong></span>
									</div>
								</div>
								<p v-else class="preview-empty">Tidak ada item {{ group.label.toLowerCase() }}.</p>
							</section>
						</div>
					</template>

					<!-- Delivery Tab View -->
					<div v-else-if="activeTab === 'delivery'" class="preview-doc-card">
						<div class="preview-group-head">
							<h4>Dokumen Surat Jalan (Delivery Note)</h4>
						</div>
						<div v-if="previewData.documents?.delivery_notes?.length" class="preview-doc-list">
							<div v-for="dn in previewData.documents.delivery_notes" :key="dn.name" class="preview-doc-item">
								<FileText :size="18" :stroke-width="2" />
								<div class="doc-info">
									<strong class="mono">{{ dn.name }}</strong>
									<span class="doc-date">{{ dn.date || '—' }}</span>
								</div>
								<span class="badge" :class="dn.docstatus === 1 ? 'b-done' : 'b-draft'">
									{{ dn.status }}
								</span>
							</div>
						</div>
						<p v-else class="preview-empty">Belum ada Surat Jalan di ERPNext untuk Sales Order ini.</p>
					</div>

					<!-- Packing Tab View -->
					<div v-else-if="activeTab === 'packing'" class="preview-doc-card">
						<div class="preview-group-head">
							<h4>Dokumen Packing Slip</h4>
						</div>
						<div v-if="previewData.documents?.packing_slips?.length" class="preview-doc-list">
							<div v-for="ps in previewData.documents.packing_slips" :key="ps.name" class="preview-doc-item">
								<Package :size="18" :stroke-width="2" />
								<div class="doc-info">
									<strong class="mono">{{ ps.name }}</strong>
									<span class="doc-date">{{ ps.date || '—' }} · DN: {{ ps.delivery_note || '—' }}</span>
								</div>
								<span class="badge" :class="ps.docstatus === 1 ? 'b-done' : 'b-draft'">
									{{ ps.status }}
								</span>
							</div>
						</div>
						<p v-else class="preview-empty">Belum ada Packing Slip di ERPNext untuk Sales Order ini.</p>
					</div>

					<!-- Review Tab View -->
					<div v-else-if="activeTab === 'review'" class="preview-doc-card">
						<div class="preview-group-head">
							<h4>Ringkasan Order & Dokumen</h4>
						</div>
						<div class="preview-summary-grid">
							<div class="summary-box">
								<span class="s-label">Status SO</span>
								<span class="s-val">{{ previewData.sales_order?.status }}</span>
							</div>
							<div class="summary-box">
								<span class="s-label">Pick Lists</span>
								<span class="s-val mono">{{ previewData.documents?.pick_lists?.length || 0 }} dokumen</span>
							</div>
							<div class="summary-box">
								<span class="s-label">Surat Jalan</span>
								<span class="s-val mono">{{ previewData.documents?.delivery_notes?.length || 0 }} dokumen</span>
							</div>
							<div class="summary-box">
								<span class="s-label">Packing Slips</span>
								<span class="s-val mono">{{ previewData.documents?.packing_slips?.length || 0 }} dokumen</span>
							</div>
						</div>
					</div>
				</div>

				<!-- CASE 2a: Run done + tab Picking -> read-only summary table.
				     Tab Packing & Surat Jalan punya tampilan read-only sendiri. -->
				<div v-else-if="isDone && activeTab === 'picking'" class="panel ws-done-panel">
					<div class="preview-group-head">
						<h4>Ringkasan Fulfillment (Read-only)</h4>
						<span class="preview-count">{{ doneRows.length }} Dokumen</span>
					</div>
					<div class="preview-table">
						<div class="preview-thead">
							<span>No. Dokumen</span>
							<span>Jenis</span>
							<span>Detail</span>
							<span>Status</span>
						</div>
						<div v-for="row in doneRows" :key="row.name" class="preview-trow">
							<div class="preview-item-info">
								<strong class="mono">{{ row.name }}</strong>
							</div>
							<span>{{ row.kind }}</span>
							<span>{{ row.detail }}</span>
							<span><span class="badge b-done">{{ row.status }}</span></span>
						</div>
					</div>
					<p class="preview-empty">Edit tidak tersedia di sini — gunakan halaman Packing gabungan untuk perubahan sebelum DN disubmit.</p>
				</div>

				<!-- CASE 2: Active Run Exists -> Render Step Panels -->
				<template v-else-if="workspace?.run">
					<!-- Step 1: Picking -->
					<PickingPanel
						v-if="activeTab === 'picking'"
						:workspace="workspace"
						:busy="busy"
						@refresh="refresh"
						@pick-all="handlePickAll"
						@save-picking="handleSavePicking"
						@finish-picking="handleFinishPicking"
						@request-approval="handleRequestApproval"
						@approve-short-pick="handleApproveShortPick"
						@reject-short-pick="handleRejectShortPick"
						@go-delivery="goAfterPicking"
					/>

					<!-- Step 2: Surat Jalan (Delivery Note) -->
					<DeliveryPanel
						v-else-if="activeTab === 'delivery'"
						:workspace="workspace"
						:busy="busy"
						@create-dn="handleCreateDeliveryNote"
						@go-packing="activeTab = 'packing'"
						@go-review="activeTab = 'review'"
						@go-picking="activeTab = 'picking'"
						@refresh="refresh"
					/>

					<!-- Step 3: Packing Slip -->
					<!-- Packing slip flow hides the DN step; back-navigation lands on the submit step -->
					<PackingPanel
						v-else-if="activeTab === 'packing' && enablePackingSlip"
						:workspace="workspace"
						:busy="busy"
						@pack-all="handlePackAll"
						@reset-packing="handleResetPacking"
						@go-delivery="activeTab = 'review'"
						@go-picking="activeTab = 'picking'"
						@go-review="activeTab = 'review'"
						@refresh="refresh"
					/>

					<!-- Step 3 Surat Jalan: panel review (info DN + daftar item + submit) -->
					<ReviewPanel
						v-else-if="activeTab === 'review'"
						ref="reviewPanelRef"
						:workspace="workspace"
						:busy="busy"
						@submit-dn="handleSubmitDeliveryNote"
						@go-packing="activeTab = 'packing'"
						@go-delivery="activeTab = 'review'"
						@refresh="refresh"
					/>
				</template>
			</div>
		</div>

		<!-- Split Confirmation Modal with Dropdown Print -->
		<SplitConfirmationModal
			:open="showSplitModal"
			:workspace="workspace"
			:sales-order="currentSO"
			@close="showSplitModal = false"
			@print-both="openPrintPopup('both')"
			@print-dry="openPrintPopup('dry')"
			@print-frozen="openPrintPopup('frozen')"
		/>

		<!-- Print Preview Modal Popup (No new tabs!) -->
		<PrintPreviewModal
			:open="showPrintModal"
			:title="printModalTitle"
			:items="printModalItems"
			@close="showPrintModal = false"
		/>

		<ManifestDialog
			:open="manifestOpen"
			:company="manifestCompany"
			:date="manifestDate"
			:customer="manifestCustomer"
			@close="manifestOpen = false"
			@saved="onManifestSaved"
		/>
	</div>
</template>

<style scoped>
.ws-page-container {
	max-width: 1400px;
	margin: 0 auto;
	padding: 18px 24px 48px;
}

.ws-topbar {
	display: flex;
	align-items: flex-start;
	justify-content: space-between;
	gap: 12px;
}

.ws-manifest-btn {
	display: inline-flex;
	align-items: center;
	gap: 6px;
}

/* Back Link matching PRODAPP */
.back {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	color: var(--muted, #64748b);
	text-decoration: none;
	font-size: 13px;
	font-weight: 600;
	margin-bottom: 14px;
	transition: color 0.14s ease;
}

.back:hover {
	color: var(--ink, #24303a);
}

/* Grid Layout matching PRODAPP FU68 */
.ws-layout {
	position: relative;
	display: grid;
	grid-template-columns: 292px minmax(0, 1fr);
	gap: 20px;
	min-height: calc(100vh - 144px);
}

/* Left Switcher */
.so-switch {
	position: absolute;
	top: 0;
	bottom: 0;
	left: 0;
	width: 292px;
	display: flex;
	flex-direction: column;
	gap: 10px;
	overflow-y: auto;
	padding: 2px 14px 6px 2px;
	border-right: 1px solid var(--line, #e3e9ee);
	scrollbar-width: thin;
}

.soc {
	flex: none;
	width: 100%;
	display: flex;
	flex-direction: column;
	gap: 2px;
	padding: 10px 14px 11px;
	border: 1px solid var(--line, #e3e9ee);
	border-radius: 10px;
	background: rgba(255, 255, 255, 0.72);
	text-decoration: none;
	cursor: pointer;
	transition: background 0.14s ease, border-color 0.14s ease, transform 0.12s ease;
}

.soc:hover {
	background: var(--brand-softer, #eff5f9);
	border-color: var(--brand-light, #66a3bf);
}

.soc:active {
	transform: scale(0.97);
}

.soc.on {
	background: var(--brand-soft, #e3eef5);
	border-color: transparent;
}

.soc.on .soc-name {
	color: var(--brand, #3368a0);
}

.soc.on .soc-sub,
.soc.on .soc-ref {
	color: var(--brand, #3368a0);
	opacity: 0.75;
}

.soc-ref {
	font-size: 11.5px;
	color: var(--faint, #8d99a5);
	white-space: nowrap;
}

.soc-name {
	font-size: 13.5px;
	font-weight: 600;
	color: var(--ink, #24303a);
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.soc-sub {
	font-size: 12px;
	color: var(--faint, #8d99a5);
	white-space: nowrap;
}

/* Main Workspace */
.ws-main {
	grid-column: 2;
	grid-row: 1;
	min-width: 0;
	display: flex;
	flex-direction: column;
}

/* Panel */
.panel {
	background: #ffffff;
	border: 1px solid var(--line, #e2e8f0);
	border-radius: 8px;
	box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.04);
}

/* Hero Panel */
.ws-hero {
	display: flex;
	align-items: flex-start;
	justify-content: space-between;
	gap: 16px;
	padding: 16px 22px;
	margin-bottom: 14px;
}

.ws-hero-main {
	min-width: 0;
}

.ws-eyebrow {
	display: flex;
	align-items: center;
	gap: 8px;
	font-size: 12px;
}

.ws-ref {
	font-size: 12px;
	color: var(--muted, #64748b);
	font-weight: 600;
}

.chip-gudang {
	font-size: 11px;
	padding: 2px 7px;
	border-radius: 4px;
	font-weight: 600;
	background: var(--brand-softer, #eff5f9);
	color: var(--brand, #3368a0);
}

.ws-hero-main h1 {
	font-size: 21px;
	font-weight: 700;
	color: var(--ink, #24303a);
	margin: 5px 0 3px;
	letter-spacing: -0.01em;
}

.ws-meta {
	font-size: 12.5px;
	color: var(--muted, #64748b);
}

.ws-plan {
	text-align: right;
	flex-shrink: 0;
}

.ws-plan-label {
	display: block;
	font-size: 10.5px;
	text-transform: uppercase;
	color: var(--muted, #64748b);
	font-weight: 700;
	letter-spacing: 0.05em;
}

.ws-plan-pack {
	display: block;
	font-size: 22px;
	font-weight: 750;
	color: var(--ink, #24303a);
}

.ws-plan-pcs {
	display: block;
	font-size: 12px;
	color: var(--muted, #64748b);
}

/* Banner Done */
.banner-done {
	display: flex;
	align-items: center;
	gap: 10px;
	padding: 11px 16px;
	border-radius: 10px;
	background: #ecfdf5;
	border: 1px solid #a7f3d0;
	color: #065f46;
	font-size: 13px;
	font-weight: 550;
	margin-bottom: 14px;
}

/* Stepper matching PRODAPP - Bersih, Centang 100% di Tengah, Teks Aktif Berwarna */
.stepper {
	display: flex;
	align-items: center;
	margin: 10px 0 16px;
	overflow-x: auto;
	padding: 4px 0;
}

.step {
	display: inline-flex;
	align-items: center;
	gap: 8px;
	padding: 2px 4px;
	border: 0;
	background: transparent;
	font: inherit;
	font-size: 13.5px;
	color: var(--muted, #64748b);
	cursor: pointer;
	white-space: nowrap;
	border-radius: 6px;
	transition: color 0.14s ease;
}

.step:hover:not(:disabled) {
	background: transparent;
	color: var(--ink, #1e293b);
}

.step .dot {
	width: 22px;
	height: 22px;
	border-radius: 50%;
	border: 1.5px solid var(--line2, #cbd5e1);
	display: flex;
	align-items: center;
	justify-content: center;
	background: var(--surface, #ffffff);
	flex-shrink: 0;
	color: #ffffff;
	transition: background 0.14s ease, border-color 0.14s ease;
}

.step .dot .dot-inner {
	width: 6.5px;
	height: 6.5px;
	border-radius: 50%;
	background: var(--accent, #3368a0);
}

.step-active .dot {
	border-color: var(--accent, #3368a0);
}

.step-done .dot {
	background: var(--accent, #3368a0);
	border-color: var(--accent, #3368a0);
	color: #ffffff;
}

.step .dot :deep(svg),
.step .dot svg {
	display: block;
	margin: auto;
}

/* Background colour hanya pada teks saat berada di tahap tersebut, tampilan tenang */
.step-text {
	padding: 3px 8px;
	border-radius: 6px;
	transition: background 0.14s ease, color 0.14s ease;
}

.step-active .step-text {
	background: #eaf2f9;
	color: var(--accent-strong, #2a5585);
	font-weight: 650;
}

.step-done:not(.step-active) .step-text {
	color: var(--ink, #24303a);
	font-weight: 500;
}

.step-locked {
	cursor: not-allowed;
	opacity: 0.5;
}

.step-locked .dot {
	border-style: dashed;
}

.sep {
	flex: 1 1 22px;
	min-width: 22px;
	max-width: 52px;
	height: 1.5px;
	border-radius: 1px;
	background: var(--line2, #d4dde4);
	transition: background 0.2s ease;
}

.sep.on {
	background: var(--brand-light, #66a3bf);
}

/* Actions */
.ws-label-actions {
	display: flex;
	align-items: center;
	justify-content: flex-end;
	margin-bottom: 14px;
}

.ws-label-print {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	font-weight: 600;
}

.multi-print-btns {
	display: flex;
	align-items: center;
	gap: 8px;
}

/* Dropdown */
.split-print-dropdown {
	position: relative;
}

.split-dropdown-menu {
	position: absolute;
	top: calc(100% + 6px);
	right: 0;
	z-index: 50;
	width: 290px;
	background: #ffffff;
	border: 1px solid var(--line, #e2e8f0);
	border-radius: 10px;
	box-shadow: 0 12px 32px rgba(15, 23, 42, 0.15);
	padding: 6px;
	display: flex;
	flex-direction: column;
	gap: 3px;
}

.split-menu-item {
	display: flex;
	align-items: flex-start;
	gap: 10px;
	padding: 9px 12px;
	border: none;
	border-radius: 6px;
	background: transparent;
	text-align: left;
	cursor: pointer;
	font-family: inherit;
	transition: background 0.15s ease;
	width: 100%;
}

.split-menu-item:hover {
	background: var(--bg, #f1f5f9);
}

.menu-icon {
	color: var(--brand, #2b72ba);
	margin-top: 2px;
	flex-shrink: 0;
}

.menu-text {
	display: flex;
	flex-direction: column;
	gap: 2px;
}

.menu-text strong {
	font-size: 13px;
	color: var(--ink, #0f172a);
}

.menu-text span {
	font-size: 11.5px;
	color: var(--muted, #64748b);
}

/* Open Panel */
.ws-open-panel {
	padding: 24px;
	display: flex;
	flex-direction: column;
	gap: 20px;
}

.open-panel-head {
	display: flex;
	align-items: flex-start;
	justify-content: space-between;
	gap: 20px;
	padding-bottom: 18px;
	border-bottom: 1px solid var(--line, #e3e9ee);
}

.open-panel-head h3 {
	font-size: 16px;
	font-weight: 700;
	color: var(--ink, #24303a);
}

.open-panel-head p {
	font-size: 13px;
	color: var(--muted, #64748b);
	margin-top: 3px;
	max-width: 580px;
	line-height: 1.5;
}

.reason-warn-text {
	color: #c2410c !important;
	font-weight: 550;
}

.existing-docs-callout {
	display: flex;
	align-items: flex-start;
	gap: 12px;
	padding: 12px 16px;
	background: #fff7ed;
	border: 1px solid #fed7aa;
	border-radius: 8px;
	color: #9a3412;
	font-size: 12.5px;
}

.existing-docs-callout strong {
	display: block;
	font-size: 13px;
	margin-bottom: 2px;
}

.existing-docs-callout p {
	margin: 0;
	line-height: 1.5;
}

.open-items-container {
	display: flex;
	flex-direction: column;
	gap: 16px;
}

.preview-group-section {
	display: flex;
	flex-direction: column;
	gap: 8px;
}

.preview-group-head {
	display: flex;
	align-items: center;
	justify-content: space-between;
}

.preview-group-head h4 {
	font-size: 13px;
	font-weight: 700;
	color: var(--ink, #24303a);
}

.preview-count {
	font-size: 12px;
	color: var(--muted, #64748b);
}

.ws-done-panel .preview-thead,
.ws-done-panel .preview-trow {
	grid-template-columns: 2fr 1fr 1fr 1fr;
}

.preview-table {
	border: 1px solid var(--line, #e3e9ee);
	border-radius: 8px;
	overflow: hidden;
	background: #ffffff;
}

.preview-thead {
	display: grid;
	grid-template-columns: 2.5fr 1fr 1fr 1fr 1.2fr;
	gap: 12px;
	padding: 8px 14px;
	background: var(--bg, #f8fafc);
	font-size: 11px;
	font-weight: 700;
	color: var(--muted, #64748b);
	text-transform: uppercase;
	letter-spacing: 0.04em;
	border-bottom: 1px solid var(--line, #e3e9ee);
}

.preview-trow {
	display: grid;
	grid-template-columns: 2.5fr 1fr 1fr 1fr 1.2fr;
	gap: 12px;
	padding: 10px 14px;
	align-items: center;
	font-size: 12.5px;
	border-bottom: 1px solid var(--line, #f1f5f9);
}

.preview-trow:last-child {
	border-bottom: none;
}

.preview-item-info {
	display: flex;
	flex-direction: column;
	gap: 2px;
}

.preview-item-info strong {
	color: var(--ink, #24303a);
}

.preview-item-info span {
	font-size: 11.5px;
	color: var(--muted, #64748b);
}

.preview-doc-card {
	display: flex;
	flex-direction: column;
	gap: 16px;
}

.preview-doc-list {
	display: flex;
	flex-direction: column;
	gap: 10px;
}

.preview-doc-item {
	display: flex;
	align-items: center;
	gap: 14px;
	padding: 12px 16px;
	background: #ffffff;
	border: 1px solid var(--line, #e2e8f0);
	border-radius: 8px;
}

.preview-doc-item .doc-info {
	display: flex;
	flex-direction: column;
	gap: 2px;
	flex: 1;
}

.preview-doc-item .doc-date {
	font-size: 11.5px;
	color: var(--muted, #64748b);
}

.preview-summary-grid {
	display: grid;
	grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
	gap: 14px;
}

.summary-box {
	display: flex;
	flex-direction: column;
	gap: 6px;
	padding: 14px 18px;
	background: #ffffff;
	border: 1px solid var(--line, #e2e8f0);
	border-radius: 8px;
}

.summary-box .s-label {
	font-size: 12px;
	color: var(--muted, #64748b);
}

.summary-box .s-val {
	font-size: 14px;
	font-weight: 700;
	color: var(--ink, #1e293b);
}

.preview-empty {
	font-size: 12.5px;
	color: var(--muted, #64748b);
	font-style: italic;
}

.gen-error-msg {
	font-size: 12.5px;
	color: #dc2626;
	background: #fef2f2;
	padding: 8px 12px;
	border-radius: 6px;
	border: 1px solid #fecaca;
}

.ws-loading-panel,
.ws-error-panel {
	padding: 48px;
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	gap: 12px;
	color: var(--muted, #64748b);
}

/* Responsive */
@media (max-width: 1180px) {
	.ws-layout {
		grid-template-columns: 240px minmax(0, 1fr);
	}
	.so-switch {
		width: 240px;
	}
}

@media (max-width: 820px) {
	.ws-layout {
		display: block;
		min-height: 0;
	}
	.so-switch {
		position: static;
		width: auto;
		flex-direction: row;
		overflow-x: auto;
		overflow-y: hidden;
		margin-bottom: 10px;
		padding: 2px 2px 6px;
		border-right: none;
	}
	.soc {
		width: 200px;
	}
}
</style>
