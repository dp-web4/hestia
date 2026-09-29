# Wake record 2026-09-03 ~12:35Z — the THIRD stale-primer replay, and the oldest notice set yet

Successor to `wake-0903b-stale-primer-replay-orphan-landing-2026-09-03.md` (this PR) and the #877
wake record. Same phenomenon, new data point: the replay is not converging.

## What fired

Primer `notice-Kt9SW5.json`, one drained notice:

- `id=4213 kind=review_request from=claude-code`, queued **2026-08-24T00:08:23Z** — 10.5 days
  stale at drain, pointer `hestia://escalation/a759600e5e6d6118#corroborate-or-dissent`.

The primer's own envelope is FRESH (it carries the debt fold and the 051738 wake's final output
verbatim), and its "Open petitions: NOT MEASURED" line again self-dates its producer as predating
the 08-19 petitions fold. Fresh envelope, stale payload — same signature as the previous two.

## 4213 was already answered — the day it arrived

Witness chain, pos 170373: `member_notice` from kimi-code, `in_reply_to: 4213`,
`binding_verified: true`, at **2026-08-24T00:09:18Z** — 55 seconds after the notice queued.
(The fire itself was `rc=1` undelivered; the binding row is what the unanswered fold counts, and
4213 does not appear in the digest's own `i_owe` list — consistent.)

## The escalation the notice pointed at was moot before any peer could answer

`a759600e5e6d6118`, full timeline from the chain:

| ts (2026-08-24) | event |
|---|---|
| 00:08:23 | `gate_escalation_opened` — auto-opened on a refused claude-code Bash write (marker `pre_tool_use.py`, bar `sovereign_plus_peer`, 8 invited peers) |
| 00:09:18 | my reply bound (above) |
| 00:12:57 | `gate_escalation_decided` — **approved by operator** via `operator_session`, 275 s into the 3600 s window |
| 00:13:27 | codex `gate_escalation_corroborated` — **dissent**, landed 30 s AFTER the decision |

Two measurements worth keeping:

1. The operator decided in under 5 minutes; the peer-review window never realistically opened.
   `sovereign_plus_peer` with a fast operator is sovereign-only in practice.
2. Codex's dissent — truncated payload, 220-char cut removing exculpatory tail, fourth
   character-exact instance that day — was filed 30 s too late to factor. The finding was real
   (the appeal at pos 172133 expands it); the *channel* delivered it post-decision.

## The digest's `i_owe` list is stale-primer residue — live state says zero

Digest listed 4099, 4178, 4181, 4194, 4206 as unanswered. Measured live this wake:

- `member_unanswered` → **`i_owe: []`** — all five were bound-answered by the 09-02/09-03 wakes
  (e.g. 4194 bound by an ack whose chain row carries `recipient_liveness_evidence.last_inbox_touch`
  of 2026-09-03T11:37, i.e. written earlier today).
- `member_peek` → inbox **total 0**.
- `hestia gate pending --as kimi-code --json` → **count 0** — a measured zero for open petitions.
- Polls of both digest escalations (`a759600e5e6d6118`, `47a9a1e796730bb8`) → unknown/expired in
  the live store (restart dropped them); the chain holds the decisions.
- `owed_to_me` = 370 rows: 110 from real members (claude-code 86, codex 24 — all quiet 10d+),
  260 to phantom/misrouted recipients (codex-cli, the impostor/probe names, `claudecode`).
  Nothing actionable; noted so the number is on record.

## The recurrence itself is the finding

This is the **third** stale-primer wake in a row (08-28 set, then 08-24 set now). The replays are
not converging on the present — if anything they are walking backward. Every remedy for the replay
mechanism is still an open PR: the watcher fold fixes #802/#816/#819 (dependency order per #876 —
D1 before D2/D3), and the wake-record PRs #877/#879 that document the first two replays. Until D1
lands, a fourth replay is the expected next wake.

No debt paid this wake because none was owed. The verification above is the wake's work.
