# Stock Reconciliation Count Protection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Track steps with checkboxes. The user selected a dynamic workflow in a DIFFERENT session: do not execute it in this planning session. That session must load workflow-authoring before authoring/running its workflow.

**Goal:** Preserve explicit physical counts through form edits, Save/reload, workflow Submit/reload and effective native ledger posting.

**Architecture:** Follow native Stock Entry's separation of entered quantity, conversion factor, derived stock quantity and balance. warehouse_app owns conversion and Desk behavior; POSNext only adapts explicit count input to that shared contract. Keep ERPNext's ledger, valuation, workflow and serial/batch engines.

**Tech Stack:** Installed Frappe/ERPNext v16, Python unittest/Frappe tests, native Desk JavaScript, existing Node VM tests; POSNext Vue/Vitest only if an observed UI contract requires a change. No new dependencies.

**Spec:** `docs/specs/2026-11-05-sr-counted-input-protection-design.md` (revision3). Read both documents before execution.

## Global Constraints

- Production target is CLOUD `https://ropi.co.id`; initial cloud investigation is GET-only.
- No core edits, dependency additions, negative-stock setting changes, historical stock corrections, or fictitious balancing stock.
- Never touch `Backup SIte Production/`; credentials only from existing environment, never output/commit secrets.
- Native-only documents, blind count, role permissions, workflow, photos, serial/batch and ledger remain intact.
- No production deployment/configuration/stock operation without separate exact approval.
- No commit or push without explicit authorization; propose exact scoped Conventional Commit message and wait before each authorized commit. Plan steps do not grant authorization.
- Read applicable repo instructions and current Git changes before edits; preserve concurrent work. Do not run destructive fixture gates against production-data dev/prod sites.
- Cloud observed16.55.2/ERPNext16.53.0 differs from scratch16.52.0/16.51.1. Recheck versions; production-readiness proof requires target-equivalent runtime and actual source/hooks compatibility.

## Review Focus

- An unchanged/default numeric0 must not become a physical zero count; test explicit DOM zero and API zero (Tasks2–4).
- A UOM response started before an edit must not confirm a later input or context (Tasks2–3).
- POSNext changes posting time during submission and reconstructs child rows during save; neither may lose counts or silently re-confirm stale context (Task4).
- A background approval reloads the document without browser state; persisted confirmation and native lifecycle must still protect it (Tasks2,4,6).
- Empty/no-change/native-only and blind-count records must not acquire custom counts or leak ledger values through errors (Tasks2,5,6).

## Source Map and Ownership

Paths are relative to warehouse_app unless explicitly prefixed `POSNEXT/` (sibling `../pos_next`).

| Files | Responsibility |
|---|---|
| `warehouse_app/sr_uom.py` | Master conversion, precision and confirmation validation |
| `warehouse_app/overrides/stock_reconciliation.py` | Lifecycle integration after final posting time, before native bundle/filter |
| `warehouse_app/warehouse_app/stock_reconciliation.py` | Fetch Items and conversion endpoint |
| `warehouse_app/public/js/stock_reconciliation.js` (new) | Desk input/async/Save barrier plus migrated W26 import |
| `warehouse_app/hooks.py`, `warehouse_app/upgrade.py` | Load JS, additive field, deterministic legacy-script retirement |
| `warehouse_app/warehouse_app/sr_import.py` | File count conversion, timestamp template and no-op semantics |
| `warehouse_app/tests/test_sr_*.py`, `sr_client_script.test.mjs` | Existing reusable unit harnesses |
| `warehouse_app/tests/test_sr_count_integration.py` (new) | Native lifecycle/ledger evidence on isolated site |
| `POSNEXT/pos_next/api/stock_opname.py` | Thin input adapter only; no duplicate conversion engine |
| `POSNEXT/pos_next/api/test_stock_opname.py` | POSNext UOM/zero/posting/workflow compatibility |
| `POSNEXT/pos_next/overrides/stock_reconciliation.py` | Read reference; preserve blind-count/MRO behavior, no planned change |

## Task 1 — Lock runtime/caller contracts and record baseline

**Files:** Read spec, both repos' instructions/state, existing tests; create `docs/proofs/2026-11-05-sr-counted-input-protection.md`.

