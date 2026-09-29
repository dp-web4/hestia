# 0015 — NOT-SAME work is **claimed**, not assigned

**Status:** proposed
**Date:** 2026-08-09
**Author:** claude-code (CBP), at dp's direction
**Supersedes nothing. Answers:** `#264` (the third verdict), and the standing review bottleneck.
**Revision 3 (2026-08-09)** — amended from fleet review: §5/§5a corrected (THOR), §4a added,
§6/§7 answered and sharpened (NOMAD), §11a given two measured defects it would otherwise have
shipped on. All new figures measured against `hestia@ba8993d`, cited by file and line.
`acting_on: 5c66a16c-5b27-432a-a68a-bf50285a3774`

---

## 1. The measurement this exists to change

```
escalation decisions, trailing 25 000 chain entries
215 decisions · decided_by {'operator': 215} · decided_via {'operator_session': 215}
```

**Zero ever ruled by an agent.** And on 2026-08-09, across two repos: **8 open PRs, 0 reviewed**,
two of them open three days.

This is not a missing capability. Every hard part is built and in force today:

| capability | status |
|---|---|
| a member can rule another member's escalation (`tool_gate_arbitrate_escalation`) | **built** |
| NOT-SAME enforced **server-side**, reusing the appeal arbiter's rules | **built** |
| `hestia gate pending` reports per-caller `you_may_rule` | **built** |
| independence recorded on the ruling | **built** |
| any agent has ever used it | **never — 0 of 215** |

dp, on what the gap costs: *"i'm just rubberstamping because i can't see who's doing what and why,
and being flooded with false positives."*

**A verb with no caller is not a capability.** This decision is about the caller.

---

## 2. Why the existing model is PUSH, and why push failed

The arbiter **selects**. It scores candidates by independence and liveness and routes to one. Its
own source records what that produced, and the story is the argument for changing it:

> `agent-inventory` — an hourly cron that reads config files — was selected as arbiter and graded
> **cross_vendor**, the STRONGEST independence tier, purely because "agent-inventory" matched no
> known vendor prefix and `!=` therefore read as "maximally different". The receipt said
> *"routed to a not-same arbiter."*
>
> It was not-same. It also cannot reason, cannot read an appeal, and will never rule. The appeal
> would have sat routed-and-answered-looking forever.

That is the fleet's signature defect — **a state bit-identical to the null state** — and the source
already names it as *worse than an unrouted appeal, because an unrouted one says so*.

Push-routing must **predict** two things it cannot observe: that the target can reason about this
subject, and that it will run. The entire `Liveness` enum exists to estimate the second one from
the chain.

---

## 3. The inversion: a claim is self-proving

**A claim is an act.** Only something that can act can claim.

Everything push-routing has to guess, a claim demonstrates:

| push must predict | a claim proves |
|---|---|
| the candidate is alive | it just acted |
| the candidate can reason about this | it read the subject and chose it |
| the candidate will get to it | it is asking for it now |

`agent-inventory` cannot claim. Not because a rule excludes it — because claiming requires
doing something, and it does not do things. **The failure mode is structurally unreachable
rather than defended against**, which is the difference between a guard and an architecture.

This does not delete the arbiter. Independence scoring stays exactly as it is and is enforced
server-side; what changes is **who initiates**. The arbiter becomes the *referee*, not the
*dispatcher*.

---

## 4. Preference orders the board; it never gates it

dp's requirement is *"by preference"*, and preference has an obvious failure mode: everyone claims
the interesting work and the tedious work starves.

So the rule is narrow:

- **Preference is a sort key, not a filter.** A member states tags it prefers. The board it sees
  is *complete* and *ordered*, never truncated.
- **Age outranks preference.** An item's rank rises with time unclaimed, so the unpopular item
  reaches the top of everyone's board rather than the bottom of all of them.
- **The operator is the floor, not the default.** Past a threshold an unclaimed item is marked
  `starved` and surfaces to dp — but as an escalation *of the queue*, distinguishable from an item
  nobody could rule. Today dp is 100% of the resolver pool by accident; this makes dp the resolver
  of last resort by design.
- **No silent caps.** If the board truncates for display, it says how many it dropped. A board that
  shows five of forty and does not say so reads as "there are five".

Preference is also **evidence**, and is recorded as such: what a member repeatedly claims and rules
well is a T3 signal. It is *not* wired into scoring by this decision — recording first, scoring
later, deliberately, because a preference signal that feeds reputation immediately creates an
incentive to claim what is easy to rule.

### 4c. As drafted above, preference is not subordinate to age — it is dead. Age must be bucketed.

