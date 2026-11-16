<script setup>
import { computed, ref, watch } from 'vue'
import { ChevronRight, X } from 'lucide-vue-next'
import {
	fetchManifest,
	fetchManifestCandidates,
	fetchManifests,
	saveDeliveryManifest,
} from '@/data/fulfillment'

const props = defineProps({
	open: { type: Boolean, default: false },
	company: { type: String, default: '' },
	// Tanggal & customer terisi otomatis dari Sales Order yang sedang dibuka.
	date: { type: String, default: '' },
	customer: { type: String, default: '' },
})
const emit = defineEmits(['close', 'saved'])

const deliveryDate = ref('')
const boxBigDepart = ref('')
const boxSmallDepart = ref('')
const boxBigReturn = ref('')
const boxSmallReturn = ref('')
const outlets = ref([])
const regions = ref([])
const manifestList = ref([])
const driverOnly = ref(false)
const editName = ref(null)
const loading = ref(false)
const saving = ref(false)
const error = ref('')

const isListMode = computed(() => driverOnly.value && !editName.value)
const modalTitle = computed(() => {
	if (editName.value) return driverOnly.value ? 'Isi Driver & Mobil' : 'Edit Packing List Harian'
	if (driverOnly.value) return 'Packing List Harian'
	return 'Buat Packing List Harian'
})

watch(
	() => props.open,
	(open) => {
		if (open) {
			openDialog()
		}
	},
)

function openDialog() {
	deliveryDate.value = props.date || new Date().toISOString().slice(0, 10)
	boxBigDepart.value = ''
	boxSmallDepart.value = ''
	boxBigReturn.value = ''
	boxSmallReturn.value = ''
	outlets.value = []
	regions.value = []
	manifestList.value = []
	driverOnly.value = false
	editName.value = null
	error.value = ''
	load()
}

function buildRegions(rows) {
	const seen = new Map()
	for (const o of rows) {
		const r = o.region || '-'
		if (!seen.has(r)) {
			seen.set(r, { region: r, vehicle: '', driver: '' })
		}
	}
	return [...seen.values()].sort((a, b) => a.region.localeCompare(b.region))
}

async function load() {
	loading.value = true
	error.value = ''
	try {
		const res = await fetchManifests(props.company || undefined, deliveryDate.value)
		manifestList.value = (res && res.manifests) || []
		driverOnly.value = Boolean(res && res.driver_only)
		editName.value = null
		outlets.value = []
		regions.value = []
		if (!driverOnly.value) {
			await loadCandidates()
		}
	} catch (e) {
		error.value = e.message || 'Gagal memuat data.'
	} finally {
		loading.value = false
	}
}

async function loadCandidates() {
	const rows = await fetchManifestCandidates(props.company || undefined, deliveryDate.value)
	outlets.value = (rows || []).map((o) => ({
		...o,
		checked: props.customer ? o.customer === props.customer : true,
		picker: '',
		dry_koli: 0,
		frozen_koli: 0,
	}))
	regions.value = buildRegions(outlets.value)
	if (!outlets.value.length) {
		error.value = 'Tidak ada Delivery Note untuk tanggal tersebut.'
	}
}

async function loadEdit(name) {
	editName.value = name
	loading.value = true
	error.value = ''
	try {
		const m = await fetchManifest(name)
		deliveryDate.value = m.delivery_date || deliveryDate.value
		boxBigDepart.value = m.box_big_depart || ''
		boxSmallDepart.value = m.box_small_depart || ''
		boxBigReturn.value = m.box_big_return || ''
		boxSmallReturn.value = m.box_small_return || ''
		regions.value = (m.regions || []).map((r) => ({
			region: r.region,
			vehicle: r.vehicle || '',
			driver: r.driver || '',
		}))
		outlets.value = (m.outlets || []).map((o) => ({ ...o }))
	} catch (e) {
		error.value = e.message || 'Gagal memuat manifest.'
	} finally {
		loading.value = false
	}
}

function backToList() {
	editName.value = null
	outlets.value = []
	regions.value = []
	error.value = ''
}

function rowsForRegion(regionName) {
	return outlets.value.filter((o) => (o.region || '-') === regionName)
}

