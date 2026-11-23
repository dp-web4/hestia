# held/: hestia#1317 (glob variant): a glob after `cd D &&` is judged at the event cwd. NOT applied

| file | sha256 |
|---|---|
| `4007c23c73bf08aa0fbf45a0396cb7b2158322751eec8fc2b2c0bbe8f86fa94c.patch` | `4007c23c73bf08aa0fbf45a0396cb7b2158322751eec8fc2b2c0bbe8f86fa94c` (base main `480279d3`) |

## The defect

After `cd D &&`, an unquoted relative glob is judged as if it expanded in the hook event's cwd. When that
cwd is outside the grant, the act is refused, and a peer-ruled scope request opens for a directory that
does not exist.

**Live on McNugget (claude-code, `v0.3.0-118-g480279d3`, 2026-11-16 ~11:35Z):**
- **act:** `cd ~/repos/hestia && ls tools/*hooks_gt_store*`
- **deny:** `mrh.command`, refused as `~/ai-workspace/tools/*`. That is the event cwd, and `~/ai-workspace/tools` does not exist.
- **opened:** scope-0c520c5ed9ab

This is the same shape reported on #1317 on 2026-11-13 (scope-e8534ae6a99a). A plain relative path in the
same position, `cd ~/repos/hestia && cat tools/x.py`, was already allowed.

## The cause

The cause is one line in pass 3's relative vote (`_command_scope_reach_one`). An interpretation of a
relative spelling is judged only if it could name something:

- **Plain path:** judged when its parent directory exists. This was already correct.
- **Glob:** its probe is `<dir>/*`. The check stripped the `*`, then took the dirname of `<dir>`, which is
  one level too high. So `<cwd>/tools/*` was judged because `<cwd>` exists, even though `<cwd>/tools`
  does not.

The defect hides under a bare segment grant, because the granted repo root joins the vote's bases and
votes the glob in scope. Every live seat holds `path:` grants, which add no base, so only the event cwd
votes.

## The change (`hestia_gate_core.py` only, one condition)

For a glob, the anchor is the glob's own directory (`probe[:-2]`). Plain paths are unchanged (dirname).
A glob expands only inside its own directory. Where that directory does not exist, the shell passes the
word through literally and nothing is reached. This is the same reasoning the plain-path rule already
applies.

**Nothing is loosened:**
- **Existing outside directory:** an interpretation whose directory exists outside the grant is still
  refused, with or without a `cd`.
- **The `cd` target itself:** it is still judged strictly (`kind == "dir"`, unchanged).
- **Must-deny row that now votes correctly:** under a segment grant, `ls secret/*` with `<cwd>/secret`
  existing outside the grant used to pass, because the missing `<repo>/secret` voted in scope. It is now
  refused. The test pins this row.

## Tests: `tools/gate_glob_after_cd_test.py` (new, 12 rows, `path:` grant plus 2 segment-grant rows, temp-root admission off)

- **4 must-allow rows:**
  - the #1317 act;
  - a bare `dir/*`;
  - a deeper glob;
  - the 11-13 shape, where a later `&& cd` governs the glob.
- **2 controls:** a plain relative path, and an absolute glob inside the grant.
- **4 must-deny rows:**
  - a glob climbing out of the `cd` target to an existing outside directory;
  - a glob whose directory exists at the event cwd, with no `cd`;
  - an absolute outside glob;
  - a plain `../` escape.
- **2 segment-grant rows:**
  - must deny: a glob whose directory exists only at the event cwd;
  - must allow: the `cd`-then-glob act.

**Results:**
- **Unpatched core (480279d3):** 4 failing: the three #1317 rows (it refuses `<cwd>/tools/*`, exactly as
  the live gate does) and the segment-grant must-deny.
- **Patched core:** PASS, 0 failing.

**Regression, against the staged core (`HESTIA_SCOPE_BATTERY_CORE`), on McNugget (macOS):**
- **Pass:** the five held batteries (#1595, #1594, #1560 at 67/67, #1583, #1598), plus
  `gate_evaluate_test`, `gate_parity_runner_test`, `scope_fork_differential_test` and the other
  `gate_*` tests.
- **Two batteries fail identically on the unpatched base, so not from this change:**
  - `gate_grep_patterns_and_toolchain_grant_test` (2 substitution rows);
  - `shell_scope_reach_battery_test` (3 `/var/folders` temp-root rows).

Both look like macOS environment rows.

## Apply

```
python3 held/build-1317/build.py <worktree at main> <EMPTY out dir>   # re-cut if main moved; prints the sha
git apply --check <out dir>/<sha>.patch && git apply <out dir>/<sha>.patch
python3 tools/gate_glob_after_cd_test.py                               # PASS: 0 failing
```

The patch touches the gate core, its hooks-gt copy and the five manifests (governed paths), and adds the
test.

**Out of scope:** the `../` escape variant on #1317 (`cd D/child && python3 ../script.py`, which is judged
at the event cwd). It is a separate line (pass 3's `bases` exclude `dir_bases`), and its fix changes which
interpretations vote. That deserves its own review.
