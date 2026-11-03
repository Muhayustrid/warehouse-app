# Bukti Verifikasi: Konsolidasi UOM Stock Reconciliation (`warehouse_app`)

**Tanggal:** 2026-11-03

**Status:** Terverifikasi pada Host Test Suite; 66 tes Python lulus, termasuk wrapper 19 tes Node. Seluruh temuan review final dan residual F1/F2 telah ditangani dan disetujui dalam review ulang. Pengujian site belum dijalankan.

**Dokumen Desain:** `docs/specs/2026-11-03-sr-uom-consolidation-design.md`

**Rencana Implementasi:** `docs/plans/2026-11-03-sr-uom-consolidation.md`

**Handoff pos_next:** `HANDOFF_POS_NEXT_SR_UOM.md`

---

## 1. Ringkasan Eksekusi

Konsolidasi matematika per-UOM Stock Reconciliation (SR) telah diimplementasikan lintas 5 task teknis dan gelombang perbaikan terfokus (Residual Fix F1/F2):
1. **`sr_uom.py` (Task 1):** Modul inti murni yang memiliki aturan konsistensi `compute_row`, penentuan faktor `resolve_factors`, predikat baris `is_convertible`, dan pembacaan snapshot buku besar `ledger_qty` dengan dukungan saldo batch (`batch_no`) dan penerusan `ignore_reserved_stock=True` agar saldo fisik (bukan available) tetap terjaga.
2. **`StockReconciliationUOM` (Task 2):** Class extension via `extend_doctype_class` yang mengaitkan konversi UOM ke `validate_posting_time()` setelah `super().validate_posting_time()`. Menggantikan hook event `before_validate` lama yang dihapus dari `inventory_uom.py`.
3. **Endpoint & Fetch Items (Task 3):** Endpoint `@frappe.whitelist(methods=["POST"]) compute_row` terproteksi izin tulis SR dengan dukungan `batch_no`, serta penyesuaian `get_items` yang mengisi baris tanpa mengubah `qty`/`valuation_rate` native.
4. **Import Stock Count (Task 4):** Penyesuaian `validate_count_rows` pada `sr_import.py` menggunakan `sr_uom` dengan preservasi ledger qty pada baris rate eksplisit.
5. **Client Script Tipis (Task 5):** Penyederhanaan skrip client SR W23 di `upgrade.py` menjadi pemanggil endpoint `compute_row` dengan proteksi guard async concurrency, penanganan transisi UOM/item, batch balance threading, dan fallback empty-only `resolve_val_rate` yang mempertahankan nilai eksplisit 0 pada native `valuation_rate`.

> **Catatan Status Review:**
> Seluruh task implementasi (Tasks 1–5), temuan F1–F4, dan perbaikan residual F1/F2 telah tuntas diselesaikan dan diverifikasi pada host-only test suite: 66 tests Python lolos 100%, 19/19 Node.js tests lolos. Tidak ada klaim validasi live site/database karena operasi Docker/site dilarang. Whole-change final review masih pending oleh controller.

---

## 2. Hasil Eksekusi Test Suite Gabungan

Semua pengujian unit host-side dijalankan dari root repositori worktree tanpa koneksi ke database atau Docker live.

### 2.1 Host Unittest Suite (Python + Node.js)

**Perintah:**
```bash
python3 -m unittest \
  warehouse_app.tests.test_sr_uom \
  warehouse_app.tests.test_sr_class \
  warehouse_app.tests.test_sr_endpoints \
  warehouse_app.tests.test_sr_import_uom \
  warehouse_app.tests.test_sr_client_script \
  warehouse_app.tests.test_inventory_company \
  -v
```

