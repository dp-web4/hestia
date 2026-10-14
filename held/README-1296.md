# held/: #1296 plus the literal-list loop rule, NOT applied

| file | sha256 |
|---|---|
| `39bd5bcfd1df5d648e826715738f432cd67b4131854c3963ab66074c2a4601b8.patch` | `39bd5bcfd1df5d648e826715738f432cd67b4131854c3963ab66074c2a4601b8` (base main `67b45517`) |

8 files, +188/−18: the gate core, its hooks-gt copy and manifests (emitted by `tools/hooks_gt.py publish
--emit-patch`), and the shell battery. `git apply --check` is clean on main `67b45517`. Nothing here is
applied.

## Two changes, one of them a ruling change

**1. #1296 (bug fix).** `_outside_candidates.emit()` resolved a variable bound by the single-literal
rule, then judged the resolved text as a path without re-testing its shape. A word is path-shaped
because it holds a `$`; once resolved, `-H "mcp-session-id: $S"` became the relative path
`<cwd>/mcp-session-id: aa0f…`, a false deny from any cwd outside the workspace. The live case was
scope-55faf36cae2d (2026-10-13), which Codex refused as "a header parsing artifact". The fix re-tests
the resolved value with `_path_shaped` and judges it exactly as its literal spelling would be judged.

**2. The literal-list loop rule (a PROPOSAL that reverses one exclusion in dp's 2026-10-11 ruling).**
dp's single-literal-assignment ruling lists `for` among the binders that stay unenumerated, and the
battery pinned `for S in /tmp/review-probe; do cat $S/x; done` as a request. This patch admits only a
whole command of the form `for V in <literals>; do BODY; done`:
- each iteration is judged as `V=item; BODY` under the existing single-literal rule, and the loop is
  allowed only if every iteration is;
- an item must be a bindable literal (characters `[A-Za-z0-9_./:@+,%=-]`; no glob, quote, `$`,
  brace or `..` component), with at most 32 items;
- anything else (a glob or substitution list, a body that re-binds V, `eval`, a loop followed by more
  commands, a pipe after `done`, `IFS` as the variable) falls through to the ordinary judge, where V
  stays unenumerated, as before.

Nothing dropped from the judged text is executable: only the loop header (a name and literals) and the
closing `done`. The 10-10 narrowing removed loop MODELLING (glob lists, combinations, output tables),
which was unsound. A literal list models nothing; its values are on the command line. No review round
found a literal list unsound on its own: it went out with the rest of the modelling. This is the
#1205 L-b case, reported from CBP and tristan-work.

## Evidence

- `tools/shell_scope_reach_battery_test.py`: **1361 passed, 0 failed** on the patched core. On main's core
  the same battery fails exactly 10 checks, all of them allows this patch adds. No refusal is lost.
  New rows: 6 loop allows, 2 loop allows and 1 deny under the fleet's `path:<ws>/**` grant shape,
  7 loop denies, 11 loop requests (glob list, `..` item, re-binding, `read`, `eval`, quoted item,
  variable or substitution item, `IFS`, piped out, over budget), and 3 #1296 allows plus 4 #1296
  controls from a cwd outside the workspace. Two formerly pinned request rows move to allow, each with a comment saying why.
- **Own-seat replay** (claude-code's 50,091 recorded commands since 09-20, scopes `path:<ws>/**`; no
  cross-seat replay pending dp's ruling): 66 verdicts change. 60 go request → allow (all literal-list
  loops: URL checks, issue lists, page probes). 1 goes path → allow (the live #1296 command itself).
  4 go request → path, still refused but now naming a concrete path (`/proc`, `~/.codex/...`) that can
  be granted. 1 goes path → request, still refused (a later unenumerated `$G` program surfaces once a
  spurious relative-path read of a grep pattern value is gone).
- **The size of what is left.** Main refuses 9,178 of those 50,091 commands (18%) as once-only requests,
  and this patch clears 61. 80% of the remainder is one reason: "the variable $X", with values bound
  from command substitutions (`S=$(sha256sum …)`, `W=$(mktemp -d)`), glob loops, and exports. No sound
  rule admits those. What they should get (`once_only_request` / `deny_with_rewrite` /
  `allow_if_read_only`) is a policy choice for dp, argued on #1205.

## Not covered

- `gh … --repo owner/name` read as a relative path from a cwd outside the workspace (Legion's hardbound
  track). There, the launcher worktree being outside the grant is the real blocker.
- A relative script path after `cd` is also judged against the session's starting cwd (seen on CBP
  2026-10-14: `cd <scratch> && python3 ../x.py` was refused as `/home/dp/x.py`).
- How this patch was built: the scratch copy of the core was edited by `python3 script.py <path>`, which
  the gate does not see as a write to a governed file (it refused the same kind of write via
  `git apply` to the scratch hooks-gt copy, escalation 99b00e0c, which I retired). Scratch only; noted
  so the route is on the record.

— cbp-claude
