<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { AlertTriangle, ExternalLink, LoaderCircle, RefreshCw, X } from 'lucide-vue-next'
import { fetchOrderPreview, generateFulfillmentRun, stageLabel } from '@/data/fulfillment'
import { fmtDate, fmtQty } from '@/lib/format'
import { toast } from '@/lib/toast'

const props = defineProps({
	open: { type: Boolean, default: false },
	salesOrder: { type: String, default: null },
})
const emit = defineEmits(['close', 'generated'])

const data = ref(null)
const loading = ref(false)
const error = ref('')
const closeBtn = ref(null)
const drawer = ref(null)
const generating = ref(false)
const generateError = ref('')
const idempotencyKey = ref('')
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

const dryLabel = computed(() => data.value?.profile?.dry_display_name || 'Dry')
const frozenLabel = computed(() => data.value?.profile?.frozen_display_name || 'Frozen')
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
const hasActiveRun = computed(() => Boolean(data.value?.run))
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
			error.value = ''
			generateError.value = ''
			generating.value = false
			idempotencyKey.value = ''
			loading.value = false
			document.body.style.overflow = ''
			return
		}
		document.body.style.overflow = 'hidden'
		idempotencyKey.value = newIdempotencyKey()
		generateError.value = ''
		await load(salesOrder)
		await nextTick()
		closeBtn.value?.focus()
	},
	{ immediate: true },
)

async function load(salesOrder = props.salesOrder) {
	if (!salesOrder) {
		return
	}
	const token = ++loadToken
	loading.value = true
	error.value = ''
	try {
		const result = await fetchOrderPreview(salesOrder)
		if (token !== loadToken) {
			return
		}
		data.value = result
	} catch (e) {
		if (token !== loadToken) {
			return
		}
		data.value = null
		error.value = e.message || 'Failed to load this sales order.'
	} finally {
		if (token === loadToken) {
			loading.value = false
		}
	}
}

function close() {
	emit('close')
}

async function generate() {
	if (!canGenerate.value || !props.salesOrder) {
		return
	}
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
		await load(props.salesOrder)
		emit('generated', result)
		toast.success(
			result.reused
				? 'Existing Fulfillment Run reused.'
				: 'Draft Dry/Frozen Pick Lists generated.',
		)
	} catch (e) {
		const message = e.message || 'Failed to generate Pick Lists.'
		if (message.startsWith('SO_CHANGED')) {
			// The old request key belongs to the previous SO hash; retrying it would
			// only produce an idempotency mismatch.
			idempotencyKey.value = newIdempotencyKey()
			await load(props.salesOrder)
			generateError.value = 'The Sales Order changed. Review the refreshed detail and try again.'
		} else {
			generateError.value = generateErrorMessage(message)
		}
		toast.error(generateError.value)
	} finally {
		generating.value = false
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
		close()
	}
}

