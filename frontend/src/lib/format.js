export function fmtNum(value) {
	return Number(value == null ? 0 : value).toLocaleString('en-US')
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// "01 Oct 2026" — diparse dari string TANPA Date utk menghindari pergeseran
// zona waktu (creation dari server adalah waktu site, bukan UTC murni).
export function fmtDate(value) {
	if (!value) {
		return ''
	}
	const s = String(value)
	const m = s.match(/^(\d{4})-(\d{2})-(\d{2})/)
	if (!m) {
		return s
	}
	return `${m[3]} ${MONTHS[Number(m[2]) - 1] || m[2]} ${m[1]}`
}

export function initials(user) {
	const local = String(user || '').split('@')[0] || '?'
	const parts = local.split(/[._-]+/).filter(Boolean)
	if (parts.length >= 2) {
		return (parts[0][0] + parts[1][0]).toUpperCase()
	}
	return local.slice(0, 2).toUpperCase()
}
