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
	fetchFulfillmentOptions,
	saveFulfillmentSettings,
	searchLink,
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
const ffOptions = ref({ warehouses: [], roles: [], print_formats: [] })
const ffLoading = ref(false)
const ffSaving = ref(false)
const ffCanEdit = ref(false)
const ffError = ref('')
const ffLoadedCompany = ref('')
const ffItemGroupQuery = ref('')
const ffItemGroupOptions = ref([])
const ffPaperSizes = ['A4', 'A5', 'Letter', 'Thermal 80mm']
const ffShowAdvanced = ref(false)
const ffLocked = computed(
	() =>
		!ffCanEdit.value ||
		ffLoading.value ||
		!ffCompany.value ||
		ffLoadedCompany.value !== ffCompany.value,
)
let ffItemGroupTimer = null
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
	return { ...emptyProfile(), ...(profile || {}), company: company || profile?.company || '' }
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
	ffOptions.value = { warehouses: [], roles: [], print_formats: [] }
	ffItemGroupQuery.value = ''
	ffItemGroupOptions.value = []
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
		ffOptions.value = {
			warehouses: options?.warehouses || [],
			roles: options?.roles || [],
			print_formats: options?.print_formats || [],
		}
		ffItemGroupQuery.value = ffProfile.value.frozen_item_group || ''
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
	if (ffLocked.value || ffSaving.value) {
		return
	}
	ffSaving.value = true
	ffError.value = ''
	try {
		const { name, config_revision, modified, ...editable } = ffProfile.value
		const payload = { ...editable, company: ffCompany.value }
		if (name && modified) {
			payload.expected_modified = modified
		}
		const result = await saveFulfillmentSettings(payload)
		ffProfile.value = normalizeProfile(result.profile, result.company)
		ffCompany.value = result.company
		ffLoadedCompany.value = result.company
		ffItemGroupQuery.value = ffProfile.value.frozen_item_group || ''
		toast.success('Fulfillment settings saved')
	} catch (e) {
		ffError.value = e.message
		toast.error(e.message)
	} finally {
		ffSaving.value = false
	}
}

function onItemGroupInput(event) {
	clearTimeout(ffItemGroupTimer)
	const q = String(event?.target?.value || '').trim()
	ffItemGroupQuery.value = q
	if (q !== ffProfile.value.frozen_item_group) {
		ffProfile.value.frozen_item_group = ''
	}
	if (!q) {
		ffItemGroupOptions.value = []
		return
	}
	ffItemGroupTimer = setTimeout(async () => {
		try {
			ffItemGroupOptions.value = await searchLink('Item Group', q)
		} catch {
			ffItemGroupOptions.value = []
		}
	}, 250)
}

