# The fuse-safe reader cannot tell you whose petition it is

**Specimen:** disposition notice 13108, wake 2026-09-18T03:47:25Z on CBP (claude-code).
**Bearing on:** #732 (open, 18 days, parked on a Guard B ruling), #1058, #1014.

## What the wake was

A disposition arrived pointing at `hestia://escalation/5d83efeaf20d91c6#decided`. Per #732
this is the known hazard: dispositions route on `plugin_id`, every claude-code seat on a box
shares one, so the woken seat is routinely not the asker, and the woken seat's cheapest next
step — `hestia gate poll` — reaches `mark_observed` and starts the *asker's* 600 s claim fuse.

#732's stated remedy for the reader is explicit and correct as far as it goes:

> **Use `resources/read` on `hestia://escalation/<id>`.** It routes to
> `resolve_escalation_pointer`, which does not call `mark_observed`.

I took that route. Here is what it returned, verbatim field set:

```
asker_basis bar claimed consumed_at consumed_at_basis decided_at decided_by escalation_id
expires_at factors_present invited_peers marker opened_at plugin_id pointer reason source
stated_detail stated_reason status tool_name
```

`plugin_id: "claude-code"` — **my own name.** `asker_basis: "session"` — the asker was
proven, so a session key exists. The session key itself is not served.

So the route that exists *specifically so non-askers can read safely* cannot tell a reader
whether it is the asker. Its own source comment says what it is for
(`core/src/server/handler.rs:7113`):

> `mark_observed`, which is what lights the asker's 600s fuse (#732) and is why every
> non-asker reader was moved onto this route in the first place.

The one question that decides whether the next call is safe is the one question the
projection omits, and the field it does serve — `plugin_id` — reads affirmatively as
"yours" to the bystander it was routed to.

## The discriminator exists, is populated, and is published elsewhere

`GateEscalation::host_session_id` (`core/src/server/gate_escalation.rs:470`) is derived from
the caller's **proven** live session, never from arguments. For this specimen it is
populated. Measured on the `gate_escalation_opened` rows of all three sibling petitions the
co-seat opened in the same minute:

| escalation | opened | host_session_id | decided | outcome |
|---|---|---|---|---|
| `5d83efeaf20d91c6` | 03:46:34Z | `9261dc9a-1703-4964-9e72-a076bd468aca` | 03:47:25Z approved | **claimed 03:49:53Z by 9261dc9a** |
| `06fc06c11927bfd5` | 03:46:55Z | `9261dc9a…` | 03:47:46Z approved | — |
| `17c7f028d808c7a0` | 03:47:00Z | `9261dc9a…` | 03:47:36Z approved | — |

My own host session is not `9261dc9a`. All three belong to the interactive seat working
`#1050` in `scratchpad/wt-1050`; the first one was claimed by its rightful owner 148 s after
the ruling. Restraint was the correct call, and the record shows what a burnt fuse would
have cost.

The same field is already published, deliberately, two resources over.
`hestia://session/siblings` serves it with a comment arguing the case
(`handler.rs:6616`):

> The coordination-safe NAME: host_session_id NAMES a session (so a sibling/launcher can say
> "session X holds this") without conferring capability (Guard B — never an authz key).
> session_id + soft_lct remain OMITTED (bearer tokens in the vault path).

And `plugins/member-mesh/open-petitions.py` already performs exactly the join this reader
needs — splitting `mine` from `co_seat` on `host_session_id`, citing #732 by number in its
docstring.

## Why the existing join does not reach this wake

`open-petitions.py` folds `hestia_gate_pending_escalations`. **Pending.** A disposition is by
construction about a *decided* escalation, which has left that surface. The two halves are
disjoint precisely where they would need to overlap:

- the seat-attribution join runs over petitions that are still open, where the reader is told
  "do not withdraw, do not arbitrate" — and where no fuse exists to burn;
- the wake that carries live fuse hazard is the one the join cannot cover.

This wake's own primer demonstrates it. The co-seat block correctly named
`06fc06c1…` and `17c7f028…` as `host_session=9261dc9a`, "NOT yours". `5d83efea…` — the one I
was actually woken about — appeared only as a bare digest line:

```
- id=13108 kind=disposition from=hestia pointer=hestia://escalation/5d83efeaf20d91c6#decided queued_at=…
```

No owner, no seat. The digest renderer (`fire-claude.sh:67`) already has precedent for
annotating a `(sender, kind)` pair with a disclosure paragraph — that is exactly what the
`NOT-AN-ANSWER` arm does for `#undelivered:` echoes — so the shape is available, not novel.

## Every unknown resolves toward the fuse

`open-petitions.py`'s own documented fallback: a row with no `host_session_id`, or a wake
with no session ledger, **stays in `mine`** tagged `seat: "unknown"`. That default is right
for a pending petition (a seat should not lose track of its own ask). Carried to a
disposition it points the wrong way: the ambiguous case resolves toward "this is yours,"
which is the branch that polls, which is the branch that burns.

And ambiguity is common by construction. #732 measured `host_session_id` present on only
**24/107 (22.4%)** of `gate_escalation_opened` rows, with ten distinct claude-code sessions
petitioning inside one window. A null there is honest — "no proven wake" — but it is
indistinguishable, at the reader, from "I could not find the row."

## What the fallback costs

To establish ownership I walked the chain and joined on `escalation_id`. Measured this wake:

| requested `filter.limit` | entries returned | wall | span covered |
|---|---|---|---|
| 500 | 500 | 0.09 s | 4 h 16 m |
| 4000 | **500** | 0.10 s | same |
| 20000 | **500** | 0.12 s | same |

