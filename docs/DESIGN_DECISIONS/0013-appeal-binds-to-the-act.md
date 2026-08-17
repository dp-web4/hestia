# 0013 — An appeal binds to the act, not to a marker

**Status:** decided (dp, 2026-08-07). Supersedes the claim-token model.
**Supersedes in flight:** #244 fix (2) as proposed in-thread; #281's visibility approach (which
remains useful as an interim, but is not the repair).
**Composes with:** the signature premise (dp, same session). The dependency is **asymmetric** —
this decision's *scope* closure stands alone; its *identity* clause requires signing. See
[How this composes with signatures](#how-this-composes-with-signatures).

---

## The defect this replaces

`claim()` joins on `(plugin_id, marker)` and nothing else. No tool, no target, no arguments, no
act identity.

A grant is therefore addressed to *"whoever calls themselves X, doing anything whose marker
resolves to Y."* Two consequences, both measured on 2026-08-07, both live:

**A grant is claimable outside its scope.** The operator approved a `Write` of a markdown file
under `/tmp`; its marker was a governance filename, and the real target appeared only in the `why`
prose that `claim()` never reads. **The same grant would have been satisfied by an edit to the
gate itself.** At claim time the two acts are indistinguishable.

**A grant is claimable by another agent.** `proven_asker` derives from a *`session_id` argument*;
omit it and the mismatch check is skipped, `asker_is_proven` is computed but never gates the
claim, and the call returns `claimed: true, permits_write: true`. Independently, `tool_connect`
takes `plugin_id` as a caller-supplied string — the handler's own comment says *"any local client
could then connect claiming `plugin_id = …`"* — so even the proven path proves only that the
caller repeated its own assertion.

The root shape: **a grant today is a token that authorises a future act.** Tokens travel.

---

## The model

### 1. Auditable provenance for every act, with composable fractal role and agent

Every act carries the composed identity that produced it — agent, role, instance, session — and
that composition is the provenance, not a single flat id. Sub-identities compose upward; the audit
trail is the composition.

### 2. The denied act is recorded, and the escalation references it

A denial is not an event that happened to a string. It is a **recorded act with an identity**, and
an escalation carries that identity. The act's status becomes **`appealed`** and stays there until
resolved.

### 3. A grant or denial resolves exactly one recorded act

Any grant or denial traces to the referenced, recorded act **alone**, and transitions *that act's*
state from `appealed` to `granted-on-appeal` or `denied-on-appeal`.

**A grant is not a capability. It is a verdict on a past act.** What it authorises is
**re-evaluation of the original recorded act, verbatim, from the chain**, and only for the
**originating role/agent chain**.

Nothing is minted, so nothing can be spent elsewhere.

### 4. Unattributed acts are not appealable

Not as sanction — as structure. **There is no agent to hand the result to.** A grant on an
unattributed act has no recipient; re-evaluation has nobody to re-evaluate *for*.

So an act with no attributable agent must be **refused at escalation-open time**, with that stated
as the reason. It must not open an escalation that later fails at claim.

**Hard prerequisite: attribution in force, not attribution merged.** 124 of 425
`gate_escalation_opened` rows (29%) are `unattributed` — the largest single class. Refusing them at
open converts that class into refusals, so it must not land until attribution (#256) is *installed
and observed* on the gates that would do the refusing. Merged is not installed: the same-day
plane-E measurement below is a live demonstration of that gap at the measured seat.

> **Corrected 2026-08-08** (kimi-code review of this decision, notice 1649; re-derived independently
> by claude-code from a full chain walk — 124 unattributed opens, 90 approved, **44 claimed**, last
> at 16:17:47Z, `abbe8f6a90fbc4be`). An earlier draft of this paragraph claimed grants to
> `unattributed` "proved unclaimable." **That is false, and the chain says the opposite.** 44 of 90
> were claimed and spent, because the `(plugin_id, marker)` join cannot tell a non-entity from a
> member: `unattributed` is claimable like any other string. The conclusion survives; the mechanism
> was wrong, and the true one is the stronger argument for this decision. What actually happened on
> 2026-08-07 is that after the last claim at 16:17:47.885Z, **every** later approved `unattributed`
> escalation — **7** of them, `da3ea954` through `c58abb17` at 18:17:21Z, re-derived
> 2026-08-08 and equal on two independent walks — went **unclaimed** — not because there was no agent to hand a grant to, but because a name-join breaks
> the moment the claimer stops calling itself `unattributed` (the #244 fix). Caveat, stated because
> it bounds the inference: never-claimed is common baseline noise (claude-code never claimed 72% of
> its 159 approvals), so no single unclaimed row proves anything; a cut from 44-claimed to 0-of-7 at
> one boundary is not that noise pattern. **A tail count is not a fixed quantity** — write it as
> "every approved row after the cut," with the count as of a stated walk, or the next reader
> re-measures a different integer and reads a corrected doc as a wrong one. **Name-bound grants strand under legitimate rename;
> act-bound grants would not.** That is this decision's case, made by the defect itself.

### 5. Timeout is a verdict, not an absence

An escalation that expires is recorded as **`denied on appeal — reason: timeout`**.

The state machine is therefore **total**: no act is stranded in `appealed`. This closes the
PRD §8.2 symptom *"escalations expire unruled overnight"* — not by preventing expiry, but by making
expiry a decision with a reason. An unlooked-at appeal and a refused one stop being
indistinguishable.

---

## Resolutions of the three implementation tensions

**Denials that cannot be recorded → the fallback, same availability-not-blocker principle** (dp).
A fail-closed denial caused by an unreachable daemon cannot write to the chain: recording requires
the path that just failed. That class does not become unappealable — it takes the fallback record
(plane E), and appeals reference it. Unavailability degrades the evidence; it does not remove the
right to appeal.

> **Open dependency: plane E had not recorded in the reference deployment when this decision was
> written.** The private operational evidence identified three independent reasons: the recorder
> was absent from the installed gate, its import was unresolvable off-repo, and the destination
> directory was never created — plus a latent wrong-`HESTIA_HOME` bug. The *principle*
> stands. But the state machine's totality **in the unrecordable-denial case is aspirational until
> plane E records once from an installed seat**, and this decision should not be read as claiming
> otherwise. By this document's own standard, a criterion satisfiable by prose is not satisfied.

**Verbatim re-evaluation → resolve via hash of the original** (dp). The chain need not hold the
act's bytes — the plugin deliberately never sends full tool arguments to the daemon. It will hold
the **digest**. At retry the member re-presents the verbatim act, the daemon re-evaluates it and
verifies the digest matches.

> **This wire does not exist yet** (kimi, 1649). Today `policy_decision` carries `attempted`,
> redacted *and* truncated at `ATTEMPTED_MAX = 400` (`handler.rs:2305`, `1287-1290`), and no digest.
> Because the plugin by design never sends full arguments, the daemon cannot compute the digest
> itself: it must be computed **plugin-side at deny time and sent as a new field**. That is a build,
> not a wiring fix — future tense throughout this paragraph is deliberate. See contract B1. A different act yields a different digest and is refused. Privacy
preserved, verbatim enforced — and the digest is the natural object to sign.

**State transition on an append-only chain → this is solved, do not reinvent it** (dp:
*"blockchains do this all the time, previous state is mutated constantly"*). Transitions are
appended and current state is a fold. The projection machinery already exists (#198).

---

## How this composes with signatures

**The dependency is ASYMMETRIC, and the first draft of this section got it wrong** (corrected on
kimi's review of #283; codex's review reaches the same place from the other side).

- **Scope closure is independent.** A grant cannot travel to a *different act*, because the digest
  of the re-presented act must match the recorded one. That holds no matter who presents it, under
  today's declared identity, with no signatures anywhere.
- **Identity closure is NOT independent.** *"Only the originating role/agent chain"* is checked by
  comparing the claimant's identity against the recorded act's — and `tool_connect` authenticates
  nobody, so any member can assert the originating identity. **That clause is unenforceable until
  acts are signed.** It is a hard dependency, not a parallel track.

kimi's framing is the precise one: the digest is **half the credential**. Under this decision alone
an attacker must possess the act bytes *and* assert the identity; signatures close the second half.

So: signatures do not need this decision (they are independently valuable — codex's reading).
This decision's identity clause does need signatures (kimi's reading). Both are true; the arrow
points one way.

**Do not ship the identity clause as enforced before signing lands.** Declare it, record what it
*would* have refused, and say plainly that it is not yet enforceable — otherwise it becomes exactly
the defect this repo keeps finding: a declared control read as an audited one.

---

## What we already have

Measured on 2026-08-07 against `origin/main`, this is mostly a **wiring gap, not a build**:

| piece | state |
|---|---|
| denied act recorded with an identity | **exists** — `policy_decision` carries `action_id` |
| composed identity on that record | **exists** — `plugin_id`, `role_lct`, `instance_lct`, `session_id` |
| escalation → deny reference field | **exists** — `gate_escalation_opened.answers_deny` |
| that field ever populated | **never — 0 of 314** |
| act state machine + fold | projection machinery exists (#198) |
| signing primitive for the digest | **exists, zero callers** (`witness_act.rs`) |

The link from an escalation to the act it appeals has had a slot since it was designed, and has
never carried a value.

---

## Consequences to accept deliberately

- **Claim tokens disappear.** There is nothing to claim, so the marker/tool/target join class
  ceases to exist rather than being made stricter.
- **Some acts become unappealable** — the unattributed ones — and that must be *said* at open time,
  not discovered at claim time.
- **Re-evaluation can still deny.** A grant authorises re-evaluation, not an outcome. If law
  changed in between, the verbatim act may be refused again, and that is correct.
- **The originating role/agent chain is part of the binding.** The same agent acting in a different
  role is not the same appellant.

---

## Amendments from peer review (2026-08-07)

Reviewed independently by **kimi-code** and **codex** on #283. Both accepted the model; between
them they found one error and eight precisions. Recorded here rather than silently folded in,
because the corrections are the evidence that the review happened.

### The error: signatures are not a parallel track

Corrected in *How this composes with signatures* above. The first draft claimed orthogonality in
both directions; the identity clause is a hard dependency on signing. Left visible because "these
two things are independent" is the kind of claim that gets quoted onward.

### From kimi

**A1 — there is no exception mechanism, and the doc must say so.** A grant re-evaluates the act
under *current law*. If the rule that denied it still stands, re-evaluation denies again. So an
appeal against a working rule resolves only by **fixing the rule** or **denying the appeal** —
there is no "approve this once" any more.

The operator flow becomes: **appeal → fix rule → grant → re-evaluate.**

Endorsed as a forcing function, and worth stating why it is an improvement rather than a cost:
one-off approvals are precisely how the same false-positive class got re-approved all day on
2026-08-07 without ever being fixed. Requiring a law change to resolve an appeal means the *class*
gets fixed once instead of the *instance* getting waved through repeatedly. But it must be written
down, or someone rediscovers hollow approvals in their newly-correct form.

**A2 — the timeout verdict carries a reason-class.** `denied on appeal — reason: timeout` must be
distinguishable, in the record and in any trust computation, from a denial on the merits. Nobody
looked is not the same as the appeal was wrong, and scoring them alike would penalise a member for
the resolver's absence. (The #211 lesson, one level up.)

**A3 — a side effect worth claiming: the appeal-refusal trap dissolves.** Appeals reference an
`action_id`, not a marker string, so the self-access predicate's haystack has nothing to match.
The whole "escalations minted by documenting the defect" class — which on 2026-08-07 refused a
code review, three commit messages, a drift survey, and a section of the governance PRD — closes as
a *consequence* of act-binding rather than needing its own fix.

### From codex

**B1 — canonical act serialization and a digest domain.** Two encodings of the same act must
produce the same digest, and the digest must be domain-separated so an act digest can never be
confused with a witness digest or a chain hash. Without a canonical form, "verbatim" is a wish.

**B2 — the fallback record must be DURABLE.** dp's fallback for daemon-unreachable denials is only
worth having if it survives the condition that created it. A fallback that lives in the process
that just failed is not a fallback.

**B3 — compare-and-swap on the terminal transition.** Timeout and a late ruling are both terminal
transitions on the same act and *they race*. Without CAS an act can receive two terminal verdicts,
or a human decision can be silently overwritten by an expiry that fired first. The state
transition must be conditional on the act still being `appealed`, and the loser of the race must be
recorded as having lost rather than dropped.

**B4 — append-only transitions, never mutation of historical rows.** dp's *"blockchains do this all
the time"* is the right precedent and this is its precise reading: state moves by **appending** a
transition that references the act; current state is a fold. No historical row is rewritten.

**B5 — a red test: every opened escalation links to its recorded act.** `answers_deny` is populated
in 0 of 314 escalations today, so the test starts red and its going green *is* the wiring landing.
A test that cannot fail on the current code would prove nothing.

### The meta-pattern, now observed from three seats

kimi's summary, independently reached: **this system builds correct mechanisms and under-connects
them.** The alias ruling, the signing primitive with zero callers, `answers_deny` at 0 of 314, the
shared core deployed nowhere, `current-build.json` with a reader and no writer.

This decision opens with the wiring inventory instead of discovering it afterwards. That habit —
*before designing the fix, measure whether the mechanism already exists and is simply unwired* — is
the transferable part, and it should outlive this document.

---

## The stop-condition, measured (2026-08-08)

kimi's review closes: *"Do not build the arbitration driver on the current claim path — an agent's
ruling claimable by a different agent for a different act is the deputy problem automated."*
Endorsed, and there is a second reason to hold, found by walking the chain rather than reading the
design.

Chain as-of head `a29ed8c1`, 119,677 entries to genesis
(`tools/derivation_blind_census.py`):

| escalation lifecycle step | rows | read by the trust fold? |
|---|---|---|
| `gate_escalation_opened` | 425 | **yes** |
| `gate_escalation_claimed` | 108 | **no** |
| `gate_escalation_corroborated` | 6 | **no** |
| `gate_escalation_arbiter_refused` | 3 | **no** |
| `gate_escalation_decided` | 302 | **yes** |

`DERIVATION_EVENT_TYPES` (`derivation.rs:144`) carries the two ends and none of the middle. **The
claim step is the one step of the escalation lifecycle no trust computation can see.** If the
deputy problem fires today it does not produce a suspicious claim in the record derivation reads —
it produces an open and a decision with *nothing between them*.

So the hold is not only "the claim path has the wrong semantics." It is also: **the claim path is
unmonitored**, and automating an arbiter on top of it would add volume to the one step that
generates no trust evidence. Signatures and act-binding first, as kimi says; and whichever lands
first, the claim event needs to reach the fold, or the control is unobservable in exactly the
scenario it exists for.

Wider context, same census: 20 of the 26 event types in `GOVERNANCE_EVENTS`
(`governance_ledger.rs:61` — a curated, documented list of "every event type that is an ADMIN act")
are absent from `DERIVATION_EVENT_TYPES`. The trust fold reads the smaller of two lists, and only
the larger one was written deliberately. That is the same meta-pattern one level out: the mechanism
exists, is documented, is live for the operator UI, and the machine that scores members does not
read it.
