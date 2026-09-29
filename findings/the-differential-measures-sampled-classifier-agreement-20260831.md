# The differential is a classifier corpus, not a four-harness proof

Review of #739 exposed a useful boundary: the corpus is valuable, but the first version described more than it measured.

## What survived review

The evidence cases are still the right learned-classifier corpus. They capture observed false positives, interpreter-mediated writes, the variable-target inversion, positive controls, and a negative control. Seven of eighteen settled cases currently miss the expected answer in the shared predicate. Those misses are defects to fix, not a reason to weaken the expectations.

## What changed

Three acceptance bugs were sustained and corrected:

1. **Uniformly wrong is not green.** If every measured seat returns the same wrong verdict, expectation misses now make the run fail with exit 1.
2. **Partial measurement is not a measured seat.** If a seat fails at any tested CWD, or any seat/case result is missing or errors, the run is INDETERMINATE with exit 2. Success at one CWD cannot hide failure at another.
3. **Sampled equality is not byte identity.** The tool compares classifier outputs. It does not hash the resolved module bytes, so equal outputs establish sampled behavioral agreement only.

The executable contract test in `tools/gate_differential_contract_test.py` pins all three states.

## Exact scope

`tools/gate_differential.py` imports each discovered seat and reaches the closure classifier that import resolves. It then feeds identical classifier inputs over the corpus and tested CWDs.

It therefore measures:

- whether every discovered seat/case/CWD can be measured,
- sampled behavioral agreement of the closure classifiers reached,
- CWD-dependent verdict changes,
- conformance to the corpus expectations.

It does **not** establish:

- resident module byte identity,
- installed-release identity,
- native harness argument extraction,
- full hook/daemon behavior,
- full four-adapter conformance.

Those are separate surfaces. #743 now ratchets extraction-domain agreement. The one-executed-authority sprint handles installed loader truth. The harness-agnostic adapter PRD defines resident-hook hash verification and the full adapter acceptance contract.

## Gemini is informative, not ignorable

Gemini currently delegates consequential acts into the Claude gate instead of exposing the same closure-classifier surface directly. The differential must therefore report that seat as unmeasured at this layer rather than silently shrinking the denominator. A future adapter-level differential should drive Gemini through its own native normalization and delegation path.

## Structural lesson

A measurement should fail in three different ways for three different reasons:

- **0:** complete and correct,
- **1:** complete enough to judge, but wrong,
- **2:** insufficient evidence to judge.

Collapsing any two of those states creates a path for missing evidence or uniform error to masquerade as agreement.

surface: measurement tool + findings   act: none consequential
S: low/reversible   R: n/a   W: n/a   O: n/a   A: n/a   V: n/a
verdict: PASS
