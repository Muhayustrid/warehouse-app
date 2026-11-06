# POSNext Handoff: Stock Opname Adapter for SR Count Protection

Date: 2026-11-06 (supersedes the 2026-11-05 version of this file)
For: a FRESH AI agent session that works only in the POSNext repository.
Execution repository: `/Users/rotiropi/ERPNext-Project/development/frappe-bench/apps/pos_next`
Contract owner (read-only for you): `/Users/rotiropi/ERPNext-Project/development/frappe-bench/apps/warehouse_app`, commit `810dacc` on `main` (committed, NOT pushed, NOT deployed).

## 1. Goal in one paragraph

warehouse_app now protects the physical count on Stock Reconciliation (SR): the counted
input is `custom_qty_after` in `custom_uom` (e.g. 1056 Pack); native `qty` is derived
(1056 x 6 = 6336 Pcs) and must survive save, reload, workflow and submit. Every custom-UOM
row must carry `custom_count_confirmation`, a fingerprint of its context (company, item,
warehouse, posting mode/time, UOM, master factor, batch). Rows without a matching
fingerprint are REJECTED at validate. POSNext Stock Opname writes SR documents, so today
every outlet save with a custom UOM fails. Your job: a thin adapter in POSNext that stamps
the fingerprint at the right moments using warehouse_app's helper. Nothing else.

## 2. Hard rules

- Work only in the POSNext repo. Never edit warehouse_app; if its contract is wrong, stop and report.
- Read POSNext `CLAUDE.md` and `PROJECT_STATE.md` first. The POSNext tree has many unrelated uncommitted/untracked files from other work: do not stash, reset, clean, or commit them.
- TDD: write the failing tests first, show them RED, then implement.
- No deploy, no image rebuild, no migrate on dev/prod (`dev.localhost`, `erp.localhost` hold production data), no cloud writes (`https://ropi.co.id` is read-only), no changes to production Client/Server Scripts or settings.
- No `allow_negative_stock`, no cancelling/amending historical stock documents, no balancing transactions.
- No new dependencies. No commit or push without the user's approval of the exact message.
- Do not weaken warehouse_app validation, add bypass flags, or duplicate conversion math in POSNext.
- Communicate with the user in Indonesian; code comments and docs in English.

## 3. warehouse_app contract you consume (verify in source before coding)

File `warehouse_app/sr_uom.py` at `810dacc`:

- `SR_CONFIRMATION_FIELD = "custom_count_confirmation"`: Data, hidden, read-only, no_copy on Stock Reconciliation Item.
- `confirm_count_rows(doc) -> None` (internal, NOT whitelisted). For every row with `custom_uom` set it:
  - requires a non-empty `custom_qty_after` (explicit 0 is valid);
  - rejects custom rows with `serial_no` or `serial_and_batch_bundle`;
  - resolves the Item master factor (`resolve_factors`) and checks the target is representable at qty precision;
  - writes `custom_conversion_factor` and `custom_count_confirmation`, using the doc's CURRENT `company`, `set_posting_time`, `posting_date`, `posting_time`, and row `warehouse` / `batch_no`.
  It returns nothing and reads no balances or rates, so it is safe for outlet (blind-count) users. Native-only rows (no `custom_uom`) are untouched.
- Posting context inside the fingerprint: `set_posting_time=0` gives the token `"now"` (native auto-timestamps do not invalidate). `set_posting_time=1` uses the exact date+time, so any change, or toggling the flag, invalidates.
- `apply_to_doc(doc)` runs inside `StockReconciliationUOM.validate` and does three things:
  - throws "Baris N (ITEM) belum dikonfirmasi..." when a custom row's fingerprint does not match the current context and master factor;
  - rejects clearing `custom_uom` on a previously counted row;
  - derives `qty = custom_qty_after x factor`.
  It never re-confirms automatically.
- `resolve_factors(pairs)` is unchanged; your existing `_validated_rows` call stays valid.
- The whitelisted `warehouse_app.warehouse_app.stock_reconciliation.compute_row` READS STOCK. Outlet code must NOT call it.

## 3b. Contract tightening after the 810dacc review (fixed 2026-11-06, uncommitted at time of writing)

