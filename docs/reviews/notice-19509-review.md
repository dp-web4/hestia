# PR #1239 re-review — notice 19509

Verdict: **the two P1 findings and the P2 finding in review 18784 are resolved**.
No remaining blocking finding in this repair delta. This supersedes those three
changes-requested findings for head `177f2913d927ba5cd1c2d10e384022ad2d4c720b`
plus held producer patch SHA-256
`ca833c340ab5fc61a14d9bade234869ec68c848ef46b081a05a1bf7905402b09`.

## Findings resolved

- **P1, incomplete write sets:** the restored `_closure_write_set` requires
  `RULE_WRITE` and an absolute or resolved destination before declaring a set
  complete. Both original variable-destination cases, and the relative target
  without a cwd, now send `hestia:unpriceable:unenumerated`. Known targets survive.
- **P1, canonical destinations:** `Closure.forms()` and
  `ClosureVerdict.resolved` carry the canonical destination through the collector
  to the claim. The independent modeled alias carries both spellings. The boundary
  suite also checks a real fixture symlink on every seat.
- **P2, bracket globs in act text:** `markers_of` unions the old tokenization with
  one preserving brackets. The original `[pq]re_tool_use.py` reproduction now
  prices `SovereignPlusPeer` from either act text or resolved targets. Bracketed
  literal paths still price strong; `[xy]re_tool_use.py` stays `SingleApprover`.

## Independently repeated validation

- All three stored patch hashes match their filenames. The recovered `2e0547b5`
  reference has the exact hash recorded in review 17641. Comparing diff blocks,
  **12 of 14 are byte-identical** between that reference and `ca833c34`; only
  `claim_self_write_test.py` and `seat_gate_boundary_test.py` differ. Those two
  differences add the glob and producer regressions described in the request.
- Exact-context in-memory reconstruction succeeds for all 14 files;
  `git apply --check` passes at the reviewed head. Changed Python sources compile.
  All three changed published engine copies equal their sources after header
  removal and match their normalized manifest hashes.
- Independent producer probe: **8/8**, including both multi-target controls,
  unknown destinations, alias destination, glob transport, missing cwd, and an
  ordinary absolute target.
- Patched claim suite: **45/45**. Patched closure suite: **39/39**.
- Patched boundary suite: **11 tests × 4 seats**, including actual fixture
  symlink, unknown-destination sentinel, later target, and glob assertions.
- Isolated Rust pricing harness: **9/9 assertions**. It compiles the current
  pricing functions verbatim, omitting only serde derives from the copied `Bar`
  enum. Two negative controls intentionally send the old incomplete producer
  evidence and remain weak; the repaired sentinel/canonical-destination evidence
  prices strong. The bracket-glob, bracketed-literal, and nonmatching controls pass.
- The daemon delta since `d6f23be2` consists of the bracket-preserving
  tokenization and its assertions. The underlying producer sources and GT files
  did not change between those heads; the producer repair remains in the held patch.
- PR head rechecked as `177f2913` before publication.

## Reproduction

Run from this review branch, which adds these artifacts to the reviewed head:

```sh
patch=held/ca833c340ab5fc61a14d9bade234869ec68c848ef46b081a05a1bf7905402b09.patch
git apply --check "$patch"
python3 docs/reviews/notice-19509-probe.py "$patch"
python3 docs/reviews/notice-19509-price-probe.py
python3 docs/reviews/notice-19509-suites.py "$patch" claim_self_write_test
python3 docs/reviews/notice-19509-suites.py "$patch" hestia_governance_closure_test
python3 docs/reviews/notice-19509-suites.py "$patch" seat_gate_boundary_test /absolute/writable/non-tmp/fixture-base
```

The probe/suite runners are the prior review's artifacts updated to the new
digest, with explicit lineage checks added. The pricing harness now asserts its
expected outcomes and includes the bracketed-literal/nonmatching controls. The
suite runner uses temporary module overlays; it relocates only the boundary
fixture base, without altering test assertions. Transport is stubbed.

## Limits and integration note

This is a review of the requested repair, not a fresh audit of the entire stack.
The author's full Cargo run and 14-suite Python run were **not independently
repeated**. Rust evidence here is an isolated pricing harness, not daemon
integration or live authorization. Prior spend/reclaim and replay review evidence
remains in the PR history. No producer installation or approval factor was cast.

The stated directory-target and interpreter limitations remain outside this
repair. The reported #1247 tuple-versus-string integration conflict needs its own
restack and review; this verdict does not clear that branch.

— Codex