**Interfaces:** Produces an evidence manifest: actual revisions, class MRO, hooks/load order, metadata precision, test-site identity, caller list and safe test commands. It is not a deployment manifest.

- [ ] Read `/Users/rotiropi/AutoFetchErestoToERPNext` mandatory knowledge/safety/investigation files. Read warehouse_app `AGENTS.md`, `TASKS.md`, `PROJECT_STATE.md`; POSNext `CLAUDE.md` and local state before any POSNext edits.
- [ ] Inspect Git status/diffs of both apps; use isolation respecting their instructions. Record dirty POSNext work and do not stash/reset/overwrite it. Identify which runtime source actually executes each app.
- [ ] Verify target cloud Python revision/hooks/MRO through authorized existing source access. Do not guess from app version0.0.1 or run mutating cloud probes. If unavailable, record the production-proof blocker and keep all work local.
- [ ] Inspect installed `get_conversion_factor`, precision, `validate_posting_time`, no-change filter, serial/batch API and Desk script registration. Pin the local adapter seam and document how it replaces the Qty-writing callback before requests begin.
- [ ] Inventory exact writers/callers, including POSNext `_validated_rows`, `save_opname`, `submit_opname`, `_payload`, direct API, import, fixtures and migrate producers. Exact-text grep callers before changing shared functions.
- [ ] Run baseline: `python3 -m unittest warehouse_app.tests.test_sr_uom warehouse_app.tests.test_sr_class warehouse_app.tests.test_sr_endpoints warehouse_app.tests.test_sr_client_script`. Add import/access suites using their existing runner isolation. Record actual output;44 passed was historical evidence, not a promised new result.
- [ ] Verify scratch identity/volumes and absence of shared production data paths before integration. Runtime upgrades/new sites/dependency changes require permission when not already authorized. Do not rebuild a shared image affecting other work without approval.

## Task 2 — Shared conversion and minimal confirmation (TDD)

**Files:** Modify `warehouse_app/sr_uom.py`, `warehouse_app/overrides/stock_reconciliation.py`, `warehouse_app/warehouse_app/stock_reconciliation.py`, `warehouse_app/upgrade.py`; test `test_sr_uom.py`, `test_sr_class.py`, `test_sr_endpoints.py`.

**Interfaces:** Preserve existing `compute_row(...) -> dict`, `resolve_factors(pairs) -> dict`, `precisions(row=None) -> dict`, `apply_to_doc(doc) -> None` callers except documented additive result keys. Add internal `count_confirmation(*, company, item_code, warehouse, posting_date, posting_time, uom, factor, batch_no=None) -> str`. Add internal `confirm_count_rows(doc) -> None` for explicit validated server-side count input only; no whitelist and no stock-read response. Confirmation never stores After or native Qty.

- [ ] Add failing cases with exact assertions: counted1056/factor6/native stale6306 yields6336, After remains1056; counted0 yields0; missing confirmation on custom row throws; native-only/mixed native rows remain unchanged; saved context mismatch or master-factor change throws.
- [ ] Add precision tests:2.5×1.2=3 with installed-representable metadata; unrepresentable targets throw; invalid/nonfinite factor/input throw atomically; display10/12 never becomes an explicit count by comparison. Preserve existing valuation round-trip behavior separately from count conversion.
- [ ] Posting-context (spec §3 revision3.1, user decision 2026-11-05): `set_posting_time=0` fingerprints the token `"now"`; `set_posting_time=1` fingerprints normalized explicit date+time; toggling the flag invalidates. The token is only for confirmation validity — Before/ledger always use the actual post-`validate_posting_time()` timestamp. Tests: now-mode Save→Submit at different times incl. across midnight passes with After/target unchanged; Before uses each run's actual timestamp; explicit mode detects same-day time change; toggle invalidates; intervening transactions never rewrite the count; explicit fingerprint stable after reload.
- [ ] Test fingerprint normalization for date/time objects vs strings, empty batch, factor representation and field length. Same semantic context gives the same bounded value; any relevant context change differs. Use stable serialization+stdlib digest; no custom crypto/security claim.
- [ ] Run focused tests, retain expected RED output, then implement minimum logic. Reuse verified native factor/precision helpers only where they satisfy strict master validation. Remove rounded-equality preservation of stale native Qty for confirmed counts.
- [ ] Add `custom_count_confirmation` Data hidden/no-copy through existing field-spec/upsert pattern. Never infer confirmation from default Float0. `confirm_count_rows(doc)` validates explicit nonempty After and resolves master/context; caller is responsible for calling it only for a newly authorized explicit count action.
- [ ] Extend conversion endpoint result with confirmation for supplied explicit After and resolved company/context; preserve access checks. Do not require blind-count callers to call a stock-reading HTTP endpoint: Task4 uses the internal helper.
- [ ] At the verified lifecycle seam, validate final-context confirmation before assigning target and before bundles/no-change filtering. Handle `_action`/background reload and native timestamp normalization; invalid context throws, not automatic re-confirmation.
- [ ] Run focused and baseline suites GREEN. Record incompatible old assumptions explicitly and replace only tests contradicted by revision3, not failing security/native assertions.

