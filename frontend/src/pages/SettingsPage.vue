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
	fetchFulfillmentSettings,
	saveFulfillmentSettings,
	fetchFulfillmentOptions,
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

const ffCompany = ref('')
const ffCompanies = ref([])
const ffProfile = ref(emptyProfile())
const ffLoading = ref(false)
const ffSaving = ref(false)
const ffCanEdit = ref(false)
const ffError = ref('')
const ffLoadedCompany = ref('')
const ffItemGroups = ref([])
const ffLocked = computed(
	() =>
		!ffCanEdit.value ||
		ffLoading.value ||
		!ffCompany.value ||
		ffLoadedCompany.value !== ffCompany.value,
)
let ffLoadToken = 0

function emptyProfile() {
	return {
		name: null,
		company: '',
		enabled: 0,
		config_revision: 0,
		modified: null,
		frozen_item_group: '',
		dry_display_name: 'Dry',
		frozen_display_name: 'Frozen',
		include_child_item_groups: 1,
		dry_parent_warehouse: '',
		frozen_parent_warehouse: '',
		dry_print_format: '',
		frozen_print_format: '',
		print_paper_size: 'A4',
		dry_print_copies: 1,
		frozen_print_copies: 1,
		allow_partial_delivery: 0,
		enable_packing_slip: 1,
		short_pick_approval_required: 1,
		require_all_packed: 1,
		require_checker_approval: 1,
		allow_cross_group_packing: 0,
		allow_draft_print: 1,
		barcode_mode_enabled: 0,
		minimum_shelf_life_days: 0,
		role_order_coordinator: '',
		role_picker_dry: '',
		role_picker_frozen: '',
		role_packer: '',
		role_checker: '',
		role_dispatch: '',
	}
}

function normalizeProfile(profile, company) {
	const p = { ...emptyProfile(), ...(profile || {}), company: company || profile?.company || '' }
	if (p.short_pick_approval_required !== undefined) {
		p.short_pick_approval_required = p.short_pick_approval_required ? 1 : 0
	}
	if (p.enable_packing_slip !== undefined) {
		p.enable_packing_slip = p.enable_packing_slip ? 1 : 0
	}
	return p
}

async function loadFulfillment(company = ffCompany.value) {
	const token = ++ffLoadToken
	// Clear before the request: a failed/slow company switch must never leave the
	// previous company's profile editable or saveable.
	ffLoading.value = true
	ffError.value = ''
	ffCanEdit.value = false
	ffLoadedCompany.value = ''
	ffProfile.value = emptyProfile()
	ffItemGroups.value = []
	try {
		const [settings, options] = await Promise.all([
			fetchFulfillmentSettings(company || undefined),
			fetchFulfillmentOptions(company || undefined),
		])
		if (token !== ffLoadToken) {
			return
		}
		ffCompanies.value = settings.companies || []
		ffCompany.value = settings.company || company || ''
		ffCanEdit.value = Boolean(settings.can_edit)
		ffProfile.value = normalizeProfile(settings.profile, settings.company)
		ffItemGroups.value = options?.item_groups || []
		ffLoadedCompany.value = ffCompany.value
	} catch (e) {
		if (token !== ffLoadToken) {
			return
		}
		ffError.value = e.message
		toast.error(e.message)
	} finally {
		if (token === ffLoadToken) {
			ffLoading.value = false
		}
	}
}

function onFulfillmentCompanyChange() {
	loadFulfillment(ffCompany.value)
}

async function saveFulfillment() {
	if (ffLocked.value || ffSaving.value || !ffProfile.value.frozen_item_group) {
		return
	}
	ffSaving.value = true
	ffError.value = ''
	try {
		const { name, config_revision, modified, ...editable } = ffProfile.value
		const payload = {
			...editable,
			company: ffCompany.value,
			enabled: 1,
			include_child_item_groups: 1,
		}
		if (name && modified) {
			payload.expected_modified = modified
		}
		const result = await saveFulfillmentSettings(payload)
		ffProfile.value = normalizeProfile(result.profile, result.company)
		ffCompany.value = result.company
		ffLoadedCompany.value = result.company
		toast.success('Order Queue classification saved')
	} catch (e) {
		ffError.value = e.message
		toast.error(e.message)
	} finally {
		ffSaving.value = false
	}
}

