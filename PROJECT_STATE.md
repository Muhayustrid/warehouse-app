# PROJECT_STATE — warehouse_app

Compressed 2026-11-06. Full prior history: `git show 810dacc:PROJECT_STATE.md`, TASKS.md (W1–W46),
W49 evidence: docs/proofs/2026-11-05-sr-counted-input-protection.md.

## CURRENT (2026-11-06) — W49 SR count protection: committed 810dacc (not pushed/deployed), NOT production-ready
- In progress (uncommitted): TDD fixes for review findings H1, H2, M4, M5 (scope: warehouse_app only; H3/POSNext out of scope).
  - H2: stock UOM/factor must come from Item master, never row.stock_uom payload.
  - H1: reject custom_qty_after not exactly storable at its field precision (no silent rounding, no global precision change).
  - M4: Undo leaves stale typed snapshot -> Save blocked (keep in-flight/no-blur protection).
  - M5: Qty/rate lock not reapplied after import fill_grid / custom->serial item change.
  - Status: ALL FOUR FIXED, committed after 810dacc (user-approved 2026-11-06; not pushed/deployed). See below.
- Open after this round: H3 POSNext incompatible (adapter needed; handoff HANDOFF_POS_NEXT_SR_COUNT_PROTECTION.md, prompt in section 10).
- User decision 2026-11-06: POSNext re-confirms (confirm_count_rows) in submit_opname initial state after stamping posting; HQ approval never re-confirms.
- Blockers before deploy: POSNext adapter + paired release, cloud recheck (cloud Frappe 16.55.2 / ERPNext 16.53.0 vs srcount 16.52.0/16.51.1), SR Client/Server Script backup (migrate disables W23/W26), deploy approval.
- Rollback rehearsal DONE on srcount (cc0634b <-> 810dacc): clean, idempotent, no stock doc mutated; drafts made while rolled back need re-confirm after roll-forward. Not rehearsed: image deploy, browser asset cache, cloud.

## Fix round 2026-11-06 (H1/H2/M4/M5) — done, committed
- TDD RED->GREEN per finding (unit, node, and integration test_17/18 RED against 810dacc sr_uom.py). Evidence table in proof "Fix round H1/H2/M4/M5".
- Results: pytest 120 + 41 subtests; node 81/81; srcount integration 18/18 OK, residue 0; browser M4/M5 PASS (draft 00292 created+deleted).
- Final Opus review: H1/H2/M5 CLOSED; M4 PARTIAL (same-value retype) -> fixed + RED/GREEN + browser recheck; no further review round.
- Helper contract: signatures unchanged; stricter behaviour (master stock UOM, After precision) recorded in HANDOFF 3b.
- OPEN low: Desk Float control rounds typed After to field precision (srcount: 2) before the server check; row is rejected with an indirect message, nothing saved. H1 message reached via API/import.

## Runtime and fixtures (srcount)
- Stack erpnext-srcount: srcount.localhost:8003, DB :3310, image erpnext16:local; only warehouse_app bind-mounted (docker/compose.srcount.mount.yaml) -> git switch + migrate + restart = live code. POSNext 2.16.0 baked.
- Controller MRO: ExtendedCustomStockReconciliation -> warehouse_app StockReconciliationUOM -> pos_next CustomStockReconciliation -> ERPNext. doctype_js loads both apps' stock_reconciliation.js.
- Keep fixtures: company `_Test SR Count Co`, items W49E2E-PACK (Pcs, Pack=6)/-SER, MAT-STE-2026-00185, MAT-RECO-2026-00186/187/197/198, 00235-00244, 00254, 00264-00272, warehouse "W49 Repro - _SCC". Bin W49E2E-PACK @ Stores = 6336 @1000. DB backup 20261106_043819.
- DO NOT touch: 00268/00272 (submitted WITHOUT ledger = bench execute retry-without-rollback artifact, Frappe 16.52), drafts 00267/00269-00271 (hold POSNext open-opname guard on 4 _SCC warehouses).
- Test rule: never assert stock via `bench execute` on raising functions; use run-tests (rollback) or explicit try/rollback; new isolated fixtures only.

## Test commands
- Node: `SR_SCRIPT=warehouse_app/public/js/stock_reconciliation.js NATIVE_SR_SCRIPT=warehouse_app/tests/fixtures/native_stock_reconciliation.js node --test warehouse_app/tests/sr_client_script.test.mjs`
- Unit: `python3 -m pytest warehouse_app/tests/test_sr_client_script.py warehouse_app/tests/test_sr_uom.py warehouse_app/tests/test_sr_endpoints.py warehouse_app/tests/test_sr_import_uom.py warehouse_app/tests/test_sr_access.py warehouse_app/tests/test_sr_class.py warehouse_app/tests/test_sr_install.py warehouse_app/tests/test_inventory_company.py -q`
- Integration: `docker exec -w /home/frappe/frappe-bench/sites erpnext-srcount-backend-1 bash -lc 'bench --site srcount.localhost run-tests --lightmode --module warehouse_app.tests.test_sr_count_integration'`

## W49 history (condensed; details in proof)
- Rounds 1-6 (2026-11-05): implementation + 6 review/fix rounds; final round 6: node 72/72, pytest 112, integration 16/16, browser 1056 Pack -> 6336 Pcs Save/reload/Submit/reload + ledger (00238, 00241, 00244).
- Commit 810dacc (user-approved). Opus full review: 0 critical, 3 high (H1, H2, H3), 2 medium (M4, M5).
- Spec rev3.1: fingerprint posting ctx = "now" when set_posting_time=0, exact date+time when 1; toggle invalidates.
- Server adapter simulation: without adapter POSNext save rejected; with adapter OK, 1056/6336 unchanged.

## Earlier work (all DONE; details in TASKS.md / git history)
- W48/W47 (2026-10-12): SPA Requests dialog close fix, floatbar sizing; not pushed to frappe.cloud.
- W42-W46 (2026-10-10): Inventory/Requests responsive + filter changes. Incident: stack 1oktober2026 site went BLANK (volume empty) — not production data.
- W41 (2026-10-09): full SPA /gudang redesign (no Tailwind/frappe-ui; server-side pagination). W40: Inventory page (Stock Cards, Movements, export, recalculate).
- W39: grid edit-row dark-screen fix (idempotent column hide). W38/W37/W36: Box columns removed from report/SPA.
- W33-W35: SPA /gudang live; W34 retired classic Desk UI (only SPA entry). Rollback W34: `git revert 2032bc2` + migrate.
- W21-W32: Default Inventory UOM, SE rate per UOM (W21/W32), SR in inventory UOM (W23/W23b), Import Stock Count on SR form (W25/W26), Pick List + batch UOM (W31), native roles SM/SU (W24).
- W9-W20: handover request board, settings, group requests (W19), sidebar/logo/FC readiness.
- Parked: Item Custom DocPerm only "POSNext Cashier" (Stock User/Manager 403 on Item) — user decision; 403 Stock Settings modal for pure Stock User on SE.

## Operational lessons (keep)
- Changing hooks.py requires `bench clear-cache`. Restart web workers after Python changes (bench execute runs a fresh process and misleads).
- `bench execute` swallows/retries exceptions and commits — use run-tests or try/rollback for stock tests.
- Frappe saves 0.0 for never-filled custom Float: custom row marker = custom_uom set, not custom_qty_after.
- Cleanup must be scoped by exact fixture names (no LIKE '_T_%' wildcards).
- This file is tracked in git (pre-existing); kept, not untracked.