**Hasil:**
```text
test_apply_to_doc_invalid_uom_atomic (warehouse_app.tests.test_sr_uom.TestSrUom.test_apply_to_doc_invalid_uom_atomic) ... ok
test_apply_to_doc_uses_doc_posting_time (warehouse_app.tests.test_sr_uom.TestSrUom.test_apply_to_doc_uses_doc_posting_time) ... ok
test_before_and_diff (warehouse_app.tests.test_sr_uom.TestSrUom.test_before_and_diff) ... ok
test_changed_after_recomputes_qty (warehouse_app.tests.test_sr_uom.TestSrUom.test_changed_after_recomputes_qty) ... ok
test_compute_row_idempotence (warehouse_app.tests.test_sr_uom.TestSrUom.test_compute_row_idempotence) ... ok
test_empty_after_prefills_from_ledger (warehouse_app.tests.test_sr_uom.TestSrUom.test_empty_after_prefills_from_ledger) ... ok
test_empty_qty_is_computed (warehouse_app.tests.test_sr_uom.TestSrUom.test_empty_qty_is_computed) ... ok
test_explicit_zero_rate_allowed (warehouse_app.tests.test_sr_uom.TestSrUom.test_explicit_zero_rate_allowed) ... ok
test_inconsistent_rate_rounded_first_fixed_point (warehouse_app.tests.test_sr_uom.TestSrUom.test_inconsistent_rate_rounded_first_fixed_point) ... ok
test_is_convertible (warehouse_app.tests.test_sr_uom.TestSrUom.test_is_convertible) ... ok
test_ledger_qty_caching (warehouse_app.tests.test_sr_uom.TestSrUom.test_ledger_qty_caching) ... ok
test_precisions_from_new_doc (warehouse_app.tests.test_sr_uom.TestSrUom.test_precisions_from_new_doc) ... ok
test_precisions_from_row (warehouse_app.tests.test_sr_uom.TestSrUom.test_precisions_from_row) ... ok
test_prefill_empty_after_rounding_boundary_keeps_ledger_qty (warehouse_app.tests.test_sr_uom.TestSrUom.test_prefill_empty_after_rounding_boundary_keeps_ledger_qty) ... ok
test_rate_changed_recomputes (warehouse_app.tests.test_sr_uom.TestSrUom.test_rate_changed_recomputes) ... ok
test_rate_round_trip_kept (warehouse_app.tests.test_sr_uom.TestSrUom.test_rate_round_trip_kept) ... ok
test_resolve_factors (warehouse_app.tests.test_sr_uom.TestSrUom.test_resolve_factors) ... ok
test_silent_zero_rate_is_empty (warehouse_app.tests.test_sr_uom.TestSrUom.test_silent_zero_rate_is_empty) ... ok
test_untouched_row_at_rounding_boundary_keeps_native_qty (warehouse_app.tests.test_sr_uom.TestSrUom.test_untouched_row_at_rounding_boundary_keeps_native_qty) ... ok
test_untouched_row_keeps_native_qty (warehouse_app.tests.test_sr_uom.TestSrUom.test_untouched_row_keeps_native_qty) ... ok
test_batch_zero_count_converts_before_bundle (warehouse_app.tests.test_sr_class.TestStockReconciliationClass.test_batch_zero_count_converts_before_bundle) ... ok
test_converts_after_posting_time_before_bundle_and_native_filter (warehouse_app.tests.test_sr_class.TestStockReconciliationClass.test_converts_after_posting_time_before_bundle_and_native_filter) ... ok
test_hooks_registration (warehouse_app.tests.test_sr_class.TestStockReconciliationClass.test_hooks_registration) ... ok
test_mro_with_pos_next_override (warehouse_app.tests.test_sr_class.TestStockReconciliationClass.test_mro_with_pos_next_override) ... ok
test_old_hook_removed (warehouse_app.tests.test_sr_class.TestStockReconciliationClass.test_old_hook_removed) ... ok
test_uses_final_posting_time (warehouse_app.tests.test_sr_class.TestStockReconciliationClass.test_uses_final_posting_time) ... ok
test_endpoint_invalid_uom_throws (warehouse_app.tests.test_sr_endpoints.TestStockReconciliationEndpoints.test_endpoint_invalid_uom_throws) ... ok
test_endpoint_missing_context_throws (warehouse_app.tests.test_sr_endpoints.TestStockReconciliationEndpoints.test_endpoint_missing_context_throws) ... ok
test_endpoint_permission (warehouse_app.tests.test_sr_endpoints.TestStockReconciliationEndpoints.test_endpoint_permission) ... ok
test_endpoint_posting_time_defaults (warehouse_app.tests.test_sr_endpoints.TestStockReconciliationEndpoints.test_endpoint_posting_time_defaults) ... ok
test_endpoint_prefill_and_change (warehouse_app.tests.test_sr_endpoints.TestStockReconciliationEndpoints.test_endpoint_prefill_and_change) ... ok
test_endpoint_rate_handling (warehouse_app.tests.test_sr_endpoints.TestStockReconciliationEndpoints.test_endpoint_rate_handling) ... ok
test_endpoint_rejects_non_numeric_strings (warehouse_app.tests.test_sr_endpoints.TestStockReconciliationEndpoints.test_endpoint_rejects_non_numeric_strings) ... ok
test_endpoint_rejects_nonfinite_numbers (warehouse_app.tests.test_sr_endpoints.TestStockReconciliationEndpoints.test_endpoint_rejects_nonfinite_numbers) ... ok
test_endpoint_string_null_undefined_treated_as_empty (warehouse_app.tests.test_sr_endpoints.TestStockReconciliationEndpoints.test_endpoint_string_null_undefined_treated_as_empty) ... ok
test_fetch_fills_batch_rows (warehouse_app.tests.test_sr_endpoints.TestStockReconciliationEndpoints.test_fetch_fills_batch_rows) ... ok
test_fetch_invalid_default_uom_falls_back (warehouse_app.tests.test_sr_endpoints.TestStockReconciliationEndpoints.test_fetch_invalid_default_uom_falls_back) ... ok
test_fetch_round_trip_stable (warehouse_app.tests.test_sr_endpoints.TestStockReconciliationEndpoints.test_fetch_round_trip_stable) ... ok
test_fetch_skips_serial (warehouse_app.tests.test_sr_endpoints.TestStockReconciliationEndpoints.test_fetch_skips_serial) ... ok
test_import_explicit_rate (warehouse_app.tests.test_sr_import_uom.TestSrImportUom.test_import_explicit_rate) ... ok
test_import_invalid_uom_error_message (warehouse_app.tests.test_sr_import_uom.TestSrImportUom.test_import_invalid_uom_error_message) ... ok
test_import_matched_row_boundary_uses_rounded_before (warehouse_app.tests.test_sr_import_uom.TestSrImportUom.test_import_matched_row_boundary_uses_rounded_before) ... ok
test_import_matched_row_stripped (warehouse_app.tests.test_sr_import_uom.TestSrImportUom.test_import_matched_row_stripped) ... ok
test_import_no_rate_uses_system_rate (warehouse_app.tests.test_sr_import_uom.TestSrImportUom.test_import_no_rate_uses_system_rate) ... ok
test_import_rate_drift_1200_004999_round_trip (warehouse_app.tests.test_sr_import_uom.TestSrImportUom.test_import_rate_drift_1200_004999_round_trip) ... ok
test_import_row_matches_class_math (warehouse_app.tests.test_sr_import_uom.TestSrImportUom.test_import_row_matches_class_math) ... ok
test_import_zero_stock_warning_and_none_rate (warehouse_app.tests.test_sr_import_uom.TestSrImportUom.test_import_zero_stock_warning_and_none_rate) ... ok
test_sr_client_script_node_suite (warehouse_app.tests.test_sr_client_script.TestSrClientScript.test_sr_client_script_node_suite) ... ok
test_combined_positional_pagination_with_company (warehouse_app.tests.test_inventory_company.TestInventoryCompanyRegression.test_combined_positional_pagination_with_company) ... ok
test_export_explicit_company (warehouse_app.tests.test_inventory_company.TestInventoryCompanyRegression.test_export_explicit_company) ... ok
test_filter_options_no_permissions (warehouse_app.tests.test_inventory_company.TestInventoryCompanyRegression.test_filter_options_no_permissions) ... ok
test_filter_options_permission_and_placeholder_integrity (warehouse_app.tests.test_inventory_company.TestInventoryCompanyRegression.test_filter_options_permission_and_placeholder_integrity) ... ok
test_inventory_info_returns_company (warehouse_app.tests.test_inventory_company.TestInventoryCompanyRegression.test_inventory_info_returns_company) ... ok
test_inventory_info_user_permission_company (warehouse_app.tests.test_inventory_company.TestInventoryCompanyRegression.test_inventory_info_user_permission_company) ... ok
test_movements_explicit_company (warehouse_app.tests.test_inventory_company.TestInventoryCompanyRegression.test_movements_explicit_company) ... ok
test_movements_positional_args_backward_compatibility (warehouse_app.tests.test_inventory_company.TestInventoryCompanyRegression.test_movements_positional_args_backward_compatibility) ... ok
test_stock_balance_explicit_company (warehouse_app.tests.test_inventory_company.TestInventoryCompanyRegression.test_stock_balance_explicit_company) ... ok
test_stock_balance_positional_args_backward_compatibility (warehouse_app.tests.test_inventory_company.TestInventoryCompanyRegression.test_stock_balance_positional_args_backward_compatibility) ... ok
test_stock_balance_user_permission_company (warehouse_app.tests.test_inventory_company.TestInventoryCompanyRegression.test_stock_balance_user_permission_company) ... ok
test_stock_cards_explicit_company (warehouse_app.tests.test_inventory_company.TestInventoryCompanyRegression.test_stock_cards_explicit_company) ... ok
test_stock_cards_positional_args_backward_compatibility (warehouse_app.tests.test_inventory_company.TestInventoryCompanyRegression.test_stock_cards_positional_args_backward_compatibility) ... ok

----------------------------------------------------------------------
Ran 61 tests in 0.357s

OK
```

