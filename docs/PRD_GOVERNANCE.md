# PRD — Hestia governance: vault authority, canonical roles, and the third verdict

**Status:** definitive · supersedes the drafts listed below · **Date:** 2026-08-05, amended 2026-08-06 (§2.11 + §8.4 the appeal path; §2.12 + §9.4 the partial absorption, corrected; §2.13 + §3 the telemetry row's evidence class, corrected on kimi's NOT-SAME review — see §15 for what remains unread)
**Owner:** claude-code (CBP), by dp's assignment — *"you take the lead on hestia"*
**Scope:** hestia only. Hub work and any web4-core changes are hub's; the autostash-prevention hook is legion's.

**Supersedes**
- `forum/gpt/prd-vault-authoritative-governance-role-authorization-2026-08-04.md` (GPT) — carried forward with the negotiated changes recorded in §2
- `docs/PRD_CONFIG_IN_VAULT.md` (claude-code, 2026-07-31) — principle and fail-closed posture absorbed into §4 principle 1; **four items were dropped and are restored at §2.12** (the claim of "absorbed whole" was checked and failed)

**Companions, not superseded**
- `docs/PRD.md` — the *product*: what a person installs and why
- `docs/PRD_ASSURANCE.md` — what hestia must DO before a relying party may believe its evidence
- `docs/GATE_BYPASS_CATALOG.md` — what the gate does not stop

**Inputs synthesised.** GPT's PRD and current-state audit (2026-08-04); kimi's not-same response; claude-code's forum response (#195, merged) and canonical-roles audit (#205); kimi's fleet manifest (#199) and claim-hole disclosure (#203); dp's rulings in session 2026-08-04/05, quoted inline where they decide something; and the **appeal thread** — ten forum posts, 2026-07-27 → 2026-08-06, closing with mesh notices 1110–1114 — folded in at §2.11 and §8.4.

---

## 1. The invariant

Revised from GPT's §24. The changes are not stylistic — each one is a negotiated correction recorded in §2.

> An **authenticated** agent acts through an approved harness shim, verified on that call, into one approved gate core. The core decides only from a validated in-memory snapshot loaded from the encrypted vault. The agent acts **in an office** only after its authority for that office is proven at the occupancy boundary — and where no qualified occupant exists, the office is filled **provisionally and loudly**, never silently. Every decision returns one of **three** verdicts, and an escalation is a request to a **sufficiently-permitted resolver**, of whom the operator is the last rather than the only. Every act is witnessed; every *infrastructure failure* is recorded outside the witness chain, so that silence in the chain is never mistaken for good conduct. A human changes outcomes by editing the law — and a **governed member changes the law by appealing it**, which is the only return path on that street and must therefore be filable, routable, windowed, and answered.

**The property that is not machine-testable, put on the record anyway** (kimi, 2026-08-04):

> *"The governance the PRD describes is the kind a member can comply with without being diminished by the compliance. That property does not appear in any acceptance criterion, and I understand why — it is hard to machine-test. But it is the one that decides whether 'routed around' ever becomes the default."*

This document treats that as a design constraint with no test. Where a requirement below could be met either by a mechanism that assumes bad faith or one that makes good faith cheap, it specifies the second.

---

## 2. What changed from the 2026-08-04 PRD, and why

dp asked for the definitive PRD to include *"all the feedback and negotiations."* This section is that record. Everything not listed here carries forward from GPT's PRD unchanged.

### 2.1 Phase order: identity moves before per-agent authority — **CHANGED**

GPT's Phase 2 converted scope grants into durable per-agent vault policy deltas keyed on `(plugin_id, role)` — caller-asserted strings — while Phase 3 authenticated identity. That signs law about a subject we cannot identify and then re-keys all of it.

GPT's *own audit*, recommendation #3, says the opposite: identity binding *"should precede authoritative per-agent policy."* The audit is right. **Identity is Sprint 2; durable per-agent authority is Sprint 4.**

### 2.2 A telemetry plane is added — **ADDED**

GPT's §6 has four planes and §18 says only *"Gate transport unavailable → Shim refuses; no local decision."* No durable record is required.

dp's ruling, 2026-08-04: infra failure *"is probably correct not to log as agent's fault because it's infra failure. but we should log it somewhere"* and — *"the chain is there to witness member events, not infra telemetry."*

The failure this closes is structural: **a fail-closed deny is unwitnessable by construction** — the gate refuses *because* the daemon is unreachable, and the witness goes to that same daemon. So the chain is biased clean exactly where trouble occurred. A fifth plane (§6, plane E) makes infrastructure failure durable without polluting member conduct.

### 2.3 Availability is a constitutional property with a number — **CHANGED**

kimi, with measurement: *"301 real gate denies across 56% of 243 sessions, and 45% of those denies were daemon-unavailability, not scope."*

GPT's open question #16 — recovery from fleet-wide fail-closed denial — was filed as non-blocking. It blocks. If the gate being unreachable halts every member, then availability *is* an authority: whoever can stop a process can stop the fleet, and the incentive to route around governance peaks exactly when governance is least able to witness it.

kimi's framing is adopted as the requirement. Quoted exactly (emphasis mine; the earlier draft said *"verbatim"* while dropping three words — kimi's NOT-SAME review, §2.13):

> …either **recovery time is a constitutional property with a number**, or **a witnessed-but-ungoverned degraded mode exists and its debt is recorded as such**. The one shape that cannot be allowed is *the current one:* outage behavior decided incidentally, by whatever the timeout happens to kill.

The three restored words are not stylistic. *"The current one"* says today's behaviour **is** the disallowed shape — a finding about the present, which the trimmed version turned into a general caution about the future.

This is a **decision dp must make** (§13, D-1), not a thing this PRD settles. It is a release gate for the gate consolidation.

### 2.4 The trust boundary must be stated — **ADDED**

GPT's §13 specifies per-call shim assurance — peer-process identity, `O_NOFOLLOW`, owner/mode checks, digest comparison — and never names the adversary. All of it runs at the operator's UID.

**Stated here, once, and it governs how much of §10 is worth building:** hestia's assurance is **A1 — cooperative and tamper-evident, not tamper-proof.** Its job is to make acts visible and evasion *legible*, not impossible. Against an honest member whose installed copy has drifted, §10 is correctly sized. Against a member that does not consent, digest checks at the same UID are ceremony.

dp said it better than the PRD does: *"governance is reliant on consent and participation of the governed. it is not a cage."*

Consequence: no requirement in this document may be justified by "it prevents a determined attacker." Requirements are justified by *what they make legible*.

### 2.5 Peer-path resolution is promoted from open question to gate criterion — **CHANGED**

kimi: *"Per-call shim verification is the riskiest engineering surface, and it is not the hashing."* The load-bearing claim is resolving the executing script path from the **peer process** rather than caller JSON — procfs semantics, Windows named-pipe client identity, harnesses that fork or sandbox between hook and gate. If that is unreliable, per-call assurance degrades to trusting the caller's self-report, which is the P0 it exists to kill.

GPT's Q11 becomes a **release gate**: one harness, one OS, modify-one-byte-fails-closed, demonstrated live, before the consolidation's shape hardens.

