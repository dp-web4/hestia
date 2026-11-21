# held/: hestia#608 refusal detail records the actual rule. NOT applied

| file | sha256 |
|---|---|
| `611bdc930a802bf45a36ce71bc35fd66bdf079ec288937b9b0244d4b0b424617.patch` | `611bdc930a802bf45a36ce71bc35fd66bdf079ec288937b9b0244d4b0b424617` |

Base: main `59f2478eb70314a26c1538c166d9e938738e73fc`.

## The change

`claim_self_write` accepts an optional `refusal_rule`; the common gate supplies the closure's actual
rule. `stated_detail` now reads as an auto-opened **act**, not an auto-opened **write**, and includes
that rule. It no longer asserts a verb class the marker layer did not establish.

This lets a reviewer distinguish a real write (`governance-closure-write`) from a read-only
out-of-grammar refusal (`governance-closure-out-of-grammar`) on the chain. It does not change claim
identity, approval scope, or the old constant's behavior for callers that omit the optional rule.

The patch updates the mechanism, common gate, both hooks-gt copies, five manifests, and the four-seat
boundary test.

## Validation

- Unmodified sources: the new acceptance test fails on the constant `refused write` literal; the
  other 17 boundary tests pass.
- Revised sources: **18 tests × 4 seats pass**, including:
  - a real write carries `governance-closure-write`, not `refused write`;
  - a read-only `bash -c 'cat …'` refusal carries `governance-closure-out-of-grammar`, not
    `refused write`.
- Builder strictly reproduces all nine files and `git apply --check` passes on the base.

## Apply

```sh
python3 held/build-608-detail/build.py <worktree at main> <EMPTY out dir>  # re-cut if main moved
git apply --check <out dir>/<sha>.patch
git apply <out dir>/<sha>.patch
python3 plugins/_shared/seat_gate_boundary_test.py
```
