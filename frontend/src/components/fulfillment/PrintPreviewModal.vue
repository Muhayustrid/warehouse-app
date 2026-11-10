<script setup>
import { computed, ref, watch } from 'vue'
import { Printer, X } from 'lucide-vue-next'

const props = defineProps({
	open: { type: Boolean, default: false },
	title: { type: String, default: 'Cetak Dokumen' },
	items: {
		type: Array,
		default: () => [], // e.g. [{ label: 'Dry', doctype: 'Pick List', name: 'STO-PICK-xxx', format: '' }]
	},
})

const emit = defineEmits(['close'])

const activeIndex = ref(0)
const iframeRef = ref(null)

watch(
	() => props.open,
	(val) => {
		if (val) {
			activeIndex.value = 0
		}
	},
)

const currentDoc = computed(() => {
	if (!props.items?.length) return null
	return props.items[activeIndex.value] || props.items[0]
})

const printUrl = computed(() => {
	if (!currentDoc.value) return ''
	let url = `/printview?doctype=${encodeURIComponent(currentDoc.value.doctype || 'Pick List')}&name=${encodeURIComponent(currentDoc.value.name)}&trigger_print=0`
	if (currentDoc.value.format) {
		url += `&format=${encodeURIComponent(currentDoc.value.format)}`
	}
	return url
})

function triggerPrint() {
	if (iframeRef.value && iframeRef.value.contentWindow) {
		iframeRef.value.contentWindow.focus()
		iframeRef.value.contentWindow.print()
	}
}
</script>

<template>
	<Teleport to="body">
		<Transition name="fade">
			<div v-if="open && currentDoc" class="print-modal-layer" @click.self="$emit('close')">
				<div class="print-modal-card" role="dialog" aria-modal="true" aria-label="Print Preview">
					<!-- Header -->
					<div class="print-modal-head">
						<div class="print-modal-title">
							<h3>{{ title }}</h3>
							<span class="mono print-doc-code">{{ currentDoc.name }}</span>
						</div>

						<!-- Tabs if multiple documents (Dry & Frozen) -->
						<div v-if="items.length > 1" class="print-tabs">
							<button
								v-for="(item, idx) in items"
								:key="item.name"
								type="button"
								class="print-tab-btn"
								:class="{ on: activeIndex === idx }"
								@click="activeIndex = idx"
							>
								{{ item.label || item.name }}
							</button>
						</div>

						<!-- Actions (Close only on top-right) -->
						<div class="print-modal-actions">
							<button type="button" class="btn iconbtn" aria-label="Tutup" @click="$emit('close')">
								<X :size="16" :stroke-width="2" />
							</button>
						</div>
					</div>

					<!-- Body with iframe -->
					<div class="print-modal-body">
						<iframe
							ref="iframeRef"
							:src="currentDoc.html ? undefined : printUrl"
							:srcdoc="currentDoc.html || undefined"
							class="print-iframe"
							title="Print Preview Frame"
						/>
					</div>

					<!-- Footer with Cetak button at bottom-left -->
					<div class="print-modal-foot">
						<button type="button" class="btn btn-primary print-action-btn" @click="triggerPrint">
							<Printer :size="15" :stroke-width="2" />
							<span>Cetak Sekarang</span>
						</button>
					</div>
				</div>
			</div>
		</Transition>
	</Teleport>
</template>

<style scoped>
.print-modal-layer {
	position: fixed;
	inset: 0;
	z-index: 100;
	display: flex;
	align-items: center;
	justify-content: center;
	background: rgba(15, 23, 42, 0.55);
	backdrop-filter: blur(2px);
	padding: 20px;
}

.print-modal-card {
	background: #ffffff;
	border: 1px solid var(--line, #e2e8f0);
	border-radius: 12px;
	box-shadow: 0 24px 60px rgba(0, 0, 0, 0.25);
	width: min(920px, 95vw);
	height: min(88vh, 850px);
	display: flex;
	flex-direction: column;
	overflow: hidden;
}

.print-modal-head {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 12px 20px;
	border-bottom: 1px solid var(--line, #e2e8f0);
	background: #ffffff;
	gap: 16px;
	flex-shrink: 0;
}

.print-modal-title {
	display: flex;
	align-items: baseline;
	gap: 8px;
	min-width: 0;
}

.print-modal-title h3 {
	font-size: 16px;
	font-weight: 750;
	color: var(--ink, #1e293b);
	margin: 0;
}

.print-doc-code {
	font-size: 12px;
	color: var(--muted, #64748b);
}

.print-tabs {
	display: flex;
	align-items: center;
	gap: 4px;
	background: var(--bg, #f1f5f9);
	padding: 3px;
	border-radius: 8px;
}

.print-tab-btn {
	padding: 4px 12px;
	font-size: 12px;
	font-weight: 600;
	border: none;
	border-radius: 6px;
	background: transparent;
	color: var(--muted, #64748b);
	cursor: pointer;
	transition: all 0.15s ease;
}

.print-tab-btn.on {
	background: #ffffff;
	color: var(--brand, #3368a0);
	box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.print-modal-actions {
	display: flex;
	align-items: center;
	gap: 8px;
	flex-shrink: 0;
}

.print-action-btn {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	padding: 8px 18px;
	font-size: 13.5px;
	font-weight: 600;
	border-radius: 8px;
}

.print-modal-foot {
	display: flex;
	align-items: center;
	justify-content: flex-end;
	padding: 12px 20px;
	border-top: 1px solid var(--line, #e2e8f0);
	background: #ffffff;
	flex-shrink: 0;
}

.print-modal-body {
	flex: 1;
	background: #f8fafc;
	overflow: hidden;
	position: relative;
}

.print-iframe {
	width: 100%;
	height: 100%;
	border: none;
	background: #ffffff;
}

.fade-enter-active,
.fade-leave-active {
	transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
	opacity: 0;
}
</style>