## Task 3 — One-way Desk input and pre-write async guards (TDD)

**Files:** Create `warehouse_app/public/js/stock_reconciliation.js`; modify `warehouse_app/hooks.py`, existing `test_sr_client_script.py`, `sr_client_script.test.mjs`. Do not activate both app and DB handlers on a live site.

**Interfaces:** Native form public behavior stays SR. App has one instance-local adapter for `set_valuation_rate_and_qty`; new JS is the sole owner of custom input synchronization/W26 functionality. Server conversion result uses Task2's additive confirmation key.

- [ ] Extend Node harness to load actual pinned native JS and app JS, registering multiple handlers in native order with deferred balance/factor requests; keep native sources revision-identifiable. Add test `late_native_balance_preserves_count_1056` asserting After1056/native target6336 after callback6306.
- [ ] Add reversed-response, same-value-zero DOM input, active editor Save, context change during pending Save, row delete/re-add, form navigation and submitted/cancelled refresh tests. Assert pending stale replies cannot set confirmation or clear After/UOM.
- [ ] Run RED against old W23; record failure from actual event sequence, not a fabricated expected failure.
- [ ] Implement local adapter before native requests start. Ledger responses update only current/Before/difference on custom rows; no reverse Qty→After. Native-only behavior delegates safely; maintain serial/batch behavior or explicit unsupported error.
- [ ] Implement input snapshot, per-row generation and Save/Submit barrier using verified Frappe mechanisms. Preserve typed values when context invalidates confirmation. Expose one clear confirmation action for unchanged legacy/zero count; no general-purpose intent state machine.
- [ ] Fetch new rows without After prefill; native Qty derived/non-editable for custom rows. Keep existing role-gated presentation and prevent grid re-render loops. Refresh docstatus1/2 is nonmutating.
- [ ] Run Node through `python3 -m unittest warehouse_app.tests.test_sr_client_script`; verify installed test wrapper actually invokes Node cases and fails on their failures. Smoke adapter registration on the isolated runtime before claiming the load-order contract works.

## Task 4 — DEFERRED: POSNext adapter in its own repository/session

**User scope update:** Do NOT execute this task in the warehouse_app workflow. Its deliverable is the separate [`HANDOFF_POS_NEXT_SR_COUNT_PROTECTION.md`](../../HANDOFF_POS_NEXT_SR_COUNT_PROTECTION.md). The checklist below is a future acceptance reference for that session, not authorization to edit POSNext. Warehouse work continues with Task5. Production release remains blocked until POSNext compatibility is completed and proved separately.

### Future POSNext acceptance reference

**Files:** `POSNEXT/pos_next/api/stock_opname.py`, `POSNEXT/pos_next/api/test_stock_opname.py`; references `POS/src/components/pos/StockOpnameDialog.vue`, `pos_next/overrides/stock_reconciliation.py`. No planned SPA/controller redesign.

**Observed contracts:** Dialog `buildItems()` filters blank rows but retains explicit0 and sends custom UOM/After. `_validated_rows()` removes native Qty for custom counts and delegates to warehouse_app. `save_opname()` reconstructs child rows. `submit_opname()` may stamp a new current timestamp before saving/applying workflow. None currently sets the new confirmation.

**Interfaces:** Backend calls Task2 internal `confirm_count_rows(doc)` only after profile/warehouse/input/freeze/permission validation and explicit count confirmation. Never bypass the lifecycle validator globally or add duplicate factor math.

