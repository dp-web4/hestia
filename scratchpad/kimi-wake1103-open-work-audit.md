# Hestia open-work audit — 2026-11-03

Scope: all 20 open PRs at audit start and all 325 open issues by number, title, activity, and linked disposition. Every PR's current body, recent review thread, mergeability, and checks was inspected. Issue titles and current links were triaged; the 325 issues are not 325 independently re-verified defects.

## Actions taken in this audit

- Closed #1462 as contained in #1467 (both its head and original #1164 are ancestors of #1467 head 92effaba).
- Opened #1491 for #1475, the parity-corpus expectation mismatch. Test/tooling only; independent review and CI required.
- Updated #1488 to af259ac9 with whole-attempt, committed-feedback, core-generation, and law-door repairs. All 21 focused lib + 4 context controls pass locally; CI and independent final review required.
- Opened #1492 for #1236: full lock-concurrency suite plus new stdin parity control passes.
- Ran the requested pinned synthetic build of #1325's combined candidate b6d09940: all 19 request_load tests passed; no live chain was read.
- Ran #1487 recovery prototype f964d8d3: 8 backup + 6 chain snapshot + 20 affected binary tests passed against synthetic fixtures.

Earlier oldest-five audit: #1164 closed as superseded by #1467; #1275 closed as blocked with #1192 remaining open.

## PR dispositions

| PR | Current disposition |
|---|---|
| #1488 | Actionable: updated to af259ac9. All 21 focused lib + 4 context controls green locally; hosted CI/final review pending. |
| #1487 | HOLD: safe staging direction good; recovery prototype f964d8d3 passes 8+6+20 synthetic tests here. Platform/SQLCipher, caller/privacy and operator decisions remain. |
| #1467 | Draft HOLD: retirement/inventory integration preserved; terminal-witness/outcome recovery unresolved. |
| #1462 | CLOSED in this audit: contained in #1467, not merged. |
| #1454 | HOLD: held gate apply, multi-cd sequential-state over-denial and CI failure; needs recut and governed approval. |
| #1453 | HOLD: consumer-identity bypass independently reproduced; needs new artifact, controls, CI and governed approval. |
| #1428 | Draft dependency stack: request/target validation sound on reviewed delta; normalization hardening candidate and #1426/#1474 stack remain. |
| #1426 | Draft HOLD: #1474 path/repository provenance bug and governed GT update remain. |
| #1423 | Draft HOLD: unknown-field/mixed-version authority semantics need an explicit compatibility decision and raw vault controls. |
| #1421 | HOLD: nearest-versus-union floor rule needs one operator decision shared by daemon and gate, then recut. |
| #1413 | HOLD: conflicting and alternate-channel remedy is not mechanically checkable; needs a governed current-base artifact. |
| #1410 | HOLD: conflicting; parallel-hook contention, seen-before-delivery, pointer rendering and deployment receipt unresolved. |
| #1407 | Cache/source direction reviewed GO; held v5 artifact still needs exact-current-base comparison, installed-executor assessment, CI and fresh operator approval. |
| #1406 | Held stack behind #1407/#1394; peer GO does not authorize application. |
| #1394 | Held stack behind #1407; peer GO does not authorize application or resolve floor/refusal follow-ups. |
| #1328 | Held patch technically passed earlier review, but portable builder/current-base reconstruction, CI and operator apply remain. |
| #1325 | Active review branch b6d09940; 19/19 synthetic tests passed here. Witness-order/key contract review, snapshot/privacy and operator decisions remain. |
| #1323 | Conflicting; vault/mode transition unknown outcomes, witnessing, operator policy and full review remain. |
| #1178 | Conflicting; b1b2cfc0 review candidate needs integration/CI and #1471 recovery protocol. |
| #891 | Draft: parser/publication boundary and historical remeasurement unresolved; current CI alone is not publication evidence. |
| #1491 | Opened in this audit: full 34x4 clean, 28 runner checks, decide 25+31x4; CI/review pending. |
| #1492 | Opened in this audit: full lock-concurrency suite and new stdin parity control green; CI/review pending. |

## Issue-level triage

- **Directly actionable with code/test work:** #1475 (PR #1491), #1488 (updated PR), #1325 (peer build), #1487 (peer build), #1410 (test controls).
- **Held gate application, not ordinary merges:** #1398, #1386, #1330, #1314/#1328/#1329, #1429/#1454, #1407, #1406, #1421. These need exact current-base artifacts and operator-governed application, not branch merges.
- **Protocol/policy decisions before implementation can close:** #1471, #1468, #1421 floor modes, #1323 delegation mode, #1320, #1409, #1408, #1450, #1378, #1332, #825, #824 and related authority/recovery tracks.
- **Security defects with fresh reproduction but no accepted repair yet:** #1474, #1453, #1455, #1479/#1485/#1486, #1483, #1480, #1476 and related vault/projection findings.
- **Mesh/session work in my direct lane but not ready:** #1410/#1389, #1354, #1251, #1236 and older transport/liveness reports. Candidate fixes need concurrency and truthful-outcome controls, not merely local green tests.
- **Older issue stock:** many pre-October issues are evidence records, superseded mechanisms, or unverified historical reports. They need source/current-main falsification sweeps before either closure or implementation; age alone is not a closure reason.

## Completion rule used

A green old head or a clean merge button is insufficient. Merge only with current-head CI, independent NOT-SAME review, no unresolved source HOLD, and any required governed/operator authorization. Close only as an explicit superseded or terminal disposition that leaves the underlying issue/work visible.
