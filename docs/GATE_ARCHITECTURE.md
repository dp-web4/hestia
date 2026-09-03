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

- **Event shape.** How this harness delivers a tool call, and the names of its fields. This
  licenses *translation* only. The mapping from `(tool, key)` to a declared value kind is the
  gate's data, not the shim's code: a shim may say "this harness spells it `absolute_path`", and
  may not say "this key is a path" or "this key is not worth extracting". Deciding what is in the
  reach domain is a scope predicate, and scope predicates are forbidden below.
- **Refusal channel.** How this harness is told no. These genuinely differ: exit code 2 with
  stderr, exit 0 with a deny payload, and the fail-open defaults documented in `GATE_PROFILE.md`
  section 0 are real properties of real hook engines.
- **Registration.** Where this harness records its hooks, and how that file is read.
- **Identity.** The plugin id and role this seat acts under, passed to the gate as arguments.
- **Launch and restart verbs.** systemd against launchctl is a platform fact.
- **Reachability timing.** How long this harness can wait for the gate before the harness
  itself times the hook out, and how many retries fit inside that budget. Codex clamps a hook
  at 3s; claude-code allows far longer. These are harness clocks, so the timeout and retry
  numbers are harness data. What the shim may calibrate is the TIMING of reaching the authority,
  never the OUTCOME of failing to reach it: an unreachable authority is fail-closed on every
  harness, and no timing choice may turn that into an allow. The adapter sees reachability
  only. Whether a resident hook is miswired is the daemon's view of the adapter, not the
  adapter's view of itself (PRD_HARNESS_AGNOSTIC_ADAPTERS section 8).

Never in a shim, under any argument:

- Any read-versus-write classification of a command.
- Any scope or path-containment predicate.
- Any governance-closure or gate-self determination.
- Any denial, escalation, appeal or witness content.
- Any fail-closed or fail-open posture decision, including what happens when a timeout expires.
- Any recovery policy: what to do INSTEAD when the authority does not answer. There is no
  instead.

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

## 4. What the corpus measures, and the two layers it does not

A gate decision is three layers deep, and only the third is shared today.

1. **Loader resolution.** Which bytes answer for this seat: the installed copy, and the
   `sys.path` the seat builds at import time. A seat can import a `_shared` of a different
   vintage than the one in the tree, or fail to import one at all.
