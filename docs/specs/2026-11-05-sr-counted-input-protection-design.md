# Stock Reconciliation: input tetap, konversi satu arah

Tanggal: 2026-11-05  
Revisi: 3.1 — revisi3 + klarifikasi posting-context (§3, keputusan pengguna 2026-11-05)  
Status: Spesifikasi selesai ditulis; implementasi dan deployment belum disetujui  
App: `warehouse_app` · Produksi: CLOUD `https://ropi.co.id`

## 1. Hasil yang harus dicapai

**“Input apa, setelah submit harus tetap itu.”**

Input1056Pack dengan master6Pcs/Pack menghasilkan target6336Pcs. After/UOM tetap sama setelah Save/reload dan Submit/reload. Refresh saldo tidak boleh mengubahnya menjadi1051Pack/6306Pcs. Jika proses tidak dapat menjaga input, hentikan dengan pesan jelas.

Dokumen, ledger, valuasi, jurnal, permissions, workflow, reservation, serial/batch dan submit/cancel tetap native ERPNext beserta kontrak app terpasang. Tidak mengubah core, dependency, stok historis, negative-stock setting, atau membuat transaksi penyeimbang. Tidak menyentuh `Backup SIte Production/`. Deployment, konfigurasi produksi, operasi stok, commit dan push memerlukan persetujuan terpisah.

## 2. Acuan dan bukti

Acuan struktur: Stock Entry native lokal memisahkan `qty`/`uom` sebagai input, `conversion_factor`, `transfer_qty` sebagai hasil, serta `actual_qty` sebagai saldo pembanding. Server `set_transfer_qty()` menghitung hasil dari input; callback saldo warehouse yang diperiksa tidak mengganti Qty transaksi dengan saldo.

SR meniru **pemisahan tanggung jawab**, bukan menyalin controller Stock Entry. Stock Entry mencatat pergerakan; SR menetapkan saldo absolut. Larangan Qty0 Stock Entry tidak diterapkan ke hitungan fisik SR.

Bukti investigasi2026-11-05:

- Saat dicek, source repo warehouse_app dan `origin/main` sama: `cc0634b`.
- CLOUD Frappe16.55.2/ERPNext16.53.0; exact revision Python/hooks custom cloud belum terverifikasi. Scratch lokal16.52.0/16.51.1 bukan bukti kesetaraan cloud.
- Native JS cloud + W23 direproduksi bersama: request saldo dimulai, pengguna mengetik1056, callback sintetis6306 terlambat, handler W23 mengubah After menjadi1051.
- Ini membuktikan mekanisme penimpaan, bukan input/urutan request historis dokumen cancelled RECO-JURI-261105001.
- Server Script aktif `sr_auto_populate_before_after` membaca Bin terkini untuk backdated Before/difference dan memakai truthiness untuk nol. W26 import tetap diperlukan.
- Baseline44 unit test lulus; integration ledger baru belum dijalankan. Stock Entry belum dibuktikan identik dengan source cloud atau bebas race.

Bukti rinci: `/Users/rotiropi/AutoFetchErestoToERPNext/docs/2026-11-05-stock-reconciliation-qty-investigation.md`.

## 3. Desain inti

| Tanggung jawab | Field SR |
|---|---|
| Input hitungan pengguna | `custom_qty_after` + `custom_uom` |
| Faktor master Item | `custom_conversion_factor` |
| Target absolut dalam Stock UOM | native `qty` |
| Saldo historis pembanding | `current_qty`, `custom_qty_before` |

Satu arah: **After × faktor master → native Qty**. Tidak ada handler native Qty → After pada baris custom. Server menghitung ulang target sebelum proses native; bukan mempercayai hasil browser. Saldo hanya memperbarui Before/selisih sesuai izin.

Gunakan `sr_uom.py` yang sudah ada dan helper UOM/precision ERPNext yang kontraknya cocok. Jangan membuat framework intent, mesin stok, controller alternatif, atau menyalin matematika ke banyak tempat.

### Belum dihitung bukan nol

After baris custom baru tidak di-prefill dari saldo. Fetch Items menyiapkan item/gudang/UOM dan Before, tetapi pengguna tetap mengisi atau mengonfirmasi After. Saldo10Pcs/Pack12 tidak boleh otomatis menjadi hitungan0.833Pack/target9.996Pcs. Baris custom belum dihitung memblokir Save/Submit; pengguna dapat menghapus baris yang tidak dihitung sesuai aturan draft native.