async function submit() {
	if (driverOnly.value && !editName.value) return

	let payloadOutlets = []
	if (!driverOnly.value) {
		if (editName.value) {
			payloadOutlets = outlets.value.map((o) => ({
				customer: o.customer,
				delivery_note: o.delivery_note,
				region: o.region || '-',
				picker: o.picker || '',
				dry_koli: Number(o.dry_koli) || 0,
				frozen_koli: Number(o.frozen_koli) || 0,
			}))
		} else {
			const checked = outlets.value.filter((o) => o.checked)
			for (const o of checked) {
				for (const dn of o.delivery_notes || []) {
					payloadOutlets.push({
						customer: o.customer,
						delivery_note: dn.name,
						region: o.region || '-',
						picker: o.picker || '',
						dry_koli: Number(o.dry_koli) || 0,
						frozen_koli: Number(o.frozen_koli) || 0,
					})
				}
			}
			if (!payloadOutlets.length) {
				error.value = 'Pilih minimal satu outlet / Delivery Note.'
				return
			}
		}
	}

	const payloadRegions = regions.value.map((r) => ({
		region: r.region,
		vehicle: r.vehicle || '',
		driver: r.driver || '',
	}))

	saving.value = true
	error.value = ''
	try {
		const res = await saveDeliveryManifest({
			name: editName.value || undefined,
			company: props.company || undefined,
			delivery_date: deliveryDate.value,
			box_big_depart: Number(boxBigDepart.value) || 0,
			box_small_depart: Number(boxSmallDepart.value) || 0,
			box_big_return: Number(boxBigReturn.value) || 0,
			box_small_return: Number(boxSmallReturn.value) || 0,
			regions: payloadRegions,
			outlets: payloadOutlets,
		})
		emit('saved', res.name)
	} catch (e) {
		error.value = e.message || 'Gagal menyimpan Delivery Manifest.'
	} finally {
		saving.value = false
	}
}
</script>

