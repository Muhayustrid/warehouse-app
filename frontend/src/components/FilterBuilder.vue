<script setup>
// Panel filter ala list view: baris [Field][operator][Nilai], field dibatasi
// whitelist server (filter_fields) — bentuk input mengikuti fieldtype
// (Date = field rentang kalender, Select/Float/Data input biasa).
// Date selalu 'between' [from, to]: server mengubah satu sisi kosong
// menjadi >= / <= (lihat _date_filter gudang_request).
// Bahasa visual production_workspace: .filterwrap/.filterpanel/.frows.
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Filter, Plus, X } from 'lucide-vue-next'
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

const open = ref(false)
const root = ref(null)

const activeCount = computed(
	() =>
		filters.value.filter((f) =>
			Array.isArray(f.value)
				? f.value.some((x) => String(x || '').trim() !== '')
				: String(f.value || '').trim() !== '',
		).length,
)

function onDocClick(e) {
	if (open.value && root.value && !root.value.contains(e.target)) {
		open.value = false
	}
}
function onKey(e) {
	if (e.key === 'Escape') {
		open.value = false
	}
}
onMounted(() => {
	document.addEventListener('click', onDocClick)
	document.addEventListener('keydown', onKey)
})
onUnmounted(() => {
	document.removeEventListener('click', onDocClick)
	document.removeEventListener('keydown', onKey)
})

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
	<div ref="root" class="filterwrap">
		<button
			type="button"
			class="btn filterbtn"
			:class="{ active: activeCount }"
			aria-label="Filter"
			@click="open = !open"
		>
			<Filter :size="14" :stroke-width="2" />
			<span>Filter</span>
			<span v-if="activeCount" class="filtercount">{{ activeCount }}</span>
		</button>
		<div v-if="open" class="popoverlay" @click="open = false" />
		<Transition name="pop">
			<div v-if="open" class="filterpanel">
				<div class="frows">
					<p v-if="!filters.length" class="frows-none">No filters</p>
					<div v-for="(f, i) in filters" :key="i" class="frow">
						<div class="frow-head">
							<select
								class="select fsel"
								:value="f.field"
								@change="onFieldChange(i, $event)"
							>
								<option v-for="(cfg, key) in meta" :key="key" :value="key">
									{{ cfg.label }}
								</option>
							</select>
							<button
								type="button"
								class="frow-x"
								title="Remove filter"
								@click="removeFilter(i)"
							>
								<X :size="13" :stroke-width="2.2" />
							</button>
						</div>
						<!-- Date: alur rentang kalender sudah mencakup from/to — operator dikunci -->
						<span
							v-if="metaFor(f.field).fieldtype === 'Date'"
							class="fhint"
							title="Pick the first date for 'from', the second for 'to' — one date alone filters from that day"
							>between</span
						>
						<select
							v-else
							class="select fsel"
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
							:from="rangeOf(f)[0] || ''"
							:to="rangeOf(f)[1] || ''"
							@update:from="onRangeChange(i, 'from', $event)"
							@update:to="onRangeChange(i, 'to', $event)"
						/>
						<select
							v-else-if="metaFor(f.field).fieldtype === 'Select'"
							class="select"
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
							class="input"
							:value="f.value || ''"
							@change="onValueChange(i, $event)"
						/>
						<input
							v-else
							type="text"
							class="input"
							:placeholder="metaFor(f.field).placeholder || ''"
							:value="f.value || ''"
							@input="onValueChange(i, $event)"
						/>
					</div>
				</div>
				<div class="frows-foot">
					<button type="button" class="linkbtn" @click="addFilter">
						<Plus :size="13" :stroke-width="2.4" />
						Add Filter
					</button>
					<button v-if="filters.length" type="button" class="linkbtn filter-clear" @click="clearAll">
						Clear All
					</button>
				</div>
			</div>
		</Transition>
	</div>
</template>

<style scoped>
.fsel { height: 30px; font-size: 12.5px; }
.fhint { font-size: 12px; color: var(--muted, inherit); }
.linkbtn { display: inline-flex; align-items: center; gap: 4px; }
</style>