Tambahkan satu field internal `custom_count_confirmation` bertipe Data, hidden, no-copy. Nilainya fingerprint deterministik konteks yang dikonfirmasi: company, item, warehouse, posting date/time, UOM, faktor master dan batch bila relevan. Kehadirannya membedakan hitungan0 eksplisit dari default Float0; kecocokannya mendeteksi konteks yang berubah. Fingerprint bukan rahasia, otorisasi, atau bukti forensik input.

Tidak ada `custom_count_intent`, JSON context, duplikasi After/native Qty, riwayat request, atau state machine persisten. Form/import mengisi penanda melalui hasil verifikasi konversi yang sudah ada; server memeriksa ulang. Format fingerprint dan canonicalization ditetapkan satu kali di shared module dan diuji, bukan dibuat berbeda per caller.

### Konteks posting dalam fingerprint (klarifikasi pengguna 2026-11-05)

Native `validate_posting_time()` mengganti posting date/time ke saat ini pada setiap Save/Submit bila `set_posting_time=0` (default SR). Karena itu fingerprint memuat **mode posting**, bukan selalu timestamp:

1. `set_posting_time=0` → `posting_context = "now"`. Timestamp otomatis yang berubah pada Save/Submit (termasuk melewati tengah malam) tidak menginvalidasi konfirmasi.
2. `set_posting_time=1` → tanggal+jam eksplisit, dinormalisasi dengan kontrak Frappe terpasang (`getdate`/`get_time`). Perubahan tanggal atau jam (hari yang sama sekalipun) menginvalidasi konfirmasi. Fingerprint konsisten setelah reload.
3. Toggle `set_posting_time` 0↔1 menginvalidasi konfirmasi. Flag tidak dinyalakan otomatis dan timestamp native tidak diubah.
4. Token `"now"` hanya untuk validitas konfirmasi. Query saldo Before, konversi/lifecycle native dan bukti ledger memakai posting_date/posting_time aktual setelah native `validate_posting_time()`; tidak ada cache saldo lintas timestamp.
5. Mode `"now"` berarti target hitungan diterapkan pada waktu posting aktual, bukan snapshot saat mulai menghitung. After/UOM dan target tidak disesuaikan karena transaksi di antara Save dan Submit. Makna ini ditampilkan jelas di form (indikator/teks), tanpa dialog tambahan pada setiap Save.

Test wajib: Save→Submit mode now pada waktu berbeda (termasuk lintas tengah malam) berhasil dengan After/target tetap; Before memakai timestamp aktual tiap proses; mode explicit mendeteksi perubahan jam pada hari yang sama; toggle mode membatalkan konfirmasi; transaksi di antara Save/Submit tidak menimpa hitungan; fingerprint explicit konsisten setelah reload.

### Perubahan konteks

Perubahan item, warehouse, company, UOM, batch, tanggal/jam posting atau faktor master tidak boleh menafsir ulang angka diam-diam. Pertahankan angka yang terlihat, invalidasi konfirmasi, dan blokir Save/Submit sampai pengguna mengonfirmasi hitungan untuk konteks baru. Jangan menyalakan `set_posting_time` otomatis.

Server membandingkan konfirmasi dengan konteks dan faktor aktual. Mengosongkan UOM/penanda pada counted row tersimpan bukan jalur silent fallback ke native; periksa dokumen sebelum save dan berikan error yang dapat ditindaklanjuti. Penghapusan baris draft normal tetap mengikuti native permissions/workflow.

## 4. Perlindungan form dan async

Satu file app `public/js/stock_reconciliation.js`, dimuat melalui `doctype_js`, menggantikan W23 dan W26. Pertahankan impor, role gate dan presentasi grid yang idempoten. Native Qty pada custom row adalah hasil, bukan input kedua.

Adaptasi fungsi form native pengambil saldo hanya pada instance SR. Untuk custom rows, batasi penulisan callback **sebelum** callback mengganti Qty; jangan membiarkan After tertimpa lalu memulihkannya. Native-only tetap memakai kontrak native. Tidak patch global `frappe.call`, core, scan_mode global, atau seluruh controller.

Setiap respons memeriksa identitas form/baris, generation, konteks dan docstatus sebelum menulis. Respons basi/terbalik, baris dihapus/diganti, pindah form serta submitted/cancelled tidak boleh mengubah data. Error ditampilkan tanpa mengosongkan After/UOM. Load-order dan handler registration harus dibuktikan pada runtime target; jika tidak cocok, aktivasi diblokir.

Snapshot input browser diambil saat pengguna mengetik, bukan saat respons saldo datang. Save/Submit mem-flush editor aktif, memeriksa snapshot tersebut dan menunggu verifikasi faktor/perhitungan relevan atau berhenti dengan pesan jelas. Perubahan input selama menunggu menginvalidasi attempt. Jangan hanya membandingkan dua field yang mungkin sudah sama-sama tertimpa.

