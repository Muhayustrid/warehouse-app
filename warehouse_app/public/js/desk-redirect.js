// W33-P4 cutover: workspace Desk "Gudang" sudah menjadi SPA di /gudang.
// path_resolver frappe meng-hardcode semua path desk/* ke template Desk
// SEBELUM redirect/route rule dievaluasi, jadi satu-satunya cara memindahkan
// pembuka jalur lama /desk/gudang adalah client-side. File ini di-include ke
// Desk via app_include_js dan no-op di semua halaman lain.
(function () {
	var path = window.location.pathname.replace(/\/+$/, "");
	if (path === "/desk/gudang" || path === "/app/gudang") {
		window.location.replace("/gudang");
	}
})();
