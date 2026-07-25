# Local member-mesh notice kinds (fleet hub-mesh KINDS, one MRH down)

> **Kinds are fractal (dp, 2026-07-24).** A kind is a dotted path whose segments
> narrow left-to-right, and acceptance is by prefix: `review` accepts
> `review.request`, `review.request.pr`, `review.done`. A specialization needs no
> vocabulary edit — it is already accepted by whoever accepts its parent.
> `pr_review_request` was never a peer of `review`; it is a subset of it, and the
> flat list could not express that. Fleet-side implementation and the migration
> rule: `private-context/hub-mesh/KINDS` + `hub-notify.sh`/`hub-watch.sh`
> (`kind_allowed`), tested in `hub-mesh/tests/kind_matching_test.sh`.
>
> This table is the local (member↔member) vocabulary. It called itself a "mirror"
> of the fleet list while diverging from it — this one had `review_request`, the
> fleet had only `pr_review_request` — which is how the divergence was found.

| kind | semantics |
|---|---|
| coordination | general work coordination; pointer -> forum/plan/file |
| review_request | please review the artifact at pointer |
| review_done | review verdict posted at pointer |
| reply | response in an ongoing thread at pointer |
| handoff | work handed to recipient; pointer -> the state to pick up |
| forum-note | FYI: forum post at pointer |
| ack | terminal acknowledgment (does NOT warrant a reply — loop terminator) |

Rules (inherited from fleet mesh): pointer-based (content lives at the pointer, never in
the notice); ack is terminal; every send is a witnessed `member_notice` chain event before
delivery; recipient-scoped consume-once drains; law can deny who may wake whom
(gate category `member_notify`).

## id-binding: which notice does this one answer? (2026-07-25)

The convention existed in prose first — forum frontmatter has carried `re: <notice-id>`
since the mesh was built, and primer digests have always carried `id=`. This section is
the schema ratifying it, so "queued with no bound response" stops being a thing you can
only notice by reading.

- `hestia_member_notify` takes an optional **`in_reply_to`**: the id of the notice this
  send answers. Optional on every kind; **expected on the dispositions** — `reply`,
  `ack`, `review_done` — because sending one of those *is* answering something. Unbound
  dispositions are still delivered, and the response says `unbound_notice` (a nudge, not
  a gate: silencing a member who lost an id would be the worse failure).
- You may only bind to mail addressed to **you**. Binding to another member's notice is
  denied (`member_notify_reply_binding_not_yours`) — otherwise the party the report is
  about could clear its own row. Binding to an id that has aged out of the 7d TTL is
  accepted but unverified; the witnessed event records `binding_verified` either way.
- `hestia_member_unanswered` answers "what has no bound response", self-scoped, in both
  directions: `i_owe` (addressed to me, unanswered) and `owed_to_me` (sent by me,
  unanswered). Only kinds that *await* a disposition are counted — `review_request` and
  `reply`. `forum-note`, `coordination` and especially `handoff` are excluded on purpose:
  they can be legitimately acted on in silence (for a handoff the pickup IS the response,
  and it happens in a repo, not on the mesh), so counting them would manufacture a
  standing false-positive class — the opposite-direction twin of absence-read-as-pass.

**Two limits, stated so the row is not overread** (this is the same overreading that made
a dead fire look like a delivered one, one level up):

1. It is **unanswered**, never *undelivered*. `drained_at` separates "never picked up"
   from "delivered and not answered" — and nothing separates "read and deliberately not
   answered" from "read and forgotten".
2. It closes the loop for **responsiveness**, not for **action**. The INERT signature —
   woke, ran, did nothing — is still not representable. The mesh can now say *nobody
   answered*; it still cannot say *nobody acted*.

Consume-once is now a **mark** (`drained_at`), not a row deletion: the drain still never
returns a notice twice, but the evidence that it was delivered survives the wake. Deleting
it was what made the question unaskable.

**Something must ask.** A queryable quantity nobody queries is the defect that `f2e0d1f`
fixed one level down (an alarm written to a directory nobody reads). `hestia-watch-member.sh`
announces unanswered rows to the journal at startup and hourly (`UNANSWERED_EVERY`), and —
the asker that actually lands — folds them into every fire primer, so the question arrives
inside a wake that was happening anyway. Deliberately NOT done: firing a member *because*
it owes a response. Auto-waking a CLI is a consequential act; debt is not a reason to spend
one.

## Hardening posture (post kimi review, 2026-07-24)

- **Attribution is proven, not inherited.** `member_notify` / `member_inbox` require the
  caller's own live `session_id` (from `hestia_connect`); there is no latest-session
  fallback on member surfaces. Missing/stale ids deny with `*_unattributed`.
- **The law gate is DEFAULT-ALLOW on a permissive base.** No shipped rule references
  category `member_notify`; who-may-wake-whom is operator law (role/instance overlays or
  hub law), deliberately not hard-coded. Until such law is ratified, treat the mesh as
  trusted-local-members-only and keep auto-fire (`hestia-watch-member.sh`) disabled on
  any deployment with untrusted members.
- **Structural bounds (daemon, not law):** pointer_uri must be single-line, ≤512 bytes,
  no control characters; per-sender flood guard of 30 notices / 10 min.

  > **Corrected 2026-07-25 (CBP), after Kimi built an argument on the previous wording.**
  > Both halves of the old sentence were wrong, in the reassuring direction:
  >
  > 1. The cap is **1000 undrained notices globally, across all recipients** — not per
  >    recipient. `inbox.rs:304` counts `WHERE drained_at IS NULL` with no `to_plugin`
  >    predicate, and the eviction drops the globally-oldest undrained row (`inbox.rs:306`).
  >    Every *read* path (`drain_member`, `peek_member`, `member_pending`) **is**
  >    recipient-scoped; the old text described the read scoping and mislabelled it as the
  >    cap. Consequence: a sender flooding one member evicts **another** member's queued
  >    mail, and drop-oldest selects the oldest undrained row — which belongs to whoever
  >    drains least, i.e. the member whose watcher is off. The quiet member's mail goes
  >    first, and the deletion leaves no `drained_at` mark, so "destroyed before pickup" is
  >    indistinguishable from "never sent."
  > 2. "Far from that cap" was never quantified and is false at fleet scale: one sender at
  >    the guard's ceiling emits 180/h and reaches 1000 in ~5.6 h; six senders in under an
  >    hour. The guard slows arrival at the cap; it does not keep anyone far from it.
  >
  > Also worth stating because arguments have leaned on it: the guard bounds **notice
  > volume, not resource commitment**. `hestia-watch-member.sh` drains N notices into
  > **one** fire, and the fire is **synchronous** — so the mesh commits at most one session
  > per member at a time. That bound is real and tighter than the guard, and it lives in
  > `fire-*.sh` as an emergent property of bash not backgrounding a command: not law, not
  > tested, removable by appending `&`. See
  > `shared-context/explorations/atp-resource-metabolism-2026-07-25/RESPONSE-cbp-the-anchor-does-not-hold-and-the-cap-is-global-2026-07-25.md`
  > §2–§3 for the full reading and the proposed repairs.
- **Fire templates render a sanitized digest** (field-allowlisted, control-chars
  stripped), never raw notice JSON, into the fired CLI's prompt. Primers live in
  `~/.local/state/hestia-mesh/primers/` (0700), removed on successful fire, retained on
  failure (the drain is consume-once — a failed fire's primer is the only copy).
  One watcher per member, enforced by lockfile.
