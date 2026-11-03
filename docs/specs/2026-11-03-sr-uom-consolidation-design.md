# Konsolidasi konversi UOM Stock Reconciliation (warehouse_app)

Tanggal: 2026-11-03 · Status: disetujui (desain) · App: `warehouse_app`
Handoff terkait: [`HANDOFF_POS_NEXT_SR_UOM.md`](../../HANDOFF_POS_NEXT_SR_UOM.md)

## 1. Latar belakang

Keluhan user: Stock Reconciliation (SR) sering salah konversi, baik saat input
di grid maupun saat submit.

Aturan "kolom per-UOM ↔ `qty`/`valuation_rate` native" saat ini
diimplementasikan di empat tempat dengan aturan berbeda:

| Module | Qty Before | Pembulatan | Baris batch | UOM tak valid |
|---|---|---|---|---|
| Client script W23 (`upgrade.py`, `CLIENT_SCRIPT_STOCK_RECONCILIATION`) | `current_qty / f` | tidak ada | dikonversi | msgprint + kosongkan |
| Hook `inventory_uom.apply_sr_inventory_uom` (`before_validate`) | ledger @ posting time | precision field | dikonversi | throw |
| `warehouse_app/stock_reconciliation.get_items` (Fetch Items) | `qty / f` | 3 desimal, rate 2 desimal | **di-skip** | skip diam-diam |
| `warehouse_app/sr_import.validate_count_rows` | ledger | 3 desimal, toleransi 0.0005 | (item batch ditolak di parse) | error per baris |

Hook server mengonversi ulang **semua** baris ber-`custom_uom` setiap save,
sehingga pembulatan dari module lain menjadi selisih nyata:

- **Qty round-trip.** Ledger 10 pcs, Pack = 12. `get_items` mengisi
  `custom_qty_after = round(10/12, 3) = 0.833`. Hook: `qty = 0.833 × 12 =
  9.996`. Native menganggap baris berubah → SLE −0.004 pcs.
- **Rate round-trip.** `valuation_rate = 1234.5678` → `rate_uom =
  round(1234.5678 × 12, 2) = 14814.81` → hook: `14814.81 / 12 = 1234.5675`.
  Baris ikut terevaluasi ulang.
- **Posting time.** Hook berjalan di `before_validate`, sebelum native
  `validate_posting_time()` me-reset posting date/time ke "sekarang" bila
  `set_posting_time` mati; Qty Before dihitung terhadap timestamp lama.
- **Client script** punya rantai handler yang saling menulis
  (`custom_uom → factor → before → after → qty → custom_qty_after`, guard
  epsilon 1e-6, `after_ajax`, re-guard promise) — tujuh commit perbaikan sejak
  W23 tanpa unit test.

Aritmetika di atas sudah diverifikasi; reproduksi end-to-end di site dev
menjadi langkah pertama implementasi (lihat §7).

## 2. Tujuan dan kriteria sukses

1. Baris yang tidak diubah user tidak pernah menggeser `qty` atau
   `valuation_rate` native (kasus 10 pcs / Pack 12 tetap 10).
2. Grid, Fetch Items, Import Stock Count, dan submit memberi angka yang sama
   untuk input yang sama — satu aturan faktor, pembulatan, dan skip.
3. Qty Before dihitung terhadap posting date/time final dokumen.
4. Matematika baris SR teruji lewat unit test tanpa site.

Di luar lingkup: perubahan pos_next (lihat dokumen handoff), Stock Entry,
Pick List, laporan inventory, perubahan field/DocType.

## 3. Desain

### 3.1 Module hitung baris SR — `warehouse_app/sr_uom.py` (baru)

Satu-satunya pemilik matematika baris SR. Interface:

- `compute_row(...) -> dict` — **fungsi murni** (tanpa DB). Input: `factor`,
  `ledger_qty`, `qty_after`, `rate_per_uom`, `qty` tersimpan,
  `valuation_rate` tersimpan, `allow_zero_valuation_rate`, dan precision
  field. Output: `custom_conversion_factor`, `custom_qty_before`,
  `custom_qty_difference_per_uom`, `qty`, `valuation_rate`.
- `resolve_factors(rows) -> {(item_code, uom): factor | None}` — satu query
  `UOM Conversion Detail` per dokumen; faktor 1 bila UOM = stock UOM; `None`
  = UOM tidak valid (caller yang memutuskan reaksinya).
- `is_convertible(row) -> bool` — baris dikonversi bila `item_code` dan
  `custom_uom` terisi, `custom_qty_after` bukan kosong, dan baris **tidak**
  punya `serial_no` / `serial_and_batch_bundle`. Baris `batch_no` direct
  dikonversi (keputusan W31). `use_serial_batch_fields` tidak memengaruhi.