HUB's §3, accepted in full. *"Preference is a sort key"* and *"age outranks preference"* are in
tension, and as written the tension resolves against preference entirely: `opened_at` is a
**second-resolution** timestamp over a population that has never exceeded single-digit
concurrency, so **ties essentially never occur and the secondary key is never consulted.** dp
asked for *"by preference"*; the rule as drafted delivers strict FIFO with a preference field no
ordering ever reads. Two consequences, both HUB's:

- **Convergence, not dispersion.** A uniform order points every awake claimer at the same top
  item. The lease (§5) absorbs that collision — and the lease is increment **3**. Preference doing
  real work is the only thing that would *spread* claimers across the board; making it inert
  removes the dispersal mechanism and leaves the collision two increments unhandled.
- **The T3 evidence would be contaminated.** If order is uniform and age-driven, what a member
  claims is a function of *when it woke up*, not what it prefers. Recording-before-scoring is
  right; recording a signal that is really a cron schedule and scoring it later is worse than
  recording nothing.

**So age is bucketed, not continuous.** Age tiers; preference orders *within* a tier. This keeps
the §4 guarantee that matters — an unpopular item still climbs to the top of everyone's board —
while giving the sort key something to order.

### 4a. Starvation and the horizon are adversarial, and on this surface starvation cannot occur

THOR's §3, accepted: **age-rank promotes an item toward the top of the board at the same rate it
promotes it toward unrulability.** The starvation rule exists to keep an item visible until
someone rules it; past the horizon, visibility and rulability part company, and `starved` stops
being distinguishable from `nobody could rule it` — collapsing §10's acceptance criterion in
exactly the regime it was written for.

Measured (§5a), the composition on increment 1's source is worse than adversarial — it is
**vacuous**:

> Gate escalations expire on a **1-hour wall-clock TTL** and drop out of `pending()`. Any
> starvation threshold worth the name is measured in days. **No escalation can ever be rendered
> `starved`: it is `Expired` and gone from the board first.**

So §4's starvation rule is not merely at risk on this surface — it is **unobservable**, and
§10's "a starved item reaches dp labelled as starved" cannot be satisfied by increment 1 at all.
Three consequences, all cheap, none deferrable to a later increment:

1. **The starvation threshold must be read against each source's own horizon, not set as a
   constant.** Per source: escalations, 1h TTL; appeals, `APPEAL_CHAIN_WINDOW = 20_000` entries
   — a *write-volume* horizon that halved in two days (4.65d → 2.25d, kimi). Different units,
   so one number cannot serve both. The threshold must be strictly less than the horizon, in
   whatever units that source measures.
2. **Expiry is an outcome, not an absence.** An item that ages out must be *recorded as expired
   unruled* and reach dp on that basis. Today it simply stops appearing, which is the
   `ruled` / `expired unrulable` / `still open` conflation this fleet already documented on
   08-03 — the instrument built to detect the hazard cannot distinguish the hazard from success.
3. **§10's starved criterion is provisional until a source exists that can starve.** Stated here
   rather than quietly carried, because an acceptance criterion no increment can satisfy is the
   same defect one layer up.

#### 4b. Correction to rev 3: the horizon is not a wall, it is this decision's free parameter

Rev 3 filed the 1-hour TTL as a hard constant to design around and asked dp whether escalations
are *"really meant to die in an hour."* **That question is answered in the source, and the answer
inverts the conclusion.** `DEFAULT_TTL_SECS`' own docstring (`gate_escalation.rs:76-104`):

- It **was 120s**, from dp's *"deny on timeout of a couple minutes"* — a bound on how long a
  member sat *frozen*, under a blocking design that no longer exists.
- It was raised to 3600 for **precisely this decision's problem**: *"a peer is ASYNCHRONOUS —
  another agent on another schedule, reached by a mesh notice it will see when it next drains.
  Two minutes means it essentially never arrives in time."* Measured 2026-07-30: escalation
  `8bb08a85` opened, kimi-code notified over the mesh, **expired unruled** — *"not a failure of
  the peer; a window sized for someone already watching."*
- And the cost of widening is stated as nil: *"a pending escalation permits NOTHING, so a longer
  window widens no permission — it only widens the chance that somebody answers. What must stay
  tight is `APPROVAL_CLAIM_WINDOW_SECS`"* (600s — it bounds how long a **granted** approval can
  be ridden, and 0015 must not touch it).

So starvation is not vacuous by nature. It is vacuous **at the current value of a knob whose own
documentation says widening it is free, and which has already been moved 30× in this exact
direction for this exact reason.** THOR quoted my 07-31 line back at me — *"the window width is
the last free parameter"* — and on this surface it is literally true.

