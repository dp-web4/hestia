# held: hestia #1398, a composed read is a read on the read-only floor

**Patch:** `c544b4204f4b3de7df15f2555d68818fb9d5041dd97fc579c66755298c7c7b57.patch`, cut by `build-1398/build_1398.py` on main `95d6d0b7`. It changes `_read_only_admits` in the gate core only, plus its hooks-gt copy and the 5 manifests. **Not applied:** it needs an operator-approved escalation.

**Why.** On 2026-10-25 dp put `shared-context/forum` on the society floor (recursive, `rw`). The daemon serves that read-only, because it's narrower than rwed. cbp-being's `search` of the forum was then refused `mrh.path`, which opened a scope request, and dp gave a live grant to get it working. A narrowed `r` grant on the same path has admitted that search since part B, so the floor's read rule and a grant's read rule disagreed.

**What changes.** The read-only floor admits an act whose path needs only `r`:
- a `READ_ONLY_PATH_TOOLS` reader, as before;
- now also any tool whose `PATH_TOOL_MODES` need is exactly `r`. That's a being's composed `search` and `git_read`, the same rule part B uses for a narrowed grant.

Every writer is still refused.

**Tests**
- `held/build-1398/floor_composed_read_test.py`: `search`, `git_read` and `Read` are admitted through a read-only floor entry; `Write`, `Edit`, `write_note`, `run` and `git_clean` are refused. It passes on the patched core and fails on main. It moves into `tools/floor_read_only_test.py` when applied.
- `tools/floor_read_only_test.py`: the closure guard now covers every tool the floor admits, including composed reads, which must be closure readers (`_READ_PATH_TOOLS` ∪ `_COMPOSED_READ_TOOLS`). It passes on main.
- On the patched copy:
  - grant modes 17/17
  - test_gate_core all pass
  - sprintD 88/0, E 9, F 10
  - mechanism 34
  - grammar
  - seat boundary 17x4
  - closure 39
  - cross-harness 4/4
  - floor read-only 9/9 (with the held case)
  - battery 1434/0
  - decide contract 25 (+29x4)

**Independent of part C (#1394):** part C doesn't edit `_read_only_admits`.

**Not in this change:** serving a narrowed floor entry's `w` (the other half of #1398). That needs the daemon to serve narrowed floor rows by mode and the gate to admit them under #1386's precedence (the floor applies only where no own grant reaches).


**Re-cut 2026-10-27** on main `2b3d0ca2` (after #1412): patch `c544b420…` (the previous `659414ee…` was on `95d6d0b7`; superseded). Sources unchanged, manifests regenerated. Verified on the new main: held test 1/1 (8 verdicts), grant_modes 17, floor 8, nonexistent_path 8, sprintD 91, sprintF 10, mechanism 34, seat boundary 17×4, closure 39, battery 1434/0, decide contract 25 (+29×4).
