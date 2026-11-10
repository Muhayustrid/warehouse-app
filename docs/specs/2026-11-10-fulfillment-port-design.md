# Port Fulfillment dari `callmevan1120/warehouse-app` ke `main` lokal

Tanggal: 2026-11-10. Status: desain disetujui user, belum implementasi.

## Latar

- `main` lokal (`Muhayustrid/warehouse-app`, HEAD `ced3814`) sudah maju 11 commit
  dari base bersama `a69511d`, fokus Stock Reconciliation UOM + proteksi input hitung.
- Remote `callmevan1120/warehouse-app` (HEAD `dc42c7f`) menambah subsistem
  fulfillment di atas base yang sama: F1 Order Queue, F2 settings/run/generate,
  F3/F4 workspace picking–packing–delivery + cetak (33 commit).
- Keputusan user: port **semua fulfillment** (Opsi 1 — port selektif, bukan merge git
  penuh, bukan bertahap). Selesai = tergabung ke `main` dan terverifikasi di dev
  (`dev.localhost:8000`), data produksi aman, verifikasi boleh buat draft lalu hapus.

## Prinsip port

1. File **baru** remote disalin verbatim (isi + nama file sama persis).
2. File **konflik** diintegrasi manual dengan basis lokal (SR-UOM lokal menang di
   areanya, fulfillment remote disisipkan di areanya).
3. File **status/docs** remote TIDAK dibawa (`PROJECT_STATE.md`, `TASKS.md`, `PRD_*`,
   `IMPLEMENTATION_PLAN*`, `PLANNING_PROMPT.md`, `HANDOFF_*` milik remote,
   `docs/superpowers/`, `FULFILLMENT_R0_DISCOVERY.md`).
4. Aset build (`warehouse_app/public/gudang/assets/*`, `public/gudang/index.html`,
   `www/gudang.html` versi build) TIDAK di-merge manual — di-regenerate via rebuild.
5. `hooks.py` dan seluruh pekerjaan SR-UOM lokal TIDAK disentuh
   (DocType baru Frappe auto-discover; remote juga tidak mengubah `hooks.py`).

## Inventarisasi port

### A. Backend baru — salin verbatim (18 file + 5 DocType)

- `warehouse_app/warehouse_app/fulfillment/` (18 file: `__init__`, `api`,
  `approval`, `classification`, `delivery`, `dispatch`, `generate`, `generation`,
  `idempotency`, `loader`, `packing`, `permissions`, `picking`, `profile`,
  `queue`, `settings_api`, `short_pick`, `workspace`).
- 5 DocType, masing-masing `__init__.py` + `.json` + `.py`:
  `warehouse_fulfillment_profile`, `warehouse_fulfillment_request_key`,
  `warehouse_fulfillment_run`, `warehouse_fulfillment_run_item`,
  `warehouse_fulfillment_run_allocation`.
- Test/gate (19 file): `test_fulfillment_{classification,generation,idempotency,
  packing,permissions,queue,short_pick,workspace}.py`, `w49_f1_fixture.py`,
  `w49_f1_profile_gate.py`, `w49_f1_readonly_gate.py`, `w49_f2_fixture.py`,
  `w49_f2_gate.py`, `w49_f2_profile_gate.py`, `w49_f2_schema_gate.py`,
  `w49_f2_settings_gate.py`, `w49_r0_gate.py`, `w54_f3_f4_gate.py`,
  `w54_schema_gate.py`.

### B. Frontend baru — salin verbatim

- `frontend/src/data/fulfillment.js`.
- `frontend/src/pages/FulfillmentPage.vue`, `FulfillmentWorkspacePage.vue`.
- `frontend/src/components/fulfillment/` (6 file: `DeliveryPanel`, `PackingPanel`,
  `PickingPanel`, `PrintPreviewModal`, `ReviewPanel`, `SplitConfirmationModal`).
- `frontend/src/components/FulfillmentDrawer.vue` — catatan: di remote tidak ada
  importirnya (dead code, hanya `router.js` yang me-refer halaman fulfillment).
  Tetap dibawa verbatim demi paritas; kandidat hapus di lain waktu, bukan di sini.

### C. Frontend remote-only — ambil versi remote utuh

