# held/: hestia#661, relocating an ancestor of the closure is a write. NOT applied

| file | sha256 |
|---|---|
| `1cd61d0658c2c1f6a8d93bcf0984d311cd8c533d600e3565aa31d9832c8a4b1d.patch` | `1cd61d0658c2c1f6a8d93bcf0984d311cd8c533d600e3565aa31d9832c8a4b1d` (base main `59f2478eb70314a26c1538c166d9e938738e73fc`) |

## The defect

Directory markers asked only whether a target was inside the protected directory. `mv plugins/kimi`, `mv plugins`,
and `git checkout -- .` could therefore relocate or overwrite every hook and the shared closure without a write
verdict or even a marker.

## The change

- In write position, a proper prefix of a directory marker now matches in normalized absolute and relative form:
  `plugins` and `plugins/kimi` prefix `plugins/*/hooks`, including absolute paths and `..` spellings. Case-folded
  comparison also covers case-insensitive filesystems conservatively; on a case-sensitive host this can over-refuse
  a case variant, never silently allow it.
- Realpath resolution covers symlinked ancestors. Relative inputs are normalized without consulting the gate
  process's cwd, so an unrelated root cannot inherit the running repository's closure.
- An existing absolute directory is also checked for the marker's literal leading directory. That catches a repo
  root used as a pathspec, including `git checkout -- .` and `git -C <root> checkout -- .`, without expanding
  globs or inventing a root for a directory that does not exist.
- `cp -r` destination ancestors are covered too, so duplicating a governance tree to an unprotected name is not
  silently admitted. Existing descendant matching is unchanged, and read position does not use the new arm.

## Scope limits

Grandparent moves above a recognized root and whole-tree rewrites that name no pathspec remain out of scope:
`git reset --hard`, branch checkout, merge, pull, stash, and archive extraction need separate treatment. This patch
does not claim every possible ancestor or repository mutation is covered.

## Verification

On base `59f2478e`, with the generated closure loaded from the scratch overlay:

- `hestia_governance_closure_test.py`: **PASS, 40 tests**. Ancestor moves/copies, absolute and `git -C` checkouts,
  case-folded and `..` forms, symlinked ancestors, unrelated-root, read-side, and ordinary `/tmp` controls all
  pass. The unpatched control fails on the first ancestor move.
- `closure_output_writes_test.py`: **PASS, 4 tests / 103 write-read pairs**.
- `shell_grammar_test.py`: **PASS, 4 suites**, including generated write pairs and real-shell differential cases.
- `one_gate_decide_contract_test.py`: **PASS, 25 tests + 31x4 shim-parity cells** with the closure overlay.
- The builder strictly reproduces all eight patch files, including the hooks-gt copy and five manifests.
  `git apply --check` passes. Ruff is unavailable (`No module named ruff`).
- No governance directory was moved, restored, or otherwise mutated; checks are classification-only.

## Apply

```
python3 held/build-661-ancestor-closure/build.py <worktree at main> <out dir>
git apply --check <out dir>/<sha>.patch && git apply <out dir>/<sha>.patch
```

Nothing here is applied to the governed source in this worktree. The patch, builder, and this note are the
reviewable deliverable.

## Accountability self-audit

```
surface: closure directory-marker matching   act: classify a relocating or overwriting act on a governance ancestor
S: high/irreversible [construct: an ancestor move can disarm every hook and the shared closure]
R: n/a [construct: no new caller authority or reachability check]
W: pass [construct: existing claim identity and escalation authority are unchanged]
O: pass [construct: ancestor and target evidence are judged before the act]
A: pass [construct: the matched ancestor reaches the same refusal and approval record]
V: present [construct: previously invisible ancestor writes enter the existing escalation route]
verdict: PASS
```
