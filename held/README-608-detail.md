# held/: hestia#608 + #1497 deliberate-escalation detail. NOT applied

| file | sha256 |
|---|---|
| `4eda8ccbba6a190f9af27bc3b3be6180e77fb26d51e14dd13efdf3f22750b37b.patch` | `4eda8ccbba6a190f9af27bc3b3be6180e77fb26d51e14dd13efdf3f22750b37b` |

Builder base: merged worktree `8f6dd4412d7f2d0e7f8949f6f95f485d95635247`, containing current main
`faffd549c964d72eb09c3656dc6dff6da34bc1b1`. `git apply --check` also passes directly on that main.

This one patch supersedes `e1a515cd…`, `dae63377…`, and `611bdc93…`; those candidates must not be
applied. The older files remain only as history.

## The change

The builder applies `held/build-noauto/source-noauto.diff` first, then adds #608's rule-aware detail.
The no-auto half handles the daemon's `not_asked` answer for both scope and governance-write refusals:
nothing opens, and the member is offered the deliberate-escalation door with the refusal id.

`claim_self_write` also accepts an optional `refusal_rule`, supplied by the common gate from `cv.rule`.
Its `detail` now reads:

> The gate's record of a refused act (&lt;actual-rule&gt;). Nothing is asked unless the member escalates it as a deliberate act.

It no longer says the gate auto-opened anything, and a read-only out-of-grammar refusal no longer
asserts a write. Claim identity and approval scope are unchanged; older callers that omit the optional
rule retain a rule-free version of the same accurate detail.

The patch updates the mechanism, common gate, both hooks-gt copies, five manifests, and the four-seat
boundary test: ten files total.

## Validation

- Unmodified sources: the new acceptance test fails on the old auto-open/write detail; the other 17
  boundary tests pass.
- Revised sources through the overlay seam: **18 tests × 4 seats pass**, including:
  - a real write carries `governance-closure-write` and the deliberate-escalation wording;
  - a read-only `bash -c 'cat …'` refusal carries `governance-closure-out-of-grammar` and no `write`
    claim or auto-open wording.
- Overlaid `tools/one_gate_decide_contract_test.py`: **26 decide() contract tests plus 31×4 shim
  parity pass**, including the `not_asked` scope and governance paths. The optional real-daemon arm
  was skipped because `HESTIA_DECIDE_CONTRACT_ENDPOINT` was unset.
- Builder strictly reproduces all ten files. `git apply --check` passes on the builder base and
  directly on main `faffd549`.
- No governed source was edited during validation; overlays and temporary roots stayed inside the
  worktree.

## Apply

```sh
python3 held/build-608-detail/build.py <worktree at main> <EMPTY out dir>  # re-cut if main moved
git apply --check <out dir>/<sha>.patch
git apply <out dir>/<sha>.patch
python3 plugins/_shared/seat_gate_boundary_test.py
```
