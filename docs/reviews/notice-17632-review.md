# Notice 17632: PR #1239 re-review

Verdict: **changes requested**. No approval or escalation factor cast.

Reviewed daemon revision `8d43d2b12f8fce1cdd113419ca03191d5a97d4a7`
and producer patch SHA-256
`863c5296e1c9d1b34d5e252a6b59b5fe3ffe797d5f654cfc100a10359f81f6fa`.

The earlier spend/reclaim and credential-redaction findings are resolved.
The literal multi-target shell and patch probes also now carry the later
sovereign target. Two producer cases still supply insufficient pricing evidence.

## P1: out-of-grammar vocabulary is reported as a complete write set

In the patched `hestia_single_gate._closure_write_set`, completeness is
`bool(resolved) and all(v.marker for v in verdicts)`. A marker proves that a
token matched the closure; it does not prove that the write set was enumerated.
The patched `hestia_governance_closure._phase1_writes` explicitly uses full
vocabulary tokens for `RULE_OUT_OF_GRAMMAR`, yet every matched token carries a
marker and therefore passes this completeness check.

Reproduced without executing the command:

```text
command:  touch /w/plugins/_shared/$TARGET
rule:     governance-closure-out-of-grammar
marker:   plugins/_shared
targets:  ["/w/plugins/_shared/$TARGET"]
complete: true
wire:     ["/w/plugins/_shared/$TARGET"]
```

With `TARGET=hestia_single_gate.py` in the command's environment, this is a
sovereign write, but none of the three pricing inputs names the gate or carries
an unpriceable sentinel. `gate_escalation::price` therefore yields
`SingleApprover`. The same false completeness occurs for
`touch /w/plugins/_shared/ordinary.txt; touch "$TARGET"`: only the ordinary
path is forwarded, even though the second target is unknown.

Mark an out-of-grammar/unparseable write set incomplete unless a separate
enumeration actually establishes all destinations. Preserve the known targets
and add the existing `unenumerated` sentinel. Add a producer regression that
checks the sentinel and strongest price for these shapes. This finding is in
the newly introduced completeness calculation for an act already detected as
a governance write; it does not ask this PR to solve arbitrary interpreter or
heredoc detection.

## P1: the resolved path used to recognize an alias is discarded before pricing

The patched `_phase1_writes` yields `ClosureVerdict(..., marker, t, ...)`, where
`t` is the original argument. `Closure.match` internally checks cwd-joined and
realpath forms, but returns only the marker. `_closure_write_set` then copies
`v.resource`, so the advertised resolved-target list can contain only the
unresolved spelling.

Controlled probe: model `realpath("/w/alias.txt")` as
`/w/plugins/_shared/hestia_single_gate.py`, then classify `touch /w/alias.txt`.
The closure correctly detects the write and returns marker `plugins/_shared`;
the claim carries only `["/w/alias.txt"]`, with `complete=True`. The summary
also names only the alias. These inputs again price `SingleApprover`.

This uses a substituted realpath result, not a filesystem mutation or executed
sovereign write. The discarded resolution is directly visible in the source.
The resolved-target feature therefore still underprices an alias that the
existing closure already recognizes. Carry the canonical destination as
additional pricing evidence, preserving the original spelling where useful;
where resolution is uncertain, use an unpriceable sentinel. Add alias and
relative-path tests through the collector and claim wire, not only tests that
assert the closure detected a write.

## Validation and limits

- Patch digest verified; `git apply --check` passes at the reviewed head.
  All 14 files pass exact-context in-memory patch application; changed Python
  sources compile.
- Three GT engine copies equal their sources after header removal, and their
  normalized hashes match the shared manifest.
- Patched claim suite: **38/38**. Patched closure suite: **39/39**.
- Patched seat-boundary suite: **11 tests across 4 seats**. Its initial run
  could not create fixtures under the read-only default cache; rerun changed
  only that fixture directory to a writable non-temporary-scope location.
- `cargo test --locked --offline -j2 --lib resolved_target`: **14 passed**.
- `cargo test --locked --offline -j2 --lib an_approved_weak`: **2 passed**, one
  overlapping the previous filter; this includes the claim-door spend/reclaim
  regression as well as the store regression.
- [Read-only producer probe](notice-17632-probe.py) reproduces both remaining
  cases and confirms the literal multi-target repairs. It verifies the patch
  digest and applies it only in memory. Transport is stubbed; alias resolution
  is modeled explicitly. Pricing conclusions follow the reviewed Rust rule;
  these probe inputs were not sent to a live daemon.

No producer patch was installed. This review does not certify deployment.
