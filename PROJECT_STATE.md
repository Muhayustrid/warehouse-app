# PROJECT_STATE — warehouse_app

Head: 2026-10-30 — **W54 DONE locally & Backup 29 Okt Migrated to erp.localhost**. In-app fulfillment workspace MVP (F3/F4), Multi-Koli Packing Refinement (Sequential Bin Filling & Live Preview), 1-Click Pick All, Single Print Action, 29 Oct cloud database restored & migrated into `erp.localhost`, and bind mount permanently configured in `frappe16`. Ready for commit & push authorization.

## Current

- W54 Refinements & Print Format Alignment (DONE locally):
  - Stepper Bar Auto-Hide Packing Slip (DONE): Diperbaiki bug di mana stepper bar masih memunculkan step "3. Packing Slip" saat opsi `enable_packing_slip` dimatikan di Pengaturan. Penyebab: `get_profile` pada `profile.py` dan `_profile_payload` pada `loader.py` belum menyertakan kolom `enable_packing_slip`, sehingga saat memuat data preview order nilainya `undefined` (yang secara default dianggap aktif). Kini status `enable_packing_slip` tersinkron penuh dari backend ke frontend, dan tahapan stepper otomatis menciut menjadi 3 langkah bersih (`1. Picking` -> `2. Surat Jalan (DN)` -> `3. Review & Kirim`).
  - Pick List Multi-Page Running Header (DONE): Format cetak Pick List pada halaman ke-2 dst kini tidak lagi mengulang kop surat / letterhead (`.pl-header`) dan rincian customer (`.pl-parties`). Halaman ke-2 dst tampil bersih dengan running header 1 baris ramping (`PICKING LIST — <Doc> [DRY/FROZEN] | Page X / Y`), sehingga tabel item dan blok tanda tangan muat rapi tanpa buang ruang kertas.
  - Fix Multi-Koli Packing Reset & DN Submit Block (DONE): Diperbaiki bug di mana mengemas > 1 koli mereset status kemasan dan gagal submit Delivery Note dengan error `DN_NOT_FULLY_PACKED`. Penyebab: `dn.save()` pada instance `dn` lama di memori menimpa kembali kolom `packed_qty` di database menjadi 0.0. Solusi: update counter kemasan kini menggunakan `frappe.db.set_value` murni tanpa menyentuh tabel anak, ditambah mekanisme auto-sync `packed_qty` dari Packing Slip terbit sebelum validasi submit.
  - Format Print Pick List & Global Letterhead Synced (DONE): Body template Format Print Pick List telah diperbarui mengikuti struktur & CSS yang diberikan (tabel Picker/Packer/Checker, Time, Total Koli, 3 kolom tanda tangan), dengan judul PICKING LIST dan badge DRY/FROZEN (13.5px bold). Letter Head global 'Company Letterhead - Grey' juga telah ditambahkan penanganan khusus Pick List dengan badge DRY/FROZEN di atas judul.
  - Delivery Note Print Format Koli (DONE): Posisi koli pada Letterhead Delivery Note ditukar menjadi `Dry : ______` di kiri lalu `Frozen : ______` di kanan, dengan ukuran font dibesarkan (14px bold, lebar kotak 260px) agar sangat jelas terbaca saat dicetak.
  - Fix Submit Delivery Note Skip Packing Slip (DONE): Pengecekan `DN_NOT_FULLY_PACKED` di `dispatch.py` kini menghormati opsi `enable_packing_slip` dan `require_all_packed`. Jika opsi packing slip dinonaktifkan / dilewati, Delivery Note dapat langsung disubmit tanpa terblokir.
  - Short Pick Instant Modal Popup: Alur picking disederhanakan tanpa birokrasi berbelit. Saat kuantitas barang diambil kurang dari target (stok di gudang kurang), tombol 'Selesaikan Picking' langsung memunculkan pop up rincian barang kurang dan catatan alasan stok kurang, lalu 1-klik konfirmasi langsung menyelesaikan picking dan melompat ke Surat Jalan.
  - Pick List DRY/FROZEN Banner: Ditambahkan badge blok tegas bertuliskan `DRY` atau `FROZEN` di header kanan atas tepat di atas judul `PICKING LIST` pada `Format Print Pick List`, langsung terbaca jelas saat kertas keluar dari printer.
  - Opsi Skip Packing Slip di Settings: Ditambahkan opsi `enable_packing_slip` (Check, default 1) pada `Warehouse Fulfillment Profile` & halaman Settings. Jika dinonaktifkan, tahapan fulfillment menjadi 3 langkah (Picking -> Surat Jalan / DN -> Review & Kirim) dengan tab Packing Slip dilewati dan tombol aksi mengarahkan langsung ke Review & Kirim. Gunicorn container direstart sehingga opsi langsung aktif.
  - Pick List Title & Logo Aspect Ratio: Judul Print Format Pick List diganti menjadi `PICKING LIST`. Logo JURI dibungkus dalam container ber-aspect-ratio alami (`max-width: 105px !important; max-height: 50px !important; object-fit: contain !important;`) sehingga tidak gepeng / terdistorsi oleh CSS tabel bawaan Frappe.
  - Packing Slip Linked to Delivery Note: Format cetak Packing Slip menampilkan `Delivery Note No.` (`doc.delivery_note`), status draf Delivery Note, serta tanggal posting Delivery Note dari tahap draf sebelumnya.
  - Non-Hardcoded Dry Item Exception (Air Mineral Outlet): Ditambahkan konfigurasi pengecualian non-hardcode via field `dry_item_exceptions` pada `Warehouse Fulfillment Profile` dan custom field `custom_fulfillment_category` pada `Item`. Item `PJ260009` (Air Mineral Outlet 600 ml) dalam grup `Produk Jadi Pabrik` kini otomatis terklasifikasi sebagai `dry` tanpa satupun baris hardcode di logika klasifikasi.
  - Fix Packing Slip Frozen Category & Multi-Koli: `against_pick_list` & `item_group` diproyeksikan dari `Delivery Note`, `import json` ditambahkan ke `packing.py`. Pemilihan koli akurat sesuai alokasi.
  - ERPNext Native UI Alignment & Awesomebar: Panel kartu putih bersih standar Desk, label gudang dinamis, dan Awesomebar shortcut registered.
