# held: #1345 part B, grant modes at the gate

**Patch:** `daaca28580977a4a9ee385c1c9c3c923a1acfd5cf3d9ef40bce3247a9deaa81f.patch`, built on cbp/floor-modes f4e671a9 (#1381).

**Superseded:** `21aee711….patch`, the first cut. It mapped no mode to `run`. Kept because the safety preset refuses `git rm` of a held patch.

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

## Tests: `held/build-1345b/grant_modes_gate_test.py`

It has 15 tests through the production composition: daemon answer, then `fetch_policy_snapshot`, then `resolve_agent_policy`, then `evaluate`.
- **Patched core:** 15/15.
- **Base core:** 12 fail and 3 pass.
  - The 3 that pass are the invariants that must hold on both cores: a narrowed grant keeps the boundary of any grant, never admits a repo-named call, and full grants are unchanged.
  - Every admission test fails on the base. So every new row separates the two cores.

What the 15 cover:
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

## Not in this change (follow-ups)

- **Per-path modes inside a shell line.** Write, delete and execute positions are classified by the closure but not yet mapped per path to modes, so any non-read command needs a full grant.
- **The gate-opened scope request should carry the mode the refused act needed**, so the decider sees "asks for w".
- **The narrowed floor.** The daemon still withholds floor entries narrower than r (`floor_for`). With per-mode admission it could serve them by mode.
- **SAGE's side.** `being_gate_client._granted_reach` should use `scope_roots_with_modes`, and the dispatcher's own confinement should require w for a write. Otherwise a narrowed grant the gate admits is refused at the dispatcher. That's SAGE #533 (draft, inert until this is applied).

## Rebuild and measure

```
python3 -I held/build-1345b/build_1345b.py <hestia worktree at the base> <out dir>
```

- **Re-applying the source diff:** `source-1345b.diff` (the change, against f4e671a9) is applied offset-tolerantly, and each hunk must match exactly once.
- **Output:** neutral-named copies plus `<sha256>.patch`.
- **Verification:** the result is checked in memory.
- **After #1375 and #1381 merge,** re-run it on main for the apply.

— cbp-claude
