# Sprints — the app's governing surfaces

**Derived from:** `PRD_APP_GOVERNING_SURFACES.md` (2026-09-24). Sequences S1–S3; S4 is deferred
there and does not appear here.

**Ordering rule, from the PRD:** decide before grant. Acting on what is already asked is the
owner's daily act; issuing new authority is rarer and more dangerous, and is built once the decide
path has been exercised for real.

Each sprint lands as its own PR. A sprint is done when its acceptance line is **measured** — a test
that fails against the previous commit, or a transcript. "It renders" is not acceptance.

---

## Sprint 1 — Decide: pending escalations

**Why first:** the data already arrives. `DashboardSnapshot.pending_escalations` is on the wire
every tick and the app's own type omits it, so the owner's most consequential decision is fetched
and discarded. This sprint spends its effort on the decision path, not on plumbing.

| # | deliverable |
|---|---|
| 1.1 | `PendingEscalation` type; `DashboardSnapshot` carries `pending_escalations` — the app stops discarding what it fetches |
| 1.2 | `decide_gate_escalation` Tauri command → `POST /api/operator/gate-escalation` through the operator session, never the CLI path |
| 1.3 | A Decide view: each pending item with the refused act, the rule that refused it, the asker, and the remaining window |
| 1.4 | Approve requires a reason **in the app**, quoting the daemon's rule; deny does not. The asymmetry is preserved, not inverted |
| 1.5 | Signed out: the action is **absent**, not disabled-looking. Signed-in state comes from `operator_status` |

**Acceptance, measured:**
- a decision made in the app lands in the chain with `via` naming the strong channel, and the same
  shape decided on the CLI lands with a different `via`;
- an approve with an empty reason is refused **by the app**, before the daemon sees it;
- with no operator session, no decide control exists in the DOM.

**Conflict management (PRD §1a), in this sprint because escalations are the single-shot case:**
- a 409 from the engine renders as *already decided elsewhere*, not as an error;
- the queue is re-read on window focus as well as on the tick;
- the view re-reads after every decision instead of patching local state.

Each is covered by a test that fails when the behaviour is reverted — measured, not asserted.

**Non-goal:** scope requests. They share the pane later (Sprint 2), and mixing them here would
couple two daemon contracts in one change.

**Ruling owed before Sprint 4:** scope grants and config writes are **not** single-shot, so the 409
story does not cover them. Last-writer-wins may be right for some and wrong for others, and the app
must not pick silently. Sprint 4 is blocked on that ruling.

---

## Sprint 2 — Decide: scope requests

**Why second:** same pane, different daemon contract (`POST /api/scope/decide`). A scope ruling
carries the ruler's own words to the asker, which an escalation decision does not.

| # | deliverable |
|---|---|
| 2.1 | `GET /api/scope/requests` surfaced: path, asker, stated reason, age |
| 2.2 | `rule_scope_request` command → `POST /api/scope/decide`, carrying the ruler's reason verbatim |
| 2.3 | The two kinds share one Decide view and stay visually distinct — an escalation is a refused act, a scope request is an asked-for reach |
| 2.4 | The asker's stated reason is shown **in full**; truncation here is how a request gets ruled on its summary |

**Acceptance, measured:**
- a request ruled in the app reaches the asker with the ruler's words attached (verified against a
  live member — HUB has a being that files these);
- a refusal with no reason is refused by the app.

---

## Sprint 3 — Who is governed here

| # | deliverable |
|---|---|
| 3.1 | `GET /api/agents` surfaced: installed / adapter-available / governed, plus gaps |
| 3.2 | **`UNKNOWN` renders as its reason string, never as an empty list** — the one forbidden rendering |
| 3.3 | `ungovern` / `connect` offered only where the daemon says they apply |

**Acceptance, measured:** with `agent-inventory` uninstalled, the app shows the daemon's reason. The
test asserts on the reason text, so a regression to an empty list fails it.

**Note:** hestia #1076 adds beings to this inventory. When it lands a being appears here with no app
change — the shape is the daemon's, which is the point of building against the route.

---

## Sprint 4 — Grant

| # | deliverable |
|---|---|
| 4.1 | Live and standing grants per member, and what was revoked |
| 4.2 | grant / revoke / promote-to-standing / floor adjust, each an operator act |
| 4.3 | Every write names the operator's LCT in the chain entry, not the daemon's |

**Acceptance, measured:** a grant issued in the app is honoured by the member's next gate call, and
the chain entry names the operator.

---

## What is deliberately not scheduled

- **S4 Evidence** (chain/trust views) — deferred in the PRD; the dashboard serves it.
- **Remote deciding** — blocked on a ruling about what a remote operator session means.
- **Anything requiring Sprints B–F of `SPRINTS_APP.md`** — nothing here depends on them.
