import frappe
from urllib.parse import quote


def get_context(context):
	# SPA Gudang (W33) — dilayani di /gudang lewat website_route_rules.
	# Role gate server-side: halaman hanya untuk role gudang (SM/SU/SysMgr);
	# link tersembunyi di workspace bersifat kosmetik, gate yang ini yang
	# menegakkan (pola production_workspace).
	if frappe.session.user == "Guest":
		# routing berbasis path — deep link tetap utuh lewat query redirect-to
		frappe.local.flags.redirect_location = "/login?redirect-to=" + quote(
			frappe.request.path or "/gudang", safe=""
		)
		raise frappe.Redirect
	if frappe.session.user != "Administrator":
		roles = set(frappe.get_roles(frappe.session.user))
		if not roles & {"Stock Manager", "Stock User", "System Manager"}:
			frappe.local.flags.redirect_location = "/app"
			raise frappe.Redirect
	from frappe.sessions import get_csrf_token

	context.csrf_token = get_csrf_token()
	context.no_cache = 1
	return context