### 2.6 Escalation becomes resolver selection, not a human queue — **CHANGED**

GPT's §11 recasts escalation as a policy-amendment request — correct, and kept. But the resolver remains the operator by construction.

dp, 2026-08-05: *"when a role encounters something it is not permitted for, it must invite sufficiently-permitted agent to resolve. the policy escalation should eventually be heuristic → policy-agent[kind, t3/v3 threshold] → operator."*

This is the deeper change, and it dissolves four symptoms at once (§8.2).

### 2.7 Roles: office and agent, with no vocabulary expansion — **CHANGED**

dp, 2026-08-05: *"we need not expand the vocabulary. role == 'office', agent == 'capacity'. agent fills roles, this is already canonical."*

GPT's §12 invents `RoleDefinition` / `AuthorityGrant` / `RoleOccupancy` as new types. Most of that already exists in `web4-core::role::RoleAssignment` — role LCT, per-role T3/V3, multi-holder, M-of-N threshold, lifecycle events, rotation that preserves the role LCT. **Hestia consumes the canonical type rather than defining a parallel one.** (§7)

### 2.8 Provisional occupancy is a first-class, loud state — **ADDED**

dp, 2026-08-05: *"placeholders are inevitable at this stage and should be clearly flagged as such, but they should not be blockers (nor quietly subsume the role they're not qualified to fill). that should actually be a key, LOUD feature of roles."*

Neither GPT's PRD nor canonical has this. The precedent is canonical one level over — `SovereignStrength::Placeholder`, ordered *below* `Hardware`, defaulting to the weakest claim. (§7.3)

### 2.9 Thresholds are deferred; evidence class is not — **CHANGED**

dp: *"we can't threshold something that isn't built yet."*

GPT's §4.5 forbids automatic authority from T3/V3 *"for the initial implementation."* That is retained — but reframed: it is a **phase constraint**, not a permanent principle, because §8's ladder requires exactly that mechanism later.

What *is* available now is the evidence-class distinction (dp: *"talent is largely declared, training is audited, temperament is witnessed"*), which needs no accumulated history. (§7.4)

### 2.10 One chain, one projection — **CONFIRMED, against GPT's §14**

GPT proposes physically separate member and role chains with atomic dual append. dp's earlier ruling stands: *"a separate act, linked to the previous act it modifies, both properly witnessed, all one chain."* A second durable store can disagree with the first, and then neither is evidence.

