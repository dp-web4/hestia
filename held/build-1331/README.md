# held: #1331 gaps (a)/(b), the secret rule judges a **named** link's resolved target. **NOT applied.**

**Scope (nomad's review, 2026-10-28):** this covers a link that is **named** in the act: a path argument or a
shell word, including chains and directory links. It does **not** cover shapes that reach a link without
naming it: **globs** (`cat note?.txt`, `cat keys/*`), a **`cd` inside the line** followed by a relative
word, and **recursive readers** that follow links (`grep -R`, `rg -L`, `find -L`, the `Grep`/`Glob` tools on a
directory). main allows all of those too; they're recorded against #1331 as follow-ups.

Patch: `held/5e0e7b7932262d251dcccbbb48fe0345ba8ff5dcc8a7960741d207a3dbece8bc.patch` (base main `8f5bd7e2`, after #1427). It covers the gate core, plus the hooks-gt mirror and the 5 manifests. This is the one to apply.

**Re-cut 2026-10-28** from `4aa15bda…` (base `f9f29a23`, kept beside it as a superseded record, like the other shas in `held/`). The only change is the `egress_blobs` anchor, which #1427 made `[egress_command_text(event.command)]`. `link_targets()` still reads the **raw** command, so a link named inside a commit message still has its target judged. That's deliberate: for an innate rule it errs toward refusal. Results on this base:
- `link_target_check.py`: PASS, 6 link rows `egress.secret` and 3 ordinary rows unchanged. The control (main's core) FAILS as designed.
- `tools/egress_prose_test.py` on the revised core: PASS 13/18, so the two changes compose.
- `test_gate_core`: all checks pass.
- Shell-scope battery: 1434/0.

## The defect
The innate `egress.secret` rule (Gate 1a, `egress_blobs`) sweeps paths and the command **as named**. Measured in-process on main `f9f29a23`, through `tools/` fixtures. The "secret" is a fake file in a temp workspace whose path carries the innate `.ssh` token. Inside a granted repo, a link to it:

| act | main |
|---|---|
| shell read of the link, relative name | **ALLOW** |
| shell read of the link, absolute path | DENY `mrh.command` (scope, not the innate rule) |
| `Read` of the link, absolute or relative | **ALLOW** |
| the target by its real path (control) | DENY `egress.secret` |

## The change
`egress_blobs` adds `link_targets(event)`: the resolved target of each path argument, and of each shell word that names an existing path, wherever a link makes it **differ** from the name.
- Relative words are joined onto the event's cwd.
- `--flag=value` contributes its value; a bare flag contributes nothing.
- A path that isn't a link adds nothing, so an ordinary act's verdict can't change.
- It never raises; an unreadable path adds nothing.

`degraded_verdict` uses the same `egress_blobs`, so it gains the same view.

## Evidence (revised core served as `hestia_gate_core`, `run_overlay.py`)
- `link_target_check.py`: **PASS** on the revised core. All 6 link rows are `egress.secret`, including a `--input=<link>` flag value, and the 3 ordinary rows are untouched. On main's core every link row fails except the real-path control.
- Same exit code under both cores:
  - `test_gate_core`
  - `shell_grammar`
  - mechanism 34
  - `seat_gate_boundary` 17×4
  - sprintD 91
  - sprintE 9
  - sprintF 10
  - `governance_closure` 39
  - `cross_harness` 4/4
  - `grant_modes` 17
  - `floor_read_only` 8
  - `nonexistent_path` 8
  - `gate_verdict`
- Shell-scope battery: **1434 / 0** on the revised core (`HESTIA_SCOPE_BATTERY_CORE`).
- `one_gate_decide_contract_test` fails identically under both cores, an artifact of the worktree living under `/tmp`.

## Landing order
This and held #1427 (#1330, `egress_command_text`) both edit `egress_blobs`'s return. Whichever lands second re-cuts with `build_1331.py` / `build_1330.py`. The two changes compose: #1330 narrows what the command text contributes, and this adds link targets, which #1330 leaves untouched.

## Running it
- Cut / re-cut: `transform_1331.py <worktree> <out>`, then `build_1331.py <worktree> <out>`.
- Tests: `run_overlay.py <worktree> <out> <test file>`. Pass an empty `<out>` to run the control on the worktree's core.

After the governed apply, `link_target_check.py` moves to `tools/link_target_test.py` and loads the real module. Until then it has a name `tools/ci_discovery.is_test_shaped` does not match, so CI does not run a held overlay test against the core it was written to fail on (Nova, 10-28).
