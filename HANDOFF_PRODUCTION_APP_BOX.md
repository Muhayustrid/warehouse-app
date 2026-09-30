# HANDOFF ke production_app — Longgarkan kontrak serah terima: request TANPA box (pendamping W30 warehouse_app)

> Dokumen ini adalah prompt siap-pakai untuk AI agent production_app (repo `Muhayustrid/production-app`).
> Salin seluruh isi bagian "PROMPT" di bawah ke sesi agent tersebut.

---

## PROMPT

### Konteks

Keputusan user (2026-09-30): **input Box (kg + alokasi jumlah) dihapus dari alur request serah terima**. Papan gudang (warehouse_app, Page `gudang_request`) tidak lagi mengirim argumen box sama sekali — qty request otomatis = hasil penuh tiap Work Order (endpoint memang selalu menegakkan `Σ qty == expected`, jadi inputan lama memang redundan untuk qty; yang hilang hanyalah penimbangan kg).

Status kedua app:

- **warehouse_app**: kode dialog baru (tanpa input box, payload `{work_order}` / `{work_orders}` saja) SUDAH di-commit di repo warehouse_app (branch main, W30) tetapi **sengaja BELUM di-deploy ke container** — menunggu kontrak baru di production_app.
- **production_app**: belum berubah. Saat ini `create_request` menolak panggilan tanpa kg (dengan `box_1` absen/None, call mati lebih awal di `_finite_kg`, `api/handover.py:1130-1133` — "Box 1 harus angka kg yang valid"; `:1187` untuk box_1 numerik <= 0) dan `create_group_request` mewajibkan `boxes` dengan kg > 0 per baris (`api/handover.py:1468-1481`). Kalau warehouse_app di-deploy sekarang, papan gagal.

### Tugas di production_app

Ubah dua endpoint di `production_app/api/handover.py` agar menerima panggilan TANPA argumen box. **Longgarkan kontrak, bukan ganti signature** — caller lama dengan argumen box tetap berfungsi persis seperti sekarang (prinsip R11).

1. **`create_request(work_order, box_1=None, ...)`** — mode qty-only:
   - Trigger mode: `box_1` datang sebagai `None` (tidak dikirim caller).
   - Skip `_validate_box_allocation` (validasi kg/all-or-nothing) sepenuhnya.
   - Qty = hasil penuh: `amount = flt(wo.produced_qty)`, `expected = _expected_unit_count(wo, lot, amount)` — server tetap otoritatif, jangan percaya angka dari client.
   - Ringkasan WO `custom_box_1..3(_qty)` ditulis **0 semua** (pakai `zero_boxes`, pola yang sudah ada di `create_group_request`) — field WO dipertahankan sebagai ringkasan historis; request baru saja tidak membawa kg.
   - Seluruh guard lain TIDAK berubah: role gate, lock WO, duplicate-request guard, lot availability, `_enforce_whole_uom`, atomicity, `_retry_on_deadlock`.
2. **`create_group_request(work_orders, boxes=None)`** — mode qty-only:
   - Trigger mode: `boxes` datang sebagai `None` (param kini opsional; jadikan default `None`, bukan string kosong).
   - Tetap buat **Handover Box Plan** dengan SATU baris child `{kg: 0, qty: expected_total}`. Alasan: pill grup + cancel grup di papan gudang bekerja lewat link `Material Request.custom_handover_box_plan` — tanpa plan, mekanisme cancel-grup dan penanda grup mati.
   - Invarian `Σ qty == Σ expected` tetap dicek (trivially true untuk mode ini, biarkan aserinya jalan).
   - `boxes` terisi → perilaku lama utuh (kg > 0 per baris, dst).
3. **Board payload** (`handover_board`): request baru membawa field box 0/None — `boxes: [b for b in (box_1, box_2, box_3) if b]` sudah otomatis kosong dan pill SPA (`v-if="c.box"` di `HandoverBoard.vue`) sudah otomatis tak tampil. Verifikasi saja, tidak perlu diubah.
4. **Jangan sentuh**: field `custom_box_1..3(_qty)` di Work Order (dipertahankan sebagai historis), field legacy `custom_box_1/2` di MR, app warehouse_app (termasuk report "Serah Terima Gudang" yang membaca `wo.custom_box_1/2/3` — kolom itu akan menampilkan 0 untuk request baru, data lama tetap utuh), dan alur produksi apa pun (`api/work_order.py`, Form Order, stage SPA — semuanya bebas box).

### Urutan deploy WAJIB

**production_app land + deploy DULU**, baru warehouse_app menyinkronkan page JS barunya. Kabari user setelah land supaya sesi warehouse_app menjalankan sync + verifikasi. (Kebalikannya = papan gudang gagal membuat request.)

### Test di production_app

- `tests/test_handover_actions.py`: tambah kasus qty-only `create_request` tanpa argumen box (MR submitted, qty = hasil penuh, ringkasan WO = 0, guard lot/duplikat tetap menolak dengan zero-write) dan `create_group_request` tanpa `boxes` (plan 1 baris kg=0 qty=total, members ter-link). Kasus legacy dgn box TIDAK boleh ada yang diubah — harus tetap hijau.
- `tests/test_handover_board.py`: payload request baru = box 0/None, `boxes` kosong, `box_plan` terisi utk grup.
- `test_handover_setup.py` + seluruh test SPA: tidak berubah.

### Penerimaan (definition of done)

1. `create_request(work_order)` via HTTP murni (tanpa param box) → 200, MR submitted Material Transfer qty = hasil penuh WO **dalam stock UOM** (row MR selalu ditulis `qty: amount, uom: stock_uom` — `handover.py` `_insert_submitted_handover_mr`; angka display UOM hanya `expected_unit_count` di response), `custom_box_1..3(_qty)` WO = 0.
2. `create_group_request(work_orders)` tanpa `boxes` → plan HBP 1 baris (kg 0, qty = total), N MR ter-link, cancel grup bekerja.
3. Panggilan legacy dgn box lengkap → hasil identik dengan perilaku lama.
4. Semua test production_app hijau (lama + baru).
5. Setelah itu (koordinasi lanjut di sesi warehouse_app, bukan di sini): sync page JS W30, gate w9/w19, E2E browser papan.

### Non-goal (keputusan terpisah, JANGAN dikerjakan sekarang)

Pensiunkan field `custom_box_1..3(_qty)` dari Work Order / hapus kolom Box di report — hanya bila kelak dipastikan penimbangan box ditinggal permanen. Sekarang cukup longgarkan kontrak.
