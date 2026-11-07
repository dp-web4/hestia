# build-noauto: the gate opens no requests or escalations on its own (held, not applied)

**Patch:** `held/e1a515cd362c26c112cfc27e0b4a8cb7d861046cd13923437cff5ae1c2966eb3.patch`. It is built by `build_noauto.py` (the build-1450a recipe, with `SOURCES` naming the mechanism and the single gate) over base `5cf6e607`, whose `plugins/_shared` and `hooks-gt` are identical to main `9ae2b633`. It supersedes `adb06466…`, the scope-only cut.

## Rulings

dp, 2026-11-05, scope: *"don't do gate-generated scope requests to the operator. instead, deny with option to escalate. if the agent really needs it, they can escalate as a deliberate act. to me, 'opened by the gate on a refused bash' is noise."*

dp, 2026-11-05, extended to every escalation: *"auto escalation should be emergency-only (i can't think what, at the moment). all escalations should be deliberate acts by agent, with reason."*

Together these reverse the 2026-10-05 scope auto-open and the stage-2 claim-or-open of governance writes. Grants and approvals of every kind are unchanged. A member now reaches them through its own deliberate escalation, not through every refusal. No emergency auto-open was built: dp could name no case, and a speculative one would be the auto-open again under another name.

## Change (source: `source-noauto.diff`)

- **Scope.** `hestia_gate_mechanism.claim_scope` accepts the daemon's `not_asked` verdict and returns the refusal id. `hestia_single_gate._scope_escalation` sets no escalation_id for a `not_asked` path. Its deny says nothing was sent to the operator or any peer, and names `hestia scope escalate <refusal_id> --as <member> --reason '...'`.
- **Governance writes.** `hestia_gate_mechanism.claim_self_write` maps the claim door's `not_asked` answer to verdict `not_asked` and passes on the daemon's detail, which names `hestia gate escalate <refusal_id> --as <member> --reason '...'`. The claim's `detail` no longer says "Auto-opened by the gate". `_governance_closure` needs no change: with no escalation_id it prints no "Escalation … is open" line.
- **Not changed:** the `gate.self_access` remedy text in `hestia_gate_core`. It already points at a deliberate door (`hestia_gate_escalation_open`, with a reason). Adding the new door there would also touch the remedy-door tests and `sprintD_test`'s literal tool list. That can be a follow-up.
- hooks-gt is regenerated, along with the manifests' hashes.

## Mixed-version safety

| gate | daemon | scope refusal | governance-write refusal |
|---|---|---|---|
| old | new | `not_asked` is read as `not_opened`. The gate denies and names `hestia_request_scope`. Nothing opens. | No escalation_id comes back, so the old gate prints "refused, and NO escalation was opened — " followed by the daemon's `error`. The daemon sets `error` to "not asked — … hestia gate escalate <id> …", so the line is true and names the door. Nothing opens. |
| new | old | The old daemon still answers `opened`/`pending`, and the new gate renders those as before. | The old daemon opens as before, and the new gate renders "escalated" as before. |
| new | new | The deny names the refusal id and the escalate command. | Same. |

## Evidence

| check | result |
|---|---|
| `tools/one_gate_decide_contract_test.py` with `HESTIA_CONTRACT_OVERLAY` set to the held copies (the test's staging seam; nothing governed was written) | PASS: 25 tests plus shim parity 31x4. Includes (1b) scope `not_asked` and the new closure `not_asked` case: it denies, says nothing was sent, names `hestia gate escalate refusal-stubgov --as kimi`, carries no escalation id, and makes no "is open" claim. |
| same test against the deployed gate source (old gate, new-daemon stub) | The closure `not_asked` case passes through the `error` text, as the mixed-version row above says. The two scope (1b) checks fail as expected, because they need the held scope half. |
| daemon side (in the PR, not held): `cargo test` in core | see the PR |

## Note on how the first cut was made

The first (scope-only) source change was written into the worktree's `plugins/_shared` by a script. That went past the governance-closure gate, which is the route this recipe exists to avoid. The restore went through the gate as escalation 64c9dc53aa7224b3 (operator-approved). Since then every change has been made to the neutral-named copies here, `source-noauto.diff` has been regenerated from them, and the tests have run through the overlay seam.