### 2.2 Kompilasi Python (`py_compile`)

**Perintah:**
```bash
python3 -m py_compile \
  warehouse_app/hooks.py \
  warehouse_app/inventory_uom.py \
  warehouse_app/overrides/stock_reconciliation.py \
  warehouse_app/sr_uom.py \
  warehouse_app/tests/test_sr_class.py \
  warehouse_app/tests/test_sr_client_script.py \
  warehouse_app/tests/test_sr_endpoints.py \
  warehouse_app/tests/test_sr_import_uom.py \
  warehouse_app/tests/test_sr_uom.py \
  warehouse_app/tests/w23_gate.py \
  warehouse_app/tests/w25_gate.py \
  warehouse_app/tests/w31_gate.py \
  warehouse_app/upgrade.py \
  warehouse_app/warehouse_app/sr_import.py \
  warehouse_app/warehouse_app/stock_reconciliation.py
```
**Hasil:** Bersih (exit code 0, tanpa output kesalahan sintaks).

### 2.3 Pemeriksaan Format Git Diff (`git diff --check`)

**Perintah:**
```bash
git diff --check && git diff --cached --check
```
**Hasil:** Bersih (exit code 0, tidak ada whitespace error atau conflict marker).

### 2.4 Audit Pembersihan Simbol Legacy

