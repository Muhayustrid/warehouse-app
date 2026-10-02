import { frappeRequest } from '@frappe-ui/utils/frappeRequest.js'
import { ensureCSRFToken } from './csrf'

// Teks error frappe (frappeRequest melempar object dgn .messages/.exc_type)
// dirapikan jadi satu string polos — pengganti wzrq_err_text halaman klasik.
export function errText(e) {
	if (!e) {
		return 'Unknown error'
	}
	if (Array.isArray(e.messages) && e.messages.length) {
		return e.messages.map((m) => String(m).replace(/<[^>]*>/g, '')).join(' ')
	}
	if (typeof e.message === 'string' && e.message && !/^\[object/.test(e.message)) {
		return e.message.replace(/<[^>]*>/g, '')
	}
	return 'HTTP ' + (e.status || e.httpStatus || '?')
}

// POST ke endpoint whitelisted; gagal CSRF (sesi baru/expired) → refresh
// token sekali lalu retry (pola createCSRFAwareRequest pos_next, dipangkas).
export async function call(url, params = {}) {
	const doRequest = () =>
		frappeRequest({
			url: '/api/method/' + url,
			method: 'POST',
			params,
		})
	try {
		return await doRequest()
	} catch (e) {
		const csrfish =
			e?.exc_type === 'CSRFTokenError' ||
			String(e?.message || '').toLowerCase().includes('csrf')
		if (!csrfish) {
			throw new Error(errText(e))
		}
		const ok = await ensureCSRFToken().catch(() => false)
		if (!ok) {
			throw new Error(errText(e))
		}
		return await doRequest()
	}
}

// GET ringan (baca saja) — tidak menuntut header CSRF.
export async function callGet(url, params = {}) {
	try {
		return await frappeRequest({
			url: '/api/method/' + url,
			method: 'GET',
			params,
		})
	} catch (e) {
		throw new Error(errText(e))
	}
}
