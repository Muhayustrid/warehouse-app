import { ensureCSRFToken } from './csrf'

// Pengganti frappeRequest (frappe-ui): fetch tipis dengan header CSRF +
// cookies. Error frappe (object dgn .messages/.exc_type) dirapikan jadi satu
// string polos oleh errText — pengganti wzrq_err_text halaman klasik.
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

// Frappe membungkus hasil whitelisted method dalam {"message": ...} —
// frappeRequest mengembalikan data.message; fetch tipis ini menirunya.
function unwrap(data) {
	return data && typeof data === 'object' && 'message' in data && Object.keys(data).length === 1
		? data.message
		: data
}

async function request(url, options) {
	const res = await fetch(url, { credentials: 'include', ...options })
	const text = await res.text()
	let data = null
	try {
		data = text ? JSON.parse(text) : null
	} catch {
		/* non-JSON (mis. HTML error) — dibiarkan null */
	}
	if (!res.ok) {
		let messages = []
		try {
			messages = data?._server_messages
				? JSON.parse(data._server_messages).map((m) => JSON.parse(m).message)
				: []
		} catch {
			/* fallback di bawah */
		}
		const e = new Error(errText({
			messages: messages.length ? messages : [data?.exception || data?.message || res.statusText],
			status: res.status,
		}))
		e.status = res.status
		e.exc_type = data?.exc_type || data?.exception
		throw e
	}
	return unwrap(data)
}

// POST ke endpoint whitelisted; gagal CSRF (sesi baru/expired) → refresh
// token sekali lalu retry (pola createCSRFAwareRequest pos_next, dipangkas).
export async function call(url, params = {}) {
	const doRequest = () =>
		request('/api/method/' + url, {
			method: 'POST',
			headers: {
				'Content-Type': 'application/x-www-form-urlencoded',
				'X-Frappe-CSRF-Token': window.csrf_token || '',
			},
			body: new URLSearchParams(params).toString(),
		})
	try {
		return await doRequest()
	} catch (e) {
		const csrfish =
			e?.exc_type === 'CSRFTokenError' ||
			String(e?.message || '').toLowerCase().includes('csrf')
		if (!csrfish) {
			throw e
		}
		const ok = await ensureCSRFToken().catch(() => false)
		if (!ok) {
			throw e
		}
		return await doRequest()
	}
}

// GET ringan (baca saja) — tidak menuntut header CSRF.
export async function callGet(url, params = {}) {
	try {
		// fetch tak punya opsi `params` — query wajib dirangkai sendiri
		const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== ''))
		const suffix = qs.toString() ? '?' + qs : ''
		return await request('/api/method/' + url + suffix)
	} catch (e) {
		throw new Error(errText(e))
	}
}
