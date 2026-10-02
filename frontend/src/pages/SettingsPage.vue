<script setup>
// Settings gudang (SPA, W33) — port halaman klasik gudang_settings:
// dua dropdown warehouse + daftar item grup-request (chip nama + kode),
// satu tombol Save menyimpan semuanya.
import { ref, computed, onMounted } from 'vue'
import { Autocomplete } from '@frappe-ui/components/Autocomplete'
import { Button } from '@frappe-ui/components/Button'
import { FormControl } from '@frappe-ui/components/FormControl'
import FeatherIcon from '@frappe-ui/components/FeatherIcon.vue'
import { toast } from '@/lib/toast'
import {
	fetchWarehouseOptions,
	fetchHandoverSettings,
	saveHandoverWarehouses,
	fetchGroupItems,
	saveGroupItems,
	searchItems,
	fetchItemName,
} from '@/data/settings'

const warehouses = ref([])
const source = ref('')
const target = ref('')
const groupItems = ref([]) // [{code, name}]
const saving = ref(false)
const loading = ref(true)

const itemOptions = ref([])
const pickedItem = ref(null)

onMounted(async () => {
	try {
		const [opts, settings, grp] = await Promise.all([
			fetchWarehouseOptions(),
			fetchHandoverSettings(),
			fetchGroupItems().catch(() => null),
		])
		// frappeRequest mengembalikan message endpoint langsung
		warehouses.value = Array.isArray(opts) ? opts : []
		source.value = settings.source || ''
		target.value = settings.target || ''
		if (grp) {
			const names = grp.names || {}
			groupItems.value = (grp.items || []).map((code) => ({
				code,
				name: names[code] || code,
			}))
		}
	} catch (e) {
		toast.error(e.message)
	} finally {
		loading.value = false
	}
})

const warehouseSelectOptions = computed(() => [
	{ label: '—', value: '' },
	...warehouses.value.map((w) => ({ label: w, value: w })),
])

function removeItem(i) {
	groupItems.value.splice(i, 1)
}

async function onItemQuery(q) {
	if (!q || !q.trim()) {
		itemOptions.value = []
		return
	}
	try {
		itemOptions.value = await searchItems(q)
	} catch (e) {
		itemOptions.value = []
	}
}

async function onItemPicked(option) {
	pickedItem.value = null
	const code = option && option.value
	if (!code) {
		return
	}
	if (groupItems.value.some((it) => it.code === code)) {
		toast.warning('Item already in the list')
		return
	}
	const name = await fetchItemName(code).catch(() => code)
	groupItems.value.push({ code, name })
}

async function save() {
	saving.value = true
	try {
		const [rw] = await Promise.all([
			saveHandoverWarehouses(source.value, target.value),
			saveGroupItems(groupItems.value.map((it) => it.code)),
		])
		source.value = rw.source || ''
		target.value = rw.target || ''
		toast.success('Settings saved')
	} catch (e) {
		toast.error(e.message)
	} finally {
		saving.value = false
	}
}
</script>

<template>
	<div class="mx-auto max-w-2xl space-y-4">
		<div>
			<h1 class="text-2xl font-semibold tracking-tight text-ink-gray-9">Settings</h1>
			<p class="mt-0.5 text-sm text-ink-gray-5">
				Warehouses used when the warehouse team creates handover requests.
			</p>
		</div>

		<div class="space-y-6 rounded-lg border border-outline-gray-1 bg-surface-modal p-5">
			<div class="space-y-1.5">
				<label class="text-sm font-medium text-ink-gray-7">Source Warehouse</label>
				<FormControl
					v-model="source"
					type="select"
					:options="warehouseSelectOptions"
					:disabled="loading"
				/>
				<p class="text-xs text-ink-gray-4">
					Where the goods come from. Leave empty to follow the production lot warehouse
					automatically.
				</p>
			</div>

			<div class="space-y-1.5">
				<label class="text-sm font-medium text-ink-gray-7">
					Target Warehouse <span class="text-ink-red-4">*</span>
				</label>
				<FormControl
					v-model="target"
					type="select"
					:options="warehouseSelectOptions"
					:disabled="loading"
				/>
				<p class="text-xs text-ink-gray-4">
					Where handover requests deliver the goods. Required to create a request.
				</p>
			</div>

			<div class="space-y-2">
				<label class="text-sm font-medium text-ink-gray-7">Group Request Items</label>
				<p class="text-xs text-ink-gray-4">
					Items eligible for group requests — several Work Orders of one item with shared
					boxes.
				</p>
				<div v-if="groupItems.length" class="flex flex-wrap gap-2">
					<div
						v-for="(it, i) in groupItems"
						:key="it.code"
						class="flex items-center gap-2 rounded-full border border-outline-gray-2 bg-surface-gray-1 py-1 pl-3 pr-1.5"
					>
						<div class="leading-tight">
							<div class="text-sm font-medium text-ink-gray-8">{{ it.name }}</div>
							<div class="text-xs text-ink-gray-4">{{ it.code }}</div>
						</div>
						<button
							class="flex h-6 w-6 items-center justify-center rounded-full text-ink-gray-4 hover:bg-surface-gray-3 hover:text-ink-gray-7"
							title="Remove"
							@click="removeItem(i)"
						>
							<FeatherIcon name="x" class="h-3.5 w-3.5" />
						</button>
					</div>
				</div>
				<p v-else class="text-sm text-ink-gray-4">No items configured</p>
				<Autocomplete
					v-model="pickedItem"
					:options="itemOptions"
					placeholder="Add an item..."
					@update:query="onItemQuery"
					@update:model-value="onItemPicked"
				/>
			</div>

			<div class="flex justify-end border-t border-outline-gray-1 pt-4">
				<Button variant="solid" label="Save" :loading="saving" @click="save" />
			</div>
		</div>
	</div>
</template>
