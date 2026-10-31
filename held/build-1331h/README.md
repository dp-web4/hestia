# build-1331h — Nova's #1435 review of 748469d2 (held, not applied)

**Patch:** `held/8ae5488080817a138df9e01d80d4c9e5aaa258438e5b2aac6cc45e2eaf53758d.patch`, transformed from git HEAD `748469d2` by `transform_1331h.py` and built by `build_1331h.py`.

## Finding (Nova, 2026-10-31)

`link_targets` discards `link_reach`'s `too_wide`, so Gate 1a sweeps only the partial target list. The overflow refusal ran only before evaluate's final, scoped allow. Two other paths allowed a reach the gate had checked only in part:
- evaluate's early allow for an authoritative unscoped `*` policy;
- `degraded_verdict`'s READ and read-only-Bash allows.

Both promise that Gate 1a's innate check is never relaxed.

**Reproduced on the applied core** (`every_allow_check.py`, control run): `cat wide/*` past the cap is **allowed** under (b) unscoped and (c) degraded `cat` and `ls`.

## Change (source diff: 11 added lines)

The innate too-wide condition now runs before every allow:
- evaluate's final allow keeps `within` (only reach rooted in the grants counts), so an out-of-scope pattern still reaches the scope pass and escalates;
- the unscoped early allow calls `link_reach_too_wide(event)` with no `within`: an unscoped policy reaches everything;
- `degraded_verdict` computes it once and returns it before either read allow.

No bound changes. Each call is one bounded `link_reach`, the same budget as evaluate's.

417465d5 had removed an unscoped guard on a misdiagnosis. The `ls /etc/*` escalation it seemed to break was the 256-match cap under the single gate's trial grant, which was fixed in the same cut by raising the cap.

## Evidence (revised core via `run_overlay.py`)

| check | result |
|---|---|
| `every_allow_check.py` (a) in-scope, (b) unscoped, (c) degraded `cat` and `ls`, (d) outside the grants, 3 small-glob controls, GateEvent shape | all ok; the control run on 748469d2 fails (b) and (c) |
| `link_reach_test` | 45/45 |
| `link_target`, `egress_prose` | 6/3, 13/18 |
| `seat_gate_boundary` | 17 × 4 |
| `test_gate_core` | all pass |
| `grant_modes_gate_test` | 17 |
| shell-scope battery | 1434 / 0 |
| `gate_event_reach_test` (revised dir) | PASS |

At apply time, `every_allow_check.py` moves to `tools/every_allow_reach_test.py`.
