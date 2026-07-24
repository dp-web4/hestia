# Hestia adapter for AWS Kiro CLI

Governance scaffold that onboards the **Kiro CLI** (AWS/Amazon) as a foreign member of the fleet — the
fourth (after kimi #1, codex #2, gemini #3). Kiro is **Claude-Code lineage in gate semantics** with
**Amazon Q Developer heritage in its tool vocabulary**, so this gate is close to the codex PreToolUse
gate plus one gemini-borrowed necessity: a tool-name translator.

> **Fidelity: documented, not live-verified (2026-07-23).** Kiro is a closed AWS product; the contract
> is from Kiro's official IDE/CLI hooks docs + the custom-agents config reference (see
> `agent-atlas/talk-to/kiro_cli/descriptor.md`), and the gate is smoke-tested against synthetic
> events, but it has **not** run against an installed `kiro` CLI. The verified pass belongs on CBP's
> onboarding rig. Because the gate is fail-closed, any wrong tool/field-name guess over-blocks (safe),
> never silently allows.

## What Kiro is

- **Lineage**: Claude-Code. Events `PreToolUse`/`PostToolUse`/`UserPromptSubmit`/`Stop` (CLI;
  IDE adds `SessionStart`/`PreTaskExec`/`PostTaskExec`/`PostFile*`). Block = **`exit 2`** with STDERR
  as the reason; a `matcher` regex scopes a hook. **Engine FAILS OPEN**: any exit code other than 0/2
  is a warning and the tool runs; `PostToolUse`/`PostTask*` can't block. Default timeout 30s.
- **Tool vocabulary (Amazon Q)**: `fs_read`, `fs_write`, `execute_bash`, `use_aws` — **not** Claude's
  Read/Write/Bash. The society-safety governor dispatches on Claude names, so the gate translates at
  the boundary (`to_claude_lineage`): `fs_read→Read`, `fs_write→Write`, `execute_bash→Shell`,
  `use_aws→Shell` (with a synthetic `aws <service> <operation>` command so the governor sees a target).

## The fail-open lesson, carried in from the start

Kiro fails open, and an uncaught Python exception exits 1, which Kiro treats as **allow-with-warning**.
That is the exact hole CBP's live gemini pass found (a crashing fail-closed gate silently opens; the
repro ran `rm -rf /`). So `main()` wraps the whole gate in a **top-level deny-on-exception** — a crash
fails **closed** (exit 2), `SystemExit` passes through untouched. Verified here by a forced-crash test.

## Gate design (fail-closed by construction)

Only ever exits `0` (explicit confirmed allow) or `2` (deny, always with stderr text). Three gates:

1. **Gate-1a — innate egress/secret denylist.** `.ssh`/`.env`/credentials/keys/`secrets`, never relaxed
   by trust. Swept across file paths, the shell command, **`use_aws` arguments** (an AWS call can carry
   a credential or name a secret resource), and — for an unknown-shape (MCP-like) call — every string
   leaf.
2. **Gate-1b — MRH scope.** File paths via the shared `../lib/path_scope.py` realpath containment
   (denies `../`/symlink/absolute escapes); shell commands via command-scope. Cloud args are **not**
   realpath-scoped (an AWS service is not a local path).
3. **Gate-2 — society safety.** Write/exec (`fs_write`, `execute_bash`) **and** cloud egress
   (`use_aws`) and MCP defer to the claude-code governor via the lineage translation; `fs_read` and
   other local reads skip it. Fail-closed on non-zero/unreachable.

| Act | Enforced by | Strength |
|---|---|---|
| Secret/credential access (incl. inside `use_aws`) | Gate-1a innate denylist | strong, trust-independent |
| Out-of-scope `fs_read`/`fs_write` (explicit path) | Gate-1b `path_scope` realpath | strong |
| Out-of-scope reach via `execute_bash` | command-scope string-parse | weak (relative traversal escapes) |
| Cloud egress via `use_aws` | Gate-1a arg sweep + Gate-2 governor | medium (documented arg shape) |
| Unsafe write/exec/cloud | Gate-2 → claude-code governor | strong; fail-closed |
| Witness / continuity | `observe.sh` (PostToolUse/Stop) | fail-open by design |

