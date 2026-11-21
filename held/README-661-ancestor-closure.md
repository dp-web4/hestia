# held/: hestia#661, relocating an ancestor of the closure is a write. NOT applied

| file | sha256 |
|---|---|
| `b1b4e49c3e3d621ba5bf8fd06e1a3cd7e63695179834c573eb4e278fe7b193da.patch` | `b1b4e49c3e3d621ba5bf8fd06e1a3cd7e63695179834c573eb4e278fe7b193da` (base main `59f2478eb70314a26c1538c166d9e938738e73fc`) |

## The defect

Directory markers asked only whether a target was inside the protected directory. `mv plugins/kimi`, `mv plugins`,
and `git checkout -- .` could therefore relocate or overwrite every hook and the shared closure without a write
verdict or even a marker.

## The change

- In write position, a proper prefix of a directory marker now matches: `plugins` and `plugins/kimi` prefix
  `plugins/*/hooks`. Existing descendant matching is unchanged, and read position does not use the new arm.
- An existing absolute directory is also checked for the marker's literal leading directory. That catches a repo
  root used as a pathspec, including `git checkout -- .`, without expanding globs or inventing a root for a
  directory that does not exist.
- `cp -r` destination ancestors are covered too, so duplicating a governance tree to an unprotected name is not
  silently admitted.

## Verification

On base `59f2478e`, with the generated closure loaded from the scratch overlay:

- `hestia_governance_closure_test.py`: **PASS, 40 tests**. Ancestor moves, ancestor copies, repo-root checkout,
  unrelated-root, read-side, and ordinary `/tmp` controls all pass. The unpatched control fails on the first
  ancestor move.
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
