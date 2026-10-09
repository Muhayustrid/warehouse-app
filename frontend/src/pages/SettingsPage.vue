<script setup>
// Settings gudang (SPA) — redesign bahasa visual production_workspace:
// .page-head + .panel kaca (.panel-head/.panel-body/.panel-foot) + .form-grid +
// .field + chip native. Logic & data contract tetap dari data/settings.js.
import { ref, computed, onMounted } from 'vue'
import { X } from 'lucide-vue-next'
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
const pickedItem = ref('')
const input = ref(null) // template ref: kolom Add an item

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

// autocomplete add: query diketik → server-side search; dipilih → fetch nama
// lalu masuk chip (dedup + warning bila sudah ada)
let pickTimer = null
function onItemInput(e) {
	clearTimeout(pickTimer)
	const q = String(e?.target?.value || '').trim()
	pickedItem.value = q
	if (!q) {
		itemOptions.value = []
		return
	}
	pickTimer = setTimeout(async () => {
		try {
			itemOptions.value = await searchItems(q)
		} catch {
			itemOptions.value = []
		}
	}, 250)
}

async function onItemPick(option) {
	const code = option && option.value
	if (!code) {
		return
	}
	input.value = ''
	pickedItem.value = ''
	itemOptions.value = []
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
	<div class="page-head">
		<div class="ph-left">
			<h1>Settings</h1>
			<p class="sub">Warehouses used when the warehouse team creates handover requests.</p>
		</div>
	</div>

	<div class="st-panel panel">
		<div class="panel-head">
			<span class="lead">Handover defaults</span>
		</div>
		<div class="panel-body">
			<div class="form-grid">
				<div class="field">
					<label for="st-source">Source Warehouse</label>
					<select id="st-source" v-model="source" class="select" :disabled="loading">
						<option v-for="o in warehouseSelectOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
					</select>
					<p class="hint">
						Where the goods come from. Leave empty to follow the production lot warehouse
						automatically.
					</p>
				</div>
				<div class="field">
					<label for="st-target">Target Warehouse <span class="req">*</span></label>
					<select id="st-target" v-model="target" class="select" :disabled="loading">
						<option v-for="o in warehouseSelectOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
					</select>
					<p class="hint">Where handover requests deliver the goods. Required to create a request.</p>
				</div>

				<div class="field wide">
					<label>Group Request Items</label>
					<p class="hint" style="margin-top: 0">
						Items eligible for group requests — several Work Orders of one item can be
						requested together.
					</p>
					<div v-if="groupItems.length" class="st-chips">
						<span v-for="(it, i) in groupItems" :key="it.code" class="chip st-chip">
							<span class="st-chiptext">
								<span class="st-chipname">{{ it.name }}</span>
								<small class="st-chipcode">{{ it.code }}</small>
							</span>
							<button type="button" class="st-chipx" title="Remove" :aria-label="`Remove ${it.name}`" @click="removeItem(i)">
								<X :size="13" :stroke-width="2" />
							</button>
						</span>
					</div>
					<p v-else class="hint">No items configured</p>

					<div class="st-addwrap">
						<input
							ref="input"
							class="input"
							type="text"
							placeholder="Add an item..."
							:disabled="loading"
							aria-label="Add an item"
							autocomplete="off"
							@input="onItemInput"
							@change="onItemInput"
						/>
						<ul v-if="pickedItem && itemOptions.length" class="st-opts" role="listbox">
							<li v-for="o in itemOptions" :key="o.value">
								<button type="button" role="option" :aria-selected="false" @mousedown.prevent="onItemPick(o)">
									{{ o.label }}
								</button>
							</li>
						</ul>
					</div>
				</div>
			</div>
		</div>
		<div class="panel-foot">
			<span class="why">Saved together — warehouses and group items go in one pass.</span>
			<span class="spacer" />
			<button class="btn btn-primary" :disabled="saving || loading" @click="save">
				{{ saving ? 'Saving…' : 'Save' }}
			</button>
		</div>
	</div>
</template>

<style scoped>
.st-panel { max-width: 760px; }

.st-chips {
	display: flex;
	flex-wrap: wrap;
	gap: 8px;
	margin: 8px 0 10px;
}
.st-chip { gap: 8px; padding: 4px 6px 4px 10px; }
.st-chiptext { display: flex; flex-direction: column; line-height: 1.2; }
.st-chipname { font-size: 12.5px; font-weight: 600; color: var(--ink, #1f2937); }
.st-chipcode { font-size: 10.5px; color: var(--faint, #98978f); }
.st-chipx {
	display: grid;
	place-items: center;
	width: 22px;
	height: 22px;
	border: 0;
	border-radius: 50%;
	background: none;
	color: var(--faint, #98978f);
	cursor: pointer;
}
.st-chipx:hover { background: var(--grey-bg, #f1f1ec); color: var(--ink, #1f2937); }

/* autocomplete add: wrapper relatif agar dropdown menempel di bawah input */
.st-addwrap { position: relative; max-width: 420px; margin-top: 6px; }
.st-opts {
	position: absolute;
	z-index: 20;
	top: calc(100% + 4px);
	left: 0;
	right: 0;
	margin: 0;
	padding: 4px;
	list-style: none;
	border: 1px solid var(--line, #e5e5e0);
	border-radius: 10px;
	background: #fff;
	box-shadow: 0 12px 32px -12px rgba(36, 48, 58, 0.25);
	max-height: 240px;
	overflow-y: auto;
}
.st-opts button {
	display: block;
	width: 100%;
	padding: 7px 10px;
	border: 0;
	border-radius: 7px;
	background: none;
	font: inherit;
	font-size: 13px;
	color: var(--ink, #1f2937);
	text-align: left;
	cursor: pointer;
}
.st-opts button:hover { background: var(--grey-bg, #f1f1ec); }

@media (max-width: 820px) {
	.form-grid { grid-template-columns: 1fr; }
	.panel-body { padding: 14px; }
	.panel-foot { padding-left: 14px; padding-right: 14px; }
	.panel-foot .why { display: none; }
}
</style>
