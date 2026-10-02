import { getCSRFTokenFromCookie, ensureCSRFToken } from './csrf'

export function sessionUser() {
	const cookies = new URLSearchParams(document.cookie.split('; ').join('&'))
	const user = cookies.get('user_id')
	return user === 'Guest' ? null : user
}

// Dipanggil sekali di main.js sebelum mount: pastikan token CSRF siap dan
// user sudah login — Guest diarahkan ke login Desk (SPA tidak punya halaman
// login sendiri; Desk yang memiliki sesi).
export async function initSession() {
	getCSRFTokenFromCookie()
	// placeholder jinja dari index.html valid sebagai JS — dianggap "belum ada"
	if (!window.csrf_token || window.csrf_token.startsWith('{{')) {
		await ensureCSRFToken().catch(() => false)
	}
	if (!sessionUser()) {
		const next = encodeURIComponent(location.pathname + location.search)
		location.href = '/login?redirect-to=' + next
		throw new Error('not logged in — redirecting')
	}
}
