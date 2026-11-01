# build-1450a — #1450 phase 0, step A (held, not applied)

**Patch:** `held/2d25a3abefbcb49d18dc683fc2169b8fb00bf9d524ab6c65d8108e4c6c6911ea.patch`, built by `build_1450a.py` (the recipe of build-1331h, with `SOURCES` naming the mechanism) over main `05615183` (after #1460, #1435 and #1438 merged).

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

At apply time, `session_sent_check.py` moves to `tools/scope_status_session_test.py`.
