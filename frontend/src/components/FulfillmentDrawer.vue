<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { AlertTriangle, ExternalLink, RefreshCw, X } from 'lucide-vue-next'
import { fetchOrderPreview, stageLabel } from '@/data/fulfillment'
import { fmtDate, fmtQty } from '@/lib/format'

const props = defineProps({
	open: { type: Boolean, default: false },
	salesOrder: { type: String, default: null },
})
const emit = defineEmits(['close'])

const data = ref(null)
const loading = ref(false)
const error = ref('')
const closeBtn = ref(null)
const drawer = ref(null)
let loadToken = 0

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

const groups = computed(() =>
	['dry', 'frozen', 'unclassified'].map((key) => ({
		key,
		label: GROUP_LABELS[key],
		items: data.value?.groups?.[key] || [],
	})),
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
			loading.value = false
			document.body.style.overflow = ''
			return
		}
		document.body.style.overflow = 'hidden'
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
									<span>Dry items</span>
									<strong>{{ data.groups.dry.length }}</strong>
								</div>
								<div class="ff-summary-item ff-summary-frozen">
									<span>Frozen items</span>
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
								Read-only preview. Picking, packing, and delivery actions are not available in F1.
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
</style>