function openNative(doctype, name) {
	const slug = DOC_SLUGS[doctype]
	if (!slug) {
		return
	}
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
					role="dialog"
					aria-modal="true"
					aria-labelledby="ff-drawer-title"
				>
					<header class="ff-drawer-head">
						<div class="ff-drawer-title">
							<p class="ff-eyebrow">Sales Order</p>
							<h2 id="ff-drawer-title">{{ salesOrder }}</h2>
							<p v-if="data" class="ff-drawer-customer">
								{{ data.sales_order.customer_name || data.sales_order.customer }}
								<span v-if="data.sales_order.company"> · {{ data.sales_order.company }}</span>
							</p>
						</div>
						<div class="ff-drawer-actions">
							<span v-if="data" class="ff-stage" :class="`ff-stage-${data.stage}`">
								{{ stageLabel(data.stage) }}
							</span>
							<button
								ref="closeBtn"
								type="button"
								class="btn iconbtn"
								aria-label="Close detail"
								@click="close"
							>
								<X :size="16" :stroke-width="2" />
							</button>
						</div>
					</header>

					<div class="ff-drawer-body">
						<div v-if="loading" class="ff-drawer-loading" aria-label="Loading detail">
							<div class="ff-skel ff-skel-title"></div>
							<div class="ff-skel"></div>
							<div class="ff-skel"></div>
							<div class="ff-skel"></div>
						</div>

						<div v-else-if="error" class="ff-drawer-state ff-error" role="alert">
							<AlertTriangle :size="22" :stroke-width="1.8" />
							<div>
								<strong>Could not load this sales order</strong>
								<p>{{ error }}</p>
							</div>
							<button type="button" class="btn btn-sm" @click="load()">
								<RefreshCw :size="14" :stroke-width="2" />
								Retry
							</button>
						</div>

						<template v-else-if="data">
							<div class="ff-meta">
								<div>
									<span>SO date</span>
									<strong>{{ fmtDate(data.sales_order.transaction_date) || '—' }}</strong>
								</div>
								<div>
									<span>Delivery</span>
									<strong>{{ fmtDate(data.sales_order.delivery_date) || '—' }}</strong>
								</div>
								<div>
									<span>Native status</span>
									<strong>{{ data.sales_order.status || '—' }}</strong>
								</div>
							</div>

							<div class="ff-summary">
								<div class="ff-summary-item ff-summary-dry">
									<span>{{ dryLabel }} items</span>
									<strong>{{ data.groups.dry.length }}</strong>
								</div>
								<div class="ff-summary-item ff-summary-frozen">
									<span>{{ frozenLabel }} items</span>
									<strong>{{ data.groups.frozen.length }}</strong>
								</div>
								<div class="ff-summary-item ff-summary-warn">
									<span>Needs attention</span>
									<strong>{{ data.groups.unclassified.length }}</strong>
								</div>
							</div>

							<div v-if="data.warnings?.length" class="ff-inline-warn" role="status">
								<AlertTriangle :size="15" :stroke-width="2" />
								<span v-for="warning in data.warnings" :key="warning">{{ reasonText(warning) }}</span>
							</div>

							<section class="ff-section ff-run-section">
								<div class="ff-section-head">
									<h3>Fulfillment Run</h3>
									<span v-if="data.run" class="ff-run-status">{{ data.run.status }}</span>
								</div>

								<div v-if="data.run" class="ff-run-card">
									<div class="ff-run-main">
										<span>Active Run</span>
										<a
											class="ff-run-link"
											:href="`/app/warehouse-fulfillment-run/${encodeURIComponent(data.run.name)}`"
											target="_blank"
											rel="noopener"
										>
											{{ data.run.name }}
											<ExternalLink :size="13" :stroke-width="2" />
										</a>
									</div>
									<div class="ff-run-pls">
										<button
											v-if="data.run.dry_pick_list"
											type="button"
											class="ff-pl-link"
											@click="openNative('Pick List', data.run.dry_pick_list)"
										>
											{{ dryLabel }} · {{ data.run.dry_pick_list }}
										</button>
										<button
											v-if="data.run.frozen_pick_list"
											type="button"
											class="ff-pl-link"
											@click="openNative('Pick List', data.run.frozen_pick_list)"
										>
											{{ frozenLabel }} · {{ data.run.frozen_pick_list }}
										</button>
									</div>
								</div>

								<div v-else class="ff-generate-row">
									<button
										type="button"
										class="btn btn-primary ff-generate-btn"
										:disabled="!canGenerate"
										@click="generate"
									>
										<LoaderCircle
											v-if="generating"
											:size="14"
											:stroke-width="2"
											class="spin"
										/>
										{{ generating ? 'Generating…' : 'Generate Pick Lists' }}
									</button>
									<p v-if="!canGenerate && !generating" class="ff-muted ff-generate-reason">
										{{ generateDisabledReason || 'Generation is not available for this order.' }}
									</p>
									<p v-else class="ff-muted ff-generate-reason">
										Draft only. Picking and submission stay in the next phase.
									</p>
								</div>
								<p v-if="generateError" class="ff-generate-error" role="alert">
									{{ generateError }}
								</p>
							</section>

							<section v-for="group in groups" :key="group.key" class="ff-section">
								<template v-if="group.items.length || group.key !== 'unclassified'">
									<div class="ff-section-head">
										<h3>{{ group.label }}</h3>
										<span class="ff-count">{{ group.items.length }}</span>
									</div>
									<div v-if="group.items.length" class="ff-items">
										<div class="ff-items-head">
											<span>Item</span>
											<span>UOM</span>
											<span>Ordered</span>
											<span>Delivered</span>
											<span>Outstanding</span>
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
									<p v-else class="ff-muted">No {{ group.label.toLowerCase() }} items.</p>
								</template>
							</section>

							<section class="ff-section">
								<div class="ff-section-head">
									<h3>Related documents</h3>
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
									<p v-else class="ff-muted">No {{ docGroup.label.toLowerCase() }}.</p>
								</div>
							</section>

							<p class="ff-readonly">
								F2 generates Draft Pick Lists only. Picking, Pick List submit, delivery, and
								packing actions remain unavailable until the next phases.
							</p>
						</template>
					</div>
				</aside>
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
	background: rgba(36, 48, 58, 0.36);
}

