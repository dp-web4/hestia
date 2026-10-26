# held: hestia #1386 (part C), the nearest explicit grant decides

**Patch (v2):** `74d6c840bb8452420554eb5ec798e503304fa3b68110cf66b524727e15b56cd4.patch`, cut by `build_1386.py` on main `95d6d0b7`. Supersedes `0f34c83d…` (v1), which judged only the path an act names: nomad's HOLD showed an act on a parent reaching a narrowed child (`Grep proj` reading a write-only child; `find proj -exec sed -i …` rewriting a read-only one). v2 adds the descendant check below.

**Not applied.** It needs an operator-approved escalation for the governed write, after review of the design (#1386) and this code.

## The rule

dp, 2026-10-24: "if a specific path is reachable via an explicit grant, then that grant prevails for that path (basically standing as separate governance path from nested). for paths with no direct grant, the shortest nested grant applies", then "if explicit grant, use explicit grant; else traverse to ../ and repeat".

Every grant is a **node**:
- each full `path:` root in `scopes` (rwed), including floor entries the daemon served and repo-name entries (`<ws>/<name>`, recursive);
- each part B narrowed grant (`mode_scope`), with its modes.

The deepest node covering a path decides it. An exact grant covers only its own path; walking up, only recursive grants apply. Grants on the same node union. The act is admitted only if every mode it needs (`PATH_TOOL_MODES`, rwed for a tool with no nameable mode) is in that node's modes.

**Unchanged:**
- the member's home markers and temp roots, which are admitted before any grant;
- repo-named calls (Gate 1b, #1393): only full recursive grants;
- paths no grant node covers, which keep today's order (the read-only floor for readers, then refusal).

**Fast path.** Nothing is computed unless some narrowed grant lies at or beneath another grant node (`_precedence_matters`). Without that nesting, the nearest grant is the union, and every verdict is exactly part B's. The fleet has no such nesting today.

**The floor.** All-modes floor entries ride `scopes` like the member's own full grants. That's safe because the daemon withholds any floor entry that overlaps a narrowed grant in either direction (`floor_for`, pinned by #1387). With part C the gate would also cap a re-served entry by itself. The two guards are independent, and removing either is its own reviewed change.

## v2: an act on a parent cannot reach a narrower child

An admitted act that can reach below the path it names must also satisfy every narrowed grant node strictly beneath that path (`_narrowed_beneath`); otherwise it is refused, naming the child. Only `SINGLE_TARGET_TOOLS` (Read, read_file, NotebookRead, Write, write_file, Edit, MultiEdit, NotebookEdit, replace, write_note, run) are exempt, because they act on exactly the path they name. Every other tool (Grep/Glob/search and the other directory readers, git_restore/git_clean, any unknown tool) and every shell line is checked: for a shell line, each reached path's narrowed descendants. This matches SAGE #533's run mounts under the nearest rule (a stricter child is bound after its parent; a child without `r` is masked).

## Shell commands

A command that `command_scope_reach` admits is then judged path by path, with the nearest grant for each path it reaches:
- a command on the read-only allowlist needs `r` there;
- any other command needs rwed, as in part B.

The reached paths are enumerated with the same resolver that admits the command, so there is no second parser:
- each refusal names the path it refused, which is then granted exactly (recursively, if exact is refused again) and the check re-run, bounded by `SCOPE_JUDGE_BUDGET`;
- a line whose reach can't be named in full is refused, fail narrow, but only while a narrowed grant is nested.

## For consumers

`nearest_grant_modes(policy, workspace, path, cwd=None)` returns the gate's own answer: the modes of the nearest covering grant, or None. SAGE's dispatcher (#533), run mounts (#521) and reach answer (#532) should use it, or the same walk over the `(root, recursive, modes)` triples, once the core exports it. Until then they combine grants the way part B's gate does, so the gate and the dispatcher never disagree.

## Tests

`held/build-1386/grant_precedence_gate_test.py`, 9 tests through the production composition (part B's harness):
- **Part C core:** 9/9.
- **Part B core:** 7 fail. The 2 that pass are the invariants that hold under both: a read-only umbrella never erases a full child, and with no nesting nothing changes.

The 9 cover:
- a narrowed child caps a full parent;
- the umbrella case;
- nearest beats union between two narrowed grants;
- an exact grant decides only its own path;
- grants on one node union;
- a shell write into a capped child is refused, while a read there and a write elsewhere are admitted;
- workspace-direct (bare-name) roots in both directions;
- no nesting, no change;
- `nearest_grant_modes`.

Part B's held test `test_an_all_modes_floor_never_widens_a_narrowed_child_grant` is now core-aware. Its last assertion expects the union to widen on part B, and the gate to cap a re-served floor entry on part C. Part B's 17 pass on both cores.

Existing suites on the part C copies match the base: see the PR description for the run.
