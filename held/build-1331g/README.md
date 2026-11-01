# held: #1435 fixes, the reach check on the applied head. **NOT applied.**

Patch: `held/417465d5a5b00e3db927a1e06bcc651dc4aabb6379558d690c4c98b4ecb628a6.patch`. Its base is the applied #1435 head (`90b74740`). It covers the gate core, the hooks-gt mirror and the 5 manifests.

## What CI found on the applied head (2 defects)

1. **`gate.internal_error` on every single-gate act.** `hestia_single_gate._egress_precheck` passes its `GateEvent` to `core.egress_unsweepable_deny`. A `GateEvent` carries `tool_input`, not `command` or `paths`. That function called `link_reach`, which read `event.command`, raising `AttributeError`, so the gate failed closed. 8 CI files went red. My local suites built `NormalizedEvent`s and never went through the single gate.
2. **An out-of-scope glob lost its escalation** (`one_gate_decide_contract_test` `phantom-glob-still-escalates`, `ls /etc/*`). Before escalating, the single gate re-evaluates with the would-be grant. Under that trial the glob exceeded the 256-match cap, so the act could "never pass", and nothing was escalated.

## The fix

- **`getattr` for `command` and `paths`** in `link_reach`, as `egress_blobs` already does.
- **The overflow refusal moves** out of `egress_unsweepable_deny`, where it ran before the scope pass. It becomes `link_reach_too_wide(event, within)`, called **just before `evaluate`'s final `return ALLOW`**, so it bites only an act the gate would otherwise allow.
  - It is not applied on the unscoped early allow: there `evaluate` isn't the layer enforcing scope.
  - The innate secret sweep in Gate 1a is unchanged.
- **`within`:** the overflow decision counts only globs and walks rooted inside a granted root (from `_scope_parts`: `path:` roots plus granted repos under the workspace). A pattern outside the grants is left to the scope pass and its escalation.
- **`LINK_GLOB_LIMIT` 256 → 2,048.** The match cap only bounds the cheap per-match `realpath`; the work bound is `LINK_GLOB_SCAN_LIMIT` (10,000 entries read). At 256, an ordinary `ls dir/*` over a few hundred entries couldn't pass even under a trial grant.
- **The real bound is now two passes:** the secret sweep and the overflow decision. Per act that's at most 2 × each budget, still strict and enumerable. `tools/link_reach_test.py` asserts it.

## Evidence (fixed core served as `hestia_gate_core`)

- **The 8 CI-failing files** (`run_overlay`; the 2 gemini top-level scripts via a script-forcing copy), each the same as on main's core:
  - `seat_gate_boundary`, `sprintF`, `channel_contract`, `gate_holes`, `reach_domain_contract` and `supersession_hard_stop` all pass, with 0 `AttributeError`;
  - `one_gate_decide_contract`: only the 2 `scope-sinks` rows, which main's core fails identically on Legion (a local /tmp artifact). `phantom-glob-still-escalates` passes;
  - `core_refusal_recorded`: `society.unreachable` on both cores, environmental.
- **`held/build-1331g/gate_event_check.py`:** a `GateEvent` through `egress_unsweepable_deny` returns. It PASSES on the fixed core and on main's, and FAILS on the applied core with CI's exact error.
- **`tools/link_reach_test.py`:** 45 rows PASS. `test_gate_core` passes, `link_target_test` 6/3, `egress_prose_test` 13/18, shell-scope battery **1434 / 0**.

## Rebuild
```
python3 held/build-1331g/transform_1331g.py <worktree>
python3 held/build-1331g/build_1331g.py <worktree> <out dir>
```
