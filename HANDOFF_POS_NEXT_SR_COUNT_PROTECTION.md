# POSNext Handoff: Stock Opname Compatibility with SR Count Protection

Date: 2026-11-05
Status: warehouse_app implemented locally (uncommitted, see "Implemented warehouse_app contract"); POSNext adapter still pending. Re-verify the contract before coding.
Execution repository: `/Users/rotiropi/ERPNext-Project/development/frappe-bench/apps/pos_next`
Owner of conversion: sibling `warehouse_app` repository.

## Scope and sequence

The user explicitly separated this work: first fix Stock Reconciliation in warehouse_app; implement this bounded POSNext adapter later, from the POSNext repository. This handoff does not authorize deployment, stock operations, commits, pushes, dependencies or overwriting concurrent work.

Read POSNext `CLAUDE.md`, `PROJECT_STATE.md` and applicable instructions first. Inspect Git status/diffs: POSNext had substantial unrelated uncommitted work on2026-11-05. Do not stash/reset/discard it. Verify actual runtime/source paths rather than relying on old container names.

Read these warehouse_app documents:
- `docs/specs/2026-11-05-sr-counted-input-protection-design.md` (revision3)
- `docs/plans/2026-11-05-sr-counted-input-protection.md`
- This handoff supersedes the2026-11-03 handoff for the NEW count-protection contract. Do not reapply old fixes without checking current code.

## Why POSNext is affected

Stock Opname saves native Stock Reconciliation documents. The new warehouse validator will treat physical After/UOM as input, native Qty as derived stock-UOM target, and historical balance as Before only. It must distinguish explicit0 from an uncounted/default Float0 and detect changed context.

Proposed additive field: `custom_count_confirmation` (hidden Data, no-copy), a deterministic context fingerprint, not a copy of the count and not an authorization token. No JSON intent/context engine.

For1056Pack with master6Pcs/Pack, After stays1056 and native target becomes6336. Do not multiply again in POSNext or reverse-convert a refreshed stock balance into After.

## Observed local source contracts (recheck before editing)

- `POS/src/components/pos/StockOpnameDialog.vue::buildItems` (~1636): filters blank counts using `isUncounted`; retains explicit0; nonserial rows send `custom_uom` and `custom_qty_after`. Serial rows count selected serials. No SPA redesign is currently required.
- `pos_next/api/stock_opname.py::_validated_rows` (~333): validates count/profile-domain input, resolves valid UOM via warehouse_app when installed, removes native `qty` on custom rows and sends After/UOM to document validation. It currently does not set the new confirmation.
- `save_opname` (~700): checks warehouse/workflow/modified/freeze, rebuilds children, sets optional posting fields, then saves/inserts. Rebuilding children can discard additive fields unless the adapter deliberately recreates them from the newly supplied explicit counts.
- `submit_opname` (~777): may stamp posting time now, sets `set_posting_time=1`, saves, then applies workflow. A fingerprint containing posting time will otherwise become stale. This requires an explicit policy/acknowledgment decision, not silent re-confirmation.
- `_payload` (~471): returns original custom After/UOM; do not expose balances/rates or treat fingerprint as UI count data.
- `pos_next/overrides/stock_reconciliation.py`: current local code already blanks draft differences AFTER super validation and filters reads for blind-count users. The old handoff's description of pre-super blanking is stale. Preserve the actual protections.

These are local observations, NOT exact cloud revision proof. Cloud observed Frappe16.55.2/ERPNext16.53.0 differs from scratch16.52.0/16.51.1.

## Implemented warehouse_app contract (2026-11-05, UNCOMMITTED on top of cc0634b)

Source state: working tree of warehouse_app `main` @ `cc0634b` plus uncommitted diff (sha256 of `git diff` + untracked app files at report time: `3ac6b7d9…`). Not committed, not deployed. Re-verify the code before relying on it — signatures below are what exists locally now.

