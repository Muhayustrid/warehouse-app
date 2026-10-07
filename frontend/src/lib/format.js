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

// W40 Inventory — angka gaya Indonesia (titik ribuan, koma desimal) supaya
// qty sejalan dengan Rupiah.
export function fmtQty(value, digits = 2) {
	return Number(value || 0).toLocaleString('id-ID', { maximumFractionDigits: digits })
}

// "Rp1.858.909" / "-Rp71.249" — dibulatkan ke rupiah penuh.
export function fmtRp(value) {
	const v = Math.round(Number(value || 0))
	return (v < 0 ? '-' : '') + 'Rp' + Math.abs(v).toLocaleString('id-ID')
}

// "07 Oct 2026, 21:37" — diparse dari string (waktu site, tanpa geser zona).
export function fmtDateTime(value) {
	const m = String(value || '').match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})/)
	return m ? `${fmtDate(m[1])}, ${m[2]}` : fmtDate(value)
}
