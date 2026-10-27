# PROJECT_STATE — warehouse_app

Head: 2026-10-27 — **W50 F2 DONE (Settings Profile + Fulfillment Run + Generate draft Dry/Frozen Pick Lists)**. Spec `1028181`, plan `2389066`. Test site `fulfillment.localhost`; `erp.localhost` and production stack untouched. No push. Fresh whole-branch F2 review pending.

## Current

- F2: all PRD Profile fields live in the existing `/gudang/settings`; one Profile per Company; System Manager write, Stock Manager/User read. Frozen Item Group + children = Frozen; all other valid groups = Dry.
- Generate: one active Run per SO, DB-unique request keys, 0–1 native **draft** Dry PL and 0–1 **draft** Frozen PL. No picking, PL submit, DN, Packing, print, assignment, or stock movement.
- Native split is done before first save by SO Item; stale SO, reservation, missing Item Group, shortage, and second-PL rollback fail closed.
- F1 remains the read-only queue/drawer over native PL/DN/Packing documents.
- Test site no longer throws handover-field errors when `Manufacturing Settings` is absent; production path is unchanged when the fields exist.

## Evidence

- Final gates green: R0 native gate, F2 Profile, Settings API, Schema, F2 Generate, W31, F1 read-only; 57/57 unit tests PASS; teardown residue 0.
- R0: split-before-save, short pick, one DN from two PLs, Packing Slip, DN submit/stock, scan-mode rejection, clean teardown.
- Browser: generated `WFR-2026-00001` with Dry/Frozen draft PLs from `SO-OPEN`; queue refreshed to In Picking; Run/PL links work. Responsive 1440/1024/390 with no horizontal overflow; Settings console errors 0. Bundle `index-D6DfeYxq.js`.
- Commits: `48d9f1c` R0 gate, `3680252` profile, `96c309e` Settings API, `5684566` Settings UI, `c265193` Run/Key schema, `643228b` pure planning, `e0b7e1c` idempotency, `36665ee` native Generate, `0e1db2c` Run child tables, `a81dbe8` handover guard, Task 9 UI (next).
- Visual check finds no overflow; drawer stacks at 560px; queue page head stacks at 820px; Settings fields stack at 820px.

## Next

1. Run one fresh whole-branch F2 review; fix Critical/Important findings and record rulings/minors.
2. F3: picking workspace, W31 quantities, batch/serial, short-pick approval, PL submit.
3. F4: one DN from two PLs, Packing Slips, verification, DN submit.
4. F5: Print Center, assignments, full settings hardening, audit, complete regression.

## Recently completed

- W49 F1: read-only Order Queue, classification, profile, native document links; gates/browser green.
- W48/W47: request dialog reset, Clear floatbar, table alignment, mobile toolbar parity.

## Constraints

- Do not edit core Frappe/ERPNext; do not force native documents through custom fields.
- Product F2 creates draft PLs only; R0 test fixture is the only stock-moving path.
- `fulfillment.localhost` is disposable; `erp.localhost`/`1oktober2026` are not mutation targets.
- Commit locally only with user approval; push/merge is separate.
