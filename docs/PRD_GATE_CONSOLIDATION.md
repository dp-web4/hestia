# PRD — one gate, thin shims: consolidate the per-harness hooks onto the shared core

**Status**: proposed — dp-directed 2026-08-11; peer-reviewed by GPT (NOT-SAME) 2026-08-11 and revised (see §11); fourth pass 2026-08-11 folding kimi's cross-vendor review (notice 1929, see §12) — the step-C pilot seat has read the plan and endorsed it. Not started.
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

This is **step B** below, and it must be true for an adopting harness *before* that harness imports the core — otherwise consolidation moves the entire policy surface into a place that harness cannot protect.

## 6. Ordered plan (GPT-endorsed sequencing A–G)

**A. Freeze the boundary.** Ratify four things as the refactor contract: the logical LAW/SHIM/AGENT boundary (§4, with the pruned profile), the **installed topology** (§7.2), the **authority source** (authenticated vault snapshot; §3.1), and the **degraded-mode semantics** (**RATIFIED — dp, 2026-08-11: deny-writes-allow-reads**, identical to the existing timeout posture; per-shim tighten-only; see §7.1(9), which then holds every harness to it). Nothing migrates until these are fixed.

**B. Extend the governance closure to every adopting harness.** Before any non-Claude harness imports the core, give it (and the shared-mechanism module, the loader/digest path, the registration/installer surface) the same self-access refusal the Claude adapter already has for the core. Acceptance: a write to the core *or to the loader that selects it* is refused and escalatable from every adopting harness, asserted by a cross-harness test.

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
8. A write to **any element of the effective governance closure defined in §5** — the core, the shared-mechanism module, the loader/digest-selection path, **the registration/config that selects the shim, the installers/manifests that put it in force, and any exemption ledger** — is **refused and escalatable from every adopting harness** (step B), asserted before step C lands. A criterion that covers only core + mechanism + loader still leaves a path to redirect *which* law executes; it must cover the whole closure §5 names.

### 7.4 Availability parity across harnesses (observed) — the timeout asymmetry must close

Today the gate **times out for kimi and codex even with the box idle**, and **never for claude** (dp, 2026-08-12). This is not (only) CPU contention (#354); it is a **structural per-call cost difference**. claude takes one lean daemon round-trip for its verdict. kimi and codex reach the society-safety verdict by **spawning a subprocess** that runs its own connect + verdict + poll protocol against the daemon, on top of their own fire-and-forget witness — so per gate call they pay subprocess spawn + interpreter startup + a separate multi-round-trip, and the society subprocess may not even inherit the raised total-budget env. Even idle, that accumulated cost blows their budget while claude's stays inside it.

The refactor should close this **by construction**: once every harness decides through the same shared path claude uses — society-safety as an in-process predicate, not a subprocess-delegated round-trip — the extra cost is gone. So the accepted state is:

10. **The idle timeout rate is equal across harnesses (≈0).** Measured over a window of gate calls with the box quiet, kimi's and codex's fail-closed-on-timeout rate matches claude's. If the asymmetry survives the refactor, the consolidation did **not** actually put every harness on the same path (they are still subprocess-delegating, or still on a heavier round-trip), and cutover (§6.F) is not complete. This is an **observed** criterion — measure the live per-harness timeout rate after deploy — the availability half of §7.2's declared → executable → deployed → observed.

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
