# held/: hestia#660, short chmod modes keep their targets. NOT applied

| file | sha256 |
|---|---|
| `619f31fc96bf84591750343697da1cd4f040e12aa1549aa5388d622acb5cda28.patch` | `619f31fc96bf84591750343697da1cd4f040e12aa1549aa5388d622acb5cda28` (base main `59f2478eb70314a26c1538c166d9e938738e73fc`) |

## The defect

`chmod -x FILE` was classified as a read. `_positionals` discarded `-x` as an option, and the chmod branch then
discarded `FILE` as the mode. Adding an exec bit escalated; removing it was free.

## The change

- Parse chmod's mode explicitly. Symbolic forms such as `-x`, `-w`, `-r`, `-rwx`, `a-x`, `go-rwx`, `u-x,g+w`, and
  `a=r`, numeric modes, and the `--` delimiter all preserve the target.
- Consume known chmod flags by name, including recursion and common verbosity flags. Unknown options use the
  existing out-of-grammar fail-closed posture.
- Handle `--reference FILE` and `--reference=FILE` as supplying the mode, so remaining arguments are targets.
- Keep `chown`/`chgrp` on their existing implementation. `--help`/`--version` and a command with no target do not
  invent a write.

## Verification

On base `59f2478e`, with the generated closure loaded from the scratch overlay:

- `hestia_governance_closure_test.py`: **PASS, 40 tests**. The unpatched control fails on the first `chmod -x`
  case. Long-standing write controls, `chown`, references, and unknown-option behavior are included.
- `closure_output_writes_test.py`: **PASS, 4 tests / 103 write-read pairs**.
- `shell_grammar_test.py`: **PASS, 4 suites**, including generated write pairs and real-shell differential cases.
- `one_gate_decide_contract_test.py`: **PASS, 25 tests + 31x4 shim-parity cells** with the closure overlay.
- The builder strictly reproduces all eight patch files, including the hooks-gt copy and five manifests.
  `git apply --check` passes. Ruff is unavailable (`No module named ruff`).
- No governance file was chmod'd or otherwise mutated; all checks are classification-only.

## Apply

```
python3 held/build-660-chmod-modes/build.py <worktree at main> <out dir>
git apply --check <out dir>/<sha>.patch && git apply <out dir>/<sha>.patch
```

Nothing here is applied to the governed source in this worktree. The patch, builder, and this note are the
reviewable deliverable.

## Accountability self-audit

```
surface: chmod target extraction in the governance closure   act: classify a mode change on a governed file
S: high/irreversible [construct: removing exec/read permission can disarm enforcement]
R: n/a [construct: no new caller authority or reachability check]
W: pass [construct: existing claim identity and escalation authority are unchanged]
O: pass [construct: the complete target set is judged before any mode change]
A: pass [construct: the same resolved targets reach the refusal and approval record]
V: present [construct: previously missed disarms now enter the existing escalation route]
verdict: PASS
```