**Perintah:**
```bash
rg -n "apply_sr_inventory_uom|_ledger_qty" warehouse_app
```
**Hasil:**
- `warehouse_app/tests/test_sr_class.py:12`: Catatan rencana pengujian
- `warehouse_app/tests/test_sr_class.py:218`: Asersi `self.assertFalse(hasattr(inventory_uom, "apply_sr_inventory_uom"))`
- `warehouse_app/tests/test_sr_uom.py`: Hanya penamaan method test (`test_prefill_empty_after_rounding_boundary_keeps_ledger_qty` dan `test_ledger_qty_caching`)

Tidak ada referensi fungsional kode yang tertinggal ke simbol legacy tersebut.

---

## 3. Bukti Verifikasi Kasus Presisi Kritis

### 3.1 Kasus Round-trip Qty (9.996 vs 10 Nos)

**Masalah awal:**
Item dengan stock UOM Nos, UOM opname Pack (faktor 12). Stok buku besar = 10 Nos.
Pada implementasi lama, `10 / 12 = 0.833`. Saat form disimpan, hook mengalikan `0.833 × 12 = 9.996`, sehingga baris yang sama sekali tidak diedit oleh staf gudang bergeser dari 10 menjadi 9.996 (muncul selisih palsu −0.004).

**Bukti Pengujian Lolos:**
1. **`test_untouched_row_keeps_native_qty` (`test_sr_uom.py:140`):**
   ```python
   compute_row(factor=12, ledger_qty=10, qty_after=0.833, qty=10, prec=P)["qty"] == 10
   ```
   Aturan konsistensi memeriksa:
   `flt(qty / factor, 3) == flt(custom_qty_after, 3)` (yaitu `flt(10 / 12, 3) == 0.833`).
   Karena nilainya sama pada presisi 3 desimal, nilai `qty` native tersimpan (10) dipertahankan utuh.