- Field: `Stock Reconciliation Item.custom_count_confirmation` (Data, hidden, read_only, no_copy), constant `warehouse_app.sr_uom.SR_CONFIRMATION_FIELD`.
- `warehouse_app.sr_uom.count_confirmation(*, company, item_code, warehouse, posting_date, posting_time, set_posting_time=0, uom, factor, batch_no=None) -> str` — 32-hex SHA-256 over canonical JSON `[company, item, warehouse, posting_ctx, uom, factor, batch]`; `posting_ctx="now"` when `set_posting_time=0`, else `getdate(posting_date).isoformat()` + " " + `get_time(posting_time).isoformat()` (microseconds preserved, e.g. `16:51:33.742924`; `timedelta(0)` midnight accepted; empty = None/"" only). Changed in review round 2/3 — tokens produced by the earlier `%H:%M:%S` draft are not compatible.
- `warehouse_app.sr_uom.confirm_count_rows(doc) -> None` — internal (not whitelisted). Stamps confirmation on custom rows (`custom_uom` set) with explicit non-empty `custom_qty_after`, using the doc's CURRENT company/posting mode/date/time and the Item master factor; throws for invalid factor, unrepresentable target, custom serial/bundle rows. Returns nothing; no balances/rates. Call it only AFTER final company/warehouse/posting fields are assigned.
- Lifecycle: `StockReconciliationUOM.validate_posting_time()` → native `super()` → `apply_to_doc(doc)`, which throws if any custom row lacks a confirmation matching current context + current master factor (no auto re-confirm), rejects clearing `custom_uom` on a previously saved counted row, then derives native `qty = After × factor` one-way. Native-only rows untouched.
- `resolve_factors(pairs)` signature unchanged (POSNext `_validated_rows` caller stays compatible).
- Whitelisted `warehouse_app…stock_reconciliation.compute_row(...)` gained `company`, `set_posting_time`, `omit_confirmation` and returns `custom_count_confirmation` — it reads stock; outlet users must NOT use it (use the internal helper).
- Fetch (`get_items`) no longer prefills After. W23/W26 Client Scripts and Server Script `sr_auto_populate_before_after` are DISABLED (not deleted) by `upgrade.apply()`; W23/W26 no longer produced.

Consequence for POSNext (expected, not yet tested there): an outlet payload with `custom_uom`+`custom_qty_after` but no confirmation is now REJECTED at validate. `submit_opname` setting `set_posting_time=1` on a row confirmed in `"now"` mode invalidates it → the timestamp policy gate below must be resolved before release.

Warehouse-side evidence (isolated `srcount.localhost`, Frappe16.52.0/ERPNext16.51.1 — NOT cloud-equivalent), after review round 3: unit 99 OK, Node 50/50 OK (run with `SR_SCRIPT`/`NATIVE_SR_SCRIPT` env), integration `warehouse_app.tests.test_sr_count_integration` 16/16 OK, served-form browser checks (see proof "Served-form browser evidence"). Observed on srcount: the installed POSNext override persists draft `current_qty`/`custom_qty_before` as 0 (by design); W49 does not change that. See `docs/proofs/2026-11-05-sr-counted-input-protection.md`. No POSNext test was run.

## Required bounded adapter

1. Wait for warehouse_app's verified release interface and exact revision. Proposed internal helper is `warehouse_app.sr_uom.confirm_count_rows(doc) -> None`; this is NOT implemented at handoff creation. Confirm its final signature, inputs and lifecycle before using it.
2. For explicit, authorized count saves only: preserve current POSNext parsing, profile/warehouse/freeze/workflow/photo validation; assign final document context, then invoke the shared helper before native save/insert. Let warehouse_app derive native Qty and validate factor/precision.
3. Use a guarded lazy import; retain native stock-UOM operation when warehouse_app/fields are absent. Never silently accept a nonstock UOM when its conversion engine is absent.
4. Do not call the public stock-reading warehouse endpoint as an outlet user just to confirm counts. The internal helper must not return or leak historical balances/rates.
5. Do not add validation-bypass flags or duplicate conversion math. Generic HQ approval/background submission must validate persisted confirmation; it must not silently regenerate one after a context/master change.
6. Keep native-only serial handling; direct batch custom follows warehouse_app's proven support. Unsupported combinations fail clearly instead of skipping validation.

### Posting-context rule (user decision 2026-11-05, spec revision3.1)