.ff-drawer {
	display: flex;
	flex-direction: column;
	width: min(760px, 100vw);
	height: 100%;
	background: var(--surface);
	box-shadow: -12px 0 44px rgba(36, 48, 58, 0.16);
}

.ff-drawer-head {
	display: flex;
	align-items: flex-start;
	justify-content: space-between;
	gap: 12px;
	padding: 18px 20px;
	border-bottom: 1px solid var(--line);
}

.ff-drawer-title {
	min-width: 0;
}

.ff-eyebrow {
	color: var(--muted);
	font-size: 10.5px;
	font-weight: 700;
	letter-spacing: 0.06em;
	text-transform: uppercase;
}

.ff-drawer-title h2 {
	margin-top: 2px;
	color: var(--brand);
	font-size: 20px;
	font-weight: 750;
	letter-spacing: -0.02em;
}

.ff-drawer-customer {
	margin-top: 3px;
	color: var(--muted);
	font-size: 12.5px;
}

.ff-drawer-actions {
	display: flex;
	align-items: center;
	gap: 8px;
	flex: none;
}

.ff-drawer-body {
	display: flex;
	flex-direction: column;
	gap: 16px;
	padding: 18px 20px 28px;
	overflow-y: auto;
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
	border: 1px solid var(--line);
	border-radius: 10px;
	background: var(--brand-softer);
}

.ff-meta span {
	color: var(--muted);
	font-size: 10.5px;
	font-weight: 650;
	text-transform: uppercase;
	letter-spacing: 0.04em;
}

.ff-meta strong {
	font-size: 13px;
	font-weight: 650;
}

.ff-summary {
	display: grid;
	grid-template-columns: repeat(3, minmax(0, 1fr));
	gap: 10px;
}

.ff-summary-item {
	display: flex;
	align-items: baseline;
	justify-content: space-between;
	gap: 8px;
	padding: 10px 12px;
	border-radius: 10px;
	font-size: 12px;
}

.ff-summary-item span {
	font-weight: 600;
}

.ff-summary-item strong {
	font-size: 18px;
	line-height: 1;
}

.ff-summary-dry {
	background: #eaf0ff;
	color: #36519a;
}

.ff-summary-frozen {
	background: #e5f6f1;
	color: #146b57;
}

.ff-summary-warn {
	background: #fff1d6;
	color: #8a5a00;
}

.ff-inline-warn {
	display: flex;
	align-items: flex-start;
	flex-wrap: wrap;
	gap: 5px 8px;
	padding: 9px 11px;
	border: 1px solid #efd8a8;
	border-radius: 10px;
	background: #fff9ea;
	color: #7a5200;
	font-size: 12px;
}

.ff-section {
	display: flex;
	flex-direction: column;
	gap: 8px;
}

.ff-section-head {
	display: flex;
	align-items: center;
	gap: 8px;
}

.ff-section-head h3 {
	font-size: 13px;
	font-weight: 700;
}

.ff-count {
	min-width: 20px;
	padding: 0 6px;
	border-radius: 999px;
	background: var(--grey-bg);
	color: var(--muted);
	font-size: 11px;
	line-height: 19px;
	text-align: center;
}

.ff-items {
	overflow: hidden;
	border: 1px solid var(--line);
	border-radius: 10px;
}

.ff-items-head,
.ff-item-row {
	display: grid;
	grid-template-columns: minmax(170px, 1.6fr) 64px 74px 74px 88px;
	gap: 8px;
	align-items: center;
}

.ff-items-head {
	padding: 8px 10px;
	background: var(--grey-bg);
	color: var(--muted);
	font-size: 10px;
	font-weight: 700;
	letter-spacing: 0.04em;
	text-transform: uppercase;
}

