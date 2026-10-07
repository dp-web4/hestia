# PR #1239 rebuild review — notice 18784

Verdict: **changes requested** on head `d6f23be2cea23e3162e14dbd4ba698c851856bb1`
and held patch SHA-256 `574426d6772d36bf2630cb94bf4b82d1b1d2b07a0db18651d9808158ca2d825b`.

The rebuild restores two P1 defects already fixed in producer patch `2e0547b5…`
and cleared in [review 17641](https://github.com/dp-web4/hestia/pull/1239#issuecomment-6012272986).
The lineage in held/README.md stops at the earlier `863c5296…` patch; this is a
functional regression, not just a comment/docstring difference.

## Findings

1. **P1 — Restore conservative completeness for unknown destinations.**
   `held/574426d6….patch:145`, `_closure_write_set`: completeness requires only
   nonempty resources and markers, ignoring the verdict rule and path resolution.
   Both an out-of-grammar variable destination and a compound command with a
   known ordinary target plus an unknown destination produce `complete=True` and
   omit `hestia:unpriceable:unenumerated`. The reviewed Rust pricing functions
   price the variable case `SingleApprover`. A variable can designate a sovereign
   file, so this drops the second authorization factor. The relative-without-cwd
   regression also returns complete. Restore the previously reviewed RULE_WRITE
   and absolute/resolved-path checks and their claim-wire regressions.

2. **P1 — Carry canonical destinations through the collector again.**
   `held/574426d6….patch:144`, `_closure_write_set`, and `_phase1_writes`:
   `Closure.match` can recognize an alias's canonical destination, but the
   collector sends only `v.resource`, the original spelling. With realpath
   modeled to resolve an ordinary alias to the common gate, the claim contains
   only the alias and the directory marker; the reviewed pricing code returns
   `SingleApprover`. Restore `Closure.forms`, `ClosureVerdict.resolved`, and the
   collector's forwarding of canonical forms from the cleared patch, including
   its real-symlink boundary tests. Canonical destination as a control prices
   `SovereignPlusPeer`.

3. **P2 — Preserve bracket classes before pricing act-text globs.**
   `core/src/server/gate_escalation.rs:447`, `markers_of`:
   the act-text splitter includes `[` and `]`. Consequently a path basename
   `[pq]re_tool_use.py` is split before `sovereign_expansions` can inspect it.
   With no resolved targets it prices `SingleApprover`, whereas the identical
   pattern supplied as a resolved target prices `SovereignPlusPeer`. The new
   rule explicitly promises both representations and still supports old callers
   without targets. Add act-text bracket-class coverage and preserve the pattern
   through tokenization. The existing `*.py` act-text control passes.

## Independent validation

- Patch digest and exact source context verified across all 14 files;
  `git apply --check` passes without applying the patch.
- Changed Python sources compile; three published engine copies equal source
  after header removal and satisfy normalized manifest hashes.
- `notice-18784-probe.py`: **4/8 checks pass**. Unknown destination (two shapes),
  canonical alias and relative-without-cwd fail; literal multi-target shell,
  multi-target patch, glob forwarding and ordinary absolute controls pass.
- `notice-18784-suites.py`: claim **39/39**, closure **39/39**, seat boundary
  **11 tests × 4 seats** pass. These included suites omit the restored P1 cases.
- `notice-18784-price-probe.py` compiles the reviewed pricing functions verbatim
  in a temporary Rust harness (only serde derives on Bar omitted), reproducing
  both underpriced producer inputs and the act-text bracket-class discrepancy.
  This is a focused function probe, not a full cargo test run.

Reproduce from this review branch:

```sh
python3 docs/reviews/notice-18784-probe.py held/574426d6772d36bf2630cb94bf4b82d1b1d2b07a0db18651d9808158ca2d825b.patch
python3 docs/reviews/notice-18784-price-probe.py
```

The producer probe intentionally exits nonzero on the reviewed defects. Suite
runner usage is in its docstring; the seat fixture directory must be writable
and outside temporary-scope classification. The alias probe models realpath;
no real sovereign write or live escalation claim was performed. The held patch
remains uninstalled; this review casts no authorization factor.
