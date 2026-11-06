# POSNext Handoff: Stock Opname adapter for SR count protection

Date: 2026-11-06 (rev 3, replaces all earlier versions of this file)
For: a FRESH AI agent session that works only in the POSNext repository.
Execution repo: `/Users/rotiropi/ERPNext-Project/development/frappe-bench/apps/pos_next` (branch `main`, HEAD `4010494f` when written)
Contract repo (READ-ONLY for you): `/Users/rotiropi/ERPNext-Project/development/frappe-bench/apps/warehouse_app`, commit **`d171a3b`** on `main` (contains `810dacc` + the H1/H2/M4/M5 fixes). Committed, not pushed, not deployed.

## 1. What and why (read this first)

warehouse_app now protects the physical count on Stock Reconciliation (SR):
- The counted input is `custom_qty_after` in UOM `custom_uom` (e.g. 1056 Pack).
- Native `qty` is DERIVED on the server: `qty = custom_qty_after x factor`, factor from the Item master (1056 x 6 = 6336 Pcs).
- Every row with `custom_uom` must carry `custom_count_confirmation`, a fingerprint of its context. On every save/submit, `apply_to_doc` (run from SR `validate`) recomputes the fingerprint and REJECTS the doc if it is missing or differs. It never re-confirms on its own.

Today POSNext never sets the fingerprint, so **every outlet save of a custom-UOM row fails** ("Baris N (ITEM) belum dikonfirmasi..."). Your job: call warehouse_app's `confirm_count_rows(doc)` at the exact points listed in section 4. Nothing else: no new UI, no conversion math, no validator changes.

## 2. Hard rules

- Edit only the POSNext repo. Never edit warehouse_app; if its contract looks wrong, stop and report.
- Read POSNext `CLAUDE.md` and `PROJECT_STATE.md` first. The tree has ~25 unrelated dirty/untracked paths (sidebar JSON, `.agents/`, harness files, ...): do not stash, reset, clean, revert, or commit them.
- TDD: write each test first, run it, show it RED with the real failure text, then implement and show GREEN.
- Tests run ONLY on the isolated stack `erpnext-srcount` (section 6). Never on `dev.localhost` / `erp.localhost` (production data), never write to cloud `https://ropi.co.id`.
- No deploy, image rebuild, migrate, dependency, push, or commit without the user's explicit approval (commit: propose the exact message, wait).
- No `allow_negative_stock`, no cancel/amend/delete of historical stock docs, no balancing transactions, no bypass flags, no weakening of warehouse_app checks.
- Talk to the user in Indonesian; code, comments, docs in English.

## 3. The contract (verify in `warehouse_app/sr_uom.py` at `d171a3b` before coding)

Only call `confirm_count_rows(doc)`. You do not need any other helper.

`confirm_count_rows(doc) -> None`, internal Python (NOT whitelisted). It only touches rows with `custom_uom` set; native rows are untouched. For each custom row it:
1. rejects `serial_no` / `serial_and_batch_bundle` on a custom row;
2. requires `custom_qty_after` not `None`/`""` (explicit `0` is valid);
3. resolves the factor from the **Item master** (`resolve_factors` + `_master_stock_uom`; a `stock_uom` on the row is ignored);
4. rejects an After that is not exactly storable at the precision of `custom_qty_after` (`row.precision("custom_qty_after")`, 2 decimals on srcount via System Settings float_precision). Error: `Baris N (ITEM): Qty After X tidak dapat disimpan tepat pada presisi P desimal...`;
5. rejects a target qty not representable at qty precision / non-whole for whole-number stock UOMs;
6. writes `custom_conversion_factor` and `custom_count_confirmation` on the row.

It reads no stock balances or rates, so it is safe for blind-count outlet users. It throws `frappe.ValidationError` via `frappe.throw`.

The fingerprint covers exactly: `doc.company`, row `item_code`, row `warehouse`, posting context, row `custom_uom`, master factor, row `batch_no`. It does NOT cover After or qty (changing the count does not invalidate it; the helper still has to run so H1/H2 checks apply).
- Posting context: `set_posting_time = 0` -> token `"now"`; `set_posting_time = 1` -> exact `posting_date` + `posting_time`. Any change of those, or toggling the flag, invalidates.
- Consequence: call `confirm_count_rows(doc)` LAST, after company, `set_warehouse`, rows (with their `warehouse`/`batch_no`) and all posting fields are final, immediately before `doc.save()` / `doc.insert()`.

Do NOT call `warehouse_app.warehouse_app.stock_reconciliation.compute_row`: it reads stock (HQ only).

Import it lazily and guarded, the same way `_validated_rows` already imports `resolve_factors`: only when `"warehouse_app" in frappe.get_installed_apps()` and the SR Item meta has the custom fields. Without warehouse_app: skip and keep today's native stock-UOM behaviour. One tiny local helper (e.g. `_confirm_counts(doc)`) used at all call sites is fine.