Perubahan saldo akibat transaksi lain tidak mengubah input/target. Refresh submitted/cancelled hanya presentasi, tidak menulis field atau memasang defaults. Scan custom yang belum memiliki kontrak input teruji diblokir dengan pesan memakai flow native; native-only scan tetap native.

## 5. Server dan kompatibilitas

- Validasi numeric finite, UOM sah dan faktor positif sesuai master Item; tidak percaya faktor request atau fallback1 diam-diam.
- Ikuti precision metadata dan integer-UOM native. Tolak input/hasil yang tidak dapat direpresentasikan, dengan nilai dan alasan; tidak hardcode3-desimal/faktor6 atau mengubah global precision.
- After0 sah. Rate kosong tidak meminta revaluasi; rate0 mengikuti `allow_zero_valuation_rate` dan validasi native. Refresh saldo tidak mengganti rate eksplisit pengguna.
- Pertahankan class extension yang ada agar tidak mengambil slot override POSNext. Konversi/validasi setelah posting time final dan sebelum bundle/no-change filtering hanya setelah MRO/order runtime diverifikasi. Timestamp yang direset native sehingga konfirmasi tidak cocok harus menghasilkan error, bukan konfirmasi otomatis.
- Before memakai ledger native pada timestamp final, termasuk dimensions/batch/order/exclusion voucher sendiri sesuai kontrak terpasang. Jangan memakai Bin terkini untuk saldo historis. Native tetap pemilik valuation/current amounts/differences/ledger.
- Pertahankan blind count, field filtering, valuation permission, open-opname guard dan workflow POSNext. Konversi murni tidak mensyaratkan hak membaca saldo. Jangan membocorkan saldo/rate melalui UI, API, error, print atau penanda konfirmasi.
- Native-only rows tetap native dan tidak diberi custom UOM pada refresh/reload. Mixed rows wajib diuji.
- Draft custom lama tanpa konfirmasi ditampilkan apa adanya; minta pengguna mengonfirmasi After/UOM/konteks sebelum Save/Submit. Tidak menebak riwayat input dan tidak bulk rewrite. Submitted/cancelled tidak diubah.
- Native serial/bundle tetap native. Direct batch custom didukung setelah konversi sebelum bundle dan saldo/target batch historis teruji. Kombinasi custom serial/bundle yang belum aman diblokir jelas, bukan silent skip. Import serial/batch tetap ditolak sesuai kontrak lama.

## 6. Import, Fetch Items dan API

W26 download/upload XLSX/CSV, parser/limit, permissions, row errors dan konfirmasi replace tetap tersedia. Template membawa tanggal/jam posting dokumen dan saldo historis sesuai izin; Counted tetap kosong sampai diisi.

Upload count eksplisit termasuk0 menghasilkan penanda konfirmasi. Capture konteks saat upload; tolak respons/konfirmasi replace yang sudah basi sebelum mengganti grid. Pengguna tetap review dan Save native.

Hilangkan matched-strip berbasis toleransi0.0005. No-op hanya jika quantity dan valuation efektif cocok dengan target tervalidasi pada precision native. Semua matched boleh menghasilkan no-op terverifikasi; jangan memaksa pergerakan agar baris tetap ada.

Native-only API payload tidak berubah. Custom API memakai After/UOM dan penanda konfirmasi dari endpoint konversi yang sudah ada; bukan endpoint save/submit baru. Inventarisasi caller sebelum mengubah kontrak. Caller lama yang belum dapat membedakan default0 dari hitungan eksplisit menerima error migrasi jelas, bukan tebakan. Caller yang diperlukan harus diperbarui dan diuji sebelum cutover; perubahan lintas app membutuhkan scope/persetujuan terpisah. API tetap mengikuti permissions/workflow native.

## 7. Scope implementasi

| Berkas | Tujuan |
|---|---|
| `warehouse_app/public/js/stock_reconciliation.js` | Pemilik form/import; input satu arah, guard callback dan Save |
| `warehouse_app/hooks.py` | Memuat JS SR; mempertahankan hook lain |
| `warehouse_app/sr_uom.py` | Shared konversi, master/precision, konfirmasi konteks |
| `warehouse_app/overrides/stock_reconciliation.py` | Validasi pada lifecycle native |
| `warehouse_app/warehouse_app/stock_reconciliation.py` | Fetch tanpa After prefill, endpoint konversi |
| `warehouse_app/warehouse_app/sr_import.py` | Konversi sama, historical template, stale-upload guard, no-op |
| `warehouse_app/upgrade.py` | Field penanda, retirement script idempoten, hentikan producer lama |
| `warehouse_app/tests/`, `docs/proofs/` | Regresi otomatis, integration/browser dan bukti nyata |

