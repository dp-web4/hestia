# Every ruling row names who ACTED and never who it is ABOUT — and that is why the return edge is addressed by seat name

Measured on CBP, 2026-09-18 (local 2026-09-17 21:00 PDT), claude-code mesh wake
`9099519e`. Chain window `2026-09-13T19:48:04Z → 2026-09-18T04:01:55Z`, 12,000
entries walked with `tools/chain_walk.py`; 287 of them non-bulk (everything that is
not `outcome`, `policy_decision`, `agent_inventory`, `gate_self_*`, `egress_forwarded`,
`member_notice`).

Artifact: PR on `cbp/asker-session-on-ruling-rows` — three append sites, one test,
three arms. No behaviour change: nothing is addressed differently yet.

## The wake

Second bystander wake in 13 minutes. Five `disposition` notices, `i_owe` 0 of 0,
`open_petitions.mine` empty. All five escalations (`17c7f028`, `06fc06c1`,
`b98f92ec`, `ab77a323`, `32dfe9de`) were opened by host session
`9261dc9a-1703-4964-9e72-a076bd468aca` — the interactive seat working #1050, with
dp in the room typing `ok`. My session is `9099519e`. The previous wake measured the
same thing (6 of 6) and filed #1060; this one asked the next question instead of
re-deriving that one.

The next question is **why** the notice comes to the name. Not policy — arithmetic.

## The census

Session-provenance coverage, by event type, over the window. `N` is rows;
each column is how many of those rows carry a populated value.

| event type | N | host_session_id | session_id | other identity present |
|---|---|---|---|---|
| `gate_escalation_opened` | 23 | **23** | **23** | `asker_basis` 23, `plugin_id` |
| `gate_escalation_claimed` | 11 | **11** | 0 | `plugin_id` — and the key is the CLAIMANT's |
| `gate_escalation_corroborated` | 16 | 0 | 0 | `corroborated_by` (a NAME), `plugin_id` |
| `gate_escalation_decided` | 14 | 0 | 0 | `decided_by`, `decided_role`, `decided_via` |
| `gate_escalation_withdrawn` | 9 | 0 | 0 | same as decided |
| `gate_escalation_coalesced` | 2 | 0 | 0 | `plugin_id` only |
| `gate_escalation_expired` | 1 | 0 | 0 | `plugin_id` only |
| `scope_requested` | 28 | 0 | 0 | `plugin_id`, `role` |
| `scope_granted` | 9 | 0 | 0 | `granted_by`, `plugin_id` |
| `scope_refused` | 14 | 0 | 0 | `granted_by`, `plugin_id` |
| `scope_attestation` | 37 | 0 | 0 | `attested_by`, `requested_by` 13/37 |
| `appeal` | 9 | 0 | **9** | `plugin_id`, `routed_to` |
| `adjudication` | 9 | 0 | 0 | **`adjudicator_session`**, `subject_plugin_id` |

## The rule the table states

**A session key appears on a row exactly when the daemon proved the session of the
party that ACTED on that call. The session of the party the row is ABOUT is never
carried forward.**

- `opened` — the actor is the asker, so the asker's wake is there (#542 put it there).
- `claimed` — the actor is the claimant, so the key is the claimant's. Same field
  name, different subject. That is worth saying out loud: `host_session_id` does not
  mean one thing on this chain.
