<script setup>
// Field rentang tanggal (W33-r6) dengan alur klik berurutan ala permintaan
// user: field kosong → klik → kalender → tanggal pertama = "from" (kalender
// tetap terbuka, field ikut terisi) → tanggal kedua = "to" (kalender tutup).
// Hanya from → tetap jadi filter (server mengubah between satu-sisi jadi >=).
// Nilai internal ISO YYYY-MM-DD; tampilan DD-MM-YYYY.
// Bahasa visual production_workspace: popup manual ala .filterpanel.
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { Calendar } from 'lucide-vue-next'
import dayjs from 'dayjs'
import { months, monthStart, generateWeeks } from '@/lib/calendar'

const props = defineProps({
	from: { type: String, default: '' },
	to: { type: String, default: '' },
	placeholder: { type: String, default: 'Select date' },
})
const emit = defineEmits(['update:from', 'update:to'])

const open = ref(false)
const root = ref(null)
const view = ref('date')
const year = ref(dayjs().year())
const month = ref(dayjs().month())

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

const fmt = (iso) => {
	const d = dayjs(iso)
	return d.isValid() ? d.format('DD-MM-YYYY') : iso
}
const display = computed(() => {
	if (props.from && props.to) {
		return `${fmt(props.from)} to ${fmt(props.to)}`
	}
	if (props.from) {
		return fmt(props.from)
	}
	return ''
})

const weeks = computed(() => {
	const f = props.from ? dayjs(props.from) : null
	const t = props.to ? dayjs(props.to) : null
	return generateWeeks(year.value, month.value, '').map((week) =>
		week.map((d) => ({
			...d,
			isFrom: !!f && d.date.isSame(f, 'day'),
			isTo: !!t && d.date.isSame(t, 'day'),
			inRange:
				!!f && !!t && d.date.isAfter(f, 'day') && d.date.isBefore(t, 'day'),
		})),
	)
})

const monthLabel = computed(() => `${months[month.value]} ${year.value}`)

function prev() {
	const m = monthStart(year.value, month.value).subtract(1, 'month')
	year.value = m.year()
	month.value = m.month()
}
function next() {
	const m = monthStart(year.value, month.value).add(1, 'month')
	year.value = m.year()
	month.value = m.month()
}
function goToday() {
	const now = dayjs()
	year.value = now.year()
	month.value = now.month()
}

function pick(date) {
	const iso = date.format('YYYY-MM-DD')
	if (props.from && props.to) {
		// sudah lengkap → mulai rentang baru
		emit('update:from', iso)
		emit('update:to', '')
	} else if (props.from && !props.to) {
		let f = props.from
		let t = iso
		if (dayjs(t).isBefore(dayjs(f))) {
			;[f, t] = [t, f]
		}
		emit('update:from', f)
		emit('update:to', t)
		open.value = false // kedua tanggal terisi → tutup kalender
	} else {
		// tanggal pertama = from; kalender tetap terbuka untuk to
		emit('update:from', iso)
	}
}

function clear() {
	emit('update:from', '')
	emit('update:to', '')
	open.value = false
}
</script>

