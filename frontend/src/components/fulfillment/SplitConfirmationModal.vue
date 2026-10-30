<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
	ArrowRight,
	CheckCircle2,
	ChevronDown,
	Printer,
	X,
} from 'lucide-vue-next'
import { fmtQty } from '@/lib/format'

const props = defineProps({
	open: { type: Boolean, default: false },
	workspace: { type: Object, default: null },
	salesOrder: { type: String, default: '' },
})

const emit = defineEmits(['close', 'print-both', 'print-dry', 'print-frozen'])

const dropdownRef = ref(null)
const dropdownOpen = ref(false)
const selectedPrintType = ref('both')

const dryLabel = computed(() => props.workspace?.profile?.dry_display_name || 'Dry')
const frozenLabel = computed(() => props.workspace?.profile?.frozen_display_name || 'Frozen')
const hasDry = computed(() => Boolean(props.workspace?.groups?.dry?.pick_list))
const hasFrozen = computed(() => Boolean(props.workspace?.groups?.frozen?.pick_list))

const currentPrintLabel = computed(() => {
	if (selectedPrintType.value === 'dry') return `Cetak ${dryLabel.value}`
	if (selectedPrintType.value === 'frozen') return `Cetak ${frozenLabel.value}`
	return 'Cetak Pick List'
})

function onDocClick(e) {
	if (dropdownRef.value && !dropdownRef.value.contains(e.target)) {
		dropdownOpen.value = false
	}
}

onMounted(() => {
	window.addEventListener('click', onDocClick)
})

onBeforeUnmount(() => {
	window.removeEventListener('click', onDocClick)
})

function handleSelectPrint(type) {
	selectedPrintType.value = type
	dropdownOpen.value = false
	if (type === 'both') {
		emit('print-both')
	} else if (type === 'dry') {
		emit('print-dry')
	} else if (type === 'frozen') {
		emit('print-frozen')
	}
}
</script>

