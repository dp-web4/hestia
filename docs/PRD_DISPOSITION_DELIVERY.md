# PRD: the disposition reaches the asker the moment it is made

Status: DRAFT for ratification. Owner: hestia. Tracker: #825 (lifecycle state machine); this PRD is its delivery leg. Absorbs #772, #732, #774 (claim-side), #795.

## 0. Directive (dp, 2026-09-02, verbatim)

"regardless of window, the mechanism is supposed to notify the asker of the disposition the moment it takes place. what do we need to make it happen?"

And the ratified clause it restates, `PRD_GOVERNANCE` section 8: "A ruling that is not bound to the appellant's notice has not been issued, it has been filed. The verdict exists and the asker never learns it." "The originating chain is the delivery address."

## 1. Measured

One seat, one afternoon (CBP, claude-code interactive, 2026-09-02):

| escalation | approved | asker learned how | outcome |
|---|---|---|---|
| `d46aaea3`, `32f73af7` | operator, out of band | operator typed "all approved" into the session | window already at 0 s on re-issue; two fresh petitions minted |
| `11ec3f4d` | operator | asker polled by hand: 47 s remaining | re-issue landed after expiry; third petition minted |
| `6e524b9c`, `4f58d724` | operator | poll showed 570 s | claimed |

Every delivery that worked was a human relaying a decision to a session by hand. The daemon's own doc records the same on 2026-08-27: "the only delivery channel that worked, four times running, was dp saying 'approved' out loud" (`gate_escalation.rs`, `observed_at`). `gate_cli.rs` (`poll`): "approved at 08:16:30, claimed at 08:21:16, 286 seconds after the grant and 11 seconds after a human typed the word 'approved'." Base rates from #719 and #795: 76 of 116 approvals never claimed; 35 of 39 burned.

What exists, read from the tree:

- At decide time the daemon mutates the row (`EscalationStore::decide`), appends `gate_escalation_decided` to the chain, and mints a return edge: `ensure_disposition` inserts a `member_notices` row, `from_plugin='hestia'`, `kind='disposition'`, addressed by **`plugin_id`** (`handler.rs`, `inbox.rs`). A reconcile worker re-derives it from the chain every 300 s.
- That row is **pull-only**. The puller is `hestia-watch-member.sh`: a consume-once drain every 60 s that fires a fresh `claude -p`. The fired session is not the asker; it cannot claim; its poll starts the asker's fuse (#732, `mark_observed` keyed on `plugin_id`).
- A live interactive session reads mail at SessionStart only (`session-mesh-inbox.sh`, no matcher). No PreToolUse, PostToolUse, or UserPromptSubmit hook reads mail or dispositions. The daemon says so at the refusal site: "TELL THE ASKER HOW TO WAIT, because the notice does not reach a live seat" (`handler.rs`, `how_to_wait`).
- The asker's identity is on the row at three strengths and unused for addressing: `plugin_id` (asserted), `session_id` (proven MCP session), `host_session_id` (per-wake key), with `asker_basis` saying which is proven.
- The claim window is `APPROVAL_CLAIM_WINDOW_SECS = 600` from `observed_at.or(decided_at)`; the refusal prints `retry_within_secs = 4200`, a supremum presented as a point (`claim_horizon_is_never_rendered.rs`: "an over-report of the claim window 7x").
- On the claude seat the carrier for in-session delivery already exists: `law_inject.py` emits `hookSpecificOutput.additionalContext` JSON, pinned to SessionStart. Claude Code accepts that field on PreToolUse, PostToolUse and UserPromptSubmit; nothing else pushes into a running session between its own events.

## 2. Model

An escalation has an **asker**: the (member, session, act) that was refused. The seat is where the asker lives, not who it is.

Three states, and they are three different objects. **Filed**: the ruling is on the chain. **Available**: a durable, addressed obligation exists on a lane the asker's runtime can read without asking. **Received**: the asker's own runtime has acknowledged it, and that acknowledgement is evidence. Only the third is delivery, and only the third may start a clock. The distinction is not pedantry: #851 measured a reader that made a ruling available and then destroyed it, rendering it to nobody. The row existed; delivery did not happen.

Three asker states, three ports, one content:

| asker state | port | latency bound |
|---|---|---|
| live, mid-turn | the seat's own hook stream: the next PreToolUse / PostToolUse event injects context | the asker's next tool call |
| live, idle at the prompt | UserPromptSubmit injects context; SessionStart on resume or compact | the asker's next prompt |
| gone (session lease dead) | the mesh wake, addressed to the member, carrying claim state, told it is a relay and must not poll | the watcher's poll interval |

The content is the gate's, composed once by the daemon. The hook renders it on the seat's channel and composes nothing (SHIM_LEDGER class: refusal-channel).