- [ ] Before cross-repo edits, confirm user-approved scope covers this adapter, inspect current dirty work, and coordinate ownership. If permission/ownership is unresolved, produce a handoff patch plan and mark release blocked; do not edit a competing working tree.
- [ ] Add failing `TestStockOpnameUom` create→save→reload tests1056Pack→6336Pcs and0. Test `_payload` returns original After/UOM without system balance/rates or confirmation leakage; native stock-UOM fallback still works without warehouse_app.
- [ ] Test submit timestamp behavior: preserve explicitly approved backdate; current-time stamping cannot silently discard confirmation. Add direct/custom workflow, returned revise, concurrency `modified` mismatch, photos and background approval reload tests.
- [ ] Resolve timestamp UX explicitly: retain existing posting policy but require explicit reconfirmation when its final timestamp changes the confirmed context. Never silently regenerate confirmation during generic approval/submit. If preserving the existing timestamp policy needs a new user-visible acknowledgment/API argument, stop for approval of that small contract BEFORE implementation; do not silently weaken the spec or change posting policy.
- [ ] For explicit `save_opname` counts, call shared confirmation after doc company/warehouse/posting fields are assigned and before save/insert. If posting time is defaulted later by native, establish its final value via verified native behavior first; no duplicate clock/ledger engine.
- [ ] Do not re-confirm an unchanged persisted count solely because an approver submits it. Do not call public stock-reading endpoint as an outlet user. Preserve profile access, photo checks, returned workflow and reservation guards.
- [ ] Run the isolated site's installed POSNext backend runner for `pos_next.api.test_stock_opname` and `pos_next.tests.test_stock_opname_override`, following that runner's verified syntax. Record exact command/output in proof; never use stale container names from instructions without checking.
- [ ] Frontend stays unchanged unless timestamp acknowledgment or an actually failing regression needs it; then add focused existing Vitest tests and obtain scope approval. Coordinate warehouse_app/POSNext artifact deployment as one compatibility unit.

## Task 5 — Import/Fetch parity and script retirement (TDD)

**Files:** `warehouse_app/warehouse_app/sr_import.py`, `warehouse_app/warehouse_app/stock_reconciliation.py`, new JS, `upgrade.py`; tests `test_sr_import_uom.py`, `test_sr_access.py`, new `warehouse_app/tests/test_sr_install.py`; update affected W23/W25/W31/W32 gate assertions only when safe.

**Interfaces:** Keep public `upload_stock_count(...)`, `validate_count_rows(...)`, `get_items(...)` contracts; template endpoint gains optional posting date/time arguments supplied by form. Rows with explicit counts carry Task2 confirmation. Only authorized callers get ledger data.

- [ ] Add failing tests for import0/noninteger factor, context timestamp, no-op valuation comparison, native10/Pack12 Fetch without After prefill, stale upload and replace-confirm callback. Preserve existing size/parser/atomic/permission behavior.
- [ ] Add migration tests: two apply calls produce one additive field, no app-owned W23/W26 enabled, legacy server script disabled, no deletion, unrelated scripts untouched. Retirement failure and conflicting duplicates must not report success. Assert no producer re-enables retired scripts.
- [ ] Move W26 functionality into new JS, carrying posting context on template/upload. Use shared conversion, not copied formulas; replace0.0005 matched stripping with validated effective quantity+valuation equality.
- [ ] Remove W23/W26 from `CLIENT_SCRIPTS` production specs; disable matching verified names/markers and exact conflicting server script idempotently. Do not indiscriminately disable all SR scripts. Preserve rollback originals outside fixtures/source-controlled secrets.
- [ ] Run unit suites GREEN and isolated repeated install/migrate; prove single handler registration/served assets. No production migration is authorized by this step.

## Task 6 — Native ledger E2E, review, and handoff

**Files:** Create `warehouse_app/tests/test_sr_count_integration.py`; proof file from Task1; update both apps' local state only for their owned work.

**Interfaces:** Tests execute actual SR document controller/workflow/native ledger, not just `apply_to_doc`; browser executes served app/native JS. All artifacts identify site, revisions, roles and timestamps.

