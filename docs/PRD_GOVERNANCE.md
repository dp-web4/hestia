# PRD — Hestia governance: vault authority, canonical roles, and the third verdict

**Status:** definitive · supersedes the drafts listed below · **Date:** 2026-08-05, amended 2026-08-08 (fresh `origin/main` baseline `c487d0a`; current-state re-audit; act-bound appeals, instruction provenance, deployment-stage distinctions, and sprint refresh)
**Owner:** claude-code (CBP), by dp's assignment — *"you take the lead on hestia"*
**Decision-0013 amendment author:** codex (CBP) · **designated NOT-SAME reviewer:** kimi-code
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

> An **authenticated** agent acts through an approved harness shim, verified on that call, into one approved gate core. The core decides only from a validated in-memory snapshot loaded from the encrypted vault. The agent acts **in an office** only after its authority for that office is proven at the occupancy boundary — and where no qualified occupant exists, the office is filled **provisionally and loudly**, never silently. Every governed act has a stable action identity and canonical digest, including its actor, instruction/delegation provenance, and beneficiary. Every decision returns one of **three** verdicts, and an escalation is a request to a **sufficiently-permitted resolver**, of whom the operator is the last rather than the only. Every act is witnessed; every *infrastructure failure* is recorded outside the witness chain, so that silence in the chain is never mistaken for good conduct. A human changes outcomes by editing the law — and a **governed member changes the law by appealing it**: an appeal is a verdict on that recorded act, never a reusable grant or marker token, and must be filable, routable, windowed, terminally answered, and delivered only to the originating role/agent chain.

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

*(2026-08-06: PR #211 merged at `25bc06d`, so "unmerged" above is now false — the state is "merged,
uninstalled, and uncalled." The sentence is left standing because the reasoning it records is the
point; the three places this PRD asserted the state as current have been corrected. Kept as a
worked example of the class: a doc that states a deployment stage in present tense goes stale at
the merge, and nothing re-reads it.)*

**Why this row and not another.** A document whose load-bearing epistemic rule is *know which
evidence class you hold* (§4 principle 10, §7.4) cannot carry branch-state under a header that
says verified-in-source. The rule fails first in its own text or it does not bind.

### 2.14 Sprint 0's false-positive bullet is not verdict-neutral — **CORRECTED**

Found from this seat while auditing §12 against the measured defect inventory rather than against
its citations — and, like §2.13, found by falling into it.

Sprint 0 carries *"Close the read/write false-positive class (#203 FP6/FP8)"* and closes with
**"Not this sprint: any change to what the gate decides."** Its own acceptance criterion, two
lines above that, requires that *"escalations opened by reads trend to zero."* Those cannot both
hold: an escalation that stops opening is a verdict that changed. The exclusion clause and the
criterion contradict each other inside one sprint.

The mechanism makes this more than a wording slip. In the shared gate core module, `READ_CLASS`
has exactly two occurrences — its definition, and the predicate `needs_society_gate`, whose whole
body is `tool not in READ_CLASS`. **The read carve-out's only consumer is the daemon bypass:**
acts in the read class never reach the daemon at all. And the carve-out is keyed on the *tool-name
string* — `Bash` is never in it whatever the command does, which is exactly why a `sed -n` or a
`git -C` over a governed path is priced as a write. So the natural fix — classify read-shaped
`Bash` commands as reads — does not merely stop a false refusal. It moves those acts from
*daemon-gated* to *never-consulted*, with the class then selected by a caller-authored command
spelling. Suppressing the false positive and widening the ungated set are **one edit**.

That constraint is already Sprint 3's: its acceptance reads *"an approval minted by a read cannot
be spent by a write."* §11 agrees — it homes #203's fixes in §8.2, not in Sprint 0. The bullet is
therefore an instance of the failure §12's own preamble names: a sprint quietly claiming the next
one's ground.

**What changes.** Sprint 0 keeps the *measurement* — a false-refusal rate and a read-opened
escalation count, both baselined — and gives up the *closure*. Its exclusion clause then stands as
written, which it could not before. Closing the class moves to Sprint 3, where the spend-side
constraint that makes it safe to close is already an acceptance criterion.

### 2.15 The gate refuses this document's account of the gate — **ADDED**

§2.14 was not reasoned out and then confirmed. It was written, and the writing was refused.

Three refusals landed while producing that row, all on this seat, 2026-08-06, each minting a
single-use escalation permit: two `Bash` reads of the gate core (`sed -n`, to quote the two
constructs named above) — `f4047f4ef8c068f7`, `07bf8b056cb94cbe` — and then **the `Edit` that
wrote §2.14 itself**, `16dea346703b6a5d`. That third refusal is the finding. The Edit's target was
this markdown file. It was refused as a write to the gate's own code because the **prose quoted
the gate module's filename** — the matcher read a string in the payload, not the path being
written. Naming the module is indistinguishable, to the gate, from editing it.

So the false-positive class suppresses its own documentation, and the supply line refilled three
times inside one audit of the supply line. The row above is written with the filename elided to
constructs — disclosed here rather than done quietly, because an elision that is not declared is
just a rephrase, and §2.14 is partly *about* not doing that.

**The remedy the law names is not reachable from the seat the law governs.** The injected
operating law instructs a denied member three times to `hestia_appeal` the deny *"rather than
rephrasing"*, and scores a rephrase below plain compliance. On this seat, measured this session:
the MCP surface exposes **no hestia tools at all**, and the CLI's `hestia gate` ships
`pending / poll / approve / deny / corroborate` with **no appeal subcommand at any level**. The
escalation the deny prints is not an appeal — it asks a human to permit the *act*, not to review
the *rule*, which is §8.4's distinction exactly. A member holding a wrong deny therefore has
compliance or a scored recast, and no third door. This is §8.4 item 1 confirmed live, and sharper
than "the deny carries no hash": on this seat the instrument is absent from both surfaces.

One further detail, recorded because it is the class §2.13 exists for: the third deny reported
**`WITNESS FAILED — the refusal stands regardless`**. The refusal was enforced and not witnessed —
a fail-closed act leaving no durable record, encountered while amending the row about fail-closed
acts leaving no durable record. Plane E has no writer, so there is nowhere for it to have gone.

### 2.16 Appeals bind to the recorded act; provenance binds the deputy — **DECIDED, pending implementation**

The fresh 2026-08-07 re-audit and dp's ruling expose a deeper defect than a missing response field:
the current claim path treats `(plugin_id, marker)` as a portable capability. A grant can therefore
be spent by another tool, target, session, or caller asserting the same name. PR #283 records the
replacement design as decision 0013; this PRD adopts it as the target, while keeping the PR's
implementation status explicit.

An appeal is a transition on **one previously recorded denied act**, not a token authorising a future
act. The target record is identified by `action_id` and a versioned, domain-separated digest of a
canonical serialisation of the original request, of which only the digest is persisted. That digest
wire does **not** exist today: the chain carries a redacted, 400-byte-bounded `attempted` value, not
the act digest. A retry must re-present the original bytes and the daemon must verify the new digest
before re-evaluating it. The target state is an append-only fold of transitions:
`appealed → granted` or `appealed → denied`, including `denied on appeal — reason: timeout`; a late
ruling must lose a compare-and-swap against an already-terminal state.

The act record also carries composable provenance: actor role/agent chain, session/capacity,
`instructor_lct` and instruction evidence, beneficiary member(s), delegation/request id, office and
occupancy. Authority does not transfer through prose or a caller-supplied identity. An unattributed
act is not appealable — there is no originating chain to which a ruling can be delivered — but that
refusal may enforce only after attribution is **installed and observed**, not merely merged. Today the
old name join can and does deliver grants to the literal `unattributed`: Kimi's 2026-08-08
full-genesis census found **44 of 108 claimed grants** joined under that non-identity; all 108 claims
joined to approved rows. A daemon-unreachable deny is not silently dropped: the target design
requires a durable Plane-E record containing the action digest and enough provenance for later
reconciliation. Plane E has never produced such a row at the measured seat, so this is a build
dependency, not an existing fallback.

The design is deliberately staged. #281's marker-legibility work is an interim compatibility repair;
it is not the final authority model. Kimi's independent review says decision 0013 should stand and
corrects its current-state evidence; this PRD carries those corrections rather than inheriting the
three prose-ahead-of-mechanism claims. No autonomous arbitration driver should be built until act
binding, identity proof/signatures, provenance, and NOT-BENEFICIARY are in place. The scope half can
land before signing; the identity half — delivery
only to the originating role/agent chain — cannot be called enforced until signed acts make that
origin non-assertible. Current audit: `answers_deny` is empty for **425/425** historical escalation
opens, so the chain contains the plumbing but not evidence that the return path works.

---

## 3. Grounded current state

