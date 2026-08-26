# Hestia plugin for Claude Code

Wires Claude Code into your local Hestia daemon. Every tool call gets a
hash-linked witness entry in your local audit chain. Per-plugin trust
scores evolve from outcomes. Credentials live in one encrypted vault
instead of scattered `.env` files. **No data leaves your machine.**

## What you'll see

Open the daemon's dashboard at `http://127.0.0.1:7711/` while you work
in Claude Code. Each tool call appears in the witness chain feed
within a second:

![dashboard](https://raw.githubusercontent.com/dp-web4/hestia/main/docs/screenshots/dashboard-web.png)

After a few sessions the trust panel shows real T3/V3 trajectories for
`claude-code` (and any other agent you've also wired up).

## What it captures

For every tool call:

| Field | From |
|---|---|
| `tool_name` | the tool Claude Code invoked (`Read`, `Bash`, `Edit`, etc.) |
| `target` | first matching key in `tool_input` (`file_path`, `path`, `url`, command head) |
| `success` | `tool_response.is_error` flag (any error = failure) |
| `magnitude` | by tool class — Bash/Shell 0.8, Write/Edit 0.6, Read/Grep 0.2 |
| `plugin_id` | always `"claude-code"` |

The full tool arguments and tool output are **never sent** to the
daemon. Only the metadata above. If you want richer payloads in the
chain you'd extend `witness.py` to forward them deliberately.

## Prerequisites

You need the Hestia daemon installed locally and running. Detailed
install at https://hestia.tools, but the short version on Linux:

```bash
cargo install hestia              # daemon binary
mkdir -p ~/.hestia && chmod 700 ~/.hestia
openssl rand -base64 30 | tr -d '\n' > ~/.hestia/.passphrase
chmod 600 ~/.hestia/.passphrase
HESTIA_PASSPHRASE="$(cat ~/.hestia/.passphrase)" hestia init
# Then enable as systemd user service — see hestia repo deploy/templates/
```

If the daemon isn't running, this plugin fails silently (one polite
stderr hint, once). It doesn't block your tool calls or fail any work.

## Install (manual, until marketplace listing lands)

Clone the hestia repo somewhere, then add to `~/.claude/settings.json`:

```jsonc
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": "python3 /path/to/hestia/plugins/claude-code/hooks/witness.py",
        "timeout": 3
      }]
    }]
  }
}
```

Restart Claude Code (new sessions pick up the hook automatically).

Open `http://127.0.0.1:7711/` and watch a session populate the chain
in real time.

## Disabling

Remove the PostToolUse entry from `~/.claude/settings.json`, or set
`HESTIA_ENDPOINT=` (empty) in your environment.

## Debugging

```bash
HESTIA_HOOK_DEBUG=1   # set in shell where Claude Code runs
# logs to ~/.hestia-claude/hook.log
```

## Policy gating: the PreToolUse gate EXISTS and must be wired

> Corrected 2026-08-26. Until now this section listed PreToolUse under "what this
> plugin doesn't do (yet)" and assigned it to Hardbound as future work. That has been
> false since the gate shipped. It stood for 97 days (last edit 2026-05-16) while the
> gate grew tests and became fail-closed, so **an operator following this document
> correctly ended up ungated, having made no mistake.** At least two seats reached that
> state exactly this way. Measured and reported by McNugget + HUB, 2026-08-21.

`hooks/pre_tool_use.py` in this plugin is the enforcing gate: it blocks until the
daemon returns a verdict, exits 2 to deny, and **fails closed** (a denial is returned
when the daemon is unreachable, rather than an allow). The `PostToolUse` witness hook
is *not* a gate — it records after the fact and cannot refuse anything.

**Wiring the witness without the gate leaves the seat observed but ungoverned.** If
your Claude Code settings declare hestia hooks only at `PostToolUse`, this plugin is
running in witness-only mode. `tools/fleet_manifest.py` now reports that state
explicitly as `provisioned-but-UNGOVERNED` rather than rendering it the same as
"not installed".

Consult current wiring guidance before changing gate configuration on a seat — editing
what governs an agent is deliberately a distinct class of act, and on an already-gated
seat the gate will refuse the edit and route it for human escalation.

## What this plugin doesn't do (yet)
- **Window correlation** — each tool call opens a fresh MCP session,
  which clutters the chain with `session_started` entries. A sidecar
  daemon could pool the connection; deferred until pain is real.
- **Pre-installed credential consumption** — the SDK supports
  `vaultGet`; this plugin doesn't currently surface vault credentials
  to Claude Code's tools.

## License

AGPL-3.0-or-later. See [LICENSE](../../LICENSE).
