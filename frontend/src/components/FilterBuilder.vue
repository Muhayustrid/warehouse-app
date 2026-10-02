<script setup>
// Panel filter ala list view: baris [Field][operator][Nilai], field dibatasi
// whitelist server (filter_fields) — bentuk input mengikuti fieldtype
// (Date = field rentang kalender, Select/Float/Data input biasa).
// Date selalu 'between' [from, to]: server mengubah satu sisi kosong
// menjadi >= / <= (lihat _date_filter gudang_request).
import { computed } from 'vue'
import { Popover } from '@frappe-ui/components/Popover'
import { Button } from '@frappe-ui/components/Button'
import FeatherIcon from '@frappe-ui/components/FeatherIcon.vue'
import DateRangeField from '@/components/DateRangeField.vue'

const props = defineProps({
	meta: { type: Object, default: null },
})
const filters = defineModel({ type: Array, default: () => [] })
const emit = defineEmits(['change'])

const OP_LABELS = {
	'=': '=',
	'!=': '≠',
	like: 'like',
	'not like': 'not like',
	between: 'between',
	'>=': '≥',
	'<=': '≤',
	'>': '>',
	'<': '<',
}

const activeCount = computed(
	() =>
		filters.value.filter((f) =>
			Array.isArray(f.value)
				? f.value.some((x) => String(x || '').trim() !== '')
				: String(f.value || '').trim() !== '',
		).length,
)

function metaFor(field) {
	return (props.meta || {})[field] || { operators: ['like'], fieldtype: 'Data' }
}

function rangeOf(f) {
	return Array.isArray(f.value) ? f.value : [f.value || '', '']
}

function emitCopy() {
	filters.value = filters.value.map((f) => ({ ...f }))
	// pemicu reload eksplisit — watch deep di parent tidak selalu andal
	// terhadap mutasi array dari child (quirk defineModel di dev)
	emit('change')
}

function onFieldChange(i, e) {
	const field = e.target.value
	const m = metaFor(field)
	filters.value[i] = { field, operator: m.operators[0], value: '' }
	emitCopy()
}

function onOperatorChange(i, e) {
	filters.value[i].operator = e.target.value
	emitCopy()
}

function onValueChange(i, e) {
	filters.value[i].value = e.target.value || ''
	emitCopy()
}

function onRangeChange(i, part, iso) {
	const f = filters.value[i]
	const [from, to] = rangeOf(f)
	f.value = part === 'from' ? [iso || '', to || ''] : [from || '', iso || '']
	emitCopy()
}

function addFilter() {
	const keys = Object.keys(props.meta || {})
	if (!keys.length) {
		return
	}
	const first = keys[0]
	filters.value.push({ field: first, operator: metaFor(first).operators[0], value: '' })
	emitCopy()
}

function removeFilter(i) {
	filters.value.splice(i, 1)
	emitCopy()
}

function clearAll() {
	// kosongkan SECARA IN-PLACE — assignment `filters.value = []` lewat
	// defineModel tak sampai ke parent (pola mutasi dipakai semua handler lain)
	filters.value.splice(0, filters.value.length)
	emitCopy()
}
</script>

<template>
	<Popover placement="bottom-start">
		<template #target="{ togglePopover }">
			<Button variant="subtle" label="Filter" icon-left="filter" @click="togglePopover()">
				<template #suffix>
					<span
						v-if="activeCount"
						class="rounded-full bg-surface-selected px-1.5 text-xs font-semibold text-ink-gray-7"
						>{{ activeCount }}</span
					>
				</template>
			</Button>
		</template>
		<template #body-main>
			<div class="w-[400px] max-w-[calc(100vw-2rem)] p-3">
				<p v-if="!filters.length" class="py-2 text-center text-sm text-ink-gray-4">
					No filters
				</p>
				<div v-else class="space-y-2">
					<div
						v-for="(f, i) in filters"
						:key="i"
						class="grid min-w-0 grid-cols-[1.1fr_0.9fr_1.3fr_auto] items-center gap-1.5"
					>
						<select
							class="h-8 min-w-0 rounded border border-outline-gray-2 bg-surface-modal px-1.5 text-xs text-ink-gray-7"
							:value="f.field"
							@change="onFieldChange(i, $event)"
						>
							<option v-for="(cfg, key) in meta" :key="key" :value="key">
								{{ cfg.label }}
							</option>
						</select>
						<!-- Date: alur rentang kalender sudah mencakup from/to — operator dikunci -->
						<span
							v-if="metaFor(f.field).fieldtype === 'Date'"
							class="truncate text-xs text-ink-gray-5"
							title="Pick the first date for 'from', the second for 'to' — one date alone filters from that day"
							>between</span
						>
						<select
							v-else
							class="h-8 min-w-0 rounded border border-outline-gray-2 bg-surface-modal px-1.5 text-xs text-ink-gray-7"
							:value="f.operator"
							@change="onOperatorChange(i, $event)"
						>
							<option v-for="op in metaFor(f.field).operators" :key="op" :value="op">
								{{ OP_LABELS[op] || op }}
							</option>
						</select>
						<!-- nilai -->
						<DateRangeField
							v-if="metaFor(f.field).fieldtype === 'Date'"
							class="min-w-0"
							:from="rangeOf(f)[0] || ''"
							:to="rangeOf(f)[1] || ''"
							@update:from="onRangeChange(i, 'from', $event)"
							@update:to="onRangeChange(i, 'to', $event)"
						/>
						<select
							v-else-if="metaFor(f.field).fieldtype === 'Select'"
							class="h-8 w-full min-w-0 rounded border border-outline-gray-2 bg-surface-modal px-1.5 text-xs text-ink-gray-7"
							:value="f.value || ''"
							@change="onValueChange(i, $event)"
						>
							<option value=""></option>
							<option v-for="o in metaFor(f.field).options || []" :key="o" :value="o">
								{{ o }}
							</option>
						</select>
						<input
							v-else-if="metaFor(f.field).fieldtype === 'Float'"
							type="number"
							step="1"
							min="0"
							class="h-8 w-full min-w-0 rounded border border-outline-gray-2 bg-surface-modal px-1.5 text-xs text-ink-gray-7"
							:value="f.value || ''"
							@change="onValueChange(i, $event)"
						/>
						<input
							v-else
							type="text"
							class="h-8 w-full min-w-0 rounded border border-outline-gray-2 bg-surface-modal px-1.5 text-xs text-ink-gray-7"
							:placeholder="metaFor(f.field).placeholder || ''"
							:value="f.value || ''"
							@input="onValueChange(i, $event)"
						/>
						<button
							class="flex h-6 w-6 shrink-0 items-center justify-center rounded text-ink-gray-4 hover:bg-surface-gray-3 hover:text-ink-gray-7"
							title="Remove filter"
							@click="removeFilter(i)"
						>
							<FeatherIcon name="x" class="h-3.5 w-3.5" />
						</button>
					</div>
				</div>
				<div class="mt-3 flex items-center justify-between border-t border-outline-gray-1 pt-2">
					<button
						class="text-sm font-medium text-ink-gray-6 hover:text-ink-gray-9"
						@click="addFilter"
					>
						+ Add Filter
					</button>
					<button
						v-if="filters.length"
						class="text-sm text-ink-gray-4 hover:text-ink-gray-7"
						@click="clearAll"
					>
						Clear All
					</button>
				</div>
			</div>
		</template>
	</Popover>
</template>
