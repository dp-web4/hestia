# held: #1411, existence first (no escalation for a read of a nonexistent path). **NOT applied.**

dp, 2026-10-26: *"we should not be doing escalations on nonexistent paths because there is nothing to
escalate - it's just noise"*; *"we should be checking existence first"*; *"the not visible to you should
only come on an existing path thats off limits"*; *"how is mkdir or a new file write handled"*.

Patch: `held/e1b2dba5c17d7f9b8dde378734f9c39629c6bdab164abf952711a1485477d357.patch` (base `95d6d0b7`).
It covers the gate core and `test_gate_core.py`, plus the hooks-gt mirror and manifests.

## The rule
| act | path | result |
|---|---|---|
| read (`PATH_TOOL_MODES == "r"`) | does not exist | **`mrh.path.nonexistent`**: "does not exist … no scope request was opened", plus a did-you-mean when a member's grant root, re-rooted, names an existing path. **Not** in `SCOPE_ESCALATING_RULES`, so nothing is opened |
| read | exists, off limits | `mrh.path`, unchanged: the ordinary refusal, and a request opens |
| read | does not exist, inside a grant | allowed by the gate; the tool reports not-found |
| write / create (any mode but plain `r`) | anything | `mrh.path`, unchanged. Creating a new file, even in a new directory, is a real ask |

The did-you-mean looks at every grant the member holds (full, read-floor, narrowed). The being's
snapshot grant is a narrowed `r` grant, which never appears in `scopes`. Measured case:
`<ws>/hestia/governance/hestia/hooks-gt/_shared/x` → "did you mean `<ws>/governance/hestia/hooks-gt/_shared/x`?"

**Not in this patch:** `mrh.command.nonexistent` (#1327, the shell path) refuses `mkdir -p a/b/c`
with no request when `a/b` doesn't exist. That's a create, so by the rule above it should be a real
ask. Noted on #1411 for its own change.

## Fixtures
Existing rows that assert the ordinary refusal read paths that were never created. Under
existence first those would test the new rule instead, so they now create the path first:
- `test_gate_core.py` (governed, in the patch): 4 inserts, by `fix_fixtures.py`.
- `tools/grant_modes_gate_test.py` and `tools/floor_read_only_test.py` (not governed, committed here):
  a `materialize` step in `_verdict`, which the #1411 rows switch off.

Both pass on main's core unchanged (control run).

## Evidence (main tree, revised core overlaid)
- `nonexistent_path_gate_test.py`: **6 pass**; on main's core it fails (`rule — mrh.path`).
- `test_gate_core.py` with fixtures: all checks pass, on both the revised core and main's core.
- grant_modes 17, floor_read_only 8, sprintD 88, sprintE 9, sprintF 10, mechanism 34, shell_grammar,
  seat_gate_boundary 17×4, governance_closure 39, cross_harness 4/4: **all pass, same as main**.
- shell-scope battery 1434/0; decide() contract 25 (+ shim parity 29×4).

## Running it
- `run_tg.py <worktree> <dir with core_rev.py, mech_rev.py, tg_rev.py>` runs the fixtured
  test_gate_core as if it sat in `plugins/_shared`, with the core's source reads redirected too.
- Other suites: overlay the copies under the real module names (as `held/build-1386` does) and run each file.
- Re-cut after main moves: `build_1411.py <worktree> <out>`.

**Landing order:** this touches the gate core like #1394/#1406, and all of them touch the
manifests. Whichever lands first, the others re-cut by script (see #1394's landing-order comment).
