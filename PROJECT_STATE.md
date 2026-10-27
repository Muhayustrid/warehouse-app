# PROJECT_STATE — warehouse_app

Head: 2026-10-27 — **W50 F2 follow-up committed (`00fd1f9`, `4b6bd45`); fresh whole-branch F2 review still pending**. Test site `fulfillment.localhost`; `erp.localhost` and production stack untouched. No push.

## Current

- F2: all PRD Profile fields live in the existing `/gudang/settings`; core F2 fields are visible, while Warehouses/Print/Policies/Roles are under an Advanced disclosure (closed by default) but still included in the save payload. One Profile per Company; System Manager write; revisioned. Frozen Item Group + optional children = Frozen; every other valid leaf group = Dry.
- Generate: one active Run per SO, DB-unique request keys, 0-1 native **draft** Dry PL and 0-1 **draft** Frozen PL. No picking, PL submit, DN, Packing, print, assignment, or stock movement. Permission: System Manager, or Stock Manager paired with Stock User; Stock User alone is read-only.
- Native split happens before first save by SO Item; stale SO, reservation, missing Item Group, shortage, and second-PL rollback fail closed. Post-save lineage and allocation are verified.
- F1 remains the read-only queue/drawer over native PL/DN/Packing documents.
- Test-stack routing fix: `localhost:8080` now 308-redirects to `fulfillment.localhost:8080`; `erp.localhost` remains separate. The earlier red “DocType Warehouse Fulfillment Profile not found” was the erp site, not F2 data.
- Queue filter follow-up: stage/search/date/Clear are grouped in one filter bar; stage/date apply immediately, search applies on Enter, Clear resets; active filter returns the expected rows.

## Evidence

- Backend gates green at `c6a5a36`: R0 native gate, F2 Profile, Settings API, Schema, F2 Generate, W31, F1 read-only; 58/58 unit tests PASS; no residual Run/Key/test SO after F2 cleanup.
- UI follow-up `00fd1f9` + filter follow-up: Settings shows 6 core fields (Advanced expands 21 fields / 6 sections); queue filter bar groups stage/search/date/Clear and works (In Picking 2 rows, Clear restores 4). No horizontal overflow at 1920/1440/1280/1100/1024/900/768/560/430/390/360; console errors 0. Bundle `index-Cg0nl-FS.js`.
- Site routing verified: `localhost:8080/gudang/fulfillment` redirects to `http://fulfillment.localhost:8080/gudang/fulfillment`; fulfillment API ping 200; erp API ping 200.
- Commits: `c6a5a36` UOM/role/layout F2 review fixes; `00fd1f9` Settings advanced disclosure; `4b6bd45` queue filter bar + rebuilt assets. Earlier F2 task commits remain on `main`; no push.
- R0: split-before-save, short pick, one DN from two PLs, Packing Slip, DN submit/stock, scan-mode rejection, exact teardown.

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
- Commit locally only; push/merge is separate.
