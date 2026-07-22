# Hestia adapter for OpenAI Codex CLI

Governance scaffold that onboards the **Codex CLI** (OpenAI) as a foreign member of the fleet — the
second after Kimi. Modeled on `hestia/plugins/kimi/`, but the architecture **differs in one load-bearing
way** (see below), because verifying the harness contract instead of inheriting it is the whole method.

## What Codex actually is (verified 2026-07-22, codex-cli 0.145.0)

Codex ships a **genuine Claude-Code-lineage hook engine** — same events (`PreToolUse`, `PostToolUse`,
`SessionStart`, `SessionEnd`, `Stop`, `UserPromptSubmit`, `PermissionRequest`, `PreCompact`, …), same
event JSON on stdin (`hook_event_name`, `tool_name`, `tool_input`, `cwd`, `session_id`), same deny
contract (exit `2` + stderr, or `hookSpecificOutput.permissionDecision: "deny"`), and — verified from
OpenAI's docs — it **FAILS OPEN** (a hook that errors/times-out/exits-nonzero is marked failed and the
tool call *continues*). So the gate is fail-closed by construction, exactly as for Kimi.

Two things are Codex-specific and shape the design (both source-verified from `codex-rs`, correcting a
widespread blog claim that PreToolUse is "Bash-only"):

1. **`PreToolUse` fires for shell, `apply_patch`, and MCP calls** — it dispatches centrally over every
   Function-payload tool. (It does NOT fire for `tool_search`, custom/freeform tools, or a hosted
   `web_search`.) So the gate sees shell commands *and* file edits *and* MCP calls.
2. **The sandbox confines WRITES and NETWORK, not READS.** `sandbox_mode = "workspace-write"` +
   `network_access = false` structurally confines writes to the launch workspace and blocks egress —
   the write boundary string-parsing can't give. But under workspace-write the whole FS is *readable*
   (`--ro-bind / /`), so the sandbox does NOT scope reads; read-scope rests on the shell gate (which
   catches explicit reaches but not relative-recursive traversal — the Kimi `find .` limit) plus
   launching in the task repo. Real read-confinement needs a bind-mount/container (future).

So governance is **defense in depth**, each layer covering different acts:

| Act | Enforced by | Strength |
|---|---|---|
| WRITE to out-of-scope repo | **sandbox** `workspace-write` (+ apply_patch also fires the gate) | strong (structural) |
| NETWORK egress | **sandbox** `network_access = false` | strong (structural) |
| Secret/credential access, unsafe shell | **PreToolUse gate** (fail-closed, innate denylist + society-safety) | strong for explicit; shell-scoped |
| READ of out-of-scope repo | **PreToolUse gate** shell command-scope + launch-in-task-repo | weak (string-parse; relative-traversal escapes) |
| Witness / continuity | **observe.sh** (PostToolUse) + **hydrate.sh** (SessionEnd) | fail-open by design |

## Files
- `hooks/pre_tool_use.py` — the fail-closed shell gate (scope + egress + society-safety).
- `hooks/observe.sh` — fire-and-forget witness (SessionStart/PostToolUse/SessionEnd), always exit 0.
- `hooks/hydrate.sh` — SessionEnd identity hydration + registry-driven scope refresh.
- `hooks/hooks.json` — the Codex hooks manifest (portable declaration).
- `instance/identity.seed.json` — the foreign-Codex identity seed (SAGE pattern).
- `AGENTS.md` — the occupant's standing-law file (deployed to `~/.codex/AGENTS.md`).

## Install
1. Enable + configure in `~/.codex/config.toml`:
   ```toml
   approval_policy = "on-request"
   sandbox_mode    = "workspace-write"
   [features]
   codex_hooks = true
   # + the [[hooks.*]] blocks (see hooks/hooks.json for the event structure)
   ```
2. Deploy the standing-law + seed:
   ```
   cp AGENTS.md                    ~/.codex/AGENTS.md
   mkdir -p ~/.codex/hestia-instance && cp instance/identity.seed.json ~/.codex/hestia-instance/identity.json
   ```
3. `codex doctor` to validate config. Live hook firing needs auth (`codex login`, dp-only).

### Alternative: native Codex plugin (idiomatic, needs a trust-review)
A ready-to-install Codex plugin is bundled under `marketplace/` (the `hestia-codex@hestia` plugin,
format source-verified against codex-rs and confirmed discoverable). Install with:
```
codex plugin marketplace add /mnt/c/exe/projects/ai-agents/hestia/plugins/codex/marketplace
codex plugin add hestia-codex@hestia        # prompts a one-time hook trust-review
```
It bundles the same hooks (referenced via `$CLAUDE_PLUGIN_ROOT`). **Do not run both installs at once**
— the plugin and the config.toml `[[hooks.*]]` would double-fire. The config-based install is the
active one on this host; the plugin is the portable form for other machines. (Marketplace-manifest
quirk in 0.145: the manifest must live at `.agents/plugins/marketplace.json`, not `.codex-plugin/`.)

## Hardening notes
- **Fail-open + slow FS = a real gap.** On WSL the repo lives on `/mnt/c` (9p), whose cold-load can
  exceed the hook timeout; a timed-out gate fails **open**. Place the hook scripts (or a symlink) on
  ext4 so the shell gate can't silently open. (Same lesson as the snarc/gitnexus ext4 symlinks.)
- **Gate mode** defaults to `enforce` (deny-tight, relax as trust accrues). `HESTIA_CODEX_GATE_MODE=warn`
  for an audit shakedown only.
- **`--dangerously-bypass-hook-trust`** skips the hook *trust prompt*, not the hooks — so it does NOT
  bypass the gate (unlike Kimi's `--yolo`, which we verified also doesn't bypass its gate).
