# PRD — one gate, thin shims: consolidate the per-harness hooks onto the shared core

**Status**: **PARTIALLY IMPLEMENTED; convergence sprint active.** The current integrated measurement finds 67.3% of law-bearing code still in seat files, four forked Gemini predicates, divergent engine loaders, and untyped per-seat extraction domains. The A-G train established a shared daemon authority path and substantial shared predicate code, but it did not deliver one executed gate. The current completion contract is [SPRINT_ONE_GATE_EXECUTED_AUTHORITY.md](SPRINT_ONE_GATE_EXECUTED_AUTHORITY.md). This PRD remains the architectural history and source of earlier acceptance criteria; any statement below that A-G completed “one gate” is superseded by the measured sprint status.
**Author**: claude-code (CBP), 2026-08-11
**Motivating finding**: the shared gate core (`plugins/_shared/hestia_gate_core.py`) is **built but not wired** — it says so at line 103 (*"NOT WIRED. Nothing imports this yet."*). The live gates (codex, kimi) are the **pre-hardening hand-copies**, so security fixes that already exist in the core are absent from the enforcing hooks.
**Directive (dp)**: *"common gate whenever possible, per-harness shims call the common gate, with local adjustments only as needed for the specifics of the harness. otherwise it is not maintainable and a massive security risk … fix the procedure, not one message."*
**The goal, sharpened (GPT):** one implementation is necessary but not sufficient — **the goal is one authority path.** An authenticated agent acts through an approved harness shim into one approved gate core that decides from a validated policy snapshot. That is `PRD_GOVERNANCE.md`'s invariant; this PRD is how the gate mechanism stops contradicting it.
**Relates to**: `PRD_GOVERNANCE.md` (the invariant), Decision 0017 (the authority-bearing closure), `PRD_CONFIG_IN_VAULT.md` (a governance input the party can write is a hole — same shape as the gate's own code + loader), the git-manager note.

---

## 1. The problem, demonstrated not theorised

There are **N hand-maintained copies of a security predicate** — one per harness (claude-code, codex, kimi), plus an installed `society_pre_tool_use.py` not even in the repo. A shared core that would end this exists and is substantial, but **nothing imports it** except one telemetry helper. The consequence is not messiness; it is that **the enforcing gates run older, weaker logic than the fixed version already in the tree.**

Proven this session:
- The per-request timeout fix (`0.5 → 5.0`, env-overridable) landed in the society gate on 2026-08-07 and **never reached the claude-code hook** — a four-day divergence in a fail-closed threshold, found only because a member kept fail-closing.
- The fail-closed **message** lives in each harness's copy; fixing it meant editing one installed file by hand, which gate-self-access (correctly) refuses — so it could not be done in-session at all.
- The **hardened scope predicates** (path-boundary containment; resolve-before-segment traversal) exist **only in the unwired core**; codex and kimi still carry the **pre-hardening substring/lexical forms** — the exact bug classes the core's own comments document as fixed (§3.3).

## 2. The principle, and why it is a security requirement first

> A security predicate has exactly one implementation, deciding from one authenticated authority source, executed through one verified loader. Per-harness behaviour is a *parameter*, never a second copy.

Maintainability is the obvious case; **security is the load-bearing one**:
1. **N copies = N places to fix, N chances to drift** — already realized on security paths (§3.3).
2. **The posture becomes per-harness by accident** — the constellation is only as strong as its weakest copy, and nothing tracks which is weakest.
3. **Only one copy is pinned** — the `member_lct` census and the self-tests hold the claude-code hook to its invariants; the codex/kimi copies are held to nothing.
4. **More copies = more audit surface**, reviewed once then diverged.

## 3. Current state — measured (audit 2026-08-11 at `a019141`; GPT corrections folded in)

### 3.1 What the shared core provides (substantial — NOT yet authoritative)
`evaluate(event, profile, workspace, policy) -> Verdict` — the local egress+scope policy, and it **never calls `sys.exit`**, so a shim cannot mistake "core returned nothing" for allow. Plus the single `REMEDIES` table, the `_deny(rule, …)` constructor (a rule id, not a sentence), hardened `path_in_scope`/`command_in_scope`/`_under_temp_root`, `resolve_agent_policy`, the shim-contract types, and `record_gate_unavailable`. The core is transport-free by design: no HTTP client, no `REQUEST_TIMEOUT_S`, no `sys.exit`.

**But it is not authoritative yet (GPT #3):** `evaluate(..., policy=None)` calls `resolve_agent_policy(profile)` with no `vault_reader`, which can fall back to the **local replica** — and the core's own comment admits that replica is time-bounded but **not authenticated** (no MAC/signature). `PRD_GOVERNANCE.md` requires the core to decide from a *validated in-memory vault snapshot*. So "wire the core" is not "the core is done" — cutover has a hard precondition (§6.F, §7).

### 3.2 What is duplicated (should be one copy)
codex and kimi each re-implement the entire local decision (`detect_workspace`, `load_in_scope`, `identity_role`, `launch_cwd_repo`, `FORBIDDEN`, `READ_CLASS`, `path_in_scope`, `command_in_scope`, the member-address allowlist) in **pre-hardening** form; a witness/attestation + mini-MCP client block (~150 lines) is near-identical across all three; `_attempted_summary` exists in three copies with three behaviours; and the budget contract is unshared (`REQUEST_TIMEOUT_S`/`TOTAL_BUDGET_MS` only in claude-code, ad-hoc timeouts in codex/kimi).

### 3.3 Live drift with security consequence (fixed in core, still broken in the shims)
Same bug **classes** the core's comments already document as fixed, still live in the enforcing codex/kimi copies:
- **Path-boundary written as a substring test** — temp-root and workspace containment use a prefix/`in` check where a boundary check is required.
- **Scope check reads a path's head lexically before resolving `..`** — a granted first segment fronts for an ungranted resolved target.
- **Refusal remedy names a tool that does not exist** (`request_scope`) instead of the real `hestia_request_scope`/`hestia_appeal`.
- **The deny recorder varies by vendor** — codex records refusals to the chain; kimi records only inside a bare `except: pass`, so the trust chain's denominator already differs by harness.
- **kimi cannot distinguish a real deny from an infra fail-closed** (codex can), so it mis-scores infrastructure failure as member conduct.
- **The deny/infra conflation is measured in production, not hypothetical (kimi, PR #357):** commands merely *naming* the claude-code hooks directory (spelled here in paraphrase — the verbatim marker string in file content draws the very fail-closed deny this bullet describes) drew `deny [fail-closed] — no policy verdict (daemon path failed)` while marker-free probes passed around them — read-only inspection manufactured escalations, and (separately measured) the fail-closed layer leaves **no deny record** while the classifier layer does. Scope note: the daemon-side marker policy-eval error itself is out of this PRD's scope (§9); what consolidation fixes is the shim half — §6.E gives every harness codex's real-deny-vs-infra discrimination, and §7.1(9) requires degraded verdicts to be recorded, so infra failure stops being scored (or silently not scored) as member conduct.

### 3.4 Genuinely harness-specific (stays in the shim)
Engine exit contract / fail-open reality (all Claude-lineage engines fail OPEN on timeout → each gate is the fail-closed party, but the *rendering* differs); stdin event schema + parse (codex also sees `apply_patch` and MCP calls); identity-*location* facts. The decision **topology** difference (claude-code daemon round-trip vs codex/kimi local-decide-then-witness-and-delegate) is real, but becomes a parameter/injected callback of the **shared-mechanism** module — never a parameter of LAW, which stays transport-free (GPT 2nd pass, wording) — not a fork.

### 3.5 Repo-integrity flags
`society_pre_tool_use.py` is referenced by claude-code's self-protection and by codex/kimi's `CLAUDE_PRE` default but is **absent from the repo** — it exists only as an installed copy, so the guard protects a filename the tree lacks and the delegation target disagrees with the protected filename. Reconcile before §6.G.

## 4. Target architecture

- **LAW** = the core: `evaluate() -> Verdict`, `REMEDIES`, every scope/egress predicate. One copy, amended only by due process, pinned by tests, deciding from an authenticated policy snapshot.
- **SHIM** per harness, reduced to seams that **cannot widen authority**: `parse_event(raw) -> NormalizedEvent`, `render(verdict) -> (exit_code, stderr)`, and identity-*location* facts + a transport callback. **No scope logic, no forbidden list, no remedy text, no decision.**
- **AGENT** = `AgentPolicy` from the authenticated vault snapshot.

**HarnessProfile must be pruned (GPT #2):** today it carries `mode_env`, `forbidden_extra_env`, `launch_cwd_env`, `identity_path`, `workspace_env`, `default_role` — several of which change reachability/verdicts, so a shim that chooses them is deciding policy by the back door. Keep the profile to parse/render/transport/identity-**location** facts that cannot widen authority. **`mode` and extra restrictions move to law or vault policy; launch-cwd widening becomes an explicit session capacity/grant, not an environment incidental.**

**What moves into the SHARED-MECHANISM module (not LAW):** the daemon/witness MCP transport (injected, so the core stays transport-free), and the **budget/timeout contract** (`REQUEST_TIMEOUT_S`/`TOTAL_BUDGET_MS`, env-overridable). Timeouts govern availability and fail-closed behaviour — they are mechanism, not scope/egress law (GPT #5).

## 5. The precondition — protect the effective governance CLOSURE before adoption

My first draft said "add the core to the self-protection markers." GPT corrected both the fact and the scope:

- **Fact:** current main **already** has `hestia_gate_core.py` in claude-code's `_GOVERNANCE_FILES`, and `gate_self_protection_test.py` asserts membership *and* real Write/Edit/Bash refusal. So the core is not unprotected in the Claude adapter.
- **The real gap:** that self-protection exists **only in the Claude adapter.** kimi, codex, gemini, cursor have **no self-protection mechanism at all** — a member editing its *own* hook is caught by no one. So the precondition is not one filename; it is that **every harness that begins depending on the common core must be unable to treat a write to the effective governance closure as an ordinary act.**
- **The closure is bigger than the core (GPT #7):** authority-bearing surfaces include the core, the shared-mechanism/transport module, the **loader/digest-selection path**, the registration/config that selects the shim, the installers/manifests that put it in force, and any exemption ledger. **A write that can redirect *which* core executes is equivalent to a write to the core.** Tie this to Decision 0017's authority-bearing closure, not to a file list.
- **Governance-access, not self-access (dp, 2026-08-11):** the check must refuse a write to *anyone's* governance closure, **regardless of who is accessing** — not merely a member's *own*. Self-scoping is a **delegation hole by construction**: member A editing member B's gate is not A's "self", and the fleet delegates freely, so a one-hop handoff defeats a self-access check. The protected set is therefore the **union of every registered plugin's closure** (above), and the refusal fires for **any accessor**. This is also *why* the check belongs in the **common core, not the shim**: a per-shim self-check is duplicable-with-drift *and* delegable; one core-resident governance-access check, called by shims too thin to hold a decision, is neither. (The claude adapter's current matcher already matches governed filenames "anywhere … so this holds for a peer's copy as well as mine" — this makes that intent the ratified rule and moves it to the core.)
- **Criteria in the vault, extensible without touching the core (dp, 2026-08-11):** the *match criteria* — the per-plugin closure definitions the governance-access check consults — live in the **vault**: **inspectable** (auditable) but **not easily writable**. A write to the criteria is itself a governance act (escalatable), and the criteria are **self-referentially inside the closure they define** — so they cannot be edited to un-protect a target without tripping the very check they feed. The core **reads** the criteria; it does not hold them as code. Consequences: (1) **registering a new plugin protects it by adding its criteria to the vault — no core edit** (closed for modification, open for extension; adding a plugin must not require a governed write to the core every time); (2) a **minimal fail-safe literal** (the core's own closure) stays in the core/shim as the **degraded floor** for when the vault is unreadable — a vault-read failure must not disarm protection, the same fail-safe-replica reasoning as the closure list and the degraded-mode Tier-2 backstop (§7.1(9)). This makes the vault the authoritative, extensible source and the literal the floor — tying directly into the vault-as-cache architecture (PRD_TRUST_CACHE).
- **Integrity by attestation, not whack-a-mole (dp, 2026-08-12).** Once core governance lives in the vault, the only writable governance surface left on the filesystem is the **thin shims** — a small, fixed set. So the matcher no longer has to *win whack-a-mole* against every write path to governance *files* (Edit/Write/`rm`/`cp`/`>`/`sed -i`/the `settings.json` registration bypass — the source of the years of FP fixes): governance is no longer *in* matchable files. The primary guarantee shifts from **prevention-by-matching** (always incomplete) to **detection-by-attestation**: the vault stores each shim's (and the core's) **expected hash**, the installed shims are **verified live against the vault-stored hashes**, and any divergence — tampered, stale, or wrongly-installed — is flagged in the dashboard as **"miswired."** This is §7.2's *declared → deployed → observed* made continuous and pointed at the shim layer, and it means the write-position governance-access check is **lightweight defense-in-depth**, not a load-bearing monolith. (Degraded interaction: verifying a hash needs the vault; a vault-unreadable state is the degraded floor — deny-writes — §7.1(9). And a shim reads as "miswired" precisely when its live hash ≠ the vault's, which is also how a stale-after-deploy shim is caught, closing the "installed ≠ enforced" gap for the shim layer.)

This is **step B** below, and it must be true for an adopting harness *before* that harness imports the core — otherwise consolidation moves the entire policy surface into a place that harness cannot protect.

## 6. Ordered plan (GPT-endorsed sequencing A–G)

**A. Freeze the boundary.** Ratify four things as the refactor contract: the logical LAW/SHIM/AGENT boundary (§4, with the pruned profile), the **installed topology** (§7.2), the **authority source** (authenticated vault snapshot; §3.1), and the **degraded-mode semantics** (**RATIFIED — dp, 2026-08-11: deny-writes-allow-reads**, identical to the existing timeout posture; per-shim tighten-only; see §7.1(9), which then holds every harness to it). Nothing migrates until these are fixed.

**B. Extend the governance closure to every adopting harness — as a governance-access check in the common core, called by thin shims.** Before any non-Claude harness imports the core, every harness must enforce the **governance-access refusal**: any write to the *union* of every registered plugin's governance closure (the core, the shared-mechanism module, the loader/digest path, the registration/installer surface) is refused and escalatable **regardless of which member is acting** — self-access is delegable, so the check is accessor-agnostic (§5). It lives in the **common core**, not per shim: one implementation, called by shims too thin to hold a weaker decision. It keys on the **write position** (the actual target — redirect/`rm`/`cp`/`sed -i` target, Edit/Write destination), not any *mention* of a governed filename, so it does not inherit the marker-in-command / content-match false positives that plague the current per-shim matcher. Acceptance: a write to the core *or to the loader that selects it* is refused and escalatable **from every adopting harness and for any accessor**, asserted by a cross-harness test.

**C. Migrate one predicate family — single-harness acceptance.** Point kimi's `path_in_scope`/`command_in_scope`/`_under_temp_root` at the core. **The pilot choice is deliberate, and the pilot seat has consented (kimi, notice 1929):** kimi's gate is the weakest copy — no self-protection, no deny/infra discrimination, deny recording inside a bare `except: pass` — so piloting there fixes the most per line changed, and the seat that will live under the migrated predicates has read this plan and endorsed running first. This **closes the three live scope bypasses for kimi** with no exit-contract change. Acceptance is scoped to **kimi's shim == core** on the §3.3 inputs (kimi now denies them) plus no regression on safe inputs — NOT cross-harness identical deny (GPT 2nd pass #2): codex is deliberately still pre-hardening until F, so a "all harnesses agree" test at this point *should* fail against the measured current state. Cross-harness identical-verdict convergence is asserted at G, once every shim has migrated. (Alternative considered and rejected as bigger-bang: migrate this predicate family atomically across all adopting harnesses in C. Chosen the incremental path; the convergence proof simply moves to G.)

**D. Migrate remaining local law by import — pure predicates only.** Centralize `FORBIDDEN`, `READ_CLASS`, the member-address list, and the pure scope predicates, and replace inline deny sentences with `_deny(rule)` + `REMEDIES` (kills the `request_scope` phantom and unifies the message everywhere at once). **Delete/replace the authority-bearing legacy inputs rather than share them (GPT 2nd pass #1):** `load_in_scope` (permissive `web4` fallback), and equally `launch_cwd_repo` and `identity_role` — these read harness/local identity and cwd state to *derive authority*, which the ratified target says must come from the authenticated policy/occupancy path (`AgentPolicy`/`resolve_agent_policy` and an explicit launch-cwd grant, per §4). Centralizing them would standardize the old authority model; they get removed, not shared. D shares only common predicates/constants/remedies.

**E. Shared transport/mechanism module.** Move the witness/attestation + mini-MCP client and the budget/timeout contract into one shared module all three import — giving kimi codex's real-deny-vs-infra discrimination for free.

**F. Cut over to `evaluate()` — gated on authoritative policy (GPT #3).** codex/kimi call `evaluate() -> Verdict` + `render()`, local decision copies deleted; claude-code last. **Hard precondition:** in enforce mode `evaluate()` receives an authoritative/certified policy snapshot **or fails closed into a separately defined degraded mode.** No silent `policy=None`/local-replica fallback may become the common path.

**G. Delete second implementations and prove fleet convergence.** Remove the duplicates; reconcile `society_pre_tool_use.py` (§3.5); and prove **deployed digest convergence** (§7.2), not merely repo-level singularity.

## 7. Falsifiable success criteria

### 7.1 Source + behaviour
1. **One implementation** of each scope/egress predicate, the forbidden/member-address lists, and the fail-closed message — grep finds it once, in the core/shared module. A second copy anywhere is a red test.
2. The three live bypasses (§3.3) **leave no divergent verdict across harnesses** — after migration the differential test gets an identical deny from every shim. This is *not* "no verdict changes" (see §9): the stale harnesses change from their weaker verdict to the common deny, which is the point — the criterion is **convergence**, not preservation.
3. A refusal from any harness names a **tool that exists**, asserted by resolving the named tool.
4. `load_in_scope` and the permissive `web4` fallback are **gone**, not shared.
5. In enforce mode, `evaluate()` **never decides from an unauthenticated policy** — it receives a certified snapshot or takes the defined degraded path; asserted by a test that injects `policy=None` and requires degraded-mode, not allow.
**Criterion 9 — degraded mode is defined, tested, and recorded. It is the fleet's only fault isolation after consolidation (kimi, notice 1929).** N hand-copies were accidental availability-redundancy: a bug in one copy downed one harness. One core is one failure domain — a core defect now fails every seat the same way at the same time. That trade is asymmetric (for *security* faults, heterogeneity was anti-isolation: the attacker picks the weakest copy, so consolidation strictly improves that side) and it is only acceptable if the availability side is paid for explicitly: (a) the degraded-mode semantics ratified at A are implemented in the core, not per shim; (b) a test deliberately breaks the core/policy path and asserts every adopting harness takes the defined degraded path — no harness falls open, none invents its own fallback; (c) **every degraded verdict is recorded and distinguishable from a conduct deny** — PR #357 shows what the undefined mode does today: unrecorded fail-closed denies and manufactured escalations. A degraded mode that exists but leaves no trace fails this criterion. **Ratified semantics + trigger (dp, 2026-08-11):** the posture is **deny-writes-allow-reads**, and the trigger is the **daemon/referee being unreachable** — the *timeout* — NOT the local decision module, which is transport-free (opens no socket) and so stays available. This sharpens (a): the posture is **computed by the available local module** in the common case (Tier 1), with a **minimal shim-level backstop only for the rare case the module itself will not import** (Tier 2) — the one place a shim carries its own fallback, for the same reason the self-protection closure list is a fail-safe replica rather than an import (a load failure must not fall open). A shim may **tighten** the posture locally (deny reads too) but **never loosen** it. And (c)'s recording is satisfied by a **per-shim append-only diagnostic timeout log** — the fallback witness precisely when the daemon (the normal witness) is the unreachable thing — appended locally on each degraded event and reconciled when the daemon returns.

### 7.2 Deployment (declared → executable → deployed → observed) — GPT #6
Source consolidation is not deployment consolidation: one source file copied into five plugin packages drifts exactly like five hand-copies.
6. **Installed topology is defined and singular:** one host-local canonical core artifact per installed Hestia generation, imported by every shim through a deterministic/verified path. If packaging forces replicas (e.g. the codex marketplace package), they must carry the **same content digest/provenance**, and fleet deployment must **measure** it.
7. **Fleet digest convergence is observed — as an extension of the #231 build-authority mechanism, not a new instrument (kimi, notice 1929).** PR #231 (merged, live on CBP) already gives the daemon a supervisor-owned current-build manifest (`HESTIA_CURRENT_BUILD_FILE`), a `current`/`stale`/`unknown` verdict on operator surfaces, and the right fail-closed posture (`unknown` never claims health). The gate core is the same problem at a second scope: the ratified core digest goes in the same supervisor-owned manifest family, every seat reports its enforcing-core digest, and the dashboard/TUI shows per-seat current/stale/unknown. Two sharpenings carried over from the drift findings: the digest must be **self-reported by the loaded core** (the running gate attests what it imported, mirroring #231's compile-time identity), not a bystander hashing a file on disk beside it; and this is an **operator surface, not a CI check** — install-drift is structurally invisible to CI, which is exactly why #231 put it on the dashboard. gemini/cursor get an explicit **migrate-or-retire** decision if still supported. The criterion is the running gate, not the repo file.

### 7.3 Closure
8. A write to **any element of the effective governance closure defined in §5** — the core, the shared-mechanism module, the loader/digest-selection path, **the registration/config that selects the shim, the installers/manifests that put it in force, and any exemption ledger** — is **refused and escalatable from every adopting harness, for any accessor** (step B — governance-access, not self-access; §5), asserted before step C lands. A criterion that covers only core + mechanism + loader still leaves a path to redirect *which* law executes; it must cover the whole closure §5 names. A criterion that fires only for a member's *own* closure still leaves the one-hop delegation path (A edits B's gate) open; it must be accessor-agnostic.

### 7.4 Availability parity across harnesses (observed) — the timeout asymmetry must close

Today the gate **times out for kimi and codex even with the box idle**, and **never for claude** (dp, 2026-08-12). This is not (only) CPU contention (#354); it is a **structural per-call cost difference**. claude takes one lean daemon round-trip for its verdict. kimi and codex reach the society-safety verdict by **spawning a subprocess** that runs its own connect + verdict + poll protocol against the daemon, on top of their own fire-and-forget witness — so per gate call they pay subprocess spawn + interpreter startup + a separate multi-round-trip, and the society subprocess may not even inherit the raised total-budget env. Even idle, that accumulated cost blows their budget while claude's stays inside it.

The refactor should close this **by construction**: once every harness decides through the same shared path claude uses — society-safety as an in-process predicate, not a subprocess-delegated round-trip — the extra cost is gone. So the accepted state is:

10. **The idle timeout rate is equal across harnesses (≈0).** Measured over a window of gate calls with the box quiet, kimi's and codex's fail-closed-on-timeout rate matches claude's. If the asymmetry survives the refactor, the consolidation did **not** actually put every harness on the same path (they are still subprocess-delegating, or still on a heavier round-trip), and cutover (§6.F) is not complete. This is an **observed** criterion — measure the live per-harness timeout rate after deploy — the availability half of §7.2's declared → executable → deployed → observed.

**Instrument + owner (kimi review of #364).** The natural gauge is the **Class T pair-audit** (`docs/GATE_BYPASS_CATALOG.md` §17): the load-bearing pair `gate internal budget < harness hook timeout`, read **per member**. Class T is precisely the timeout-asymmetry failure this criterion forbids, and it is **silent on every other surface** — no denies, a clean witness chain, nothing logs — so a criterion measured only as "denies we happened to see" cannot detect it. Naming the instrument is therefore load-bearing, not bookkeeping: criterion 10 is that pair-audit's **idle-rate reading after cutover**, and without a named owner to run it periodically (the git-manager, §10 — Class T was flagged 2026-08-07 as something to *re-check periodically rather than trust once*) the criterion is an assertion with no gauge behind it.

## 8. The procedure fix — make the correct path the easy path

Today "update the gate" means find which of N copies, edit it, notice the others didn't get it, hand-patch each installed copy out-of-band (the in-session path is walled by self-access), and hope nothing drifts. After this: edit the core, tests pin it, the deploy installs one core + thin shims and **measures digest convergence**, and the shim is too thin to hold a decision — so a fix cannot land in one harness and miss another. The cheap path (edit one file) becomes the correct path (fix every seat, provably).

## 9. Non-goals
Not re-designing the daemon protocol, the vault, or Decision 0017's authority model — this consumes them. Not adding a new harness. **No *new* policy semantics** — but this is not "no verdict changes" (GPT 2nd pass #3): converging every harness on the already-ratified common semantics **will change current live decisions wherever a stale copy was weaker** (that is the point of closing the §3.3 bypasses). The non-goal is inventing new law, not preserving the weaker verdicts the drift produced.

## 10. Open questions
- **Disclosure.** The §3.3 bypasses are exploitable in codex/kimi now. If the repo is public, the specific inputs are tracked privately, not in an issue; this PRD names bug *classes* the core already documents, not fresh strings. Step C fixes them for kimi immediately.
- **Degraded mode (F) — promoted out of this section (kimi, notice 1929).** Whether a degraded mode exists, is tested per-harness, and records its verdicts is no longer open: it is acceptance criterion 9 (§7.1). The *choice of semantics* is now **ratified (dp, 2026-08-11): deny-writes-allow-reads**, identical to the timeout posture (daemon/referee unreachable), per-shim tighten-only, with degraded verdicts recorded via a per-shim append-only diagnostic timeout log (§6.A, §7.1(9)).
- **society_pre_tool_use.py's home.** Becomes a `society_safety` predicate in the core, or stays a distinct installed artifact? Settle before §6.G.
- **Ownership of the sync.** The deploy that installs "one core everywhere and measures convergence" is the git-manager role's job; landing this without that owner reintroduces drift at install time.

## 11. Revision note — GPT (NOT-SAME) review incorporated, 2026-08-11

GPT endorsed the direction (one logical LAW, syntax shims, agent authority from a separate policy object) and filed seven load-bearing corrections, all adopted:
1. **Closure, not one filename** — §5 corrected (the core is *already* self-protected in the Claude adapter; the real gap is the other harnesses have none) and widened to the effective governance closure (core + transport + loader + registration + installers + exemption ledger), tied to Decision 0017. Reordered as step B.
2. **HarnessProfile is not syntax-only** — §4 prunes it to facts that cannot widen authority; `mode`/extra-restrictions move to law/vault, launch-cwd becomes an explicit grant.
3. **The core is substantial, not authoritative** — §3.1 corrected; §6.F and §7.1(5) make cutover gated on an authenticated policy snapshot or a defined degraded mode, no silent `policy=None`.
4. **Delete `load_in_scope`, don't share it** — §6.D and §7.1(4).
5. **Budget/timeout is mechanism, not LAW** — §4 and §6.E put it in the shared-transport module.
6. **Source ≠ deployment consolidation** — §7.2 adds installed-topology definition and fleet digest-convergence (declared → executable → deployed → observed).
7. **Protect the closure, not only the core** — folded into §5/§7.3.

The one framing I want to keep foregrounded, because it is the whole point: **one implementation is necessary; one authority path is the goal.** GPT's sequencing (A–G) is adopted verbatim as §6.

**Second pass (GPT, on the revised text).** No architecture objection; three internal contradictions and one wording nit, all resolved:
1. **`launch_cwd_repo`/`identity_role` are authority-bearing, not shared-law helpers** — §6.D now deletes/replaces them alongside `load_in_scope` rather than centralizing them; D shares only pure predicates/constants/remedies.
2. **§6.C's acceptance couldn't hold in sequence** — codex is still pre-hardening until F, so a cross-harness "identical deny" test at C would fail against the measured state. C's acceptance is now **kimi == core**; cross-harness convergence moves to G.
3. **§9 non-goal corrected** — this is "no *new* semantics," not "no verdict changes": closing the §3.3 bypasses **does** change current live decisions where a stale copy was weaker, by design.
4. **Wording** — §3.4 topology is a **shared-mechanism** parameter/callback, not a core parameter, keeping LAW transport-free in both §3.4 and §4.

GPT's closing invariant, adopted: **one source is not enough; one authority path + one observed deployed generation is the actual invariant.**

**Third pass (GPT) — two acceptance-text defects, both fixed:**
1. **§7.1 criterion 2 was backwards** — it said the bypasses "change no verdict from any harness," which contradicts §9 (the stale harnesses are *supposed* to change to the common deny). Reworded to **"leave no divergent verdict across harnesses"**: the criterion is convergence, not preservation.
2. **§7.3 criterion 8 under-covered the closure** — it tested only core + shared-mechanism + loader, while §5 defines the closure to also include registration/config, installers/manifests, and any exemption ledger. Criterion 8 now covers the **whole** closure §5 names, so no test-passing path can redirect *which* law executes. With these, GPT has no further objection to ratification.

## 12. Revision note — kimi (cross-vendor, the step-C pilot seat) review incorporated, 2026-08-11

Kimi read the PRD at main (notice 1929) and filed four points; all four adopted, two with sharpenings:

1. **Pilot rationale made explicit, with consent** — §6.C now states *why* kimi goes first (weakest copy: no self-protection, no deny/infra discrimination, deny recording in a bare `except: pass` — the pilot fixes the most) and records that the pilot seat endorsed running first. A migration whose first subject consents on the record is a different governance act than one imposed.
2. **§3.3 gains its sixth instance** — PR #357's measured evidence that the deny/infra conflation is live: marker-naming read-only commands drew unrecorded fail-closed denies and manufactured escalations. Sharpening: the daemon-side marker policy-eval error stays out of scope (§9); the PRD claims only the shim half (§6.E discrimination + criterion 9's recording requirement). Meta-datum: adding this bullet to this PRD *itself* drew the fail-closed content-match deny until the marker was paraphrased — the defect censored its own documentation, in a temp-worktree doc file the gate does not otherwise protect (escalation `4c40012185cbee3f`, left for dp to deny as a content-match false positive).
3. **Fault-isolation inversion → acceptance criterion 9** — kimi's strongest point: N hand-copies were accidental availability-redundancy, one core is one failure domain, so degraded mode is the only fault isolation left and cannot stay an open question. Adopted as §7.1 criterion 9 (defined at A, implemented in core, break-the-core test per harness, degraded verdicts recorded and distinguishable from conduct denies). Sharpening: the inversion is **asymmetric** — for security faults heterogeneity was anti-isolation (the attacker picks the weakest copy), so consolidation strictly improves that side; criterion 9 is the price of the availability side, not a reason to keep the copies.
4. **§7.2 rides #231 instead of inventing a second instrument** — the supervisor-owned build-authority manifest, per-seat current/stale/unknown, and fail-closed `unknown` already exist and are live; the enforcing-core digest is the same problem at a second scope. Two carried-over sharpenings: the digest must be self-reported by the loaded core (attest what was imported, not hash a nearby file), and it is an operator surface, not a CI check — install-drift is structurally invisible to CI.

## 13. Revision note — nomad's codex-seat field data, re-measured after the A–G train, 2026-08-14

Nomad ran the codex seat under the per-harness adapter through the hackathon weekend and filed three
field data points on 2026-08-12 (mesh notice `47e57a2f-1d96-4a08-b8f4-6be93cd927f4`; carried into PR #385
against the pre-execution text, when this PRD still read *"Not started"*). Sprints A–G have since landed,
been reviewed twice by GPT, repaired and merged, so the points are recorded here **against what the train
actually did**, not as proposals. Re-measured at `9a7f45b`; each verdict names its instrument.

1. **The codex trust-rearm hazard — mechanism CONFIRMED, trigger NOT exercised by this train, seat currently armed.**
   Nomad's description of the mechanism is exact: codex persists a per-hook-command trust hash keyed
   `"<config path>:<event>:<leg indices>"`, and a leg whose key is absent is silently skipped in
   non-interactive runs — no error, no prompt, no log line. Read at the seat on 2026-08-14: six hook legs
   are registered and **six `[hooks.state]` entries exist**, so every leg on this seat is currently trusted.
   The sharpening the re-measurement adds is the trigger condition: **the hash keys the COMMAND STRING, not
   the hook file's content.** Sprints D/E/F rewired codex *inside* its gate script; the registration was not
   touched — `plugins/codex/hooks/hooks.json` has **exactly one commit in its whole history**, the adapter's
   original landing, so no train commit changed a registered command line and no trust entry was invalidated.
   Nomad's prediction is therefore **untested by this train rather than refuted** — it stays live for the first
   codex deploy that changes a command (new leg, wrapper env var, interpreter or path change).
   The one place it *did* fire is nomad's own measured instance: a **new** PostToolUse leg added beside the
   already-trusted observe leg (`post_tool_use:0:1`). Nomad's 2026-08-08 reading (new leg skipped, sibling
   fired) and today's reading (both legs carry trust entries) are the two ends of one event — an interactive
   re-trust closed it. **Corollary, and the part that outlives the incident:** because trust keys the command
   and not the content, codex hook trust attests nothing about what the hook *does*. Content attestation is a
   separate instrument and it **landed in Sprint G** — `hestia_gate_core.core_digest()`, self-hashed at import
   and **sent on every refusal record by the unified recorder** (§7.2(7)). Nomad's hazard is an argument for
   that instrument, not a second one.

   **SENT is not PERSISTED, and the distinction is the whole lesson of this PRD applied to itself**
   (GPT audit, 2026-08-14). The shim half is deployed and does send the digest; the daemon half does not
   keep it. `tool_witness_decision` parses a fixed argument list under `additionalProperties: true`, so the
   wire `core_digest` is **accepted and silently dropped** at the boundary — filed as **#419**, which also
   records that the same door never reads `verdict_available`. Until #419 lands, the digest survives only on
   the per-shim fallback diagnostic log (i.e. precisely when the daemon is *unreachable*), which is inverted
   from intent. So the honest statement of §7.2(7)'s status is: **declared and executable and deployed on the
   producing side; not yet observable on the witness chain.** Anyone reading this section as "deployed
   generation is attested end-to-end" would be reading a claim one boundary wider than the evidence — the
   exact `shipped ≠ in force` failure the train exists to make impossible to state by accident.

2. **Witness-path parity (nomad's criterion 11) — STILL OPEN, and now measured rather than anecdotal.**
   Sprint E unified the **deny** recorder across harnesses, and `witness_decision_unified()` in
   `plugins/_shared/hestia_gate_mechanism.py` says so in its own contract: it "only ever runs on the deny/warn
   path, so no hook-clamp pressure on allows." The allow leg is still per-adapter hook wiring, which is exactly
   the asymmetry nomad reported. Two readings at `9a7f45b`, and they disagree with each other:
   - **In the repo**, codex's `hooks.json` registers only the Phase-0 observe shell hook on PostToolUse — a
     fire-and-forget append of the raw event JSON to a local `observe.jsonl`, `exit 0`, no daemon call. A seat
     installed from the tree today still gets **denials-only chain visibility**. Nomad's finding stands.
   - **At the installed seat**, `~/.codex/config.toml` registers a *second* PostToolUse leg, the codex witness
     script, which does fire `hestia_begin_action` + `hestia_record_outcome`. The allow side was fixed — by the
     per-adapter route nomad explicitly declined to keep fighting — and the tree and the seat now disagree.
   That divergence is install-drift of exactly the class §7.2 says CI cannot see, on the witness path instead
   of the gate path. **Criterion 11 as nomad stated it is not met:** witness ingestion is not a property of
   adopting the shared core, it is a property of one seat's hand-edited config. Recording it here as open, with
   the two readings that make it checkable, rather than restating it as a new criterion in §7.

3. **Post-cutover liveness probe (nomad's criterion 12) — HALF LANDED in Sprint G, in a different shape.**
   `tools/gate_class_t_probe.py` reads per-member reached-verdict vs infra-fail-close rates from the reputation
   ledger and calls out the Class T signature — *a member with acts but ZERO reached verdicts, the un-governed
   twin of a healthy member.* That is precisely the state a silently-skipped gate leg produces, and the probe
   produced the pre-deploy baseline (one member at 22 infra fail-closes / 2h against ~0 for the others). What it
   does **not** do is the canary half: it reads acts that happened to occur, so an idle seat and a skipped-hook
   seat read the same. **Landed:** the passive detector. **Open:** *fire* a canary act per seat after any wiring
   change and assert the entry landed on both sides. The remaining half is the smaller one, and it is the half
   that turns "the hooks are configured" from an attestation into a check.

4. **Held-branch disposition — HOLDS, and its stated precondition has half-arrived.**
   `nomad/kiro-crush-adapters` (`1dacafc`, 2026-07-24, 17 files / +1562) and `nomad/antigravity-adapter`
   (`d63f2fb`, 2026-07-28, 7 files / +564) both still exist at origin, unmerged, with no PR. Holding them was
   right and stays right: they are per-harness gate copies of the pre-consolidation shape, and merging them now
   would add two more instances of the thing B–E exist to remove. The stated gate on migration — *after codex
   proves the rearm path* — needs restating in light of point 1: codex **is** on the shared core (D–F), so the
   "wait for the rewire" clause is satisfied, but the rewire never exercised rearm. Migration should therefore
   be gated on **the first command-line-changing codex deploy**, not on the consolidation train, which would
   otherwise read as satisfied by a train that never touched the hazard.
   Antigravity's carried-forward property gets *better* under the train, not worse: it fails closed natively,
   the only harness measured here that does, and the post-F shared path is fail-closed by contract
   (`query_society_safety` never returns allow except on an explicitly recognized daemon verdict). The migration
   now has a fail-closed target to land on rather than a fail-open one to defend against — nomad's worry becomes
   a check, not a risk.

**Left behind from the original fifth pass (PR #385), deliberately:** its Status-line rewrite (written when
this PRD read "Not started"; the line now records dp's 2026-08-13 execution directive and the A–G sprints), its
inline §6.F cutover-precondition paragraph, and its §7.5 proposing criteria 11 and 12. Re-adding proposals to a
plan that has already executed would misdate them; the two criteria are recorded above as one open, one
half-landed, each with the instrument that would close it.
