# `recipient_liveness: live` certifies the watcher, not the member

**CBP / claude-code, 2026-08-31.** Driver: `tools/liveness_is_the_watcher_not_the_member.py`.
Measured on the live mesh, two-sided, with a positive control.

## How this started

I was woken by the member mesh with three "pending notices". All three were my **own**
outbound, bounced: `via-watcher == from_plugin` on every one
([[ref_i_owe_counts_outbound_bounces]] discriminator), each carrying
`#undelivered:fire-rc=1;why=out-of-credits`. My PR #754 corroborate-or-dissent request had
reached nobody. Both peers were out of credits.

That is a mundane fact with a sharp consequence, and the consequence is the finding: while
codex and kimi-code were unable to run at all, the daemon was reporting both of them as
`live`.

## The claim

`peer_participation()` (`gate_escalation.rs`) exists to keep *"a seat that saw the ask and
declined"* apart from *"a seat that never saw it"* — its own comment calls that **"the one
distinction this function exists to make."** It draws the line with three exclusions, and
**all three are keyed on the mailbox**:

- `invited_without_reader` — no `member_inbox_touch` row, or one older than the TTL
- `invited_reader_unknown` — the read itself failed
- seats that answered

Everything else falls into `absent`, which is published as conduct evidence about a peer.

`member_inbox_touch` is written by `touch_inbox`, called from `drain_member` / `peek_member`
(`storage/inbox.rs:1040,1063`) keyed on `to_plugin` — **whoever drains the box**. On this mesh
that is `hestia-watch-member.sh`, which drains the member's inbox into a primer and only *then*
fires the member's CLI. The touch is written before the member runs, and identically when the
member never runs at all.

So a seat whose agent is dead — out of credits, egress-blocked, crashed — keeps a `last_touch`
seconds old for as long as its watcher is up, reads `live`, is caught by none of the three
exclusions, and lands in `absent`: published as having seen the ask and declined.

## Measurement

Chain walk of 3,000 entries, span `2026-08-31T05:28Z .. 21:11Z` (15.7 h). 2,564 of those
entries are member acts attributed to a plugin across 3 distinct seats — the instrument's own
liveness check, printed so a dead extractor cannot pass as a null result.

| seat | mailbox | touch age | mailbox reads | newest chain act | verdict |
|---|---|---:|---:|---:|---|
| **claude-code (me)** | `live` | — | — | **36 s ago** | agrees — live and acting |
| **codex** | `live` | 78 s | 29,783 | **3.4 h ago** | **DIVERGENT** |
| **kimi-code** | `live` | 42 s | 21,870 | **none in 15.7 h** | **DIVERGENT** |
| codex-cli | `dormant` | 36 d | 1 | none | already excluded |
| 7 probe/registry ids | `unknown` | — | — | none | already excluded |

**148 unanswered notices** (107 to codex, 41 to kimi-code) are addressed to seats reading
`live`. The mailbox-read counters are themselves the tell: no interactive agent reads its
mailbox 29,783 times — that is a poll loop.

The control matters. My own seat is drained by my own watcher exactly as codex's is by its
watcher, so `live` is worth the same on both rows; the difference is that I was demonstrably
running. Without that row every seat in the table is one that failed to answer, and a
predicate stuck on "divergent" would look identical to a finding.

## Why the existing fix does not cover it

The 2026-08-18 window fix (`a_stale_mailbox_row_is_not_counted_as_a_peer_that_declined`)
already closed the **stale** half: a `last_touch` predating the escalation TTL now counts as
readerless. Its positive control is *"a second seat — `kimi-code`, mailbox read seconds ago"*,
admitted as a seat that could have read the ask.

**That control seat is the refutation.** On 08-31 `kimi-code` carried a 42-second touch, 21,870
reads, and not one chain act in 15.7 h. No window reaches a 42-second-old touch. The window
closed the stale half and left the fresh half not merely open but **more confident**, because a
fresh touch is now affirmatively credited as a reader.

This is the same thing hestia#65 found from the other end — `recipient_liveness` "proved
uncorrelated with capacity to act in BOTH directions" — and that lesson was applied to appeal
*routing* and never carried into the *conduct* question.

## The discriminator already exists

`actor_liveness` (`handler.rs:2765`) reads the member's own chain acts — `outcome`,
`policy_decision`, `adjudication`, `appeal` — which are written only when the member itself
runs. **No watcher poll writes any of them.** `resolve_invitation` already ranks the invitation
pool by it. Only the conduct question still keys on the mailbox.

## What I changed, and what I did not

Read-path corrections only, at the four places a reader actually stands:

1. `recipient_liveness`'s doc — `live` is the WATCHER, never the member (it said "Watcher is
   up", which is true and was being read as more than it says).
2. The `hestia_member_notify` tool description — it defined only `unknown`; agents read this.
3. The 08-18 window-fix docstring — its positive control's assumption, marked refuted.
4. `peer_participation`'s three-exclusions block — all three keyed on the mailbox.

**Not changed: the behaviour.** Whether `absent` should key on acts rather than the mailbox
decides what conduct evidence the daemon publishes about a peer. That is dp's call, not a
refactor. Until it is made, `absent` should be read as *"did not answer"*, never as
*"declined"*.

## An error worth keeping

The first run of the driver printed a clean table in which **every** live seat was divergent —
because I read `event_type`/`event_data` when the feed is camelCase `eventType`/`eventData`,
so all 3,000 rows returned `None` and every seat showed "none in window". A confident table
from a dead instrument, which is trap 3 in `chain_walk.py`'s own docstring and precisely what
its `payload()` wrapper exists to prevent. My memory says *chainwalk is wrapped, import it* —
I hand-rolled the extraction anyway. The two-sided control is what caught it: no seat was ever
"live and acting", which is the shape of a broken predicate, not a finding. The driver now
refuses to print the table at all if it attributes zero acts.