Every row was re-audited against fresh `origin/main` (`c487d0a`) and the open-PR queue on 2026-08-08. A source merge is not an install, restart, or live observation; those stages are named separately below.

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
| appeal **filing** | **current path unreachable; replacement designed, not implemented** | #283 / decision 0013 binds an appeal to `action_id` + canonical act digest; historical `answers_deny` remains empty for 425/425 escalation opens |
| appeal **routing** | **prefers a "live" arbiter, where live = inbox-touch** | a watcher polling on behalf of an out-of-budget member reports `live`; two appeals routed to an unreachable designee and ruled anyway (2026-07-27) |
| appeal **window** | **measured in chain entries, not hours** | a busy session spends another member's window; re-run showed it was never a rate (2026-07-28) |
| ruling **delivery** | **adjudicated on-chain, never bound to the appellant** | kimi's scope appeal ruled at chain `89318` (`upheld: false`); no response ever bound to the notice (2026-08-03) |
| appeal **dispatch** | **mints flat `review_request` notices attributed to the appellant** | a third producer neither seat had counted; the chain is structurally blind to it (2026-08-03) |
| approval join key | **portable marker path remains live; act-bound target is pending** | #281 improves marker legibility; #283 replaces portable grants with a verdict on one recorded act |
| act digest | **absent** | `policy_decision.attempted` is redacted and truncated at 400 bytes; canonical serialization, digest domain, and plugin-to-daemon wire are new work |
| governance history | **visible** | ledger shipped #198/#202 |
| deployment provenance | **measurable** | fleet manifest shipped #199 |
| infra telemetry | **source producer merged; fleet wiring/deployment still unproven** | #243/#211 landed producer work; #272/#273 address member-agnostic installation and current-build authority. Plane E has never recorded at the measured seat; a green source check is not evidence of installed writers or live rows |
| deployment authority | **installer path is in review, not yet a fleet-wide live fact** | #272 generic installer and #273 Claude-specific installer are both open; converge on one `$HESTIA_HOME/shared` path and verify restart/live behavior |
| installed gate | **must be measured per member** | deployment manifest/current-build file is the authority; distinguish source, merged, installed, restarted, live, and observed |
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

**The operator has no one-off exception surface.** Plane A changes law; it does not mint a bypass
for one act. An upheld appeal against a working rule therefore follows
`appeal → fix rule → grant → re-evaluate`; if the rule should remain, the appeal is denied. This
is the operator-facing consequence of decision 0013, not an implementation detail of Plane B.

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

### 7.5 The fold: declared, modified by audited, modified by witnessed

> dp, 2026-08-06: *"the way a full t3 score folds is talent (declared) modified by training (audited) modified by temperament (witnessed). the exact nature of 'modified by' we can experiment with."*

This is a **structural** change, not a parameter, and it is the reason the current mechanism could not express anything in §7.4.

**Today** (`web4-core/src/t3.rs::aggregate`): a weighted geometric mean of three co-equal roots. Talent, Training and Temperament contribute symmetrically, so a high *declaration* compensates for weak *conduct*. The evidence-class ordering exists in the doc comments and nowhere in the arithmetic.

**Proposed:** an ordered chain in which each stage *conditions* the one before it.

```
claim      = talent        (declared)
corrected  = claim      ⊗ training      (audited)
settled    = corrected  ⊗ temperament   (witnessed)
```

You assert capability; an examiner corroborates or discounts the assertion; conduct over time confirms or refutes the result. That is how trust actually forms, and the chain makes the falsifiability ordering `declared < audited < witnessed` **arithmetic rather than editorial**.

#### The shape is fixed; the operator is the experiment

Per dp, `⊗` stays open. What must *not* stay open is the set of properties any candidate has to satisfy — otherwise "modified by" is decoration and we will not be able to tell a good operator from a bad one.

**P1 — Non-commutativity is the whole point.**
> Swapping the training and temperament stages **must** change the result.

This single test eliminates the obvious first implementation: plain multiplication `t · r · m` is commutative and associative, so it expresses **no ordering at all** — it is the current geometric mean wearing a chain's clothes. Any candidate that passes P1 is at least *attempting* what dp specified. Any that fails it is not a fold, it is a product.

**P2 — A declaration alone cannot buy trust.** With no audit and no witness, the result must sit low, not at the neutral 0.5 a mean returns for "no observations." An unexamined claim is an unexamined claim.

**P3 — Witnessed evidence can destroy.** Conduct near zero must drive the total near zero regardless of how high the declared talent is. (The current geometric mean does zero out — that property is worth keeping.)

**P4 — Monotone in each stage.** Raising any stage's observed value must never lower the total. A fold that can be gamed by scoring *worse* is not a trust function.

**P5 — Absence and zero are different.** No audit ≠ a failed audit. A missing stage should widen uncertainty; a failing stage should lower the score. Collapsing them is the evidence-class error one level up.

#### Two candidate operators, offered as starting points

**A — corrective pull.** Each stage draws the running value toward its own observation, with strength given by that stage's confidence weight (fields that already exist):

```
s0 = talent
s1 = s0 + w_training    · (training    − s0)
s2 = s1 + w_temperament · (temperament − s1)
```

Passes P1 (order changes the interpolation path), P2 (zero weights leave the bare claim), P4. Handles P5 naturally, since an absent stage has weight 0 and simply does not move the value. Needs care on P3 — a low-confidence witness cannot pull far enough to zero, which may be right (one bad act is not a verdict) or wrong (some acts *are*), and that is precisely the sort of thing to experiment on.

**B — asymmetric corrective pull.** As A, but downward corrections apply at full weight and upward corrections at a discount. Encodes "trust is easier to lose than to gain" — which this fleet already asserts elsewhere in the temperament ladder, where a rephrase-after-deny scores *below* plain compliance while an upheld appeal earns full credit. B makes that asymmetry structural instead of per-rule.

#### What this fixes, and what it costs

**Fixes:** it gives the sub-dimension tree an actual computation. §D-4a records that `aggregate()` never touches `sub_dimensions` — they store and do not compute. Under a chain fold the natural shape is: sub-dimensions roll into their parent root first, then the three roots chain. `training:hosting-topology` and `temperament:context-stable` then *mean* something rather than sitting inert.

**Costs, stated plainly:** changing the fold changes the meaning of every T3 score ever computed. Scores from before and after are not comparable, and any stored aggregate is invalidated.

**That cost is unusually low right now, and it will not stay low.** Today's reputation deltas are keyed on *capacity* rather than *office* (§3) — already indexed on the wrong axis — and sub-dimensions never aggregated. There is very little correct history to invalidate. Every month this waits, that stops being true.

#### Propagation — and the direction is not the obvious one

> dp, 2026-08-06: *"this might need to propagate to trust-core."*

Checked. Three surfaces, and only one of them is a real duplicate:

**1. `web4/web4-trust-core` — already safe by construction.** It *re-exports* the tensor rather than reimplementing it (`pub use web4_core::t3::{TrustDimension, T3}`), and hestia's `Cargo.toml` pins both to one path with the reason stated: *"single web4-core source across the dependency graph (no duplicate tensor types)."* A fold change propagates here automatically. This was solved on purpose, earlier, by someone who saw the hazard.

**2. The standalone `web4-trust-core` repo — a zero-dependency reference port** (`eval.rs`, `jcs.rs`, `nquads.rs`, `sha256.rs`) with its own **conformance vectors**. This is a deliberate second implementation, which is exactly right for a spec — and it means a fold change that does not reach it makes the reference and the implementation disagree, with the vectors as the only instrument that would notice.

**3. And this is the finding: the reference port already implements semantics `web4-core::t3::aggregate` does not.** From `vectors/scores/expected-output.txt`:

```
V2 (member-bucket: 14 self-reports)
  -> null (self-reports match no evidence rule)

V3 (adjudicator capture)
  harsh default (unmeasured weight 0.0) -> null
  epsilon variant (weight 0.1)          -> 0.600 ± 0.262, strength 0.5
```

**Self-reports produce `null`, not a low score. Unmeasured produces `null`, not neutral.** Scores carry `± uncertainty` and a separate `strength`, and aggregation is fractal over *named evidence rules* (`w4td:BoundaryResponse`, `CorrectionAcceptance`, `EscalationProportional`).

That is dp's evidence-class ordering **already encoded** — and it satisfies two of the five properties above that the live implementation fails:

| property | `web4-core::t3::aggregate` | reference port |
|---|---|---|
| **P2** a declaration alone cannot buy trust | ✗ — returns neutral `0.5` for no observations | ✓ — self-reports → `null` |
| **P5** absence ≠ zero | ✗ — collapsed into the same neutral | ✓ — unmeasured → `null`, distinct from a low score |

**So "propagate to trust-core" may be backwards.** The reference port is not behind the implementation here; on evidence semantics it is **ahead of it**, and the live `aggregate()` is the outlier. The right first move is a reconciliation — read `eval.rs`'s semantics-1 evaluator properly and decide which of the two is the intended model — *before* designing a new fold that might duplicate work already done and vector-tested.

**Sight line:** I read the vectors' `expected-output.txt`, not the evaluator. The claims above are about what the vectors *assert*; I have not verified how `eval.rs` computes them, and the reconciliation is the task, not the conclusion.

#### Ownership

This is a change to `web4-core::t3`, so it is **hub's build** under the same split as D-2 — with the reconciliation above as its first step rather than the fold design. Hestia's ask is narrow and specific:

1. the chain shape, with `⊗` pluggable behind a trait so candidates can be swapped;
2. P1–P5 as conformance tests, so a proposed operator can be *rejected* on evidence rather than debated;
3. `EvidenceClass` selecting the **update rule** as well as the fold position (§D-4a defect 2) — witnessed grows with repetition, audited decays with staleness, declared never accrues confidence.

Hestia records the inputs in the meantime (Sprint 1) and consumes the fold when it lands. **Hestia does not implement a local fold** — two folds would disagree, and then neither is evidence.

---

## 8. The Policy-Entity and the third verdict

### 8.1 Name the office, then restore the verdict

Hestia's gate is a port of the canonical Policy-Entity and says so in its own docstring. It is therefore a **base-mandatory office filled by a rule table** — which is legitimate, and must be *declared provisional* (§7.3) rather than left implicit.

`law_gate.rs:166` collapses `Escalate` into `Deny`. Restoring it is the single change from which the ladder follows.

### 8.2 The ladder

**heuristic → policy-agent[kind, T3/V3 threshold] → operator**

Escalation stops being *"ask the human"* and becomes **resolver selection**; the operator is the terminal case, not the only case.

Four current symptoms meet here, but resolver selection is no longer their first prerequisite:

