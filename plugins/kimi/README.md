# Hestia — Kimi Code adapter (foreign-orchestrator integration reference)

A working reference adapter for onboarding a **foreign coding-agent orchestrator** — [Kimi Code
CLI](https://www.moonshot.ai/) — into Hestia's Web4 presence/trust layer. It is the integration-surface
counterpart to a transcript reader: where a history-search tool reads *what Kimi did*, this describes
*how to observe and gate Kimi as it works*.

It exists in two layers, wired independently:

- **Observe (default, non-blocking).** `kimi.plugin.json` wires `hooks/observe.sh` to four
  **non-blocking** events only (`SessionStart`, `PostToolUse`, `PostToolUseFailure`, `SessionEnd`). It
  deliberately does **not** wire `PreToolUse`/`UserPromptSubmit` (the blocking-capable events), so it is
  structurally incapable of interfering with the member's loop. It appends each raw event JSON as one
  JSONL line to an observation log — the substrate a behavioral baseline (drift detection) is grown from.
  Always exits 0; fail-open by construction.
- **Gate (opt-in, blocking).** `hooks/pre_tool_use.py` is the Phase-1 membrane — the one hook a Kimi act
  transits to have effect. It is **fail-closed by construction** (see below), enforces a per-entity MRH
  scope + innate egress/secret invariants locally, and delegates society-safety for write/exec acts to a
  governor. Defaults to **warn** (surfaces would-block verdicts without denying); flip with
  `HESTIA_KIMI_GATE_MODE=enforce`.

## Kimi Code's integration surface (the reusable knowledge)

The load-bearing facts for anyone integrating with Kimi Code (and, largely, the Claude-Code-lineage
CLIs generally — Kimi is a near-clone of Claude Code's hook engine):

- **16-event hook engine**, including `PreToolUse`/`PostToolUse`/`UserPromptSubmit`/`SessionStart`/
  `SessionEnd`/`PostToolUseFailure`/…  (Kimi's *trained self-model* wrongly believes it has no hooks;
  it does — `AGENTS.md` carries the correction so a session doesn't re-derive the error.)
- **Blocking-capable events:** only `PreToolUse`, `UserPromptSubmit`, and `Stop` can block (via exit-2 /
  a `permissionDecision:deny` JSON). All other events are fire-and-forget.
- **The hook engine FAILS OPEN.** timeout / spawn-failure / non-2 exit / exception on a blocking hook all
  resolve to **allow**. This is the single most important fact for writing a blocking hook: *the gate
  itself must be the fail-closed party* — default `exit 2`, reach `exit 0` only on an explicit confirmed
  allow; never rely on `set -e` or the engine default.
- **Config:** `~/.kimi-code/config.toml` `[[hooks]]` blocks map events → commands; pin
  `[upgrade] auto_install = false` in `tui.toml` so the audited binary doesn't drift.
- **Transcript:** Kimi writes an append-only
  `~/.kimi-code/sessions/<slug>/<id>/agents/main/wire.jsonl` carrying rich detail including
  `turn.prompt` (which is why prompt capture uses the transcript, not a `UserPromptSubmit` hook). This is
  the file a history-search tool ingests; the ctx provider id for it is `kimi_code_cli_wire_jsonl_tree`.

## Files

| File | Role |
|---|---|
| `kimi.plugin.json` | Native Kimi Code plugin manifest — wires the four non-blocking observe hooks. |
| `hooks/observe.sh` | Fail-open, dependency-free. Appends each raw event as one JSONL line. Always exit 0. |
| `hooks/pre_tool_use.py` | The Phase-1 gate. Fail-closed; per-entity MRH scope + egress/secret invariants + delegated society-safety. Warn by default. |
| `hooks/hydrate.sh` | Persistence ("model is weather, identity is organism"): on SessionEnd, updates `identity.json` and rewrites the `HESTIA:STATE` block in the deployed `AGENTS.md` so the next session boots knowing its footprint. |
| `AGENTS.md` | The member's standing law, addressed to Kimi as a peer — disclosed observation, current MRH, working norms, continuity story, the self-model correction. |
| `instance/identity.seed.json` | Seed identity/footprint (SAGE `_seed` pattern for a hosted-foreign occupant). `mrh.in_scope` is an **example** grant — customize per install. |

## Config (all env-overridable; defaults suit a generic install)

| Env | Meaning | Default |
|---|---|---|
| `HESTIA_WORKSPACE` | root containing the granted repos | `~/ai-workspace` |
| `HESTIA_SOCIETY_GATE` | society-safety gate caller | `$HESTIA_WORKSPACE/hestia/plugins/claude-code/hooks/pre_tool_use.py` |
| `HESTIA_KIMI_IDENTITY` | the member's live identity.json | `~/.kimi-code/hestia-instance/identity.json` |
| `HESTIA_KIMI_GATE_MODE` | `warn` \| `enforce` | `warn` |
| `HESTIA_FORBIDDEN_EXTRA` | comma-separated extra forbidden path tokens (e.g. your private-repo names) | (empty) |

## Posture — an immune system, grown; not a jail, built

Onboarding a foreign agent is treated as growing an immune system's adaptive baseline through safe,
disclosed exposure — not as origin-banning or cwd-caging (which are voluntary-compliance theater). A new
member joins at zero trust and earns scope through witnessed, good-faith work. Observation is disclosed
(`AGENTS.md`) because good-faith community runs on disclosure, not surveillance. A deny is *steering* — it
carries the reason and the in-scope alternative — not a bare wall.

## Status

Reference adapter, wired and exercised against the real Kimi Code CLI. Observe layer is live and
fail-open; the gate is fail-closed and defaults to warn (audit-first rollout). Known limits: the
observation log lives on the member-writable surface (fine while observe-only and disclosed; the durable
fix is off-host hash-chained ingest with gap detection), and concurrent hook appends can interleave (the
consumer must skip-and-count malformed lines, not die). Part of the broader Web4 / Hestia work at
[dp-web4/hestia](https://github.com/dp-web4/hestia); this is the first foreign (non-Claude-Code)
orchestrator adapter and the pattern the next one (DeepSeek, Gemini, Grok, …) reuses.
