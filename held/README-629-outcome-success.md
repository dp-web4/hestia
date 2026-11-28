# held/: hestia#629, explicit process failures reach outcome.success. NOT applied

| file | sha256 |
|---|---|
| `74898a722e7fc32e25adbf7c8c18c2898ad19456a23fc22769514cbacf7a9955.patch` | `74898a722e7fc32e25adbf7c8c18c2898ad19456a23fc22769514cbacf7a9955` (base main `59f2478eb70314a26c1538c166d9e938738e73fc`) |

## The defect

The shared outcome witness returned `success=True` whenever the tool envelope lacked an error flag. A command
that ran and exited nonzero is a well-formed tool call, so its process failure never reached the outcome record.

## The change

- `derive_success` recognizes numeric `exit_code`, `exitCode`, `returncode`, and `return_code` fields, including
  numeric strings and JSON-encoded response objects. Booleans are not process statuses.
- Shell results with a documented `Exit Code: N` footer are recognized for native shell tools. The last label wins,
  because the tool's own footer follows anything the command printed. Arbitrary output text is never searched for
  a status.
- Nonzero status records `success=False` with `exit status N` and bounded stderr detail when available. Explicit
  interruption also records failure. Zero, stderr-only warnings, and missing status evidence keep their existing
  behavior; no status is inferred from an ordinary error message.
- The existing `PostToolUseFailure` and envelope-error paths are unchanged.

This is deliberately narrower than a claim that every outcome is now known: a harness that omits act-level status
still gets the legacy best-effort answer. Denied-act decision records and live historical census work are separate
from this patch.

## Verification

On base `59f2478e`, with the generated core loaded from the scratch overlay:

- `hestia_witness_core_test.py`: **ALL CHECKS PASSED**. Structured field spellings, Gemini `llmContent` and
  `returnDisplay`, Codex string responses, final-footer precedence, zero/interrupted/legacy controls, and four
  end-to-end `hestia_record_outcome` calls all pass. The four outcome records carry `success=False` and join the
  gate's original action.
- The same revised suite against the unpatched core fails **exactly the 12 new failure-evidence checks**.
- `hestia_witness_receipt_test.py`: **ALL CHECKS PASSED**.
- `decision_witness_contract_test.py`: **PASS, 20 tests**.
- `closure_read_tool_names_test.py`: **PASS, 8 tests**.
- `one_gate_decide_contract_test.py`: **PASS, 25 tests + 31x4 shim-parity cells** with the core overlay.
- `tools/hooks_gt.py check`: clean on the base. The builder strictly reproduces all eight patch files, including
  the hooks-gt copy and five manifests. `git apply --check` passes.
- Real daemon arms were not run; all daemon traffic in these suites is loopback stub traffic.
- Ruff is unavailable in this environment (`No module named ruff`).

## Apply

```
python3 held/build-629-outcome-success/build.py <worktree at main> <out dir>
PYTHONPATH=plugins/_shared python3 <out dir>/hestia_witness_core_test.py
git apply --check <out dir>/<sha>.patch && git apply <out dir>/<sha>.patch
```

Nothing here is applied to the governed source in this worktree. The patch, builder, and this note are the
reviewable deliverable.

## Accountability self-audit

```
surface: outcome success derivation   act: record an already-completed act's process outcome
S: med/reversible [construct: post-hoc evidence only; no new protected act or permit]
R: n/a [construct: no new caller authority or reachability check]
W: pass [construct: existing witness identity and action-id joins are unchanged]
O: n/a [construct: outcome recording remains after the act; preflight order is unchanged]
A: pass [construct: explicit status and bounded error ride the same outcome record]
V: n/a [construct: no new permit path; existing gate escalation is unchanged]
verdict: PASS
```