2. **Extraction.** Which argument values become the event's paths and command, before any
   predicate runs. This layer is per-seat and unshared: the four seats enumerate a union of ten
   argument keys and agree on three (#734).
3. **The predicate.** The scope, closure and gate-self decision. This is the layer that
   `plugins/_shared` already owns.

`tools/gate_differential.py` grades layer 3 and only layer 3. It loads each seat's module the way
the seat does and calls the closure classifier that resolution exposes, so **for claude-code,
codex and kimi it is the same shared bytes answering three times.** The tool prints this itself:

    MEASURES: byte-identity of the shared closure engine as each seat's import
              resolves it. NOT per-seat extraction (#734) and NOT loader drift.

**The 7 agreed-but-wrong cases out of 18 are therefore one shared predicate wrong seven times,
not four gates independently agreeing.** An earlier draft of this document made the second claim.
The correction cuts both ways:

- It is a **stronger** argument for one gate than agreement would have been. Deduplicating the
  seats cannot close any of the seven, because on this layer there is already only one
  implementation to deduplicate. The defects are in the law itself. One gate is right because a
  defect is then fixable in one place, not because sharing makes anyone correct.
- It is a **weaker** claim about the fleet. `SEAT DISAGREEMENTS: none` is not evidence that the
  seats behave alike. It is evidence that the same file answers when called four ways.

**gemini could not be driven at all.** It exposes no closure classifier, and nothing on the
`sys.path` it builds answers to `hestia_governance_closure`, so the run reports `SEATS NOT
MEASURED: 1 of 4` and marks the fleet verdict INDETERMINATE rather than clean. The seat carrying
four forked predicates is precisely the seat the instrument cannot reach. That is a fact about
layer 1, and it is why layer 1 needs a bar of its own rather than a footnote in this one.

**Admission rule: a case must reproduce its own citation.** A case that cites a real escalation
but is reduced to a command the classifier answers differently is not evidence. The failing shape
is specific: such a case sits in the table as expected-read / got-read and *certifies* the gate on
a command that was in fact refused. Two cases were admitted that way on 2026-08-31 and corrected
the same day; applying the rule is what turned one mis-attributed false positive into the
fail-open vulnerability recorded in section 6.

A fix is not done when the seats agree, because on the predicate layer they cannot do otherwise.
It is done when the corpus passes.

## 5. Enforcement: one bar per layer

The corpus gates the shared predicate. It cannot gate what it does not drive. Each layer
therefore carries its own release bar, and no bar may be reported as covering another.

1. **The predicate bar.** `tools/gate_differential.py`. The agreed-but-wrong count is
   release-blocking and moves only down: **7 of 18 as of 2026-08-31**. Every case must reproduce
   the escalation it cites. A run that could not drive every seat reports INDETERMINATE and does
   not satisfy this bar.
2. **The extraction bar.** Each harness adapter is driven on its own tool vocabulary, per seat.
   Key-vocabulary agreement is printed beside the collapse percentage: **3 of 10 as of
   2026-08-31**. The domain table is keyed on **`(tool, key) -> value kind`**, never on argument
   name alone: `pattern` is a glob under `Glob` and a regex under `Grep`, so a name-keyed list is
   unsound rather than merely incomplete, and a rule derived from one reading re-imported the
   other seat's live incident (#734). A path-shaped value arriving under an unenumerated key is
   witnessed, so the gap is loud rather than discovered by someone going looking.
3. **The loader bar.** Each **installed** loader is driven where it is installed, not in the
   tree, because installed `_shared` vintage can lag the hook that imports it. A seat that cannot
   be driven fails this bar rather than being omitted from a table. gemini fails it today.
4. **The ratchet.** `tools/gate_collapse_meter.py` runs in CI. Pins are lowered in the same PR
   that lowers the number, so the pin edit is the progress record. **Target is 0% per-seat
   law-bearing code and 0 forked functions.** Not a lower percentage. Zero.
5. **The review rule.** A pull request that adds a line to a shim must name the harness
   peculiarity that line depends on. If the author cannot name one, the line belongs in the gate.
   Reviewers reject on this rule alone.
6. **New harnesses.** Adding a harness means writing an adapter and a declaration. It does not
   mean writing a gate. A PR that adds a harness carrying its own predicates does not merge.

## 6. Known distance from this architecture, as of 2026-08-31

Stated so that nobody reads this document as a description of the present.

- **67.3% of law-bearing code is still per-seat**: 3166 sloc across four seats against 1539
  shared. claude-code holds 1618 of it, gemini 233. This is the post-#745 measurement; removing
  the legacy fallback improved the number without changing the 0% target.
- **claude-code carries the shell command classifier** that the others do not: roughly sixteen
  functions deciding read from write. Under this architecture it moves into the gate.
- **gemini carries four second implementations** of predicates the engine already owns
  (`path_in_scope`, `command_in_scope`, `launch_cwd_repo`, `_all_repos`), and issue #730 is the
  behaviour that follows: it permits on an unreachable daemon where codex and kimi refuse.
- **gemini cannot be driven by the corpus at all.** It exposes no closure classifier and resolves
  no shared engine on the `sys.path` it builds, so every predicate verdict we hold is over three
  seats and is INDETERMINATE for the fleet. The least-measured seat is the most-forked one.
- **The gate-self rule does not hold against an interpreter** (#628, #714, both open). It was
  bypassed on 2026-08-31 with no escalation, by a script whose argv named no governance path.
- **False positives are live and costed**: two escalations on 2026-08-31 alone, both for
  read-only commands. `f8225656a1870623` was a `git log` and a `wc -l` inside a `for` loop -
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
  seat hooks - the paths that gate each seat's own gate - do. This makes #589 and #609 one branch
  reported from opposite ends rather than two defects.
- **The extraction domain is unshared and, until #734, unmeasured.** Every seat builds the
  event's paths itself from a hard-coded list of argument key names: union of ten, agreed by all
  four, three. Holding tool and destination fixed and varying only whether the value was
  extracted flips the verdict on three of four probed tools, and 19 gated calls in one seat's
  local transcripts carried a path under an unenumerated key. The predicate is on a ratchet; the
  domain it is applied to was not on any instrument.
- **The meter is blind to two layers.** It discovers gates in the tree, so claude-code's
  `invoke_legacy_fallback` parallel path is in none of the numbers, and installed vintage is in
  none of them either.
- **The ratchet pin was never lowered** after slice 1, so main currently permits a 1.8 point
  regression.

Each of these is a scheduled correction under this architecture, not an exception to it.

## 7. Why this is non-negotiable

The case does not rest on the seats disagreeing about the predicate. On that layer they cannot
disagree: they import the same bytes, which is why the corpus finds one implementation wrong
seven times and no seat disagreements at all. The case rests on the layers that are still spelled
once per seat, where divergence is measured and is already live.

- **Extraction agrees 3 ways out of 10.** Two seats exclude `pattern` because including it
  false-denied every Glob on a live seat; one seat includes it because excluding it allowed an
  out-of-scope `include: ["../restricted-project/**"]`. Both fixes are correct against their own
  incident and neither reached the other. Union re-imports the false deny; pick-a-winner re-opens
  the hole. Only a typed rule satisfies both records, and no seat has one.
- **The refusal path and the reach domain are spelled four ways.** Normalised-AST comparison puts
  7 duplicated bodies in DIVERGENT, of which roughly 345 sloc is law rather than wiring, and
  `deny` and `path_targets` are both in it.
- **One behavioural divergence is already measured** on a seat that has never run an agent
  (#730), and the seat it was measured on is the one no instrument can currently drive.

The divergence surface is pairwise: four harnesses is six pairs, forty-five is nine hundred and
ninety. There is no version of hand-maintained copies kept in step by review that survives that
number, and the evidence is that we could not keep four in step for three weeks, on the layers
where keeping them in step was left to review.

The cost that scales is an adapter. The cost that does not is a gate per harness.
