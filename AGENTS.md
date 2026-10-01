# warehouse_app — konteks & batasan

## Tujuan

Custom app Frappe/ERPNext untuk **org Gudang (barang jadi)**, berjalan di site yang sama dengan `production_app` (kini site `1oktober2026` di stack baru; sebelumnya `frontend` — lihat § Lingkungan & deploy). Prinsip dasar (keputusan resmi user, 2026-09-20): **native ERPNext tidak boleh terpengaruh custom app mana pun** — production_app fokus user manufacturing, dan semua tooling gudang dikembangkan di app ini. Saling lepas: warehouse_app tidak boleh mengubah perilaku produksi, production_app tidak boleh memaksa perilaku native/gudang.

**Konvensi kolom (keputusan user, 2026-09-29):** tambahan kolom/custom field untuk kebutuhan gudang (di Item, Stock Entry, Material Request, atau doctype native lain) **wajib dikemas di warehouse_app** — pola W21: spec di `upgrade.py` + upsert idempoten (`after_install`/`after_migrate`) + gate tests, label Inggris, jangan dibuatkan lewat production_app/core. Kolom yang mengubah perilaku tampilan diberi client script ber-role gate ("Gudang Barang Jadi") sehingga user native tak terpengaruh.

## Latar (kenapa app ini ada)

- 2026-09-19 (FU48, production_app): gudang sementara pakai Desk ERPNext native; SPA produksi dibersihkan jadi produksi-only.
- 2026-09-20 (FU57, production_app): user menemukan MR native terpaksa wajib Work Order akibat guard custom app, lalu memutuskan: *"native erpnext harusnya ga terpengaruh oleh custom app… nanti kita bikin custom app untuk gudang sendiri aja, yang ini fokus untuk user manufacturing aja"*. Guard dihapus (`retire_mr_guard()`), konsekuensi MR serah terima manual bisa "yatim" diterima user.
- Kesimpulan: **Desk native hanya jembatan**; app gudang terpisah ini adalah rumah permanen tooling gudang. Riwayat lengkap: memory `fu48-interim-gudang-desk` + ledger SDD production_app.

## Domain (dunia yang dioperasikan)

- Produksi roti/bakery, company abbr `-ROPI`; gudang terkait: Gudang Bahan Baku, Gudang Barang Jadi, Gudang Produksi.
- Alur serah terima produksi→gudang: produksi membuat Material Request Material Transfer per Work Order (Form Order = MR dengan `custom_is_form_order`), mengirim via Stock Entry Material Transfer; pelacakan per **batch** dan **box** (Box 1/Box 2 = Float kg); partial SE dari Desk dihitung terkirim penuh; over-request gagal atomik di SE.
- Role gudang: "Gudang Barang Jadi". Celah pre-existing (diparkir): role murni tak punya read Company → tambah Stock User bila perlu simpan dokumen.
- Endpoint server gudang di production_app (`create_request`/`cancel_request`/`fulfill_form_order`) sengaja dibiarkan hidup tanpa pemanggil SPA — reversibel, jangan dihapus tanpa keputusan user.

## Status (2026-09-20)

- W1 selesai: scaffold `bench new-app` + install di site `frontend`, kode tersinkron ke 6 container frappe. Belum ada doctype/API/UI.
- Operasi gudang saat ini masih lewat Desk native (interim) + SPA produksi hanya untuk produksi.

## Scope & pertanyaan terbuka (bahan planning)

Belum dikunci — putuskan bersama user di sesi planning (pakai SDD bila besar):
- Fitur inti gudang: terima serah terima, stok masuk/keluar/transfer, MR ke produksi, counting/opname, laporan stok, apa lagi.
- Bentuk UI: app berbasis Desk (doctype + workspace + client script) vs SPA kedua ala production_workspace.
- Apakah serah terima & alur MR gudang pindah ke sini (beserta endpoint dormant di production_app), atau tetap di produksi dan app ini melengkapi.
- Perbaikan role/perm gudang (Company read, delete draft MR sendiri) — habitat alami perbaikan ini app ini.

**Dilarang (berlaku balik juga ke sini):** edit core Frappe/ERPNext; memaksa dokumen native lewat field custom (jangan ulangi pola guard FU48a); mengubah alur produksi di production_app dari app ini.

## Lingkungan & deploy

- **Lingkungan aktif (sejak 2026-10-01)**: stack compose `1oktober2026` di `~/1oktober2026/` (custom image `erpnext-custom-1okt:v16.35.0`, frappe 16.36/erpnext 16.37 + hrms + item_group_series + stock_entry_series + pos_next + production_app + warehouse_app). Container: `1oktober2026-{backend,frontend,queue-short,queue-long,scheduler,websocket,db,redis-cache,redis-queue}-1`; site TUNGGAL `1oktober2026` (default site) = **site produksi hasil restore** (PT. JUARA ROTI INDONESIA, user asli ropierpnext@gmail.com — jangan pernah bertindak sebagai akun itu). HTTP: `http://127.0.0.1:8088` (route Desk `/app` maupun `/desk` sama-sama jalan).
- **Semua app di-bind-mount** dari `~/1oktober2026/apps/*` → `apps/<name>` di container. Clone warehouse_app di `~/1oktober2026/apps/warehouse-app` (origin GitHub; repo kerja utama tetap `~/erpnext-new/apps/warehouse_app`).
- **Pipeline deploy kode app ini (model baru)**: 1) commit di repo kerja utama; 2) `git -C ~/1oktober2026/apps/warehouse-app pull <repo-utama> main` (atau push+pull dari origin); 3) `docker exec 1oktober2026-backend-1 bench --site 1oktober2026 migrate` (after_migrate menerapkan field/client script); 4) `bench clear-cache` (WAJIB bila hooks.py berubah); 5) restart container python (backend + queue-short + queue-long + scheduler) bila ada perubahan file .py — worker memegang modul lama; 6) `curl http://127.0.0.1:8088/api/method/ping`. Tidak ada docker cp/pth lagi.
- Stack lama `erpnext-new` (port 8081) dan `erpnext-fresh` (8082) MATI + volume sites-nya kosong (insiden volume terhapus terulang 2026-10-01); jangan dipakai/dihidupkan tanpa keputusan user.

## Protokol kerja

- Baca `TASKS.md` + `PROJECT_STATE.md` sebelum bekerja; penomoran tugas pakai prefiks `W#`.
- Tandai IN_PROGRESS di `PROJECT_STATE.md` sebelum edit; DONE butuh **bukti eksekusi** (jangan dari baca kode saja). Satu task aktif pada satu waktu.
- Residu fixture uji = 0 (hapus user/dokumen buatan + Sessions/Activity Log). Browser milik user — jangan pernah bertindak sebagai akun aslinya (ropierpnext@gmail.com); logout via fetch + `X-Frappe-CSRF-Token` sebelum login fixture.
- Commit di repo ini (branch `main`); push/merge hanya atas permintaan user. Rilis aset frontend mengikuti pola production_app bila suatu saat app ini punya SPA.