.ff-item-row {
	padding: 8px 10px;
	border-top: 1px solid var(--line);
	font-size: 12px;
}

.ff-item-main {
	display: flex;
	flex-direction: column;
	min-width: 0;
	gap: 1px;
}

.ff-item-main strong {
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
	font-size: 12.5px;
}

.ff-item-main span {
	color: var(--muted);
	font-size: 11px;
}

.ff-item-reason {
	color: #8a5a00 !important;
}

.ff-doc-group h4 {
	margin: 4px 0 5px;
	color: var(--muted);
	font-size: 11px;
	font-weight: 700;
	letter-spacing: 0.04em;
	text-transform: uppercase;
}

.ff-doc-list {
	display: flex;
	flex-direction: column;
	gap: 5px;
}

.ff-doc-row {
	display: grid;
	grid-template-columns: minmax(120px, 1fr) auto auto 16px;
	gap: 10px;
	align-items: center;
	width: 100%;
	padding: 8px 10px;
	border: 1px solid var(--line);
	border-radius: 9px;
	background: var(--surface);
	color: var(--ink);
	font: inherit;
	font-size: 12px;
	text-align: left;
	cursor: pointer;
}

.ff-doc-row:hover {
	border-color: var(--brand-light);
	background: var(--brand-softer);
}

.ff-doc-name {
	font-weight: 650;
	color: var(--brand);
}

.ff-doc-status {
	padding: 2px 7px;
	border-radius: 999px;
	background: #e4f6e9;
	color: #1f6b3a;
	font-size: 10.5px;
	font-weight: 650;
}

.ff-doc-status.draft {
	background: #fff2d9;
	color: #8a5a00;
}

.ff-doc-date {
	color: var(--muted);
	font-size: 11px;
}

.ff-muted {
	color: var(--muted);
	font-size: 12px;
}

.ff-readonly {
	padding-top: 4px;
	color: var(--faint);
	font-size: 11.5px;
}

.ff-run-section {
	padding: 12px;
	border: 1px solid var(--line);
	border-radius: 12px;
	background: var(--brand-softer);
}

.ff-run-status {
	padding: 2px 7px;
	border-radius: 999px;
	background: #eaf0ff;
	color: #36519a;
	font-size: 10.5px;
	font-weight: 700;
}

.ff-run-card {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 12px;
	flex-wrap: wrap;
	padding: 9px 11px;
	border: 1px solid var(--line);
	border-radius: 10px;
	background: var(--surface);
}

.ff-run-main,
.ff-run-pls {
	display: flex;
	align-items: center;
	gap: 8px;
	flex-wrap: wrap;
}

.ff-run-main {
	flex-direction: column;
	align-items: flex-start;
	gap: 2px;
}

.ff-run-main > span {
	color: var(--muted);
	font-size: 10.5px;
	font-weight: 700;
	letter-spacing: 0.04em;
	text-transform: uppercase;
}

.ff-run-link {
	display: inline-flex;
	align-items: center;
	gap: 5px;
	color: var(--brand);
	font-size: 12.5px;
	font-weight: 700;
	text-decoration: none;
}

.ff-run-link:hover {
	text-decoration: underline;
}

.ff-pl-link {
	padding: 5px 8px;
	border: 1px solid var(--line);
	border-radius: 8px;
	background: var(--surface);
	color: var(--ink);
	font: inherit;
	font-size: 11.5px;
	cursor: pointer;
}

.ff-pl-link:hover {
	border-color: var(--brand-light);
	background: var(--brand-soft);
}

.ff-generate-row {
	display: flex;
	align-items: center;
	gap: 10px;
	flex-wrap: wrap;
}

.ff-generate-btn {
	display: inline-flex;
	align-items: center;
	gap: 7px;
	flex: none;
}

.ff-generate-reason {
	margin: 0;
	font-size: 11.5px;
}

.ff-generate-error {
	padding: 8px 10px;
	border: 1px solid #f0c7c0;
	border-radius: 8px;
	background: #fff6f4;
	color: #9b2c1f;
	font-size: 12px;
}

.spin {
	animation: ff-spin 0.9s linear infinite;
}

.ff-drawer-loading {
	display: flex;
	flex-direction: column;
	gap: 10px;
	padding-top: 6px;
}