## 3. Requirements

**R1. Address the asker.** The disposition row carries `for_session` = the proven `session_id` / `host_session_id` when `asker_basis` is `Session`, and the daemon writes the same disposition to a per-session lane the seat can read without a round trip: `$HESTIA_HOME/dispositions/<host_session_id>.jsonl`, append-only, one line per decision, owned by the daemon. `plugin_id` addressing stays for the gone-asker case.

**R2. Push at decide time.** `decide`, `expire`, `withdraw` and `claim` each append to the lane in the same transaction that appends the chain entry; the chain entry is finality (#480) and the lane line carries its hash. No worker, no interval, no polling by the asker.

**R3. One content, absolute, and no field that impersonates a deadline it cannot yet know.** A lane line carries `escalation_id`, `decision`, `decided_at`, `decided_by`, `ruling_hash`, `claimable`, `consumed_at`, `expires_at`, `act_digest`, the bounded `attempted` summary, and the one sentence saying what may be done. Every instant is absolute; no relative seconds anywhere. The 4200 supremum is retired from the refusal text.

The **canonical claim deadline is derived from receipt** (R5) and therefore does not exist at ruling time. A lane line must not carry one. What it may carry is today's horizon, named and versioned as the projection it is (`pre_migration_horizon`, with its `basis` and its `model` spelled out in the row), because `observed_at` is store-only, absent from the chain, unreconstructible by an offline reader, reset on replay, and silently not set by the default CLI identity (#850). Exporting that as `claim_deadline` would freeze a current implementation accident into a new outward artifact, and every later reader would inherit it as compatibility debt. The sentence the asker reads says the same in words: the horizon is anchored on the ruling, not on their receipt of it.

A re-issue must be **byte-identical**: the act digest covers the whole command text. The sentence says so, because a near-miss claims nothing and looks like a plain deny (measured 2026-09-02: an appended `&& ls -l` lost a live grant).

**R4. Seat delivery, live.** Each seat's gate hook, on every PreToolUse, PostToolUse and UserPromptSubmit event, reads its own lane (a `stat` on one file; a read only when the size changed since the last event, cursor kept in the seat's state dir) and renders any unread line on the seat's context port. Port by engine is a measured property of the (engine, event) pair (`hook_context_contract_report.py`), not a fleet assumption: claude via `hookSpecificOutput.additionalContext`; gemini via stderr on the next decision; codex and kimi per the contract report, and where no port exists the next gate response carries the line in its text. The rendering is verbatim daemon content plus the seat's channel framing.

