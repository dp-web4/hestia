# PRD — the app's governing surfaces

**Status:** draft for review. Author: claude-code (HUB), at dp's direction 2026-09-24.
**Reviewers owed:** GPT, codex, kimi, legion, cbp, sprout, mcnugget.
**Measured at:** `d9018a21`, on HUB, 2026-09-24. Every number below was run, not read.

**Subordinate to** `PRD_APP.md` (§1: *"The app is how the owner becomes served"*) as amended by
decision 0014 (the app is a member with its own harness LCT, not a dashboard on a daemon).
`SPRINTS_APP.md` sequences the identity work; this document sequences what the owner can *do*
once that identity exists. Sprint A of that document has landed; B–F have not, and nothing here
depends on them.

---

## 1. The one fact that decides this document's scope

`core/src/server/http.rs:5823`, the daemon's own words about `POST /api/operator/gate-escalation`:

> the **STRONG** decision channel for a governance-surface write … Behind `operator_gate`, so the
> caller has proved an operator LCT by challenge/response. That is what makes this channel
> different from `hestia gate approve` on the CLI, **which is authenticated only by filesystem
> access to `HESTIA_HOME` — the same access every member on this box already has.**

There are three ways to decide a governance escalation today, and they are not equivalent:

| channel | authenticated by | who can reach it |
|---|---|---|
| `hestia gate approve` (CLI) | filesystem access to `HESTIA_HOME` | **every member on the box**, including the agent being judged |
| daemon web dashboard | operator session in a browser the daemon serves | whoever has the browser |
| `POST /api/operator/gate-escalation` | **an operator LCT proved by challenge/response** | a holder of the operator key |

Sprint A gave the app encrypted custody of that key and signed five-field sessions (`#298`). **The
app is therefore the only surface that can exercise the strong channel as designed.** That is not a
UI preference; it is the reason to build these surfaces in the app rather than add another tab to
the dashboard.

The corollary is uncomfortable and belongs here: an operator who decides from the CLI is using the
channel that the same box's agents can also use. The app exists to make the strong channel the
convenient one.

---

## 2. What exists — measured 2026-09-24

### 2.1 The app runs, and is a monitor

| | value | how measured |
|---|---|---|
| app source files | 23 | `find app/src -name '*.ts*' \| wc -l` |
| registered Tauri commands | 24 | `invoke_handler` in `src-tauri/src/lib.rs` |
| pages | 8 (Chain, Dashboard, Delegations, Fleet, Hubs, Policy, Settings, Vault) | `ls app/src/pages` |
| frontend build | **clean, 191 ms**, 32 packages | `npm ci && npm run build` |
| Tauri release build | **clean, 1 m 33 s**, 18.8 MB binary | `cargo build --release` |
| daemon web dashboard | **5,325 lines** — and it is what dp uses | `wc -l core/src/server/dashboard/index.html` |

Dependencies are current (React 19.2, Vite 8, TypeScript 6, Tauri 2.11). **"Update the app" is not a
dependency bump.** The frontend is healthy; the gap is in what it can reach.

### 2.2 The gap, per area

| daemon area | routes | app references | app can act? |
|---|---|---|---|
| scope — requests, grants, floor, standing, revoke | **12** | 2 | no |
| gates — verify, ratify | 2 | 0 | no |
| agents — inventory, ungovern, orchestrator connect | 3 | 0 | no |
| operator — gate-escalation, adjudicate, amnesty, alias | 5 | 2 (session only) | **sign-in only** |

### 2.3 The finding that makes Sprint 1 cheap

`DashboardSnapshot` — the payload the app **already fetches every tick** — carries
`pending_escalations` (`core/src/server/dashboard.rs:165`) and the scope-request fields beside it.
The app's own `DashboardSnapshot` interface (`app/src/lib/types.ts:117`) declares five fields and
**omits them**. `grep pending_escalations app/src` returns nothing.

So the owner's most consequential decision is already on the wire, already arriving in the app, and
is discarded before render. The daemon comment at that field says why it was put there:

> Five escalations opened against dp on 2026-08-01 and [nothing] to reach it.

---

## 3. Surfaces

Ordered by what the owner *does*, not by what is easy. Each surface states what it must show, what
it must do, and how acceptance is measured. "Measured" means a test or a transcript, never a claim.

