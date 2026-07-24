# Hestia adapter for Charm Crush

Governance scaffold that onboards **Crush** (Charm / charmbracelet) as a foreign member of the fleet —
the fifth (after kimi #1, codex #2, gemini #3, kiro #4). Crush is **Claude-Code lineage in gate
semantics** but a Go TUI with its own lowercase tool vocabulary and — the load-bearing catch — a
different stdin field for the event name.

> **Fidelity: documented, contract + tool names source-verified, not live-verified (2026-07-23).** The
> hook contract, exit-code semantics, stdin shape, and tool-name constants are read from
> `charmbracelet/crush@main` source (files cited below); the gate is smoke-tested against synthetic
> events; it has **not** run against a live Crush install. The verified pass belongs on CBP's
> onboarding rig. Because the gate is fail-closed, a wrong arg-name guess over-blocks (safe).

## What Crush is (source-verified)

- **Lineage**: Claude-Code. **Single `PreToolUse` event** (the only blocking hook Crush has;
  richer lifecycle events are an open request, issue #2707).
- **Exit-code contract** (`internal/hooks/runner.go`): `exit 2` → deny (stderr = reason); `exit 49`
  (`HaltExitCode`) → deny + halt the turn; **any other non-zero → non-blocking error → the tool RUNS**;
  timeout → the tool RUNS; `exit 0` → parse stdout JSON `{decision: allow|deny|none}`. Default 30s.
- **Stdin shape** (`internal/hooks/input.go`): `{event, session_id, cwd, tool_name, tool_input}`. The
  event field is **`event`**, NOT `hook_event_name` — a gate checking the wrong field would exit 0 on
  every call and **silently disarm**. This gate checks `event` (with `hook_event_name` as a harmless
  fallback).
- **Tool vocabulary** (`internal/agent/tools/*.go` Name constants): read `view`/`ls`/`glob`/`grep`;
  write `edit`/`write`/`multiedit`; exec `bash`; **network egress `fetch`/`download`**; dynamic
  `mcp__<server>__<tool>`. All lowercase → translated to the governor's Claude TitleCase names.

## The fail-open lesson, carried in from the start

Crush fails open, and an uncaught Python exception exits 1, which Crush treats as a **non-blocking
error = allow**. That is the hole CBP's live gemini pass found (a crashing fail-closed gate silently
opens). So `main()` wraps the whole gate in a **top-level deny-on-exception** — a crash fails **closed**
(exit 2); `SystemExit` passes through. Verified here by a forced-crash test.

## Gate design (fail-closed by construction)

Only ever exits `0` (explicit confirmed allow) or `2` (deny, with stderr text). Three gates:

1. **Gate-1a — innate egress/secret denylist**, swept across file paths, the `bash` command,
   `fetch`/`download` URLs, and MCP arguments.
2. **Gate-1b — MRH scope** via the shared `../lib/path_scope.py` realpath containment for file paths
   (incl. `download`'s local `file_path`); command-scope for `bash` + MCP args. Egress URLs are **not**
   realpath-scoped (a URL resolves under cwd and would false-deny every fetch).
3. **Gate-2 — society safety.** Write/exec (`edit`/`write`/`multiedit`/`bash`), egress
   (`fetch`/`download`), and MCP defer to the claude-code governor via the lineage translation;
   `view`/`ls`/`glob`/`grep` skip it. Fail-closed on non-zero/unreachable.

| Act | Enforced by | Strength |
|---|---|---|
| Secret/credential access (incl. in a URL) | Gate-1a innate denylist | strong, trust-independent |
| Out-of-scope `view`/`edit`/`write`/`download` (explicit path) | Gate-1b `path_scope` realpath | strong |
| Out-of-scope reach via `bash` | command-scope string-parse | weak (relative traversal escapes) |
| Network egress via `fetch`/`download` | Gate-1a URL sweep + Gate-2 governor | medium |
| Unsafe write/exec/egress | Gate-2 → claude-code governor | strong; fail-closed |
| Witness / continuity | SQLite `crush.db` (no event stream) | passive; out of this adapter |

## Files

- `hooks/pre_tool_use.py` — the fail-closed PreToolUse gate (translator + crash-guard + `path_scope`).
- `hooks/hooks.json` — the `hooks` block to merge into `crush.json`.
- `instance/identity.seed.json` — member #5, honest 0.5 T3, `web4`-scoped MRH.
- `AGENTS.md` — the standing law Crush reads.
- **No `observe.sh`/`hydrate.sh`.** Crush has only a `PreToolUse` event — no `PostToolUse`/`Stop`, so
  passive witnessing must be read off the SQLite `crush.db`, not an event stream. That reader is a
  separate concern, not part of this gate. Seed `identity.seed.json` manually at install.

## Install

1. Deploy `instance/identity.seed.json` → `~/.local/share/crush/hestia-instance/identity.json` (edit
   `mrh.in_scope`).
2. Deploy `AGENTS.md` → the granted repo root.
3. Merge `hooks/hooks.json`'s `hooks` block into `crush.json`, fixing absolute paths + `HESTIA_WORKSPACE`.
- **Use ABSOLUTE paths in a global config** (relative paths only resolve at project scope), and put the
  scripts on **ext4**, not `/mnt/c` — the only fail-open surface is a timeout, and a 9p cold-load can
  exceed Crush's 30s hook timeout. Repoint the `/mnt/c` paths per install.

## Verification

Smoke-tested against synthetic events (2026-07-23, Nomad): `view` in-scope allow; `view` out-of-scope
deny; `write .env` secret deny; `bash` out-of-scope command deny; `fetch` secret-in-URL deny;
`download` out-of-scope local-path deny; the **`event`-field check** (a `hook_event_name`-only payload
still gates, does not disarm); malformed-JSON fail-closed; and a **forced-crash test** confirming the
top-level guard exits 2 (fail-closed). **Not yet done (the `verified` bar):** run against a live Crush
install — confirm the exact `tool_input` arg names, confirm MCP tool naming, confirm the exit-49 halt
and fail-open behavior empirically. That belongs on the onboarding rig.

## Accountability self-audit (RWOA + S + V)

```
surface: crush PreToolUse gate   act: allow/deny a foreign member's tool call (read/write/exec/egress scope)
S: med/reversible (one gated tool call; irreversible egress via fetch/download/bash is the high-stakes tail) [construct: MODE=enforce]
R: n/a — authorizes on MRH scope from role-sourced identity, not reachability [construct: load_in_scope]
W: pass — scope from grant-time identity, not a hook-time editable input; safety defers to the witnessed claude-code governor [construct: Gate-2 to_claude_lineage]
O: pass — runs PreToolUse, before any side effect; a denied act leaves state bit-identical (exit 2, no mutation) [construct: _gate before sys.exit]
A: n/a — enforcement point, not a ledger writer; witness rides crush.db + the governor's record [construct: identity.seed _note]
V: present — egress/secret innate always-deny (incl. URLs); crash fails closed; operator holds widen/veto [construct: deny(innate=True) + main() guard]
verdict: PASS (documented; re-audit after live-CLI verification)
```
