# held/: a declared probe opens no peer scope request (#767 follow-up), NOT applied

| file | sha256 |
|---|---|
| `61fcd3772093ec630372265e165c03734d72233a304dc6478cd88a72e7826c36.patch` | `61fcd3772093ec630372265e165c03734d72233a304dc6478cd88a72e7826c36` (base main `6e77283a`) **current** |

Files: the single gate, its hooks-gt copy and manifests (emitted by `tools/hooks_gt.emit_patch` from a scratch
copy), and the decide contract test. Nothing here is applied.

## The problem

Every deploy cycle, the preflight asks each member's gate whether it would allow
`touch $HESTIA_HOME/deploy.hold`, against the live daemon. The probe is advisory (#767), so a refusal changes
nothing about the install. But the refusal still goes through `_scope_escalation`, which opens a **real peer
scope request** for each member. Nobody re-issues the act, so every request lapses. dp sees one per harness:
"i get this from every harness on startup" (2026-10-14). dp's ruling on the fix: "needless frictions are bad".

## The change

- `hestia_single_gate.NO_ESCALATE_ENV = "HESTIA_GATE_NO_ESCALATE"`. When the invoker sets it to exactly `1`,
  `_scope_escalation` returns the refusal as the law judged it, with a sentence saying why nothing was opened, and
  the daemon is **asked nothing**. Any other value keeps today's behaviour.
- **It can only withhold a request, never lift one.** It cuts the escalation path before the peek, so it never
  reaches an approval either. The worst a member could do by setting it in its own environment is not be
  offered a request it could have had.
- In the PR, not held: `deploy/from-main/gate-preflight.py` and the claude-code probe in `hestia-deploy.sh`
  declare it next to `HESTIA_HOOK_TIMEOUT_S`, which is the existing pattern for a non-harness invoker
  declaring something about itself. Against today's gate the variable is ignored, so those halves are safe to
  land first.

## Evidence

`tools/one_gate_decide_contract_test.py` with `HESTIA_CONTRACT_OVERLAY` pointing the single gate at the patched
copy: **PASS (23 + shim-parity 29x4)**. On main's gate the new test's rows fail (4 rows), so it separates old
behaviour from new. New test `test_a_declared_probe_opens_no_scope_request`: the probe is refused under the same
rule, no `hestia_scope_claim` call, no escalation id, the reason names the declaration; with the value `0` the
act escalates as before.

Not decided here: #767's own question (should members be allowed to hold the deploy). Once that is ruled the
probe stops being advisory; this change only stops the probe from filing paperwork.

— cbp-claude
