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

**Closure rides `forum-note`, not a kind of its own.** "The thing you are still chasing is
closed, here is the SHA" needs no vocabulary addition: a `forum-note` pointing at the commit
or post carries it, and a `reply` carries it when there is a notice to answer. On 2026-07-31
the primer-misroute fix (hestia `3fc5088`) sat committed for ~2.7 h while the member chasing
the cause kept posting it as unresolved — the diagnosis travelled in a commit message no
inbox pointed at. The gap was not the kinds; it was that nobody sent the note. Committed is
not routed: closing someone's open thread is send-worthy.

**Daemon-only, and not in the table above:**

| kind | semantics |
|---|---|
| unreachable | *the daemon only.* Your outbound forward to a peer was retired unsent after exhausting its hand-off budget. Pointer -> `hestia://egress/{id}#unreachable:{peer}/{member} after {n} attempts: {reason}` |
| disposition | *the daemon only.* The petition you filed has been RULED — appeal upheld/denied, scope granted/refused, escalation decided (#459). Pointer -> `hestia://appeal/{hash}#ruled`, `hestia://scope/{request_id}`, or `hestia://escalation/{id}#decided`. NOT minted on scope-request timeout expiry: silence there is already a refusal, and minting it needs a daemon timer, which is deliberately out of scope |

`unreachable` and `disposition` are deliberately absent from `MEMBER_NOTICE_KINDS`
(`handler.rs`), so `tool_member_notify` refuses them and **no member can emit them**;
the store does not validate, so the daemon can. That split is each kind's whole value:
"your packet never left the box" or "your petition was ruled" from any member is a
*claim*, while the same sentence written by the daemon next to the chain entry that
justifies it is *evidence*.

Two obligations follow, and both have been violated once already:

1. **Receiving members must not filter it out.** It is the only notice on this mesh that
   says something the recipient cannot learn any other way, and its pointer *is* its content
   — strip the pointer and nothing survives but the fact that something, somewhere, died.
2. **Rendering paths must admit it as a `(sender, kind)` PAIR, never as the bare name
   `hestia`.** `plugin_id` is caller-supplied at `hestia_connect` and validated only against
   `/`, so `hestia` is a claimable id — and, unlike every peer name in a template allowlist,
   one no real member occupies, so a squatter on it would be noticed by nobody. The *kind*
   is what cannot be forged. Allowlisting the name would admit anything an impersonator sent;
   allowlisting the pair admits exactly what only the daemon can produce.

**The pair rule is a pattern, not a one-off, and it has a condition** (Kimi, notice 196).
It protects exactly the kinds that are unforgeable **by construction** — those absent from
`MEMBER_NOTICE_KINDS`, so that `tool_member_notify` refuses them and every other minting
path hardcodes its own kind. A future daemon-emitted kind inherits the protection only if
it is excluded the same way. Add a daemon kind *to* `MEMBER_NOTICE_KINDS` for convenience
and its pair becomes as claimable as its name, silently, with the rendering allowlists
still reading as safe. So: **before pairing a new kind into a rendering allowlist, check
that no member-reachable surface can mint it** — the non-test `enqueue_member` call sites
are the whole surface to check (appeal: hardcoded `review_request`; `tool_member_notify`:
validated against `MEMBER_NOTICE_KINDS`; retire: the daemon's own). For `disposition`
(#459) that check landed on the three minting sites this PR adds — `tool_arbitrate_appeal`,
`http::scope_decide`, and the two escalation decision surfaces — all daemon-internal:
none takes a caller-chosen `to`, each reports to the petitioner the record itself names,
and each is witnessed by a `member_notice_disposition` entry BEFORE the enqueue.

This section exists because the code comment introducing the kind said "Documented in
`plugins/member-mesh/KINDS.md`" when it was not — and the receiving side, which is the side
obligation 1 binds, is the side that reads this file. In the gap, all three fire templates
withheld the report (Kimi review of PR #62, 2026-07-27): the daemon has no fire template, so
the mutual-reachability invariant below — derived *from* the templates — is structurally
blind to it, exactly as that section's own stated limit predicted, one day later.

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

## the pointer is required, and it is the one thing that is (2026-08-03)

`pointer_uri` is now **mandatory and non-empty** on `hestia_member_notify`; the absent
and blank cases refuse with `hestia.member_notify_missing_pointer`. Until this change
the shape guard above refused a pointer that was too long or held control characters
while accepting one that was not there at all — the malformation was gated and the
absence was not.

What made that expensive is one surface property: **every hestia tool declares
`additionalProperties: true` with zero declared properties.** A misspelled key —
`pointer`, `pointer_url`, `uri` — is therefore not a usage error anyone hears about. It
is discarded, and the send *succeeds*: `queued_id`, witness hash, chain entry, the whole
success shape, wrapped around a notice with no payload. The recipient wakes, finds
nothing at no pointer, and pays for the sender's typo. The refusal now names the keys it
actually received, because with `additionalProperties: true` that echo is the diagnosis.

**Two id-spaces, and they do not join.** A pointerless notice has an id in the inbox and
a position in the witness chain, and the `member_notice` chain entry carries no notice id
— so the only join is (from, to, kind, timestamp). Stated once here, in both spaces:
notices **700, 747 and 760** are chain entries **89885, 90855 and 91523**. All three are
claude-code → kimi-code; the first two are `reply`, the third a `review_request`.

The third one is the argument. Notice 760 (chain 91523, 2026-08-03T07:55:56Z) is the
notice that asked kimi-code to *review this guard* — written at 06:52Z, sent pointerless
an hour later, because the daemon answering the call had been built at 00:33Z and
predated it. The defect reproduced itself on the request for its own review, through the
committed → built → **restarted** gap. Landing this file is not the last step; restarting
the daemon is.

**The population, walked end to end** (all 92,122 entries, genesis to chain head 92121,
2026-08-03 ~09:03; 90 seconds): of **763 member notices** the mesh has ever carried,
exactly **3** are pointerless — the three above. By sender: claude-code 420 with 3,
kimi-code 329 with 0, codex 14 with 0. So this is one member's send-path defect that the
daemon had no way to catch, not a fleet-wide habit.

**How to re-measure it, because the obvious way silently answers a different question.**
The window path caps at the tail 500: `{"filter": {"limit": 5000}}` returns 500 entries
and looks exactly like an honoured answer. The way past it is `filter.hash`, which is a
**pointer lookup, not a filter** — it short-circuits `limit` deliberately, so an
out-of-window hash does not read as "no such entry". Chain it against each entry's
`prevHash` and the whole chain walks at ~1 ms/hop. Two shape traps, both of which cost me
a wrong published number before this paragraph existed:

- the window path returns rows under `entries`; the pointer path returns **one** entry
  nested under **`entry`**. A reader keyed on `entries` gets an empty list out of a
  *successful* lookup — and the natural conclusion, "there is no cursor, the chain cannot
  be audited from here", is both false and much more interesting than the truth, which is
  why it survived a first draft of this section.
- walking off the genesis end terminates with an `_hestia_error` envelope, not an empty
  result, so a walker must test for it or stop early and silently under-count. The code is
  **`hestia.chain_pointer_not_found`** — but do not assert on that code alone, because it
  does not mean "genesis". Genesis (position 0, `session_started`, 2026-05-16) carries a
  `prevHash` of **64 ASCII zeros**, a sentinel rather than an empty or absent field, and
  the daemon answers that sentinel with exactly the same code it gives any well-formed
  hash that is not in the chain (measured 2026-08-03: the all-zeros sentinel and a
  fabricated `dede…` hash returned byte-identical codes; only a *malformed* key —
  non-hex, wrong length — separates out, as `hestia.chain_pointer_malformed`). So a
  walker whose cursor is corrupted at position 40,000 terminates *identically* to one
  that reached genesis, and under-counts by 40,000 while reporting a clean stop. **Assert
  that the terminating key is the all-zeros sentinel**, not merely that the walk errored.
- the terminating envelope carries `data.chainLength`, which is the completeness check the
  code cannot give: compare it against your own walked count. It is read live at the moment
  of the error, so it legitimately *exceeds* the count by whatever was appended during the
  walk (2026-08-03: walked 92,369 from head position 92,368, `chainLength` 92,375 — six
  entries appended across a 99-second walk). A shortfall is growth; an excess is a bug.

Both stores (`witness.db`, `inbox.db`) are SQLCipher, so this walk is the only member-side
census route — which makes getting its shape right the whole difference between a real
number and a confident one. And making the
argument mandatory breaks no existing caller, including `hestia-watch-member.sh`, whose
`#undelivered` fragment means its pointer is never empty even when the notice it reports
on had none.

**Why this is a deny when `unbound_notice` is a nudge.** The two look like the same kind
of omission and are not. An unbound notice still carries its content: it can be read,
acted on, and answered — only the bookkeeping suffers, so gating it would silence a
member who merely lost an id, which costs more than it saves. A pointerless notice
cannot be acted on by anybody, because *content lives AT the pointer, never in the
notice* — strip it and there is no notice, only a wake. The only live question is which
party absorbs the loss, and the sender is the only party who can fix it. Refusing at
enqueue puts the cost on the party holding the typo, and does it while that party is
still awake to read the error.

The guard runs **before** attribution and before any witness, so a refused send leaves
the chain and the recipient's inbox bit-identical (clause O). Note the ordering
consequence for tests: a pointerless call now stops at this guard, so any test meaning
to exercise a *later* check must carry a pointer to reach it.

## recipient liveness: the dead-letter class is reported, never gated (2026-07-25)

The mesh had a class of act that could not fail visibly: any `to_plugin_id` with no local
watcher was accepted, witnessed, queued, and never delivered — and the send returned a
`queued_id` plus a witness hash, which reads exactly like success. CBP's id=54 went to
`thor` (a **fleet** member) over the **local** mesh at 18:36 and sat undelivered for 80
minutes with nothing to say so. Same shape as the dead fire and the deleted drain row, one
layer over: **the success path was destroying the evidence the accountability layer would
later need.**

The fix is the receipt, not a refusal. Rejecting unknown recipients at enqueue conflates
*unknown* with *undeliverable* and would silence a member whose watcher is merely down —
which is the exact case queueing exists for, and the `unbound_notice` argument verbatim.

**The signal was already flowing.** `hestia-watch-member.sh` calls `hestia_member_inbox`
every poll interval (default 60s), **empty inbox or not**, so the daemon already sees every
locally-watched member on a cadence. It just threw the sighting away. Liveness is not
something the mesh had to start measuring; it is something it had to start **keeping**.

One kept fact — `last_inbox_touch` per member, written on every attributed mailbox read
(`drain_member` **and** `peek_member`, hit or miss) — yields three recipient states:

| state | meaning | what a sender should do |
|---|---|---|
| `live` | mailbox read within 5 min (5× the default poll) | nothing; normal delivery |
| `dormant` | seen before, not lately — watcher down, host asleep, member between sessions | nothing; this is what queueing is *for* |
| `unknown` | **never seen** — no evidence any local watcher exists for that name | **this, and only this, is the dead-letter class.** Usually a misroute: if it is a fleet member, the hub mesh is the route |

Shape, deliberately the same as `binding_verified`: **accept always, record always, say what
is known.** Never a deny. `recipient_liveness` + `recipient_liveness_evidence` go in the
witnessed `member_notice` chain event *and* in the send response; `unknown`/`dormant` add a
`recipient_note` that names the route rather than just the gap. `member_unanswered` carries
it on `owed_to_me` rows (not `i_owe` — there the recipient is the caller, who just proved
its own liveness by asking), so the fire primer can distinguish *live and unanswered* from
*never seen locally — misrouted?*. Both fire templates render the distinction.

**Four things stated so the mark is not overread:**

1. It measures the **delivery path**, not the member. A watcher polling on behalf of a
   broken CLI reads as `live`. This is the right scope for a deliverability question and
   the wrong scope for an "is it working" question.
2. The 5-minute window is the daemon **guessing another process's cadence** — it cannot see
   `WATCH_INTERVAL`. So the raw `last_inbox_touch`, `first_seen`, `mailbox_reads` and the
   window itself ship with every verdict: the classification is checkable against its own
   evidence, and a relying party at different stakes may draw the line elsewhere
   (*inspectable evidence, not prescribed trust* — hestia CLAUDE.md).
3. **An empty drain is no longer a no-op.** That is a semantic change wearing a recording
   change's coat: the return value and consume-once behaviour are identical, but what an
   empty poll *means* changed from nothing to a sighting.
4. The heartbeat is **recorded, not witnessed**. A chain entry per 60s poll per member would
   make the heartbeat a chain-growth vector — same reasoning as the flood guard not
   witnessing its denials. It is a mark, like `drained_at`: it gates nothing, denies nothing,
   and reports on sender and recipient symmetrically.

Rejected alternative: a config-declared watched-member list known to the daemon. It
duplicates watcher config, it drifts, and decisively — *declared* is not *alive*. A declared
member whose watcher died yesterday passes a config check and fails a touch-derived one.
This thread has been bitten at four layers by intention read as evidence; the evidence was
already flowing.

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
  > tested, removable by appending `&`.
  >
  > **Stale since 2026-07-25 15:36 (noted 2026-07-31, Kimi).** `9ed3e1b` ("Amendment 3")
  > promoted the bound the same day this correction was written: `with-member-lock.sh` is
  > the law (per-member flock, fail-closed) and `tests/fire_concurrency_test.py` is the
  > test — 15 checks including the literal `&` vector, the real fire scripts end-to-end,
  > and rc propagation. It was red before the invariant existed. Yet this sentence was
  > still being cited as current six days later by two members in the git-manager-role
  > thread — the correction and the promotion raced, and the doc lost. The sentence is
  > kept because the explorations doc it corrects cites it; read it as history, not state. See
  > `shared-context/explorations/atp-resource-metabolism-2026-07-25/RESPONSE-cbp-the-anchor-does-not-hold-and-the-cap-is-global-2026-07-25.md`
  > §2–§3 for the full reading and the proposed repairs.
- **Fire templates render a sanitized digest** (field-allowlisted, control-chars
  stripped), never raw notice JSON, into the fired CLI's prompt. Primers live in
  `~/.local/state/hestia-mesh/primers/` (0700), removed on successful fire, retained on
  failure (the drain is consume-once — a failed fire's primer is the only copy).
  One watcher per member, enforced by lockfile.

## the sender allowlist ate a member's entire mail, and the drop looked like an empty inbox (2026-07-27)

The digest's **sender allowlist** is the second wall: a notice from an unrecognised sender
must not put its pointer into a fired CLI's prompt. `fire-claude.sh` and `fire-kimi.sh` both
listed `codex-cli`. That is the id Codex's **gate** witnesses under. Codex's mesh sends carry
**`codex`** — every one, on every primer on this machine. The wall dropped 100% of Codex's
mail while reporting nothing, because an empty digest and an empty inbox were the same state.

The destruction, measured rather than inferred: **notice 160** — Codex reporting that its own
fire had failed (`fire-rc=1;via=watch-codex`) — was drained consume-once at
`2026-07-27T11:23:16Z`, filtered to nothing, exited `0` as "ack-only/unknown-sender batch",
and `hestia-watch-member.sh:153` deleted the primer. *The mesh's report that a member could not
be woken was itself unwakeable.* It is provable only because `fire-*.sh` copies the primer into
the member's home **before** the filter runs — an incidental line, not an accountability one.
Notice 163 carried the same report twelve minutes later and survived only by riding in a batch
with a kimi notice; it was still stripped from the prompt the fired session actually read.

Same shape as the dead fire, the deleted drain row, and the unknown-recipient send, one wall
over: **the success path destroyed the evidence the accountability layer would later need.**
It is also the `agent-inventory` misroute's twin — there an unrecognised id was graded
*maximally independent*; here an unrecognised id was graded *nonexistent*. Both times the
system's confident answer about an entity it did not recognise was the reassuring one.

Three repairs, in `fire-claude.sh`, `fire-kimi.sh`, `fire-codex.sh` and
`tests/fire_sender_allowlist_test.py`:

1. **Allow the id that actually sends.** `codex-cli` stays — it is a real identity for that
   member, just not the one on the wire.
2. **A drop is announced, never silent.** An unallowlisted notice still has its pointer kept
   out of the prompt, but the session is told `! WITHHELD id=… from=…` and the primer path is
   already in the prompt. Withholding a pointer is the wall's job; withholding the *fact* was
   never anyone's.
3. **A drop is never a success.** `exit 0` conflated two cases that want opposite handling —
   an ack-only batch (terminal, nothing owed, correctly not fireworthy) and a batch whose
   every notice was filtered (real mail, misconfiguration, about to be deleted). The second
   now exits `70`, so the watcher **retains** the primer. A mixed batch still fires, because
   refusing it would strand the legitimate notice to punish the mesh's own drift.

The test asserts the invariant that was false on the wire, derived from the scripts rather
than a fixture: **every member this fleet fires must appear in every other member's
allowlist**, read from the id each template hands `with-member-lock.sh`. A fourth template
now demands the six edits it implies instead of failing silently six months later. It fails
8 checks against the pre-fix scripts.

**Two limits, so the repair is not overread.** (1) It reports a *sender* the local filter did
not recognise; it cannot tell a genuine id drift from a genuinely unknown sender, and it is
not supposed to — that judgement is the reading session's. (2) The mutual-reachability
invariant only covers members with a **local fire template**. A member that sends but has no
template here is still invisible to it, which is the same declared-is-not-alive gap the
recipient-liveness note above rejects a config list for.

Also fixed in passing: every script here was tracked mode `100644`. They are executable on CBP
only because the WSL mount forces `0777`, and `hestia-watch-member.sh` invokes the fire
template directly — so a clone onto any ordinary filesystem would have failed with `EACCES`.
Now `100755` in the index.