- [ ] Write integration tests using isolated test company/item/warehouses and native fixture transactions. Verify isolation/cleanup strategy before running any submit/cancel. Native tests must not reuse user production documents or temporarily enable negative stock.
- [ ] Prove1056Pack→6336Pcs saved/reloaded/submitted/reloaded and effective ledger; include a later fixture movement to distinguish current balance from posting-time target. Record rate/value/GL/repost state as relevant.
- [ ] Cover count0, representable fractions, nonrepresentable refusal, factor change, same-second ordering, native-only/mixed, serial/batch, no-change rows/all-matched and effective valuation proof.
- [ ] Browser E2E: delay/reorder actual native/custom calls, type then immediately Save/Submit, change context, import, and refresh docstatus1/2. Assert no changed input/dirty mutation after read-only refresh.
- [ ] Record POSNext end-to-end compatibility as DEFERRED to its own session/handoff, not PASS. Warehouse tests may verify extension/permission compatibility against existing source but must not edit POSNext or claim its workflow is fixed. Release is blocked until the separate session proves outlet→HQ→native-submit ledger behavior.
- [ ] Rehearse install/migrate twice and rollback artifact+DB-script configuration under local maintenance freeze, including tab reload and draft compatibility. Restore no handler twice; no field/data deletion.
- [ ] Request independent final review of actual diff and proof. Fix confirmed defects with focused regression tests. Verification-before-completion skill required before success claims.
- [ ] Produce release manifest: exact app/core revisions, scripts to disable/backups/rollback, blockers, actual PASS/FAIL/SKIP results and production approval still required. Update local state without rewriting unrelated work. Stop; no deployment/stock correction/commit/push automatically.

## Dynamic Workflow Handoff — New Session Only

Suggested phase order: Evidence gate → Shared conversion → Desk async → Import/migration → Warehouse integration → Independent review → Verified interface handoff. Task4/POSNext implementation runs later in its own repository/session. Implementation phases are sequential because they share contracts/files. Parallelize only independent read-only evidence or final review; do not spawn multiple writers on `sr_uom.py` or `upgrade.py`. Do not edit POSNext in this workflow.

Use pinned `sonnet-max` for implementation/testing and `opus-xhigh` for deliberate hard review; no model overrides for pinned agents. Prefer one implementation agent resumed across coupled tasks and one independent reviewer. Keep the workflow under10 agents; do not fan out a separate agent per tiny step. Progress must preserve RED/GREEN outputs and actual blockers. Workflow authorization does not authorize production actions, commits, dependency upgrades or cross-repo overwrites.

Copy into the next session:

> Implement the reviewed Stock Reconciliation count-protection plan using a dynamic workflow. Working repo: /Users/rotiropi/ERPNext-Project/development/frappe-bench/apps/warehouse_app. Read AGENTS.md, TASKS.md, PROJECT_STATE.md, docs/specs/2026-11-05-sr-counted-input-protection-design.md and docs/plans/2026-11-05-sr-counted-input-protection.md, plus the mandatory migration safety references in Task1. Load workflow-authoring before creating a workflow. First recheck Git changes and cloud/local runtime contracts. Scope is warehouse_app ONLY: skip deferred Task4, do not edit POSNext or its local state. Read HANDOFF_POS_NEXT_SR_COUNT_PROTECTION.md as a downstream compatibility constraint. Follow TDD, sequential shared interfaces, isolated warehouse ledger/E2E tests and independent final review. Publish the implemented helper/field contract and revision in the handoff; mark POSNext workflow/timestamp compatibility deferred and production release blocked. Do not silently regenerate confirmation on approval. Do not deploy, alter production scripts or stock, add dependencies, commit, push or touch Backup SIte Production. Report blockers and actual test results. Read the plan's dynamic workflow section for agent budget and phase boundaries.

## Plan Self-Review

- Spec coverage: Tasks2–3 own count/zero/context/async; Task4 owns POSNext callers/workflow; Task5 owns import/install; Task6 owns ledger/security/rollback proof.
- One shared conversion engine and one internal confirmation helper; POSNext is an adapter, not a second implementation.
- No JSON intent expansion; one bounded confirmation fingerprint only. No automatic context re-confirmation on generic Submit.
- Timestamp workflow interaction is an explicit pre-implementation decision gate, not a hidden behavior change. UI scope stays unchanged unless that gate requires approved acknowledgment.
- No current tests, implementation, workflow, deployment or ledger checks are claimed by this document. User selected workflow execution in another session.
