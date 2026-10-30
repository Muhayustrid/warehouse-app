// W33-P4 cutover + W34 pensiunan UI klasik: seluruh jalur Desk lama milik
// warehouse_app dipindahkan ke SPA. path_resolver frappe meng-hardcode semua
// path desk/* ke template Desk SEBELUM redirect/route rule dievaluasi, jadi
// pemindahan hanya bisa client-side. File ini di-include ke Desk via
// app_include_js dan no-op di semua halaman lain.
(function () {
	var target = {
		"/desk/gudang": "/gudang",
		"/app/gudang": "/gudang",
		// W34: halaman klasik dihapus — bookmark lama mendarat di SPA-nya.
		"/desk/gudang_request": "/gudang",
		"/app/gudang_request": "/gudang",
		"/desk/gudang_settings": "/gudang/settings",
		"/app/gudang_settings": "/gudang/settings",
	}[window.location.pathname.replace(/\/+$/, "")];
	if (target) {
		window.location.replace(target);
		return;
	}

	// Register Gudang Fulfillment entries into ERPNext native Awesomebar (search bar)
	function registerSearchEntries() {
		if (!window.frappe) return;

		function addEntries() {
			if (
				frappe.search &&
				frappe.search.utils &&
				typeof frappe.search.utils.make_function_searchable === "function"
			) {
				var entries = [
					{ label: "Gudang Fulfillment", action: function () { window.location.href = "/gudang/fulfillment"; } },
					{ label: "Warehouse Fulfillment", action: function () { window.location.href = "/gudang/fulfillment"; } },
					{ label: "Fulfillment Workspace", action: function () { window.location.href = "/gudang/fulfillment"; } },
					{ label: "Order Queue Gudang", action: function () { window.location.href = "/gudang/fulfillment"; } },
					{ label: "Packing Slip Gudang", action: function () { window.location.href = "/gudang/fulfillment"; } },
					{ label: "Pick List & Kemasan Gudang", action: function () { window.location.href = "/gudang/fulfillment"; } },
				];

				var registered = frappe.search.utils.searchable_functions || [];
				entries.forEach(function (e) {
					var exists = registered.some(function (fn) {
						return fn.label === e.label;
					});
					if (!exists) {
						frappe.search.utils.make_function_searchable(e.action, e.label);
					}
				});
			}
		}

		if (window.frappe.ready) {
			frappe.ready(addEntries);
		} else if (window.$) {
			$(document).ready(addEntries);
		} else {
			window.addEventListener("DOMContentLoaded", addEntries);
		}
	}

	registerSearchEntries();
})();