2. **`test_empty_qty_is_computed` (`test_sr_uom.py:148`):**
   ```python
   compute_row(factor=12, ledger_qty=10, qty_after=0.833, qty=None, prec=P)["qty"] == 9.996
   ```
   Bila `qty` native belum ada (baris baru yang diinput manual), nilai native dihitung dari `custom_qty_after × factor = 9.996`.
3. **`test_empty_after_prefills_from_ledger` (`test_sr_uom.py:152`):**
   Bila baris diambil dari sistem tanpa input manual (`qty_after=None, qty=None`), sistem mengisi `custom_qty_after = 0.833` dan tetap mempertahankan `qty = 10` dari ledger.
4. **`test_prefill_empty_after_rounding_boundary_keeps_ledger_qty` (`test_sr_uom.py:114`):**
   Pada kasus batas `ledger_qty = 0.054`, faktor 12 (`0.054 / 12 = 0.0045`), Frappe banker's rounding membulatkan ke `0.005`. Sistem mempertahankan `qty = 0.054` dan tidak melonjak ke `0.005 × 12 = 0.060`.

### 3.2 Kasus Round-trip Valuation Rate (1234.5675 vs 1234.5678)

**Masalah awal:**
`valuation_rate = 1234.5678`, faktor 12. Di layar dikalikan menjadi `rate_per_uom = round(1234.5678 × 12, 2) = 14814.81`.
Saat disimpan, hook membagi kembali `14814.81 / 12 = 1234.5675`, merusak nilai valuasi buku besar sebesar 0.0003 per unit.

**Bukti Pengujian Lolos:**
1. **`test_rate_round_trip_kept` (`test_sr_uom.py:158`):**
   ```python
   compute_row(
       factor=12,
       ledger_qty=10,
       qty_after=1,
       valuation_rate=1234.5678,
       rate_per_uom=14814.81,
       prec=P,
   )["valuation_rate"] == 1234.5678
   ```
   Aturan konsistensi memeriksa:
   `flt(valuation_rate * factor, p) == flt(rate_per_uom, p)` (yaitu `14814.81 == 14814.81`).
   Karena konsisten pada presisi field display (2 desimal), `valuation_rate` native tidak dihitung ulang dan tetap 1234.5678.