<template>
	<Teleport to="body">
		<Transition name="split-modal-fade">
			<div v-if="open && workspace" class="split-modal-layer" @click.self="$emit('close')">
				<div class="split-modal-card" role="dialog" aria-modal="true" aria-labelledby="split-modal-title">
					<!-- Header -->
					<div class="split-modal-head">
						<div>
							<div class="split-badge-success">
								<CheckCircle2 :size="15" :stroke-width="2.5" />
								<span>Pemisahan Berhasil</span>
							</div>
							<h3 id="split-modal-title">Pick List {{ dryLabel }} & {{ frozenLabel }} Berhasil Dibuat</h3>
							<p class="split-sub">
								Sales Order: <strong>{{ salesOrder }}</strong>
								<span v-if="workspace.run?.name"> · Run: <strong>{{ workspace.run.name }}</strong></span>
							</p>
						</div>
						<button type="button" class="btn iconbtn" aria-label="Tutup" @click="$emit('close')">
							<X :size="16" :stroke-width="2" />
						</button>
					</div>

					<!-- Body Cards -->
					<div class="split-modal-body">
						<!-- Dry Card -->
						<div v-if="hasDry" class="split-group-card split-card-dry">
							<div class="split-group-head">
								<div class="split-group-title">
									<span class="ws-pill ws-dry">{{ dryLabel }}</span>
									<strong class="split-pl-code">{{ workspace.groups.dry.pick_list }}</strong>
								</div>
								<span class="badge b-draft">Draft</span>
							</div>
							<div class="split-item-list">
								<div
									v-for="item in workspace.groups.dry.rows"
									:key="item.name || item.item_code"
									class="split-item-row"
								>
									<div class="split-item-main">
										<span class="split-item-name">{{ item.item_name || item.item_code }}</span>
										<span class="split-item-sub">{{ item.item_code }} · {{ item.warehouse }}</span>
									</div>
									<div class="split-item-qty">
										<strong>{{ fmtQty(item.qty) }}</strong>
										<span>{{ item.uom }}</span>
									</div>
								</div>
							</div>
						</div>

						<!-- Frozen Card -->
						<div v-if="hasFrozen" class="split-group-card split-card-frozen">
							<div class="split-group-head">
								<div class="split-group-title">
									<span class="ws-pill ws-frozen">{{ frozenLabel }}</span>
									<strong class="split-pl-code">{{ workspace.groups.frozen.pick_list }}</strong>
								</div>
								<span class="badge b-draft">Draft</span>
							</div>
							<div class="split-item-list">
								<div
									v-for="item in workspace.groups.frozen.rows"
									:key="item.name || item.item_code"
									class="split-item-row"
								>
									<div class="split-item-main">
										<span class="split-item-name">{{ item.item_name || item.item_code }}</span>
										<span class="split-item-sub">{{ item.item_code }} · {{ item.warehouse }}</span>
									</div>
									<div class="split-item-qty">
										<strong>{{ fmtQty(item.qty) }}</strong>
										<span>{{ item.uom }}</span>
									</div>
								</div>
							</div>
						</div>
					</div>

					<!-- Footer Actions -->
					<div class="split-modal-foot">
						<!-- Dropdown Print Button -->
						<div ref="dropdownRef" class="split-print-dropdown">
							<button
								type="button"
								class="btn btn-outline split-print-btn"
								:class="{ 'is-open': dropdownOpen }"
								title="Pilih opsi cetak dokumen Pick List"
								@click.stop="dropdownOpen = !dropdownOpen"
							>
								<Printer :size="15" :stroke-width="2" class="split-print-ico" />
								<span>{{ currentPrintLabel }}</span>
								<ChevronDown :size="14" :stroke-width="2" class="split-chev" :class="{ open: dropdownOpen }" />
							</button>

							<Transition name="split-menu">
								<div v-if="dropdownOpen" class="split-dropdown-menu" role="menu">
									<button
										v-if="hasDry && hasFrozen"
										type="button"
										class="split-menu-item"
										@click="handleSelectPrint('both')"
									>
										<Printer :size="15" :stroke-width="2" class="menu-icon" />
										<div class="menu-text">
											<strong>Cetak Keduanya</strong>
											<span>Buka tab cetak Pick List {{ dryLabel }} & {{ frozenLabel }}</span>
										</div>
									</button>
									<button
										v-if="hasDry"
										type="button"
										class="split-menu-item"
										@click="handleSelectPrint('dry')"
									>
										<Printer :size="15" :stroke-width="2" class="menu-icon" />
										<div class="menu-text">
											<strong>Cetak {{ dryLabel }} saja</strong>
											<span>{{ workspace.groups?.dry?.pick_list }}</span>
										</div>
									</button>
									<button
										v-if="hasFrozen"
										type="button"
										class="split-menu-item"
										@click="handleSelectPrint('frozen')"
									>
										<Printer :size="15" :stroke-width="2" class="menu-icon" />
										<div class="menu-text">
											<strong>Cetak {{ frozenLabel }} saja</strong>
											<span>{{ workspace.groups?.frozen?.pick_list }}</span>
										</div>
									</button>
								</div>
							</Transition>
						</div>

						<!-- Primary Start Picking -->
						<button type="button" class="btn btn-primary split-start-btn" @click="$emit('close')">
							<span>Mulai Picking</span>
							<ArrowRight :size="15" :stroke-width="2" />
						</button>
					</div>
				</div>
			</div>
		</Transition>
	</Teleport>
</template>

<style scoped>
.split-modal-layer {
	position: fixed;
	inset: 0;
	z-index: 100;
	display: flex;
	align-items: center;
	justify-content: center;
	background: rgba(15, 23, 42, 0.5);
	backdrop-filter: blur(2px);
	padding: 16px;
}

