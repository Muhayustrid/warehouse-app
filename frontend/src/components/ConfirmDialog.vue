<script setup>
// Dialog konfirmasi generik — pengganti frappe.confirm (cancel request /
// cancel group request). Bahasa visual production_workspace: <dialog>.
import { ref, watch, nextTick } from 'vue'
import { TriangleAlert } from 'lucide-vue-next'

const props = defineProps({
	options: { type: Object, required: true }, // { title, message, confirmLabel, theme }
	onConfirm: { type: Function, required: true },
})
const show = defineModel({ type: Boolean, default: false })

const dlg = ref(null)

watch(show, (v) => {
	if (v) {
		nextTick(() => dlg.value?.showModal())
	} else {
		dlg.value?.close()
	}
})

function onCancel() {
	show.value = false
}

async function onPrimary() {
	props.onConfirm()
	show.value = false
}
</script>

<template>
	<Teleport to="body">
		<dialog ref="dlg" class="dialog" :aria-label="options.title" @cancel.prevent="onCancel">
			<header class="dlg-head">
				<div class="dlg-ico dlg-ico-danger"><TriangleAlert :size="17" :stroke-width="2" /></div>
				<div class="dlg-hgroup">
					<h3>{{ options.title }}</h3>
				</div>
			</header>
			<p class="dlg-note">{{ options.message }}</p>
			<div class="dlg-actions">
				<button type="button" class="btn" @click="show = false">Cancel</button>
				<button type="button" class="btn btn-danger" @click="onPrimary">
					{{ options.confirmLabel || 'Confirm' }}
				</button>
			</div>
		</dialog>
	</Teleport>
</template>

<style scoped>
.dlg-note { color: var(--muted, inherit); font-size: 13.5px; margin: 0; }
.dlg-ico-danger { background: var(--bad-bg, #f6e1dc); color: var(--bad-ink, #9c4736); }
.btn-danger { background: var(--bad-bg, #f6e1dc); border-color: transparent; color: var(--bad-ink, #9c4736); }
.btn-danger:hover:not(:disabled) { background: var(--bad-ink, #9c4736); color: #fff; }
</style>
