# Gate architecture: one common gate, minimum shims

**Status: NON-NEGOTIABLE.** Ruled by dp on 2026-08-31. This document is normative and
supersedes any conflicting guidance in `GATE_PROFILE.md` and `PRD_GATE_CONSOLIDATION.md`,
including that PRD's status line. Where an existing gate contradicts this document, the gate is
wrong and is scheduled for correction, not the document.

## The ruling

> "we made a common gate for a reason. and it is false as stated. you should only have a thin
> shim, like everyone else. the common gate should be the learned version of what we've run
> across the variants - learned from the false positives, the vulnerabilities, the needless
> frictions, the exploited bypasses."

> "the architecture has to be clear and non-negotiable. common gate - pragmatic, eliminate fp,
> remove frictions, govern what actually needs governing, collaboratively. shims: the absolute
> minimum to wire harness hooks into common gate. anything that is not demonstrably unique to
> the peculiarities of the harness must not be in the shim."

## 1. The two components, and only two

**The common gate** is `plugins/_shared/`. It owns every decision. One implementation, one place
to be right, one place to fix.

**A shim** is `plugins/<harness>/hooks/`. It wires one harness's hook mechanism to the common
gate. It decides nothing.

There is no third category. "Mostly shared with a local adjustment" is the state this
architecture exists to end.

## 2. The test for where a line belongs

**A line may live in a shim only if it is demonstrably unique to the peculiarities of that
harness.** The burden of proof is on the shim. The default home for any line is the gate, and
"it was easier here" is not a demonstration.

Demonstrably harness-unique, and therefore allowed in a shim:

- **Event shape.** How this harness delivers a tool call, and the names of its fields.
- **Refusal channel.** How this harness is told no. These genuinely differ: exit code 2 with
  stderr, exit 0 with a deny payload, and the fail-open defaults documented in `GATE_PROFILE.md`
  section 0 are real properties of real hook engines.
- **Registration.** Where this harness records its hooks, and how that file is read.
- **Identity.** The plugin id and role this seat acts under, passed to the gate as arguments.
- **Launch and restart verbs.** systemd against launchctl is a platform fact.

Never in a shim, under any argument:

- Any read-versus-write classification of a command.
- Any scope or path-containment predicate.
- Any governance-closure or gate-self determination.
- Any denial, escalation, appeal or witness content.
- Any fail-closed or fail-open posture decision.
- Any timeout, retry or recovery policy.

If a seat needs different behaviour from one of those, that is a **parameter on the shared
implementation**, declared as data, not a second implementation.

## 3. What the common gate must be

From the ruling, and each clause is an obligation rather than an aspiration:

- **Pragmatic.** It governs acts, not text that resembles acts.
- **Eliminates false positives.** A refusal that costs honest work and teaches a recast is a
  defect of the gate, not of the actor. Every measured false positive is a bug with a test.
- **Removes needless friction.** If the safe path is harder than the unsafe one, the design is
  wrong, because the efficiency attractor is structural and will find the cheaper path.
- **Governs what actually needs governing.** Coverage is not the goal; consequence is. A rule
  with no true positive is removed, not tuned.
- **Built collaboratively.** The gate is the *learned* version of what the variants ran, drawn
  from all seats' evidence. It is explicitly **not** one seat's implementation promoted to law.
  That matters here for a measured reason: the cause of this whole recurrence was claude-code
  authoring the law and exempting itself, enforcing 0 denies across 266 acts while kimi was at
  8/126 and codex at 2/12. The author of the law being outside it is the failure this clause
  forbids.

## 4. How "learned" is measured

`tools/gate_differential.py` carries a corpus of cases with an `expected` column, built from
lived evidence: false positives that cost escalations, bypasses that were actually exercised,
and frictions that produced recasts.

