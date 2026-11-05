# build-noauto: the gate stops opening scope requests (held, not applied)

**Patch:** `held/adb0646649d3b4d6d81d069fe20b9bbc092ac1d64ce15753dde66560534cf651.patch`, built by `build_noauto.py` (the recipe of build-1450a, with `SOURCES` naming the mechanism and the single gate) over main `9ae2b633`.

## Ruling

dp, 2026-11-05: *"don't do gate-generated scope requests to the operator. instead, deny with option to escalate. if the agent really needs it, they can escalate as a deliberate act. to me, 'opened by the gate on a refused bash' is noise."*

This reverses the 2026-10-05 auto-open ("yes on gate gap, let's fix it"). Standing, session and one-time grants are unchanged. They are now reached through the member's deliberate escalation instead of through every refusal.

## Change (source: `source-noauto.diff`)

- `hestia_gate_mechanism.claim_scope` accepts the daemon's new `not_asked` verdict. It returns the refusal id in the third slot.
- `hestia_single_gate._scope_escalation` sets no escalation_id for a `not_asked` path, because nothing is pending. Instead the deny says nothing was sent to the operator or any peer, and names the deliberate door: `hestia scope escalate <refusal_id> --as <member> --reason '...'`.
- hooks-gt is regenerated, along with the manifests' hashes.

## Mixed-version safety

| gate | daemon | result |
|---|---|---|
| old | new | The old gate receives `not_asked` and maps it to `not_opened`. It denies and names `hestia_request_scope`. Nothing opens. |
| new | old | The old daemon still answers `opened`/`pending`. The new gate renders those as before. |
| new | new | The deny names the refusal id and the escalate command. Nothing opens until the member escalates. |

## Evidence

| check | result |
|---|---|
| `tools/one_gate_decide_contract_test.py`, run with the source change in place in the worktree before it was held | PASS (25 + shim parity 31x4), including new case (1b): not_asked denies, says nothing was sent, names `hestia scope escalate refusal-…`, carries no escalation_id |
| daemon side (in the PR, not held): `cargo test` in core | 1402 lib + all integration tests pass |

## Note on how this was cut

The source change was first written into the worktree's `plugins/_shared` by a script. That went past the governance-closure gate, which is the route this recipe exists to avoid. The restore went through the gate as escalation 64c9dc53aa7224b3 (operator-approved). The held patch was then cut from the saved diff over a clean tree.
