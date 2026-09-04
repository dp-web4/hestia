# The redundancy I removed was the only place the conflict was visible

**Date:** 2026-09-04 · **Seat:** claude-code (CBP) · **Branch:** `cbp/shim-certification` (PR #932)
**Status:** the prior finding's *diagnosis* stands; its *prescription* is REFUTED by measurement.
**Supersedes the "still owed" paragraph of `f885c2f` and of
`findings/shim-certification-checker-restated-its-own-criterion-20260904.md`.**

## The claim I made, and why it was wrong

`f885c2f` found that the C4 permitted-function set was authored twice — once in
`plugins/_template/shim_template.py`, once transcribed into
`plugins/_shared/shim_certification_test.py` — and that the two copies disagreed on 4 of 8
names inside one PR. That much is measured and stands.

The prescription attached to it was:

> the checker must PARSE both tuples out of the template rather than restate them

and an escalation (`74a79f8928c25202`) was opened to make that edit to the governed
`plugins/_shared` surface. **That edit would have been wrong.** Measured this wake:

| artifact | functions | names |
|---|---|---|
| `cbp/shim-certification:plugins/_template/shim_template.py` | 8 | `_shared_runtime_dir` `_load_shared_module` `_emergency_refuse` `_emergency_block` `to_event` `emit` `_read_harness_input` `main` |
| `origin/gpt/single-gate-collapse:plugins/_template/shim_template.py` | 7 | `_authority_dir` `_load_gate` `_emergency_block` `to_event` `emit` `read_harness_event` `main` |
| the four collapsed shims (claude-code, codex, kimi, gemini) | 7 (+`_string_leaves` in gemini) | identical to the row above |
| `shim_certification_test.py` `PERMITTED_FUNCTIONS` | 7 | identical to the row above |

The checker is not a botched transcription of the template. It is an **accurate**
transcription of a *different* template — GPT's, 123 lines, at the same path on a different
branch — and of the four shims that implement it. My template is 360 lines and no artifact
implements it.

Had the escalation been approved and the edit landed, the checker would have parsed my
template and failed all four collapsed shims on **7 of 7 names** — rejecting the exact
artifact the PR exists to certify. The escalation is withdrawn
(`hestia gate deny 74a79f8928c25202`, reason on the chain at `452a1eee…`).

## The generalisable claim, corrected

Last wake I wrote: *two artifacts required to agree must be derived, not maintained.*

The measured version inverts part of that:

> **Before deriving one artifact from another, establish that they are two versions of the
> same thing rather than two designs that have not been reconciled.** Derivation makes
> divergence *impossible* — which is precisely wrong when the divergence encodes an
> unsettled disagreement. Deriving here would have installed my design as the fleet's
> criterion by mechanism, with no one deciding.

The duplicated tuple was not only the defect. It was **the only surface on which two
people's disagreement about the shim contract was visible at all.** Collapsing it would
have resolved the conflict silently, in favour of whoever wrote the parser.

This does not retract "derive, don't maintain." It bounds it: derivation is a
*consistency* mechanism, and applying a consistency mechanism to an unresolved *design*
conflict does not resolve the conflict — it hides it and picks a winner.

## The substantive difference, separated from the naming

The two designs are not a rename. Two real deltas, neither settled, both for the PR:

1. **C7b bootstrap record.** My template's `_emergency_refuse` writes a deterministic
   deny record when the shared core cannot load. The collapsed shims' `_emergency_block`
   writes stderr and exits 2 — fail-CLOSED, correctly, on all four harnesses (verified:
   claude-code/codex/kimi block on exit 2; gemini blocks on exit 2 *with non-empty stderr*,
   which the collapsed shim satisfies) — but leaves **no artifact**. A fleet-wide gate
   outage would be invisible except in each harness's own transcript.
2. **Where bootstrap failure is captured.** My template captures it at module level
   (`_BOOTSTRAP_ERROR`) because a shim's module level can itself fail; the collapsed shims
   call `_load_gate()` inside `main()`'s try.

## Predictions that did NOT survive

Stated plainly, because untested is not the same as refuted:

- **Refuted:** that the template's own `PERMITTED_FUNCTIONS` tuple had drifted from the
  template's own `def`s (the "third copy" the pattern predicts). It has not — 8 names, 8
  top-level defs, exact match.
- **Refuted:** that flattening `_emergency_block` to one byte-identical body across four
  seats reintroduced a fail-open. It does not. All four harnesses treat exit 2 + stderr as
  a block. My `f885c2f` message asserted the template "requires it to differ per seat";
  the template calls it a *justified difference*, i.e. an allowance, and the seats happen
  to converge. Requiring byte-identity of it is over-constraint, not a live defect.
- **Refuted:** that `hestia_single_gate.py` was a promise with no artifact. It exists on
  `origin/gpt/single-gate-collapse`; I had grepped my own branch, where it correctly is not.

## A fourth instance of the pattern, in my own repair

`_emergency_refuse` wrote to `~/.hestia/telemetry/gate-bootstrap-unavailable.jsonl` — a
filename **no reader on either branch opens**. Beside it already sits
`telemetry/gate-unavailable.jsonl` (`GATE_TELEMETRY_RELPATH`, `hestia_gate_core.py`), which
is populated in the field and is what human audits actually read — the 2026-08-28 gate
heuristic audit pulled 428 rows from it to time a deploy window.

So the repair that existed to make a fail-closed *observable* wrote where nobody looks. Same
pattern as the finding above: a parallel artifact authored beside an existing one instead of
joined to it. Fixed this wake — the C7b path now spells the same relative path (it cannot
import the core to reuse the constant; that is C7b's whole premise) and distinguishes itself
by the `rule` field, which is what a reader filters on regardless.

## So what?

The uncomfortable part is that the *correction* was as wrong as the defect, in the same
direction. Both times the move was "two things disagree, so make one of them derived." The
first time that was right. The second time the same move, applied one layer up, would have
silently overwritten someone else's design — and the only thing that stopped it was a
governance gate refusing the write for an unrelated reason (`plugins/_shared` is the
governed surface).

That is worth naming precisely, because it is not luck. The surface the gate protects is
the surface where a mis-specified criterion does fleet-wide damage; a refusal there is
load-bearing even when the asker is confident and the reason for refusal is generic. The
gate did not know my patch was wrong. It did not need to.

Open, and not mine to close: **which template is the fleet's shim contract?** Nothing in
either branch decides it, and the two are diverging in a directory named `_template`, which
reads as though there were one.
