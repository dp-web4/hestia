# #1275 completion — held, not applied

The current PR fixes identifier-shaped text in the core matcher but leaves the
Web/MCP precheck using a raw substring. Its failed plugin job reports exactly
one failed file out of 152: `tools/hooks_gt_test.py` (run 38118912132).

The branch now includes main through `d3e4a3f5`, merged without conflicts. The
original core change is preserved. The completion patch is
`3c75ec32e2e462300f1a0646f63b62230baf371de910731361793a8437b2fb7b.patch`.
It contains eight files:

- One call-site change in `hestia_single_gate._egress_precheck`, using
  `core.names_forbidden_token`.
- Both shared gate GT copies, regenerated from their proposed sources.
- All five GT manifests, including every member's shared-engine pin.

Generate the patch and reproduce the before/after checks with:

```sh
python3 docs/reviews/build-1275.py
```

The builder executes the proposed precheck in memory and projects the proposed
bytes through `hooks_gt.check`; it writes only the held patch. It does not alter
any installed gate or source module. `--full` additionally runs the existing
core tests and common-gate contract suite. The core suite's non-temporary-root
fixtures are relocated into the checkout because its default external cache
is not writable here; assertions and production code remain unchanged.

Validation of the held candidate:

- Six regression methods cover 503 Web/MCP egress assertions. Before the
  change, 100 identifier subcases fail; with it, all pass. Representative path
  spellings, mixed occurrences, separate payload leaves, non-dot tokens, and
  operator-added tokens are covered.
- The projected GT tree has zero findings from the actual checker.
- `git apply --check` accepts the patch against this branch.
- The existing core suite passes 154 assertions with checkout-local fixtures.
- The common-gate suite reports `PASS: 22 decide() contract tests`; this count
  includes its explicitly skipped real-daemon arm. The remaining contracts run
  against its isolated test daemon and the in-memory candidate.
- Staged public-boundary and executable-bit checks pass. Full plugin, release,
  upgrade, and Rust CI have not run on an applied candidate: application is denied.

These tests prove a text-classifier change, not that identifier-shaped strings
cannot be filenames or contain sensitive values. The exception is deliberately
the same as the original #1275 core change. Generic prose and escaped-pattern
false positives remain; OS read confinement is separate work under #1284.

## Governance disposition

The attempted one-line source edit was denied as `gate.self_access`, opening
escalation `e27eb6a6ee898aef`. On 2026-10-14 the operator explicitly **denied**
that escalation. The peer factor attested the worktree target only, not the
redacted diff. Neither that factor nor task ownership overrides the denial.
No source edit or GT application followed it. Applying this candidate requires
a new explicit operator decision on the reviewable patch; this document does
not request or assert approval. The draft PR remains incomplete and red until
the governed write is authorized, applied, and tested in CI.

The regression file is committed as a test of the desired behavior and remains
red against the unapplied precheck; the builder provides the paired candidate
run. This is disclosed rather than skipping the regression to make CI green.

## Accountability self-audit

surface: shared egress precheck; act: classify potential secret egress

S: high/irreversible [construct: `_egress_precheck`]

R: n/a [construct: no new reachability authority]

W: escalate [construct: `gate.self_access`, operator-denied escalation]

O: pass [construct: `_sequence` checks egress before local law and society]

A: unchanged [construct: `_finalize` records the resulting decision]

V: present [construct: innate `egress.secret` denial and governance escalation]

verdict: ESCALATE — held only; operator denial remains in force.
