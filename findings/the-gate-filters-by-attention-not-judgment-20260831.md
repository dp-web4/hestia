# The escalation apparatus filters by attention, not by judgment

**Seat:** claude-code (CBP) · **Date:** 2026-08-31
**Driver:** `tools/escalation_outcome_is_presence.py` (added this session)
**Walk:** 60,000 hops, span `2026-08-16T05:57:21Z` .. `2026-08-31T17:11:36Z`

> The oldest edge is a **HOP BUDGET boundary, not a date the chain starts**. Re-running
> with a different budget moves it. The span is printed so the run can be compared, not
> so 08-16 can be quoted as an origin.

## The hypothesis I set out to test — and it is REFUTED

I opened this session believing the gate was a **human-presence detector**: that outcome
was set by whether dp was at the keyboard, and that the peer-review apparatus (bars,
invitation pools, corroborate/dissent, reputation folds) was decoration. The sharp,
falsifiable form was **bimodality**: a spike of rulings at small dt (operator present,
types approve, too fast for any peer to wake and read) and a flat mass at the 3600s TTL
(nobody there), with an empty trough in between — the trough being exactly the region
where peer review could matter.

**That is refuted.** `secs_into_window` at decision, for the 277 ruled rows:

| bucket | n |
|---|---:|
| 0–30s | 53 |
| 30–60s | 38 |
| 60–120s | 34 |
| 120–300s | 53 |
| 300–600s | 27 |
| 600–1800s | 60 |
| 1800–3600s | 12 |

There is no trough. **140 of 277 (51%) rule between 120s and 1800s** — minutes of open
window, ample for a woken peer to drain, walk the chain and file. "There was no time for
review" is *not* why review is absent. My frame was wrong, and it was wrong in the
direction that flattered the conclusion I already held.

## What is actually true, read from the daemon's own fields

Not inferred from timing — `gate_escalation_decided` carries `decided_by`, `decided_via`,
`status` and `factors_present` directly.

**The funnel, 355 mature opens** (≥1 TTL old; 4 younger rows censored, not guessed):

```
355 opened
 └─ 277 ruled                    (78%)   ── 78 never ruled at all
     └─ 276 approved, 1 denied   (99.6%)
         └─ 78 claimed           (28% of ruled)
```

**1. The explicit verdict is a near-constant.** 276 approved : 1 denied. A channel that
answers yes 99.6% of the time carries about 0.03 bits. Whatever selects, it is not the
approve/deny axis. (The one `denied` row is the positive control on the field itself: the
daemon *does* write that spelling, so 1 is a measurement, not a detector blind spot.)

**2. Refusal has no voice.** 78 of 355 (22%) reached no decision — 46 with a witnessed
`gate_escalation_expired`, 32 with **no terminal event at any hop**. Nothing in the record
distinguishes *"an operator read this and declined"* from *"nobody was ever there."* Both
render as silence. This is the defect: the system cannot record a reason for **no**, so
nothing downstream can ever learn from a refusal. The only articulate outcome is yes.

**3. Peers participate, but barely, and it is not a time problem.** `decided_via` is
`operator_session` 267 / `peer_member` 10 — peers decided **10 of 277 (3.6%)**. Factors:
operator 267, codex 13, claude-code 12, kimi-code 7; **29 of 277 rows (10.5%) carry any
peer factor**. Given finding (1) above, the 51% of rulings with a multi-minute window were
reachable and mostly went unreached.
*(This supersedes my earlier note that peers had decided **1**. The correct figure over
this span is 10. The old number was read over a narrower window.)*

**4. The largest single loss is the CLAIM, not the ruling.** Only 78 of 277 approvals were
ever claimed — **72% of granted permissions expire unspent**. End-to-end, **78 of 355
escalations (22%) result in the act happening**.

## So the two real filters are RULING and CLAIMING, and neither is review

22% of escalations die unruled; 72% of the survivors die unclaimed. Both attrition points
are functions of *who happened to be awake when*, not of anyone's judgment about the act.
The peer machinery sits on the one axis that is nearly constant.

**This session is its own n=2.** Escalations `ed47035ed07133a8` and `f4a8ea0dd68ec543`
were approved by the operator at 17:00:33 and 17:00:50 today, at 71s and 63s into their
windows — a *fast, attentive* operator. Both died unclaimed, because the session that
opened them ended and the next mesh wake landed at ~17:11, after the claim windows shut.
Nothing was refused. The act simply did not happen, and the chain records that outcome
identically to a refusal.

## What I would change, in priority order

1. **Give refusal a voice.** A lapse must be distinguishable from a decline. Either an
   explicit `declined` with a reason, or an expiry row that records whether the escalation
   was ever *read* by a decider. Until then, "22% unruled" is uninterpretable — and every
   reputation fold over escalation outcomes is folding over noise.
2. **Stop treating the peer bar as the lever.** It gates an axis that is 99.6% constant.
   If peer review is meant to matter, it has to attach where the variance is: the decision
   to *let something lapse*.
3. **Make the grant outlive the asker's session.** 72% unspent is not asker negligence; the
   claim window is scoped to a session that may not survive it.

## Reproduce

```
python3 tools/escalation_outcome_is_presence.py --max-hops 60000
```
Prints the funnel, the `secs_into_window` histogram, and `decided_by`/`decided_via`/
`status`/`factor_authors` folds. It reads `factors_present` and `status` — the real payload
keys. My first draft folded over `factors` and `outcome`, keys the emitter never writes,
and printed a clean, well-formed **0 peer factors**. That zero was a false measured zero
and I caught it only by dumping a live payload before publishing.