- `ledger_qty(item_code, warehouse, posting_date, posting_time, cache, batch_no=None)` —
  pindahan `_ledger_qty` (`get_previous_sle` @ posting timestamp untuk non-batch,
  atau `erpnext.stock.doctype.batch.batch.get_batch_qty` untuk baris dengan `batch_no`).
  Cache key: `(item_code, warehouse, batch)`. Batch timestamp balance diteruskan
  dengan parameter standar ERPNext (`for_stock_levels=True, consider_negative_batches=True, do_not_check_future_batches=True`).

#### Aturan konsistensi (inti perbaikan)

Konstanta tunggal: `QTY_UOM_DECIMALS = 3` (presisi kolom per-UOM yang
dipakai semua producer).

- **Qty.** `qty` native tersimpan dipertahankan bila
  `round(qty / factor, 3) == round(qty_after, 3)`. Selain itu (termasuk `qty`
  kosong) `qty = flt(qty_after × factor, precision(qty))`.
- **Rate.** `rate_per_uom` kosong → `valuation_rate` tidak disentuh. Rate 0
  hanya berlaku bila `allow_zero_valuation_rate` (semantik W23b). Selain itu
  `valuation_rate` tersimpan dipertahankan bila
  `round(valuation_rate × factor, p) == round(rate_per_uom, p)` dengan `p` =
  precision `custom_valuation_rate_per_uom`; kalau berbeda
  `valuation_rate = flt(rate_per_uom / factor, precision(valuation_rate))`.
- **Before/diff** selalu dihitung ulang dari ledger:
  `before = flt(ledger_qty / factor, 3)`, `diff = flt(after − before, 3)`.

Batas yang diterima: user yang sengaja mengetik nilai yang sama pada 3
desimal (mis. 0.833 Pack untuk stok 10 pcs) tetap dianggap "tidak berubah"
— memang tidak bisa dibedakan pada presisi kolom.

### 3.2 Class extension Stock Reconciliation

- `hooks.py`: `extend_doctype_class = {"Stock Reconciliation":
  ["warehouse_app.overrides.stock_reconciliation.StockReconciliationUOM"]}`.
  **Bukan** `override_doctype_class`: slot itu dipakai pos_next
  (`CustomStockReconciliation`) dan Frappe hanya memakai override terakhir
  (`frappe/model/base_document.py:117`). Extension diterapkan di atas class
  override (`base_document.py:139`), MRO: `StockReconciliationUOM →
  CustomStockReconciliation (pos_next) → StockReconciliation (ERPNext)`.
- Override `validate_posting_time()`: `super().validate_posting_time()` lalu
  konversi semua baris via `sr_uom.apply_to_doc(self)` sebelum pembuatan serial/batch bundle
  dan native `remove_items_with_no_change()`. Posting time sudah final dan baris batch
  belum ber-bundle saat konversi.
- UOM tidak valid → `frappe.throw` atomik (pesan W23 dipertahankan).
- Doc event `before_validate: apply_sr_inventory_uom` dihapus dari
  `hooks.py`; fungsi lama dihapus dari `inventory_uom.py`, konstanta `SR_*`
  pindah ke `sr_uom.py` (`upgrade.py` mengimpor dari sana, tidak
  menduplikasi).

### 3.3 Caller lain memakai module yang sama

- **`get_items` (Fetch Items):** baris dari native membawa `qty` ledger.
  Isi `custom_qty_after = round(qty / factor, 3)` dan kolom turunan dari
  `compute_row`; `qty`/`valuation_rate` native tidak diubah (aturan
  konsistensi menjamin save tidak menggesernya). Baris `batch_no` direct
  ikut diisi (seragam dengan hook); serial/bundle tetap dilewati. UOM tidak
  valid → fallback stock UOM, faktor 1 (perilaku 6f9e782 dipertahankan).
- **`sr_import.validate_count_rows`:** faktor dan kolom turunan dari
  `resolve_factors` + `compute_row`; validasi per baris, toleransi matched,
  dan pesan error tetap. Baris hitung dengan rate eksplisit tanpa perubahan qty
  meneruskan `qty=current` ledger ke `compute_row` agar aturan konsistensi
  mempertahankan nilai integer qty ledger tanpa drift desimal pembulatan.

### 3.4 Endpoint per-edit dan client script tipis

- Endpoint `warehouse_app.warehouse_app.stock_reconciliation.compute_row`
  (whitelisted, POST): input `item_code, warehouse, posting_date,
  posting_time, uom, qty_after, rate_per_uom, qty, valuation_rate,
  allow_zero_valuation_rate, batch_no=None`; output kolom turunan + `qty`/`valuation_rate`
  native, atau pesan error UOM tidak valid. Permission:
  `frappe.has_permission("Stock Reconciliation", "write", throw=True)` —
  sama dengan native `get_stock_balance_for`, jadi tidak membuka data stok
  ke role baru.