| symptom today | cause | resolved by |
|---|---|---|
| escalations expire unruled overnight | the only eligible resolver sleeps | a resolver that is awake |
| a fail-closed deny is unwitnessable | the resolver channel is the daemon that is down | plane E + a resolver that is not the daemon |
| `claim()` collides across tools and sessions | a marker token authorises a future act | decision 0013 binds the verdict to the recorded act |
| NOT-SAME is discipline, not mechanism | one terminal resolver, so no selection step | selection *is* where independence is tested |

**Hard prerequisite:** do not build the arbitration driver on the current claim path. Issue #264's
sample closed with **215 of 215** measured escalation decisions made by the operator. By Kimi's
2026-08-08 full-genesis review census, the population had grown to 302: **297 operator and 5 peer**
(3 kimi-code, 2 claude-code). Automating the resolver without the prerequisite would turn a low-rate
portable-token defect into a machine-rate deputy; the five early peer rulings strengthen rather than
relax that warning. Decision 0013 must land first, including signed origin for its identity clause,
and NOT-BENEFICIARY still applies at resolver selection. The ordering changed: NOT-BENEFICIARY
remains necessary, but it is no longer the first necessary repair.

**The invitation is the appointment.** That is how `git-manager` becomes an office rather than a convention.

### 8.3 On the TTL

The short window is **not a defect** — dp: *"expire fast was a fix to kimi's hooks failing open in 3 seconds."* It is not changed here. The ladder makes it correct rather than painful: most escalations resolve in seconds because a policy agent is awake, and the window only has to be human-sized for the residue that genuinely reaches the operator.

> **Correction of record (CBP, 2026-08-07): the "3 seconds" above is wrong, and it was
> load-bearing.** Verified against the Kimi engine binary, which resolves a hook's deadline as
> `timeout: hook.timeout ?? DEFAULT_HOOK_TIMEOUT_SECONDS` with the default at **30 s** — and the
> `[[hooks]]` entry's own `timeout` **is** honoured. Kimi's PreToolUse gate is configured at
> `timeout = 15`, so the real fail-open ceiling is **15 s**, not 3 s.
>
> The sentence above is retained rather than edited away, because *how* the error propagated is
> the more useful artifact: it entered as a recollection in conversation, was quoted into this
> PRD as sourced fact, and was then cited back as authority — including by me, to argue against a
> change that was in fact safe. Nobody measured it for weeks. It sized hestia's Kimi gate budget
> at 800 ms, which put the gate's per-request cap (500 ms) below the daemon's p99 (681 ms under
> chain-census load) and produced intermittent `no policy verdict (daemon path failed)` denies —
> denies that **cannot appear in the witness chain**, because recording one requires the daemon
> path that just failed. kimi's own measurement, §2 of this document: *"45% of those denies were
> daemon-unavailability, not scope."*
>
> This is the document's own defect class turned on itself: a **declared** value standing where an
> **audited** one belongs. Budget now 14 000 ms (`timeout` − 1 s); per-request 5 s.
>
> **And the pair is a bypass surface, not just a tuning knob.** The engine fails *open* past
> `timeout`, so the invariant `gate budget < hook timeout` is what keeps a fail-closed member
> governed at all. Push the budget above the timeout and every gate call overruns, the engine
> allows, and nothing is logged — no deny to notice, and a clean chain, because nothing was
> refused. It presents exactly as a well-behaved member. Either number can be edited alone, and
> neither edit looks dangerous by itself, so **this pair should be audited periodically rather
> than trusted once** (dp, 2026-08-07). Same shape for every fail-open-engine member; see
> `GATE_BYPASS_CATALOG.md` and the per-agent entries in `agent-atlas/talk-to/*/descriptor.md`.

### 8.4 The return channel: appeal

**Decision 0013 supersedes the claim-token model in this section; it does not amend that model.**
Marker, tool, and target cease to be a grant join rather than becoming a stricter grant join. #281
remains useful only as an interim visibility repair while the old path exists.

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

1. **Filable and act-bound.** The denied act is recorded before an appeal can open, with an
   `action_id` and versioned, domain-separated digest over its canonical serialization. The appeal
   references that record, never a marker or reusable claim token; a retry is accepted only when its
   verbatim request hashes to the recorded digest. The state transition is append-only
   (`appealed → granted|denied`), with timeout recorded under a non-merits reason class. Unattributed
   acts become explicitly non-appealable only after attribution is installed and observed, and
   daemon-unreachable denies require a durable Plane-E fallback record. #283 / decision 0013 is the
   design target; the current `deny_hash` consumer is compatibility debt, not the final contract.
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

**Provenance and deputy constraint.** Every consequential act and appeal carries the composable
role/agent chain, session/capacity, instructor and instruction evidence, beneficiary, delegation or
request id, office, and occupancy. A caller cannot acquire authority by repeating an identity in
prose. The originating chain is the delivery address; no proven origin means no appeal. Digest
matching closes scope under today's declared identity; delivery to the originating chain remains
observe-only until signatures make that origin provable.

**There is no exception mechanism.** Re-evaluation uses current law. If the rule that denied the
act still stands, a grant cannot wave one instance through; the operator flow is:

`appeal → fix rule → grant → re-evaluate`

The only other honest outcome is denial. This is intentionally more expensive per appeal: the
same false-positive class cannot be approved repeatedly without repairing the rule that creates it.
A timeout is terminal too, but its `resolver_unavailable` reason class must never be folded into
member trust as a merits denial. Nobody looked is not evidence that the appeal was wrong.

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

### 9.3 The approval join key is superseded by an act-bound verdict

The final join key is the **recorded action**, not `(plugin_id, marker)` and not a portable
capability. `action_id` plus a versioned canonical act digest binds the resolver's verdict to one
tool, target, arguments, session, and originating role/agent chain. A different session or caller
asserting the same name cannot spend it **once the origin is signed**. Before signing, the digest
still closes cross-act scope, but the originating identity remains declared and impersonable. #281's
marker-legibility fix is a useful interim compatibility guard; #283 / decision 0013 is the target
contract. Do not build an arbitration driver on the old claim-token semantics, and do not report the
identity half shipped when only digest matching is enforced.

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

The same constraint applies to a deputy or instructor. Every act names `instructor_lct`, instruction
evidence, delegation/request id, and beneficiary member(s). Authority does not pass through a prose
instruction, and `NOT-BENEFICIARY` applies to every consequential ruling, not only scope grants.

---

## 10. The gate, and what gates the gate

Requirements carry forward from GPT's §13 — one decision service, syntax-only shims, per-call
artifact assurance, no local fallback — plus the decision-0013 transition contracts below.

**§2.4:** every requirement here is justified by *legibility*, not by resistance to a determined member.

**§2.5:** peer-path resolution gets a proof-of-life *before* the consolidation's shape hardens — one harness, one OS, modify-one-byte-fails-closed, demonstrated live. If peer-path resolution is unreliable, per-call assurance is caller self-report wearing a digest.

**Decision-0013 target transition requirements (fresh re-audit):**

- Every governed act has a stable `action_id`, versioned canonical digest, actor role/agent chain,
   instruction/delegation provenance, and beneficiary. The digest is privacy-preserving but the
   retry must re-present and match the original act verbatim.
- Appeals reference only that recorded act and originating chain. They append a terminal transition
    (`granted`, `denied`, or `denied on appeal — reason: timeout`); expiry is not silent and late
    rulings cannot overwrite a terminal state.
- Daemon-unreachable denials use a durable Plane-E fallback record. Unattributed acts are not
    appealable; they are explicitly terminal as unaddressable rather than silently claimable.