<template>
	<Teleport to="body">
		<div v-if="open" class="dm-overlay" @click.self="emit('close')">
			<div class="dm-modal" role="dialog" aria-modal="true" :aria-label="modalTitle">
				<div class="dm-modal-head">
					<h2>{{ modalTitle }}</h2>
					<button type="button" class="dm-close" aria-label="Tutup" @click="emit('close')">
						<X :size="16" :stroke-width="2" />
					</button>
				</div>

				<div class="dm-modal-body">
					<div class="dm-field-grid">
						<label class="dm-field">
							<span>Tanggal Kirim</span>
							<input v-model="deliveryDate" class="input input-sm" type="date" :disabled="!!editName" />
						</label>
						<button
							v-if="!editName"
							type="button"
							class="btn btn-sm dm-reload"
							:disabled="loading"
							@click="load"
						>
							{{ loading ? 'Memuat...' : 'Muat' }}
						</button>
						<span v-else class="dm-editing-hint">Mode edit manifest</span>
					</div>

					<!-- Daftar manifest (Stock User saja) -->
					<template v-if="isListMode">
						<div v-if="loading" class="dm-list-empty">Memuat manifest…</div>
						<div v-else-if="manifestList.length" class="dm-manifest-list">
							<button
								v-for="m in manifestList"
								:key="m.name"
								type="button"
								class="dm-manifest-item"
								@click="loadEdit(m.name)"
							>
								<span class="dm-manifest-main">
									<span class="dm-manifest-name mono">{{ m.name }}</span>
									<span class="dm-manifest-count">{{ m.outlet_count }} outlet</span>
								</span>
								<ChevronRight :size="15" :stroke-width="2" />
							</button>
						</div>
						<p v-else class="dm-list-empty">Tidak ada manifest untuk tanggal ini.</p>
					</template>

					<!-- Form create / edit -->
					<template v-else>
						<div v-if="!driverOnly" class="dm-box-group">
							<span class="dm-box-title">Box Abu</span>
							<div class="dm-box-grid">
								<span class="dm-box-head"></span>
								<span class="dm-box-head">Berangkat</span>
								<span class="dm-box-head">Pulang</span>
								<span class="dm-box-row">B (Besar)</span>
								<input v-model.number="boxBigDepart" class="input input-sm" type="number" min="0" aria-label="Box besar berangkat" />
								<input v-model.number="boxBigReturn" class="input input-sm" type="number" min="0" aria-label="Box besar pulang" />
								<span class="dm-box-row">K (Kecil)</span>
								<input v-model.number="boxSmallDepart" class="input input-sm" type="number" min="0" aria-label="Box kecil berangkat" />
								<input v-model.number="boxSmallReturn" class="input input-sm" type="number" min="0" aria-label="Box kecil pulang" />
							</div>
						</div>

						<div v-if="regions.length" class="dm-regions">
							<div v-for="region in regions" :key="region.region" class="dm-region">
								<div class="dm-region-head">
									<span class="dm-region-name">{{ region.region }}</span>
								</div>
								<div class="dm-region-meta">
									<label class="dm-field">
										<span>Mobil</span>
										<input v-model="region.vehicle" class="input input-sm" type="text" />
									</label>
									<label class="dm-field">
										<span>Driver</span>
										<input v-model="region.driver" class="input input-sm" type="text" />
									</label>
								</div>
								<div class="dm-outlets">
									<div v-for="o in rowsForRegion(region.region)" :key="o.customer" class="dm-outlet-row">
										<label v-if="!editName" class="dm-check">
											<input v-model="o.checked" type="checkbox" />
											<span>{{ o.customer_name || o.customer }}</span>
											<small>{{ (o.delivery_notes || []).map((d) => d.name).join(', ') }}</small>
										</label>
										<span v-else class="dm-check dm-check-static">
											<span>{{ o.customer_name || o.customer }}</span>
											<small class="mono">{{ o.delivery_note }}</small>
										</span>
										<div class="dm-outlet-meta">
											<label>
												<span>Picker</span>
												<input v-model="o.picker" class="input input-sm" type="text" :disabled="driverOnly" />
											</label>
											<label>
												<span>Koli Dry</span>
												<input v-model.number="o.dry_koli" class="input input-sm" type="number" min="0" :disabled="driverOnly" />
											</label>
											<label>
												<span>Koli Frozen</span>
												<input v-model.number="o.frozen_koli" class="input input-sm" type="number" min="0" :disabled="driverOnly" />
											</label>
										</div>
									</div>
								</div>
							</div>
						</div>
						<p v-else-if="!loading" class="dm-empty">Tidak ada wilayah untuk tanggal ini.</p>
					</template>

					<p v-if="error" class="dm-error" role="alert">{{ error }}</p>
				</div>

				<div class="dm-modal-foot">
					<button
						type="button"
						class="btn"
						@click="editName ? backToList() : emit('close')"
					>
						{{ editName ? 'Kembali' : 'Batal' }}
					</button>
					<button
						v-if="!isListMode"
						type="button"
						class="btn btn-primary"
						:disabled="saving || !regions.length"
						@click="submit"
					>
						{{ saving ? 'Menyimpan...' : driverOnly ? 'Simpan Driver & Mobil' : 'Simpan & Cetak' }}
					</button>
				</div>
			</div>
		</div>
	</Teleport>
</template>