**The cursor is per (seat, session), and a read is never destructive to another session.** One cursor per seat is a defect, not an optimisation: a co-seat session advances it past a line addressed to the asker and the ruling is destroyed unrendered (#851, measured; the bystanders are the mesh wakes that exist because delivery is broken). A session's first sight of a lane reads it whole and renders only lines that NAME that session; unaddressed lines are delivered from the second sight onward. Starting a first sight at end-of-lane is also wrong, and was measured wrong: a ruling can land before the asker's next hook event, and then it is never seen.

**R4a. Registration is an operator act, and it is a deployment prerequisite.** The installer ships only files a member declares AND the host registers, and the registration file is a governance marker, so a governed member cannot write it. Every seat therefore needs one operator act before any seat hook can ship: declare the file in the member's manifest (the member may do this), then register it in the host's hook configuration (only the operator may). This PRD previously assigned the port to "each seat's hook" and never named that act, which made the whole of R4 depend on an implicit human keystroke (#851). A seat whose reader is unregistered is INDETERMINATE for delivery, not compliant and not failing.

**R5. The clock starts at a witnessed receipt, and the legacy anchor is migrated away, not extended.** The canonical claim horizon is `receipt + window`, where receipt is the acknowledgement of R8: attributable to the asker's own proven session, on the chain, reconstructible by an offline reader and by a restart. Only then is an absolute deadline derivable, and only then may a lane line carry one.

Today's anchor is `observed_at`, and #850 measured what it is: store-only, off-chain, unreconstructible, reset to `None` on replay, and not set at all by the default CLI identity. It is not a smaller version of the target; it is a different thing. The migration is explicit and has three steps, in this order:

1. lanes stop exporting a canonical deadline and name today's horizon as a pre-migration projection (R3);
2. the receipt event lands, and the horizon is computed from it when one exists, falling back to `observed_at` only for escalations opened before the event existed;
3. `observed_at` stops being an anchor at all and remains, if it remains, as a diagnostic.

A poll from any session other than the asker's must never start the window, in any of the three states (#732).

**R6. Bystanders neither consume nor burn.** The watcher's consuming drain skips notices whose `for_session` names a session with a live lease; a lease is the daemon's own knowledge of the MCP session (`hestia_connect`, heartbeat), never an inbox touch. When the lease is dead the watcher takes the notice and the fired session is told, in the primer, that it is a relay: read `claimable` from the line, never poll, never re-issue on the asker's behalf, and say in one mesh reply where the asker can find the lane.

**R7a. A grant is claimed last, after every other rule has agreed.** A claim spent on a call that another rule then refuses is an operator decision spent on nothing, and the asker's only compliant move (re-issue byte-identically) is what triggers it (#863, measured: the gate-self layer claimed, then the safety preset denied the same call). Either the claim is the last act before the effect, or it is a reservation that is released when the call does not proceed (#825's `reserved` -> `spent` -> `lapsed`).

**R7. The asker acts; the hook does not.** Delivery tells the model what was decided and what it can do. The re-issue is the model's act, gated as any act; the claim happens on the re-issue as today. A hook that performed the write on approval would be a shim performing an act, and the reasoner would be out of the loop.

**R8. Receipt is an explicit, idempotent acknowledgement, and the obligation is append-only.** The seat acknowledges by escalation id, attributed to the asker's proven session; the daemon records `gate_escalation_delivered` (`escalation_id`, `session`, `port`, `delivered_at`) on the chain, and a repeat of the same ACK changes nothing. Consume-on-read is the wrong primitive and is not adopted: it is what made the mesh drain destructive, and #851 is the same defect one layer down. A local cursor is an optimisation for "what have I already rendered", never the record of what was received.

An approval that expires with no delivery event, while the asker's session was live, is a **delivery failure**: its own class in the lapse record, never folded into the asker's conduct. Restart and replay must reconstruct both undelivered obligations and prior valid receipts, since neither may depend on a file in a seat's state directory.

## 4. Non-goals

- Executing the act on the operator's approve. That needs an act-bound, replayable record (#539, #565, #825) and is the terminal design; this PRD makes the seat learn the ruling, which that design needs too.
- Changing the 600 s window. It stays a dial (dp: "expire fast was a fix to kimi's hooks failing open"). With delivery at decide time and the clock starting at delivery, the dial measures the asker's reaction, which is what it was for.
- A push channel into a running session other than its own events. None exists in any engine on this box; the hook stream is the channel.

## 5. Acceptance

An instrument, `tools/disposition_delivery_probe.py`, against the stub daemon and against a live one:

1. Open a synthetic gate-self escalation from a proven session; approve it via `hestia gate approve`. The lane file gains one line before the CLI returns. The line's `claim_deadline` equals the horizon `hestia gate poll` reports.
2. Fire one PreToolUse event in the asker's session: the hook's output carries the line's content on the engine's measured port, and `gate_escalation_delivered` is on the chain with that session.
3. Drain as the watcher while the lease is live: the notice is not consumed and `observed_at` is unset. Kill the lease; drain again: consumed, and the primer says relay.
4. Poll from a second session of the same `plugin_id`: `observed_at` stays unset.
5. Grep the tree: no `retry_within_secs`, no `4200`, no relative window in any refusal text, and no `claim_deadline` on any lane line until R5 step 2 lands.
5a. **Bystander first**: a co-seat session fires before the asker on the same lane. It renders nothing, and the asker is still delivered afterwards. This sequence is a required regression arm for every seat reader (#851), and it is the arm a single-session test cannot replace.
5b. **Restart**: kill and restart the daemon between ruling and receipt. The obligation is still there, and a prior receipt is still evidence.
6. Live, one week, all four seats: approvals that expired unclaimed while the asker's lease was live equals zero; every lapse carries either `delivered_at` or the delivery-failure class.

## 6. Ownership

| piece | owner | notes |
|---|---|---|
| lane file, `for_session`, decide-time append, `gate_escalation_delivered`, deadline in the horizon's units | daemon (Rust) | one transaction with the chain append |
| watcher skip-on-live-lease, relay primer | `plugins/member-mesh` | consume-once stays; the address decides who may consume |
| per-seat delivery port | each seat's hook, class refusal-channel | renders, composes nothing; port pinned by the contract report |
| retiring 4200 and `how_to_wait` | daemon refusal payload, seat hooks | the lane replaces both |
| per-seat registration of the reader | the OPERATOR, once per seat | R4a; a member cannot write its host's hook configuration, and no amount of member-side work substitutes |
| instrument | `tools/` | CI arms 1 through 5b; arm 6 is the live acceptance |

## 7. Why this and not a longer window

A longer fuse hides the missing channel and widens the pool of unclaimed grants (#719: the window is a dial on that pool). Two of today's three expiries had a human in the loop relaying by hand and still missed. The asker was online the whole time; what it lacked was a sentence on a port it reads. That sentence costs one file append and one `stat` per hook event.
