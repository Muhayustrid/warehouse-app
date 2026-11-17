# PROJECT_STATE — warehouse_app

Head: 2026-11-16 — **feat/fulfillment-stage-tabs (29 commits, unpushed)**: tab Packing = **sheet ala papan klip (Image 2)**: kartu per customer (header kuning, Dry/Colly), tabel Item/Qty/Koli/Berat/B-K/Picker/Estimasi (B/K & Picker kosong utk tulis tangan), Koli+Berat editable inline (autosave per kartu via `save_packing_slip`), klik nama customer = editor full layar lama, TOTAL KOLI + tabel truk + MOBIL/DRIVER, tombol Cetak Packing List = `get_packing_sheet_html` (A4 2 kolom). Label 60x40mm desain baru. **TRAP: `bench restart` TIDAK reload web di container ini (gunicorn = PID 1, tanpa honcho) — WAJIB `kill -HUP 1`**, kasus nyata 2026-11-16 (render lama + endpoint "no attribute" walau file benar). callGet diberi cache-buster `_=Date.now()`. Editor full layar (`.ps-editor-full` fixed inset 56px, z-40). Driver + No. Mobil per hari via POST `save_packing_driver`. Order queue full 1400px. Data dummy: 4 SO `SORD-JURI-261116001..004` (po_no=DUMMY-PS). Tests 136/136 OK; build sukses.

## Current

- Redesign Packing List editor (DONE, commit 0e9e430):
  - `PackingSlipPage.vue` rewritten: tampilan persis image 2 (Excel), drag baris/kolom/resize manual tanpa dependensi, add-row picker dari DN items, driver + no. mobil di header.
  - Backend: `validate_slip_lines` + `packing_summary` (pure logic, 6 tes baru), save_packing_slip terima driver/vehicle_no + validasi item harus di DN & qty>0, load_packing_slips agregat hasil packing per SO, custom fields via upgrade.py (bench migrate).
  - Rulings tetap: count() v16 error → loop manual; berat per-koli dari baris pertama; prefer DN draft.
- Packing Slip per SO page (DONE, commit e81a4e2 + fix):
  - List per SO (bukan per PS): semua SO dgn DN non-cancelled; status Editable/Read-only/Belum Packing; fallback editor dari DN items bila PS belum ada (klasifikasi frozen/dry via profile).
  - Save: satu PS draft per koli (from_case_no=koli), berat persist via item `net_weight` (header `net_weight_pkg` dihitung ulang ERPNext = sum(net_weight x qty)), berat diambil dari baris pertama koli; kategori persist via `custom_box_size` (K=frozen/B=dry).
  - Rulings: `count()` aggregate get_all v16 error → loop manual; default category = frozen; editor pilih DN draft bila ada beberapa DN per SO.
  - Bug fix (e81a4e2): docstatus 0 falsy `or 2` menyaring DN draft; endpoint save rekursif (alias `_save_packing_slip`); PS wajib >=1 item saat insert.
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

1. User review editor baru /gudang/packing-slips (reload browser, build baru sudah terpasang).
2. Push hanya setelah persetujuan eksplisit.

## Constraints

- Do not edit core Frappe/ERPNext; do not force native documents through custom fields.
- `fulfillment.localhost` is disposable; `erp.localhost`/`1oktober2026` are not mutation targets.
- Commit locally only; push/merge requires separate authorization.
