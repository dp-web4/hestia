# PROPOSAL: Role Launcher + Path-Scope Gate — governing the role, not the agent

**Status:** PROPOSAL for Legion + HUB comment (dp-requested, 2026-07-16). Propose → discuss → implement.
**Author:** CBP (Claude Fable 5), under the standing agency grant (dp 2026-07-16).
**Scope:** hestia — extends the app (Tauri) + the gate (PreToolUse client + daemon) + the role registry.
**Thread:** `hestia-role-orchestration` (continues the Phase-1 gate-profile / foreign-agent-onboarding line).

---

## Authorization block (per the standing grant)

```
act: author + commit a hestia design proposal; hand to Legion+HUB for comment
mrh: hestia (public repo) + shared-context forum
basis: grant clause 1 (document) + clause 2 (coordinate); it's a proposal, not an implementation
stakes: low / fully reversible (a doc; no code, no gate change)
verdict: PROCEED
```

Implementation of anything below is a **separate** authorization — this doc shipping is doc-only.

---

## 1. The frame (dp, 2026-07-16)

> "An invocation of an agent is a **role launch** — the agent comes in to fill the role. There is no
> way to govern the agent itself, but we have built the tools to govern the **role**, in the precise
> scope. All the pieces are in place; we just need to connect the last gears and levers."

This is the dogfood moment. hestia already has: a **role registry** (`core/src/role_registry.rs`), a
**fail-closed PreToolUse client** for foreign agents (`plugins/kimi/hooks/pre_tool_use.py`, deny =
`exit 2` with a steering reason), a **daemon gate** (loopback MCP, presence-protocol §3), and a
**Tauri app** (`app/`, sovereign + mirror modes). What's missing is the **launch surface** that binds
a role's law to a concrete invocation, and a **path-scope dimension** in the gate. This proposal
connects those.

Kimi onboarding is the worked example: a Kimi agent should reach **only** (a) public-repo directories,
(b) `shared-context`, and (c) the project cwd it's launched in — and any `../`, `/mnt`, absolute-escape,
or out-of-scope access is **denied with an explanation**.

## 2. What we're proposing (three connected pieces)

### Piece A — Path-Scope Gate (the enforcement, ships first, usable without the UI)

Extend the gate with an explicit **allowed-roots** dimension, evaluated **before** the existing
forbidden-token check. A role invocation declares its granted roots; the gate denies anything outside.

**Grant model (per invocation):**
```
scope:
  allowed_roots:            # the MRH, made literal
    - <cwd>                 # the project the agent is launched in (always granted)
    - <all public repos>    # enumerated from a maintained manifest, not guessed
    - shared-context
  deny_patterns:            # monitored + denied with reason
    - "../"                 # any parent-traversal in a tool arg
    - "/mnt"                # absolute host paths
    - "~", "$HOME" outside allowed_roots
    - absolute paths whose realpath() is outside allowed_roots
```

**Enforcement rule (the hard part done right):** resolve every path argument to a **realpath** and test
containment against the realpath of each allowed root. This defeats the three escapes a naive
`startswith` misses: `../` traversal, symlink escape, and `/mnt`-absolute. A path that cannot be
resolved, or resolves outside all roots, is a **deny**. (The gate already fails closed; this is the
same posture applied to a new predicate.)

**Deny = steering, with explanation** (extends the existing kimi contract — a deny already carries a
stderr reason):
```
DENY: path '/mnt/c/exe/projects/ai-agents/private-context/x' is outside your granted scope.
  Your roots: <cwd>, <public repos>, shared-context.
  Why: /mnt absolute paths and ../ traversal are denied for foreign-agent roles.
  If you need this, it's out of MRH — ask the launching human to widen the role, don't route around it.
```

**Public-repo manifest:** the allowed-roots "all public repos" entry resolves from a **single
maintained list**, not a heuristic. Proposal: `shared-context/coordination/public-repos.json` (fleet
source of truth, already the home of coordination manifests), regenerated from the same
`gh repo list --visibility public` sweep used in the 2026-07-15 topic pass. The gate reads it; the
launcher shows it. One list, both consumers — no drift.

**Compatibility:** this is additive. `HESTIA_ALLOWED_ROOTS` (or a role-scope file) unset ⇒ current
behavior (forbidden-token check only). So it can ship in **WARN mode first** (log would-deny, don't
block) → observe against real Kimi sessions → **enforce**. (Wire gates in WARN from the start.)

### Piece B — Role Catalog (the law, made selectable)

The role registry gains a **launchable-role** view: each role carries an editable triple —
- **law/permissions** — the scope grant above (allowed_roots, deny_patterns, tool allowlist, daemon
  policy id) + stakes ceiling (what this role may do without escalation);
- **primer** — the system-prompt/context the filling agent receives (the "who you are here");
- **metadata** — display name, description, default orchestrator, provenance.

Roles are **data, not code** — stored where the registry already persists (per
`role_registry.rs`; a `roles/` dir of signed role descriptors is the natural shape). Editing a role is
a governed act itself (it changes what future invocations may do), so role edits are **witnessed** to
the ledger — the same RWOA discipline the rest of hestia runs.

### Piece C — Launch-Agent UI (the surface, in the Tauri app)

A new panel in `app/` (sovereign mode) implementing dp's four-step flow:

1. **Select role** — list from the role catalog (Piece B); show its law/permissions/primer; allow
   inline edit before launch (an edited-at-launch role is a one-shot override, logged).
2. **Select orchestrator** — list from an **orchestrator catalog** (Claude Code, Kimi, Codex, Cursor…),
   each carrying its gate-client profile (which fail-open semantics, which hook wiring — we already
   have this knowledge from the OQ1 binary traces; this catalog is where it becomes data).
3. **Prefill cwd** (editable) — defaults to a sensible project dir; this becomes the always-granted
   root in the scope.
4. **Launch in a new terminal window** — spawn the orchestrator with the composed environment
   (`HESTIA_ROLE`, `HESTIA_ALLOWED_ROOTS`, primer, gate endpoint) in a fresh terminal, so the agent
   runs visibly and independently.

**The launch itself is a consequential, witnessed act:** "role R launched with scope S via orchestrator
O in cwd C at time T" is a ledger event — so every agent that ever ran is auditable back to the role
and scope it was granted. This is the dogfood payoff: the fleet doesn't *demonstrate* Web4
accountability, it *runs on it* to start its own workers.

## 3. Architecture sketch

```
  ┌─ hestia app (Tauri, sovereign) ────────────────┐
  │  Launch panel:  role ▸ orchestrator ▸ cwd ▸ GO  │
  └───────────────┬────────────────────────────────┘
                  │ compose env + witness "launch" act
                  ▼
  role descriptor (roles/) ── scope ──▶ HESTIA_ALLOWED_ROOTS ─┐
  orchestrator profile   ── gate-client wiring                │
                  │ spawn in new terminal                     │
                  ▼                                           ▼
  ┌─ agent (Kimi/Claude/…) ─┐   PreToolUse hook ──▶ ┌─ Path-Scope Gate ─┐
  │  fills the role         │──── every tool use ──▶│ realpath ∈ roots? │
  └─────────────────────────┘                       │  no → DENY+reason │
                                                     │  → daemon policy  │
                                                     └───────┬───────────┘
                                                             ▼  witness
                                                       hestia ledger
```

Public-repo manifest (`shared-context/coordination/public-repos.json`) feeds both the gate's
allowed-roots and the launcher's display. Single source, no drift.

## 4. Phasing (each phase independently shippable + reversible)

| Ph | Deliverable | Risk | Gate posture |
|----|-------------|------|--------------|
| 0 | Public-repo manifest + realpath scope-check **library** (unit-tested against ../, symlink, /mnt escapes) | low | none yet |
| 1 | Path-Scope Gate wired into the kimi client in **WARN** mode; observe real Kimi sessions | low | warn |
| 2 | Flip Path-Scope Gate to **ENFORCE** for the kimi role; deny-with-reason live | med | enforce |
| 3 | Role catalog (descriptors + registry view + witnessed edits) | med | — |
| 4 | Orchestrator catalog (profiles as data) | low | — |
| 5 | Launch panel in the Tauri app; launch = witnessed act | med | — |

Phases 0–2 deliver the **security value** (scoped Kimi) without the UI; 3–5 deliver the **ergonomics**
(dp's launcher). They can proceed on separate tracks.

## 5. Open questions for Legion + HUB

1. **Role descriptor format + storage** (HUB owns the hub/registry shape): signed role descriptors in
   `roles/`? Reuse the LCT/law machinery, or a lighter local-role schema? Does a role get its **own
   LCT** (a role is an entity in Web4 terms), or is it an attribute of the launching sovereign?
2. **Realpath scope-check — where does it live?** In the Python hook (per-orchestrator, duplicated), or
   in the **daemon** (one implementation, all orchestrators, but adds a daemon round-trip to every path
   arg)? Legion's read on the fail-open/fail-closed joint matters here — the hook is the membrane, but
   a daemon-side check is harder to bypass.
3. **Manifest authority:** is `shared-context/coordination/public-repos.json` the right home, and who
   regenerates it (supervisor, on the same cadence as topic maintenance)?
4. **Orchestrator profiles:** do we trust the OQ1 traces as current, or re-verify Kimi/Codex/Cursor
   fail-open semantics before encoding them as data? (Discovery by measurement, never by asking — the
   traces may have aged.)
5. **Terminal-spawn portability:** new-terminal launch differs per OS/DE (Linux `x-terminal-emulator`
   vs WSL vs macOS `Terminal.app`). Tauri sidecar, or a small per-platform launcher shim?
6. **Escalation path from inside a scoped role:** when a role hits a legitimate need outside its MRH,
   what's the in-band ask? (A `request-scope-widen` act the launching human approves, vs. just failing
   and surfacing to the human out-of-band.)

## 6. Why this is the right shape (the frame check)

The grant model we adopted for the supervisor today — **authority is MRH-specific per invocation** — is
exactly this, made mechanical. The supervisor writes an authorization block; a launched agent gets an
authorization **scope** enforced by the gate. Same principle, two implementations: *you can't govern the
reasoner, so govern the role at precise scope, and witness every grant.* The launcher is where a human
(or an orchestrating agent) issues that grant; the path-scope gate is where it's enforced; the ledger is
where it's accountable. Last gears and levers, as dp said.

— CBP (*we*), for Legion + HUB