onMounted(loadFulfillment)

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
			<p class="sub">Handover defaults and the Frozen Item Group used by the Order Queue.</p>
		</div>
	</div>

	<div class="st-panel panel">
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
			<span class="spacer" />
			<button class="btn btn-primary" :disabled="saving || loading" @click="save">
				{{ saving ? 'Saving…' : 'Save' }}
			</button>
		</div>
	</div>

	<div class="panel ff-panel">
		<div class="panel-head">
			<div class="ff-panel-title">
				<span class="lead">Order Queue classification</span>
				<span class="hint">Choose the Frozen Item Group for Dry/Frozen classification.</span>
			</div>
			<div class="ff-status">
				<span v-if="ffProfile.name" class="badge">{{ ffProfile.enabled ? 'Enabled' : 'Disabled' }}</span>
				<span v-else class="badge">New profile</span>
				<span v-if="ffProfile.name" class="ff-revision">Revision {{ ffProfile.config_revision }}</span>
				<span v-if="!ffCanEdit" class="ff-readonly-note">Read-only</span>
			</div>
		</div>
		<div class="panel-body">
			<div v-if="ffError" class="ff-error" role="alert">{{ ffError }}</div>
			<div v-if="ffLoading" class="hint">Loading classification…</div>

			<div v-if="ffCompanies.length > 1" class="ff-company">
				<label for="ff-company">Company</label>
				<select
					id="ff-company"
					v-model="ffCompany"
					class="select"
					:disabled="ffLoading"
					@change="onFulfillmentCompanyChange"
				>
					<option v-for="c in ffCompanies" :key="c.name" :value="c.name">{{ c.name }}</option>
				</select>
			</div>
			<div v-else-if="ffCompany" class="ff-company-label">
				<span>Company</span>
				<strong>{{ ffCompany }}</strong>
			</div>

			<div class="field ff-frozen-field">
				<label for="ff-frozen-group">Frozen Item Group <span class="req">*</span></label>
				<select
					id="ff-frozen-group"
					v-model="ffProfile.frozen_item_group"
					class="select"
					:disabled="ffLocked"
				>
					<option value="">Select Item Group</option>
					<option v-for="group in ffItemGroups" :key="group" :value="group">{{ group }}</option>
				</select>
				<p class="hint">
					Items in this group and its child groups are Frozen. Every other valid Item Group is Dry.
					Saving enables the profile for this Company.
				</p>
			</div>

			<div class="field ff-policy-field">
				<label class="ff-check">
					<input
						id="ff-enable-packing-slip"
						v-model="ffProfile.enable_packing_slip"
						type="checkbox"
						:true-value="1"
						:false-value="0"
						:disabled="ffLocked || !ffCanEdit"
					/>
					<span>Gunakan Tahapan Packing Slip (Koli)</span>
				</label>
				<p class="hint">
					Aktif menggunakan pembagian koli Packing Slip. Jika dinonaktifkan, alur langsung dari Pick List ke pembuatan Surat Jalan & Kirim (tanpa Packing Slip).
				</p>
			</div>

			<div class="field ff-policy-field">
				<label class="ff-check">
					<input
						id="ff-short-pick-approval"
						v-model="ffProfile.short_pick_approval_required"
						type="checkbox"
						:true-value="1"
						:false-value="0"
						:disabled="ffLocked || !ffCanEdit"
					/>
					<span>Require approval for short picks</span>
				</label>
				<p class="hint">
					Off blocks short picks. On requires an approver before Finish picking.
				</p>
			</div>
		</div>
		<div class="panel-foot">
			<span class="why">Frozen Item Group and short-pick policy are configured here.</span>
			<span class="spacer" />
			<button
				v-if="ffCanEdit"
				class="btn btn-primary"
				:disabled="ffLocked || ffSaving || !ffProfile.frozen_item_group"
				@click="saveFulfillment"
			>
				{{ ffSaving ? 'Saving…' : 'Save classification' }}
			</button>
		</div>
	</div>

