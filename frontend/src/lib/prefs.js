// Preferensi tampilan SPA — namespace `wzg` (pemisah dari halaman klasik
// `wzrq_*` supaya kebiasaan lama tidak saling menimpa).
const NS = 'wzg_'

export function loadPref(key, fallback) {
	try {
		const raw = localStorage.getItem(NS + key)
		if (raw == null) {
			return fallback
		}
		return JSON.parse(raw)
	} catch (e) {
		return fallback
	}
}

export function savePref(key, value) {
	try {
		localStorage.setItem(NS + key, JSON.stringify(value))
	} catch (e) {
		/* private mode: abaikan */
	}
}

export function hasPref(key) {
	try {
		return localStorage.getItem(NS + key) != null
	} catch (e) {
		return false
	}
}
