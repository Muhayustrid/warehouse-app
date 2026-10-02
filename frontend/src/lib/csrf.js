const CSRF_PLACEHOLDER = '{{ csrf_token }}'

function normalizeToken(token) {
	if (typeof token !== 'string' || !token || token === CSRF_PLACEHOLDER) {
		return null
	}
	return token
}

export function getCSRFTokenFromCookie() {
	const cookies = new URLSearchParams(document.cookie.split('; ').join('&'))
	const token = normalizeToken(cookies.get('csrf_token'))
	if (token) {
		window.csrf_token = token
	}
	return token
}

// frappe v16 tidak punya endpoint get_csrf_token (pos_next membuat endpoint
// custom-nya sendiri — tidak tersedia bagi app lain). Sumber token di dev:
// HTML Desk /app (sudah login) yang menyematkan csrf_token di boot-nya.
// Produksi: www/gudang.py menyuntikkan token langsung ke index — jalur ini
// hanya fallback bila token belum ada.
export async function ensureCSRFToken() {
	const res = await fetch('/desk', {
		method: 'GET',
		credentials: 'include',
		cache: 'no-store',
	})
	if (!res.ok) {
		return false
	}
	const html = await res.text()
	const m = html.match(/csrf_token['"]?\s*[:=]\s*['"]([A-Za-z0-9_-]{16,})['"]/)
	if (!m) {
		return false
	}
	window.csrf_token = m[1]
	return true
}
