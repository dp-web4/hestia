# The promise outlived the predicate: the approval panel has been telling the operator the opposite of the truth for 25 days

**Seat:** claude-code (CBP) · **Date:** 2026-08-31
**Subject:** `core/src/server/dashboard.rs:1244`, `core/src/server/dashboard/index.html:3270`,
`core/src/server/gate_escalation.rs` (`bar_met`)
**Status:** verified at source, **in force in the running build** (`c991e12`, installed 2026-08-30)

## The claim

On every `sovereign_plus_peer` escalation with no peer factor, the operator's approval panel
renders, in warning colour:

```
YOUR APPROVAL ALONE WILL NOT PERMIT THIS — still needs an independent NOT-SAME peer factor
(hestia_gate_escalation_corroborate)
```

That is false, and has been since `9d3936d` (2026-08-06). The operator's approval alone is
sufficient. It always completes the bar, permits the claim, and unblocks the write.

## Verified at source, three steps

1. `gate_escalation.rs`, `bar_met`, `SovereignPlusPeer` arm:
   `self.factors.iter().any(|f| f.channel.is_sovereign())`. **The peer conjunct is gone** —
   `9d3936d` made it evidence rather than a gate, after #219 censused the old rule at 0-of-66
   bar-met lifetime.
2. `decide()` **always appends the decider's own factor**, with `channel: via`. The operator
   route passes `Channel::OperatorSession`.
3. `Channel::is_sovereign()` is `matches!(self, OperatorSession | LocalCli)`.

So the instant the operator clicks approve, a sovereign factor exists, `bar_met()` is true,
and `is_claimable()` follows. There is no path on which a `sovereign_plus_peer` escalation
needs a peer to be claimable.

Meanwhile `dashboard.rs` computed the same question with its own copy of the *old* rule:

```rust
Bar::SovereignPlusPeer => e.factors.iter().any(|f| f.channel == Channel::PeerMember)
```

Correct on 2026-08-04, when it was written. Inverted two days later.

**In force, not merely in `main`.** `git show c991e12:core/src/server/dashboard.rs` carries the
stale predicate and `c991e12:core/src/server/gate_escalation.rs:591` carries the relaxed
`bar_met`. That build was installed 2026-08-30 and is what serves the panel now.

## Why it survived: a still-open list is forward-looking, an inverted invariant is not

`9d3936d` touched `gate_escalation.rs` and `handler.rs` and nothing else. Its commit message is
unusually careful — it rewrites rather than deletes the superseded test, explains the change of
law, and **names the dashboard as remaining work**:

> STILL OPEN, and named rather than quietly skipped: the liveness-anchored invitation window
> … and the dashboard dissent surface.

The dashboard was on the list. But it was on the list as a **missing feature** — surfacing
dissent — not as an **existing sentence that had just become false**. Nobody went looking for
statements the change had inverted, because that is a backward-looking audit and a TODO list is
a forward-looking one.

This is the generalisable bit, and it is the third instance of the same shape I have hit this
week: *when you relax a predicate, the work is not only "what have I not yet built" but "what
already asserts the old predicate."* Prose, tests, dashboards and docstrings all assert
predicates, and none of them are type-checked.

## The irony is exact

That panel exists **because of this failure mode, in the opposite direction**. Its own source
comment records the origin:

> dp, 2026-08-04: *"do they actually unblock anything when i approve?"* — asked after approving
> one whose bar was `sovereign_plus_peer`, which recorded `approved` and still refused the
> write, because no peer had corroborated.

The remedy for that was a discriminator telling the operator when their approval is not enough.
Two days later the condition it discriminates stopped existing, and the remedy became a
generator of the same confusion with the sign flipped. The UI comment even says why this line
matters most:

> Colour it, because a sentence in the metadata line is easy to skim past and this is the one an
> operator must not skim.

So the highest-salience element on the approval surface is the wrong one.

## What it costs, given what this fleet actually is

The false sentence does not merely misinform — it **prescribes a wait**, and names the tool to
wait for (`hestia_gate_escalation_corroborate`). Set that against what I measured earlier this
week:

- **44% of 357 escalations invite nobody at all** → 1.3% factor rate vs 64–72% when invited.
- Peers decided **10 of 275**; of acts reaching a human the operator has never said no (267/267).
- Invited seats are frequently not alive to answer: **codex 39.7%, kimi 26.8%** of wakes died.
- Peer review is busy but late — median factor lands **+647s after** the ruling.

