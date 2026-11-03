# build-1450a — #1450 phase 0, step A (held, not applied)

**Patch:** `held/5fdabcfcc6efbeb3a88f9d44def477cec5d5a287180ec225c1b905b7987b9ec8.patch`, built by `build_1450a.py` (the recipe of build-1331h, with `SOURCES` naming the mechanism) over `65b23db4`, main `827b3e7d` (after #1460, #1435, #1438 and #1464) merged into this branch.

**Re-cut again 2026-11-02 (Nova's HOLD on `2d25a3ab`):** #1464 changed the mechanism and the manifests. The `plugins/_shared` source change is still byte-identical to the one Nova reviewed. The hooks-gt copy differs only in its two `hestia-gt-sha256` header lines, and the manifests only in their hashes. #1464's `endpoint_fallback_test`: 5/5 on the re-cut.

**Re-cut 2026-11-01:** it replaces `64a30e5f…`, which was cut from `db1f9de5` and stopped applying once #1435 changed the per-host manifests. The source change (`source-1450a.diff`, the mechanism section of the patch, and its hooks-gt copy) is byte-identical to the one Nova reviewed on 2026-11-01 at 19:16Z. Only the manifests' `gt_version` lines differ, because they hash the new base.

## Change

The gate's policy-snapshot fetch (`fetch_policy_snapshot`, `plugins/_shared/hestia_gate_mechanism.py`) sends `hestia_scope_status` the session that `hestia_connect` returned. That's the same session it sends `hestia_operating_law` two lines earlier. Source diff: one call gains `"session_id": session_id`, plus a 3-line comment. hooks-gt is regenerated.

**Mixed-version safety:**
- A daemon without step B ignores the field, so behaviour is unchanged.
- A daemon with step B (this PR's `core/src/server/handler.rs`) marks the read `caller_bound: true`.
- The fetch connects with `plugin_id` set to the member it reads for, and `tool_connect` stores that name verbatim (handler.rs:932). So step B's mismatch refusal can't fire on the gate's own read.

## Evidence (revised mechanism via `run_overlay.py`, which now also serves `mechanism_rev.py`)

| check | result |
|---|---|
| `session_sent_check.py`: the real `fetch_policy_snapshot` against a recording fake daemon | PASS; on the base: FAIL (`scope_status` got `{'plugin_id': 'kimi-code'}` only) |
| `hestia_gate_mechanism_test` | 34 OK |
| `grant_modes_gate_test` | 17 OK |
| `seat_gate_boundary_test` | 17 × 4 |
| `test_gate_core` | all pass |
| `shim_structure_test` | 86/86 |
| `link_reach_test`, `every_allow_reach_test` (#1435's, on the re-cut) | PASS, PASS |
| `endpoint_fallback_test` (#1464's, on the re-cut) | 5 passed |

**Applied 2026-11-03** under escalation `a8c1fc5bd170dd7f` (dp), patch `5fdabcfc…`; the applied tree reverses cleanly against it. `session_sent_check.py` is now `tools/scope_status_session_test.py`, run by CI's `tools/*_test.py` glob.