<template>
	<div ref="root" class="filterwrap drangefield">
		<button
			type="button"
			class="input drange-btn"
			:title="display || placeholder"
			@click="open = !open"
		>
			<span class="drange-label" :class="{ 'rp-ph': !display }">{{ display || placeholder }}</span>
			<Calendar :size="14" :stroke-width="2" class="drange-ico" />
		</button>
		<div v-if="open" class="popoverlay" @click="open = false" />
		<Transition name="pop">
			<div v-if="open" class="filterpanel dcal">
				<div class="dcal-head">
					<button type="button" class="linkbtn dcal-title" @click="view = view === 'date' ? 'month' : 'date'">
						{{ monthLabel }}
					</button>
					<div class="dcal-nav">
						<button type="button" class="btn btn-sm iconbtn" aria-label="Previous month" @click="prev">‹</button>
						<button type="button" class="btn btn-sm" @click="goToday">Today</button>
						<button type="button" class="btn btn-sm iconbtn" aria-label="Next month" @click="next">›</button>
					</div>
				</div>
				<div v-if="view === 'date'" class="dcal-grid" role="grid">
					<div class="dcal-dow" role="row">
						<span v-for="(d, i) in ['S', 'M', 'T', 'W', 'T', 'F', 'S']" :key="i">{{ d }}</span>
					</div>
					<div v-for="(week, wi) in weeks" :key="wi" class="dcal-week" role="row">
						<button
							v-for="d in week"
							:key="d.key"
							type="button"
							role="gridcell"
							class="dcal-day"
							:class="{
								out: !d.inMonth,
								today: d.isToday,
								edge: d.isFrom || d.isTo,
								inrange: d.inRange,
							}"
							:aria-selected="d.isFrom || d.isTo ? 'true' : 'false'"
							:aria-label="d.date.format('YYYY-MM-DD')"
							@click="pick(d.date)"
						>
							{{ d.date.date() }}
						</button>
					</div>
				</div>
				<div v-else class="dcal-months" role="grid" aria-label="Select month">
					<button
						v-for="(m, i) in months"
						:key="m"
						type="button"
						class="dcal-m"
						:class="{ on: i === month }"
						@click="month = i; view = 'date'"
					>
						{{ m.slice(0, 3) }}
					</button>
				</div>
				<div class="dcal-foot">
					<button type="button" class="btn btn-sm" :disabled="!from && !to" @click="clear">Clear</button>
				</div>
			</div>
		</Transition>
	</div>
</template>

<style scoped>
.drange-btn {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 150px;
  text-align: left;
  cursor: pointer;
}
.drange-label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12.5px; }
.drange-label.rp-ph { color: var(--faint, inherit); }
.drange-ico { flex: none; color: var(--faint, inherit); }
.dcal { right: 0; left: auto; width: 260px; transform-origin: top right; }
.dcal-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.dcal-title { font-size: 13px; }
.dcal-nav { display: flex; align-items: center; gap: 4px; }
.iconbtn { width: 28px; padding: 0; display: grid; place-items: center; font-size: 14px; }
.dcal-grid { margin-top: 10px; }
.dcal-dow, .dcal-week { display: grid; grid-template-columns: repeat(7, 1fr); }
.dcal-dow span {
  text-align: center;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--faint, inherit);
  padding: 3px 0;
}
.dcal-day {
  border: 0;
  background: none;
  font: inherit;
  font-size: 12.5px;
  color: var(--ink, inherit);
  height: 30px;
  border-radius: 7px;
  cursor: pointer;
}
.dcal-day:hover { background: var(--brand-softer, rgba(102, 163, 191, 0.1)); }
.dcal-day.out { color: var(--faint, inherit); }
.dcal-day.today { font-weight: 800; }
.dcal-day.inrange { border-radius: 0; background: var(--brand-softer, rgba(102, 163, 191, 0.1)); }
.dcal-day.edge { background: var(--brand-soft, rgba(102, 163, 191, 0.18)); color: var(--brand-strong, inherit); font-weight: 700; }
.dcal-months { display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px; margin-top: 10px; }
.dcal-m {
  border: 0;
  background: none;
  font: inherit;
  font-size: 12.5px;
  color: var(--ink, inherit);
  padding: 8px 0;
  border-radius: 7px;
  cursor: pointer;
}
.dcal-m:hover { background: var(--brand-softer, rgba(102, 163, 191, 0.1)); }
.dcal-m.on { background: var(--brand-soft, rgba(102, 163, 191, 0.18)); color: var(--brand-strong, inherit); font-weight: 700; }
.dcal-foot { display: flex; justify-content: flex-end; margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--line, rgba(0, 0, 0, 0.08)); }
</style>