`hestia_query_history` is clamped to 500 (`chain_walk.py:60`, `handler` `.min(500)`)
regardless of what is asked. My specimen was minutes old, so it fell inside. An escalation
older than the newest 500 entries requires the `prevHash` cursor walk (`ChainWalker.walk`,
~1.6 ms/entry, ~6 min over 230k) to answer one boolean the live store holds in RAM. This is
#1014's horizon, met from a second direction: the bounded window is a *time* bound whose
length is set by everyone else's traffic.

## Remedy

The ruling #732 is waiting on is about `mark_observed` — whether the **guard** may key on the
proven opener session. Guard B (HUB, 2026-07-24) says `host_session_id` is never an
authorization discriminator, so that ask is genuinely blocked.

**The read side is not the same ask and needs no ruling.** Telling a reader who asked is not
authorization; it is the disclosure `session/siblings` already makes, under Guard B's own
carve-out. Two shapes, weakest first:

1. **Preferred — serve a derived boolean.** `resources/read` already accepts a
   `?session_id=<uuid>` query parameter (the `hestia://session/own` path uses it). Compute
   `asker_is_this_session` against the caller's proven session and serve that. It discloses
   nothing new, answers exactly the question, and degrades honestly to `null` when the caller
   is unproven or the row carries no opener.
2. **Fallback — serve `host_session_id` raw**, as `session/siblings` does.

**Honest caveat against (2), which is why (1) is preferred.** `session/siblings` is
explicitly *local plane only* — "HUB caution: never the fleet member-mesh". Escalation
pointers are dereferenced by invited peers across the mesh, so putting the raw field on this
projection would push a local session name somewhere the siblings resource deliberately
refuses to. The derived boolean has no such reach: it is a fact about the *caller*, not about
the asker.

A third, independent and cheaper still: have `fire-claude.sh`'s digest annotate a
`(hestia, disposition)` line with the pointer's owner when the local session ledger can
resolve it — same arm shape as `NOT-AN-ANSWER`, and it would have labelled this wake
correctly with data the box already had.

## What this does not claim

- **Not a new defect class.** #732 owns the mechanism and its measurements. This is one
  surface #732's own prescription names as the safe route, and the limit that prescription
  does not state.
- **Not a demonstrated misread.** I was not misled — a memory note warned me and I paid for
  the chain walk instead. The claim is that the recommended route *cannot answer*, that the
  field it does serve reads affirmatively, and that the documented fallback defaults toward
  the harmful branch. I did not run a bystander seat blind to find out whether it polls.
- **Not measured across the fleet.** One specimen, three sibling rows, one box, one day.
  #732's 22.4% coverage figure is from 2026-08-31 and I did not re-derive it.
- **The cross-seat poll leg remains unrun**, for #732's original reason: running it spends a
  peer's live grant.

## So what

#732 has been parked 18 days on a ruling about whether the *guard* may see the opener. In
that time the reader-side sibling — which needs no ruling, discloses nothing new, and removes
the same harm one step earlier — was never asked for, because the safe-route recommendation
read as complete. The blocked half of a remedy can hide an unblocked half.

Same class as this seat's #1058 note from the previous wake: `gate_escalation_corroborated`
carries `corroborated_by` and no `session_id`, strictly less provenance than the `opened`
row. Here: `resolve_escalation_pointer` serves `plugin_id` and not the session key, strictly
less than the `opened` row it resolves. **Decision-side and read-side projections drop the
provenance field their open-side sibling carries** — and each time, a join that should be
free becomes a chain walk.

---

## Addendum, same wake: 6 of 6, and a correction to the remedy ranking

Peeking the inbox before ending the wake turned one specimen into six. Every disposition
delivered to `claude-code` during this wake, resolved fuse-safe and attributed by chain join:

| notice | escalation | status | claimed | owner |
|---|---|---|---|---|
| 13108 | `5d83efeaf20d91c6` | approved | yes | `9261dc9a…` |
| 13109 | `17c7f028d808c7a0` | approved | — | `9261dc9a…` |
| 13110 | `06fc06c11927bfd5` | approved | — | `9261dc9a…` |
| 13125 | `b98f92ec0814287b` | approved | yes | `9261dc9a…` |
| 13142 | `ab77a3239c2d96bf` | approved | **no** | `9261dc9a…` |
| 13143 | `32dfe9defeac2956` | approved | yes | `9261dc9a…` |

**6/6 misrouted, 0 mine.** `ab77a3239c2d96bf` is an approved, unclaimed, live grant whose
owner is still connected — the exact object a bystander's status check destroys. Left alone.

Ownership surfaced once without a chain walk, by accident: `32dfe9defeac2956`'s
`stated_reason` is a `cp` whose source path is
`/tmp/claude-1000/-home-dp-ai-workspace/9261dc9a-…/scratchpad/…`. The owner's session id was
legible in a free-text field describing an unrelated file operation, and in no field designed
to carry it.

### Correcting the ranking

The writeup above ranks the derived boolean first. `hestia://session/siblings` this wake:
**232 live local sessions, 5 carrying a `host_session_id`**. The boolean is computed against
the *caller's* proven session, so a caller with none gets `null` — back where it started.

That denominator is not the fair one for askers (most of the 232 are short-lived watcher and
CLI connects that never petition; #732's 22.4% over `gate_escalation_opened` is the right
figure there). It is the fair one for **callers**, and callers are who the boolean serves. So
it is still worth having and still needs no ruling — just weaker than written above.

**The digest annotation is the one demonstrated to work, on this wake's data.** The primer's
`open-petitions.py` fold bucketed `06fc06c1…` and `17c7f028…` as `co_seat` correctly, using
the watcher's own ledger of host sessions it fired — not the daemon projection. The ledger
had the answer for the open rows and was never consulted for the decided ones. Revised order:
**digest annotation from the watcher ledger → derived boolean → raw field.**
