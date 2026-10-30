# held: #1331 follow-ups, Gate 1a judges the links an act REACHES without naming them. **NOT applied.**

Patch: `held/138e65d26bea7f50e85c9adf51302a366e7a53e4756d91070d543dedc593b94f.patch` (base main `5bc41374`, after #1433). It covers the gate core, plus the hooks-gt mirror and the 5 manifests.

## The defect
#1433 judges a link's resolved target only when the act **names** the link. Measured on its applied core (10-28, posted on #1331), every *unnamed* shape still reached a secret-named target. The fixture is a fake `.ssh` file in a temp workspace. Shapes that still reached it:
- **globs and braces:** `cat *.txt`, `note?.txt`, `[n]otes.txt`, `keys/*` through a dir link, `sub/*`, `{notes,plain}.txt`;
- **a `cd`/`pushd` inside the line:** `cd sub && cat key.txt`, plus `;`, a subshell, and `pushd`;
- **readers that follow links while walking:** `grep -R`, `rg -L`, `find -L … -exec cat`, `cp -rL`, `tar -h`.

## The rule
`link_targets()` keeps its name and contract. It now returns `link_reach(event)[0]`:
- **Globs and braces:** a glob or brace word is expanded (braces by hand, then the core's own `_glob`, matched with its `_GLOB_CHARS`), and each match is judged as a named path.
- **`cd`/`pushd`:** every relative word is judged against the cwd **and** every directory a `cd`/`pushd` in the line names.
- **Link-following readers** (flags read from each tool's `--help`): the directories they read are walked with `os.walk(followlinks=False)`, and every link inside is judged.
- **Bounds:** 256 glob matches and 10,000 walk entries per act. Past either, `egress_unsweepable_deny` refuses the act under the **existing `mrh.command.unenumerated` rule** with `UNENUMERATED_TARGET`, not judged in part. That's the same fail-closed shape as the scope pass's `SCOPE_JUDGE_BUDGET`. Labelled `egress.secret`, it had relabelled two battery rows that were already correctly refused as unenumerated (`cat /tmp/*/../../etc/hostname`, `S=/tmp/*; cat $S/x`).
- **Over-approximates by design.** shlex keeps no quoting, so a quoted pattern is expanded too, and the `cd` directories apply to every word. It can only *add* refusals, and only where a link really points at a secret-named target.
- **Not covered:** the `Grep`/`Glob` tools. Whether they read through links is the host's, and that's unmeasured (Q2 on #1331).

## Evidence (revised core served as `hestia_gate_core`)
- `held/build-1331f/link_reach_check.py` (27 rows) **PASS** on the revised core:
  - all 15 reach shapes are `egress.secret`;
  - 10 ordinary rows keep main's verdict, including #1433's named link, a glob under the bound, an in-repo non-secret link, `rg` without `-L` and `grep -r`;
  - both overflow rows are `mrh.command.unenumerated`.
- On main's core it fails **exactly** the 15 reach and 2 overflow rows, and no ordinary row.
- `test_gate_core` all pass. `tools/link_target_test.py` 6/3. `tools/egress_prose_test.py` 13/18. Shell-scope battery **1434 / 0**.
- **Latency** (median `evaluate` on ordinary commands over a 200-file repo; scratch fold, 10-29):
  - unchanged within noise without a glob, 0.1 to 0.3 ms;
  - a 200-match glob goes from 0.16 to 4.0 ms, bounded by `LINK_GLOB_LIMIT`.

The check is deliberately not test-shaped (`tools/ci_discovery.is_test_shaped`), so CI doesn't run it against the core it's written to fail on. It moves to `tools/link_reach_test.py` at the governed apply.

## Rebuild
```
python3 held/build-1331f/transform_1331f.py <worktree>         # source-1331f.diff from HEAD's core + new_block.py.txt
python3 held/build-1331f/build_1331f.py <worktree> <out dir>   # core_rev.py + <sha256>.patch, verified
python3 held/build-1331f/link_reach_check.py <out dir>         # PASS; with "" (main's core) it fails the reach/overflow rows
```
