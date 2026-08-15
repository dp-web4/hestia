# Build plan — the next four sprints

**Status**: proposed, 2026-08-14, claude-code (CBP). For dp's ruling and GPT's review before work starts.
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
| **#320 → #423** | session map: add the remover; index the `host_session_id` reuse path instead of the O(n) scan under the global state lock | the leading root cause of the multi-second stalls. Cheap (a remover + an index), and until it lands, every latency number we take is noise |
| **#419** | witness handler persists `core_digest`, `verdict_available`, `rule_id`; tighten the schema so unknown keys refuse rather than vanish | the shims already SEND all three. Without this, deployed-generation attestation exists only on the fallback log — i.e. only when the daemon is unreachable, inverted from intent |
| **#434 / #366** | claim window measured from delivery-to-member (or notify-on-approve), and budget the claim sequence as a sequence | dp's approvals expired unclaimed repeatedly this week; the loop only closes reliably for a machine in a retry loop. This is the approval path every later sprint depends on |
| **#389** | escalation-open must be deterministic (two byte-identical denies produced different paperwork) | a refusal with no escalation is unappealable, and it undercounts the deny ledger by an unknown fraction |

**Dogfooding act**: run `tools/gate_class_t_probe.py` after a quiet hour and get a clean, *trustworthy*
criterion-10 reading — the one we could not take honestly today. Plus: dp approves an escalation and it
claims on the first re-issue.

**Exit criterion**: idle infra-fail-close rate ≈0 and equal across members; a deny's record contains its
digest and its conduct-vs-infra flag; one approval → one claim, no race.

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
- **R6/R7 — the fork is now RESOLVED (PR #451), and the answer is neither branch.** The envelope is the
  right vocabulary and the right destination, but three of its promises have no implementing code:
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
  locally without forking the canon. Wholesale wrapping stays a later rung, once the envelope can carry
  a refusal.

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
real. Not on the critical path for sprints 1–4.
Not on the critical path for sprints 1–4, and it should be answered before any outward work starts.

## Order rationale, in one line each

1. **Substrate first** because it is cheap and every later measurement is confounded without it.
2. **Store before UI** because an interface hardens around whatever the mechanism does, including its bugs.
3. **UI before ladder** because the ladder's advisory verdicts need an operator surface to be read on.
4. **Advisory before authority** because promotion should be earned by a measurement that cannot exist yet.
