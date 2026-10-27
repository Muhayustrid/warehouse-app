# PROJECT_STATE — warehouse_app

Head: 2026-10-27 — **W49 F1 DONE (Order Queue read-only + Dry/Frozen profile)**. Spec `22ff498`, plan `af9090a`. Test site `fulfillment.localhost` runs the same `warehouse_app` code on a separate database; `erp.localhost` and the production stack were not mutated. No push.

## Current

- F1 surface: `/gudang/fulfillment` (SPA queue + right drawer), profile form in Desk, native links to Pick List/Delivery Note/Packing Slip.
- Data path: Sales Order is the queue unit; native documents remain the source of truth. No create/update/submit/cancel or stock movement in F1.
- Test site: `fulfillment.localhost` (ERPNext + warehouse_app), synthetic `ZZTEST W49` company/items/stock and one SO per stage (open/picking/packing/ready).
- Browser acceptance: temporary Stock User, 4 rows, drawer groups and all three native document links, stage/search/date/error/retry/empty states, no horizontal overflow at 1440/1024/390 px, console errors 0. Bundle `index-Chf2Qo-T.js`.
- Evidence: 17/17 classification + 21/21 queue unit tests; profile gate OK; read-only gate OK (no writes, 403 no-role, disabled-profile exception path); W31 gate OK with clean teardown. Test user/session/activity residue 0.
- Local commits: `49c61f1` fixture, `3799d24` profile, `9438d92` native chain, `ba03aa8` pure queue, `07b2202` API, `7148fd0` SPA.

## Next

- F2: Fulfillment Run + request keys + Generate Pick List Dry/Frozen. Build the R0 runtime gate on `fulfillment.localhost` first; no stock-moving code before it is green.
- F3: picking workspace, W31 quantities, batch/serial, short-pick approval, PL submit.
- F4: one DN from two PLs, Packing Slips, verification, DN submit.
- F5: Print Center, assignments, SPA settings, audit, full regression.

## Recently completed

- W48: Close/Cancel RequestDialog resets `v-model`; Clear floatbar aligned; deployed/verified.
- W47: Requests select-all dayhead alignment + floatbar label/button sizing; deployed/verified.
- W46/W45: board grid column parity and mobile toolbar responsiveness; verified.
- W49 R0: native v16/W31 source audit + classification core; docs `FULFILLMENT_R0_DISCOVERY.md`, `IMPLEMENTATION_PLAN_FULFILLMENT.md`.

## Constraints

- Do not edit core Frappe/ERPNext or force native documents through custom fields.
- Production-like `erp.localhost` and stack `1oktober2026` are not test sites for mutations.
- F1 is read-only; full flow (PL/DN/Packing/submit) remains feature-gated and untested until the disposable-site gate is green.
- Commit locally only with user approval; push/merge is separate.