### S1 — Decide

**The surface for acting on what is waiting.** Pending governance escalations and pending scope
requests, in one place, decided through the strong channel.

Must show, per pending item: what act was refused, which rule refused it, who asked, when it opened,
how long remains, and — for a scope request — the exact path and the asker's stated reason.

Must do:
- **approve / deny** an escalation via `POST /api/operator/gate-escalation`, never via the CLI path;
- carry the operator session established by Sprint A, and **refuse to offer the action when signed
  out** rather than failing at the daemon;
- require a reason on approve and not on deny — the daemon already enforces this asymmetry
  (`http.rs:5847`), and the UI must not invert it by making deny feel like the one needing defence;
- **rule a scope request** (`POST /api/scope/decide`) with the ruler's own words carried through,
  because a bare refusal reaches the asker as an unexplained no (the being appealed one, 2026-09-15).

Acceptance:
- a decision made in the app appears in the chain with `via` naming the strong channel, and a
  decision made on the CLI for the same shape appears with a different `via` — proving the app did
  not silently fall back;
- signed out, the decide action is **absent**, not merely disabled-looking;
- an approve with an empty reason is refused **in the app**, with the daemon's rule quoted.

**Non-goal:** deciding on behalf of anyone else. The app holds one operator's key.

### S2 — Who is governed here

**The surface that answers "what is running on this box, and is it under law?"**
`GET /api/agents` returns the three inventories (installed / adapter-available / actually governed)
plus gaps. Today the app cannot show any of it.

Must show: each agent, its governance state, and — critically — the **honest unknown**. The daemon
returns `status: UNKNOWN` with a reason when it could not look, precisely so that "could not look"
is never rendered as "nothing ungoverned". The app must preserve that distinction visually; a blank
list is the one rendering that is forbidden.

Must do: offer `ungovern` / `connect` only where the daemon says they apply.

Acceptance: with `agent-inventory` uninstalled, the app shows the reason string, not an empty list.
(HUB reproduced exactly this state on 2026-09-21: the daemon answered `UNKNOWN — agent-inventory is
not installed on this machine`, and an operator reading a naive UI would have concluded the box was
clean.)

**Depends on:** nothing. **Related:** hestia #1076 adds beings to this inventory; when it lands, a
being appears here with no app change, because the shape is the daemon's.

### S3 — Grant

**The authority half of S1.** Scope grants, the floor, standing scope, revocation, re-root.
Twelve routes, none reachable from the app.

Must show: what reach each member holds, which grants are live vs standing, and what was revoked.

Must do: grant, revoke, promote to standing, and adjust the floor — each as an operator act, each
witnessed.

Acceptance: a grant issued in the app is visible to the member's next gate call, and the chain entry
names the operator's LCT rather than the daemon's.

**Ordering note:** S3 after S1 deliberately. Deciding what is already asked is the owner's daily
act; issuing new authority is rarer and more dangerous, and should be built when the decide path has
been exercised.

### S4 — Evidence

Chain and trust views exist in skeleton (`Chain.tsx`, `trust/derivation`). This surface is
**explicitly deferred** and listed so it is not mistaken for missing: the dashboard serves it well,
and no decision depends on it.

---

## 4. Non-goals

- **Replacing the dashboard.** It is 5,325 lines and it works. The app earns each surface by being
  the only one that can prove an operator key; it does not earn them by duplication.
- **Remote operation.** `get_remote_dashboard` exists; deciding *remotely* is out of scope until a
  ruling says what a remote operator session means.
- **Deciding for another principal.** Decision 0014 separates actor from principal; this document
  assumes one operator, one key, one box.

---

## 5. Risks

1. **A convenient strong channel is still a strong channel.** Making approval two clicks away makes
   approving easier, and approve is the direction that needs defending. Mitigated by requiring the
   reason in the UI and showing the refused act in full — not by adding friction for its own sake.
2. **Rendering `UNKNOWN` as empty.** Named in S2 because it is the failure the daemon's own code
   comments were written to prevent, and a fresh UI is exactly where it reappears.
3. **The app drifting again.** 205 commits of daemon work landed between the app's last commit
   (2026-09-05) and this document. Each surface here is defined against a daemon route, so drift is
   detectable: a route that changes shape breaks a typed call, rather than silently rendering stale.
