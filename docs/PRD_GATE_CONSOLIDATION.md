# PRD — one gate, thin shims: consolidate the per-harness hooks onto the shared core

**Status**: proposed — dp-directed 2026-08-11, not started
**Author**: claude-code (CBP), 2026-08-11
**Motivating finding**: the shared gate core (`plugins/_shared/hestia_gate_core.py`) was **built and never wired**. It says so itself at line 103: *"NOT WIRED. Nothing imports this yet."* The live gates (codex, kimi) are the **pre-hardening hand-copies**, so security fixes that already exist in the core are still absent from the enforcing hooks.
**Directive (dp)**: *"common gate whenever possible, per-harness shims call the common gate, with local adjustments only as needed for the specifics of the harness. otherwise it is not maintainable and a massive security risk … fix the procedure, not one message."*
**Relates to**: `PRD_GOVERNANCE.md` (the gate is a mechanism of governance), `PRD_CONFIG_IN_VAULT.md` (a governance input the party can write is a hole — the same shape applies to the gate's own code), the git-manager note (`prj_cbp_build_contention_git_manager` in operator memory).

---

## 1. The problem, demonstrated not theorised

There are **N hand-maintained copies of a security predicate** — one per harness (claude-code, codex, kimi), plus an installed `society_pre_tool_use.py` that is not even in the repo. A shared core that would end this exists and is complete, but **nothing imports it** except one telemetry helper. The result is not merely messy; it is that **the enforcing gates run older, weaker logic than the fixed version already sitting in the tree.**

This is not a prediction. This session produced the proof:

- The per-request timeout fix (`0.5 → 5.0`, env-overridable) landed in the society gate on 2026-08-07 and **silently never reached the claude-code hook** — a four-day divergence in a fail-closed threshold, discovered only because a member kept fail-closing.
- The fail-closed **message** lives in each harness's copy, so fixing it meant editing one installed file by hand — which the gate-self-access rule (correctly) refuses, so it could not be done in-session at all.
- The **hardened scope predicates** (path-boundary containment; resolve-before-segment traversal handling) exist **only in the unwired core**. codex and kimi still carry the **pre-hardening substring/lexical forms** — the exact bug classes the core's own comments document as fixed. See §3.

## 2. The principle, and why it is a security requirement first

> A security predicate must have exactly one implementation. Per-harness behaviour is expressed by *parameters to that predicate*, never by a second copy of it.

The maintainability case is obvious. The **security** case is stronger and is the reason this is a PRD and not a cleanup ticket:

1. **N copies = N places a vulnerability must be fixed, and N independent chances to drift.** It has already happened, on security-relevant paths (§3).
2. **The posture becomes per-harness by accident.** A stricter check in one copy and not another means kimi and claude are governed by *different* predicates; the constellation is only as strong as its weakest copy, and nothing tracks which copy is weakest.
3. **Only one copy is pinned.** The `member_lct` census and the self-tests hold the claude-code hook to its invariants; the codex and kimi copies are held to nothing, so a regression there is invisible.
4. **More copies = more audit surface**, reviewed once and then diverged.

## 3. Current state — measured (audit, 2026-08-11, at merged `a019141`)

### 3.1 What the shared core already provides (complete, unwired)
`evaluate(event, profile, workspace, policy) -> Verdict` — the whole local policy (egress + scope), and deliberately **never calls `sys.exit`**, so a shim cannot mistake "core returned nothing" for allow. Plus the single `REMEDIES` table, the `_deny(rule, …)` refusal constructor (takes a rule id, not a sentence), the hardened `path_in_scope`/`command_in_scope`/`_under_temp_root`, `resolve_agent_policy`, the `HarnessProfile`/`AgentPolicy`/`NormalizedEvent` shim-contract types, and `record_gate_unavailable`. The core is transport-free by design: no HTTP client, no `REQUEST_TIMEOUT_S`, no `sys.exit` — those are declared the shim's job.

### 3.2 What is duplicated (should be one copy)
- **codex and kimi each re-implement the entire local decision** — `detect_workspace`, `load_in_scope`, `identity_role`, `launch_cwd_repo`, `FORBIDDEN`, `READ_CLASS`, `path_in_scope`, `command_in_scope`, the member-address allowlist — as hand-copies, in their **pre-hardening** form.
- A **witness/attestation + mini-MCP client** block (~150 lines) is near-byte-identical between codex and kimi and duplicated again, differently, in claude-code.
- `_attempted_summary` exists in **three** copies with three behaviours; claude-code's own comment calls this *"the drift the shared core exists to end, and it drifted in the direction that costs the operator."*
- **The budget contract is not shared**: `REQUEST_TIMEOUT_S`/`TOTAL_BUDGET_MS` exist only in claude-code; codex/kimi carry ad-hoc hardcoded timeouts.

### 3.3 Live drift with security consequence (fixed in core, still broken in the shims)
These are the same bug **classes** the core's own comments already document as fixed; they remain live in the enforcing codex/kimi copies because the core is unwired:
- **Path-boundary written as a substring test** for the temp-root and for workspace containment — a prefix/`in` check where a boundary check is required.
- **Scope check reads a path's head lexically before resolving `..`** — so a granted first segment can front for an ungranted resolved target.
- **Refusal remedy names a tool that does not exist** (`request_scope`) instead of the real `hestia_request_scope`/`hestia_appeal` — the live gate ships a door nobody built.
- **The one function that records refusals disagrees across vendors**: codex's `deny` records to the chain; kimi's records only inside a bare `except: pass`, so the trust chain's denominator already varies by harness.
- **kimi cannot tell a real deny from an infra fail-closed** (codex can, via marker text), so kimi mis-scores infrastructure failures as member conduct.

### 3.4 What is genuinely harness-specific (stays in the shim)
Engine exit contract / fail-open reality (all Claude-lineage engines fail OPEN on timeout, so each gate must be the fail-closed party — but the *rendering* of exit-code/stderr/JSON differs); stdin event schema + parse (codex additionally sees `apply_patch` and MCP calls); env/identity wiring (identity paths, home markers, role, plugin-id); codex's ext4-copy society-gate preference. The decision **topology** difference (claude-code does a daemon verdict round-trip; codex/kimi decide locally then fire-and-forget witness and subprocess-delegate society-safety) is real — but it must become a *parameter to the core*, not a reason to fork it. Today it is expressed as "codex/kimi shell out to claude-code," which is the coupling to untangle.

### 3.5 Repo-integrity flags
`society_pre_tool_use.py` is referenced by claude-code's self-protection (`_GOVERNANCE_FILES`, `_HOOKS_DIR_ONLY`) and by codex/kimi's `CLAUDE_PRE` default, **but is absent from the repo** — it exists only as an installed copy. So the guard protects a filename the tree does not contain, and the delegation target disagrees with the protected filename. This must be reconciled as part of the refactor.

## 4. Target architecture

- **LAW** = `hestia_gate_core.py` (already built): `evaluate() -> Verdict`, `REMEDIES`, every scope/egress predicate. One copy, amendable only by due process, pinned by tests.
- **SHIM** per harness, reduced to the two seams the core already specifies: `parse_event(raw_stdin) -> NormalizedEvent` and `render(verdict) -> (exit_code, stderr)`, plus a `HarnessProfile` literal and a daemon-call callback. **No scope logic, no forbidden list, no remedy text, no decision in the shim.**
- **AGENT** = `AgentPolicy` read from the vault (already modelled).

**Moves into the core** (not there yet): a shared daemon/witness MCP transport (injected, so the core stays transport-free per its own contract); a single budget/timeout contract; `_attempted_summary`/`_credential_shaped` onto the witness path; the attestation block.

**The shim reduces to** a profile + `parse_event`/`render` + the daemon callback — codex/kimi collapse from ~540–760 lines to that; claude-code keeps only its exit rendering and stdin parse.

## 5. The one constraint we must not get wrong — self-protection before adoption

`hestia_gate_core.py` currently matches **no** self-access marker. The moment the harnesses import it, the entire policy surface lives in **one file that nothing is watching** — and disarming every gate at once drops from "edit five files, trip the self-access rule five times" to "edit one unguarded file." claude-code's own comment already names this risk.

**Therefore step 0 is mandatory and first:** the core (and the shared transport module) must be added to the self-protection surface — its own governance-marker membership, and census/self-test pins — **before any harness imports it.** Consolidation performed in the wrong order is a larger hole than the drift it closes.

## 6. Ordered refactor plan (smallest safe step first)

0. **Guard the core first** (§5): add `hestia_gate_core.py` and the future shared-transport module to `_GOVERNANCE_FILES` and to the self-test/census pins. Verify a write to the core is refused and escalatable exactly as a write to a harness hook is.
1. **Migrate one read-only predicate**: point kimi's `path_in_scope`/`command_in_scope`/`_under_temp_root` at the core. This alone **closes the three live scope bypasses for kimi** with no exit-contract change; verify against the core's existing test rows.
2. **Unify the identical copies by import** (`FORBIDDEN`, `READ_CLASS`, member-address list, `load_in_scope`, `identity_role`, `launch_cwd_repo`). Mechanical, low-risk.
3. **Replace inline deny sentences with `_deny(rule)` + `REMEDIES`** in codex/kimi — kills the `request_scope` phantom and unifies the fail-closed **message** (the original question), everywhere at once.
4. **Move the witness/attestation + mini-MCP client into one shared transport module**; codex/kimi/claude-code import it. Gives kimi codex's real-deny-vs-infra discrimination for free.
5. **Define the budget contract in the core** (`REQUEST_TIMEOUT_S`/`TOTAL_BUDGET_MS`, env-overridable) and have all three read it.
6. **Cut codex/kimi to `evaluate() -> Verdict` + `render()`**, removing their local decision copies; do claude-code last (it also owns the daemon path and self-protection).
7. **Reconcile `society_pre_tool_use.py`**: bring it into the repo or remove the dangling references; align `CLAUDE_PRE` targets with the protected filename.

## 7. Falsifiable success criteria

Stated so they can fail:
1. **One implementation** of `path_in_scope`, `command_in_scope`, `_under_temp_root`, the forbidden list, the member-address list, and the fail-closed message exists in the tree — grep finds it once, in the core. A second copy anywhere is a red test.
2. The three live scope bypasses (§3.3) **change no verdict from any harness** — a test drives the same offending input through each harness's shim and every one denies.
3. A refusal from any harness names a **tool that exists** (`hestia_request_scope`/`hestia_appeal`), asserted by a test that resolves the named tool.
4. A write to `hestia_gate_core.py` is **refused and escalatable** exactly as a write to a harness hook is (step 0), asserted before step 1 lands.
5. Fixing a gate threshold or message is **one edit to one file**, reviewed once, pinned once, and installed to every seat by one deploy — the procedure fix, measured as: no harness carries a second copy of the changed value.

## 8. The procedure fix — make the correct path the easy path

Today "update the gate" means: find which of N copies, edit it, notice the other N−1 didn't get it, hand-patch each installed copy out-of-band (the in-session path is walled by self-access), and hope none drift before the next fix. That is why a one-line timeout change consumed a session. After this refactor it is: edit the core, the tests pin it, the deploy installs the core + thin shims everywhere. The shim is too thin to hold a decision, so a fix cannot land in one harness and miss another. That is the efficiency-attractor turned into a feature — the cheap path (edit one file) is the correct path (fix every seat).

## 9. Open questions

- **Disclosure.** The live bypasses (§3.3) are exploitable in codex/kimi now. If `dp-web4/hestia` is public, the specific inputs should be tracked privately, not in a public issue; this PRD deliberately names bug *classes* the core already documents, not fresh exploit strings. Step 1 fixes them for kimi immediately; codex follows in step 6 (or sooner if pulled forward).
- **The society gate's home.** Does `society_pre_tool_use.py` become part of the core (a `society_safety` predicate in `evaluate`) or stay a distinct installed artifact? §3.5 must be settled before step 6.
- **Who owns the sync.** The deploy that installs "core + shims everywhere at once" is exactly the git-manager role's job. Landing this refactor without an owner for its deployment reintroduces drift at install time.