`App.vue` (nav Fulfillment), `SideNav.vue` (seksi Order Queue), `router.js`
(2 rute `/fulfillment`), `data/settings.js` (3 API settings fulfillment),
`ConfirmDialog.vue` (theme warning + confirmClass — superset, lokal tak menyentuh),
`gudang.css` (33 baris, lokal tak menyentuh), `pages/SettingsPage.vue`
(remote-only, +404 baris panel fulfillment), `public/js/desk-redirect.js`
(`return` + registrasi Awesomebar fulfillment).

### D. Titik integrasi manual (5 file)

1. **`warehouse_app/upgrade.py`** — konflik tertinggi. `apply()` lokal (8 langkah)
   vs remote (13 langkah: + `ensure_profile_dry_exceptions`,
   `ensure_pl_fulfillment_fields`, `ensure_fulfillment_lineage_fields`,
   `ensure_delivery_note_letterhead_koli`, `ensure_format_print_pick_list`,
   `ensure_format_print_packing_slip`, `backfill_run_short_pick_snapshot`).
   Gabung: seluruh langkah lokal dipertahankan sesuai urutan, langkah fulfillment
   disisipkan pada posisi urutan remote. Verifikasi tiap `ensure_*`/`ITEM_*_SPEC`
   yang bernama sama di kedua sisi (khususnya `ensure_item_fields`,
   `ensure_sr_fields`, `ensure_pl_fields`) — ambil union bila badan fungsi beda.
   Konstanta `sr_uom` impor lokal (SR_CONFIRMATION_FIELD dkk.) dipertahankan.
2. **`warehouse_app/warehouse_app/gudang_settings.py`** — remote hanya menambah
   guard `_handover_fields_available()` (aman untuk site tanpa `production_app`).
   Ambil guard remote, pertahankan sisa file lokal.
3. **`frontend/src/pages/BoardPage.vue`** — konflik tertinggi kedua. Basis lokal;
   sisipkan hunk remote. Zona rawan tumpang tindih: `doCancel` (kedua sisi ubah)
   dan area dayhead/checkbox/floatbar. Selesaikan dengan diff3 per hunk, bukan
   ambil-salah-satu.
4. **`frontend/src/pages/InventoryPage.vue`** — remote hanya blok CSS
   (`.inv-page .panel`, `.inv-page .dseg*`, hover baris). Basis lokal + tempel
   blok CSS remote; cek bentrok selektor saat planning.
5. **`warehouse_app/warehouse_app/inventory.py`, `gudang_request.py`,
   `sr_import.py`, `stock_reconciliation.py`** — hanya diubah lokal, JANGAN
   ditimpa file remote (remote tak menyentuhnya; konfirmasi ulang saat planning).

## Urutan kerja (untuk implementation plan)

1. Salin file grup A–C dari checkout remote (sudah ada klon shallow di `/tmp` —
   klon ulang fresh atau fetch ke branch `port/fulfillment-remote` untuk audit).
2. Integrasi manual grup D (upgrade.py dulu — menentukan migrasi).
3. Rebuild image dev + `bench migrate` di `dev.localhost`.
4. Gate hijau: seluruh gate fulfillment (w49/w54) + gate SR lokal (w23/w25/w31/w32)
   dan test SR/inventory.
5. Verifikasi dev: buka `/fulfillment`, Order Queue tampil, buat Run (F2 generate),
   Pick List draft, Delivery Note draft + cetak packing slip, lalu HAPUS semua
   dokumen draft. Prod (`erp.localhost:8090`) tidak disentuh.
6. Commit ke `main` dengan pesan Conventional Commit + referensi remote
   (`HEAD dc42c7f`) sebagai pengganti histori merge.

## Risiko

- `doCancel`/floatbar BoardPage: salah-resolve hunk menghilangkan perbaikan W47/W48
  lokal ATAU perilaku fulfillment — mitigasi: diff3 + uji regresi dialog request.
- `ensure_item_fields`beda-beda isi antar sisi bisa ganda/menimpa Custom Field
  fulfillment vs lokal — mitigasi: bandingkan badan fungsi sebelum gabung.
- `FulfillmentDrawer.vue` dead code ikut menambah bobot aset — diterima sadar,
  bukan alasan menunda.
- shortcut: gate fulfillment remote belum dijalankan di atas `main` lokal sama
  sekali; bila gate merah karena dependensi SR-UOM lokal, naikkan ke plan.
