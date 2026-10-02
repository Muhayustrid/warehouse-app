<script setup>
// Field rentang tanggal (W33-r6) dengan alur klik berurutan ala permintaan
// user: field kosong → klik → kalender → tanggal pertama = "from" (kalender
// tetap terbuka, field ikut terisi) → tanggal kedua = "to" (kalender tutup).
// Hanya from → tetap jadi filter (server mengubah between satu-sisi jadi >=).
// Nilai internal ISO YYYY-MM-DD; tampilan DD-MM-YYYY.
import { computed, ref } from 'vue'
import { Popover } from '@frappe-ui/components/Popover'
import { Button } from '@frappe-ui/components/Button'
import FeatherIcon from '@frappe-ui/components/FeatherIcon.vue'
import { dayjs } from '@frappe-ui/utils/dayjs'
import { months, monthStart, generateWeeks } from '@frappe-ui/components/DatePicker'

const props = defineProps({
	from: { type: String, default: '' },
	to: { type: String, default: '' },
	placeholder: { type: String, default: 'Select date' },
})
const emit = defineEmits(['update:from', 'update:to'])

const view = ref('date')
const year = ref(dayjs().year())
const month = ref(dayjs().month())

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

function pick(date, togglePopover) {
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
		togglePopover() // kedua tanggal terisi → tutup kalender
	} else {
		// tanggal pertama = from; kalender tetap terbuka untuk to
		emit('update:from', iso)
	}
}

function clear(togglePopover) {
	emit('update:from', '')
	emit('update:to', '')
	togglePopover()
}
</script>

<template>
	<Popover placement="bottom-start">
		<template #target="{ togglePopover, isOpen }">
			<button
				type="button"
				class="flex h-8 w-full min-w-0 items-center justify-between gap-1 rounded border bg-surface-modal px-1.5 text-xs"
				:class="[
					display ? 'border-outline-gray-2 text-ink-gray-8' : 'border-outline-gray-2 text-ink-gray-4',
					isOpen ? 'border-outline-gray-3 bg-surface-gray-1' : '',
				]"
				:title="display || placeholder"
				@click="togglePopover()"
			>
				<span class="truncate">{{ display || placeholder }}</span>
				<FeatherIcon name="calendar" class="h-3.5 w-3.5 shrink-0 text-ink-gray-4" />
			</button>
		</template>
		<template #body="{ togglePopover }">
			<div
				class="w-fit min-w-[15.5rem] select-none rounded-lg bg-surface-modal text-base text-ink-gray-9 shadow-2xl ring-1 ring-black ring-opacity-5"
			>
				<div class="flex items-center justify-between gap-1 p-2 pb-0">
					<Button
						variant="ghost"
						size="sm"
						class="text-sm font-medium text-ink-gray-7"
						:label="monthLabel"
						@click="view = view === 'date' ? 'month' : 'date'"
					/>
					<div class="flex items-center">
						<Button variant="ghost" icon="chevron-left" class="size-7" label="previous" @click="prev" />
						<Button variant="ghost" size="sm" class="text-xs" label="Today" @click="goToday" />
						<Button variant="ghost" icon="chevron-right" class="size-7" label="next" @click="next" />
					</div>
				</div>
				<div v-if="view === 'date'" class="p-2">
					<div class="mb-1 flex items-center text-xs font-medium uppercase text-ink-gray-4">
						<div v-for="(d, i) in ['S', 'M', 'T', 'W', 'T', 'F', 'S']" :key="i" class="flex h-6 w-8 items-center justify-center">
							{{ d }}
						</div>
					</div>
					<div v-for="(week, wi) in weeks" :key="wi" class="flex" role="row">
						<button
							v-for="d in week"
							:key="d.key"
							type="button"
							role="gridcell"
							class="flex h-8 w-8 cursor-pointer items-center justify-center rounded text-sm focus:outline-none"
							:class="[
								d.inMonth ? 'text-ink-gray-8' : 'text-ink-gray-3',
								d.isToday ? 'font-extrabold text-ink-gray-9' : '',
								d.isFrom || d.isTo
									? 'bg-surface-gray-6 text-ink-white hover:bg-surface-gray-6'
									: d.inRange
										? 'rounded-none bg-surface-gray-3'
										: 'hover:bg-surface-gray-2',
								d.isFrom && !d.isTo ? 'rounded-l-md rounded-r-none' : '',
								d.isTo && !d.isFrom ? 'rounded-r-md rounded-l-none' : '',
							]"
							:aria-selected="d.isFrom || d.isTo ? 'true' : 'false'"
							:aria-label="d.date.format('YYYY-MM-DD')"
							@click="pick(d.date, togglePopover)"
						>
							{{ d.date.date() }}
						</button>
					</div>
				</div>
				<div v-else class="grid grid-cols-3 gap-1 p-2" role="grid" aria-label="Select month">
					<button
						v-for="(m, i) in months"
						:key="m"
						type="button"
						class="cursor-pointer rounded py-2 text-center text-sm hover:bg-surface-gray-2 focus:outline-none"
						:class="i === month ? 'bg-surface-gray-6 text-ink-white hover:bg-surface-gray-6' : ''"
						@click="month = i; view = 'date'"
					>
						{{ m.slice(0, 3) }}
					</button>
				</div>
				<div class="flex justify-end gap-1 border-t border-outline-gray-1 p-2 dark:border-outline-gray-2">
					<Button size="sm" variant="outline" label="Clear" :disabled="!from && !to" @click="clear(togglePopover)" />
				</div>
			</div>
		</template>
	</Popover>
</template>