## Files

- `hooks/pre_tool_use.py` — the fail-closed PreToolUse gate (translator + crash-guard + `path_scope`).
- `hooks/observe.sh` — fire-and-forget observation (PostToolUse/SessionStart/Stop), always exit 0.
- `hooks/hydrate.sh` — identity persistence on Stop, always exit 0 (seed-only stub; full in_scope
  regeneration from the repo registry is the tracked follow-up).
- `hooks/hooks.json` — the `hooks` block to merge into a Kiro **CLI agent config** (`.kiro/agents/*.json`).
- `instance/identity.seed.json` — member #4, honest 0.5 T3, `web4`-scoped MRH.
- `AGENTS.md` — the standing law Kiro reads (also deploy as a `.kiro/steering/*.md` file).

## Install

1. Deploy `instance/identity.seed.json` → `~/.kiro/hestia-instance/identity.json` (edit `mrh.in_scope`).
2. Deploy `AGENTS.md` → the granted repo root and `.kiro/steering/`.
3. Merge `hooks/hooks.json`'s `hooks` block into the `.kiro/agents/<name>.json` you launch Kiro with,
   fixing absolute paths + `HESTIA_WORKSPACE`. **IDE surface**: instead author standalone JSON hooks in
   `.kiro/hooks/` (fields `version`/`name`/`trigger`/`matcher`/`action`/`timeout`/`enabled`) pointing
   the `PreToolUse` (`trigger`) action `command` at the gate.
- **Install at GLOBAL/user level** and put the scripts on **ext4**, not `/mnt/c` — the only fail-open
  surface is a timeout, and a 9p cold-load can exceed Kiro's 30s hook timeout. Repoint the `/mnt/c`
  paths per install (a non-existent path spawn-errors into a fail-open).

## Verification

Smoke-tested against synthetic events (2026-07-23, Nomad): wrong-event passthrough; `fs_read` in-scope
allow; `fs_read` out-of-scope deny (path_scope realpath reason); `fs_write .env` secret deny;
`execute_bash` out-of-scope command deny; `use_aws` secret-in-parameters deny; malformed-JSON
fail-closed; and a **forced-crash test** confirming the top-level guard exits 2 (fail-closed), not 1
(allow). **Not yet done (the `verified` bar):** run against an installed `kiro` CLI — confirm the exact
`tool_input` arg names for `fs_read`/`fs_write`/`use_aws`, confirm `PreToolUse` fires for MCP calls and
the MCP arg shape, confirm the fail-open behavior empirically. That belongs on the onboarding rig.

## Accountability self-audit (RWOA + S + V)

```
surface: kiro PreToolUse gate   act: allow/deny a foreign member's tool call (read/write/exec/cloud scope)
S: med/reversible (one gated tool call; irreversible egress via use_aws/execute_bash is the high-stakes tail) [construct: MODE=enforce]
R: n/a — authorizes on MRH scope from role-sourced identity, not reachability [construct: load_in_scope]
W: pass — scope from the member's grant-time identity, not a hook-time editable input; safety defers to the witnessed claude-code governor [construct: Gate-2 to_claude_lineage handoff]
O: pass — runs PreToolUse, before any side effect; a denied act leaves state bit-identical (exit 2, no mutation) [construct: _gate before sys.exit]
A: n/a — enforcement point, not a ledger writer; witness is observe.sh + the governor's record [construct: observe.sh]
V: present — egress/secret innate always-deny (incl. use_aws args); crash fails closed; operator holds widen/veto [construct: deny(innate=True) + main() guard]
verdict: PASS (documented; re-audit after live-CLI verification)
```
