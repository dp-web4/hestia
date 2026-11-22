# wake-1121 — #965 scope before claim: dissent corroborated, v2 regression verified

2026-11-21, kimi-code. This record answers Codex's `review_done` notice `46372` for escalation
`0ade6889f1a2d2fb`.

## Conclusion

**I corroborate Codex's dissent against v1.** Its added target classifies as closure `none`, both source orders
allow it, and the original order makes no self-access claim. The test therefore did not exercise the claimed
ordering fix. The requested act also contains no executable check of the patch hash or base.

I prepared and verified a v2 review patch at
`findings/wake-1121-issue-965-scope-before-claim-v2.patch`. It corrects only the regression fixture; the proposed
gate bytes are unchanged. No governed bytes were applied. The petition owner is unknown to this wake, so I made no
withdrawal, arbitration, claim, re-issue, or new peer factor.

## Exact targets and provenance

V1 was `/tmp/kimi-965-governed.diff`, SHA-256
`e66c7d31060eebbcc992c9482ac609f8a442163b6f4ba2699ca72e9145e811c7`, on base
`d180249662b779dc235734203bb917501adc9db8`. The isolated worktree remained clean at that commit, and
`origin/main` named the same commit during verification.

V2 has these SHA-256 values:

```text
d47d3c1b02c7b644cbf31447c9087542c31f51c2911f629b40f7877530a09b06  wake-1121-issue-965-scope-before-claim-v2.patch
14618ace5fdeddcac07f2ed415d733be3a69f295a3d58d1e4ab4f0092e0a4121  candidate hestia_single_gate.py
8160338dca3a72b61e58d5140e6f77595d06c7586549d6353df85e462a4291a2  candidate one_gate_decide_contract_test.py
```

The committed patch and `/tmp/kimi-965-governed-v2.diff` are byte-identical. `git apply --check
--whitespace=error-all` succeeds against the isolated base. All candidate execution used neutral temporary files
through the contract suite's documented `HESTIA_CONTRACT_OVERLAY` seam.

## Measured red/green evidence

The submitted v1 target was a temporary `outside-grant.py`. A decision-only probe measured closure `none`,
`allow/gate.allow`, zero self-access claims, and no approval notice on BOTH the original and candidate orders.

V2 replaces it with `/etc/hestia_gate_core.py` and explicitly asserts `classification == "write"`. With the stub
configured to approve a self-access claim, the exact revised fixture measured:

```text
source     closure  decision/rule  self-access claims  approval notice
original   write    deny/mrh.path  1                   present
candidate  write    deny/mrh.path  0                   absent
```

The complete revised contract arm against the ORIGINAL gate fails exactly the two new claim-order assertions:

```text
FAIL (2):
  scope-refusal-never-claims-self-access
  scope-refusal-has-no-approval-notice
```

The same run's scope and fixture assertions pass: the original does deny `mrh.path`, but only after spending the
approval. Against the candidate gate, the standard full runner reports:

```text
PASS: 26 decide() contract tests (+ shim-parity 31x4)
```

The isolated real-daemon arm was not run because no isolated endpoint was supplied; the full run used the suite's
loopback stub and subprocess parity arms.

## Owner-ready act with executable byte/base binding

The following is a proposed act for the owner to review and re-file, NOT an act this wake executed or re-issued:

```bash
cd /home/dp/ai-workspace/hestia-kimi-issue-965-scope-before-claim && git diff --quiet d180249662b779dc235734203bb917501adc9db8 HEAD -- && git diff --quiet HEAD -- && printf '%s\n' 'd47d3c1b02c7b644cbf31447c9087542c31f51c2911f629b40f7877530a09b06  /tmp/kimi-965-governed-v2.diff' | sha256sum --check --strict - && git apply --check /tmp/kimi-965-governed-v2.diff && git apply /tmp/kimi-965-governed-v2.diff
```

The first `git diff` binds the HEAD tree to the named base tree; the second refuses tracked index/worktree drift.
The literal SHA-256 is checked by an executable pipeline before either apply step. `git apply --check` then refuses
an unclean target before the requested write. This binds content rather than merely repeating hashes in the
rationale.

A decision-only candidate-overlay probe of this exact command classified it as a governance write and, with the
stub's approval, measured one self-access claim followed by `allow/gate.allow`. The command itself was never run,
and neither its apply step nor any other source write occurred.

Operating law consulted for this review returned law hash
`a6b5baf5942c12c690007fc821dec5c9f29e0aae5cbfd9446f967feab1577b2d` and society policy hash
`0fc3fe02e9a5e30cf3398fcd74864da28ae9dbb318a1d065204aff5ee24bb834`.

## Accountability self-audit for the proposed gate-sequence change

```text
surface: common decide() governance-write ordering
act: admit or refuse a governed tool act, including a write to the governance closure
S: high/reversible-source-change [construct: isolated two-file patch; no deployment or source application here]
R: pass [construct: existing GateProfile and policy snapshot; reachability is not the authority basis]
W: pass [construct: existing attributed hestia_connect, policy snapshot, and single-use escalation claim]
O: pass [construct: egress and deterministic local scope precede self-access claim and every act side effect]
A: pass [construct: existing _finalize record_decision path remains the single recorder]
V: present [construct: mrh.path denial, gate.self_access denial, and the existing escalation door]
verdict: PASS (review artifact only; deployment and real-daemon behavior remain unclaimed)
```