Check `git log` in warehouse_app for the commit that contains these fixes; if it is absent, treat them as pending. Signatures of `count_confirmation`, `confirm_count_rows(doc)`, `apply_to_doc(doc)`, `resolve_factors(pairs)` and `precisions(row=None)` are UNCHANGED. Behaviour is stricter:
- H2 fixed: stock UOM and factor always come from the Item master (`_master_stock_uom`). A row `stock_uom` in the payload is ignored for the factor and the whole-number check; tokens minted with a wrong row `stock_uom` (factor 1) are now rejected. Still do not send `stock_uom` from POSNext rows.
- H1 fixed: `confirm_count_rows` and `apply_to_doc` reject a `custom_qty_after` that is not exactly storable at the field precision of `custom_qty_after` (`row.precision(...)`; on srcount it resolves to 2 decimals from System Settings float_precision). Error: "Baris N (ITEM): Qty After X tidak dapat disimpan tepat pada presisi P desimal...". POSNext must send the outlet's count unrounded and surface this error; never round it on the outlet's behalf. Add a TDD case for an over-precise count.
- M4/M5 fixed in Desk JS only (no POSNext impact): Undo no longer leaves a stale snapshot; the Qty/rate lock is reapplied after import and item change.

## 4. User decisions (binding)

1. 2026-11-05: posting-context rule as in section 3.
2. 2026-11-06, the timestamp policy: **re-confirm on outlet Submit.** In `submit_opname`, from the initial workflow state, after POSNext sets the final `posting_date`/`posting_time` and `set_posting_time = 1` (keeping an approved backdate exactly as today), call `confirm_count_rows(doc)` and then `doc.save()`. The outlet's Submit click counts as acknowledging that posting time. The counted numbers must not change.
   Later HQ workflow approval / final native submit must NOT re-confirm. If the master factor or context changed after the outlet submitted, the document must fail clearly, and HQ sends it back for revision.

## 5. Current POSNext code (local, observed 2026-11-06; line numbers approximate)

`pos_next/api/stock_opname.py`:
- `_validated_rows` (~333) validates the payload, resolves the factor via `resolve_factors`, and builds row dicts with `custom_uom` + `custom_qty_after`. It does not set the fingerprint.
- `save_opname` (~700):
  - existing doc: rebuilds the children (`doc.set("items", [])` + append), optionally sets posting fields, then `doc.save()`;
  - new doc: `new_doc` + append + optional posting, then `doc.insert()`.
  Add `confirm_count_rows(doc)` right before `doc.save()` / `doc.insert()`, AFTER company, `set_warehouse`, rows and posting fields are final.
- `submit_opname` (~777): in the initial state it stamps now (or keeps the backdate), sets `set_posting_time=1`, saves, then `apply_workflow`. Add `confirm_count_rows(doc)` right before that `doc.save()` (decision 2). The returned-state path (revise) needs no confirmation.
- `_payload` (~471) must keep exposing no balances/rates. Do not put the fingerprint in the UI payload.

Other POSNext files:
- `pos_next/overrides/stock_reconciliation.py` blanks draft differences after super validation and filters reads for blind-count users. Keep those protections. Observed on srcount 2026-11-06: the active controller's MRO is `ExtendedCustomStockReconciliation` (generated by Frappe's `extend_doctype_class`) -> warehouse_app `StockReconciliationUOM` -> pos_next `CustomStockReconciliation` -> ERPNext `StockReconciliation`. So warehouse_app validation runs on top of POSNext's override. Re-check this, since it depends on app install order.
- `pos_next/public/js/stock_reconciliation.js` loads on the Desk form together with warehouse_app's `public/js/stock_reconciliation.js`; both appear in `doctype_js`. Its `fill_live_differences` writes `custom_qty_before` / `custom_qty_difference_per_uom` client-side as `system_qty / factor`, which is display only. Verify it does not mark rows dirty or clear `custom_count_confirmation`, and that HQ can still Save/Submit an outlet-confirmed document from Desk. Change it only if a test proves a conflict.
- Use a guarded lazy import, as `_validated_rows` already does: when warehouse_app is not installed, skip confirmation and keep native stock-UOM-only behaviour.

## 6. TDD acceptance (all must be shown RED first, then GREEN)

Extend `pos_next/api/test_stock_opname.py` and `pos_next/tests/test_stock_opname_override.py`:

1. New opname, 1056 Pack (master 6): saves; reload shows After 1056 / UOM Pack / qty 6336; token set. Explicit 0 stays 0; blank rows stay excluded.
2. Re-save an existing opname (children rebuilt) with the same and with a changed count: token valid, numbers exactly as entered.
3. Outlet Submit from the initial state, with no backdate: posting stamped now, token re-issued, workflow moves on, numbers unchanged.
4. Outlet Submit with an approved backdate: backdate kept exactly; token matches it.
5. Master factor changed (6 to 12) after the outlet submit: HQ approval/final submit fails with the "belum dikonfirmasi" error and does NOT silently re-confirm.
6. Final HQ submit posts SLE: `qty_after_transaction` at the posting time is 6336 and valuation is correct. Outlet submission to an approval state is not ledger posting; prove the final native submit separately.
7. Blind-count: no payload, error, or serializer exposes ledger qty or rate; outlet users cannot set valuation; the adapter never calls `compute_row`.
8. Regressions still pass: returned/revise flow, `modified` mismatch, profile/warehouse restrictions, photo requirement, open-opname guard, native serial rows, batch rows, native stock-UOM rows without warehouse_app.
9. Desk check: HQ opens an outlet-submitted SR in Desk with both form scripts loaded and approves it; the token stays valid and the qty unchanged.