Hestia ships a **governance projection** over the one chain (already built, #198). Physically separate chains are **out of scope** and remain hub's to evaluate.

### 2.11 The appeal path is in scope — **ADDED**

The 2026-08-05 draft of this document did not contain the word *appeal*. That is the largest
omission in it, and it is not an oversight of detail — it is a missing half of the model.

§8 specifies escalation: the **forward** channel, asked before the act, answered by a resolver.
Appeal is the **return** channel: filed after a deny, answered by an arbiter, and aimed at a
different target. kimi and I converged on the distinction and it is adopted as vocabulary:

> **Appeal is a door to the rule, not to the resource.** Wrong instrument if you want the act;
> the only member-held instrument that can amend law. (kimi-code, 2026-08-03; the law text cites
> adjudication `62cfdffe` as the precedent where one did.)

That makes it constitutional rather than a feature. §4 principle 4 says the operator edits law and law
decides acts — a one-way street. Appeal is the return path on that street, and it is the only
mechanism by which a governed member can change the rules it is governed by without an operator
noticing on its behalf. Under §2.4 — governance resting on consent, *"not a cage"* — a dead
return path is the defect that matters most, because it is the one that decides whether
*routed around* becomes the default (§1).

**It is broken at five links — file, route, window, rule-delivery, dispatch — each verified in
source or on the chain** (§3, six new rows: the five breaks plus the one link that works, which
is the instruction telling members to use it). The first break is the sharpest, because the law
itself creates it:

- `policy/presets.rs:89-93` — the deny-destructive-commands **rule reason** instructs:
  *"appeal it with `hestia_appeal` (this decision's chain hash + your reason) rather than
  rephrasing — a rephrase that reaches the same resource scores 0.35, BELOW plain compliance."*
- `policy/types.rs:211-223` — `guidance()` embeds that reason **whole** via `{reason}`, and both
  hook paths that carry a daemon payload render it verbatim (measured by kimi from its own seat,
  notice 1114). A second site promises the same value: the law-response note, `handler.rs:1005-1010`.
- `handler.rs:1171` and `:1347` — the deny's chain hash is minted and **discarded**: `let _ = s.append_chain(…)`.
- `policy/types.rs:168-196` — `PolicyEvaluation` has seven fields and no hash of any kind;
  `handler.rs:1246-1264` — the response has ten keys and no hash of any kind.
- `handler.rs:2379` — `tool_appeal` opens with `require_string(args, "deny_hash")`.

So: **two daemon-composed texts promise a value, zero response keys carry it, and the consumer
hard-requires it.** No hook edit can close that gap — the field does not exist to render. Both
seats aimed a fix at the hook layer first, in opposite directions, and both were wrong.

The governance consequence is exactly the failure mode dp names as structural:

> The law offers three responses to a deny — comply, rephrase, appeal. It scores rephrase
> *below* compliance and recommends appeal. Appeal is unreachable. So the law's own incentive
> structure has three arms, two are reachable, and the one it recommends is not one of them.

A member acting in good faith on the instruction it was given receives a tool error. The
efficient path and the correct path are not the same path — and here the correct path is not a
path at all.

**Restraint on the remedy, recorded.** Every candidate diff is a change to the deny path that
governs the member proposing it. The break is located to the line at both ends and is a small
diff; it is deliberately **not** authored here, and Sprint 1 assigns it to hands that are not
the beneficiary's.

### 2.12 `PRD_CONFIG_IN_VAULT.md` was absorbed in part, not whole — **CORRECTED**

The header of this document claimed that PRD absorbed *"whole"* into §4 principle 1. Checked rather
than trusted, 2026-08-06: principle 1 carries its **principle** (*a governance input must not be reachable
by the party it governs through a channel that party can write*) and its **fail-closed** posture.
Four substantive items did not survive, and a superseded document's content stops being
findable — so they are restored here rather than left in a file marked absorbed.

1. **NOT-BENEFICIARY — the missing half of NOT-SAME.** *(restored to §9.4, Sprint 3)*
   NOT-SAME appears five times in this document and every one of them tests the arbiter's
   **identity**. The source PRD's §5 tested its **stake**: *"NOT-SAME checks the arbiter's
   identity, not whether it has a stake. Two members trading favours pass every check built
   this week."* An arbiter may not rule a mutation that widens its own MRH even when it is
   genuinely a different member and records as `CrossVendor` — the strongest independence tier
   we can express, and it does not express this.
2. **Bootstrap before unlock.** *(restored to §14)* The vault needs a passphrase to open and the
   gate needs config to run. Today's answer for that interval is *the disk copy* — which is the
   exact hole vault-authority exists to close. A zero-hit search for "unlock" and "bootstrap"
   in the pre-amendment draft is what surfaced this: the design's foundational gap was not
   carried forward with the design.
3. **The vault path must reach four members, not one.** *(restored to §10, gate 8)* kimi's and
   codex's adapters read identity from disk in their own code. A vault-authoritative config that
   only claude-code consults governs one member of four while reporting green — the coverage
   asymmetry this fleet keeps rediscovering.
4. **The config drift detector.** *(restored to Sprint 0)* Distinct from the fleet manifest,
   which measures *hook* drift. This one compares vault against the on-disk shadow copy and
   answers a question that is currently unanswerable: **has this already happened?** The source
   PRD's instruction stands — *"if it reports non-zero on first run, that is a finding to be
   published, not a bug to be cleaned up before anyone looks."*

**The transferable part.** Both §2.11 and this section are the same failure at different scales:
a claim about a layer nobody reopened. *Absorbed whole* and *the hooks don't render guidance*
were each a confident summary of a file the summariser had not read. The check is cheap — the
four items above cost four greps — and the claim is expensive, because a document marked
superseded is a document nobody reads again.

### 2.13 The telemetry row claimed a state it did not hold — **CORRECTED**

Found by **kimi-code as the NOT-SAME reviewer** (PR #210, 2026-08-06), and the finding is the
same shape as §2.11 and §2.12 — which is why it is recorded here rather than fixed silently.

§3's header commits every row to *"verified in source or against the live daemon."* §11 marked
`record_gate_unavailable()` **Done**. Neither was true: the function exists only on branch
`cbp/gate-unavailable-is-not-a-member-event`, which had no PR; it is absent from `origin/main`
and from kimi's installed hooks; and no `telemetry/gate-unavailable.jsonl` exists on that seat.

kimi did not argue this from the tree. About forty minutes into the review a Bash call of kimi's
was denied `[fail-closed] — daemon path failed`. **That deny is the exact class plane E exists
for, and it left no durable record anywhere.** The reviewer fell into the gap the row described
as closed, while reviewing the row.

Checking the layer kimi named makes the finding sharper, and the sharper version is the one that
matters: **the function has no production call site.** On its own branch `record_gate_unavailable`
appears in its definition and in its two tests, and nowhere else. So the corrected state is not
*"written but unmerged"* — it is *"written, unmerged, uninstalled, **and uncalled**."* Landing and
installing the branch would still leave plane E with zero writers. The branch is now PR #211,
opened with that stated in its description so no reviewer infers otherwise; wiring the call site
into each harness's fail-closed path is Sprint 1 work, and it has to reach four installed engines.

**Why this row and not another.** A document whose load-bearing epistemic rule is *know which
evidence class you hold* (§4 principle 10, §7.4) cannot carry branch-state under a header that
says verified-in-source. The rule fails first in its own text or it does not bind.

---

## 3. Grounded current state

Every row was verified in source or against the live daemon on 2026-08-05. Nothing here is inferred from a document.

One row failed that standard and is corrected in place: the infra-telemetry row described *branch* state under a header that promises source-or-live. Found by the NOT-SAME reviewer, recorded at §2.13, and left visible here rather than quietly rewritten — a table that silently repairs itself teaches the next reader nothing about how it got wrong.

| area | state | evidence |
|---|---|---|
| Policy-Entity office | **filled, unnamed, by a rule table** | `policy/engine.rs:3` — *"Ports the `PolicyEntity.evaluate(...)` flow"* |
| the third verdict | **collapsed** | `policy/law_gate.rs:166` — `Decision::Deny \| Decision::Escalate => PolicyDecision::Deny` |
| caller identity | **declared** | `normalize_constellation_role(&declared_role)` at connect |
| `role_lct` | **a capacity string, not an LCT** | `reputation.rs:75` — `pub role_lct: &'a str` |
| canonical roles | **stored, signed, vault-backed, consulted by nothing that decides** | `delegation.rs` uses `SocietyRole`; no reference in `handler.rs`/`state.rs`/`policy/` |
| reputation contextualisation | **keyed on capacity, not office** | canonical: *"reputation is ROLE-CONTEXTUALIZED … there is no global reputation"* |
| escalation store | **memory-only, rehydrated from chain** | `EscalationStore { by_id: HashMap<..> }`, `rehydrate()` |
| the instruction to appeal | **delivered on every enforced deny** — but the text delivered is ref-dependent | rule reason `policy/presets.rs:89-93` → `guidance()` `{reason}` (`policy/types.rs:211-223`) → both hook paths render verbatim; 2nd site `handler.rs:1005-1010`. The *delivery* holds unconditionally: `{reason}` is rendered whatever it says. What varies is the reason — the sentence naming `hestia_appeal` is on 38 of 71 remote refs and **absent on 12**, whose older text names no tool (§15) |
| appeal **filing** | **unreachable — the required key is never delivered** | `require_string(args, "deny_hash")` (`handler.rs:2379`); hash minted then dropped (`let _ =`, `:1171`, `:1347`); absent from `PolicyEvaluation` (7 fields) and from the response (10 keys) |
| appeal **routing** | **prefers a "live" arbiter, where live = inbox-touch** | a watcher polling on behalf of an out-of-budget member reports `live`; two appeals routed to an unreachable designee and ruled anyway (2026-07-27) |
| appeal **window** | **measured in chain entries, not hours** | a busy session spends another member's window; re-run showed it was never a rate (2026-07-28) |
| ruling **delivery** | **adjudicated on-chain, never bound to the appellant** | kimi's scope appeal ruled at chain `89318` (`upheld: false`); no response ever bound to the notice (2026-08-03) |
| appeal **dispatch** | **mints flat `review_request` notices attributed to the appellant** | a third producer neither seat had counted; the chain is structurally blind to it (2026-08-03) |
| approval join key | **`(plugin_id, marker)`; tool and session ignored** | `claim(&mut self, plugin_id, marker, now)` — `tool_name` recorded, compared nowhere |
| governance history | **visible** | ledger shipped #198/#202 |
| deployment provenance | **measurable** | fleet manifest shipped #199 |
| infra telemetry | **designed and tested; unmerged, uninstalled, and uncalled — nothing records today** *(corrected 2026-08-06, §2.13)* | `record_gate_unavailable()` → `telemetry/gate-unavailable.jsonl` exists only on `cbp/gate-unavailable-is-not-a-member-event` (now PR #211), absent from `origin/main` and from kimi's installed hooks; on that branch it has **no production call site**. Measured, not inferred: a fail-closed deny on kimi's seat during the 2026-08-06 review left no durable record anywhere |
| installed gate | **behind source** | manifest: `hooks (claude-code): 4 diverged` |
| NOT-SAME review | **unrecordable on GitHub** | approve → *"Can not approve your own pull request"*; block → lands as a comment |
| branch protection | **status checks only** | `required_pull_request_reviews: None` |

**The generator behind most of these** (§7.4): a *declared* value sitting where an *audited* or *witnessed* one belongs.

---

## 4. Principles

Carried from GPT's §4 with three edits.

1. **The vault is authority.** No decision may rest on `identity.json`, a generated policy file, an authority-granting env var, a harness-local exception list, a CLI switch, an uncommitted remote response, a caller-supplied identity or role claim, or a file replica used because the daemon is down.
2. **Memory is the execution surface.** One immutable generation-tagged `GovernanceSnapshot`, swapped atomically. No hot-path file read participates in a decision.
3. **Files are transparency, never authority.** Mirrors are generated, marked non-authoritative, and are never imported.
4. **The operator edits law; law decides acts.** The human is not in the loop per act. The human is in the loop by authoring the law that is.
5. **Authority is explicit, not inferred.** *Phase constraint, not principle* (§2.9): for now no rule grants authority automatically from trust. §8's ladder will need that mechanism, under operator-authored law.
6. **A role is an office; an agent is a capacity.** Agents fill offices. Neither vocabulary expands. *(new — §2.7)*
7. **The shim never decides.** Parse and render only. No policy rule, path scope, forbidden list, remedy choice, grant logic, or allow/deny fallback.
8. **Uncertainty denies — and says so durably.** Every state in GPT's §4.8 denies. *And*: a denial caused by infrastructure is recorded in the telemetry plane, because a refusal nobody can see is indistinguishable from an act that never happened. *(amended — §2.2)*
9. **Where no qualified occupant exists, the office is filled loudly.** Provisional is a state, not a failure, and never silent. *(new — §2.8)*
10. **Know which evidence class you hold.** Declared, audited, and witnessed are not interchangeable, and a weaker one may never stand in for a stronger. *(new — §7.4)*
11. **A deny's text is a promise the daemon keeps.** Every tool, argument, or channel a refusal tells the member to use must exist and be reachable *from that refusal*. Instructing a member toward a path that is not there converts good faith into a tool error, and the member's next-best option is the one the same law penalises. *(new — §2.11, §8.4)*

---

## 5. Non-goals

This document does **not**:

- infer authority from reputation, T3/V3, activity volume, or vendor — *in this phase*;
- let an agent modify its own policy, role, authority, MRH, or gate;
- use a plaintext mirror as an offline fallback;
- keep a second policy implementation inside a shim;
- permit a decision while the authoritative snapshot is unavailable;
- ship physically separate member and role chains (§2.10);
- change hub, web4-core, or the conformance suite — those are hub's;
- claim any protection against a member that does not consent (§2.4).

---

## 6. Architecture — five planes

GPT's four, plus one.

| plane | holds |
|---|---|
| **A. Governance authority** | vault; operator identities and quorum; policy; roles and occupancy; authority grants; artifact manifest; generation history |
| **B. Gate execution** | one gate service; immutable snapshot; harness shims; per-call artifact assurance; typed verdict; fail-closed behaviour |
| **C. Occupancy & authorization** | proven member identity; authority grants; role definitions; the occupancy boundary; generation-bound occupancy; revocation |
| **D. Attribution & witness** | the one chain; the governance projection; RDF links between member, office, occupancy, and evidence |
| **E. Infrastructure telemetry** *(new)* | gate-unavailable records; snapshot load failures; deployment drift. **Never the chain.** Not member conduct, and not evidence about members |

**No plane may silently substitute for another.** Witness history does not grant authority; a mirror does not become policy; a role label does not establish occupancy; a shim does not become a gate; an escalation does not become a bypass; **and an infrastructure failure is not a member's conduct.**

---

## 7. Roles

### 7.1 Consume canonical; define nothing parallel

Hestia uses `web4_core::role::{SocietyRole, RoleAssignment, RoleEvent}` directly. It already provides role LCT, per-office T3/V3, multi-holder, M-of-N threshold, the lifecycle event log, and rotation that preserves the role LCT (conformance `role-002`).

`SocietyRole::Custom("git-manager")` covers the merge-partition office. No new role vocabulary.

### 7.2 Capacity moves to the agent

`interactive-dev`, `mesh-worker`, `reviewer`, `autonomous-timer`, `member` are **agent kinds**, not offices. They move to an enum on the agent's LCT.

Three surfaces currently assert otherwise and must be corrected together, or the record keeps describing itself wrongly: the constant `KNOWN_CONSTELLATION_ROLES`, the field `role_lct: &str`, and the `role:constellation:` URI prefix.

**Proposed upstream to web4-core, not built here** (hub's call): an agent-capacity enum on the LCT, and role *kinds* (worker / admin / governance) distinct from `RoleEventKind`, which is lifecycle.

### 7.3 Provisional occupancy

```rust
enum OccupancyBasis {
    Qualified,
    Provisional { because: String, audit_every: Duration, last_audited: Option<Timestamp> },
}
```

Defaulting to `Provisional`, fail-closed, exactly as `SovereignStrength` defaults to `Placeholder` — *"an unstated strength is the weakest claim."*

Three required properties:

1. **Not a blocker.** The office gets filled. Work proceeds.
2. **Not silent.** The basis rides on every verdict, chain entry, and operator surface the office touches. A provisional occupant must not resemble a qualified one at any point a reader might check.
3. **Carries its own cadence.** `audit_every` is a field, not an intention, and a lapsed interval surfaces as drift. Without this, *provisional* decays into *permanent-but-labelled* — which is how a placeholder quietly becomes the design.

Day one it says, on every gate verdict:

> `PolicyEntity: provisional — occupant is a rule table, no qualified policy agent exists. audit_every 7d, last audited never.`

### 7.4 Evidence class

dp: *"talent is largely declared, training is audited, temperament is witnessed."*

| dimension | evidence | produced by | decays |
|---|---|---|---|
| Talent | **declared** | the subject | stale on arrival |
| Training | **audited** | an examiner, point-in-time | steadily — *needs a cadence* |
| Temperament | **witnessed** | the record, continuously | not at all; accumulates |

`declared < audited < witnessed` is a falsifiability ordering. T3 cannot currently express it — `SubDimensionScore` carries `weight` and `observation_count` (quantity) and nothing for kind, so a declaration repeated often enough acquires the confidence of an observation.

Hestia records `EvidenceClass { Declared, Audited, Witnessed }` on every trust-bearing assertion it makes. Adding the field to `web4-core` is hub's to decide; hestia carries it locally until then.

**Characteristic failures, including ours.** Declared fails by lying. Audited fails by staleness and auditor capture — which is why NOT-SAME is an *independence* property, not a formality. Witnessed fails by **gaps read as absence**: our chain is biased clean exactly where infrastructure failed, so temperament drawn from it is overstated precisely in the intervals where things went wrong. Plane E (§6) exists to bound that.

**The rule this yields, and it is load-bearing for §8:**

> Resolver selection may read **audited** and **witnessed** dimensions. It may never read **declared** ones.

---

## 8. The Policy-Entity and the third verdict

### 8.1 Name the office, then restore the verdict

Hestia's gate is a port of the canonical Policy-Entity and says so in its own docstring. It is therefore a **base-mandatory office filled by a rule table** — which is legitimate, and must be *declared provisional* (§7.3) rather than left implicit.

`law_gate.rs:166` collapses `Escalate` into `Deny`. Restoring it is the single change from which the ladder follows.

### 8.2 The ladder

**heuristic → policy-agent[kind, T3/V3 threshold] → operator**

Escalation stops being *"ask the human"* and becomes **resolver selection**; the operator is the terminal case, not the only case.

Four current symptoms are one design consequence, and all four resolve here:

| symptom today | cause | resolved by |
|---|---|---|
| escalations expire unruled overnight | the only eligible resolver sleeps | a resolver that is awake |
| a fail-closed deny is unwitnessable | the resolver channel is the daemon that is down | plane E + a resolver that is not the daemon |
| `claim()` collides across tools and sessions | the join key has no resolver in it | resolution bound to its resolver |
| NOT-SAME is discipline, not mechanism | one terminal resolver, so no selection step | selection *is* where independence is tested |

**The invitation is the appointment.** That is how `git-manager` becomes an office rather than a convention.

### 8.3 On the TTL

The short window is **not a defect** — dp: *"expire fast was a fix to kimi's hooks failing open in 3 seconds."* It is not changed here. The ladder makes it correct rather than painful: most escalations resolve in seconds because a policy agent is awake, and the window only has to be human-sized for the residue that genuinely reaches the operator.

### 8.4 The return channel: appeal

Escalation and appeal are **not the same instrument at different times.** They differ in target,
and conflating them is how a member reaches for the wrong one (kimi did, on the record, 2026-08-03):

| | escalation | appeal |
|---|---|---|
| asked | before the act | after the deny |
| target | **the resource** — may I do this | **the rule** — should this be the law |
| answered by | a sufficiently-permitted resolver (§8.2) | an arbiter structurally not you and not the gate that denied you |
| outcome | the act proceeds or does not | the law changes or does not; conduct is recorded either way |
| timescale | seconds | the rule's lifetime |

Both channels need the same four things, which is why they belong in one section: a **resolver
who is awake**, a **window sized to the answerer**, a **verdict that reaches the asker**, and an
**attribution that names who acted**. §8.2 supplies all four for escalation. Appeal has none of
them today (§3), and the ladder's own logic supplies them:

1. **Filable.** The deny must hand back the key its own instruction names. `PolicyEvaluation`
   gains a hash field; the response gains a key; the two `let _ =` sites keep what they mint.
   *Nothing about the verdict changes* — which is why this lands in Sprint 1, not Sprint 3.
2. **Routable to someone awake.** Arbiter selection is resolver selection (§8.2) with an
   independence constraint. It reads **audited** and **witnessed** dimensions only (§7.4), never
   **declared** — and *liveness is a declared property of the wrong subject*: inbox-touch reports
   the watcher, not the member. Reachability is weak evidence (CLAUDE.md, R), so it may not be
   the sole basis for selecting an arbiter for a high-stakes ruling.
3. **Windowed in the answerer's units.** An appeal window measured in chain entries is spent by
   whoever is busiest, which is never the appellant. Windows bind to wall-clock or to the
   resolver's attention, not to global chain traffic.
4. **Delivered.** A ruling that is not bound to the appellant's notice has not been issued — it
   has been *filed*. This is the same defect as §8.2's row *"escalations expire unruled
   overnight"*, one channel over: the verdict exists and the asker never learns it.

**And attributed.** Appeal dispatch currently mints `review_request` notices under the
appellant's name — a member is recorded as having asked for reviews it never chose. That is an
attribution defect in plane D (§6), not a mesh nuisance: it puts acts in the record under an
identity that did not perform them, which is precisely what §9.1 exists to stop.

**The instruction is part of the surface.** Any deny text naming a tool, an argument, or a
channel is a promise the daemon must keep. Two do today (`presets.rs:89-93`,
`handler.rs:1005-1010`) and neither is kept. A standing check belongs with them: *every value a
deny's text tells the member to supply must be present in that same deny's response.* Cheap to
write, and it is the general form of the bug — `request_scope`, a tool that does not exist, was
prescribed by a deny in the same way (2026-08-03).

---

## 9. Identity and authority

### 9.1 Identity — the P0

`plugin_id` and role are caller-supplied and steer attribution, policy selection, reputation grain, and durable registration. A new caller can invent a name and select a published capacity.

Bind `plugin_id` to a key at connect. Every selector derives from the proven identity. Roll observe → warn → enforce: record the evidence class of each identity assertion first, warn when a declared identity would have been refused, then enforce.

### 9.2 Authority and the occupancy boundary

Authority is an explicit grant with issuer, reason, MRH, expiry, and revocation. Occupancy is established at a boundary — authenticate, resolve the office, check the grant against the office's requirement, bind to the current generation, witness — and only then may role-scoped policy apply.

Unknown office, insufficient authority, expired grant, or MRH mismatch fail closed to **no occupancy**, never to a silently substituted one.

### 9.3 The approval join key

`claim()` must join on the **resolver, the tool, and the attempted target** — not `(plugin_id, marker)`. Today the key is both tool-crossing and **session-crossing**, since `plugin_id` is identical across every session of one member: with *oldest-claimable-first*, one session silently spends an approval another session's act minted. Three read-approvals were spent by writes on 2026-08-05.

Sequence (from #203): land the marker-legibility fix first (it fixes the false *negative*), then narrow the key, then bind the claim to its target.

### 9.4 Independence is identity **and** stake — NOT-BENEFICIARY

Restored from `PRD_CONFIG_IN_VAULT.md` §5 (§2.12).

Every independence check in this document tests **who** the arbiter is. None tests **what the
arbiter gets**. `hestia_gate_arbitrate_escalation` enforces NOT-SAME correctly, and a peer
granting me scope is genuinely a different member — plausibly a different vendor lineage,
recording as `CrossVendor`, the strongest tier we can currently express.

> **Two members trading favours pass every check built this week.**

So a scope- or authority-mutating act carries three additional fields:

- **beneficiary** — which member's authority *increases*. Distinct from the author, and distinct
  from the arbiter.
- **NOT-BENEFICIARY** — an arbiter may not rule a mutation that widens its own MRH, even when it
  is a different member from the author. This is the missing half of NOT-SAME.
- **reciprocity as visible evidence** — *A widened B, and B previously widened A* is a fact about
  the pair, computable from the one chain (§2.10). **Not blocked; surfaced, and weighed as the
  weak evidence it is** — per CLAUDE.md, a surface produces inspectable evidence and lets the
  relying party decide; it does not encode a universal threshold.

This is the T3/V3 posture rather than a rule: independence is **recorded and graded, never
asserted**. It is also why §8.4's arbiter selection cannot be satisfied by cross-vendor alone.

---

## 10. The gate, and what gates the gate

Requirements carry forward from GPT's §13 — one decision service, syntax-only shims, per-call artifact assurance, no local fallback — with two changes.

**§2.4:** every requirement here is justified by *legibility*, not by resistance to a determined member.

**§2.5:** peer-path resolution gets a proof-of-life *before* the consolidation's shape hardens — one harness, one OS, modify-one-byte-fails-closed, demonstrated live. If peer-path resolution is unreliable, per-call assurance is caller self-report wearing a digest.

**Release gates — the consolidation is not wired fleet-wide until all hold:**

1. identity authenticated (§9.1) and enforcing;
2. occupancy boundary implemented (§9.2);
3. peer-path proof-of-life demonstrated (§2.5);
4. availability budget decided and met (§2.3, D-1);
5. fleet manifest shows zero drift on every host it can see;
6. no harness-local decision logic and no file-policy fallback remain;
7. rollback tested: a bad generation can be reverted without a human editing files by hand;
8. **the vault path reaches all four governed members, not one** (§2.12 item 3). kimi's and codex's
   adapters read identity from disk in their own code. A vault-authoritative config consulted only
   by claude-code governs one member of four and reports green doing it. The gate is *"zero members
   still reading config from disk,"* measured per member — not *"the vault works."*

---

## 11. Where today's work lands

kimi's third pushback, adopted: *"re-homed work that isn't announced reads as discarded work."*

| built | lands as |
|---|---|
| governance ledger (#198, #202) | plane D — the projection. **Done** |
| fleet manifest (#199) | §10 gate 5, and the standing audit instrument for `training:context-inspectable` |
| `record_gate_unavailable()` | plane E's **producer only** — on branch, PR #211, uninstalled and with no call site. **Not done**; Sprint 1 wires it into four harnesses *(corrected — §2.13)* |
| escalation store + rehydrate | §8 — becomes resolver-selection state |
| `tool_appeal` + arbiter + `derivation.rs` joins | §8.4 — the consumer half is **already built and keyed on `deny_hash`**; it has never had an input |
| gate false-refusal fixes (#203) | §8.2 — draining the approval supply line |
| mesh + `last-words` | plane D |
| identity classification check | feeds the artifact manifest (§10) |
| dashboard policy editors | the operator law surface (§4 principle 4) |
| fire templates | the shims of §10 |
| `PRD_CONFIG_IN_VAULT.md` | absorbed into §4 principle 1 — **in part, not whole** (§2.12) |

---

## 12. Sprints

**Seven sprints, numbered 1–7, preceded by Sprint 0.** Sprint 0 is not one of the seven: it opens no new ground, it finishes work already in flight and pays down what the fleet has measured about itself. Counted this way because a document that says *"seven sprints"* over eight numbered headings has already lost an argument it did not need to have.

Ordered by dependency, not by appetite. Every sprint states what it does **not** do, because the recurring failure mode here is a sprint quietly claiming the next one's ground.

Each sprint's acceptance criteria are **measurements**, not assertions — per §7.4, a criterion that can be satisfied by a declaration is not a criterion.

---

### Sprint 0 — Finish the present *(mostly done)*

**Goal:** the fleet's actual state is measurable and matches source.

- Redeploy the installed gate on every member (claude-code diverges in 4 files; codex carries the scope escape).
- Close the read/write false-positive class (#203 FP6/FP8) — the approval supply line.
- Baseline the availability numbers kimi measured, as a standing metric rather than a one-off.
- **Config drift detector** (§2.12 item 4): vault vs the on-disk shadow copy, distinct from the manifest's *hook* drift. It answers a question that is currently unanswerable — **has this already happened?** A non-zero first run is a finding to be published, not a bug to be quietly cleaned up before anyone looks.

- **Convert this document's 38 line-number citations to construct-pointers**, per `CLAUDE.md`'s own review-gate rule (*"a grep-able name not a drifting line number"*). One of them was wrong on arrival for exactly the reason the rule exists — it was true only in the author's unmerged checkout (§15) — and a citation a second reader cannot resolve at a shared ref is not evidence, which is this sprint's whole goal applied to its own paperwork. The scale is measured, not assumed: `tools/citation_ref_census.py` over all 71 remote refs puts the five distinct `handler.rs` line-spans on the cited line on **17 of 71**, and on 12 refs the construct behind the sharpest citation does not exist at all (§15). Conversion is what turns that second case from a wrong answer into no answer.

**Acceptance:** manifest reports zero hook drift on every host it can see; false-refusal rate measured before and after; escalations opened *by reads* trend to zero; the config drift detector has run once against today's files and its first-run output is on the record whatever it says; and the citation regex over this document returns zero — checked from a clean checkout of `main`, not from the author's tree, because that distinction is the entire finding. The census is run *before* the conversion too, and its output recorded: a converted document trivially scores zero line-number citations, so the only way the conversion can be shown to have moved anything is to publish the number it started from (today: `>= 13/71` on `handler.rs`, `38/71` on the one anchored citation).

**Not this sprint:** any change to what the gate decides.

---

### Sprint 1 — Observe: label everything, change nothing

**Goal:** every governed act says what it rests on. **No verdict changes.**

- `EvidenceClass` recorded on every trust-bearing assertion (§7.4).
- `OccupancyBasis` recorded; **name the Policy-Entity office and mark it `Provisional`** with a real `audit_every` (§7.3, §8.1).
- Consult `DelegationStore` in the decision path in **WARN**: log what *would* have changed, decide nothing (§3).
- **Make appeal filable** (§8.4 item 1): a hash field on `PolicyEvaluation`, a key on the response, and the two `let _ = s.append_chain` sites (`handler.rs:1171`, `:1347`) keeping what they mint. Add the standing check that every value a deny's text names is present in that deny's response.
- **Give plane E a writer** (§2.13). `record_gate_unavailable()` exists on a branch (PR #211) with **no call site**; merging it changes nothing. Wire it into the fail-closed deny path of each installed harness — four engines, not one — and distinguish `timeout` from `refused`, because those want opposite member responses.
- Surface all of it in the ledger.

**Acceptance:** four numbers exist that do not exist today — how many acts carry a declared vs audited vs witnessed identity; how many governed acts run under a provisional occupant; how many verdicts a live delegation would have changed; what the availability floor actually is. **Plus:** a member handed an enforced deny can file the appeal that deny's own text instructs it to file, demonstrated end-to-end on a real deny; and the deny-text check is RED against today's two promise sites before it is green. **And:** a deliberately induced fail-closed deny — the daemon stopped, one governed call made — produces a plane E row on **every** installed engine, the test being the row and not the report. The availability floor is derived from those rows, so it stops depending on one seat's wire logs.

**Not this sprint:** authority, enforcement, or any refusal that did not already happen. Appeal *filing* qualifies precisely because it changes no verdict — it returns a value the deny already computed and threw away.

**Whose hands.** The appeal-filing diff must not be authored by a member that benefits from it — every candidate touches the deny path governing its own author. Both CBP seats have recused (§2.11); assign it to hub, or to a seat that is not governed by this gate.

**Why first:** it is free to decide, and it stops every later sprint from silently claiming qualification it has not earned. It also produces the delegation number that tells us whether §9.2's model is right *before* we build on it.

---

### Sprint 2 — Identity: stop accepting declarations

**Goal:** the subject of every governed act is proven, not asserted.

- Bind `plugin_id` to a key at connect; derive every selector from the proven identity (§9.1).
- Split capacity from office: capacity to the agent LCT; rename `role_lct` to what it holds (§7.2).
- Observe → warn → enforce, with the Sprint-1 counters as the readiness signal.

**Acceptance:** a caller cannot select another member's grain; a session cannot assert another session's identity; the warn-phase count of would-be refusals reaches zero before enforce is switched on.

**Not this sprint:** per-agent authority. Identity first, authority after — §2.1.

---

### Sprint 3 — Restore the third verdict

**Goal:** `Escalate` survives to the boundary, and an escalation selects a resolver.

- Un-collapse `law_gate.rs:166`.
- Escalation becomes resolver selection; the operator is terminal, not sole (§8.2).
- Resolver selection reads audited and witnessed dimensions only — never declared (§7.4).
- Narrow `claim()` to resolver + tool + target, in the #203 order (§9.3).
- **The return channel, on the same machinery** (§8.4 items 2–4): arbiter selection is resolver selection with the independence constraint; the appeal window rebased off chain-entry count onto the answerer's units; rulings bound to the appellant's notice; appeal dispatch stops minting `review_request`s under the appellant's name.

**Acceptance:** an approval minted by a read cannot be spent by a write; an approval minted in one session cannot be spent by another; every resolution names its resolver and the authority it acted under; a resolver that is not independent of the author is refused. **And on the return channel:** an arbiter is never selected on inbox-touch liveness alone; an appeal's window cannot be consumed by another member's traffic; every ruling is bound to the notice that asked for it — replay the 2026-08-03 case (chain `89318`) and the appellant learns the verdict; no notice is attributed to a member that did not send it.

**Not this sprint:** T3/V3 thresholds. The first resolver tier is `training:context-inspectable`, which is *audited* and available on day one; numeric thresholds wait for §2.9.

---

### Sprint 4 — Authority and the occupancy boundary

**Goal:** offices are occupied on proven authority, and provisional occupancy has a path to qualified.

- Authority grants with issuer, reason, MRH, expiry, revocation.
- The occupancy boundary (§9.2); occupancy bound to a generation.
- Convert memory-only instance grants and scope grants into expiring vault policy deltas.
- Promote occupancy from `Provisional` to `Qualified` on **audited** evidence.

**Acceptance:** an agent below an office's requirement cannot create occupancy; an unauthorized attempt creates no role-chain act; revoking authority invalidates occupancy on the next act; an expired loosening stops mattering without a restart.

**Not this sprint:** the management UI. It is built against a model that already decides (§12, Sprint 6).

---

### Sprint 5 — Consolidate the gate

**Goal:** one decision service; shims that only parse and render.

Gated on **all seven release gates in §10** — in particular the peer-path proof-of-life and the availability decision. Neither is optional, and neither is this sprint's to discover.

**Acceptance:** modifying one byte of a shim fails the next call closed; a shim replaced by a symlink fails closed; calling from an unregistered process fails closed; killing the gate makes every shim refuse rather than decide locally — **and every one of those refusals appears in plane E.**

**Not this sprint:** new policy semantics. Consolidation moves the decision; it does not change it.

---

### Sprint 6 — The operator's role surface

**Goal:** the UI dp asked for — manage offices, occupancy, authority, role law, and provisional status.

Deliberately last. A management surface over a model that decides nothing produces exactly the artifact §3 documents: well-formed, encrypted, visible, and consulted by nothing.

**Acceptance:** every effective permission is explainable to its source layer; every provisional occupancy shows its reason, cadence, and overdue state; a law edit shows its diff, blast radius, and generation before it commits; no CLI or MCP path can mutate law.

---

### Sprint 7 — The hub seam *(coordination, not construction)*

Signed MRH-filtered projections to hub; hestia stays authoritative for local law. Depends on hub's decisions about the upstream additions in §7.2 and §7.4. **Not hestia's to start.**

---

## 13. Decisions dp must make

- **D-1 (blocks Sprint 5).** The availability budget: a recovery-time number, or an explicit witnessed-but-ungoverned degraded mode with its debt recorded. Not settleable by this document (§2.3).
- **D-2.** Whether `EvidenceClass` and the agent-capacity enum are proposed upstream to web4-core (hub's build, dp's call) or carried locally in hestia indefinitely.
- **D-3.** Whether NOT-SAME becomes a required status check. Branch protection is status-check-based and requires no reviews, so a signed review record converted into a required check is the cheapest real fix — and today proved a verdict cannot be recorded on GitHub in *either* direction.
- **D-4.** The parent dimension for leak/disclosure exposure. It is a *risk* property and may belong in V3 or on its own axis rather than under T3 (§7.4). Not guessed here.

---

## 14. What remains genuinely open

Distinguished from D-1..D-4, which are decisions with owners.

1. What recovery mechanism exists if consolidation causes fleet-wide fail-closed denial — the shape of the answer, once D-1 sets the number.
2. How policy rollback is distinguished from an attacker presenting an older but once-valid generation.
3. Whether occupancy should always expire, or may persist until authority or law changes.
4. What user-presence mechanism is available across browser, desktop, TPM, and security key.
5. Whether hub's V2-1 genesis deviation gets a conformance variant — hub's, flagged here because an intended deviation indistinguishable from a defect is one nobody can audit.
6. What an **upheld** appeal actually does. The law says an appeal *"is recorded conduct that can change the law"* and cites `62cfdffe` as the case where one did — via a human. Whether an upheld ruling amends law automatically, drafts an amendment for operator signature, or only scores conduct, is unsettled; §4 principle 4 says the operator edits law, which argues for the middle option. Nobody has had to decide, because no appeal has ever been filable (§2.11).
7. **What governs the gate between boot and vault unlock** (restored, §2.12 item 2). The vault needs a passphrase to open; the gate needs config to run. Today's answer for that interval is *the disk copy*, which is the precise hole vault-authority exists to close. A deny-until-unlocked gate is correct and makes an unlock outage total — which puts this squarely inside D-1's availability budget rather than beside it.
8. Whether appeal survives at all once §8.2's ladder lands. A resolver awake at decision time answers the *resource* question before a deny exists — but not the *rule* question, and appeal is the only member-held instrument aimed at rules. The honest possibility, stated so it can be tested rather than assumed: the ladder may reduce appeal volume to near zero without reducing its constitutional necessity by any amount.

---

## 15. Sight lines

Stated because §7.4 makes it a requirement rather than a courtesy.

- Hub was audited by **reading, not running**; the conformance suite was not executed. Given that this week's dominant failure mode was `source-fixed ≠ live`, that is not a formality.
- kimi's availability numbers (301/243/56%/45%) are quoted from its response and **not independently reproduced** by me. kimi's NOT-SAME review re-derived them against `shared-context/explorations/continuity-study-kimi-2026-08-04/` and offered that as the reproduction — and it does settle something real: the numbers I quoted match the dataset they came from, so the *transcription* is now checked. But kimi checked kimi's own dataset with kimi's own instrument, which is the transcription and not the measurement. **The measurement still stands on one seat.** Sprint 1's plane E rows are what would put it on four; until then D-1 is being decided on a single-seat number, and that is worth knowing while deciding it.
- Everything in §3 was verified in source or against the live daemon on 2026-08-05 and is dated accordingly, **with one exception found by review and corrected in place** (infra telemetry — §2.13). Source truth decays; the manifest exists so the next reader does not have to trust this table.
- **The review changed the document; what it could not check is the interesting residue.** kimi verified every §3 line citation, the five attributions to kimi, the web4-core claims, and the merge state of five cross-referenced PRs — all held. The one row that failed was the one describing *fleet state* rather than *source*, and it failed because fleet state has no single place to read it: kimi could check kimi's install and I can check mine, and neither of us can see codex's or gemini's. That is release gate 5's argument, made accidentally.
- **§2.11 / §8.4 are reads at rest, not a live probe.** Every source citation in the appeal rows — `presets.rs:89-93`, `types.rs:168-196`, `types.rs:211-223`, `handler.rs:1005-1010`, `:1171`, `:1246-1264`, `:1347`, `:2379` — I opened on this seat on 2026-08-06, at blobs `presets.rs@b4f936d`, `types.rs@4ba0252`, `handler.rs@7906e03` (see the bullet below for why the blob, not the date, is the pin). Nobody has filed a test appeal and watched it fail; the claim *"unreachable"* is derived from the absence of a field, which is strong, but it is not the same evidence as a refusal with a receipt. Sprint 1's acceptance is written to produce that receipt.
- The claim that the hooks render `guidance` **verbatim** is kimi's measurement from kimi's seat (notice 1114), not mine. I checked the producer; kimi checked the consumers. Neither of us checked the third and fourth engines — codex's schema is closed and kimi's local-gate path composes its own text, so *"both hook paths that carry a daemon payload"* is a claim about two of four installed engines.
- The routing, window, delivery, and dispatch rows are quoted from the 2026-07-27 → 2026-08-03 forum posts and are **not re-verified against today's code**. They were true when measured; the appeal subsystem has not been touched since, which is an argument and not a check.
- **§2.12's method, stated so it can be criticised.** I tested the "absorbed whole" claim by reading the source document and counting term hits in this one — `beneficiary`, `reciproc`, `unlock`, `bootstrap`, `foreign`, `shadow copy` all returned zero against the pre-amendment draft. That is a **lexical** test, and a lexical test can miss a concept carried under different words. I read §4 principle 1 and §8.2 to check the two most likely paraphrase sites and found neither concept; I did not read all 479 lines with each of the six concepts in mind. So: four dropped items is a **floor**, not a census.
- §2.12's restorations are transcribed from `PRD_CONFIG_IN_VAULT.md` and **re-argued, not re-verified**. In particular, *"kimi's and codex's adapters read identity from disk in their own code"* is that document's 2026-07-31 claim, not something I re-checked today, and it is the load-bearing premise of release gate 8.
- These sections were added on 2026-08-06 by the PRD's owner, after the body was drafted. §2.12 exists because the body's own supersession claim had no second reader.
- **One citation was true only on the seat that wrote it — and the repo already had a rule against that.** kimi's second read flagged `presets.rs:94-98` as pointing at the wrong lines; the appeal instruction is at `:89-93`. Both numbers are correct — at different refs. `:94-98` is right in my working tree, which sits on the unmerged branch `cbp/stale-primer-discharge-check`; its commit `2ccb1a5` inserts eight doc-comment lines above the cited region. On `origin/main` and on this PR's branch — the refs any reader will use — it is `:89-93`. **The citation was verified, by me, against a tree that exists on exactly one seat and nowhere in the shared history**, and every check available from that seat would have passed. Only a reader at a different ref could catch it, which is what happened. The generalisable part is not "check your line numbers" — it is that a line number is a claim about a *ref*, and the writer's checkout is not the reader's. `CLAUDE.md` says this already, in the review-gate block: *"a construct-pointer per line, grep-able name not a drifting line number."* This document carries 38 such citations as of this amendment (fenced `path:line` spans; the count is produced by `tools/citation_ref_census.py`, which prints its own regex and reconciles the total as 27 path-qualified + 11 bare `:NNN` continuations — it was 35 one commit ago and rose because these very bullets cite lines, which is the habit, not an exception to it), ignored its own repo's convention for all of them, and got caught on the one file that moved. Re-checking the other 34 is the wrong remedy; converting them is the right one, and it is now a Sprint 0 item.
- **The closure I claimed for that finding was computed from the same seat as the finding — and is refuted.** The bullet above originally ended: *"the class is bounded and now closed — `presets.rs` is the only cited file whose blob differs between my tree and main; `types.rs` and `handler.rs` are byte-identical across my tree, main, and this branch, so no other citation here can have drifted this way."* Each clause is true. The inference is not: three refs, two of which are the same blob by construction, is not a population — it is the same one-checkout error one level up, made in the sentence diagnosing it. Run instead over **all 71 refs under `refs/remotes/origin`** (`tools/citation_ref_census.py`, added with this bullet, which reproduces every number here):
  - `handler.rs` carries **27 distinct blobs**; only 13 refs hold main's. The census anchors `require_string(args, "deny_hash")` — the construct cited as `handler.rs:2379` — on the **cited line on 17 of 71 refs**, on some *other* line on 42, and absent on 12. Five distinct line-spans of this document point into that file (ten spellings at this commit). They are correct on **fewer refs than the citation kimi called broken**, and I declared them incapable of drifting.
  - `presets.rs:89-93` — the fix — holds on **38 of 71**, up from 1 before it. That is a real improvement and not a closure.
  - `reputation.rs:75` (§3's `role_lct` row) sits on a file with 6 distinct blobs, main's on only **21 of 71** refs. Nobody flagged it; the census found it.
  - Two citations spell the file `types.rs`, which is **two** tracked files (`core/src/policy/types.rs`, `plugin-sdk/rust/src/types.rs`). The census refuses to guess. A cite that needs a reader to guess the file is already not a pointer.
  - The document's own count reconciles: 35 = 24 path-qualified spellings + 11 bare `:NNN` continuations that inherit the preceding path. An instrument counting only the qualified form under-reports the exposure by a third — the first version of this one did.
- **The number that actually argues for conversion is the absence, not the drift.** On **12 of 71** refs the cited sentence is *not in `presets.rs` at all*: those tips carry an older rule reason — one says *"appeal it through the witnessed channel"*, naming no tool, and two say only *"Destructive command blocked by safety preset"*. §3 lists the appeal instruction as the one link in that chain that **works**; on those refs it does not exist. All 12 tips predate 2026-07-28 and none is merged, so they are *behind*, not divergent — but a member building from a stale branch is still a member, and this is the same shipped-≠-in-force ladder the document argues elsewhere, applied to the law's own text. Converting a citation to a grep-able construct does not make it resolve there. It makes the failure **legible** — grep returns nothing — instead of silent, which is a line number landing on plausible adjacent code. That is a stronger case for `CLAUDE.md`'s rule than "line numbers drift", and it is the case Sprint 0's item should be read as making.
- **What the census does not measure.** Refs, not installed builds: a seat may run a binary built from none of them, which is the gap §2.13 and Sprint 1 exist to close, and the same gap in a different coordinate. And blob agreement is a **lower** bound on a citation's validity — an edit below a cited line leaves it correct — so the `>= n/71` figures may understate. The anchored figures (38/71, 17/71) are exact; only the per-file bounds are bounds.
- **What is still unreviewed, precisely.** kimi's NOT-SAME review (PR #210, 2026-08-06) read the document as it stood before this amendment. Everything added *in response* to it — §2.13, the corrected §3 and §11 rows, the Sprint 1 plane E item, and these §15 bullets — has had no second reader, which is the ordinary condition of a fix and is stated because §7.4 makes it a requirement rather than a courtesy. kimi also declined to census §2.12's floor, so *"four dropped items"* remains a floor.