The panel tells the operator to wait for an event that, on this fleet, structurally almost never
arrives — on the exact class of escalation (`pre_tool_use.py`, `post_tool_use.py`, `witness.py`,
`hestia_gate_mechanism.py` — see `bar_for`) that governs the gate itself. Those are the four
files this fleet edits most.

I have **not** yet measured how many live escalations were rendered with the false warning; a
full chain walk (205,824 entries) is running and is not finished. That number is untested, not
refuted — the defect is confirmed at source and in the running build regardless of its count.

## Remedy: derive the promise, do not restate it

The root cause is that one question had two implementations. The fix makes it have one.

- `Escalation::bar_met_over(bar, channels)` — the single place a bar is evaluated.
- `bar_met()` runs it over the factors **present**.
- `operator_alone_suffices()` runs the same predicate over the factors that **would** be present
  after a lone sovereign decision — i.e. it simulates the click.
- `still_needs()` derives from that.
- `dashboard.rs` calls the two methods and holds no copy of the rule.

Because the promise is computed by simulating the act it predicts, relaxing or re-tightening a
bar can never again leave the operator surface asserting the old one.

### The test pins the property, not the current answer

`the_promise_shown_before_the_click_predicts_what_the_click_does` asserts, for every marker class
`bar_for` routes: whatever `operator_alone_suffices()` said **before** the decision must equal
`bar_met()` and `is_claimable()` **after** a lone operator approval. It does not transcribe
today's bar into an expected value — a transcription is exactly what `dashboard.rs` contained,
and it passed review for 25 days while asserting the opposite of the code it described.

## Second finding, found by running the suite: a dead test and a double-counted one

The build emits `function a_single_approval_meets_a_single_approver_bar is never used` and
`duplicated attribute`. Both trace to `6266dd9` (**2026-08-04**, the same 48 hours), which
inserted a new test *between an existing `#[test]` and its function*:

```
#[test]                                   <- belonged to a_single_approval...
/// doc comment for the new test
#[test]
fn a_marker_the_gate_never_presented_...  <- took the orphaned attribute too
...
fn a_single_approval_meets_a_single_approver_bar()   <- no longer a test
```

Consequences, both measured by diffing the emitted test lists:

- `a_single_approval_meets_a_single_approver_bar` **ran zero times for 27 days** — including
  through `9d3936d`, which rewrote the very predicate it guards.
- `a_marker_the_gate_never_presented_yields_an_unclaimable_approval` was **registered twice** and
  ran twice.

So `main`'s green **"59 passed" was 58 distinct tests**: one run twice, one never run. The count
was wrong in both directions at once, and the compiler said so the whole time — in a build that
carries 21 warnings, which is the same as not saying it.

Revived, it **passes**. Stated plainly: it hid no regression. But it also certified nothing for
27 days, and it was the SingleApprover guard sitting dead across the week the bar was rewritten.

## Accountability self-audit

```
surface: operator escalation approval panel   act: approve a governed write (grant a permit)
S: high/irreversible-in-effect [construct: gate_escalation::decide -> is_claimable -> claim]
R: n/a [construct: unchanged — LCT-authenticated operator session]
W: pass [construct: Channel::OperatorSession, decide() records decided_by/role/via]
O: pass [construct: no side effect added; both new methods are pure reads over `factors`]
A: pass [construct: unchanged — decide() commits status+factor together into the chain entry]
V: n/a [construct: no veto path altered]
verdict: PASS — this diff removes a false statement from a decision surface and adds no act.
```

## So what?

Two of my last three findings, and this one, are the same defect at different layers: **an
instrument that kept describing a rule after the rule changed.** The ratchet counted copies after
the risk moved to divergence; the ledger counted obligations after the bounce semantics changed;
this panel counted peers after the peer conjunct was dropped.

The common cause is not carelessness. It is that in every case the *authoritative* value and the
*described* value were computed in two different places, and only one of them was under test. The
remedy is the same each time and it is not "be more careful": **make the description a function of
the thing it describes**, so there is no second copy to go stale.

The sharper version, which I had not seen before today: a change that carefully lists its own
remaining work will still miss this class, because the list is of things *not yet built*, and an
inverted invariant is a thing *already built that just became false*. `9d3936d` did the
conscientious thing and still shipped the defect. That is worth more attention than a lecture on
diligence — it says the missing step is a mechanical one (what asserts this predicate?), not a
motivational one.
