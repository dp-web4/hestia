# 0015 — NOT-SAME work is **claimed**, not assigned

**Status:** proposed
**Date:** 2026-08-09
**Author:** claude-code (CBP), at dp's direction
**Supersedes nothing. Answers:** `#264` (the third verdict), and the standing review bottleneck.
**Revision 2 (2026-08-09)** — amended from fleet review: §5 corrected (THOR), §6/§7 answered and
sharpened (NOMAD), §11 given a measured defect it would otherwise have shipped on. All new
figures measured against `hestia@ba8993d`. `acting_on: 5c66a16c-5b27-432a-a68a-bf50285a3774`

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

One module, one rule set, no drift — but **two predicates**, and they disagree on exactly one
enumerable case: `p.arbiter == p.appellant` under `AgainstAppellant` returns `SelfWithdrawal`
(permitted) from the direction-aware entry and `Refused` from the direction-blind one. The
blindness is deliberate and correct at its own site: `arbiter.rs` states that the relaxation
"is opted INTO by naming a direction; it is never inherited by a caller that was not written
with the distinction in view."

So the requirement is not "call the same function" — it is **name the direction at every
surface that renders or acts on eligibility**, and treat a direction-blind render as a floor,
never as the board. THOR's third window (eviction) is accepted separately; this is the second.

**A claim confers no authority.** It is a lease: *"I am working this."* It prevents duplicate work
and makes intent visible. It does not pre-authorise the ruling, and the ruling is refused on the
same grounds it always was.

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

- **`decided_by` contains a non-operator member.** The current value is `{'operator': 215}`; the
  first agent ruling changes that dictionary, and that is the headline number.
- **A PR in this fleet is reviewed by a machine that did not write it, claimed rather than asked
  for.**
- **A starved item reaches dp labelled as starved**, distinguishable from an unrouted one.
- **The claim distribution names more than one claimer** over a week.
- Each number is read from the chain, not from a report.

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

This is a defect on the surface increment 1 lands on, found before it shipped, by the reviewer
who was asked the right question and the seat that held the source.

Preference (§4) is increment 2; the lease (§5) is increment 3; the fleet source (§6) is
increment 4 and the only one that needs new storage.

---

*Filed by claude-code (CBP). The push-vs-pull argument in §3 is the arbiter's own recorded incident,
quoted rather than paraphrased; the 0-of-215 and 8-PRs-0-reviews figures are measured and
reproducible from any seat.*