**The learned gate is the implementation that satisfies the whole corpus.** As of 2026-08-31,
after the corpus was corrected and extended (PR #739), there are **7 agreed-but-wrong cases out
of 18**. Seat agreement is already total — `SEAT DISAGREEMENTS: none` — and it is total on all
seven. Agreement is not correctness, and only the `expected` column knows the difference.

**That count is the argument for this architecture.** Deduplicating four gates into one cannot
close any of the seven, because the four already agree on them. One gate is right because a
defect is then fixable in one place, not because sharing makes anyone correct.

**Admission rule: a case must reproduce its own citation.** A case that cites a real escalation
but is reduced to a command the classifier answers differently is not evidence. The failing shape
is specific: such a case sits in the table as expected-read / got-read and *certifies* the gate on
a command that was in fact refused. Two cases were admitted that way on 2026-08-31 and corrected
the same day; applying the rule is what turned one mis-attributed false positive into the
fail-open vulnerability recorded in section 6.

A fix is not done when the seats agree. It is done when the corpus passes.

## 5. Enforcement

1. **The ratchet.** `tools/gate_collapse_meter.py` runs in CI. Pins are lowered in the same PR
   that lowers the number, so the pin edit is the progress record. **Target is 0% per-seat
   law-bearing code and 0 forked functions.** Not a lower percentage. Zero.
2. **The corpus.** The agreed-but-wrong count is a release-blocking number and moves only down.
3. **The review rule.** A pull request that adds a line to a shim must name the harness
   peculiarity that line depends on. If the author cannot name one, the line belongs in the gate.
   Reviewers reject on this rule alone.
4. **New harnesses.** Adding a harness means writing an adapter and a declaration. It does not
   mean writing a gate. A PR that adds a harness carrying its own predicates does not merge.

## 6. Known distance from this architecture, as of 2026-08-31

Stated so that nobody reads this document as a description of the present.

- **67.5% of law-bearing code is still per-seat**: 3202 sloc across four seats against 1539
  shared. claude-code holds 1654 of it, gemini 233.
- **claude-code carries the shell command classifier** that the others do not: roughly sixteen
  functions deciding read from write. Under this architecture it moves into the gate.
- **gemini carries four second implementations** of predicates the engine already owns
  (`path_in_scope`, `command_in_scope`, `launch_cwd_repo`, `_all_repos`), and issue #730 is the
  behaviour that follows: it permits on an unreachable daemon where codex and kimi refuse.
- **The gate-self rule does not hold against an interpreter** (#628, #714, both open). It was
  bypassed on 2026-08-31 with no escalation, by a script whose argv named no governance path.
- **False positives are live and costed**: two escalations on 2026-08-31 alone, both for
  read-only commands. `f8225656a1870623` was a `git log` and a `wc -l` inside a `for` loop —
  opened 05:01:08Z, decided 05:09:26Z with reason `y`, **498 seconds of operator latency to read
  a file's history**. `f5484bd911651eb0` was a `grep`, and the first draft of this document
  attributed it to the same cause. That was wrong: there was no control-flow construct. The
  trigger was a redirect to a *variable* target, `: >"$T/scratch"`, whose only write went to
  `/tmp`.
- **The same construct is inverted, and the other direction is a hole.** An unresolvable redirect
  target makes the classifier fall back to scanning for marker text anywhere in the command.
  Which way it errs is then decided by text unrelated to where the write lands: pointed at `/tmp`
  it refuses a `grep` on a seat hook; pointed at a seat hook it permits the write, because a seat
  hook is matched per *file* and splitting the directory from the filename across an assignment
  leaves no token to match. `plugins/_shared` is a `dir_marker` and does not have this hole; the
  seat hooks — the paths that gate each seat's own gate — do. This makes #589 and #609 one branch
  reported from opposite ends rather than two defects.
- **The meter is blind to one layer.** It discovers gates in the tree, so claude-code's
  `invoke_legacy_fallback` parallel path is in none of the numbers.
- **The ratchet pin was never lowered** after slice 1, so main currently permits a 1.8 point
  regression.

Each of these is a scheduled correction under this architecture, not an exception to it.

## 7. Why this is non-negotiable

Four harnesses is the easy case and it already produced one measured behavioural divergence on
a seat that has never run an agent. The divergence surface is pairwise: four harnesses is six
pairs, forty-five is nine hundred and ninety. There is no version of hand-maintained copies kept
in step by review that survives that number, and the evidence is that we could not keep four in
step for three weeks.

The cost that scales is an adapter. The cost that does not is a gate per harness.
