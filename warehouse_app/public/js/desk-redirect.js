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
	}
})();