## 7. Where to run tests

Use only the isolated stack `erpnext-srcount` (site `srcount.localhost`, http://srcount.localhost:8003, DB :3310). Admin password: `ADMIN_PASSWORD` in `docker/.env.srcount`; never print it.
- It runs image `erpnext16:local` with Frappe 16.52.0 / ERPNext 16.51.1 and POSNext 2.16.0 baked in. Only warehouse_app is bind-mounted (`docker/compose.srcount.mount.yaml`), so your POSNext edits are NOT live there.
- To test them, propose to the user adding a pos_next bind mount to that overlay (srcount only; this does not change the shared image), and get approval before recreating the srcount containers.
- srcount state: no POS Profile; Workflow "POS Next Stock Opname" exists but is inactive. Your tests must create their own scoped fixtures (unique prefix) and clean up only what they created.
- Keep these existing fixtures: company `_Test SR Count Co`, items `W49E2E-PACK`/`-SER`, MAT-RECO-2026-00186...00272, warehouse `W49 Repro - _SCC`. Drafts 00267/00269/00270/00271 occupy POSNext's one-open-opname-per-warehouse guard on Stores/WIP/Finished Goods/Goods In Transit - _SCC: create your own warehouse for tests, or ask the user before deleting those drafts. 00268 and 00272 are submitted WITHOUT ledger (harness artifact, see proof); do not use them as evidence.
- Do not assert stock results through `bench execute` on functions that may raise: Frappe 16.52 retries the call without rollback and commits (this produced 00268/00272). Use run-tests or an explicit try/rollback.
- Native rule: a count for a warehouse with no prior stock and no valuation rate cannot be submitted ("Valuation Rate required"). Outlets cannot set rates, so tests of final submit must use a warehouse with stock or have HQ set the rate. `W49E2E-PACK` (Stock UOM Pcs, Pack = 6) is a ready-made 1056 to 6336 example.
- Inspect the POSNext test runner syntax before running (`bench --site srcount.localhost run-tests --module ...`).
- Cloud runs Frappe 16.55.2 / ERPNext 16.53.0, so srcount results are not cloud proof. Say so in the report.

## 8. Release coordination (not your job to execute)

Never deploy warehouse_app `810dacc` alone onto a site where POSNext Stock Opname is in use: outlet custom-UOM saves would be rejected. Release needs:
- paired, user-approved revisions of both apps;
- a maintenance freeze on SR;
- backup of the SR Client/Server Script state; migrate disables W23/W26 and does not re-enable them;
- single-handler verification;
- the rollback plan in warehouse_app `docs/proofs/2026-11-05-sr-counted-input-protection.md`, section "Rollback rehearsal". Drafts made while rolled back must be re-confirmed after rolling forward.

## 9. Completion report

Report to the user in Indonesian:
- changed files;
- the exact adapter call sites;
- real PASS/FAIL/SKIP counts with commands;
- the input, saved, submitted and ledger evidence for 1056 Pack;
- the blind-count checks;
- what was not run;
- the remaining blockers (cloud equivalence, paired deployment approval).
Update POSNext `PROJECT_STATE.md` without overwriting other entries. Propose a commit message and wait for approval.

## 10. Prompt to start the fresh session

```
Work in /Users/rotiropi/ERPNext-Project/development/frappe-bench/apps/pos_next.
Read /Users/rotiropi/ERPNext-Project/development/frappe-bench/apps/warehouse_app/HANDOFF_POS_NEXT_SR_COUNT_PROTECTION.md
fully and follow it. Read POSNext CLAUDE.md and PROJECT_STATE.md, inspect git status, and do not
touch unrelated dirty files. Verify the warehouse_app contract at commit 810dacc in source first.
Implement only the Stock Opname adapter (confirm_count_rows on save and on outlet Submit) with TDD,
on srcount.localhost only. Ask me before changing the srcount compose overlay. Do not deploy,
commit, push, or edit warehouse_app. Report actual evidence and blockers in Indonesian.
```
