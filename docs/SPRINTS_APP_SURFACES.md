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

| 2.5 | Recursion is the operator's explicit choice, **off by default** (a request names one path); *standing* is offered only with a grant — a standing refusal is not a thing |

**Acceptance, measured:**
- a request ruled in the app reaches the asker with the ruler's words attached (verified against a
  live member — HUB has a being that files these);
- **a grant with no reason is refused by the app; a refusal with no reason is SENT.**

**Correction (2026-09-25, while building it):** the first draft of this line said *"a refusal with
no reason is refused by the app."* That inverts the daemon's own rule — `scope_decide`: *"widening
needs a stated why, narrowing does not. Refusing is the safe direction and must never carry more
friction than approving."* The real concern behind the draft was sound: the asker reads the ruler's
words, and a being given a bare "no" tends to appeal it. The answer is to **invite** words on a
refusal and say who will read them, never to **require** them. A test pins it: clicking Refuse with
an empty reason must call the daemon.

---

## Sprint 3 — Who is governed here

Split on 2026-09-27: the daemon grew `retire` / `reinstate` (#1100, #1113) after this plan was
written, and a retire revokes standing grants — consequential, with its own recent-activity guard.
So **3a** is the read surface and **3b** the actions, the same caution as decide-before-grant.

| # | deliverable |
|---|---|
| 3.1 | **3a** — `GET /api/agents` surfaced: installed / adapter-available / governed, plus gaps; beings shown with the launcher and `--member` that make them governed |
| 3.2 | **3a** — **`UNKNOWN` renders as its reason string, never as an empty list** — the one forbidden rendering |
| 3.3 | **3a** — a retired id that is still governed or wired is called out, not merely hidden |
| 3.4 | **3b** — `connect` / `ungovern` / `retire` / `reinstate`, each offered only where the daemon says it applies; retire carries its reason, ref and the recent-activity guard |

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

**Conflict policy — ruled 2026-09-25: last edit wins.** Unblocked. Because the engine will not stop
an overwrite, the view must make it visible: 4.4 below.

| 4.4 | Every write re-reads first and **shows the value it replaces** at the moment of the write; re-reads after it lands |

**Acceptance, measured:** a grant issued in the app is honoured by the member's next gate call, and
the chain entry names the operator; a write over a value another view changed since the last read
shows that value before it is replaced (tested against a stale read).

**Split on 2026-09-28**, by the spec's own capabilities: **4a** grant (operator-originated,
standing) + revoke (live and standing) + the read — built; **4b** promote / recursive / reassign
(`scope-standing`); **4c** delegations. **Floor adjust is out**: the spec keeps `/api/scope/floor`
off every UI until a surface is designed for the widest escalation there is.

**4a as built.** A *Reach* page (activity place, beside Decide): every grant grouped by member with
its lifetime on the row (a live grant says it dies at the next restart), reach (exact / subtree),
why, and who. Members are **chosen** from the recorded, unretired registry — never typed. Grant needs
a reason; revoke does not, and a revoke of something already gone is `already_revoked`.

**4.4, bound in the daemon, not just the view.** The form shows the standing row a grant would
replace ("This REPLACES…", old reason and reach) and sends it back as `expected_existing` (`null` =
shown none). `/api/scope/grant` compares it **under the lock** and answers 409 `moved` with the
current row, writing nothing; the app renders that as "changed since you looked". A binding only the
client held would be the race GPT caught on #1132, so the check lives where the write does. Absent
`expected_existing` is unbound, so the dashboard keeps working — **follow-up: the dashboard's grant
form should send it too** (spec rule `bound-to-rendered-evidence` now lists `scope-grant`).

---

### 4c as built (2026-09-29): Delegations

The placeholder page, which read a `delegations` field off the snapshot and labelled empty
roles "all", is replaced by the three routes it stood in for:
- **Pick a member** from the registry. Its delegation key is derived by the daemon; the app sends
  no identity field, and the daemon refuses one (#1067).
- **The listing** shows each delegation's status (active / expired / revoked). Revoked ones stay
  listed.
- **Grant:** roles are checkboxes from the daemon's closed list, and actions are one per line.
  The page refuses a grant naming nothing (it would be full authority) and one with no reason.
  After a grant, the daemon's `unvalidated_actions` is shown in full, not as a bare "delegated".
- **Revoke:** an already-revoked answer is an outcome.
- **Retired member:** its history is readable and the grant form is absent.
- **Signed out:** nothing is read, and the page says so.

**Raised, not changed: revoke requires a reason.** `agent_delegation_revoke` answers 400 without
one, pinned by its own test and by `delegation_panel_contract_test.py` ("revoke asks for a
reason"). That inverts the asymmetry kept on every other surface (scope revoke, decide, refuse),
where narrowing never costs more than widening. The app follows the daemon and labels the field
"the daemon requires one to revoke". The owner's call is whether to relax it.

Spec: `delegations` app -> required.

## What is deliberately not scheduled

- **S4 Evidence** (chain/trust views) — deferred in the PRD; the dashboard serves it.
- **Remote deciding** — blocked on a ruling about what a remote operator session means.
- **Anything requiring Sprints B–F of `SPRINTS_APP.md`** — nothing here depends on them.