2. **`test_fetch_round_trip_stable` (`test_sr_endpoints.py:14`):**
   Mengonfirmasi bahwa baris yang diambil lewat `get_items` membawa `valuation_rate = 1234.5678` dan `custom_valuation_rate_per_uom = 14814.81`, dan ketika diproses ulang melalui `compute_row` saat simpan, angkanya tetap stabil 100%.

---

## 4. Query Diagnostik Data Draft untuk User (Spec §4)

Sebelum rilis atau saat audit database, query read-only berikut dapat dijalankan oleh user/administrator pada database ERPNext.

### 4.1 Diagnostik Kandidat Drift (Candidate Drift Diagnostic)

Query awal dari task brief:
```sql
select p.name, i.idx, i.item_code, i.qty, i.custom_qty_after, i.custom_conversion_factor
from `tabStock Reconciliation Item` i
join `tabStock Reconciliation` p on p.name = i.parent
where p.docstatus = 0
  and i.custom_uom is not null
  and i.custom_conversion_factor > 0
  and abs(i.qty - i.custom_qty_after * i.custom_conversion_factor) > 0;
```

**Penjelasan Penting / Disclaimer:**
Query di atas merupakan **diagnostik kandidat drift**, **BUKAN bukti inkonsistensi atau kerusakan data**.
Sebagai contoh, pada kasus 10 Nos dengan UOM Pack (faktor 12) di mana `custom_qty_after = 0.833`, perhitungan `0.833 × 12 = 9.996` menghasilkan selisih `abs(10 − 9.996) = 0.004 > 0`. Baris tersebut akan muncul pada hasil query di atas, padahal baris tersebut **100% konsisten** di bawah aturan konsistensi baru (karena `round(10 / 12, 3) == 0.833`).

### 4.2 Perbandingan Konsistensi Presisi (Precision-Consistency Comparison)

Untuk membedakan artefak pembulatan normal dari inkonsistensi yang sesungguhnya, gunakan query presisi berikut:

```sql
select
  p.name as reconciliation,
  i.idx as row_idx,
  i.item_code,
  i.qty as native_qty,
  i.custom_qty_after as counted_qty_uom,
  i.custom_conversion_factor as factor,
  round(i.qty / i.custom_conversion_factor, 3) as derived_qty_after,
  round(i.custom_qty_after * i.custom_conversion_factor, 6) as converted_native_qty,
  abs(i.qty - i.custom_qty_after * i.custom_conversion_factor) as raw_diff
from `tabStock Reconciliation Item` i
join `tabStock Reconciliation` p on p.name = i.parent
where p.docstatus = 0
  and i.custom_uom is not null
  and i.custom_conversion_factor > 0
  and round(i.qty / i.custom_conversion_factor, 3) != round(i.custom_qty_after, 3);
```

- Baris yang muncul pada query 4.2 adalah baris yang **benar-benar memiliki anomali/inkonsistensi** antara kuantitas native dan kuantitas per-UOM (melebihi batas pembulatan 3 desimal).
- Baris yang muncul di query 4.1 tetapi tidak muncul di query 4.2 adalah baris sehat yang terjaga oleh aturan konsistensi round-trip.

---

## 5. Batasan Verifikasi (Limits & Known Boundaries)