## 4. Exact call sites in `pos_next/api/stock_opname.py` (line numbers at `4010494f`)

| # | Function | Line | Insert `_confirm_counts(doc)` | Why |
|---|---|---|---|---|
| A | `save_opname`, existing doc | ~740 | right before `doc.save()`, after the posting block | children rebuilt with no token |
| B | `save_opname`, new doc | ~755 | right before `doc.insert()`, after the posting block | new rows |
| C | `submit_opname`, initial state | ~813 | right before `doc.save()`, after `doc.set_posting_time = 1` | user decision 2026-11-06: outlet Submit re-confirms the final posting time |
| D | `import_opname_template`, new doc | ~1373 | right before `doc.insert()` | import also builds custom rows (`_merge_rows` carries `custom_uom`/`custom_qty_after`) |
| E | `import_opname_template`, existing target | ~1387 | right before `target.save()` | children rebuilt with no token |

Do NOT add it anywhere else:
- Never in HQ approval, `apply_workflow` for Approve, the final native submit, or the `submit_opname` returned-state path. HQ must never re-confirm. If the factor or context changed after the outlet submitted, the doc must fail clearly and HQ rejects it back.
- Never in `_payload` or any response. The token is not UI data; do not expose it, balances, or rates.
- `attach_opname_row_photo` / `attach_opname_files` insert `File` docs only; they do not save the SR. No change.

### 4b. Revise of a Rejected doc (check, do not assume)

Three paths call `apply_workflow(doc, back)` on a returned doc BEFORE the rows are rebuilt:
- `save_opname` (~730);
- `import_opname_template` (~1381);
- `submit_opname` returned-state path.

`apply_workflow` reloads the doc from DB and saves it, so warehouse_app validates the OLD stored rows with their old token.
- Normal case: the token is still valid (same context) and revise passes.
- Edge case: master factor changed while Rejected, or the doc predates this contract, so it has no token. Then revise is blocked and the outlet cannot fix its own count.

Required steps:
1. Write a RED test: a Rejected doc whose master factor changed (6 -> 12) is revised by the outlet.
2. Expected today: it fails with "tidak cocok dengan konteks" / "belum dikonfirmasi".
3. If confirmed RED, the minimal fix is `_confirm_counts(doc); doc.save()` on the still-Rejected doc right before `apply_workflow(doc, back)`, in those revise paths only.
   - This is safe because revise returns the doc to the initial state, and the outlet must Submit again, which re-confirms (site C).
   - It is not an HQ re-confirm.
   - Show it GREEN.
   - If the workflow does not allow the outlet role to save in the returned state, stop and report instead of forcing it.
4. Note: the workflow differs per site.
   - On srcount and in `stock_opname_setup.py`: `Rejected --Revise--> Draft`.
   - On dev.localhost it is `Rejected --Revise--> Approval Pending by Stock Manager`, so `_returned_states` is empty there.
   - Use the setup workflow in tests and do not hard-code state names.

## 5. TDD acceptance (each RED first, then GREEN)

Extend `pos_next/api/test_stock_opname.py` (UOM tests live in the class with `cls.uom_item = _make_test_item(uoms=[{"uom": "Pack", "conversion_factor": 12}])`, e.g. `test_uom_converts_to_native_qty`) and `pos_next/tests/test_stock_opname_override.py`. Use your own fixtures with a unique prefix, and your own warehouse.