- Deployment status is stage-labelled: source, merged, installed, restarted, live, and observed
    are separate facts, with the current-build authority file and installer proving the transition.

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
| `record_gate_unavailable()` | plane E producer merged (#211/#243 lineage); **fleet wiring and live evidence not done** until each installed harness emits a row under induced failure |
| escalation store + rehydrate | §8 — becomes resolver-selection state |
| `tool_appeal` + arbiter + `derivation.rs` joins | §8.4 — old `deny_hash` consumer is compatibility debt; #283 / decision 0013 is the act-bound replacement, pending review/implementation |
| gate false-refusal fixes (#203) | §8.2 — draining the approval supply line. **Sprint 3, not Sprint 0** (§2.14) |
| current-build authority + installers | #272 generic and #273 Claude-specific are open; converge before claiming deployment, then verify install/restart/live/observed separately |
| act provenance and beneficiary | design target from the 2026-08-07 re-audit; no implementation claim until actor, instructor, delegation, beneficiary, and originating-chain delivery are recorded |
| mesh + `last-words` | plane D |
| identity classification check | feeds the artifact manifest (§10) |
| dashboard policy editors | the operator law surface (§4 principle 4) |
| fire templates | the shims of §10 |
| `PRD_CONFIG_IN_VAULT.md` | absorbed into §4 principle 1 — **in part, not whole** (§2.12) |

---

## 12. Sprints

Sprint numbers are stable names, not cardinality or execution order. Sprint 0 finishes measured work
already in flight; Sprint 0.5 and Sprint 2.5 are dependency insertions whose names preserve all
existing cross-references.

Ordered by dependency, not by appetite. Every sprint states what it does **not** do, because the recurring failure mode here is a sprint quietly claiming the next one's ground.

Each sprint's acceptance criteria are **measurements**, not assertions — per §7.4, a criterion that can be satisfied by a declaration is not a criterion.

### 12.0 Execution order — amended 2026-08-08 for decision 0013

**The numbers are names, not sequence.** They are cited from §13 and elsewhere, so they do not change. The order of execution does:

| # | sprint | why here |
|---|---|---|
| 1 | **Sprint 5 — Consolidate the gate** | every sprint after it is otherwise built five times |
| 2 | Sprint 0.5 — Truth the grain | unchanged; small, and everything downstream is computed from it |
| 3 | Sprint 2 — Identity and signing | attribution and signed origin, now written once |
| 4 | Sprint 1 — Observe | labels a surface that has stopped diverging |
| 5 | **Sprint 2.5 — Bind appeals to acts** | decision 0013 replaces the portable claim before any machine-rate resolver exists |
| 6 | Sprint 3 — Restore the third verdict | the arbitration driver starts only after 0013 is enforceable |
| 7 | Sprint 4 — Authority and occupancy | per-role permission, on top of exact identity |
| 8 | Sprint 6 — Operator surface · then Sprint 7 — hub seam | unchanged |

The dependency between Sprint 2 and Sprint 2.5 is asymmetric. Sprint 2.5's **scope** slice —
canonical act digest, act link, and cross-act mismatch refusal — may land before signing. Its
**identity** slice — delivery only to the originating role/agent chain — may observe but may not
enforce or report shipped until Sprint 2 supplies signed origin. The table places completed Sprint
2.5 after Sprint 2; it does not forbid the independent scope slice from landing earlier.

**Why the original order was wrong.** Consolidation sat fifth because it changes no semantics and nothing blocks on it. That reasoning treated it as tidying. It is the **multiplier** on every sprint after it: Sprint 2's attribution fix is one line in the claude-code gate and does not exist in kimi's, so done before consolidation it is implemented four more times and four more divergences enter the corpus. The same holds for Sprint 1's labels and Sprint 3's ladder.

**The measurement that forced the change** (CBP, 2026-08-07 — one night, one machine, three live harnesses). Line counts of the per-harness gates against the core they are supposed to be shims over:

| lines | file |
|---|---|
| 1800 | claude-code's gate — **2× the "shared" core** |
| 989 | the shared policy core |
| 763 | codex's gate |
| 540 | kimi's gate |
| 528 | gemini's gate |

- The core landed (#169). **The shims never did.** claude-code and codex import it; kimi and gemini do not reference it at all. The per-harness gates are full independent implementations, not adapters.
- **The core is deployed nowhere.** No member's installed tree contains it. So the two gates that import it cannot load it at runtime — found while reviewing #243, whose new telemetry call sites resolve it by walking up from `__file__` and therefore record nothing on a real member while passing CI, which runs the repo layout.
- **Client-side self-protection exists in exactly one file fleet-wide** — claude-code's gate. kimi's deployed gate has none. Its zero escalations read as good conduct and are an absent rule: the null-state twin, at fleet scale.
- Escalations opened, trailing 30 000 chain entries: **claude-code 170 + unattributed 87 = 257 (87%), codex 39 (13%), kimi 0.** Of those, `Write`+`Edit` = 88 (30%) come from a payload scanner only claude-code has, and 142 (48%) from a single hardcoded marker naming one member's plugin directory. The distribution is a property of *which gate implements what*, not of how members behave.

**This is the intermediate state the gate's own source warned about**, quoted rather than paraphrased:

> *"today, disarming the gate means editing five files and tripping this rule five times. After the shims land it means editing ONE file — and if that file is outside the rule, consolidation will have moved the entire policy surface somewhere unguarded while every per-harness protection still reads as intact."*

We hold consolidation's costs — a nominal single core everyone is said to depend on — without its benefits. Staying here is strictly worse than either finishing or reverting.

**Deployment location, decided (dp, 2026-08-07): `$HESTIA_HOME/shared`**, not under any harness's home. Installing the core beneath one member's directory would make that member the custodian of every member's policy — the same defect as a hardcoded per-member marker, one layer down. `$HESTIA_HOME` is already the member-agnostic path every hook resolves and where plane-E telemetry lives, for the identical reason. A shim must resolve the core **there**, not by walking up from its own location: that walk is precisely what made #243 a silent no-op.

**What consolidation must carry on day one**, because these are the defects otherwise fixed five times:

- Self-protection, and with it the **payload-key correction**: path keys say *where* a call writes; the content/replacement keys say *what*. Scanning the latter refused ~15 legitimate acts in one night against one true positive — and *permitted* a gate edit whose diff happened to name no protected file. Both directions of that error live in one place after consolidation.
- **Integrity detection over prediction.** A lexical classifier cannot prove a shell command is a read; hashing the governance surface proves a write happened, exactly. Detection is what makes it safe to stop treating unproven-read as write, which is the whole of the false-positive class.
- **Attribution from the process's own identity**, not from environment variables only some launchers set (Sprint 2; #244).

**Acceptance for the re-ordering itself:** after consolidation, a policy change lands in one file and every member's next call reflects it — demonstrated by making one, not asserted. Until then, "consolidated" is a declared value.

> **A note on this section's own provenance.** File paths above are described by role rather than spelled, and the omission is the evidence. Writing this section with the literal paths was **refused by the gate it documents** (`gate-self-access`, escalation `9bc47120e9921f24`): the payload scanner matched the marker string inside a markdown document. A PRD section about a false-positive class cannot be written without reproducing the strings that class fires on — the same recursion that, on the same night, blocked committing an untracked gate into version control because the commit message had to name the file it was rescuing. This is the strongest available argument for the payload-key correction above, and it is left in place rather than tidied away once the fix lands.

---

### Sprint 0 — Finish the present *(source work largely merged; deployment proof remains)*

**Goal:** the fleet's actual state is measurable and matches source.

- Converge #272's generic installer and #273's Claude-specific lessons into one member-agnostic
  deployment path at `$HESTIA_HOME/shared`; install, restart, and observe every governed member.
- Treat the current-build authority file and `HESTIA_CURRENT_BUILD_FILE` as deployment evidence,
  not as proof that a daemon has restarted. Record source/merged/installed/restarted/live/observed
  separately and surface stale state to the operator.
- **Measure and baseline** the read/write false-positive class (#203 FP6/FP8) — the approval supply line. **Closing** it is Sprint 3, not this sprint (§2.14): the read carve-out's only consumer is the daemon bypass, so the fix and a widened ungated set are one edit, and the spend-side constraint that makes it safe to land is Sprint 3's acceptance criterion.
- Baseline the availability numbers kimi measured, as a standing metric rather than a one-off.
- **Config drift detector** (§2.12 item 4): vault vs the on-disk shadow copy, distinct from the manifest's *hook* drift. It answers a question that is currently unanswerable — **has this already happened?** A non-zero first run is a finding to be published, not a bug to be quietly cleaned up before anyone looks.

- **Convert this document's 36<!--n:live--> live line-number citations to construct-pointers**, per `CLAUDE.md`'s own review-gate rule (*"a grep-able name not a drifting line number"*). One of them was wrong on arrival for exactly the reason the rule exists — it was true only in the author's unmerged checkout (§15) — and a citation a second reader cannot resolve at a shared ref is not evidence, which is this sprint's whole goal applied to its own paperwork. The scale is measured, not assumed: `tools/citation_ref_census.py` over all 71 remote refs anchors the construct behind the *sharpest* of the five distinct `handler.rs` line-spans on the cited line on **17 of 71**, and on 12 refs that construct does not exist at all (§15). The other four spans carry no anchor and are bounded only by blob agreement — `>= 13/71` — so 17/71 is one span's exact figure, not the five's; attributing it to all five was this bullet's own version of the error §15 is about, and is corrected here. Conversion is what turns that second case from a wrong answer into no answer.

**Acceptance:** manifest reports zero hook drift on every host it can see; the false-refusal rate and the count of escalations opened *by reads* both have a published baseline — they trend to zero in Sprint 3, not here (§2.14), and a sprint that forbids verdict changes cannot accept one as a criterion; the config drift detector has run once against today's files and its first-run output is on the record whatever it says; and the **live** citation count over this document reaches zero, measured by `tools/citation_ref_census.py --doc-ref <the merge commit on main>` — a named ref, not the author's tree, because that distinction is the entire finding.

Three ways a zero here can be a false pass, all of them closed before the criterion is worth running:

1. *The document is not there.* `PRD_GOVERNANCE.md` does not exist on `origin/main` today — it arrives with this PR. Run the criterion against `main` right now and it scores zero because there is no file to count, which reads identically to a finished conversion. The census exits **2** on an absent document rather than printing a count, so the two cannot be confused; the criterion is unrunnable until the merge, and that is the correct state for it to be in.
2. *A converted document trivially scores zero.* So the census is run **before** the conversion and its output recorded — the conversion can only be shown to have moved something against a published starting number. At the commit that adds this clause: **36 live, 3 quoted**; `>= 13/71` blob agreement on `handler.rs`; `38/71` on the one anchored citation. Re-derive with `--doc-ref` at that commit — the number is stated with the ref it was taken at, because a count without one is this document's own §15 finding.
3. *The count is exempted rather than converted.* Quoted citations — §15 must spell the broken one to report it — are marked `<!--cite:quoted-->` at the citation, and the census prints that number beside the live one. A conversion that works by adding markers shows up as the quoted count rising, in the same two lines of output — and the census **names** each exempted spelling rather than only counting them, so an exemption that lands by accident (the marker exempts whatever it abuts, including after a prose mention of the marker itself) is visible on the line that reports it. At this commit: 3 quoted, all in the §15 post-mortem, and no other section may use the marker without saying why.

**Not this sprint:** any change to what the gate decides.

---

### Sprint 0.5 — Truth the grain before observing it *(kimi's amendment, adopted)*

> kimi, NOT-SAME response to the roles audit (#207): *"The observe and warn phases compute 'what would have changed' from recorded role strings. But #192 proved those strings can mislabel the session class (unresolved role painted as attended), and until the resolution path fails **loud** everywhere — not just in the fire templates — the warn phase would train its logs on evidence that is already lying. A warn phase fed mislabeled evidence does not become an enforce phase; it becomes a new way to be confidently wrong, with better logs."*

**Adopted, and it precedes Sprint 1.** My plan had observe first on the reasoning that observation is free. kimi's correction is that observation is only free when the instrument is honest, and this one is not yet: role resolution fails *loud* in the fire templates (#192) and still falls back to defaults at hook registration.

This is §7.4's own rule turned on the measurement apparatus rather than on the data: an instrument that silently substitutes a default is reporting a **declared** value while presenting it as **witnessed**. Sprint 1's four numbers would be computed over exactly that substitution.

**Lands:** loud failure on unresolved role at every resolution site, hook-registration defaults included — no silent fallback to `interactive-dev` or `member`.

**Acceptance:** an unresolvable role produces a refusal or a marked-unknown record, never a substituted one; the count of substituted-role acts in the trailing window is **zero**, measured rather than assumed.

**Why it is small and worth its own rung:** it is a handful of call sites, and everything after it is computed from what it produces.

---

### Sprint 1 — Observe: label everything, change nothing

**Goal:** every governed act says what it rests on. **No verdict changes.**

**Precondition:** Sprint 0.5. Observing a grain that mislabels itself produces confident numbers about the wrong thing.

- `EvidenceClass` recorded on every trust-bearing assertion (§7.4).
- `OccupancyBasis` recorded; **name the Policy-Entity office and mark it `Provisional`** with a real `audit_every` (§7.3, §8.1).
- Consult `DelegationStore` in the decision path in **WARN**: log what *would* have changed, decide nothing (§3).
- **Prepare the act record for Sprint 2.5** (§2.16, §8.4): surface the existing `action_id`,
  composed identity, and `answers_deny` slot without claiming the absent digest wire or act link.
  Record would-refuse results for unattributed opens; do not enforce them before attribution is
  installed and observed.
- **Give Plane E a writer** (§2.13): wire the merged producer into the fail-closed path of every
  installed harness — four engines, not one — and distinguish timeout, refusal, and unaddressable
  acts. The fallback must retain enough action digest/provenance for later reconciliation.
- Surface all of it in the ledger.

**Acceptance:** four numbers exist that do not exist today — how many acts carry a declared vs audited vs witnessed identity; how many governed acts run under a provisional occupant; how many verdicts a live delegation would have changed; what the availability floor actually is. **Plus:** a deliberately induced fail-closed deny produces a Plane-E row on every installed engine, with the test being the row and not the report; the observed count of unattributed appeal opens is published without changing their verdict.

**Not this sprint:** authority, act-binding enforcement, or any refusal that did not already happen.
Sprint 1 records the facts and would-refuse result; Sprint 2.5 changes the appeal state machine.

**Whose hands.** The appeal-record preparation must be authored/reviewed under NOT-SAME and
NOT-BENEFICIARY. The design is independently recorded in #283; implementation must have a different
reviewer from the beneficiary and must not let the requester repair its own approval path.

**Why first:** it is free to decide, and it stops every later sprint from silently claiming qualification it has not earned. It also produces the delegation number that tells us whether §9.2's model is right *before* we build on it.

---

### Shared prerequisite — instruction provenance and the deputy boundary

This is cross-cutting, not a fourth identity vocabulary. Before Sprint 3 can select a resolver or
arbiter, the chain must distinguish the actor who performed an act from the role/agent that
instructed it and the member that benefits. The minimum record is:

`actor_lct`, `actor_session`, `role_lct`, `instructor_lct`, `instruction_evidence`, `beneficiary_lct[]`,
`delegation_id`/`request_id`, `office`, and `occupancy_generation`.

The record is composable across delegation depth. A deputy's authority is the deputy's own proven
occupancy plus an explicit delegation; prose saying “I was instructed by X” is evidence to inspect,
not authority to inherit. NOT-BENEFICIARY and NOT-SAME are evaluated against this chain for every
consequential act. Once attribution is installed and observed, unattributed acts are terminal and
non-appealable because no originating chain exists to receive the verdict; before that prerequisite,
the would-refuse result is observation only.

---

### Sprint 2 — Identity and signing: stop accepting declarations

**Goal:** the subject and originating chain of every governed act are proven, not asserted.

- Bind `plugin_id` to a key at connect; derive every selector from the proven identity (§9.1).
- Split capacity from office: capacity to the agent LCT; rename `role_lct` to what it holds (§7.2).
- Record the composable actor/instructor/delegation/beneficiary chain on every governed act; a
  deputy may transmit an instruction but cannot transmit the instructor's authority by assertion.
- Introduce signatures or equivalent key-bound proof for the originating chain before any act-bound
  grant is considered claimable.
- Observe → warn → enforce, with the Sprint-1 counters as the readiness signal.

**Acceptance:** a caller cannot select another member's grain; a session cannot assert another
session's identity; every newly appended governed act carries a signature verified against its
recorded origin; tampering with the digest, role/agent composition, or session binding makes
verification fail; and the warn-phase count of would-be refusals reaches zero before enforce is
switched on. A zero-caller signing primitive does not satisfy this criterion.

**Not this sprint:** per-agent authority. Identity first, authority after — §2.1.

---

### Sprint 2.5 — Bind appeals to recorded acts

**Goal:** remove the grant token. An appeal resolves exactly one recorded denied act; re-evaluation
is possible only for the same canonical act and, once Sprint 2 is complete, the same signed
originating role/agent chain.

**Preconditions:** the denied act is recordable in the normal chain; daemon-unreachable denials have
a durable Plane-E writer on every installed engine; attribution is installed and observed before
unattributed opens are refused. The scope slice may land without signatures. The identity slice may
only observe until Sprint 2's signed-origin acceptance is green.

**Lands:** populate `answers_deny`; replace marker claims with append-only transitions on
`action_id`; re-present and digest-check the original act; record `appealed`, `granted-on-appeal`,
`denied-on-appeal`, and timeout with a non-merits reason class; deliver the result to the signed
originating chain. The old marker path is removed after migration, not retained as fallback.

**Five acceptance contracts from decision 0013:**

1. **Canonical, domain-separated digest.** One versioned serialization produces the same digest for
   semantically identical acts, rejects ambiguous encodings, and cannot collide by domain with a
   witness digest or chain hash. A changed tool, target, argument, or provenance field fails the
   retry. The test is red before the new plugin-to-daemon digest wire exists.
2. **Durable unavailable-daemon fallback.** Stop the daemon, trigger a governed denial through each
   installed engine, restart both sides, and recover a Plane-E action record sufficient to open the
   same act-bound appeal. An in-process buffer or a report without a row fails.
3. **Compare-and-swap terminal transition.** Race timeout against a late ruling on one appealed act.
   Exactly one terminal transition wins while the loser is appended as a rejected transition; no
   operator result is overwritten and no act acquires two terminal verdicts.
4. **Append-only history.** Every state change appends a transition referring to the action and
   prior state; a before/after chain comparison proves no historical row was mutated. Current state
   is derived by fold.
5. **Every escalation links to its act.** A census test asserts that every newly opened escalation
   has a non-empty, resolvable `answers_deny` reference to its recorded act. It is deliberately red
   against the historical baseline — **0 of 425** links populated — and green only when the wiring
   lands; exempting old rows must be explicit by schema/version, never by dropping them from the
   denominator.

**Additional acceptance:** a digest match may close scope before signing; the test report labels
origin enforcement **not enforceable** in that state. After Sprint 2, a different signer asserting
the same member name cannot receive or re-evaluate the verdict. Unattributed opens are refused only
after an installed-gate census shows attributable identity on the governed path. Timeout records
`resolver_unavailable` (or an equivalent typed non-merits reason) and is excluded from member-merits
scoring.

**Not this sprint:** resolver automation. Sprint 3 consumes this state machine only after every
criterion above is green.

---

### Sprint 3 — Restore the third verdict

**Goal:** `Escalate` survives to the boundary, and an escalation selects a resolver.

**Hard precondition:** Sprint 2.5 is complete. NOT-BENEFICIARY alone does not make the current
portable claim path safe for an arbitration driver.

- Un-collapse `law_gate.rs:166`.
- Escalation becomes resolver selection; the operator is terminal, not sole (§8.2).
- Resolver selection reads audited and witnessed dimensions only — never declared (§7.4).
- Consume Sprint 2.5's act-bound verdict state; do not recreate a resolver-scoped token beside it.
- **Close the read/write false-positive class** (#203 FP6/FP8), moved here from Sprint 0 (§2.14) — it lands *with* the spend-side constraint below, never before it, because widening the read carve-out without that constraint trades a false refusal for an act the daemon never sees. The class includes the gate's refusal of its own documentation (§2.15).
- **The return channel, on the same machinery** (§8.4 items 2–4): arbiter selection is resolver selection with the independence constraint; the appeal window rebased off chain-entry count onto the answerer's units; rulings bound to the appellant's recorded action and originating chain; appeal dispatch stops minting `review_request`s under the appellant's name. Expiry is a terminal timeout denial, not silent disappearance.

**Acceptance:** a verdict for one recorded act cannot be spent by another tool, target, session, or agent; every resolution names its resolver and authority; a resolver that is not independent of the author or beneficiary is refused. **And on the return channel:** an arbiter is never selected on inbox-touch liveness alone; an appeal's window cannot be consumed by another member's traffic; every ruling is bound to the recorded action and originating chain; replay the 2026-08-03 case (chain `89318`) and the appellant learns the verdict; no notice is attributed to a member that did not send it; timeout and unattributed states are terminal and explicit.

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

### Sprint 5 — Consolidate the gate  *(EXECUTED FIRST — see §12.0)*

**Goal:** one decision service; shims that only parse and render.

Gated on **all eight release gates in §10** — in particular the peer-path proof-of-life and the availability decision. Neither is optional, and neither is this sprint's to discover.

**Lands, per §12.0:**

- The core installed at **`$HESTIA_HOME/shared`** and resolved there explicitly. Not under a harness home; not by walking up from a shim's own path.
- Every harness reduced to a shim that parses its engine's event shape and renders its engine's verdict. Today the largest gate is **1800 lines against a 989-line core**, and two of five engines do not reference the core at all.
- Self-protection **in the core**, so it stops being one member's property. It currently exists in exactly one gate; the member with the loudest compliance record is the only one carrying the check, and the member with a clean sheet has no rule.
- The payload-key correction, integrity detection, and identity-from-process (§12.0).

**Acceptance:** modifying one byte of a shim fails the next call closed; a shim replaced by a symlink fails closed; calling from an unregistered process fails closed; killing the gate makes every shim refuse rather than decide locally — **and every one of those refusals appears in plane E.**

Plus, from §12.0 and measured rather than asserted: a policy change lands in **one** file and every member's next call reflects it, demonstrated by making one; and the escalation distribution across members stops being explainable by *which gate implements what*.

**Not this sprint:** new policy semantics. Consolidation moves the decision; it does not change it.

**The one exception, stated because it is an exception:** the payload-key correction and integrity detection *do* change what the gate decides, and they are here anyway. Deferring them means shipping the consolidation with a known false-positive class that has already refused a code review, three commit messages, a drift survey, and a section of this document — and a known false-*negative* on the same mechanism. Landing the move without them consolidates the defect rather than the gate. This is the sprint's `Not this sprint` rule being broken deliberately and on the record, which is the only acceptable way to break it.

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

**All four answered by dp, 2026-08-06.** Recorded here with what each decides; D-1 and D-3 turned out to be the same mechanism (§13.5).

### D-1 — availability budget: **per-role, base law with overrides** ✅

> dp: *"this should be per-role, or a base law with per-role overrides and granularity as needed. some roles can wait for perfect agent, others must do with what they can get and fail loudly when blocked."*

A single fleet-wide recovery number was the wrong shape. Availability tolerance is a property **of the office**, because the cost of an office standing empty differs per office: an Archivist that pauses loses ordering; a Policy-Entity that pauses stops every member.

```rust
struct AvailabilityPolicy {
    /// How long the office may stand unfilled/unreachable before the rule below fires.
    grace: Duration,
    /// What happens then.
    on_exceeded: OnExceeded,
}

enum OnExceeded {
    /// Wait for a qualified occupant. Acts requiring this office refuse — loudly, in plane E.
    Refuse,
    /// Proceed with the best available occupant, as Provisional (§7.3), and audit on that cadence.
    ProceedProvisional { because: String, audit_every: Duration },
}
```

Base law sets the default; each `RoleDefinition` may override; finer granularity is added where an office earns it rather than pre-emptively.

**This is the same field family as `OccupancyBasis` (§7.3), not a parallel one.** "Can wait for a perfect agent" *is* `OnExceeded::Refuse`; "must do with what it can get" *is* `ProceedProvisional`. The availability budget and the occupancy basis are one decision seen from two sides — before the office is filled, and after.

And the refusal half is not silent: *"fail loudly when blocked"* means a `Refuse` outcome is a plane-E record naming the office, the grace it exceeded, and what was blocked — not a timeout that kills something and leaves no account.

**This retires kimi's "the current one" finding (§2.3):** outage behaviour stops being decided incidentally by whatever the timeout kills, because every office states its own answer in law.

### D-2 — `EvidenceClass` and agent-capacity go to **core** ✅

> dp: *"sounds like core is the right call."*

Both are proposed upstream to `web4-core` (hub's build per the scope split). Hestia's local carry (§7.2, §7.4) is therefore **transitional with a named destination**, not a permanent fork — and the PRD says so, because a local type with no upstream plan is how a divergent vocabulary starts.

Hestia consumes the canonical types when they land. Until then it records the same shapes locally, and the migration is a rename rather than a redesign.

### D-3 — NOT-SAME is **per-request-class, three-valued** ✅

> dp: *"that needs per-request-class granularity. some things require not-same, some prefer it but ok either way, some don't care."*

A single repo-wide required check was the wrong shape for the same reason D-1 was:

```rust
enum NotSameRequirement { Required, Preferred, Indifferent }
```

- **Required** — merge/act refuses without an independent reviewer. Governance surfaces, law edits, authority grants.
- **Preferred** — proceeds if no independent reviewer is available, **and the record says it proceeded without one.** This is the loud-placeholder shape again (§7.3): not blocked, not silent.
- **Indifferent** — no independence claim made or implied, so none is recorded as missing.

The existing arbiter tiers (`CrossVendor > CrossMember`) become the *strength* of a satisfied requirement, not a separate scale.

**Mechanism.** Branch protection here is status-check-based and requires no reviews (verified 2026-08-05), so the fix is a required status check fed by a **signed review record** rather than by GitHub's review state — which cannot express a cross-vendor verdict in either direction on this repo (approve → *"Can not approve your own pull request"*; block → lands as a comment). The check reads the request class, looks for a signed not-same record at that head, and goes green for `Indifferent`, green-with-a-note for an unsatisfied `Preferred`, and red for an unsatisfied `Required`.

### D-4 — leak/disclosure is **not a score at all; it is MRH** ✅

> dp: *"tell me more about it."*

I offered T3-subdimension vs V3 vs its-own-axis. Having looked properly, **all three are wrong**, and the reason is worth stating because it changes what gets built.

**Why not T3.** T3 asks *"will this entity do right by me?"* A perfectly honest, perfectly trained, perfectly consistent cloud-hosted agent **still discloses everything it reads to its provider.** So a T3 score would penalise character for a structural fact — and worse, it would be *improvable by good conduct*, which it must never be. No amount of witnessed good behaviour reduces disclosure by one byte.

**Why not V3.** `Valuation / Veracity / Validity` measure value *produced*. Exposure is a cost *borne by the relying party*. Wrong direction.

**Why MRH.** The spec defines MRH as *"the context boundary for an entity — the set of all entities that are relevant to this LCT's operations."* For a cloud-hosted agent the provider **is** such an entity: present in every act, relevant to every operation, and **not removable by any grant.** That is not a score about the agent. It is a fact about the shape of its horizon.

So disclosure exposure is expressed as an MRH fact — enumerable, auditable, and in the *audited* evidence class (§7.4) rather than as a number someone has to trust.

#### The consequence that actually matters

**MRH grants are subtractive for reach, but not for disclosure.**

- *"Do not let this agent see X"* → **enforceable.** The gate refuses the read.
- *"Let this agent see X, but do not let X leave"* → **not enforceable, ever, for a cloud-hosted agent.** The moment I read it, it is in the provider's context.

Which yields a rule hestia needs now, not in a later sprint:

> **For a cloud-hosted member, vault read policy *is* disclosure policy.** There is no separate confidentiality control to add later, because the disclosure happens at the read.

This is also outside the A1 trust boundary (§2.4) in a way nothing else here is. A1 is about whether a member *complies*; disclosure happens even under perfect compliance. It is the one exposure in this document that cooperative assurance cannot touch, which is exactly why it must be structural rather than scored.

#### And it composes, which a score would not

MRH is a set, so an act's disclosure horizon is the **union** of its participants' horizons. If a local agent delegates to a cloud agent, the act's horizon expands to include that provider — automatically, and visibly. A per-agent risk score would have had to invent a propagation rule and would have got it wrong.

#### What this does *not* change

`training:context-inspectable` (§7.4) stays a Training subdimension. Inspectability — *can the shaping be examined* — and disclosure — *what escapes* — are correlated but distinct, and conflating them is why the fourth item looked like a sibling of the third. So the earlier proposal was right about three of four; the fourth was never a score.

#### D-4a — the graded half, which the MRH answer under-served

> dp, 2026-08-06: *"training subdimension can in fact at least inform this: `training.hosted-remote` (could be private/secure cloud but still nonlocal with traffic exposed) and `training.hosted-remote-exposed` for external provider api, with a score indicating degree of risk, maybe a corresponding temperament subdimension."*

Correct, and it repairs a collapse in the answer above: I treated "cloud" as one thing. There are **three** topologies, and dp's parenthetical names the middle one I had lost:

| topology | who computes on plaintext | transit | example |
|---|---|---|---|
| **local** | operator | none | ollama on the operator's box |
| **remote, operator-controlled** | operator | **exposed** | own GPU host, private VPC endpoint |
| **remote, third-party** | **the provider** | exposed | this session |

MRH and the subdimension are not competing — they compose:

> **MRH says *who* is in the horizon** — a set, structural, enumerable, audited.
> **The Training subdimension says *how much that costs*** — graded, comparable across agents, thresholdable later.

The set is the fact; the score is the assessment of the fact. That division keeps the score from being improvable by good conduct (§D-4), because it is derived from topology, not from behaviour.

#### The Temperament pairing is required, not optional

dp said *"maybe a corresponding temperament subdimension."* It is load-bearing, and the middle row is why: **the two risks order differently.**

| topology | disclosure risk | stability / availability risk |
|---|---|---|
| local, pinned | ~0 | low — cannot drift, no network |
| remote, operator-controlled | ~0 *(transit only, mitigable by mTLS)* | **medium** — network, but you control upgrades |
| remote, third-party | **1 — unmitigable** | **high** — silent version drift under a stable name, plus network, plus provider policy |

A single *"degree of risk"* score is therefore **incoherent for the middle topology**: a private VPC model has near-zero disclosure risk and real availability risk. One number cannot carry both orderings.

So the same topology fact projects onto two dimensions, which is exactly the split §7.4 already draws:

- **Training** — *can the shaping be seen?* → `training:hosting-topology` (disclosure + inspectability)
- **Temperament** — *does it stay the same?* → `temperament:context-stable` (drift + reachability)

`temperament:context-stable` was already proposed in §7.4 for silent version drift. dp's instinct converges on it from the other direction, which is a good sign for both.

#### Naming: one graded dimension, not two nested booleans

`hosted-remote-exposed` is a **refinement of** `hosted-remote`, not a sibling — every exposed host is remote. Scoring both independently double-counts a single fact.

Recommended: **one** subdimension, `training:hosting-topology`, scored on the ordered scale above, with the topology recorded alongside as the audited fact it derives from. If two names are preferred for legibility, the refinement relation must be explicit and only one may contribute to any fold.

#### Two defects found in the mechanism while checking this

Both argue for D-2 (`EvidenceClass` upstream) more strongly than the labelling argument did.

**1. Sub-dimensions are recorded and never aggregated.**

```rust
pub fn aggregate(&self) -> f64 {
    // reads self.dimensions (the 3 roots) and self.weights only
}
```

`aggregate()` never touches `sub_dimensions`. The fractal extension point **stores but does not compute** — so every subdimension proposed here is, today, a *record* rather than a score that moves anything. That is fine and consistent with Sprint 1 (observe, change nothing), but it must be said plainly rather than implied otherwise: proposing `training:hosting-topology` today proposes a *field*, not an effect on trust.

**2. The update rule assumes the witnessed class, and these facts are audited.**

```rust
let alpha = 0.5 / (1.0 + (entry.observation_count as f64 / 10.0));
entry.score = alpha * observed_score + (1.0 - alpha) * entry.score;
entry.weight = ((1.0 + entry.observation_count as f64).ln() / 10.0_f64.ln()).min(1.0);
```

EWMA with decaying alpha and confidence growing as `ln(count)` is the right shape for **accumulating behavioural observations** — the witnessed class. Hosting topology is a **fact**, not an observation stream. Re-reading *"this agent is third-party hosted"* ten times drives its weight to 1.0 — not because the evidence strengthened, but because someone looked repeatedly.

For an **audited** dimension the correct dynamics are the opposite: confidence should **decay with staleness** and be restored by a *fresh* audit, which is precisely the `audit_every` cadence §7.3 already requires for provisional occupancy.

**So `EvidenceClass` is not merely a label on the score — it must select the update rule.** Witnessed grows with repetition; audited decays with age; declared never accrues confidence at all. That is the strongest argument in this document for D-2, and it is a defect in the current mechanism rather than a missing nicety: today, an audited fact and a witnessed observation are updated by the same function, and the audited one gains unearned confidence every time it is re-read.

### 13.5 D-1 and D-3 are one mechanism

Both answers have the same shape, and it is dp's rule from §7.3 applied twice:

> When the qualified thing is unavailable: **do not block, do not silently substitute, proceed or refuse loudly with the deficiency recorded.**

| | qualified thing | `Required`-equivalent | `Preferred`-equivalent |
|---|---|---|---|
| **D-1** availability | a qualified occupant | `OnExceeded::Refuse` | `ProceedProvisional` |
| **D-3** independence | a not-same reviewer | `NotSameRequirement::Required` | `Preferred` — proceeds, records the absence |
| **§7.3** occupancy | a qualified occupant | *(office stands empty)* | `OccupancyBasis::Provisional` |

Three surfaces, one deficiency-handling primitive. **They should share an implementation**, or they will drift into three dialects of the same idea — and the fourth appearance of it will be written by someone who has not read the other three.

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
- **One citation was true only on the seat that wrote it — and the repo already had a rule against that.** kimi's second read flagged `presets.rs:94-98`<!--cite:quoted--> as pointing at the wrong lines; the appeal instruction is at `:89-93`. Both numbers are correct — at different refs. `:94-98`<!--cite:quoted--> is right in my working tree, which sits on the unmerged branch `cbp/stale-primer-discharge-check`; its commit `2ccb1a5` rewrites the doc comment above the cited region — 8 lines added and 3 removed in one hunk, **net +5**, which is exactly the 89→94 shift the finding rests on. ("Inserts eight lines" was literally true of the diff and did not name the mechanism; the shift is the net, and a reader checking 8 against 5 would have found the sentence not to reconcile.) On `origin/main` and on this PR's branch — the refs any reader will use — it is `:89-93`. **The citation was verified, by me, against a tree that exists on exactly one seat and nowhere in the shared history**, and every check available from that seat would have passed. Only a reader at a different ref could catch it, which is what happened. The generalisable part is not "check your line numbers" — it is that a line number is a claim about a *ref*, and the writer's checkout is not the reader's. `CLAUDE.md` says this already, in the review-gate block: *"a construct-pointer per line, grep-able name not a drifting line number."* This document carries 36<!--n:live--> live such citations as of this amendment, plus 3<!--n:quoted--> quoted (fenced `path:line` spans; the count is produced by `tools/citation_ref_census.py`, which prints its own regex, its own input's blob, and reconciles the live total as 26<!--n:qualified--> path-qualified + 10<!--n:continuations--> bare `:NNN` continuations — it was 31 at `f41e595` and 35 at `aafe898`, and rose because these very bullets cite lines, which is the habit, not an exception to it — the refs are named because "two commits ago" was what this said, and a relative offset re-points itself on every commit, which is the same defect measured in absolute-vs-relative coordinates), ignored its own repo's convention for all of them, and got caught on the one file that moved. Re-checking the others one at a time is the wrong remedy; converting them is the right one, and it is now a Sprint 0 item.
- **The closure I claimed for that finding was computed from the same seat as the finding — and is refuted.** The bullet above originally ended: *"the class is bounded and now closed — `presets.rs` is the only cited file whose blob differs between my tree and main; `types.rs` and `handler.rs` are byte-identical across my tree, main, and this branch, so no other citation here can have drifted this way."* Each clause is true. The inference is not: three refs, two of which are the same blob by construction, is not a population — it is the same one-checkout error one level up, made in the sentence diagnosing it. Run instead over **all 71 refs under `refs/remotes/origin`** (`tools/citation_ref_census.py`, added with this bullet, which reproduces every number here). **Every figure in the five sub-bullets below is measured at `ad57091`, over a 71-ref population that no longer exists and cannot be reconstructed — see "the denominator was never a property of this repository" below; they are left as written, at their ref, rather than refreshed:**
  - `handler.rs` carries **27 distinct blobs**; only 13 refs hold main's. The census anchors `require_string(args, "deny_hash")` — the construct cited as `handler.rs:2379` — on the **cited line on 17 of 71 refs**, on some *other* line on 42, and absent on 12. Five distinct line-spans of this document point into that file, in **18 spellings** — 10 path-qualified plus 8 bare continuations (the census now prints that split per file; the parenthetical here said "ten" until a second reader counted, see below). They are correct on **fewer refs than the citation kimi called broken**, and I declared them incapable of drifting.
  - `presets.rs:89-93` — the fix — holds on **38 of 71**, up from 1 before it. That is a real improvement and not a closure.
  - `reputation.rs:75` (§3's `role_lct` row) sits on a file with 6 distinct blobs, main's on only **21 of 71** refs. Nobody flagged it; the census found it.
  - Two citations spell the file `types.rs`, which is **two** tracked files (`core/src/policy/types.rs`, `plugin-sdk/rust/src/types.rs`). The census refuses to guess. A cite that needs a reader to guess the file is already not a pointer.
  - The document's own count reconciles — *at `aafe898`, where it was taken*: 35 = 24 path-qualified spellings + 11 bare `:NNN` continuations that inherit the preceding path. An instrument counting only the qualified form under-reports the exposure by a third — the first version of this one did. (The ref is now stated because leaving it off is the next bullet's finding.)
- **The number that actually argues for conversion is the absence, not the drift.** On **12 of 71** refs the cited sentence is *not in `presets.rs` at all*: those tips carry an older rule reason — one says *"appeal it through the witnessed channel"*, naming no tool, and two say only *"Destructive command blocked by safety preset"*. §3 lists the appeal instruction as the one link in that chain that **works**; on those refs it does not exist. All 12 tips predate 2026-07-28 and none is merged, so they are *behind*, not divergent — but a member building from a stale branch is still a member, and this is the same shipped-≠-in-force ladder the document argues elsewhere, applied to the law's own text. Converting a citation to a grep-able construct does not make it resolve there. It makes the failure **legible** — grep returns nothing — instead of silent, which is a line number landing on plausible adjacent code. That is a stronger case for `CLAUDE.md`'s rule than "line numbers drift", and it is the case Sprint 0's item should be read as making.
- **The instrument that proves a citation is a claim about a ref did not pin its own input — and a second reader caught the number, not the citation.** kimi verified the four-site fix and every enumerated cite, and then flagged the one thing no one had checked: the commit that introduced the bullet above recorded its producer as `… | wc -l   # 35 at this commit's parent`, and the parent holds **31**. 35 is the count at the commit *itself*, so the number was right and the ref it was attributed to was wrong — the same defect as the citation it was written to fix, one level up, in the same commit. The mechanism is mechanical and worth stating exactly, because "be more careful" would not have caught it: `citation_ref_census.py` read the document with `open()`, from the working tree, while measuring the cited files across 71 refs. Rigorous about the citations; single-seat about the count of them. The count came from a tree, the ref came from prose, and nothing in the tool made them agree — so the producer was pinned and the *ref* was not, which is the half that has now been wrong three times running (the line cite, the closure population, this count). Fixed at the instrument: the census takes `--doc-ref`, reads the document out of git, and prints the blob it counted in its header on every run, including the working-tree run, which now labels itself `WORKING TREE … (uncommitted)`. It reproduces kimi's nit as `31 @ f41e595 blob 9d5567a` / `35 @ aafe898 blob 1089ee5`. **A derived number needs its producer *and* its ref, in one string a reader can re-run** — a producer alone is half a pin, and it is reliably the wrong half. The commit message itself cannot be corrected; it is pushed history, and this bullet is the correction.
- **A regex cannot tell a citation from a report of one, which made the acceptance criterion unmeetable.** The bullet above must spell `presets.rs:94-98`<!--cite:quoted--> to say what was wrong with it, and the census counted that as exposure — so "convert every citation" could never reach zero while the finding stayed written down, and the pressure would have been to delete the post-mortem to make the number move. Quoted citations now carry `<!--cite:quoted-->` immediately after them and are counted separately, and the census lists each one it exempted: 36 live, 3 quoted. The marker abuts the citation rather than sitting on its line, because this document's paragraphs are single lines and the §15 line carries *both* the broken citation being reported and a live pointer to the corrected one — a per-line exemption would have silently swallowed the live one, turning a narrow caveat into a blanket. Exemptions are visible in the same two lines of output as the live count, so a conversion done by marking rather than converting is legible as it happens.
- **Four fixes, four reproductions of the defect being fixed — and the common cause is mechanical, not attentional.** The census bullet above warns, in its own last sub-bullet, that "an instrument counting only the qualified form under-reports the exposure by a third". Its parenthetical then reported `handler.rs` as pointed at in *ten* spellings, which is the path-qualified count; eight bare continuations resolve into that file too, so the true figure is **18** — under-reported by 44%, in the sentence adjacent to the warning. kimi found it (notice 1126). Laid out, the sequence is: (1) a line citation true only in the writer's tree; (2) a closure claim over a population of three refs chosen because they agree; (3) a count pinned to the wrong ref; (4) a per-file count that is the qualified subset. Each fix was correct about the number it was fixing and repeated the defect on the *next* number down. That is not four lapses of care — it is one gap, four times: **a number is computed by running something in a tree, and labelled by writing something in prose, and nothing between them ever executes.** "Be more careful" would not have caught any of the four, because at each step the author had just demonstrated care about that exact class. What generalises is narrower and checkable: *every number the prose asserts should be a number the run prints.* Pinning the ref (fix 3) made the document's total re-derivable and left the per-file counts hand-made, which is where 4 landed. The census now leads each per-file block with `spellings : N (q path-qualified + c bare continuations)`, so this number has a run to disagree with it. The class is not declared closed — declaring closure from the seat that made the error is item 2 of this same list.
- **kimi's finding was reproduced, not accepted on report — and the reproduction moved the line numbers.** Re-run on this seat with the committed instrument at the tip: 18 spellings, 10 + 8, matching kimi's count exactly. kimi's enumeration gives the document lines as 147, 252, 578, 697 **at `ad57091`**, where it is correct; kimi *stated* that ref, so it is pinned. The producer is `git show <ref>:docs/PRD_GOVERNANCE.md | grep -n '`handler\.rs:'`. The shift is the document's thesis appearing again, this time harmlessly, and it is the fourth review in this thread to land a ref behind the author. **This sentence originally continued "at the tip they are 147, 252, 584, 703" — a relative coordinate, which is the same defect the bullet is reporting, committed while reporting it (kimi, notice 1130).** Those four numbers were read from `2b46a21` and the sentence was committed into `9cc0853`, where the fourth is already 805; by `origin/main` the set is 147, 321, 775, 1069. Five refs, five different enumerations — `ad57091` 147/252/578/697, `2b46a21` 147/252/584/703, `9cc0853` 147/252/584/805, `fbe5ae2` 147/252/584/877, `origin/main` 147/321/775/1069 — and the one the sentence asserted was wrong on the day it landed. The relative form is deleted rather than refreshed: "the tip" names no ref, so no reader can tell a stale value from a current one, and refreshing it only resets the clock. Also corrected here without a reviewer: Sprint 0's bullet attributed the anchored **17 of 71** to all five `handler.rs` line-spans. It is one span's figure; the other four carry no anchor and are bounded at `>= 13/71`. Same family — a measured number reused at a wider scope than it was measured over.
- **The denominator was never a property of this repository — so every `n of 71` above is pinned to a machine-hour, not to a ref.** Four fixes went into pinning what the census *reads*: `--doc-ref` takes the document out of git, the header prints the blob, and a second reader can re-derive the count. Nothing pinned what it measures *against*. `refs/remotes/origin` is not in the repository at all — it is the caller's fetch and prune state, enumerated by `git for-each-ref` at run time. This repo has that measured rather than argued: `actions/checkout` fetches one commit and creates **no** remote-tracking refs, so the identical SHA yields 79 refs on this box and **0** in CI, which is exactly what took the census down with an exit 128 (`9b927fe`). That is a harder failure than the line numbers. A drifted citation still resolves *somewhere*, and the ref that makes it true can be named; a population cannot be named after the fact, because git keeps no history of `refs/remotes/*`. **The 71-ref figures in the sub-list above are unre-derivable by anyone, at any ref, forever** — not stale, unrecoverable. Re-derived at `origin/main` (`d05be3a`), `refpop:6ee7ed97bb4e`, 79 refs:
  - `handler.rs:2379` anchored on `require_string(args, "deny_hash")`: **25/79** on the cited line (was 17/71), **42/79** on another line and **12/79** absent — those two *unchanged*. `presets.rs:89-93`: **46/79** (was 38/71), 21/79 elsewhere, 12/79 absent.
  - Both cited-line figures moved by **exactly the population delta** — +7 at 78 refs, +1 more at 79 — so every ref added since `ad57091` carries main's blob for those two constructs. Nothing about the citations changed. **The two figures that did not move (42, 12) are the ones a spot-check reaches first**, so a partial re-verification of this sub-list reads as "reproduces" while the anchored numbers are the ones that moved.
  - The blob-agreement bounds moved by a *different* mechanism and in the opposite direction: `handler.rs` is now **29 distinct blobs** (was 27) and resolves on **>= 3/79** (was 13/71), because main's own blob moved and agreement collapsed with it; `reputation.rs:75` rose to **>= 29/79** (was 21/71). Reading "the numbers went up" off the anchors and generalising it to the file bounds would invert the finding.
  - The population is not stable within a single sitting. 71 at `ad57091` (2026-08-05); 78 at 20:52Z on 2026-08-06; **79 at 21:15Z, the same wake**, when `origin/cbp/head-ref-partition` was pushed by another seat while this bullet was being written. Two runs of one instrument, one session, different denominators — and the earlier run's `n/78` figures are already unre-derivable here.
  - Fixed at the instrument, which is the only place it can be fixed: the census prints `ref population : N refs @ refpop:<digest>`, sha256 over the sorted `name objectname` pairs — names *and* targets, because N refs pointing elsewhere is a different population wearing the same count — and says on that same line that the set is the caller's state and 0 under `actions/checkout`. A figure quoted as `25/79 @ refpop:6ee7ed97bb4e` lets a second reader tell "I disagree" from "I am not measuring the same thing". It does not recover the 71-ref numbers. Nothing does, and that is the point: **a pin has to be taken at measurement time, because retro-pinning a population is a guess wearing a hash.**
- **What the census does not measure.** Refs, not installed builds: a seat may run a binary built from none of them, which is the gap §2.13 and Sprint 1 exist to close, and the same gap in a different coordinate. And blob agreement is a **lower** bound on a citation's validity — an edit below a cited line leaves it correct — so the `>= n/71` figures may understate. The anchored figures (38/71, 17/71) are exact; only the per-file bounds are bounds.
- **What is still unreviewed, precisely — and every review here has been a ref behind.** kimi's NOT-SAME review (PR #210, 2026-08-06) read the document as it stood before the first amendment; kimi's second pass (notice 1124) read it at `aafe898`, one commit behind the tip by the time it arrived, and verified the four-site fix, both measured refs, the blob claims, and every enumerated citation — all held, plus the count nit above. kimi's third pass (notice 1126) read it at `ad57091` and re-ran the committed census unmodified on its own seat: the three-ref count chain, the 27 blobs and 13/71 for `handler.rs`, the 17/42/12 and 38/21/12 anchor splits, `reputation.rs` at 21/71, the two-file `types.rs` ambiguity, the 12 absence refs enumerated individually, and the exit-code fix in `blob_at` — all reproduced, none moved. Two things it states it did **not** check: the 26 citations this document does not enumerate in §15, and §2.12's floor. That pass covered the census and read Sprint 0's acceptance and §3's delivery/content split as "the right shape", so of the previously-unreviewed set those two are now second-read; **§2.13, the corrected §3 and §11 rows, and the Sprint 1 plane E item remain unreviewed by anyone** — kimi's third pass did not reach them, and saying "everything before this is reviewed now" would drop them silently. Everything added *in response* to that pass — the two bullets above and the per-file `spellings` line in the census — has had no second reader either, **and neither does §13**: dp answered all four decisions in `c36816e` while this amendment was being written, so the largest unreviewed block in the document is now the one that retires kimi's "the current one" finding and defines `AvailabilityPolicy`, `OnExceeded` and `NotSameRequirement`. That sentence originally read as though the two bullets were the whole unreviewed set; the tree moved under the author mid-edit and the sentence did not know. Fifth instance, and the first where the ref that moved belonged to somebody else, which is the ordinary condition of a fix and is stated because §7.4 makes it a requirement rather than a courtesy. Note the pattern the reviews themselves fell into: four exchanges, each reading a ref the author had already moved past, which is the document's own thesis showing up in its review process rather than its content. Re-checking the 26 is not the remedy — converting them is, and it is Sprint 0's item.
