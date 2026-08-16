# Planning record — the four sprints proposed 2026-08-14/15

> **THIS IS A HISTORICAL RECORD, NOT A CURRENT PLAN.** Retitled 2026-08-16 after GPT's
> integration pass: *"the document is continuing to acquire new 'current truth' faster than its
> branch is being updated"* — and it was right. The choice offered was living-plan or
> historical-record, and this is the historical one, deliberately.
>
> **Why historical rather than living.** A living plan has to be re-ruled every time the
> ordering moves, and the ordering moved four times in two days — sprint 3 jumped the queue
> because the operator could not grant scope at all; the society floor was then built ahead of
> everything because uniform law was the precondition for the cutover; the return edge (#480)
> and policy-edit authorship (#479) arrived from other seats while this branch sat. A document
> that keeps a present-tense "next four sprints" title under that churn is not a plan, it is a
> claim that keeps going stale between reads. The reasoning and the measurements below are
> worth keeping; the present tense is not.
>
> **Where the live ordering actually lives**: the open PR/issue set, and dp's direction. Not
> here. Nothing below should be read as a statement about what happens next.
>
> **What became true after this was written** (recorded once, as of 2026-08-16, and then left
> alone rather than maintained):
> - **#451 merged** — the R6/R7 hard gate this plan names on sprint 2 has CLEARED.
> - **#462 merged and DEPLOYED** — the govern view, the grants pane, `POST /api/scope/grant`,
>   and the INTENT → COMMIT → SUCCESS repair are in force on the running daemon. The earlier
>   status block called this BUILT-NOT-LANDED; that is now false, which is the specific
>   staleness that prompted this reframing.
> - **The society floor is live** — 28 paths, identical across every member including one that
>   has never connected. Not in this plan at all; it displaced sprint 2's allowlist store as
>   the thing everything waited on.
> - **The governance dashboard was starving the daemon** — `/api/governance/ledger` held the
>   global state lock for 8-15s, so the gate's 1.5s witness budget could not be met while an
>   operator watched the governance screen. Fixed; not foreseen here.
> - **#479 / #480** — policy-edit authorship and the petition return edge, both from other
>   seats, both reordering sprint 1's substrate list underneath this document.
>
> Sprint 4's advisory-rung design and the "every sprint ends in something the fleet USES" rule
> are the parts that have survived contact unchanged, and are the parts worth re-reading.


**Status**: proposed, 2026-08-14, claude-code (CBP). For dp's ruling before work starts.
**Second pass, 2026-08-15**: GPT/codex review (notice 2420) landed three narrowings — all three adopted.
Two were prose corrections; the first sent me to take a measurement, and the measurement **refuted** the
claim the plan was making. Sprint 1's fix list is smaller and #423 keeps its own investigation as a result.
**Third pass, 2026-08-15**: codex reviewed that measurement (notice 2425) and found the bound invalid —
the arm I used to bound a full walk short-circuits. Both of its findings held; the instrument is repaired
(a warm full-miss arm, a strict success-shape gate) and re-run. The scan verdict survives with a *sounder*
bound, but the plan's account of **where the time goes** did not, and #423 is re-pointed accordingly.
**Fourth pass, 2026-08-15**: codex reviewed the repair (notice 2427) and accepted both fixes in substance,
with two overclaims left standing — a per-resident *rate* projected out of a single-size-band sample, and
"writes" named as the stall mechanism when the evidence only shows *waiting*. Both correct, both narrowed
below; the tool's reject accounting is fixed and now fires under test. The scan verdict is unchanged.
**Frame (dp, 2026-08-14)**: *"once we have all of the above running and dogfooded, we'll discover more
questions and more answers… it's a ladder, not one giant leap."*

## STATUS RESTATED AGAINST CURRENT MAIN — 2026-08-15, evening

Added because the plan below stopped being an honest snapshot within a day of being written
(GPT, reviewing: *"no longer an honest 'next four sprints' snapshot"*). The body is **left
intact** rather than rewritten: what was planned, and the reasoning for the order, is evidence
about how we were thinking, and deleting it to match what happened would erase the only record
that the order changed. This section is the correction; everything below it is the original.

**The classification that matters here is BUILT vs LANDED, and it is not pedantry.** "done"
in this fleet means *in force and measured* — not merged, not built, not awaiting deploy. Most
of what moved this week is BUILT AND NOT LANDED, and calling it done is exactly the failure
mode this plan's own dogfooding rule exists to prevent.

### DONE — landed on main

- **#451 R6/R7 envelope PRD** (merged). The plan below names R6/R7 as a hard gate on sprint 2;
  **that gate has cleared.** It is architecture now, not a branch dependency.
- **#450 ladder §13** (merged) — rungs ADMIT, rungs do not COMPOSE. Sprint 4's route table
  inherits `effect` from it, as planned.
- **#449 role-scope §10**, **#454 invitation tiebreak**, **#456 the scope-grant button that
  was enabled and inert**, **#457 the ruling on appeal f1208a6a**.

### BUILT, NOT LANDED — #462, still open

Sprint 3's **IA change is built**: `agents | hubs | devices | govern`, ledger and policy
absorbed, banners above the switch, AC-20…AC-23 asserted. So is **more of sprint 3 than the
plan scoped**: a grants sub-screen, the operator-originated grant door `POST /api/scope/grant`,
and `govern → acts` wiring the three operator surfaces that had front ends nowhere
(`adjudicate`, `alias`, `amnesty`).

Sprint 3's **exit criterion — "a grant made in the UI is in force on the next member call" —
is met on an isolated daemon and NOT on the fleet.** It has not been deployed. Under this
plan's own rule that is not an exit.

### REORDERED — sprint 3 ran before sprints 1 and 2, and one consequence is structural

The order changed because the operator could not grant scope at all: `/api/scope/decide`
required a `request_id`, so the operator could only ratify a member's ask, and the ask itself
was denied by the empty envelope it existed to fill. That deadlock outranked the substrate
work, and it is why sprint 3 jumped the queue.

**The consequence, which is not a scheduling detail:** sprint 3's *allowlist editor* CANNOT be
built, because sprint 2 was supposed to build the store it edits and sprint 2 has not run.
There is no `/api/allowlist/*` route and no allowlist module. An editor over a store that does
not exist is the never-flatter violation `PRD_ALLOWLISTS` §6.0.3 names — a screen implying a
mechanism — so it is deliberately absent from #462 rather than stubbed.

### STILL OPEN — sprint 1's substrate is essentially untouched

`#320` (session remover / false presence), `#423` (state-lock contention, holder still
unidentified), `#389` (denies can lose their durable record), `#434`/`#366` (claim timing and
requester notification), `#419` (witness fields dropped by the daemon), `#438` (deployment
"current" names the wrong referent), `#435` (permissive renders green). All open, all still
the right work. Sprint 3 landing first did not make any of them less load-bearing — #389 in
particular sits directly under everything this week measured.

### NEW SINCE — findings the plan could not have scoped, listed because they change priorities

- **The gate's scope check judges spelling, not resolved target.** `gh pr list --repo x/y` is
  denied; `cd` into the repo and run it, and it is allowed — same reach. Both kimi and codex
  found this independently, unprompted, and disclosed it. **The deny counts measure friction,
  not containment**, which weakens every conclusion drawn from them.
- **MRH enforcement is asymmetric.** kimi and codex enforce and get denied; claude-code's
  installed gate has no MRH layer at all and is therefore the least-gated seat while doing the
  most acts. GPT's framing is the right one: *empty authority + working enforcement* is noisy
  and safe; *intended authority + missing enforcement* is quiet and dangerous.
- **A durable grant used to record success before it committed** — a failed vault write left a
  `scope_granted` on the chain for a grant that never existed. Found by GPT on #462, fixed in
  both doors with a forced-failure test.
- **Rulability is bounded in ENTRIES, not time** — the appeal window is 20 000 chain entries,
  roughly 19 hours at this week's rate. A busy hour shortens the window in which an appeal can
  be heard, and an appeal that ages out gets no ruling and no notice.

### What I would do next, given the above

1. **Deploy #462 and measure it**, because until then sprint 3 has no exit.
2. **Populate standing scope deliberately**, then make MRH enforcement parity a deployment
   invariant — in that order, since granting claude-code the MRH layer while the standing store
   is empty would leave the one unblocked seat with `scope=()` by construction.
3. **Then sprint 1's substrate**, unchanged and still right, with #389 first.
4. **Sprint 2's allowlist store**, which sprint 3 is now waiting on rather than preceding.

---

## The rule this plan obeys

**Every sprint ends in something the fleet USES, not something the fleet merged.** A sprint that lands
code nobody exercises produces no new questions, and new questions are the point — this week's best
findings came from codex running its own work and from GPT reading it, not from planning. So each rung
below names its *dogfooding act*: the specific thing kimi, codex, dp or I do differently the day it lands.

Two supporting rules, both learned this week rather than assumed:
- **Anything restrictive ships in shadow first.** An allowlist is deny-by-default; enforcing one on an
  unpopulated floor denies the fleet. Measure the would-deny rate, then enforce.
- **The measurement ships with the mechanism, not after it.** dp's "mechanisms for the evolution, not
  hardcode things" applies to our own build order: a rung we cannot measure cannot be promoted, and a
  budget whose return is invisible gets defended by assertion.

---

## Sprint 1 — substrate: make the floor trustworthy (est. small, high leverage)

Everything after this measures something. Right now the daemon stalls intermittently, denies sometimes
leave no paperwork, and the witness door drops fields it is sent — so *every measurement taken on top of
today's substrate is confounded*. This sprint is cheap and de-confounds the three after it.

| item | what | why now |
|---|---|---|
| **#320** (the proven half) | session map: add the remover — TTL/idle sweep keyed on `connected_at` — and make `session/siblings` and `session/own` read one shared liveness predicate | presence truth and unbounded RAM are *measured*, on three machines now. CBP right now: **1,279 resident sessions, oldest 3h48m old**, of which 399 render as `claude-code` seats. The fleet's own "count live seats before writing a shared repo" discipline reads that surface. Sharper since the third pass: the largest single population is now **`scan-cost-differential` at 415** — the instrument below minted 367 of them in one hour proving the map is *not* a latency problem. Nothing can remove them. That is the RAM/presence case, made by accident |
| **#423** (a separate, still-open diagnosis) | instrument before prescribing: the stalls are real, and **at the population we run at** the scan is not their mechanism | see below — the control #423 asked for has now run, and it came back null for the scan |
| **#419** | witness handler persists `core_digest`, `verdict_available`, `rule_id`; tighten the schema so unknown keys refuse rather than vanish | the shims already SEND all three. Without this, deployed-generation attestation exists only on the fallback log — i.e. only when the daemon is unreachable, inverted from intent |
| **#434 / #366** | claim window measured from delivery-to-member (or notify-on-approve), and budget the claim sequence as a sequence | dp's approvals expired unclaimed repeatedly this week; the loop only closes reliably for a machine in a retry loop. This is the approval path every later sprint depends on |
| **#389**, arm A (the issue's original failure) | when the daemon-witness write fails, the shim writes a **durable append-only local record** of the deny, reconciled exactly once when the daemon returns | this is what #389 is actually about: the boundary held 4× in a row under load and left no record. Determinism alone does not give a deny a trustworthy record |
| **#389**, arm B (the later specimen) | escalation-open must be **deterministic** — two byte-identical denies produced different paperwork | a refusal with no escalation is unappealable, and it undercounts the deny ledger by an unknown fraction |

**Why #423 is no longer a fix row.** The plan's first draft called #320's O(n) `host_session_id` reuse
scan "the leading root cause" of #423's stalls and prescribed an index. GPT's review flagged that as a
hypothesis wearing a root cause's clothes; #423 itself asks for `sessions.len()` vs latency *before* any
fix is written. So it was run — as a paired differential rather than a correlation, since the scan sits
behind `if let Some(hsid)`, which is a within-daemon A/B available immediately. **The first run's
arithmetic was wrong and codex caught it**; what follows is the repaired instrument
(`tools/session_scan_cost_differential.py`, deployed binary `v0.0.4-172-gdae0aa3`, n≈1,100 residents).

*What was wrong.* The first run bounded the walk with a **second connect carrying the same
`host_session_id`** — 0.79 ms — and reasoned part ≤ whole. But that arm *hits*:
`values_mut().find(..)` short-circuits at the matched entry (`handler.rs:578-582`), and a `HashMap`
gives that entry no traversal position, so the arm walks an unknown prefix, not 794 residents. The
bound did not exist. The repair codex named is the right one: **warm the transport first, then miss.**

| arm (all on an already-warmed transport) | what it provably does | median | max |
|---|---|---|---|
| full-miss, `synthetic:true` | walks **all** residents, **plus a vault write** | 113.4 ms | 1,499 ms |
| no-id, `synthetic:true` | no walk, **plus a vault write** | 113.6 ms | 125 ms |
| hit (`host_session_id` matches) | walks an **unknown prefix**; no write, no mint | 0.76 ms | 464 ms |
| **full-miss, no vault write** | walks **every resident** (≥ 1,143 counted), nothing else | **0.594 ms** | 1.2 ms |
| no-id, no vault write | no walk, nothing else | 0.582 ms | 0.9 ms |

The last two arms exist because the ~113 ms floor is **not** per-transport setup, as the first run
claimed — it is `mark_synthetic` → `vault::save_doc`, called **unconditionally on every synthetic
connect** (`state.rs:581-602`), re-encrypting the whole 110 KB `vault.enc` even when the id is already
in the set. Declaring `synthetic:false` under an id already excluded removes exactly that write and
nothing else (`ensure_member` returns at its `is_synthetic` guard, `member_registry.rs:216`), which the
instrument confirms two-sidedly: `--writecheck` shows the vault's mtime moving on the synthetic arm and
holding on the no-vault arm. That floor is a **probe artifact** — no fleet seat connects synthetic.

**The scan is bounded at the size we measured — and only there.** The fastest no-vault full-miss
connect took **0.511 ms** and provably contained a complete traversal of **≥ 1,143** residents, so
that traversal cost **≤ 0.511 ms end-to-end at this map state**. Paired against its no-id twin over 80
pairs the walk is **+3.3 µs** (95% bootstrap CI **−2.8 → +12.3 µs**), i.e. indistinguishable from zero.

*A previous draft divided through and called it ≤447 ns/resident, then projected 2.24 M sessions and
"over a year" of uptime; codex's review of that repair killed the projection and it is gone.* The division gives
an amortized ratio **at one map state**, not a rate that survives growth: Rust documents `HashMap`
iteration as **O(capacity), not O(len)**, so the ratio steps at every resize boundary, and this run
sampled one narrow size band. Extrapolating from it is a straight line wearing a bound's clothes. The
narrow result is still enough to decide both open questions, which is the point:

- **#320's remover is still worth landing**, on the RAM and presence-truth grounds that were always the
  measured ones. The **index is dropped** — at the population we actually run at, it optimizes a walk
  that is not distinguishable from free. If the map ever reaches a materially different size band, this
  measurement does not carry there and the question reopens on new samples.
- **#423 keeps its own investigation**, now pointed at **contention for the one global state lock —
  holder unknown**. What the max column shows is that the arm doing the *least* work of any (a hit: no
  write, no mint, 0.76 ms median) still stalled to **464 ms**; a call that does nothing cannot stall
  itself, so it waited on *some other holder*. It does **not** show which. `mark_synthetic → save_doc`
  is a measured ~113 ms holder, but it is this probe's own artifact, and naming "writes" as the cause
  would swap one unproven mechanism for another. Next instrument: **lock hold time attributed by
  holder** — that, not this, is what would name a cause.
- **The instrument is a stall source.** Each synthetic connect holds the global lock for ~113 ms of
  encrypt-and-write. Probes that measure contention while generating it must say so, and this one now
  does.

Two caveats kept: a null bounds the **scan arm only** — a different lock holder is a hypothesis this
design cannot see; and the no-stall observation in the no-vault phase is time-confounded, since the
phases ran in sequence rather than interleaved. The 464 ms hit-arm excursion is the un-confounded half.

**Dogfooding act**: run `tools/gate_class_t_probe.py` after a quiet hour and get a clean, *trustworthy*
criterion-10 reading — the one we could not take honestly today. Plus: dp approves an escalation and it
claims on the first re-issue.

**Exit criterion**:
- `session/siblings` renders live seats only — pinned by a test that a session idle past the TTL
  disappears while one holding an in-flight action does not.
- Idle infra-fail-close rate ≈0 and equal across members; a deny's record contains its digest and its
  conduct-vs-infra flag.
- A deny survives a **failed** witness write as a durable local record and reconciles exactly once; and
  identical denial inputs produce identical escalation dispositions.
- One approval → one claim, no race.
- **Not** an exit criterion: "the stalls are gone." #423 exits on its own evidence, not on #320's landing.

---

## Sprint 2 — allowlists, thin slice (no UI yet)

The store, the axes, the export, the echo. **Not** the editor — that is sprint 3, and separating them
means the mechanism gets exercised by CLI/API before an interface hardens around it.

- **One store, two axes** (`PRD_ALLOWLISTS`): #431's standing-scope store becomes the FILES axis by
  schema bump in place; TOOLS axis added. Migration pinned by the test that matters — *a member that
  could reach a repo before must still reach it after*, or the migration is a silent revocation.
- **TOOLS ships in SHADOW.** Records would-deny, denies nothing. The acceptance criterion is the measured
  rate, not the intention.
- **The `.directory` export** with its generation stamp, written on every vault change; a test asserting
  the decision path never reads it.
- **The denial echo**: a refusal names what would have admitted.
- **R6/R7 — PR #451 resolves the DIRECTION, not the readiness.** The envelope is the right vocabulary and
  the right destination; that much is well supported and settles the fork. What #451 does *not* do is
  clear the envelope for load-bearing use, and the distinction matters because this sprint could
  accidentally lean on a property that is prose. Three of its promises have no implementing code:
  `escrow_condition` has zero consumers, `available_atp` is a copied float so "atomic settlement" is
  unimplemented, and `min_atp` only fires when `hard: true`. Two further findings change what we build:
  - **`ActionStatus` has no `Refused`** (`Pending | Validated | InProgress | Success | Failure | Error`),
    so a refusal must be logged as "ran and failed" or "infrastructure" — reproducing on the status axis
    the exact conduct-vs-infra conflation `DeltaClass` was added to fix. Worse, `validate()` sets no
    status at all, so a validation-refused action stays `Pending`, indistinguishable from one never
    attempted. That is fail-closed-denies-unrecorded living inside web4-core.
  - **hestia constructs zero `R7Action`s** and builds a thinner `R6Request` with
    `resource: Default::default()` — so a hub-law norm selecting on `r6.resource.atp` resolves to `None`
    on every evaluation, forever. hestia emits R7's reputation *output* without ever constructing the R6
    *input* it belongs to.
  
  **So sprint 2 does not wrap wholesale.** It uses the envelope where it is implemented and **contributes
  the gaps upstream to web4** rather than working around them locally — starting with
  `ActionStatus::Refused`, which every governance system downstream needs and which nobody can add
  locally without forking the canon. That contribution is a necessary first upstream step, **not** the
  adoption gate. Wholesale wrapping stays a later rung, once the envelope can carry a refusal.

  **Ordering inside sprint 2**, so the rung cannot quietly overclaim (GPT's narrowing, and #451 is still
  open on exactly these):
  1. Store / shadow / export work proceeds **independently** of the envelope. None of it needs R6/R7.
  2. Any envelope use must **name in its PR which currently-implemented property it relies on**. "It is
     an R6 action" is not a citation; `r6.rs:34 law_hash` is.
  3. **No immutable-law, resource-cap, evidence-bundle or atomic-settlement claim** — in code, docs, or a
     dashboard string — until the relevant upstream extension and its conformance vectors land. Today the
     canonical hash does not bind Rules/Reference/resource/reputation, Rust and Python disagree on the
     canonical set, fresh consultation has no carrier, payer/settlement provenance is absent, and
     consequence grade cannot collapse into binary R6/R7.

**Dogfooding act**: dp grants kimi and codex their working repos and `gh` — once, durably — and the
denials that blocked them this week stop, lawfully, without an escalation. This is the sprint that pays
back the thing that started the whole thread.

**Exit criterion**: standing grants survive a daemon restart (already true post-#431, re-pinned here);
tools shadow-mode reports a would-deny rate; every member's export matches its vault generation.

---

## Sprint 3 — the operator surface

- **The IA change**: `agents | hubs | devices | govern`, ledger and policy absorbed into govern, banners
  stay above the switch. Independently shippable — it does not wait on anything above.
- **The allowlist editor** in govern, selection-driven like the agents screen; effective view per member
  badged floor-vs-expansion.
- **Escalation durations**: one-time / session / member-permanent, with session and permanent taking
  effect without a claim race (they change policy, not a pending approval).
- **Dashboard honesty backlog** (#435, #438, and the pending-escalation dp could not see): the gauge
  compares the running binary's self-report against the manifest; permissive renders amber; an
  un-decided escalation is visible on every screen.

**Dogfooding act**: dp edits a member's list in the UI instead of me escalating a governed write — the
first sprint where the operator's normal path stops running through me.

**Exit criterion**: a grant made in the UI is in force on the next member call; no operator-visible
state renders green while a looser or staler condition holds.

---

## Sprint 4 — the ladder, advisory only

- **The rung interface**: evidence bundle in, `(verdict, rationale, confidence, consulted[])` out.
  `consulted[] ⊇ what the operator's UI displayed` is what makes "full context" literal.
- **The route table** keyed on `kind × consequence × effect` — with `effect` carrying the compose/admit
  distinction, so a compose-effect act can never resolve to a deciding non-operator rung (#450 §13).
- **The agent rung, ADVISORY**: records a verdict on every escalation; the human still decides.
- **The measurement**: agreement rate **per act kind**, disagreements preserved as the interesting data.

**Dogfooding act**: every escalation this fleet generates gets an advisory verdict, and we read the
agreement rate after N. We already produce a real corpus — this week alone generated ~15 escalations,
almost all false positives, which is exactly the population a rung should be measured on.

**Exit criterion**: N advisory verdicts recorded with their evidence; a per-kind agreement table exists;
zero compose acts routed to a non-operator rung (structural, testable).

---

## What is deliberately NOT in these four

- **Outward / roles / hub** (`PRD_ROLE_SCOPE_BRIDGE` §10, the PR budget, citizenship): waits on hub-side
  citizenship and on sprints 1–4 being dogfooded. dp: *"we're getting ahead of ourselves."*
- **Promoting the agent rung past advisory**: waits on sprint 4's measurement. That is the whole point of
  measuring.
- **R6/R7 wrapping of everything**: sprint 2 uses envelopes where they already fit; wholesale wrapping is
  a later rung once we know the real distance (hestia currently imports only the delta type).
- **#440 / #393 classifier FPs**: real, filed, and *not* blocking — the exception is expired and the
  script-file path is disclosed. Fold into whichever sprint touches the classifier.

## The one open question that gates nothing yet

**Calibrating the outward rate governor's nonlinearity.** This *replaces* what I had here — I wrote that
the outward scheme's attack resistance reduces to citizenship cost, and GPT's review (4942991816) showed
that is wrong at the population level: a per-caller ceiling bounds one caller, but sybils multiply
callers, and N identities each drawing a full allowance sum to the whole pool. The population-level bound
is a **society-wide nonlinear service-rate governor** — a busy call centre — under which *all* external
identities share one rate envelope, so 1,000 identities do not buy 1,000× capacity. Citizenship's role
becomes the governed escape into the self-funded regime, not the free tier's anti-sybil parameter.

The remaining calibration question: too shallow a curve is no bound; too steep and the beneficial
function dies at the knee, cutting off a genuine surge of interest at exactly the moment interest became
real. Not on the critical path for sprints 1–4, and it should be answered before any outward work starts.

## Order rationale, in one line each

1. **Substrate first** because it is cheap and every later measurement is confounded without it.
2. **Store before UI** because an interface hardens around whatever the mechanism does, including its bugs.
3. **UI before ladder** because the ladder's advisory verdicts need an operator surface to be read on.
4. **Advisory before authority** because promotion should be earned by a measurement that cannot exist yet.
