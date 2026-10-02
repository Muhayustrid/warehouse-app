<script setup>
// Dialog konfirmasi request massal (N WO) — tanpa input: qty = hasil penuh
// tiap WO (server otoritatif, semantik W30). Submit berurutan per WO;
// hasil parsial ditampilkan apa adanya (pola submit_bulk halaman klasik).
import { ref, computed, watch } from 'vue'
import { Dialog } from '@frappe-ui/components/Dialog'
import { Button } from '@frappe-ui/components/Button'
import FeatherIcon from '@frappe-ui/components/FeatherIcon.vue'
import { createRequest } from '@/data/board'
import { fmtNum } from '@/lib/format'

const props = defineProps({
	rows: { type: Array, required: true }, // WO terpilih
})
const emit = defineEmits(['done'])
const show = defineModel({ type: Boolean, default: false })

const phase = ref('confirm') // confirm | result
const submitting = ref(false)
const okList = ref([])
const failList = ref([])

const title = computed(() =>
	phase.value === 'result'
		? okList.value.length
			? 'Partially created'
			: 'All failed'
		: `Handover Request (${props.rows.length} Work Orders)`,
)

function rowQty(r) {
	const qty = r.expected_units != null ? r.expected_units : Math.round(Number(r.produced_qty || 0))
	return `${fmtNum(qty)} ${r.display_uom || r.stock_uom || ''}`
}

async function submit() {
	submitting.value = true
	okList.value = []
	failList.value = []
	for (const r of props.rows) {
		try {
			const res = await createRequest(r.name)
			// frappeRequest mengembalikan message endpoint langsung
			okList.value.push(`${res.material_request} (${r.name})`)
		} catch (e) {
			failList.value.push({ wo: r.name, error: e.message })
		}
	}
	submitting.value = false
	phase.value = 'result'
	emit('done', { ok: okList.value.length, fail: failList.value.length })
}

function close() {
	show.value = false
}

// dialog ditutup (apapun jalannya) → kembali ke fase konfirmasi
watch(show, (v) => {
	if (!v) {
		setTimeout(() => {
			phase.value = 'confirm'
		}, 200)
	}
})
</script>

<template>
	<Dialog v-model="show" :options="{ title, size: 'xl' }">
		<template #body-content>
			<template v-if="phase === 'confirm'">
				<p class="mb-4 text-sm text-ink-gray-5">
					Request qty equals the full produced output of each Work Order.
				</p>
				<div class="overflow-hidden rounded-lg border border-outline-gray-1">
					<table class="w-full text-sm">
						<tbody>
							<tr
								v-for="r in rows"
								:key="r.name"
								class="border-b border-outline-gray-1 last:border-b-0"
							>
								<td class="px-3 py-2.5">
									<div class="font-medium text-ink-gray-8">
										Batch <b>{{ r.custom_adonan_ke || '-' }}</b> · {{ r.item_name }}
									</div>
									<div class="mt-0.5 text-xs text-ink-gray-5">
										{{ r.name }} · yield {{ fmtNum(r.produced_qty) }}
										{{ r.stock_uom }}
									</div>
								</td>
								<td class="whitespace-nowrap px-3 py-2.5 text-right font-medium text-ink-gray-7">
									{{ rowQty(r) }}
								</td>
							</tr>
						</tbody>
					</table>
				</div>
			</template>
			<template v-else>
				<p v-if="okList.length" class="mb-3 text-sm text-ink-gray-6">
					<b>Created:</b> {{ okList.join(', ') }}
				</p>
				<div class="space-y-2">
					<div
						v-for="f in failList"
						:key="f.wo"
						class="flex items-start gap-2 rounded-md bg-surface-red-1 p-2.5 text-sm text-ink-red-4"
					>
						<FeatherIcon name="alert-circle" class="mt-0.5 h-4 w-4 shrink-0" />
						<span><b>{{ f.wo }}</b> — {{ f.error }}</span>
					</div>
				</div>
			</template>
		</template>
		<template #actions>
			<template v-if="phase === 'confirm'">
				<Button variant="subtle" label="Cancel" @click="show = false" />
				<Button
					variant="solid"
					label="Create Request"
					:loading="submitting"
					@click="submit"
				/>
			</template>
			<template v-else>
				<Button variant="solid" label="Close" @click="close" />
			</template>
		</template>
	</Dialog>
</template>