.ff-skel {
	height: 14px;
	border-radius: 6px;
	background: linear-gradient(90deg, var(--grey-bg) 25%, #f7f8fa 50%, var(--grey-bg) 75%);
	background-size: 200% 100%;
	animation: ff-shimmer 1.2s linear infinite;
}

.ff-skel-title {
	width: 55%;
	height: 22px;
}

.ff-drawer-state {
	display: flex;
	align-items: center;
	gap: 12px;
	padding: 16px;
	border: 1px solid var(--line);
	border-radius: 12px;
	color: var(--muted);
}

.ff-drawer-state > div {
	flex: 1;
}

.ff-drawer-state strong {
	display: block;
	color: var(--ink);
}

.ff-error {
	border-color: #f0c7c0;
	background: #fff6f4;
	color: #9b2c1f;
}

.ff-error strong {
	color: #7e2117;
}

.ff-stage {
	display: inline-flex;
	width: fit-content;
	padding: 3px 8px;
	border-radius: 999px;
	font-size: 11px;
	font-weight: 650;
	line-height: 16px;
}

.ff-stage-open {
	background: var(--grey-bg);
	color: var(--muted);
}

.ff-stage-picking {
	background: #e9f2ff;
	color: #1d5d9e;
}

.ff-stage-packing {
	background: #fff2d9;
	color: #8a5a00;
}

.ff-stage-ready {
	background: #e4f6e9;
	color: #1f6b3a;
}

.ff-stage-partially_delivered {
	background: #f0eaff;
	color: #5d3f9e;
}

.ff-stage-exception {
	background: #ffe9e6;
	color: #9b2c1f;
}

.ff-drawer-enter-active,
.ff-drawer-leave-active {
	transition: opacity 0.2s ease;
}

.ff-drawer-enter-active .ff-drawer,
.ff-drawer-leave-active .ff-drawer {
	transition: transform 0.24s cubic-bezier(0.32, 0.72, 0, 1);
}

.ff-drawer-enter-from,
.ff-drawer-leave-to {
	opacity: 0;
}

.ff-drawer-enter-from .ff-drawer,
.ff-drawer-leave-to .ff-drawer {
	transform: translateX(28px);
}

@keyframes ff-shimmer {
	to {
		background-position: -200% 0;
	}
}

@keyframes ff-spin {
	to {
		transform: rotate(360deg);
	}
}

@media (max-width: 820px) {
	.ff-drawer {
		width: 100%;
	}

	.ff-drawer-head {
		padding: 14px 16px;
	}

	.ff-drawer-body {
		padding: 14px 16px 24px;
	}

	.ff-meta {
		grid-template-columns: 1fr 1fr;
	}

	.ff-summary {
		gap: 7px;
	}

	.ff-summary-item {
		flex-direction: column;
		align-items: flex-start;
		gap: 3px;
		padding: 9px 10px;
	}

	.ff-items {
		border: 0;
		overflow: visible;
	}

	.ff-items-head {
		display: none;
	}

	.ff-item-row {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 5px 12px;
		margin-bottom: 7px;
		padding: 10px;
		border: 1px solid var(--line);
		border-radius: 9px;
	}

	.ff-item-main {
		grid-column: 1 / -1;
	}

	.ff-item-row > span::before {
		content: attr(data-label);
		display: block;
		margin-bottom: 1px;
		color: var(--muted);
		font-size: 9.5px;
		font-weight: 700;
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}

	.ff-doc-row {
		grid-template-columns: 1fr auto;
	}

	.ff-doc-date {
		grid-column: 1;
	}

	.ff-doc-row > svg {
		grid-column: 2;
		grid-row: 1 / 3;
	}

	.ff-readonly {
		padding-bottom: 8px;
	}
}

@media (max-width: 560px) {
	.ff-meta {
		grid-template-columns: 1fr;
	}

	.ff-summary {
		grid-template-columns: 1fr;
	}

	.ff-summary-item {
		flex-direction: row;
		align-items: baseline;
	}

	.ff-run-card {
		align-items: flex-start;
		flex-direction: column;
	}

	.ff-run-pls,
	.ff-generate-btn {
		width: 100%;
	}

	.ff-generate-btn {
		justify-content: center;
	}
}
</style>