</template>

<style scoped>
.page-head {
	max-width: 672px;
	margin: 0 auto 18px;
}
.st-panel,
.ff-panel {
	max-width: 672px;
	margin-left: auto;
	margin-right: auto;
	background: #fff;
	border-radius: 8px;
	box-shadow: none;
	-webkit-backdrop-filter: none;
	backdrop-filter: none;
}

.form-grid {
	display: grid;
	grid-template-columns: 1fr;
	gap: 18px;
	align-items: start;
}
.form-grid .wide { grid-column: auto; }

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
.st-panel .st-addwrap { max-width: none; }
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

.ff-panel {
	margin-top: 18px;
}
.ff-panel-title {
	display: flex;
	flex-direction: column;
	gap: 3px;
	min-width: 0;
}
.ff-panel-title .lead { font-size: 15px; font-weight: 700; }
.ff-panel-title .hint { margin: 0; }
.ff-status {
	display: flex;
	align-items: center;
	gap: 8px;
	flex-wrap: wrap;
	flex: none;
}
.ff-revision,
.ff-readonly-note {
	color: var(--muted, #64707c);
	font-size: 11px;
}
.ff-company {
	display: flex;
	align-items: center;
	gap: 10px;
	margin-bottom: 14px;
}
.ff-company label {
	flex: none;
	font-size: 13px;
	font-weight: 650;
}
.ff-company .select {
	width: auto;
	min-width: 220px;
	max-width: 100%;
}
.ff-company-label {
	display: flex;
	align-items: baseline;
	gap: 8px;
	margin-bottom: 14px;
	color: var(--muted, #64707c);
	font-size: 12px;
}
.ff-company-label strong {
	color: var(--ink, #1f2937);
	font-size: 13px;
}
.ff-frozen-field { max-width: 460px; }
.ff-frozen-field .select { width: 100%; }
.ff-policy-field {
	margin-top: 16px;
	max-width: 460px;
}
.ff-policy-field .hint {
	margin-top: 4px;
}
.ff-check {
	display: inline-flex;
	align-items: center;
	gap: 8px;
	min-height: 24px;
	font-size: 13px;
	font-weight: 600;
	color: var(--ink, #1f2937);
	cursor: pointer;
	user-select: none;
}
.ff-check input {
	margin: 0;
	accent-color: var(--brand, #3368a0);
}
.ff-check input:disabled {
	cursor: not-allowed;
}
.ff-check:has(input:disabled) {
	cursor: not-allowed;
	color: var(--muted, #64707c);
}
.ff-error {
	padding: 10px 12px;
	border: 1px solid #f0c7c0;
	border-radius: 10px;
	background: #fff6f4;
	color: #9b2c1f;
	font-size: 12px;
}
.ff-panel .panel-head {
	align-items: flex-start;
	gap: 16px;
}

@media (max-width: 820px) {
	.ff-panel { margin-top: 14px; }
	.ff-status { width: 100%; justify-content: space-between; }
	.ff-frozen-field,
	.ff-policy-field { max-width: none; }
}

@media (max-width: 820px) {
	.form-grid { grid-template-columns: 1fr; }
	.panel-body { padding: 14px; }
	.panel-foot { padding-left: 14px; padding-right: 14px; }
	.panel-foot .why { display: none; }
}

@media (max-width: 560px) {
	.st-panel,
	.ff-panel {
		margin-left: 0;
		margin-right: 0;
	}

	.ff-company {
		align-items: flex-start;
		flex-direction: column;
		gap: 4px;
	}

	.ff-company .select {
		width: 100%;
	}

	.ff-panel .panel-head {
		gap: 8px;
	}

	.ff-status {
		justify-content: flex-start;
	}

	.panel-foot .btn {
		width: 100%;
	}
}
</style>