1. **Tidak Ada Akses Live Stack / Docker:** Sesuai batasan global repositori, tidak ada instalasi, migrasi, atau eksekusi perintah terhadap stack Docker `erpnext-dev` atau `erpnext-prod`.
2. **Skrip Gate Tidak Dijalankan Langsung:** Skrip integrasi database live (`tests/w23_gate.py`, `tests/w25_gate.py`, `tests/w31_gate.py`) hanya diverifikasi lulus kompilasi Python (`python3 -m py_compile`), tidak dieksekusi terhadap database MariaDB aktif.
3. **pos_next Belum Diuji di Runtime:** Perubahan pos_next (pencegahan blind-count leak dan pembersihan duplikasi matematika) didokumentasikan di `HANDOFF_POS_NEXT_SR_UOM.md` dan diverifikasi via mock MRO di `test_sr_class.py`. Pengujian integrasi runtime penuh antar-aplikasi membutuhkan deployment bersamaan.
4. **Keterbatasan Kompatibilitas `ignore_validate=True`:** Karena konversi dipindahkan ke dalam class extension method `validate_posting_time()`, pemanggilan `doc.save(ignore_validate=True)` akan membypass proses validasi dan konversi UOM tidak akan dieksekusi. Tidak ada pemanggil dalam codebase yang menggunakan flag ini untuk SR, namun ini merupakan limitasi kompatibilitas arsitektural.
5. **Status Review:** Seluruh task implementasi (Tasks 1–5) telah disetujui (approved) pada review masing-masing. Gelombang perbaikan final (F1–F4) dan residual fix (F1 reserved stock + F2 native zero) telah rampung dan diverifikasi pada host-only test suite dengan 66 tests lolos (19 Node.js tests). Tahap selanjutnya adalah whole-change review komprehensif oleh controller terhadap seluruh branch sebelum pengajuan commit/merge.

---

## 6. Verifikasi Final Fix Wave & Residual Fixes (F1–F4)

| Finding | Masalah | Resolusi | Bukti Pengujian |
|---|---|---|---|
| **F1 (P1)** | `sr_uom.ledger_qty` mengembalikan seluruh stok gudang untuk baris ber-batch | `sr_uom.ledger_qty` diperluas dengan argumen opsional `batch_no`, mendelegasikan ke `erpnext.stock.doctype.batch.batch.get_batch_qty` dengan timestamp posting bila `batch_no` terisi. Cache key `(item, warehouse, batch)`. Diteruskan dari `apply_to_doc`, endpoint `compute_row`, dan client script snapshot/args/events. | `test_ledger_qty_with_batches`, `test_apply_to_doc_two_batches_same_item_warehouse`, `test_endpoint_batch_qty`, Node test `F1: batch_no is threaded` |
| **F1 Residual** | `sr_uom.ledger_qty` batch balance bisa terpotong reserved stock jika flag diabaikan | Meneruskan `ignore_reserved_stock=True` ke `get_batch_qty` sehingga saldo fisik (24) dipertahankan meski terdapat reservasi (12) | `test_ledger_qty_batch_ignores_reserved_stock`, assertion `ignore_reserved_stock` di `test_ledger_qty_with_batches` |
| **F2 (P1)** | Client edit `custom_uom` mengirim display rate lama | Client script `custom_uom` mengirim opsi `omit_rate_per_uom: true` sehingga server menurunkan kembali display rate dari native rate | Node test `F2: custom_uom change omits rate_per_uom` |
| **F2 Residual** | Client script `valuation_rate || current_valuation_rate` kehilangan nilai eksplisit 0 | Menggunakan fallback empty-only `resolve_val_rate` (hanya jika null/undefined/empty string, bukan 0) secara konsisten di snapshot, request args, dan response checks | Node test `F2: UOM transition with native 0 valuation_rate, allow_zero=1, current_valuation_rate=10 retains 0` |
| **F3 (P1)** | Grid edit `item_code` mempertahankan metadata custom item lama | Client script `item_code` mereset metadata custom di dalam guard `syncing_rows`, meng-invalidate request ID lama, dan menunggu `after_ajax` sebelum seeding UOM default yang diproteksi dari respons out-of-order | Node test `F3: item change resets obsolete custom metadata`, `F3: out-of-order default lookup` |
| **F4 (P2)** | Import baris hitung dengan rate eksplisit tanpa perubahan qty mengalami drift pembulatan (9.996) | `sr_import.validate_count_rows` meneruskan `qty=current` ledger ke `compute_row` sehingga aturan konsistensi mempertahankan nilai integer qty ledger asli | `test_import_explicit_rate_only_preserves_ledger_qty` |
