# CBP — First Hestia deployment

Recorded as a probe, not a rollout. CBP is the oversight machine and
the first to run the daemon against real agent traffic. Goal for this
deployment: accumulate ~1 week of witness data from Claude Code's
real tool calls, then look at what showed up.

## What was installed

| Path | Purpose |
|---|---|
| `~/.local/bin/hestia` | Release binary, 9.4 MB, dynamically linked. Copied from `core/target/release/hestia`. |
| `~/.hestia/.passphrase` | 40-char random passphrase, mode 600. The consumer-tier security boundary (same threat model as `~/.ssh/id_ed25519`). |
| `~/.hestia/vault.enc` | Empty encrypted vault, mode 600. Credentials added with `hestia vault add`. |
| `~/.hestia/witness.db` | SQLite hash-linked chain. Grows with every recorded action. |
| `~/.hestia/trust/` | One JSON file per entity. Updated on every `record_outcome`. |
| `~/.hestia/endpoint` | `http://127.0.0.1:7711/mcp` — read by the SDK's auto-discovery. |
| `~/.config/systemd/user/hestia.service` | User unit. Auto-starts on login. |
| `loginctl enable-linger dp` | Daemon survives logout. |
| `~/.claude/settings.json` | New PostToolUse hook entry (kept the existing web4-governance and snarc hooks; Hestia runs alongside, not in place of). |
| `~/.claude/settings.json.pre-hestia.bak` | Backup of pre-Hestia settings — restore if hooks misbehave. |

## What runs

```
systemctl --user status hestia.service
```

Daemon listens on 127.0.0.1:7711, accepts MCP StreamableHTTP. Every
new Claude Code session in any terminal fires the `PostToolUse` hook,
which fire-and-forgets a Python script that records the outcome to
the chain. ~11 ms hook overhead per tool call on Claude Code's
critical path; the actual MCP round-trip happens in the background.

## What it captures

Every tool call Claude Code makes (Read, Bash, Write, Edit, …) becomes
a `outcome` chain entry with tool_name, magnitude (assigned by class —
Bash=0.8, Write/Edit=0.6, Read/Grep=0.2), success flag, error message,
and a sha256 hash linked to the previous entry.

A `plugin:claude-code` `EntityTrust` JSON file accumulates T3/V3
scores from the magnitudes and outcomes. After a week of use we
should have a high-N picture of:

- which tool classes claude-code uses most
- the success rate by tool class
- the trust trajectory (does the model's tool use get more reliable
  over time, or does it cycle?)

## Known noise

Each tool call opens a fresh MCP session, so the chain is roughly
50% `session_started` entries. Filtering them out at query time is
easy (`event_type != 'session_started'`); a sidecar that pools
connections would eliminate them entirely but adds a process to
manage. Deferred until we see real cost.

## Disabling

```bash
# Stop and disable the daemon
systemctl --user stop hestia.service
systemctl --user disable hestia.service

# Remove the hook entry from ~/.claude/settings.json (or just restore the backup)
cp ~/.claude/settings.json.pre-hestia.bak ~/.claude/settings.json

# Optional: wipe state
rm -rf ~/.hestia/
```

## Useful commands

```bash
# Service status
systemctl --user status hestia.service
journalctl --user -u hestia.service -f

# CLI introspection
HESTIA_PASSPHRASE="$(cat ~/.hestia/.passphrase)" ~/.local/bin/hestia info
HESTIA_PASSPHRASE="$(cat ~/.hestia/.passphrase)" ~/.local/bin/hestia vault list

# Raw SQLite (witness chain is just sqlite, you can grep it)
sqlite3 ~/.hestia/witness.db "SELECT chain_position, event_type, json_extract(event_data, '$.tool_name') AS tool, json_extract(event_data, '$.success') AS ok FROM chain_entries WHERE event_type='outcome' ORDER BY chain_position DESC LIMIT 20"

# Trust state
cat ~/.hestia/trust/*.json | python3 -m json.tool
```

## Open questions to revisit in a week

- Does the magnitude assignment match how risky the actions actually
  felt? If a bash command that does `rm -rf` and a bash command that
  does `echo hi` both score 0.8, we're losing signal.
- Does claude-code's overall trust converge to a stable T3 level, or
  does it drift? Drift would point to changing tool-use patterns.
- Is the per-call session_started overhead actually painful, or just
  visible? (Real performance signal, not a priori.)
- What's the right way to surface "show me what I've been doing" — a
  CLI subcommand? A small web view? A daily summary cron?