function pickItemGroup(option) {
	ffProfile.value.frozen_item_group = option.value
	ffItemGroupQuery.value = option.value
	ffItemGroupOptions.value = []
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
			<p class="sub">Handover defaults and the per-Company fulfillment profile used by the warehouse workspace.</p>
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

	<div class="panel ff-panel">
		<div class="panel-head">
			<div class="ff-panel-title">
				<span class="lead">Fulfillment settings</span>
				<span class="hint">Only the Frozen Item Group is required. Warehouses, printing, policies, and roles are optional.</span>
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
			<div v-if="ffLoading" class="hint">Loading fulfillment profile…</div>

			<div class="ff-section">
				<div class="ff-section-head">
					<h2>Company</h2>
					<span class="hint">One profile per Company; changes apply to new Runs only.</span>
				</div>
				<div class="form-grid ff-grid">
					<div class="field">
						<label for="ff-company">Company</label>
						<select
							id="ff-company"
							v-model="ffCompany"
							class="select"
							:disabled="ffLoading || ffCompanies.length < 2"
							@change="onFulfillmentCompanyChange"
						>
							<option v-for="c in ffCompanies" :key="c.name" :value="c.name">{{ c.name }}</option>
						</select>
					</div>
					<div class="field">
						<label for="ff-enabled">Status</label>
						<label class="ff-check">
							<input id="ff-enabled" v-model="ffProfile.enabled" type="checkbox" :true-value="1" :false-value="0" :disabled="ffLocked" />
							<span>Profile enabled</span>
						</label>
						<p class="hint">Disable to block new Fulfillment Runs without changing history.</p>
					</div>
				</div>
			</div>

			<div class="ff-section">
				<div class="ff-section-head"><h2>Classification</h2></div>
				<div class="form-grid ff-grid">
					<div class="field wide">
						<label for="ff-frozen-group">Frozen Item Group <span class="req">*</span></label>
						<div class="st-addwrap ff-linkwrap">
							<input
								id="ff-frozen-group"
								v-model="ffItemGroupQuery"
								class="input"
								type="text"
								placeholder="Search Item Group…"
								:disabled="ffLocked"
								autocomplete="off"
								@input="onItemGroupInput"
							/>
							<ul v-if="ffItemGroupOptions.length" class="st-opts" role="listbox">
								<li v-for="option in ffItemGroupOptions" :key="option.value">
									<button type="button" role="option" :aria-selected="false" @mousedown.prevent="pickItemGroup(option)">
										{{ option.label }}
									</button>
								</li>
							</ul>
						</div>
						<p class="hint">A parent group with children requires “Include child groups”.</p>
					</div>
					<div class="field">
						<label>Child groups</label>
						<label class="ff-check">
							<input v-model="ffProfile.include_child_item_groups" type="checkbox" :true-value="1" :false-value="0" :disabled="ffLocked" />
							<span>Include child Item Groups</span>
						</label>
					</div>
					<div class="field">
						<label for="ff-dry-name">Dry display name</label>
						<input id="ff-dry-name" v-model="ffProfile.dry_display_name" class="input" :disabled="ffLocked" />
					</div>
					<div class="field">
						<label for="ff-frozen-name">Frozen display name</label>
						<input id="ff-frozen-name" v-model="ffProfile.frozen_display_name" class="input" :disabled="ffLocked" />
					</div>
				</div>
			</div>

			<div class="ff-advanced-toggle">
				<div>
					<strong>Advanced settings</strong>
					<p class="hint">Warehouse scope, printing, policies, and roles. Optional for F2; defaults are safe.</p>
				</div>
				<button
					type="button"
					class="btn btn-sm"
					aria-controls="ff-advanced"
					:aria-expanded="ffShowAdvanced"
					@click="ffShowAdvanced = !ffShowAdvanced"
				>
					{{ ffShowAdvanced ? 'Hide advanced' : 'Show advanced' }}
				</button>
			</div>

			<div v-if="ffShowAdvanced" id="ff-advanced">
			<div class="ff-section">
				<div class="ff-section-head">
					<h2>Warehouses</h2>
					<span class="hint">Optional scope for picking locations; used from F3.</span>
				</div>
				<div class="form-grid ff-grid">
					<div class="field">
						<label for="ff-dry-warehouse">Dry parent warehouse</label>
						<select id="ff-dry-warehouse" v-model="ffProfile.dry_parent_warehouse" class="select" :disabled="ffLocked">
							<option value="">—</option>
							<option v-for="w in ffOptions.warehouses" :key="w.name" :value="w.name">
								{{ w.name }}{{ w.is_group ? ' (group)' : '' }}
							</option>
						</select>
					</div>
					<div class="field">
						<label for="ff-frozen-warehouse">Frozen parent warehouse</label>
						<select id="ff-frozen-warehouse" v-model="ffProfile.frozen_parent_warehouse" class="select" :disabled="ffLocked">
							<option value="">—</option>
							<option v-for="w in ffOptions.warehouses" :key="w.name" :value="w.name">
								{{ w.name }}{{ w.is_group ? ' (group)' : '' }}
							</option>
						</select>
					</div>
				</div>
			</div>

			<div class="ff-section">
				<div class="ff-section-head">
					<h2>Print</h2>
					<span class="hint">Used from F5.</span>
				</div>
				<div class="form-grid ff-grid">
					<div class="field">
						<label for="ff-dry-format">Dry print format</label>
						<select id="ff-dry-format" v-model="ffProfile.dry_print_format" class="select" :disabled="ffLocked">
							<option value="">—</option>
							<option v-for="format in ffOptions.print_formats" :key="format.name" :value="format.name">{{ format.name }}</option>
						</select>
					</div>
					<div class="field">
						<label for="ff-frozen-format">Frozen print format</label>
						<select id="ff-frozen-format" v-model="ffProfile.frozen_print_format" class="select" :disabled="ffLocked">
							<option value="">—</option>
							<option v-for="format in ffOptions.print_formats" :key="format.name" :value="format.name">{{ format.name }}</option>
						</select>
					</div>
					<div class="field">
						<label for="ff-paper">Paper size</label>
						<select id="ff-paper" v-model="ffProfile.print_paper_size" class="select" :disabled="ffLocked">
							<option v-for="size in ffPaperSizes" :key="size" :value="size">{{ size }}</option>
						</select>
					</div>
					<div class="field">
						<label for="ff-dry-copies">Dry copies</label>
						<input id="ff-dry-copies" v-model.number="ffProfile.dry_print_copies" class="input" type="number" min="1" :disabled="ffLocked" />
					</div>
					<div class="field">
						<label for="ff-frozen-copies">Frozen copies</label>
						<input id="ff-frozen-copies" v-model.number="ffProfile.frozen_print_copies" class="input" type="number" min="1" :disabled="ffLocked" />
					</div>
					<div class="field">
						<label class="ff-check">
							<input v-model="ffProfile.allow_draft_print" type="checkbox" :true-value="1" :false-value="0" :disabled="ffLocked" />
							<span>Allow draft print</span>
						</label>
					</div>
				</div>
			</div>

			<div class="ff-section">
				<div class="ff-section-head">
					<h2>Policies</h2>
					<span class="hint">Snapshotted on every Run.</span>
				</div>
				<div class="ff-checks">
					<label class="ff-check"><input v-model="ffProfile.allow_partial_delivery" type="checkbox" :true-value="1" :false-value="0" :disabled="ffLocked" /><span>Allow partial delivery</span></label>
					<label class="ff-check"><input v-model="ffProfile.short_pick_approval_required" type="checkbox" :true-value="1" :false-value="0" :disabled="ffLocked" /><span>Short-pick approval required</span></label>
					<label class="ff-check"><input v-model="ffProfile.require_all_packed" type="checkbox" :true-value="1" :false-value="0" :disabled="ffLocked" /><span>Require all packed</span></label>
					<label class="ff-check"><input v-model="ffProfile.require_checker_approval" type="checkbox" :true-value="1" :false-value="0" :disabled="ffLocked" /><span>Require checker approval</span></label>
					<label class="ff-check"><input v-model="ffProfile.allow_cross_group_packing" type="checkbox" :true-value="1" :false-value="0" :disabled="ffLocked" /><span>Allow cross-group packing</span></label>
					<label class="ff-check"><input v-model="ffProfile.barcode_mode_enabled" type="checkbox" :true-value="1" :false-value="0" :disabled="ffLocked" /><span>Barcode mode enabled</span></label>
					<div class="field ff-shelf">
						<label for="ff-shelf-life">Minimum shelf life (days)</label>
						<input id="ff-shelf-life" v-model.number="ffProfile.minimum_shelf_life_days" class="input" type="number" min="0" :disabled="ffLocked" />
					</div>
				</div>
			</div>

			<div class="ff-section">
				<div class="ff-section-head">
					<h2>Roles</h2>
					<span class="hint">Stored for the later role matrix.</span>
				</div>
				<div class="form-grid ff-grid">
					<div v-for="roleField in [
						['role_order_coordinator', 'Order coordinator'],
						['role_picker_dry', 'Dry picker'],
						['role_picker_frozen', 'Frozen picker'],
						['role_packer', 'Packer'],
						['role_checker', 'Checker'],
						['role_dispatch', 'Dispatch'],
					]" :key="roleField[0]" class="field">
						<label :for="`ff-${roleField[0]}`">{{ roleField[1] }}</label>
						<select :id="`ff-${roleField[0]}`" v-model="ffProfile[roleField[0]]" class="select" :disabled="ffLocked">
							<option value="">—</option>
							<option v-for="role in ffOptions.roles" :key="role.name" :value="role.name">{{ role.name }}</option>
						</select>
					</div>
				</div>
			</div>
			</div>
		</div>
		<div class="panel-foot">
			<span class="why">Save profile changes separately from handover defaults. Changes apply to new Runs only.</span>
			<span class="spacer" />
			<button class="btn btn-primary" :disabled="ffLocked || ffSaving" @click="saveFulfillment">
				{{ ffSaving ? 'Saving…' : 'Save fulfillment' }}
			</button>
		</div>
	</div>
