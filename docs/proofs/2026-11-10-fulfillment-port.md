# Bukti port fulfillment + verifikasi dev

Tanggal: 2026-11-10. Sumber: `callmevan1120/warehouse-app@dc42c7f` → `main` lokal.

## Perintah + hasil

1. Rebuild: `docker/erp rebuild dev` → exit 0, kontainer di-recreate, backend healthy.
2. Migrate: `docker/erp bench dev --site dev.localhost migrate` → sukses;
   DocType `Warehouse Fulfillment Run/Profile/Request Key/Run Item/Run Allocation`
   terdaftar; Custom Field `custom_count_confirmation` (SR lokal),
   `custom_fulfillment_run/group` (PL), `custom_fulfillment_category` (Item),
   `custom_fulfillment_run` + koli (DN) ada.
3. Gate fulfillment di site sekali-pakai `fulfillment.localhost` (dibuat khusus,
   dihapus setelahnya — kontrak `guard_site` remote menolak jalan di site produksi):
   - `w49_r0_gate` → ok true (rantai native PL→DN→packing→submit→cleanup).
   - `w54_schema_gate`, `w49_f2_schema_gate`, `w49_f1_readonly_gate`,
     `w49_f1_profile_gate`, `w49_f2_profile_gate`, `w49_f2_settings_gate` → ok true.
   - `w49_f2_gate` (generate) → ok true.
   - `w54_f3_f4_gate` → 1 check FAIL: `profile_print_formats` mengharapkan tepat
     4 kunci `workspace["profile"]`, implementasi (+ frontend) memakai 8 kunci
     (tambahan parent warehouse, item exceptions, enable packing slip). Cacat
     bawaan remote (commit `a17d9d4` membuat keduanya bersamaan) — bukan regresi
     port; tidak diperbaiki (di luar scope, kontrak test remote).
4. Gate SR lokal di `dev.localhost` (cek regresi port):
   - `w32_gate` → ok true. Frontend `node --test tests/*.test.mjs` → 14/14 hijau.
   - `w23/w25/w31_gate` → merah PRA-EKSIS (sebab: validasi proteksi konfirmasi /
     serial-bundle dari `d171a3b`/`810dacc` yang tidak dilengkapi token di skenario
     gate; bukti bukan port: `git diff ced3814 HEAD` kosong di seluruh area
     eksekusi gate). Tidak diperbaiki dalam port ini.
5. E2E `dev.localhost` (dokumen draft lalu hapus, semua bertag `ZZTEST-E2E-FUL-*`):
   fixture Item + Stock Entry + Customer + SO (submit) + profil sementara →
   `generate_fulfillment_run` 2× key sama → run SAMA (`reused: true`, idempotency
   terbukti) → workspace PLANNING → `save_picking` → PICKING → `complete_picking`
   (auto-submit PL, docstatus 1) → `create_delivery_note` draft → print HTML
   (kosong — wajar, tanpa packing slip karena pack tidak dijalankan) →
   hapus DN + PL + Run + Request Key + SO (cancel dulu) + profil + Customer +
   SE (cancel) + Item → residu NOL (verifikasi query `ZZTEST-E2E%` kosong,
   jumlah SO produksi kembali 475). Pelajaran E2E: app `item_group_series`
   menimpa `item_code` dengan nomor seri (pakai `doc.name` aktual);
   `generate` butuh SO submitted + token `modified`; `complete_picking`
   otomatis submit PL (tanpa `submit_pick_list` terpisah);
   `create_delivery_note` mengembalikan workspace (`["delivery_note"]["name"]`).

## Temuan

- W54 `profile_print_formats`: gate usang milik remote (lihat di atas).
- W23/W25/W31 merah pra-eksis di `main` (proteksi konfirmasi vs gate lama).
- Prod `erp.localhost:8090` tidak disentuh.