Tidak mengubah Stock Entry, Pick List, SPA unrelated, core atau dependency. Desain2026-11-03 rounded-equality dan reverse-conversion tidak berlaku untuk hitungan eksplisit. Revisi1–2 intent/context JSON digantikan spesifikasi ini.

## 8. Pengujian wajib

1. Native+app JS dengan dispatcher/Promise: request pending → pengguna1056Pack → callback6306 terlambat. After1056 dan target6336 tetap. Test baru gagal terhadap kode lama sebelum fix.
2. Input→Save/reload→Submit/reload→ledger efektif pada timestamp: After/UOM tetap, native Qty sesuai target. Mutasi fixture setelah timestamp boleh mengubah saldo hari ini.
3. Nol/kosong/default0, fractional qty, faktor non-integer, variasi metadata precision dan integer stock UOM.
4. Fetch10Pcs/Pack12 tidak menciptakan hitungan0.833/target9.996; input0 dan input bernilai sama dengan default tetap dikenali eksplisit.
5. Respons saldo/faktor/UOM terlambat/terbalik; error, row delete/re-add, pindah form; ketik lalu langsung Save/Submit.
6. Perubahan seluruh konteks dan faktor master antara Save/Submit memerlukan konfirmasi, tidak mengganti angka.
7. Transaksi fixture lain memperbarui Before tanpa mengganti hitungan; native reservation/future-stock checks tetap bekerja.
8. Import/API, legacy/mixed/native-only, workflow/background submission, permissions dan blind count.
9. Rate kosong/explicit/zero; native no-change filtering dibuktikan lewat saldo **dan valuation** efektif, bukan row count. All-matched tidak dipaksa posting.
10. Serial/batch sesuai dukungan; refresh submitted/cancelled tidak memutasi dokumen.
11. Fresh install/migrate dua kali, duplicate handler/script retirement failure, serta rehearsal rollback.

Integration hanya di site terisolasi dengan identitas terverifikasi; jangan memakai dev/prod berisi data produksi sebagai sandbox atau menjalankan gate cleanup agresif di sana. Bukti mencakup saved/submitted values, effective SLE qty/rate, stock value, GL balance bila relevan, repost selesai/tidak gagal, serta fixture isolation/cleanup. Test gagal/skipped/unsupported dilaporkan eksplisit.

## 9. Deployment dan rollback

Sebelum deployment: verifikasi revision Python/hooks/MRO cloud, kontrak helper/load-order, runtime uji setara target, compatibility caller/draft dan seluruh test. Tanpa bukti tersebut, kesiapan produksi diblokir.

Audit seluruh script SR dan duplicate marker/producer. Backup konfigurasi lengkap serta enabled state secara terlindungi. Freeze penulisan/submission SR dengan mekanisme operasional yang disetujui; jangan memengaruhi transaksi lain di luar scope.

Deploy artifact teruji, migrate, clear cache/restart sesuai kebutuhan. Disable, bukan delete: W23 `warehouse-app-w23-stock-reconciliation-uom`, W26 `warehouse-app-w26-stock-count-import`, Server Script `sr_auto_populate_before_after`. Hentikan producer W23/W26 di installer; migrate berikutnya tidak mengaktifkan ulang. Jika script konflik/handler ganda masih ada atau retirement gagal, jangan buka freeze. Reload form lama dan verifikasi asset revision serta handler tunggal. Smoke produksi read-only kecuali transaksi disetujui terpisah.

Rollback dalam freeze memulihkan artifact sebelumnya **bersama** state script dari backup, cache/restart dan verifikasi handler tunggal. Jangan mengaktifkan script lama selama JS baru masih dilayani. Field additive tidak dihapus. Draft baru ditahan dari edit versi lama bila kompatibilitas belum terbukti. Rollback kode tidak membatalkan transaksi submitted; recovery transaksi memerlukan persetujuan baru.

## 10. Status dan tahap berikutnya

Spesifikasi final selesai ditulis; belum ada implementasi, integration ledger baru, deployment atau stock correction. Blocker kesiapan produksi tetap revision Python/hooks cloud, kesetaraan runtime uji dan compatibility caller/POSNext/load-order.

Setelah pengguna menyetujui spesifikasi ini, tulis rencana implementasi TDD dengan urutan test dan verifikasi kontrak runtime. Jangan commit/push atau deploy otomatis.
