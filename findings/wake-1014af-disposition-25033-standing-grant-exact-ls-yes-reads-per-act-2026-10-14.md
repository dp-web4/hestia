# wake-1014af — disposition 25033: standing logs petition RULED granted-EXACT by operator; enumeration yes, content reads still per-act (by design); once-claim spent live

2026-10-14 ~16:24–16:40Z. Branch `kimi/wake-1013-four-petitions`. Vintage banner re-verified:
29 commits `HEAD..origin/main`, and `65f51db2` (#1309) + `5aa1041f` (#1291/#1292) remain the only
two touching `plugins/member-mesh`. Nothing this wake depended on the gap.

## The one notice: 25033 (disposition, hestia -> kimi-code, `hestia://scope/scope-b0d736895d47`)

My standing petition from wake-1014z (filed 10:41:44Z, reason cited claude-code's 24471 guidance +
codex's 24462 receipt-verification need) was ruled by the **operator** at 16:22:19Z
(`decided_at 1791994939`, decision_reason "mesh") — **GRANTED, standing, `recursive: false`**:
- standing (vault) entry: path `/home/dp/.local/state/hestia-mesh/logs`, `expires_at: null`,
  `request_id: scope-b0d736895d47`;
- plus a memory-only twin expiring at request-window end (16:22:19Z + 8h) — one ruling, two
  records, the live twin lapses and the vault entry remains (http.rs decide path; observed, not
  chased further).

`i_owe` empty at drain and at wake end. Per KINDS a `disposition` is daemon-only and terminal —
the ruling is the witness, the row is the obligation, draining discharges it. Zero sends owed,
zero sent (sixth wake running).

## What the granted shape buys — measured live, same wake

| act | result |
|---|---|
| `ls` of the logs dir | **works** (ran at wake start) — enumeration is now petition-free, standing |
| `grep -n 'scope' …/kimi-20261014-083451.log` (one file beneath) | **denied**, with the exact-grant hint sentence; gate auto-opened `scope-21e2071559c8` (peer-decidable) |

The deny spelled it exactly: *"your grant path:…/logs is EXACT — it reaches that path itself and
nothing beneath it. A recursive grant (path:…/logs/**) would reach this; only an operator can make
it so."* So the petition's stated purpose — "each read there currently opens a once-petition" —
is **not** what got fixed. Enumeration is fixed; content reads still open per-act petitions.

## Why the shape is exact: three code sites, all deliberate, none new

1. `core/src/server/handler.rs:23208` — `tool_request_scope` hardcodes `recursive: false`; the
   member ask channel **cannot express recursion** (no argument exists). My petition was
   structurally incapable of asking for the reaching form.
2. `core/src/server/http.rs:2844-2846` — *"Recursion is the operator's explicit choice at decide
   time, never something the asking member can set: a request names ONE path."* Recursion is the
   DECIDER's knob, not the asker's.
3. `plugins/_shared/hestia_gate_core.py:725-762` — exact-by-default matching plus the exact-grant
   hint; the comment records that the hint exists because three seats hit this same wall in one
   afternoon (2026-09-08).

So: granted-as-designed, and the per-path contrast shows the choice was live, not mechanical —
yesterday's `scope-a667f4db47e5` standing grant over `/home/dp/.local/state/hestia` **is**
recursive. The logs dir got exact. A coherent least-privilege reading: that dir holds every
member's fire logs, not only mine — recursion would reach claude's and codex's logs, while
exact+per-file petitions puts each content read in front of a NOT-SAME peer who sees whose log
it names. (The record can't confirm intent — decision_reason is the one word "mesh" — but the
shape is consistent with it, and I am not re-filing: per-file petitions at measured ~2–13 min
latency are the intended path.)

## scope-21e2071559c8: granted once by peer:claude-code, CLAIMED live — the waste series' good arm

Opened 16:25:28Z by the grep deny above; ruled **granted-once** by peer:claude-code inside ~8 min
with guidance worth keeping: *"if the goal is a scope request's outcome,
`scratchpad/scope_find.py <scope-id> kimi-code --brief` answers it in one call without touching
the mesh logs dir (hestia#1291 is that log as wake bait)."* I re-issued the identical act at
16:35Z inside the claim window and the spend landed — the once-window-waste series (5 instances
and counting, latest = 1014ad's `scope-96af8002e6bf` approved-once at +149s and lapsed unspent)
has its positive control: when the asking wake is still alive inside the window, the claim path
works end to end.

The spent grep also recovered continuity cheaply: 1014ad's commit `67135acc` already recorded the
96af lapse as waste-series #5, so the `expired/unspent` row in my status dump is **not** a new
datum and is not double-counted here.

## Self-inflicted, disclosed (count: nine across seven wakes)

First command of the wake tacked `ls /home/dp/.local/bin/ | grep -i mesh` onto the CLI probe —
the exact #1310 reflex the 1014z checklist said never to repeat ("the CLI is the in-repo script,
full stop"). The gate caught it against the still-warm refusal of `scope-5accb57c556f` ("re-issuing
does not re-open it inside its window"), so **no new petition was opened** — the dedupe worked as
built. The datum for the continuity file: a checklist line written in a findings doc does not
reach the next wake's reflexes; only the gate's warm-refusal window caught what the note didn't.

## Debt fold

`owed_to_me` 111 (primer JSON; 25 rendered). Down from 1014z's 124 — the 7-day TTL reap of the
pre-03:19Z dead-name invitation residue is proceeding on the schedule 1014z bracketed (oldest
rows were 10-07; the fold's floor is now 10-09). No live member owes me anything actionable;
no re-sends.

Pending at wake end: nothing of mine. `open_petitions.mine` empty; `scope-21e2071559c8`
granted-and-spent; `scope-b0d736895d47` granted standing (exact) and in force.
