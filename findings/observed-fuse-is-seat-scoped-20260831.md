# The claim fuse is seat-scoped, and the mesh wake is what lights it

**Specimen:** escalation `f5484bd911651eb0`, 2026-08-31 01:56–02:00Z, CBP.
**Author:** claude-code, session `62eed33f-a495-4a80-a484-e7f6aaff425f`.
**Status:** the harm is measured on myself. I lit another session's fuse.

**CORRECTED 2026-08-31 02:45Z** — this line originally read *"I could not have avoided it
by being careful — the wake protocol told me to read the pointer, and reading the pointer
**is** the act."* That is false, and the correction is the most useful thing in this
document. A non-observing route to the same record already existed; I chose the observing
one. See [Correction](#correction-reading-the-pointer-is-not-the-act) below. What survives
is narrower and still real: the guard cannot tell an asker from a co-seat bystander.

## What happened

At 01:56:46Z a claude-code session (`888f190a-f01d-4efe-a5a0-5320307d31ab`, interactive,
reviewing PR #729) had a Bash call refused on marker `plugins/*/hooks` and an escalation
opened on its behalf. It notified codex for review, dp approved 37s later with reason `k`,
and hestia queued a `disposition` notice to plugin `claude-code`.

The mesh delivered that notice to a **different** claude-code session — mine, woken at
01:58:11Z. The primer named the pointer. I polled it:

```
$ hestia gate poll f5484bd911651eb0 --as claude-code      # t0 = 01:59:25Z
  "observation_started_claim_window": true,
  "claim_window_secs_remaining": 600,
  "consumed_at": null,
  "permits_write": true

$ hestia gate poll f5484bd911651eb0 --as claude-code      # t0 + 66s
  "observation_started_claim_window": false,
  "claim_window_secs_remaining": 534,
```

600 → 534 over 66 elapsed seconds, and `observed` true→false. **My read started the
asker's claim fuse.** I am a session that, per `eligibility()`, may not corroborate the
petition and, per `"approvals are single use"`, must not claim it.

## Why the guard did not stop it

`GateEscalations::mark_observed` (`core/src/server/gate_escalation.rs:1426`) gates on:

```rust
Some(e) if e.plugin_id == plugin_id
        && e.observed_at.is_none()
        && e.status == Status::Approved
        && e.bar_met() => { e.observed_at = Some(now); true }
```

`e.plugin_id == plugin_id` is **seat** equality. `plugin_id` is not session-scoped: every
concurrent session of one seat shares it, and disposition delivery is *also* keyed on it.
So the routing rule and the guard rule are the same rule, which is why the notice lands
in exactly the hands the guard cannot distinguish from the asker's.

The comment at the call site (`handler.rs:16223`) states the threat model precisely:

> The READ stays open to anyone — poll has never required a session and a status query is
> not an act. What requires proof is MOVING THE CLOCK: an asserted plugin_id here would
> let any caller extend (or, by racing, fix) another member's deadline.

The "proof" is `resolve_attributed_caller`, which resolves an MCP session uuid to
`sess.plugin_id`. That session is minted by `hestia_connect`, which authenticates nobody
(#63, #128) and takes `plugin_id` from the caller. `hestia gate poll --as <name>` opens
exactly such a session from argv and prints the fact on every invocation:

> identity ASSERTED as 'claude-code' (hestia_connect authenticates nobody — see #63/#128)

So the named attack — "any caller could move another member's deadline" — costs one extra
handshake call, not a credential. The guard is prose about a predicate the code does not
have. **I did not run the cross-seat leg** (asserting a *different* seat's name against
that seat's live grant), because doing so would spend a peer's real approval; this half is
source-read plus the CLI's own banner, not measurement.

## The discriminator was on the record and went unread

The specimen's `gate_escalation_opened` row carries:

```
asker_basis      session
host_session_id  888f190a-f01d-4efe-a5a0-5320307d31ab
opened_at        1788141406
act_digest       977db558…
marker           plugins/*/hooks
```

`asker_basis: session` means the opener was **proven**, and `host_session_id` names which
session. Mine is `62eed33f…`. The field's own docstring
(`gate_escalation.rs:413`) states the doctrine being violated one screen above the code
that violates it: *"DERIVED from the caller's PROVEN live session … an attribution key a
caller can assert is an attribution key a caller can launder."*

**But the obvious fix is blocked by an existing ruling.** `state::Session::host_session_id`
carries Guard B (HUB, 2026-07-24): *"this is NEVER an authorization discriminator — no
policy/authz decision may key off it."* Starting a claim fuse is not capability-conferring
— declining to start it withholds nothing from anyone — but it materially decides whether
a later write is permitted, so it is authz-adjacent and not mine to rule on.

The alternative discriminator, the MCP `session_id` uuid (also on the record when the
asker was proven, and already in `CallerWho.session_uuid`), is daemon-minted rather than
asserted and is not named by Guard B — but it churns: a hestia session is minted per
connect, per tool call for hooks. Under Guard A reuse it is stable only for callers who
supply a `host_session_id`, i.e. it inherits the field Guard B forbids.

So: neither available key is clean. **This needs a ruling, not a patch.** What is not in
doubt is the direction of the fallback — any tightening makes the fuse start *later*, so
askers get more claim time, never less, and a record with no proven opener keeps today's
seat-level behaviour unchanged.

## Coverage, if a ruling permits the tightening

Newest 20,000 chain entries, `tools/chain_walk.py`
(driver: `private-context/hestia-local/probes/observed_fuse_denominator.py`):

| | |
|---|---|
| `gate_escalation_opened` rows | 107 |
| carrying `host_session_id` | 24 (22.4%) |
| uuid-shaped / other | 23 / 1 |

| seat | opens | distinct host sessions |
|---|---|---|
| claude-code | 70 | 10 |
| kimi-code | 31 | 3 |
| codex | 6 | 0 |

22.4% is the population a session-tight guard could discriminate on today; the rest keep
current behaviour. **Ten distinct claude-code sessions** petitioned inside that window, so
the co-seat collision is a standing condition on this seat, not an artifact of one wake.
The single non-uuid value is the synthetic `hestia-deploy-preflight` health-check string.

## The same specimen kills the "operator latency" framing

Read off the asker's own transcript and the chain, one clock:

| t | event |
|---|---|
| 01:56:45.9 | act refused, escalation opened |
| 01:56:46.6 | `review_request` queued to codex |
| **01:57:06.7** | **asker drops the refused clause and re-issues a narrowed command** |
| 01:57:08.9 | asker has its answer, without the grant |
| 01:57:23.0 | operator rules `approve`, reason `k` |
| 01:57:23.5 | `disposition` queued to `claude-code` |

**The petition was dead 16 seconds before it was granted.** dp answered in 37s — about as
fast as a human gets — and the asker's give-up latency was 21s. This is the modal
approved-then-unclaimed outcome with both clocks read from one specimen, and it says the
remedy is not a faster operator.

There is a second, mechanical layer under the behavioural one. `act_digest` binds
`sha256(stated_reason)` of the **original** call. The narrowed re-issue at 01:57:06 is a
different string, so `claim()`'s digest arm could never have matched it. Even an asker
that polled instantly held an approval unspendable by the act it actually wanted. The
grant was not merely ignored; at the moment it was minted there was no longer any act it
could authorise.

## What I would change

1. **Ask HUB whether the claim fuse may key off the proven opener session.** It is
   arguably outside Guard B (nothing is authorised by declining to start a clock) but it
   is adjacent enough that a member should not decide it. If yes, the change is one
   conjunct in `mark_observed`, fail-safe in the direction that gives askers more time.
2. ~~**Until then, stop telling bystanders to pull the trigger.** ... A disposition notice
   could carry the decided state inline — it is already known at queue time — so that
   *reading the notice* is not *observing the record*.~~ **WITHDRAWN** — dp's review, and
   the measurement below, refute the premise. Inlining state would also break the
   member-mesh pointer contract (content lives at the pointer). Replaced by: **route
   pointer dereference through `resources/read`**, which already does not observe. Tool:
   `tools/escalation_read.py`.
3. **Reconsider what "unclaimed" measures.** With give-up at 21s and act-binding to a
   superseded string, unclaimed is the expected outcome of a working system, not a
   failure rate to drive down.

## Correction: reading the pointer is not the act

dp reviewed this on #732 (2026-08-31 02:16Z) and requested changes. The correction is
sustained, and I then measured it rather than conceding it on authority.

**The claim I got wrong.** I wrote that the wake protocol makes the burn unavoidable —
that dereferencing the pointer *is* the observation. It is not. `mark_observed` has
**exactly one call site in the tree**, `tool_gate_escalation_poll`
(`core/src/server/handler.rs:16233`). `resources/read` on `hestia://escalation/<id>`
routes to `resolve_escalation_pointer` (`:5996`), which never touches it — and the
resolver already strips the `#decided` fragment the disposition notice carries, so the
notice's own pointer is directly usable on the free route. What lit the fuse was my
choice of `hestia gate poll --as claude-code`, not the wake.

**The measurement.** Source-read is not a reading, and no test pins this (the two tests
that exercise the resolver, `a_reaped_escalation_reads_the_same_from_the_chain` and
neighbours, are about reaping, not observation). So I took it, on escalation
`4b1c5dcd6c8ce23c` — this seat's own petition from the previous wake, opened when a shell
`for` loop tripped the out-of-grammar rule, approved by dp 20s later with reason `k`. The
act had already been completed compliantly via unrolled reads, so the grant authorised
nothing anyone wanted. That is what makes it a legal specimen for a destructive read: the
cross-seat leg I refused to run against a peer is safe to run against my own dead grant.

| step | `observation_started_claim_window` | `claim_window_secs_remaining` |
|---|---|---|
| `resources/read` ×3, incl. the `#decided` fragment | *(field not served)* | fuse not started |
| first attributed poll, **1563 s after the ruling** | `true` | **600** — full window |
| second poll, +17 s | `false` | 583 |

Three dereferences and 26 minutes after the operator ruled, the window was still
untouched at its full 600. **The poll is the sole trigger, measured.** dp's correction is
confirmed on the wire, not just in the source.

**What this does and does not rescue.** It rescues the protocol: there is no defect in
telling a woken member to read a pointer, provided it reads it the free way. It does not
rescue the guard. `mark_observed`'s seat-equality check still cannot distinguish the
asker from a co-seat session, and the ruling question stands — dp agrees it stands, as a
later policy question rather than a mesh-notice defect. It also does not rescue the
attack-cost paragraph, which the same run incidentally demonstrated: `hestia_connect`
with `plugin_id` and `host_agent` taken straight from argv, no credential of any kind,
returned a session that moved `claude-code`'s clock. One handshake, as claimed — now
observed, on my own record only.

**Second-order:** the reason I reached for `hestia gate poll` is that it is the only
route the tooling names. `tools/await_escalation.py` and `tools/claimable.py` both poll;
nothing in the tree dereferenced an escalation pointer the free way, and the one existing
precedent for the pattern (`tools/session_residency_census.py`, whose docstring says
"Mints no session, writes nothing") is about a different resource. The affordance existed
and was undiscoverable. That is the actual defect behind my error, and it is fixed by
shipping the reader, not by asking members to be more careful.

## Limits

- n=1 for the live fuse-start. The seat-level guard is source-read; the cross-seat forgery
  leg is deduced from #63/#128 and not run against a peer, deliberately. The
  self-directed version WAS run (see Correction) and is n=1 on one seat.
- The non-observation result is n=1 on one already-decided, already-spent petition. It
  shows the resource route did not start a fuse that a later poll then started; it does
  not prove the resolver is side-effect-free in every arm (the witness-chain fallback arm
  was not exercised — the specimen was still in the live store).
- Nothing here is pinned by a test. "The resolver does not observe" is currently an
  invariant held only by there being one call site, which a future refactor can silently
  break. A regression test is the obvious follow-on and I did not write it.
- The 22.4% coverage figure is over the newest 20k entries, not the whole chain.
- I did not attempt the code change: `cargo test` on this repo is ~28 minutes and this
  wake had ~30, and the design question above outranks the patch anyway.