- Backup 29 Okt (DONE): Restored `D:\Backup 29 Okt` (`20261029_134529-stream-database.sql.gz`, 442 real SOs) into `erp.localhost`, extracted public & private files, resolved cloud-only apps in `tabInstalled Application` and global defaults, ran `bench migrate` clean (0 errors), executed `warehouse_app.upgrade.apply()`, and configured `Warehouse Fulfillment Profile` for PT. JUARA ROTI INDONESIA (Frozen: `Produk Jadi Pabrik`). Order queue loads 26 active production SOs (12 Open, 14 Partially Delivered, 385 Completed, 0 Exceptions).
- Docker frappe16 Mount: Permanent bind mount `warehouse-app` in `frappe16/.env` (`COMPOSE_FILE`) so code & built assets never go stale.

## Evidence

- Backend gates green: `w54_schema_gate` (ok: true), `w54_f3_f4_gate` (ok: true, 36 checks), `w49_r0_gate` (ok: true), `w49_f2_gate` (ok: true), `w49_f1_readonly_gate` (ok: true), `w31_gate` (ok: true).
- Unit tests: 98/98 tests PASS in 0.021s.
- `erp.localhost` migration: 0 errors; `get_order_queue` loads 411 production SOs without a single exception.
- Frontend: built cleanly (`npm run build`), served HTTP 200 on port 8080.

## Next

1. Present proposed conventional commit message and obtain user authorization before committing and pushing to GitHub.

## Constraints

- Do not edit core Frappe/ERPNext; do not force native documents through custom fields.
- `fulfillment.localhost` is disposable; `erp.localhost`/`1oktober2026` are not mutation targets.
- Commit locally only; push/merge requires separate authorization.