<style scoped>
.dm-overlay {
	position: fixed;
	inset: 0;
	z-index: 999;
	background: rgba(15, 23, 42, 0.45);
	display: flex;
	align-items: flex-start;
	justify-content: center;
	padding: 60px 20px 20px;
}
.dm-modal {
	width: 100%;
	max-width: 640px;
	background: #ffffff;
	border-radius: 12px;
	box-shadow: 0 24px 60px rgba(15, 23, 42, 0.35);
	overflow: hidden;
	display: flex;
	flex-direction: column;
}
.dm-modal-head {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 16px 20px;
	border-bottom: 1px solid var(--line, #e5e7eb);
}
.dm-modal-head h2 {
	margin: 0;
	font-size: 16px;
	color: var(--ink, #1e293b);
}
.dm-close {
	background: none;
	border: none;
	color: var(--muted, #64748b);
	cursor: pointer;
	padding: 4px;
	display: grid;
	place-items: center;
}
.dm-modal-body {
	padding: 18px 20px;
	display: flex;
	flex-direction: column;
	gap: 14px;
}
.dm-field-grid {
	display: grid;
	grid-template-columns: 1fr 1fr;
	gap: 12px;
	align-items: end;
}
.dm-field {
	display: flex;
	flex-direction: column;
	gap: 5px;
}
.dm-field span {
	font-size: 12px;
	font-weight: 600;
	color: var(--muted, #64748b);
}
.dm-field .input {
	width: 100%;
}
.dm-reload {
	grid-column: 2;
}
.dm-editing-hint {
	grid-column: 2;
	align-self: center;
	font-size: 12px;
	color: var(--muted, #64748b);
}
.dm-box-group {
	border: 1px solid var(--line, #e5e7eb);
	border-radius: 8px;
	padding: 10px 12px 12px;
}
.dm-box-title {
	display: block;
	font-size: 12px;
	font-weight: 600;
	color: var(--muted, #64748b);
	margin-bottom: 8px;
}
.dm-box-grid {
	display: grid;
	grid-template-columns: 90px 1fr 1fr;
	gap: 8px;
	align-items: center;
}
.dm-box-head {
	font-size: 11px;
	font-weight: 600;
	color: var(--muted, #64748b);
	text-align: center;
}
.dm-box-row {
	font-size: 12.5px;
	font-weight: 600;
	color: var(--ink, #1e293b);
}
.dm-regions {
	display: flex;
	flex-direction: column;
	gap: 14px;
	max-height: 360px;
	overflow-y: auto;
}
.dm-region {
	border: 1px solid var(--line, #e5e7eb);
	border-radius: 8px;
	padding: 10px 12px;
	overflow-y: auto;
}
.dm-region-head {
	display: flex;
	align-items: center;
	margin-bottom: 8px;
}
.dm-region-name {
	font-size: 13px;
	font-weight: 700;
	letter-spacing: 0.04em;
	text-transform: uppercase;
	color: var(--ink, #1e293b);
}
.dm-region-meta {
	display: grid;
	grid-template-columns: 1fr 1fr;
	gap: 12px;
	margin-bottom: 10px;
}
.dm-outlets {
	display: flex;
	flex-direction: column;
	gap: 6px;
}
.dm-outlet-row {
	border-bottom: 1px solid var(--line, #f1f5f9);
	padding-bottom: 6px;
}
.dm-outlet-row:last-child {
	border-bottom: none;
	padding-bottom: 0;
}
.dm-check {
	display: flex;
	align-items: center;
	gap: 8px;
	cursor: pointer;
	font-size: 13px;
}
.dm-check-static {
	cursor: default;
}
.dm-check span {
	font-weight: 600;
	color: var(--ink, #1e293b);
}
.dm-check small {
	font-size: 11px;
	color: var(--muted, #64748b);
}
.dm-outlet-meta {
	display: grid;
	grid-template-columns: 1fr 1fr 1fr;
	gap: 8px;
	margin-top: 6px;
	padding-left: 22px;
}
.dm-outlet-meta label {
	display: flex;
	flex-direction: column;
	gap: 3px;
	font-size: 11px;
	font-weight: 600;
	color: var(--muted, #64748b);
}
.dm-manifest-list {
	display: flex;
	flex-direction: column;
	gap: 8px;
	max-height: 320px;
	overflow-y: auto;
}
.dm-manifest-item {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 12px;
	width: 100%;
	padding: 12px 14px;
	border: 1px solid var(--line, #e5e7eb);
	border-radius: 8px;
	background: #ffffff;
	text-align: left;
	cursor: pointer;
	font: inherit;
	transition: background 0.14s ease, border-color 0.14s ease;
}
.dm-manifest-item:hover {
	background: var(--brand-softer, #eff5f9);
	border-color: var(--brand-light, #66a3bf);
}
.dm-manifest-main {
	display: flex;
	flex-direction: column;
	gap: 2px;
}
.dm-manifest-name {
	font-size: 13.5px;
	font-weight: 700;
	color: var(--ink, #1e293b);
}
.dm-manifest-count {
	font-size: 12px;
	color: var(--muted, #64748b);
}
.dm-list-empty,
.dm-empty {
	margin: 0;
	font-size: 12.5px;
	color: var(--muted, #64748b);
}
.dm-error {
	margin: 0;
	font-size: 12.5px;
	color: #dc2626;
}
.dm-modal-foot {
	display: flex;
	justify-content: flex-end;
	gap: 8px;
	padding: 14px 20px;
	border-top: 1px solid var(--line, #e5e7eb);
}
</style>