1. **Save new (B):** 2 Pack (master 12) saves; reloaded row has After 2, UOM Pack, qty 24, factor 12, non-empty token. Explicit `0` stays 0 (qty 0). The existing `test_uom_converts_to_native_qty` must pass again; it is expected RED today.
2. **Re-save existing (A):** same count and changed count; token valid, numbers exactly as entered.
3. **Import (D, E):** template import into new and into existing draft with a Pack row; saved, token valid, qty = After x factor.
4. **Submit, no backdate (C):** posting stamped now, `set_posting_time = 1`, token matches the new posting context, workflow advances, After/qty unchanged.
5. **Submit with approved backdate (C):** backdate kept exactly; token matches it.
6. **HQ never re-confirms:** change master factor 12 -> 24 after the outlet submit; HQ Approve / final submit fails with the warehouse_app mismatch error and the token is unchanged.
7. **Final ledger:** final native submit of a valid doc posts SLE with `qty_after_transaction` = After x factor and the correct valuation. Approval states are not ledger posting; prove the final submit separately. Native rule: a warehouse with no stock and no rate cannot be submitted ("Valuation Rate required"), so use a warehouse with stock or set the rate as HQ.
8. **H1 precision:** outlet count `1.234` Pack (precision 2) -> save rejected with the "tidak dapat disimpan tepat pada presisi" message, nothing saved. POSNext must not round it. `POS/src/components/pos/StockOpnameDialog.vue` sends `Number(r.qty)` with `step="any"` (no rounding); keep it so, and make sure the dialog shows the server message.
9. **H2:** payload with `stock_uom` (or any extra field) on a row does not change the factor; POSNext still never sends `stock_uom` into SR rows.
10. **Revise (section 4b):** the RED/GREEN case above, plus normal revise still works.
11. **Blind count:** no payload, error, or serializer exposes ledger qty or rate; the outlet cannot set valuation; the adapter never calls `compute_row` (assert with a mock).
12. **No warehouse_app:** with the guard false, native stock-UOM rows still save, and custom UOM != stock UOM is still rejected as today.
13. **Regressions green:** `modified` mismatch, profile/warehouse restriction, photo requirement, one-open-opname guard, serial rows, batch rows, frozen date, the custom-workflow class (`TestStockOpnameCustomWorkflow`).
14. **Desk (manual or browser on srcount):** HQ opens an outlet-submitted SR in Desk with both form scripts loaded (`doctype_js` of pos_next and warehouse_app) and approves. Token stays valid, qty unchanged. POSNext `fill_live_differences` writes display fields directly (no `set_value`, no token change); change it only if a test proves a conflict.

## 6. Where and how to run

Stack `erpnext-srcount`: site `srcount.localhost`, http://srcount.localhost:8003, DB host port 3310, container `erpnext-srcount-backend-1`. The Admin password is in `docker/.env.srcount` (`ADMIN_PASSWORD`); never print it.
- It runs image `erpnext16:local` (Frappe 16.52.0 / ERPNext 16.51.1, POSNext 2.16.0 baked in). Only warehouse_app is bind-mounted (`docker/compose.srcount.mount.yaml`, at `d171a3b`).
- **Your POSNext edits are NOT live there.** Before running integration tests, ask the user to approve adding a pos_next bind mount to that srcount-only overlay and recreating the srcount containers. Never rebuild the shared image.
- Runner: `docker exec -w /home/frappe/frappe-bench/sites erpnext-srcount-backend-1 bash -lc 'bench --site srcount.localhost run-tests --lightmode --module pos_next.api.test_stock_opname'`. Inspect the existing test setup for the exact runner syntax first.
- **Never** assert stock results through `bench execute` on a function that can raise. Frappe 16.52 retries without rollback and commits; that produced the broken docs MAT-RECO-2026-00268/00272 (submitted without ledger). Use run-tests or an explicit try/rollback.
- srcount has the Workflow "POS Next Stock Opname" but it is INACTIVE, and no POS Profile. Tests create and activate their own fixtures and clean up only what they created, by exact name (no wildcard deletes).
- Do not touch:
  - company `_Test SR Count Co` and items `W49E2E-PACK` (Pcs, Pack = 6) / `-SER`;
  - MAT-STE-2026-00185 and MAT-RECO-2026-00186...00292;
  - warehouse `W49 Repro - _SCC`.
  Drafts 00267/00269/00270/00271 hold the one-open-opname guard on Stores/WIP/Finished Goods/Goods In Transit - _SCC, so create your own warehouse.
- Cloud runs Frappe 16.55.2 / ERPNext 16.53.0: srcount results are not cloud proof. Say so.

## 7. Release facts (not your job, but do not contradict them)

- warehouse_app `d171a3b` must never go live alone where POSNext Stock Opname is used. It needs a paired, user-approved release of both apps, an SR freeze, a backup of SR Client/Server Scripts (migrate disables W23/W26), a single-handler check, and the rollback plan in warehouse_app `docs/proofs/2026-11-05-sr-counted-input-protection.md` ("Rollback rehearsal").
- Pre-existing docs with custom rows and no token fail on their next save.
  - On dev.localhost (2026-11-06) these are `RECO-OTPameran-261009001` (Draft, 37 rows) and `RECO-TRNG-261105001` (Approval Pending, 1 row).
  - Drafts heal when the outlet re-saves (site A).
  - Approval-pending docs must be rejected and revised (section 4b).
  - List these in the report as a release item; do not modify them.

## 8. Completion report (Indonesian)

- Changed files and the exact call sites (function + line).
- Per test: RED failure text, then GREEN; real PASS/FAIL/SKIP counts with the commands used.
- 1056-style evidence for one Pack row: input, saved, submitted, and ledger values.
- Blind-count checks, the revise result (4b), and what was not run.
- Remaining blockers: cloud equivalence, paired deployment approval, pre-existing tokenless docs.
- Update POSNext `PROJECT_STATE.md` without overwriting other entries, propose an exact commit message, and wait.
