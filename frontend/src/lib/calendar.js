// Util kalender untuk DateRangeField — pengganti util DatePicker frappe-ui.
// Grid minggu mulai Minggu (startOf('week') default dayjs, sama seperti
// frappe-ui), satu object per hari: { date, key, inMonth, isToday, isSelected }.
import dayjs from 'dayjs'

export const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function monthStart(year, monthIndex) {
	return dayjs(`${year}-${monthIndex + 1}-01`)
}

export function generateWeeks(year, monthIndex, selected) {
	const start = monthStart(year, monthIndex).startOf('week')
	const end = monthStart(year, monthIndex).endOf('month').endOf('week')
	const days = []
	let d = start
	while (d.isBefore(end) || d.isSame(end)) {
		const sel = dayjs(selected)
		days.push({
			date: d,
			key: d.format('YYYY-MM-DD'),
			inMonth: d.month() === monthIndex,
			isToday: d.isSame(dayjs().format('YYYY-MM-DD'), 'day'),
			isSelected: sel.isValid() && d.isSame(sel, 'day'),
		})
		d = d.add(1, 'day')
	}
	const weeks = []
	for (let i = 0; i < days.length; i += 7) weeks.push(days.slice(i, i + 7))
	return weeks
}