- Client script W23 dipangkas dan disempurnakan:
  - tetap: role gate, isi UOM default (`apply_default_uom`/`apply_defaults`),
    sembunyikan kolom native (W32, idempoten W39);
  - handler `custom_uom`, `custom_qty_after`, `custom_valuation_rate_per_uom`,
    `warehouse`, `batch_no`, dan `current_qty` → satu fungsi `sync_row` yang
    memanggil endpoint lalu men-set semua kolom dari jawaban (abaikan jawaban
    basi bila nilai input baris sudah berubah);
  - `custom_uom` transition: memanggil `sync_row` dengan `omit_rate_per_uom: true`
    dan `omit_qty_after: true` agar server menurunkan display rate baru dari
    `valuation_rate` native tersimpan;
  - pergantian `item_code`: mereset metadata custom usang (`custom_uom`, faktor,
    before, after, diff, rate per UOM) di dalam guard `syncing_rows`, meng-invalidate
    request ID, dan menunggu `after_ajax` sebelum seeding UOM default yang dijaga
    terhadap respons asinkron out-of-order;
  - handler `qty` (perubahan dari luar, mis. scan barcode +1): set
    `custom_qty_after = round(qty / factor, 3)` → `sync_row`. Aturan
    konsistensi membuat jawaban tidak mengubah `qty` lagi, sehingga guard
    epsilon anti ping-pong tidak diperlukan;
  - UOM dikosongkan → kosongkan kolom turunan dan unset `qty`/
    `valuation_rate` (perilaku W23 dipertahankan);
  - `allowed_uoms` + msgprint diganti pesan error dari endpoint.
- Nilai yang tampil di grid = hasil `compute_row` = yang dihitung saat save.

## 4. Kompatibilitas data

- Draft SR yang sudah tersimpan dengan pasangan tidak konsisten
  (mis. `qty` 9.996) tidak diperbaiki otomatis: aturan konsistensi
  membiarkan `qty` bila `round(9.996/12, 3) == 0.833`. Sebelum deploy,
  jalankan query read-only di dev untuk menghitung draft SR dengan
  `abs(qty − after × factor) > 0` dan laporkan ke user; perbaikan data
  (bila perlu) keputusan terpisah.
- SR yang sudah submitted tidak disentuh.
- Custom field tidak berubah; `upgrade.apply` hanya memperbarui isi Client
  Script.

## 5. Penanganan error

| Kondisi | Hook/class | `get_items` | Import | Endpoint/client |
|---|---|---|---|---|
| UOM di luar tabel konversi | throw, dokumen tidak tersimpan | fallback stock UOM | error per baris | pesan error, UOM dikosongkan |
| Qty After kosong | baris native (tidak disentuh) | — | wajib diisi | kolom turunan dikosongkan |
| Serial / bundle | passthrough | dilewati | ditolak (sudah) | tidak dipanggil |

## 6. Pengujian

- **Unit test** `warehouse_app/tests/test_sr_uom.py` (pola stub
  `test_inventory_company.py`, tanpa site), minimal:
  1. 10 pcs / Pack 12, after 0.833, qty 10 tersimpan → qty tetap 10;
  2. after diubah ke 1 → qty 12;
  3. qty kosong → qty = after × faktor;
  4. rate 1234.5678 ↔ 14814.81 → valuation_rate tetap;
  5. rate per UOM diubah → valuation_rate = rate / faktor;
  6. rate 0 tanpa `allow_zero_valuation_rate` → valuation_rate tidak disentuh;
  7. `is_convertible`: serial/bundle false, batch_no true;
  8. before/diff dari ledger_qty.
- **Regresi gate** di stack dev: `w23_gate`, `w25_gate`, `w31_gate`
  (pemanggilan langsung `apply_sr_inventory_uom` di `w31_gate.py:523`
  diganti ke class/`sr_uom`).
- **E2E Playwright** di `dev.localhost:8000`: Fetch Items untuk item Pack 12
  dengan stok tidak habis dibagi → Save → Submit tanpa SLE selisih; edit
  Qty After → grid = hasil submit; scan barcode +1; UOM tidak valid ditolak.
- Bukti di `docs/proofs/2026-11-03-sr-uom-consolidation.md`.

## 7. Urutan kerja

1. Reproduksi bug 9.996 di dev (fixture item Pack 12) — bukti "sebelum".
2. `sr_uom.py` + unit test (TDD).
3. Class extension + hapus hook; regresi gate.
4. `get_items` dan `sr_import` pindah ke `sr_uom`.
5. Endpoint + client script tipis; E2E.
6. Query draft tidak konsisten (§4), bukti, rebuild image dev.

## 8. Risiko

- **pos_next blind count:** setelah konversi pindah ke dalam `validate()`,
  `custom_qty_before`/`custom_qty_difference_per_uom` terisi lagi pada draft
  opname, setelah pos_next mengosongkannya. pos_next wajib disesuaikan (lihat
  handoff) dan kedua app di-deploy dalam image yang sama.
- **Round-trip per edit** di grid: satu request per perubahan baris.
  Diterima demi satu sumber kebenaran.
- `extend_doctype_class` bersama `override_doctype_class` pos_next belum
  dijalankan di Frappe 16.52; diverifikasi di langkah 3.