The fingerprint contains the posting MODE: `set_posting_time=0` → token `"now"` (native auto-timestamps on Save/Submit do not invalidate); `set_posting_time=1` → normalized explicit date+time (any change invalidates); toggling the flag invalidates. Ledger/Before always use the actual final timestamp. Consequence for POSNext: `submit_opname` currently stamps a new time AND sets `set_posting_time=1`; on a row confirmed in `"now"` mode that toggle itself invalidates the confirmation. The gate below still applies — this rule does not authorize a POSNext posting-policy change.

### Posting timestamp gate — obtain a decision before changing behavior

Preserve explicit approved backdates and existing backdate/freeze permissions. Current-time stamping on workflow submission changes the confirmed context. Present the smallest concrete acknowledgment/API change needed to the user before implementing it; alternatively propose retaining the confirmed posting timestamp, but that is a posting-policy change requiring approval too.

Do not choose a policy silently, always block all submissions, or automatically re-confirm counts merely because an approver submits. Warehouse_app first can be implemented/tested independently; production cutover remains blocked until this interaction is resolved and tested.

## Files expected to change in POSNext

- `pos_next/api/stock_opname.py`: thin adapter and approved timestamp acknowledgment only.
- `pos_next/api/test_stock_opname.py`: extend existing UOM/posting/workflow tests.
- `pos_next/tests/test_stock_opname_override.py`: compatibility/security regression coverage; no planned controller redesign.
- `POS/src/components/pos/StockOpnameDialog.vue` and focused Vitest tests ONLY if an approved timestamp acknowledgment actually requires UI support. Existing empty/zero behavior should be reused.

No planned changes to ledger, core, roles, workflow definitions, photo policy, stock settings, override ownership or unrelated POS features.

## TDD acceptance

Write and demonstrate failing tests before adapter implementation:
- Create/save/reload1056Pack→6336Pcs; After/UOM unchanged; explicit0 stays0, blank rows remain uncounted/excluded.
- Re-save reconstructed child rows retains a valid confirmation without changing the count.
- Explicit backdated posting preserved; current-time workflow stamping obeys the approved acknowledgment contract; stale master factor/context fails clearly.
- Outlet submission to an approval state is NOT described as ledger posting. Prove final HQ approval/native submission separately, including background reload and >100-row path if installed.
- Returned/revised counts, modified mismatch, profile/warehouse restrictions, photo requirements and open-opname guard still work.
- Blind-count payloads, errors, print and serializers expose no ledger quantity/rate; outlet users cannot set valuation.
- Native-only stock UOM without warehouse_app, direct batch support and native serial flows remain correct.
- Effective native ledger target at posting timestamp equals the count; later movements may change today's balance. Check valuation/GL/repost where relevant.

Use the installed POSNext test runner and an identified isolated site; inspect runner syntax first. Do not run mutation/cleanup gates on cloud or local sites containing production data. No allow_negative_stock changes or historical voucher correction.

## Release coordination

Warehouse_app completion evidence must provide actual helper/field contract, source revision, migration behavior and isolated test results. POSNext must provide its revision, compatibility proof and resolved timestamp policy.

Do NOT deploy the new strict warehouse validator alone onto an actively used incompatible POSNext site. Production release requires separately approved paired artifact revisions, script backup/retirement, maintenance window, single-handler verification and rollback. Do not re-enable W23/W26 or the Bin-based server script during a mixed-code state.

## Completion report

Report exact changed files/contracts, actual PASS/FAIL/SKIP results, input→saved→workflow→submitted→effective-ledger evidence, blind-count checks, unresolved blockers and deployment approval still required. Update POSNext local state without overwriting other work. No automatic commit or push.

## Prompt for the later POSNext session

Read /Users/rotiropi/ERPNext-Project/development/frappe-bench/apps/warehouse_app/HANDOFF_POS_NEXT_SR_COUNT_PROTECTION.md and the linked spec/plan. Work from /Users/rotiropi/ERPNext-Project/development/frappe-bench/apps/pos_next; read its instructions/state and inspect dirty changes. Verify warehouse_app's implemented contract/revision before coding. Implement only the bounded Stock Opname compatibility adapter using the shared conversion engine, TDD and isolated native-ledger tests. Stop for user approval of timestamp acknowledgment/posting-policy changes. Preserve blind count, photos, workflow and native serial/batch. Do not deploy, alter production stock/scripts/settings, add dependencies, commit, push or discard unrelated work. Report actual evidence and blockers.