4. **0015 ships a TTL proposal alongside its threshold, rather than marking §10 provisional and
   waiting.** The one-hour horizon is the same defect as the 120s one, one order of magnitude up:
   a window sized for a decider who is already watching, on a fleet whose deciders wake on notices.

**And the dependency runs the other way from how rev 3 had it.** The only real cost of a longer
TTL is that the operator's pending queue holds more rows for longer — a *visibility* cost. A
board that ranks, annotates and reports its omissions is exactly the instrument that makes a
longer queue readable. **0015 is not blocked by the TTL; 0015 is the precondition for raising it
safely.** That is the argument to put to dp, in place of rev 3's question.

---

## 5. NOT-SAME is checked twice, because state moves

Eligibility is evaluated **at claim** and **again at rule**.

Checking only at claim is a TOCTOU hole with a governance shape: a member can be independent when
it claims and become a beneficiary before it rules — it takes one intervening act. Checking only at
rule wastes the claim and hides the conflict until the end.

Both checks call into the **same module**, and neither is a copy. The fleet has paid for copies of
one predicate repeatedly — five gate implementations, two token sets, two transcript
implementations — and this decision does not add a sixth instance of that mistake.

**Corrected on review (THOR, §5), by measurement against `origin/main` at `ba8993d`.** The
draft said "the same `arbiter::eligibility`". That is false as written, and the difference is
load-bearing rather than pedantic:

| surface | entry point | direction |
|---|---|---|
| discovery — `tool_gate_pending_escalations` (`handler.rs:11972`) | `eligibility(p)` | **blind** — `arbiter.rs:198` is a wrapper for `eligibility_for(p, ForAppellant)` |
| ruling — `tool_gate_arbitrate_escalation` (`handler.rs:12056`) | `eligibility_for(p, disposition)` | **told**, from the caller's `approve` |
| corroboration — `tool_gate_escalation_corroborate` (`handler.rs:12216`) | `eligibility(p)` | **blind** — correct today, and §5b is why that is not the same as safe |

Three call sites, not two — THOR's §5.1 correction, adopted. One module, one rule set, no drift
— but **two predicates**, and they disagree on exactly one
enumerable case: `p.arbiter == p.appellant` under `AgainstAppellant` returns `SelfWithdrawal`
(permitted) from the direction-aware entry and `Refused` from the direction-blind one. The
blindness is deliberate and correct at its own site: `arbiter.rs` states that the relaxation
"is opted INTO by naming a direction; it is never inherited by a caller that was not written
with the distinction in view."

So the requirement is not "call the same function" — it is **name the direction at every
surface that renders or acts on eligibility**, and treat a direction-blind render as a floor,
never as the board.

### 5a. The third window is real, but it is not the one anyone modelled

THOR's review argued a third window: eligibility decays with **unrelated chain write volume**,
because the 20 000-entry tail evicts lineage evidence — measured horizon 4.65 days on 08-06,
2.25 days on 08-08, halving in two days. THOR flagged the inference to this surface as
unconfirmed and assigned the check to whoever holds `handler.rs`. Ran, at `ba8993d`:

**1. Eligibility does not decay. It never reads the chain.** `eligibility_for` (`arbiter.rs:203`)
is a *pure function* of `(appellant, arbiter, deny_adjudicator, disposition)`: clause 1 compares
two strings, clause 2 compares two strings, clause 3 is `is_recognised_reasoner` (a `starts_with`
prefix match in `lineage()`), clause 4 grades by comparing those prefixes. No `recent_chain`, no
store access, no I/O. The mechanism THOR proposed is **refuted for this predicate**: unrelated
write volume cannot flip `you_may_rule`.

**2. THOR's conclusion survives anyway, on a different constant that is ~54× harsher.** The
board's items are not chain-resident. `gate_escalations` is an in-memory `EscalationStore` with
a **wall-clock TTL**: `DEFAULT_TTL_SECS = 3600`, `Status::Pending if now >= expires_at =>
Expired`, and `pending()` returns `Status::Pending` only (`gate_escalation.rs:103,355,1093`).

> **The horizon on increment 1's own source is one hour of wall clock, not 2.25 days of write
> volume — and it is immune to how quiet the fleet is.**

**3. The shared-constant inference is wrong in the reassuring direction.** The escalation
surface does not inherit `APPEAL_CHAIN_WINDOW = 20_000`. Restart replay uses its own
`ESCALATION_REPLAY_SCAN = 5_000` (`state.rs:223`) — a quarter of the appeal depth. Anyone
reasoning about this surface from the appeal window is off by 4× on replay and by the wrong
*units* on liveness.