</template>

<style scoped>
.st-panel { max-width: 980px; }

.form-grid {
	display: grid;
	grid-template-columns: repeat(2, minmax(0, 1fr));
	gap: 14px 18px;
	align-items: start;
}
.form-grid .wide { grid-column: 1 / -1; }

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

.ff-panel {
	max-width: 980px;
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
.ff-section {
	display: flex;
	flex-direction: column;
	gap: 10px;
	padding: 16px 0;
	border-top: 1px solid var(--line, #e5e5e0);
}
.ff-section:first-of-type { padding-top: 0; border-top: 0; }
.ff-advanced-toggle {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 12px;
	padding: 14px 0;
	border-top: 1px solid var(--line, #e5e5e0);
}
.ff-advanced-toggle strong { font-size: 13px; font-weight: 750; }
.ff-advanced-toggle .hint { margin: 2px 0 0; }
.ff-advanced-toggle .btn { flex: none; }
.ff-section-head {
	display: flex;
	align-items: baseline;
	justify-content: space-between;
	gap: 4px 12px;
	flex-wrap: wrap;
}
.ff-section-head h2 {
	margin: 0;
	font-size: 13px;
	font-weight: 750;
}
.ff-section-head .hint { margin: 0; flex: 1 1 240px; text-align: right; }
.ff-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.ff-grid .wide { grid-column: 1 / -1; }
.ff-check {
	display: flex;
	align-items: center;
	gap: 8px;
	min-height: 30px;
	font-size: 13px;
	color: var(--ink, #1f2937);
	cursor: pointer;
}
.ff-check input { accent-color: var(--brand, #2f6f8f); }
.ff-checks {
	display: grid;
	grid-template-columns: repeat(2, minmax(0, 1fr));
	gap: 6px 18px;
}
.ff-shelf {
	grid-column: 1 / -1;
	max-width: 260px;
}
.ff-linkwrap {
	max-width: none;
	margin-top: 0;
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
	.ff-section-head { align-items: flex-start; flex-direction: column; gap: 3px; }
	.ff-section-head .hint { flex: 0 1 auto; text-align: left; }
	.ff-grid,
	.ff-checks { grid-template-columns: 1fr; }
	.ff-shelf { grid-column: auto; max-width: none; }
	.ff-status { width: 100%; justify-content: space-between; }
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

	.ff-advanced-toggle {
		align-items: flex-start;
		flex-direction: column;
	}

	.ff-advanced-toggle .btn {
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

	.ff-checks {
		gap: 2px;
	}
}
</style>
