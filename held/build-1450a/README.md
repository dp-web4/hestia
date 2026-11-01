# build-1450a — #1450 phase 0, step A (held, not applied)

**Patch:** `held/64a30e5f00186c121481199ad4ec6ee3bb078c37902b1699dfcd612763812b0a.patch`, transformed from git HEAD `db1f9de5` by `transform_1450a.py` and built by `build_1450a.py` (the recipe of build-1331h, with `SOURCES` naming the mechanism).

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

At apply time, `session_sent_check.py` moves to `tools/scope_status_session_test.py`.
