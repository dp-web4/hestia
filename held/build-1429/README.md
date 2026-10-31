# held: #1429, a relative word landing inside the workspace after `cd` gets the in-workspace rule. **NOT applied.**

Patch: `held/79b60b56ca42c39940df3c833ca563af846ac60328ebeb542a240a781de0c223.patch` (base `4a775cd1`): the gate core, plus the hooks-gt mirror and the 5 manifests.

## The defect (measured offline on McNugget, 2026-10-30, against the gate's own `command_scope_reach`)
The same venv binary in a granted repo gets opposite verdicts, depending only on how it's spelled:

| command | today |
|---|---|
| `<ws>/membot/.venv/bin/python -c 1` | allowed (pass 1, #953's link allowance) |
| `membot/.venv/bin/python -c 1` (cwd = ws) | allowed |
| `cd <ws>/membot && .venv/bin/python -c 1` | **refused, `/usr/bin/python3`** |

That's HUB's report on #1429, where dp had to grant `/usr/bin/python3.14`.

**Mechanism.** In pass 3 of `_command_scope_reach_one`, a `dir` candidate (a relative word landing under a `cd` target) had **no inside-the-workspace branch**. It went straight to `_outside_reach_refused`, which realpaths the landing and judges the target as if it were outside the workspace. #953's link allowance never applied to that spelling.

## The rule
In the `kind == "dir"` branch, a landing **inside** the workspace is judged by pass 1's rule for an in-workspace token:
1. **Egress first:** `_symlink_target_forbidden`. A link into `.ssh/…` stays refused.
2. **The grant:** if the landing's repo segment is not granted, `_symlinked_reach_verdict` decides (and names the right repo).
3. **A link inside a granted repo is judged where it lands** (`_symlinked_reach_verdict`). A target in an ungranted repo is refused, as today's outside rule refused it. A target outside the workspace gets #953's allowance: that's the venv interpreter.

Landings **outside** the workspace keep today's rule (`cd /tmp && cat ../etc/x` is still judged at `/etc/x`).

## Evidence (revised core served as `hestia_gate_core`)
- **`held/build-1429/dir_landing_test.py`: PASS** (4 allow, 4 deny). On today's core it **fails exactly the 3 relative-after-`cd` allow rows** (all refused as `/usr/bin/python3`) and denies all 4 controls.
  - Allow: the venv interpreter by absolute path (unchanged); `cd <repo> && .venv/bin/python`; `./.venv/bin/python`; a plain in-repo file after `cd`.
  - Deny: a link to a forbidden `.ssh` target after `cd` (egress first); a link from a granted repo into an ungranted one; an ungranted repo after `cd`; a `../..` escape out of the workspace.
  - The fixture is built beside the test, not under a temp root (temp roots are always reachable, which would make every row pass), and removed afterwards.
- **A first cut was wrong and the test caught it.** It skipped every check when the landing's own repo was granted, which let `cd <granted> && cat ./peek` (a link into an ungranted repo) through. Today's core refuses that. Step 3 above closes it.
- Shell-scope battery: **1431 / 3 on both cores**, with the same 3 rows (macOS `/var/folders` temp cases on this box).
- All 116 `plugins/_shared/*test*.py` + `tools/*_test.py` under both cores: **114 identical**. The 2 that differ are `hooks_gt_test` / `hooks_gt_candidate_test`, which report the core as *unpublished* under the overlay; this patch's own mirror satisfies them.

## Sequencing
#1453 (#1330's second half) and #1435 (Legion) are also held Gate 1a patches carrying the same mirror and manifests. Whichever lands later must be re-cut on the new main (`build_1429.py <worktree> <out>`). The core hunks don't overlap.

## Running it
- Cut / re-cut: `build_1429.py <worktree> <out>`. It reads `source-1429.diff`.
- Tests: `python3 held/build-1429/dir_landing_test.py <dir with core_rev.py>`; with no argument it loads the real module.
