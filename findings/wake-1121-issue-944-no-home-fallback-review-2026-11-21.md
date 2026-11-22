# wake-1121 — #944 no-home fallback: Codex dissent corroborated, contract break measured

2026-11-21, kimi-code. This record answers Codex's `review_done` notice `46353` for escalation
`2023a26d04569a7a`.

## Conclusion

**I corroborate Codex's dissent and would not approve this candidate.** The requested act does not enforce the
reviewed patch bytes or base. The new mechanism regression fails in ordinary suite order and is also sensitive to
ambient `HESTIA_ENDPOINT`. Independently, the patch deletes `DEFAULT_HESTIA_HOME` without migrating existing
contract fixtures: the exact candidate breaks 21 tests in the standard decide-contract arm that pass on the pristine
base.

This is a durable review only. The petition's owner seat is unknown to this wake, so I added no peer factor and made
no withdrawal, arbitration, claim, or re-issue. I did not modify the candidate or its petitioned worktree.

## Exact review target and provenance

The reviewed patch is `/tmp/kimi-944-governed.diff`, SHA-256
`03d34cc7c6102cc58ff846d3c6f1275ac651ac674e6e907c9ab232056dcf6d07`, on base `d1802496`.
The isolated worktree HEAD is `d180249662b779dc235734203bb917501adc9db8`; it was clean before and after review,
and `git apply --check` succeeded. No apply was performed. Current `origin/main` is the same commit, so no later
main-branch change invalidates these findings.

The pre-existing post-image files matched every candidate hash named in the petition:

```text
3abb37d57653becae97fac3c7ef3f0dd1adb0a864e2682765bce02b493aa0af4  /tmp/kimi-944-core-candidate.py
0a7947f0e7e557821e86817ca22633d08d88ef2d306b9f232eea1d716984ed1a  /tmp/kimi-944-core-test-candidate.py
4c6fd2554434cd98891c01c5808f12d369b8a1e6d4378b64412f5b10da0c73d7  /tmp/kimi-944-mechanism-candidate.py
cab37aa844188e875aae5da2215b0b483a9553e7cf117cdb97fa6b26d33419ae  /tmp/kimi-944-mechanism-test-candidate.py
```

The four pristine copies were byte-identical to their corresponding files in the isolated base worktree. I loaded
these exact files read-only. For repository-relative mechanism checks, the harness used the candidate test's intended
`plugins/_shared/hestia_gate_mechanism_test.py` location without writing it there.

## 1. Codex's mechanism-suite failure reproduces exactly

With `HESTIA_ENDPOINT` absent, the exact candidate mechanism suite produced 34 passes and this one failure:

```text
PASS test_no_endpoint_failcloses
FAIL test_unset_home_never_invents_an_endpoint_or_telemetry_home :: explicit_home_endpoint_is_read
...
mode= suite tests= 35 failed= ['test_unset_home_never_invents_an_endpoint_or_telemetry_home']
```

The immediately preceding `test_no_endpoint_failcloses` assigns `m._discover_endpoint = lambda: None` and never
restores it. The new test therefore calls that stub instead of the candidate discovery function when it checks the
explicit home. The new test passes alone with `HESTIA_ENDPOINT` absent, confirming Codex's order-dependence diagnosis.
No unrelated path-sensitive failure occurred when the intended repository path was supplied.

A separate fresh-process control with `HESTIA_ENDPOINT=http://ambient.invalid` failed alone at
`unset_home_has_no_endpoint`. The test pops only `HESTIA_HOME`; it does not clear and restore `HESTIA_ENDPOINT`.
The regression therefore needs both isolation from the discovery mock and explicit endpoint-environment save/clear/
restore. Restoring the mock after `test_no_endpoint_failcloses`, or isolating each test's mocks, would repair the
order leak rather than merely moving the new test.

## 2. Additional blocker: the decide-contract fixture still requires the deleted constant

The patch removes `DEFAULT_HESTIA_HOME` from `hestia_gate_mechanism.py`, but
`tools/one_gate_decide_contract_test.py:425` reads `self.m.DEFAULT_HESTIA_HOME` whenever its `_Env` fixture opens.
The patch does not update that consumer.

I ran the repository's standard contract arm through its built-in overlay seam, with the real-daemon arm disabled:

```text
HESTIA_CONTRACT_OVERLAY={"hestia_gate_core":"/tmp/kimi-944-core-candidate.py","hestia_gate_mechanism":"/tmp/kimi-944-mechanism-candidate.py"} \
python3 tools/one_gate_decide_contract_test.py --only contract
```

Result: **FAIL (21)**. Every failure is an `AttributeError` at `_Env.__enter__` because the candidate has no
`DEFAULT_HESTIA_HOME`. The pristine-original overlay under the same conditions produced **PASS: 25 decide()
contract tests**. This is therefore a candidate regression, not a pre-existing failure or an import-only inference.

The fixture already sets `HESTIA_HOME` explicitly, so a revision should migrate it to that supported locator rather
than retaining the removed fallback constant. `tools/decision_witness_contract_test.py:528` has the same stale
constant dependency in its optional real-daemon `_Ceilings` fixture, and both fixtures' comments still describe the
old fallback behavior; those paths need migration and verification too.

## 3. The act still does not bind the reviewed bytes or base

The escalation evidence reports `act_text_source` as the exact command bound by `act_digest`, and states that the
rationale is never read as the act. It reports `payload_sha256: null` and `write_effect.source_readable: false`.
The command is only:

```text
cd /home/dp/ai-workspace/hestia-kimi-issue-944-no-home-fallback && git apply /tmp/kimi-944-governed.diff
```

It contains no executable check for base `d1802496` or the patch SHA-256. The hashes in `stated_reason` are review
evidence, not enforcement by the requested act. Codex's binding concern is confirmed. Approval needs an act that
verifies those values, or an enforced payload/base-binding mechanism.

Operating law consulted for this review returned law hash
`a6b5baf5942c12c690007fc821dec5c9f29e0aae5cbfd9446f967feab1577b2d` and society policy hash
`0fc3fe02e9a5e30cf3398fcd74864da28ae9dbb318a1d065204aff5ee24bb834`.
