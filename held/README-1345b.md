# held: #1345 part B, grant modes at the gate

**Patch:** `63edd85253afaf5265ffd2fba8b8a9dfb539464c922799992b3392d78b84d6fd.patch` (v2), built on main 62dcb09b (#1383 merged with the v1 held files only; nothing applied).

**v2 versus v1 (`e333aa41`).** Two changes, both answering the review on #1383. Nothing else moved:
1. **`scope_roots_with_modes` now lists a narrowed grant on a workspace-direct root** (nomad, point 2). A recursive grant on `<ws>/<name>` maps to the bare repo name `<name>` (`_scope_entry_for_grant`). v1 admitted it at the gate but left it out of this list, which SAGE's dispatcher and run mounts consume. So narrowing cbp-being's `governance/**` to `r` would have been admitted by the gate and refused by SAGE. It is now listed as the recursive root `<ws>/<name>` with its modes. Full repo-name scope is still not listed, because that list also carries declarative repo scope, which the consumer resolves itself.
2. **The path-stage refusal no longer contradicts itself.** When a narrowed grant reaches the path but lacks a mode, v1 said "outside your granted scope: '<seg>' is not granted … Your grant here is narrowed to r". v2 says "beyond your grant's modes: a grant reaches it, but not in the mode this act needs … (missing w)".

**Superseded:**
- `e333aa41….patch` (v1), as above.
- `daaca285….patch`, the same change built on f4e671a9. #1374 then changed the hooks-gt manifests on main, and the stack was re-applied. The gate sources are byte-identical to v1; only the manifest digests differ.
- `21aee711….patch`, the first cut. It mapped no mode to `run`.

All are kept because the safety preset refuses `git rm` of a held patch.

It touches 9 files:
- `plugins/_shared/hestia_gate_core.py`
- `plugins/_shared/hestia_gate_mechanism.py`
- the hooks-gt copies of both
- the 5 manifests

**Not applied.** It needs an operator-approved escalation for the governed write.

## Why

Part A (#1370) gave every grant r/w/e/d modes. To keep a gate that ignores modes from failing open, it served a narrowed grant only in `grants_by_mode`, which no gate reads. So narrowing a grant removed all of its reach (#523).

Measured 2026-10-24 on cbp-being: unticking `d` on its two forum grants and its home grant removed all three from the gate, along with its read-only escalations grant. Its beat's gate scope held one grant, `governance/**`.

This change makes a narrowed grant admit exactly its modes.

## What changes

**Mechanism** (`_fetch_policy_snapshot_uncached`):
- Every `grants_by_mode` row narrower than rwed becomes `{"entry": <in_scope spelling>, "modes": "<canonical subset of rwed>"}` in a new snapshot key, `in_scope_modes`.
- It uses the same `_scope_entry_for_grant` mapping as every other grant.
- Full-mode rows are skipped, because they're already in `in_scope`.
- Malformed rows are skipped.
- An older core ignores the key, so a narrowed grant still admits nothing there. This is the same fail-closed reasoning as `in_scope_read`.

**Core:**
- **New policy field.** `AgentPolicy.mode_scope` is parsed by `_parse_mode_scope`.
  - Each entry is parsed exactly as an `in_scope` entry.
  - Modes must be a non-empty subset of `rwed`. A malformed row is dropped whole, never repaired, and a bare `*` is never honoured.
- **`PATH_TOOL_MODES`** says what each tool's path act needs:

  | Tools | Needs | Why |
  |---|---|---|
  | `READ_ONLY_PATH_TOOLS`, plus a being's composed `search` and `git_read` | r | They only read the path. |
  | `Write`, `write_file` | w | They create or replace. |
  | `Edit`, `MultiEdit`, `NotebookEdit`, `replace` | rw | They read the old text and answer with it. |
  | `write_note` | w | A being's append, edit and retire share this one gate tool, and an append must work on a write-only grant. Its edit receipt quotes only the being's own old text. |
  | `git_restore` | w | |
  | `git_clean` | d | |
  | a being's `run` | re | It reads its script to stage a copy, then executes it. What the run reaches inside its sandbox is mounted from the being's grants by their own modes on SAGE's side (SAGE #521). The gate is handed only the script path, never the bwrap line. |
  | anything not listed (including `Task` and MCP tools) | full rwed grant only | An unknown or new tool fails narrow. |

- **Path stage.** `evaluate` admits a path through a narrowed grant only when every mode the act needs is in the grant's modes, matched with the same `path_in_scope` as any grant.
- **Command stage.** A shell command is not attributed per path yet:
  - The same strict `READ_ONLY_ROOT_VERBS` allowlist as the read-only floor needs `r`.
  - Every other command needs a full grant, so a narrowed grant never widens a command the gate can't fully classify.
  - The floor-read retry and the narrowed retry are one retry, so a read crossing both is judged as one act.
- **Refusals name the missing mode.** When a narrowed grant reaches the path but lacks a mode, the deny says so: "Your grant here is narrowed to r; this act needs w (missing w)." That's the refusal #1345 asked for.
- **`scope_roots_with_modes(policy, ws)`** returns `(root, recursive, modes)` for every path grant, full ones as rwed. A consumer that confines an act after the gate (SAGE's dispatcher and its run sandbox) can honour the same modes.

## Tests: `tools/grant_modes_gate_test.py` (moved from held/build-1345b/ when applied, 2026-10-25)

It has 17 tests through the production composition: daemon answer, then `fetch_policy_snapshot`, then `resolve_agent_policy`, then `evaluate`.
- **v2 core:** 17/17.
- **v1 core (`e333aa41`):** 16/17. The workspace-direct projection test fails, which is the defect v2 fixes.
- **Base core:** 14 fail and 3 pass.
  - The 3 that pass are the invariants that must hold on both cores: a narrowed grant keeps the boundary of any grant, never admits a repo-named call, and full grants are unchanged.
  - Every admission test fails on the base. So every new row separates the two cores.

Added in v2:
- **A narrowed workspace-direct root, end to end** (nomad, point 2). `governance/**` at `r` becomes the entry `governance`. Read is admitted. Write is refused without the words "is not granted" and names `missing w`. `scope_roots_with_modes` lists `(<ws>/governance, True, "r")` and nothing else.
- **An all-modes parent floor never widens an `r`-only child grant** (Nova, #1385).
  - Served the way the daemon serves it, with the parent entry withheld by `floor_for`, the child read is admitted and a child write and a sibling write are refused.
  - The second half pins why the withholding must outlive part B: if the entry were re-served, this gate's union would admit the child write. If that assertion ever starts refusing, the gate caps the floor itself (#1386), and only then may the daemon side be revisited.
  - The daemon half is a Rust test in the #1385 change: `an_all_modes_parent_floor_stays_withheld_over_an_r_only_child_grant`.

What the first 15 cover:
- **Each mode set:**
  - `r` admits every reader and refuses every writer, including shell writes through redirects, `cp`, `sed -i`, `rm`, `tee`, interpreters, `sort -o` and `uniq IN OUT`;
  - `rw` refuses `git_clean` and names `d` as missing;
  - `w` appends but can't read;
  - `d` deletes only.
- **`run`:** `re`, `rwe` and `red` admit it; `r`, `e` and `rw` refuse it, naming the missing mode.
- **Tools with no nameable mode** need a full grant.
- **Malformed rows** read as no grant, both in the mechanism and in the core.
- **Boundaries:** a sibling prefix, the parent directory, and an exact narrowed grant's child are all refused.
- **A shell write under an `rw` grant** stays full-grant-only.
- **A read crossing the floor and a narrowed grant** is admitted as one act. Crossing out of both is refused.
- **`scope_roots_with_modes`** output.
- **Every tool mapped to r** is a closure reader (`_READ_PATH_TOOLS` or `_COMPOSED_READ_TOOLS`).

Existing suites on the patched copies match the base core exactly:
- `test_gate_core`: all checks pass
- sprintD 88/0, sprintE 9, sprintF 10
- mechanism 34
- shell grammar
- seat boundary 17x4
- governance closure 39
- cross-harness closure 4/4
- floor read-only 8/8
- shell-scope battery 1434/0
- decide contract 25 (+ shim parity 29x4)

## A being's `run` while it holds an `r`-only grant (nomad, point 3)

SAGE composes `run` into a sandbox line (`run_command`) that names every grant it mounts, `r`-only grants as `--ro-bind`. Whether that line is judged depends on the stage:
- **Single gate (live since #934 / #1231).** `being_gate_client.gate()` hands `decide()` the being's raw arguments, with the script `path` rooted in its home. The composed line is recorded on the verdict as `command` but never judged. The act is the `run` tool on the script path, which needs `re` (`PATH_TOOL_MODES`). cbp-being's home grant is `rwe`, so it is admitted. An `r`-only grant mounted read-only is not part of the judged act, and never forces a full grant.
- **Legacy local-law stage** (only if the single gate fails to import). `core.evaluate` judges the composed line at the command stage. `bwrap` is not a read-only verb, so `_command_mode_need` is `""` and only full grants admit the paths the line names. While an `r`-only grant is mounted, a run is refused there. That fallback fails closed, never open. The cost is that runs stop until the single gate is back, which is visible and reported.

So point 3 is settled, and nothing in this change needed to move. A SAGE composition test for both stages belongs with SAGE #533, which is what feeds `r`-only grants into the mounts.

## Not in this change (follow-ups)

- **Per-path modes inside a shell line.** Write, delete and execute positions are classified by the closure but not yet mapped per path to modes, so any non-read command needs a full grant.
- **The gate-opened scope request should carry the mode the refused act needed**, so the decider sees "asks for w".
- **The narrowed floor.** The daemon still withholds floor entries narrower than r (`floor_for`). With per-mode admission it could serve them by mode.
- **SAGE's side.** `being_gate_client._granted_reach` should use `scope_roots_with_modes`, and the dispatcher's own confinement should require w for a write. Otherwise a narrowed grant the gate admits is refused at the dispatcher. That's SAGE #533 (draft, inert until this is applied). With v2, a narrowed workspace-direct grant reaches #533 through `scope_roots_with_modes`, so #533's `_repo_name_roots` needs no change for it.
- **Nearest explicit grant decides (#1386).** This change is still union semantics among a member's own grants: a narrowed grant nested under a full one is ignored. dp ruled on 2026-10-24 that the nearest explicit grant decides.
- **Floor withholding wording (#1385).** The daemon change ships separately and needs no gate edit.

## Rebuild and measure

```
python3 -I held/build-1345b/build_1345b.py <hestia worktree at the base> <out dir>
```

- **Re-applying the source diff:** `source-1345b.diff` (the change, against f4e671a9) is applied offset-tolerantly, and each hunk must match exactly once.
- **Output:** neutral-named copies plus `<sha256>.patch`.
- **Verification:** the result is checked in memory.
- **After #1375 and #1381 merge,** re-run it on main for the apply.

— cbp-claude