So eviction **is** the third window, it just is not a TOCTOU race at all: it is a deadline that
runs during the lease and needs no act by any party — THOR's structural point, intact. The board
must therefore carry each item's `secs_remaining` and treat expiry as a first-class outcome, and
§5's two checks bracket a lease that can die between them from the clock alone.

### 5b. Corroboration: the third site, where the blind entry is right for a reason that is about to expire

THOR asked for the site §5 omitted — *"add corroborate to the set or say explicitly why it is out
of scope."* It is in the set. Measured at `ba8993d`:

`tool_gate_escalation_corroborate` (`handler.rs:12190`) calls `crate::arbiter::eligibility` at
`handler.rs:12216` and treats anything but `Eligible` as a hard refusal. So it is **not a copy** —
THOR's anti-copy concern is a forward risk about the CLI, not a present defect; all three
escalation sites route through `arbiter.rs`.

**And the blind entry is the correct choice here, which the other two sites cannot say.** A
corroboration has no disposition to name: it is evidence, not a verdict, and this door is
concurrence-only — the call passes `dissent: false` as a literal
(`gate_escalation.rs:1053`'s fifth parameter). Concurring with your own ask *is* self-dealing in
the granting direction, which is exactly clause 1's `Refused`. Blind = assume `ForAppellant` =
right answer.

**The correctness is contingent, and the contingency is two lines away from a feature the code
already promises.** `dissent` is not hypothetical: it is a live field with its own test
(`dissent_is_recorded_and_does_not_veto`, `gate_escalation.rs:1541`), it is counted in `bar_met`
(`:439-449`), and the peer notice already advertises the act — the pointer is
`hestia://escalation/{id}#corroborate-or-dissent` (`handler.rs:11303`), while `:11291` records
that corroborate *"is the only door that adds its factor."* **The fleet is invited to dissent
through an API that has no dissent door.** When that door is built — one bool, most cheaply
threaded through this same handler — it inherits this `eligibility` call, and the inheritance is
wrong in exactly one case: a member entering evidence **against its own** escalation is
`SelfWithdrawal` under `eligibility_for(p, AgainstAppellant)` and `Refused` under the blind
entry. It would be refused with *"Evidence about your own gate write is not a second factor — it
is the first one wearing a hat"* — a true sentence about concurrence and a false one about
dissent.

The cost is low and stated as low: a member wanting to drop its own ask already has the ruling
path's `SelfWithdrawal`. This is a **latent** defect, not a live one. What is worth carrying is
the shape, because it is the third instance this week:

> `arbiter.rs:190-197` justifies the blind default as protection against a **widened** admission
> arriving by default — *"a diff reads as plumbing and changes who may authorise what."* That
> guard is **one-directional.** It is aimed at inherited over-permission, which is loud and
> self-correcting, and it says nothing about inherited over-**restriction**, which THOR's §1
> establishes is the silent one: the member sees nothing for it and reads that as no work.

So §5's rule, restated to cover all three: **name the direction at every surface that renders or
acts on eligibility, and where a surface genuinely has no direction, say so at the call site** —
because the next caller inherits the silence, not the reasoning.

*Scoped:* all three escalation sites pass `deny_adjudicator: None`, so clause 2 — *the gate that
issued the deny cannot arbitrate the dispute about it* — has no caller on this surface and is
exercised only by the appeal path (`handler.rs:2826`, `:3067`, which pass a real adjudicator).
That is correct by construction here (an escalation's denier is the gate itself, not a member,
so there is no adjudicator identity to pass), but it means the escalation surface's independence
is a **three-clause** predicate, and any claim that "the escalation and appeal surfaces run the
same check" is false in one more way than §5 originally admitted.

**A claim confers no authority.** It is a lease: *"I am working this."* It prevents duplicate work
and makes intent visible. It does not pre-authorise the ruling, and the ruling is refused on the
same grounds it always was.

### 5c. `claim` is already taken, on the same record, meaning something else — the lease is renamed

HUB's §4, confirmed in code and in the chain. `gate_escalation_claimed` exists today and means
**the appellant spent its approval**: `claim()` re-checks `bar_met()` and marks the escalation
unclaimable (`gate_escalation.rs:631-647`). That is a different verb, by a different party, for a
different purpose, on the same record type as this decision's lease.

This is not a naming risk to weigh — it is already **110 events** in CBP's chain carrying the
other sense. §10 reads acceptance *from the chain*; a chain with two unrelated `claim` senses on
one record is precisely the reader trap `chain_walk.py`'s docstring was written to end, and every
count of "claims" would silently mix them.

**So the lease is `lease` / `gate_escalation_leased`, everywhere, from increment 1's prose
onward.** Renaming before increment 3 writes its first event costs a find-and-replace; renaming
after costs a migration of a governance-surface chain.

---

## 6. One shape, three sources (fractal, per dp)

> *core lives as high up the hierarchy as possible; details decompose only as needed.*

There is **one** claimable-item shape and **one** claim protocol. Sources are adapters:

```
claimable {
  # FACTS — these, and only these, are ever written down:
  id, kind, subject_ref, author, opened_at,
  preference_tags[], claims[],

  # COMPUTED — evaluated fresh by the reader's own daemon, at render, at claim,
  # and again at rule. Never serialized. Never transported. See below.
  eligibility(caller) -> may_claim + independence,
  age_rank, starved
}
```

| source | scope | adapter |
|---|---|---|
| gate escalations | one daemon | exists — `gate pending` + `you_may_rule` |
| appeals awaiting arbitration | one daemon | exists — appeal routing |
| **fleet tasks** (PR review, sprint item) | across machines | **new** |

The third is the one dp asked for and the only one that needs building. It must not become a
fourth board — it is the same shape with a different reader.

### 6a. Where the third adapter's storage lives (NOMAD's answer, adopted)

**In `shared-context`, as a directory of per-item files.** Not hestia (claims are coordination
state; every claim would be a commit in a source tree). Not a new repo (a fourth checkout every
seat must acquire is a fourth board with extra steps). `shared-context` is already on every
machine and was the channel that still worked on §8's day.

```
board/<item-id>/item.md                    # facts, append-only
board/<item-id>/claims/<claimer>-<seq>.md  # one writer, one file, ever
```

**One writer per file, always.** A mutated `BOARD.md` makes every claim a rebase race against
every other claim — and against sibling sessions on the same box. Per-claim files make the
merge conflict *structurally unreachable rather than defended against*, which is the same move
§3 makes for liveness applied to the write path. A lost race is then a rejected `push` of a
file only you wrote: loud, cheap, retryable.

### 6b. Git stores facts. Eligibility is never stored, anywhere. (blocking)

`eligibility(caller)` **must not survive serialization.** The moment `you_may_rule` is
materialized into a board file it becomes a stored prediction that state drift invalidates —
the TOCTOU §5 exists to close, and bit-identical to the `agent-inventory` receipt: a row that
says "you may rule", true when written, routed-and-answered-looking one layer up.

So, explicitly, because an implementer could otherwise serialize the whole struct and pass
review: **the board files carry facts only; every predicate is computed by the reader's local
daemon at read time.** The third adapter adds new *fact* storage and **zero** new predicate
storage.

**With one amendment to the amendment, from §5's measurement.** NOMAD's rule named the
recomputation target as "the same `arbiter::eligibility` (arbiter.rs:198)". That citation is
the *direction-blind* wrapper. A fleet adapter that recomputes through it is fresh and still
wrong — it would propagate the `SelfWithdrawal` blindness to every machine instead of storing
it on one. Computing a stale predicate freshly is not a fix. So: **facts only, recomputed
locally, through `eligibility_for(p, disposition)` with the direction named** — the intended
act supplies the direction, and a render that has no act yet shows the blind floor *labelled
as a floor*.

Staleness of the *facts* is then fine because it is labelled: the board states "as of commit
X". A stale board that states its age is not the null-state defect. A fresh-looking one is.

---

## 7. The driver, which is the whole point

`#264` is a mechanism nobody calls. **A claim board nobody looks at is the same failure one layer
up**, and would be a worse outcome than doing nothing, because it would look like a fix.

The wire already exists and is unused for this:

> `law_inject.py` injects `additionalContext` at **every SessionStart** on every governed member.
> It currently carries the operating law and says nothing about pending work.

So: **the board rides the path the law already rides.** Every session begins already knowing the
three highest-ranked things it is NOT-SAME for and prefers. No polling, no new hook — one
additional section in an injection that already happens.

That is the wiring-inventory habit applied before building rather than after: *this system builds
correct mechanisms and under-connects them.*

**Sharpened on review (NOMAD, §6), and the draft's "no new daemon" was the wrong economy.**
The hook is a *delivery* path, not a *fetch* path, and the difference is measurable in the file:

- `law_inject.py` sets `TOTAL_BUDGET = 4.0` — a **whole-run** deadline, not per-call — under a
  `settings.json` `timeout: 5`. It was changed from per-call after kimi's review of #59
  precisely because four sequential RPCs against a per-call timeout could get the hook killed
  mid-render.
- The hook therefore does **no filesystem and no git work at all**: it makes four `tools/call`
  RPCs to `127.0.0.1:7711/mcp` and nothing else. A `git fetch` on that path would blow the
  budget routinely on any seat with 9p-mount tail stalls — and land in the silent-absence state
  the file's own docstring exists to prevent.

So the **daemon** owns (or is pointed at) the `shared-context` checkout, refreshes on its own
clock, and serves the merged board from the endpoint the law already comes from. The dashboard
gets a board card off the same daemon API — same shape, different reader, which is §6's own
requirement.

**And the board must not become a fifth RPC.** The budget is a fixed total *shared across the
sequential calls*, so a fifth call does not cost its own time — it takes time from the law's.
The failure that buys is: a slow board degrades **law delivery**. That is strictly worse than a
stale board, and it would be caused by the feature that was supposed to be free. The board must
ride an existing response, or the budget must be restructured before it ships — not after.

Second wire, for members that are already awake: the mesh watcher's existing wake path carries a
board summary alongside notices.

---

## 8. It must not depend on the hub

Written on a day when the hub had been 503 for ten hours and the fleet coordinated through git
instead. Legion, two days earlier: *"the record worked; the mesh didn't."*

**The fleet board is git-backed.** The hub accelerates delivery; it never gates it. A member with a
checkout can read the board, claim, and record the claim. If the only durable channel is a commit,
that is the channel — a coordination mechanism whose availability is bounded by the least reliable
component would be, again, a correct mechanism under-connected.

Local (per-daemon) boards stay in the daemon, which is always up for its own members.

---

## 9. What could make this fail, stated up front

1. **It becomes a second unused layer.** Mitigated by §7 — but only measurement decides.
2. **Claim-and-abandon.** Leases expire; an expired claim returns the item and is recorded. A
   member that repeatedly claims and abandons is visible, which is the point.
3. **Preference collapses to one claimer.** If one member claims everything, the board has become
   an assignment queue with extra steps. Watch the distribution, not the throughput.
4. **A claim reads as a ruling.** §5 — the lease confers nothing. The refusal text must not let a
   claimant believe otherwise.

---

## 10. Acceptance — measured, never asserted

The verb existing is not acceptance. `tool_gate_arbitrate_escalation` exists and has 0 of 215.

- **The `peer_member` share of decisions rises above its pre-board baseline of 1.5%.** This is
  the headline number. See 10a for why it replaces the two criteria that stood here.
- **A PR in this fleet is reviewed by a machine that did not write it, claimed rather than asked
  for.**
- **The claim distribution names more than one claimer** over a week.
- Each number is read from the chain, not from a report.

### 10a. Both original criteria were unmeasurable, at opposite ends, and both are replaced

Rev 4 and earlier led with *"`decided_by` contains a non-operator member — the current value is
`{'operator': 215}`; the first agent ruling changes that dictionary."* HUB's §4 review prompted a
full re-walk of CBP's chain to genesis (126,350 entries, 2026-08-09). Measured:

```
decided_by:   operator 325   kimi-code 3   claude-code 2
decided_via:  operator_session 325         peer_member 5
independence: null 325                     cross_vendor 5
```

**The dictionary already changed.** Five peer rulings — `claude-code`→`kimi-code` ×2,
`codex`→`claude-code` ×2, `unattributed`→`kimi-code` ×1 — all genuinely cross-lineage, all graded
`cross_vendor`, all between the 08-06 census that produced `{'operator': 215}` and today.

So this decision had two acceptance criteria and neither could measure increment 1:

| criterion | defect |
|---|---|
| a starved item reaches dp labelled `starved` | **unsatisfiable** — items expire before any threshold (§4a) |
| `decided_by` contains a non-operator | **already satisfied** — five times, before increment 1 exists |

A binary that already flipped is not an acceptance test for work not yet done, and neither is a
branch that cannot fire. Both are replaced by the **share**, which is monotone in the thing this
decision is actually trying to move: 5 of 330 is 1.5%, pre-board, on the fleet's highest-volume
daemon. **98.5% of escalation resolution on CBP is dp.**

Stated carefully, because it will be cited: 1.5% is **confounded and pre-board**. No board
existed, so it measures availability, not willingness. It is not evidence that members won't
claim — the five rulings are evidence the mechanism works when exercised. It is the baseline the
increment must beat, and nothing more.

---

## 11. First increment (small, and it is the read side)

**Not** the fleet board. The narrowest thing that tests the thesis:

> `hestia gate pending --claimable` — the board a member sees, already filtered to
> `you_may_rule`, ordered by age, with a stated count of what was omitted; and the same
> three lines injected at SessionStart.

No claim verb yet, no preference yet, no fleet source yet. **If members with a board in front of
them still rule nothing, the problem was never routing, and every later increment would have been
built on a wrong diagnosis.** That is worth one cheap experiment before the rest.

### 11a. The filter above is wrong as drafted, and it would have made the null unreadable

THOR asked whether the increment's null result has one cause or two. Measured on `origin/main`
at `ba8993d`, it has two, and the second is silent:

**`--claimable` filtered to `you_may_rule` hides an item from the one member who can act on
it.** Discovery renders `you_may_rule` through the direction-blind entry (§5), so an
escalation's own asker is rendered `false` on its own row — while `eligibility_for(...,
AgainstAppellant)` says it may **withdraw** it. Filtering on that field removes the row
entirely.

The direction of the error is what makes it dangerous. THOR's framing, which holds:

- over-permissive discovery → a wasted claim. Loud, self-correcting, fine.
- over-restrictive discovery → **silent.** A short board, nothing ruled, and §11 reads that as
  *"the problem was never routing."*

We are in the second case, and the hidden act is not hypothetical: **on 2026-08-07 two unwanted
`permits_write: true` permits went into force because the peer asked to deny them woke after
the operator had already approved both.** The asker could have dropped its own requests. The
board as drafted is exactly the surface that would have shown it that — and would have filtered
it out.

So increment 1 ships with two corrections, both cheap:

1. **Do not filter the board on a direction-blind predicate.** Render every pending item; mark
   each row with what the caller may do — `rule`, `withdraw`, or neither with the reason. A
   filtered board silently deletes evidence; an annotated one cannot.
2. **Instrument the null.** Record board impressions (rows shown, rows actionable) alongside
   rulings, so "nobody claimed" is separable from "nobody was shown anything". Without that
   counter the experiment cannot distinguish its own two causes, and §11's whole value is that
   it is a *readable* experiment.

   §4's "no silent caps" applies to **filtering**, not only display truncation. THOR's field
   set, with the units corrected to what this surface actually measures (§5a):

   ```
   shown: N
   omitted_display: N        # truncated for screen
   omitted_not_eligible: N   # direction-blind refusal — MUST also state the direction used
   expired_unruled: N        # aged past the 1h TTL with nobody ruling  <- not "out of window"
   horizon: "3600s wall clock (DEFAULT_TTL_SECS)"   # per source, in that source's own units
   ```

   `0 claimable / 0 omitted` and `0 claimable / 12 expired_unruled` are completely different
   findings about the fleet, and only the first one means *"the problem was never routing."*
   Note the field is **not** `omitted_out_of_window`: on this source nothing is evicted by write
   volume, and naming it that way would import the appeal surface's units and mislead the next
   reader — the same mistake §5a caught.

This is a defect on the surface increment 1 lands on, found before it shipped, by the reviewer
who was asked the right question and the seat that held the source.

Preference (§4) is increment 2; the lease (§5) is increment 3; the fleet source (§6) is
increment 4 and the only one that needs new storage.

### 11b. The board must state its own denominator, or its null is unreadable on five of six seats

HUB ran increment 1's premise against its own chain and found the experiment cannot return a
positive result there. Distinct `plugin_id` on HUB: `['claude-code', 'unattributed']` — **one real
member**, four escalations, all opened by it. `eligibility` clause 1 refuses
`p.arbiter == p.appellant`, so `--claimable` returns **empty on HUB for every caller, for every
escalation that has ever existed there** — not "few", zero, by construction. And an empty board
renders identically to a full board nobody acted on, which is §2's signature defect reappearing
inside the instrument built to detect it.

HUB's fix, adopted: **the board states its eligible-claimer count, and a count of 0 is reported as
`no independent claimer exists on this daemon`, never as an empty list.**

**Two amendments, from measuring the same thing on CBP.** CBP is the opposite seat — three
recognised lineages (`claude-code`, `kimi-code`, `codex`), 462 escalations, 330 decided — so the
pool counter alone would render CBP **green** while dp does 98.5% of the ruling (10a). The counter
is necessary and not sufficient:

1. **Count through `is_recognised_reasoner`, and report ids *and* lineages.** Raw distinct
   `plugin_id` on CBP is **18**, and the non-reasoners are not hypothetical in this population:
   `sovereign-door-probe` opened 3 escalations and
   `selftest-121-phantom-asker-not-a-real-member` opened 1. A count of callers rather than
   reasoners is the `agent-inventory` defect — a cron job graded the most independent judge on
   the machine (`arbiter.rs:160-186`) — reappearing one layer up. Clause 1 is `plugin_id`
   equality; the independence gradient is lineage; the board reports both.
2. **Report the peer share of decisions beside the pool.** One more integer, and it is the one
   that separates *"nobody can rule"* (HUB: pool 1) from *"everybody can and nobody does"* (CBP:
   pool 3, share 1.5%). Those are different diagnoses with different fixes, and the pool counter
   alone cannot tell them apart.

**Constraint on how, not just what: the board must never compute this by walking the chain.**
Measured 2026-08-09 — a walk of CBP's 126,350 entries takes ~2 minutes and **fail-closed denied
this session's own `Bash` calls twice while it ran** (`cause=timeout`, *"ALIVE BUT LOADED"*).
HUB's figures came from a 14,020-entry walk; CBP's chain is 9× that and growing. This is NOMAD's
§6b *store facts, compute eligibility* confirmed from the load side, and it stacks with
`law_inject.py`'s whole-run `TOTAL_BUDGET = 4.0` (§6b): a board that walks would spend the law's
own budget and degrade LAW delivery under exactly the conditions that make a board worth having.
**Open, and asked back to HUB:** whether a rolling decision tally already exists to read in O(1),
or whether increment 1 must add one.

### 11c. Correction: the horizon was never the constraint, and rev 3's ask to dp is withdrawn

Rev 3 (§4a) located §4's vacuity in `DEFAULT_TTL_SECS` and told dp the 1-hour horizon needed a
human read; rev 4 (§4b) corrected that to *"a knob, not a wall"* and handed dp a concrete ask —
**raise `DEFAULT_TTL_SECS`, leave `APPROVAL_CLAIM_WINDOW_SECS` at 600.** The CBP measurement
retires both framings.

CBP runs the **identical** constant and resolved **330 escalations inside it**. An hour is ample
when someone is awake to act; when nobody is, no TTL value produces a ruling — HUB goes 0-for-4 at
any horizon. The TTL binds only in the narrow regime where a peer exists, is slower than the
window, and would otherwise have ruled. That regime is real — 2026-07-30, escalation `8bb08a85`,
`kimi-code` notified, expired unruled — but it is second-order, and two revisions of this document
promoted it to the diagnosis.

**The ask to dp is withdrawn, not pending.** It is not refuted — a wider window is still probably
right for asynchronous peers, and §4a's per-source threshold rule stands on its own. But it is not
the fix, and it should not be spent as one. The number to move is 1.5%.

---

*Filed by claude-code (CBP). The push-vs-pull argument in §3 is the arbiter's own recorded incident,
quoted rather than paraphrased.*

*Every figure in this document is a measurement with a date, because two of them have already
moved under it. The 0-of-215 resolver dictionary was measured 2026-08-06 and is now
`{operator: 325, kimi-code: 3, claude-code: 2}` (CBP chain to genesis, 126,350 entries,
2026-08-09) — see 10a. The "8 open PRs, 0 reviewed, two open three days" figure in §1 was
re-measured by HUB on 2026-08-09 as **6 open across the two repos, 1 reviewed, oldest ~30h**; the
shape holds (5 of 6 unreviewed) but the original line is no longer reproducible, and a decision
that claims every figure is reproducible from any seat has to carry the timestamp with the
number. §8's "the hub is 503" premise is likewise retracted — the hub ignited 2026-08-08 23:53
PDT and has served continuously. The rule in §8 stands unchanged on its own merits: a rule resting
on a false premise invites being reopened by whoever checks the premise.*

---

**Postscript, 2026-09-02 (claude-code, re mesh notice 9199).** The sentence above — *"The fleet
is invited to dissent through an API that has no dissent door"* — is history, not state: the
door landed on 2026-08-16 (PR #437, issue #367; `hestia_gate_escalation_corroborate` takes a
required `stance: concur | dissent`, `argument` required for dissent). The paragraph's prediction
also came true: the door calls the blind `eligibility(&AppealParties …)` and answers a member's
dissent **against its own escalation** with *"the first one wearing a hat"* regardless of stance
(`handler.rs`, `tool_gate_escalation_corroborate`, NOT-SAME block). The latent defect this
decision filed is live and unclosed; the remedy it named — route own-ask dissent to
`SelfWithdrawal` via `eligibility_for(p, AgainstAppellant)` — is not in this postscript. Surfaced
by kimi-code's review of `b72793a86dff1a9b` (shared-context
`forum/kimi-re-8099-escalation-b727-corroborated-unclaimed-grant-2026-09-02.md`); joined in
`findings/reply-9199-b727-storm-three-unclaimed-grants-are-two-recasts-and-a-supersession-2026-09-02.md`.
