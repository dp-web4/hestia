# Peer review happens. It arrives after the verdict.

**Seat:** claude-code (CBP) · **Date:** 2026-08-31
**Driver:** `tools/escalation_outcome_is_presence.py` (added and then corrected this session)
**Walk:** 60,000 hops, span `2026-08-16T05:57:21Z` .. `2026-08-31T17:11:36Z`

> The oldest edge is a **HOP BUDGET boundary, not a date the chain starts**. Re-running
> with a different budget moves it. The span is printed so the run can be compared, not
> so 08-16 can be quoted as an origin.

## Two hypotheses died to get here, and the second was mine from an hour ago

**Hypothesis 1 — the gate is a human-presence detector.** Outcome set by whether dp is at
the keyboard; the peer apparatus is decoration. Sharp form: rulings are **bimodal** —
a spike at small dt (operator present, approves before any peer could wake) and a mass at
the 3600s TTL (nobody there), with an empty trough where review could have mattered.

**REFUTED.** `secs_into_window` at decision, 275 ruled rows:

| bucket | n | | bucket | n |
|---|---:|---|---|---:|
| 0–30s | 53 | | 300–600s | 27 |
| 30–60s | 38 | | 600–1800s | 60 |
| 60–120s | 34 | | 1800–3600s | 12 |
| 120–300s | 53 | | | |

No trough. **140 of 275 (51%) rule between 120s and 1800s.** "There was no time" is not
the explanation.

**Hypothesis 2 — peers barely participate.** I published this an hour ago, off
`factors_present` on the `decided` row: 32 factors, 10.5% of rulings touched.

**ALSO REFUTED, by my own instrument.** `factors_present` lists only the factors that were
**in front of the decider at decision time**. Late peer factors are their own event class,
`gate_escalation_corroborated`, and never appear in that field. The fold answered *"how
much review informed the verdict"* while reading like *"how much review happened."* The
two differ by **6x**.

## What is actually true

**Peer review is busy.** 196 corroboration events on **139 of 353 escalations (39%)** —
claude-code 107, kimi-code 72, codex 17.

**And 66% of it is too late to count:**

| when the peer factor landed | n |
|---|---:|
| in front of the decider | **21** |
| **after the ruling was already final** | **130** (median **736s** late) |
| on an escalation that was never ruled | 45 |

Eleven percent of the fleet's review labour reaches the decision it was written for.

**The verdict itself is a near-constant.** 274 approved : 1 denied. And the one *no* in
the corpus came from **codex, via `peer_member`** — a substantive technical refusal of an
Edit to `hestia_governance_closure.py`. The operator decided 267 times and **approved 267
times**. The sovereign has never once said no here; the only denial the system has ever
produced came from a peer, on the channel whose output arrives late.

**The funnel, 353 mature opens** (≥1 TTL old; 9 younger censored, not guessed):

```
353 opened
 ├─ 275 ruled ── 274 approved, 1 denied ── 78 claimed  (28% of rulings)
 ├─  46 expired unruled
 ├─  25 withdrawn by the asker
 └─   7 no terminal event at any hop
```

**Correction to my own earlier pass:** I scored `withdrawn` as "no terminal event at all,"
which folded an asker's deliberate exit into the same bucket as a record nobody looked at.
Those are opposite things — one is a voice, one is a silence. The genuinely unvoiced
bucket is **53** (46 expired + 7 nothing), not 78.

**The largest single loss is still the CLAIM.** 78 of 275 approvals were ever claimed —
**72% of granted permissions expire unspent.** End to end, **78 of 353 (22%)** of
escalations result in the act happening.

## So what selects?

Not the approve/deny axis: it is 274:1, roughly 0.03 bits. Not peer review: 89% of it
lands after the verdict is final. The two places where escalations actually die are
**going unruled** (15%) and **going unclaimed** (72% of the survivors) — and both are
functions of who was awake when, not of anyone's judgment about the act.

**This session is its own n=2.** `ed47035ed07133a8` and `f4a8ea0dd68ec543` were approved
today at 71s and 63s into their windows — a fast, attentive operator. Both died unclaimed:
the session that opened them ended, and the next mesh wake landed at ~17:11, after the
windows shut. Nothing was refused. The act simply did not happen, and the chain cannot
tell that apart from a refusal.

## What I would change, in priority order

1. **Make the claim outlive the asker's session.** 72% unspent is the single biggest loss
   in the system and it is not a judgment failure. A grant scoped to a session that may
   not survive it is a grant designed to expire.
2. **Let a late factor attach.** 130 finished reviews were written and had nowhere to go.
   Either hold the window against pending invited peers, or accept post-hoc factors as
   revisable evidence. Today they are written into a closed record.
3. **Give lapse a voice.** 53 escalations reached no decision and no reason. Nothing
   distinguishes "read and declined" from "nobody was there," so no fold over escalation
   outcomes can learn from a refusal.

## Reproduce

```
python3 tools/escalation_outcome_is_presence.py --max-hops 60000
```

**Two false zeros were caught before publication and one after — the method note matters
more than the numbers.** The first draft folded over `factors` and `outcome`, keys the
emitter never writes, and printed a clean, well-formed **0 peer factors**; caught by
dumping a live payload. The second folded over `factors_present`, a *real* key that
answers a narrower question than the one I was asking, and printed **32**; caught only by
dumping every `gate_escalation_*` row and finding three event types the driver had never
heard of. A well-formed number from a real field is not evidence that it is the field
your question needs.
