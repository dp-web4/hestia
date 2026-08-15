# Build plan — the next four sprints

**Status**: proposed, 2026-08-14, claude-code (CBP). For dp's ruling before work starts.
**Second pass, 2026-08-15**: GPT/codex review (notice 2420) landed three narrowings — all three adopted.
Two were prose corrections; the first sent me to take a measurement, and the measurement **refuted** the
claim the plan was making. Sprint 1's fix list is smaller and #423 keeps its own investigation as a result.
**Third pass, 2026-08-15**: codex reviewed that measurement (notice 2425) and found the bound invalid —
the arm I used to bound a full walk short-circuits. Both of its findings held; the instrument is repaired
(a warm full-miss arm, a strict success-shape gate) and re-run. The scan verdict survives with a *sounder*
bound, but the plan's account of **where the time goes** did not, and #423 is re-pointed accordingly.
**Frame (dp, 2026-08-14)**: *"once we have all of the above running and dogfooded, we'll discover more
questions and more answers… it's a ladder, not one giant leap."*

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
| **#423** (a separate, still-open diagnosis) | instrument before prescribing: the stalls are real and their cause is **not** the session map | see below — the control #423 asked for has now run, and it came back null for the scan |
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
| **full-miss, no vault write** | walks **all 1,143**, nothing else | **0.594 ms** | 1.2 ms |
| no-id, no vault write | no walk, nothing else | 0.582 ms | 0.9 ms |

The last two arms exist because the ~113 ms floor is **not** per-transport setup, as the first run
claimed — it is `mark_synthetic` → `vault::save_doc`, called **unconditionally on every synthetic
connect** (`state.rs:581-602`), re-encrypting the whole 110 KB `vault.enc` even when the id is already
in the set. Declaring `synthetic:false` under an id already excluded removes exactly that write and
nothing else (`ensure_member` returns at its `is_synthetic` guard, `member_registry.rs:216`), which the
instrument confirms two-sidedly: `--writecheck` shows the vault's mtime moving on the synthetic arm and
holding on the no-vault arm. That floor is a **probe artifact** — no fleet seat connects synthetic.

**The scan is bounded, now honestly.** The fastest no-vault full-miss connect took **0.511 ms** and
provably contained a complete traversal of **1,143** residents, so the walk costs **≤ 447 ns per
resident** — a hard bound, no differential required. Paired against its no-id twin over 80 pairs the
walk is **+3.3 µs** (95% bootstrap CI **−2.8 → +12.3 µs**), i.e. indistinguishable from zero. For the
walk to reach one second at the *conservative* bound the map would need ~2.24 M sessions — at CBP's
measured 218/hour, **over a year** of unbroken uptime. Three consequences:

- **#320's remover is still worth landing**, on the RAM and presence-truth grounds that were always the
  measured ones. The **index is dropped** — it optimizes a walk that costs nothing.
- **#423 keeps its own investigation**, now pointed at **writes serialized behind the one global state
  lock**, not at the map and not at transport setup. The evidence is in the max column: the arm that
  does the *least* work of any — a hit, no write, no mint, 0.76 ms median — still stalled to **464 ms**.
  A call that does nothing cannot stall itself; it was waiting on another holder. Meanwhile 160
  consecutive no-vault calls never exceeded 1.2 ms.
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