.split-modal-card {
	background: #ffffff;
	border: 1px solid var(--line, #e2e8f0);
	border-radius: 12px;
	box-shadow: 0 20px 48px rgba(0, 0, 0, 0.2);
	width: 100%;
	max-width: 760px;
	max-height: 90vh;
	display: flex;
	flex-direction: column;
	overflow: hidden;
}

.split-modal-head {
	display: flex;
	align-items: flex-start;
	justify-content: space-between;
	padding: 18px 22px;
	border-bottom: 1px solid var(--line, #e2e8f0);
	background: #ffffff;
}

.split-badge-success {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	padding: 2px 8px;
	background: #ecfdf5;
	color: #059669;
	font-size: 11.5px;
	font-weight: 700;
	border-radius: 4px;
	margin-bottom: 4px;
}

.split-modal-head h3 {
	font-size: 18px;
	font-weight: 750;
	color: var(--ink, #0f172a);
}

.split-sub {
	margin-top: 3px;
	font-size: 12.5px;
	color: var(--muted, #64748b);
}

.split-modal-body {
	display: flex;
	flex-direction: column;
	gap: 14px;
	padding: 18px 22px;
	overflow-y: auto;
}

.split-group-card {
	border: 1px solid var(--line, #e2e8f0);
	border-radius: 8px;
	overflow: hidden;
	background: #ffffff;
}

.split-card-dry {
	border-left: 4px solid #2b72ba;
}

.split-card-frozen {
	border-left: 4px solid #0284c7;
}

.split-group-head {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 10px 14px;
	background: var(--bg, #f8fafc);
	border-bottom: 1px solid var(--line, #e2e8f0);
}

.split-group-title {
	display: flex;
	align-items: center;
	gap: 8px;
}

.split-pl-code {
	font-size: 13.5px;
	color: var(--ink, #0f172a);
	font-weight: 700;
}

.split-item-list {
	padding: 4px 14px;
}

.split-item-row {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 8px 0;
	border-bottom: 1px solid var(--line, #f1f5f9);
}

.split-item-row:last-child {
	border-bottom: none;
}

.split-item-main {
	display: flex;
	flex-direction: column;
	gap: 2px;
}

.split-item-name {
	font-size: 13px;
	font-weight: 600;
	color: var(--ink, #0f172a);
}

.split-item-sub {
	font-size: 11.5px;
	color: var(--muted, #64748b);
}

.split-item-qty {
	display: flex;
	align-items: baseline;
	gap: 4px;
	font-size: 13px;
}

.split-item-qty strong {
	font-size: 15px;
	color: var(--ink, #0f172a);
}

.split-item-qty span {
	font-size: 11.5px;
	color: var(--muted, #64748b);
}

.split-modal-foot {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 12px;
	padding: 14px 22px;
	border-top: 1px solid var(--line, #e2e8f0);
	background: var(--bg, #f8fafc);
	position: relative;
}

/* Dropdown Print */
.split-print-dropdown {
	position: relative;
}

.split-print-btn {
	display: inline-flex;
	align-items: center;
	gap: 8px;
	padding: 8px 14px;
	font-size: 13.5px;
	font-weight: 600;
	border-radius: 8px;
	background: #ffffff;
	border: 1px solid var(--line2, #cbd5e1);
	color: var(--ink, #1e293b);
	cursor: pointer;
	transition: all 0.15s ease;
}

.split-print-btn:hover,
.split-print-btn.is-open {
	border-color: var(--brand, #2b72ba);
	color: var(--brand, #2b72ba);
	background: #ffffff;
}

.split-print-ico {
	color: var(--brand, #2b72ba);
	flex-shrink: 0;
}

.split-chev {
	color: var(--muted, #64748b);
	transition: transform 0.2s ease;
	margin-left: 2px;
}

.split-chev.open {
	transform: rotate(180deg);
}

.split-dropdown-menu {
	position: absolute;
	bottom: calc(100% + 8px);
	left: 0;
	z-index: 110;
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

.split-start-btn {
	display: inline-flex;
	align-items: center;
	gap: 8px;
	padding: 9px 18px;
	font-size: 13.5px;
	font-weight: 650;
	border-radius: 8px;
}

/* Animations */
.split-modal-fade-enter-active,
.split-modal-fade-leave-active {
	transition: opacity 0.2s ease;
}

.split-modal-fade-enter-from,
.split-modal-fade-leave-to {
	opacity: 0;
}

.split-menu-enter-active,
.split-menu-leave-active {
	transition: all 0.15s ease;
}

.split-menu-enter-from,
.split-menu-leave-to {
	opacity: 0;
	transform: translateY(6px);
}
</style>