- `adjudication` — `adjudicator_session` is present; the subject's is not.
- `corroborated` — the peer is named (`corroborated_by`) but its session is not
  recorded at all (#1058).
- `decided` / `withdrawn` / `expired` / `coalesced` — the deciding actor is an
  operator or the clock, and nothing names the asker.

**One exception, and it cuts the other way.** `gate_escalation_corroborated` drops
the *actor's* own proven session, which the rule does not explain.
`tool_gate_escalation_corroborate` refuses without a live `session_id`
(`resolve_attributed_caller`) — attribution is a precondition of the door — and the
row then records `corroborated_by` and `corroborated_role`, both names.
`CallerWho` carries `session_uuid` but not the wake key; recovering it is the same
one-line lookup the open door already performs
(`s.sessions.get(&uuid).host_session_id`). So #1058's "peer review is performed off
the record" is not a consequence of the actor/subject asymmetry. It is simply
missing, and it is one lookup from a value the door has already proven.

The store is not missing the data. `EscalationStore`'s own record holds
`host_session_id`, `session_id` and `gate_path` (`record_seat_keys`, #542), it
survives a restart (`rehydrate` restores them from the `opened` row), and the
`decided` payload is built from that very record. The field is in scope at the
append site and is not written.

## Why this is the reason the return edge is name-addressed

`handler::disposition_obligation` is the whole return-edge derivation. It takes **one
chain entry** — a terminal ruling — and returns `(recipient, pointer)`. Six arms:
`adjudication`, `gate_escalation_decided`, `_expired`, `_withdrawn`, `scope_revoked`,
`scope_granted`/`scope_refused`. Every one of them addresses the SUBJECT of the row
(`plugin_id`, or `subject_plugin_id` for an appeal). Every one of them is reading a
row from the list above where the subject's session is absent.

So the recipient can only be a seat NAME — and a name is not a session. Over the
same window, **6 distinct `claude-code` host sessions** opened or claimed escalations
(kimi-code 2, codex 1). A disposition addressed to `claude-code` has six candidate
owners, and the one that gets it is whichever seat's watcher drains first. My own
inbox this wake also held a `review_done` bound to notice 13086 — the interactive
seat's review request, answered by kimi-code, delivered to me. I left it undrained
rather than consume another session's answer.

Downstream: `member_notices` has one
recipient column, `to_plugin TEXT NOT NULL`, and no session column at all; the
watcher's consuming drain takes the row for the name; a full autonomous wake fires
for a ruling its session did not ask for and cannot claim; and its cheapest next
step — `gate poll` — starts the real asker's fuse (#732). None of that is a policy
choice made anywhere. It is the only thing derivable from the record.

`docs/PRD_DISPOSITION_DELIVERY.md` R1 is exactly the fix: *"The disposition row
carries `for_session` = the `host_session_id` recorded from the asker's proven
session."* The PRD is DRAFT, landed 2026-09-02 (#845, tracker #825), and
`for_session` appears in **no** shipping `.rs`, `.py` or `.sh` 15 days later — only
in the PRD and in `tools/disposition_deliver_bystander_probe.py`, which simulates it.

The design's *seat-side* leg was attempted and is blocked on something else. #851's
probe built the candidate deliverer, escalated it for install on 2026-09-02, and
measured that with one seat-wide cursor a bystander session does not merely read the
asker's line early — it **destroys** it, because `for_session` filtering happens
after the cursor advance. Its arm C fix is a per-(plugin, session) cursor. So R1 has
two unlanded halves: a cursor key on the seat side (#851, measured, dissented) and an
asker key on the daemon side (this PR). Neither blocks the other.

**The narrow thing this finding adds to that design:** R1 cannot be implemented
idempotently until the ruling rows carry the key. `ensure_disposition` is the
synchronous fast path and is warn-and-continue by contract; the durable path is
`project_dispositions`, a cursor that re-derives each obligation **from the chain
page alone** — that is the retry that runs precisely when the synchronous ensure
failed. An R1 implemented only at the decide site would carry `for_session` on the
happy path and silently drop it on the failure path R1 exists to survive.

## What landed

`asker_host_session_id` (deliberately not `host_session_id` — see the `claimed`
row above), from `Escalation::host_session_id`, on the three real ruling appends:

- `core/src/server/http.rs` — operator HTTP decide (`gate_escalation_decided`)
- `core/src/server/handler.rs` — MCP arbitrate (`gate_escalation_decided` /
  `gate_escalation_withdrawn`)
- `core/src/server/handler.rs` — `record_newly_lapsed` (`gate_escalation_expired`)

Test `a_ruling_names_the_askers_wake_so_the_return_edge_can_be_addressed`: approved
arm (decider is a peer, row still names the asker), withdrawn arm, and an
unproven-asker arm pinning that the key stays NULL and the ruling stays projectable
by name. The null arm matters — a substituted value in an attribution record is
worse than a missing one, and unproven askers are a live state, not a hypothetical.

Same remedy class as `bar` on the expiry row, whose own comment already makes this
argument for a different field: *"The `opened` event has always recorded it; the
expiry did not, so answering 'which bar lapses?' required joining every expiry back
to its open."*

## Honest edges

- **This changes no behaviour.** The notice still goes to the seat name. It makes the
  addressing derivable; R1's delivery leg stays #825's.
- **Coalescing is not covered, and cannot be by this shape.** `record_seat_keys` is
  called only on the `Minted` arm at both open doors — verified in source, both call
  sites. So a second session whose identical refused act coalesces into a live twin
  is named on *no* row of the lifecycle: not on the coalesce row (2 in the window, no
  session field), not on the ruling. `asker_host_session_id` will name the FIRST
  asker and be right; it will also be incomplete, and for a coalesced petition even
  perfect asker addressing delivers to one of the two askers. Where the second
  asker's return edge belongs is a question I did not answer.
- **Scope and appeal need a door change, not a copy-forward.** `scope_requested` has
  no session key on 28 of 28 rows — the field is never captured, so there is nothing
  to propagate. `appeal` carries `session_id` (the per-connection MCP uuid), which is
  documented as the wrong key to join wakes on. R1 generalises to those surfaces only
  after they do what #542 did for escalations.
- **One box, one window.** The counts are CBP over 4.2 days. The 6-of-6 disposition
  misdelivery figure is the previous wake's, same box, one hour.
- **The drain happened; what it cost is narrower than it sounds.** This wake's fire
  drained all five disposition rows before I ran, and a non-consuming `peek`
  afterwards shows them gone — so the durable return edge for five of another
  session's rulings was consumed by a session that asked for none of them. But the
  asker was not thereby denied its ruling: it reads mail at SessionStart only, it was
  mid-session, and dp was in the room saying `ok`. So the measured loss is of the
  only durable REPRESENTATION, which is an R8 (receipt) problem more than an R1
  (addressing) one — nothing can later prove, or re-deliver, what was told. #851
  measured the destructive version on the lane side. The arm where nobody is in the
  room is still unrun.

## So what

One sentence covers #732, #1058, #1060, and the wake-cost residual #927: **this chain
records acts, and every return edge addresses a subject.** Provenance is written where
it was proven, never where it will be read. That predicts where the next expensive
join will be — and it predicted the two the census found before I looked for them
(scope's return edge and the appeal subject), neither of which has an issue.
