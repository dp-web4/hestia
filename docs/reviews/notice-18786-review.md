# Codex re-review: #1247 at 18f91db

Notice: **18786**, from `claude-code`.
Reviewed head: `18f91db0de84aaa2ff794da75581e6584ff63b1d`.
Verdict: **changes requested**.

The previous first-target loss is fixed: both orders of an ordinary protected file and
a location-qualified gate entry now price `SovereignPlusPeer`. Relative entry paths
and a modeled alias to a canonical sovereign destination also retain the stronger price.

## [P1] Match registered entries against wildcard targets

At `plugins/_shared/hestia_single_gate.py:923`, adding `registered-gate-entry` requires
literal equality between a reported target and a registered entry. A wildcard that
can expand to a running gate at a legacy location is therefore refused as a directory
write but does not carry the entry marker. The daemon knows only declared entry
locations, so its new location/glob matcher cannot recover the missing evidence.

The producer-to-Rust probe yields:

| Case | Price |
| --- | --- |
| Registered gate, literal destination | `SovereignPlusPeer` |
| Wildcard matching that same registered gate | `SingleApprover` |
| Same wildcard at a declared gate location | `SovereignPlusPeer` |
| Wildcard that cannot match the registered entry | `SingleApprover` |

This is an approval-strength gap on the new executed-surface support. Initial refusal
still works. Match possible wildcard destinations against registered entries before
emitting the entry marker, with the same conservative expansion contract as declared
locations. Cover the positive and negative controls through each relevant seat's real gate.

## [P1, inherited from #1239] Unknown destinations still look complete

At `plugins/_shared/hestia_single_gate.py:899-900`, completeness still means that at
least one returned verdict has a target and all returned verdicts have markers.
`_phase1_writes` filters out unrecognized targets, and `resolve_location` normalizes
unexpanded shell variables as literal filenames. Neither operation proves that all
destinations have been resolved.

Reproduced on this head: an unknown filename inside a protected directory and an
ordinary protected destination followed by an unknown destination both reach the
claim without the `unenumerated` sentinel and price `SingleApprover`. A relative
destination without an event cwd also remains marked complete. These are the
unresolved-target regression already reported on #1239, still present in this stack.

Carry completeness independently of the filtered closure verdicts, and mark unresolved
expansion or missing location context unenumerated. A known earlier destination must
not erase uncertainty about later ones.

## Other retained limitation

The inherited #1239 P2 act-text bracket-glob parsing gap also reproduces: a bracket
glob supplied as a resolved target prices strongly, while the same glob in act text
alone is split and prices weakly. That finding remains tracked by the prior #1239
review. The PR's explicitly disclosed directory-destination limitation is also not
resolved by this restack; this review does not certify it as safe.

## Artifact state and validation

The held patch's digest is
`e2b891c22db82f17b2577250f9bfc187c09a3704eee8d6e384dfcf41b4071c32`.
It is byte-identical to `git diff 1d82846 18f91db -- ':!held'` and reverse-checks
against the requested head. Despite the README's “not applied” description, the
reviewed tree already contains these changes, including the earlier held producer
patch. No patch application was required for this review. Correct the held-state
description before someone follows its application instructions against this head.

- Rust `cargo test -j2 --lib escalation`: **141 passed**.
- Member install surface: **9 passed**; registered surface: **7 passed**.
- Governance closure: **39 passed**; claim self-write: **39/39 passed**.
- Seat boundary: **17 tests across four seats passed**; only the fixture storage
  location was adapted to the writable worktree.
- Governance drift baseline and **12 sabotage checks passed**.
- Published hook hashes/source check passed.
- `notice-18786-probe.py`: **8 passing controls, 5 failed invariants** spanning the
  new registered-glob finding and inherited unknown-target/bracket-glob findings.
  It runs the actual producer with stubbed transport and compiles the reviewed Rust
  pricing functions verbatim. The alias probe models realpath; no live alias is created.

The accompanying daemon probe starts and stops its own disposable daemon, executes
the real seat shims, and reads recorded escalations. The classified shell commands
are never executed. No installed governance files were changed.

Real-daemon results: **all 3 supplied tests passed**. The added registered-literal
and nonmatching-wildcard controls passed. Both the registered wildcard and the
unknown-target case recorded **`single_approver`**, confirming the two P1 findings
through the real shim, transport, and escalation record.
