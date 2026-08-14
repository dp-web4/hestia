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

### Retired: the native Codex plugin marketplace bundle (Sprint G)
A `marketplace/` bundle (the `hestia-codex@hestia` plugin) used to ship a second, hand-forked
copy of the gate. Sprint G deleted the forked hooks (§7.1(1) — the 227-line stale gate,
11.5KB against the live 42KB, nobody installed from it), and the rest of the registration
(manifests, plugin.json advertising the deleted `./hooks/hooks.json`, frozen identity seed
with no hydrate writer, PARITY_EXCEPTIONS ledger) is retired with it: a package that
advertises hooks it does not contain is worse than no package. The config.toml
`[[hooks.*]]` install above is the ONE install path. If a marketplace package ships again
it must be a REBUILT artifact carrying the canonical content digest (§7.2(6),
`plugins/_shared/test_gate_core.py` inventory note) — never a hand-fork. Format notes that
took real effort, preserved for that rebuild: manifest must live at
`.agents/plugins/marketplace.json` (not `.codex-plugin/`) in Codex 0.145; scripts resolve
via `$CLAUDE_PLUGIN_ROOT`; authority (MRH grants, private exceptions) must ship NARROWER
than canonical, never wider, with every withheld grant declared — see the parity test's
mechanism/authority axes in git history (`plugins/codex/tests/marketplace_parity_test.py`,
deleted with the bundle it compared).

## Launching Codex (the flags, since they are not the ones you expect)

Codex does **not** use `-c` for continue or `-y` for yolo. `-c` is `--config`. The
Claude/Kimi muscle memory is actively wrong here, which is why this section exists.

```bash
# continue the most recent session (the `claude -c` equivalent)
codex resume --last
codex resume                 # session picker
codex resume <id|name>       # a specific one
codex fork --last            # branch instead of continue

# unattended / auto-approve (the `kimi -y` equivalent) — TWO orthogonal axes
codex resume --last -a never -s workspace-write
```

| axis | flag | values |
|---|---|---|
| when to ask a human | `-a, --ask-for-approval` | `untrusted` \| `on-request` \| `never` |
| what it may touch | `-s, --sandbox` | `read-only` \| `workspace-write` \| `danger-full-access` |

Keeping these orthogonal is better than kimi's single `-y`: you can have *never prompt me*
while still confined to the workspace. `--dangerously-bypass-approvals-and-sandbox` is the
true full-yolo (both axes off); its own help says *"EXTREMELY DANGEROUS. Intended solely for
environments that are externally sandboxed."*

Other flags worth knowing: `-C/--cd <DIR>` sets the working root, `--add-dir` adds writable
dirs, `-m/--model`, `-p/--profile`, `codex exec` for non-interactive runs.

**The approval axis does not touch the gate.** `-a never` suppresses the *prompt* layer
only; the PreToolUse hook still fires and an `exit 2` deny is still honoured — the same
result verified for kimi's `-y` (see `reference_kimi_yolo_does_not_bypass_gate`). Codex
hooks fire on shell, `apply_patch` **and** MCP, not Bash alone.

**`--dangerously-bypass-hook-trust` is the one that does matter to us.** It runs enabled
hooks *without requiring persisted hook trust for this invocation* — a hook-**trust**
bypass, not an approval bypass, so it is the flag that interacts with the gate's provenance
model rather than its prompt layer. Untested against this adapter as of 2026-07-25. Do not
put it in an unattended launcher before someone checks what our gate does under it.

**Seats are not entities (dp, 2026-07-25).** Codex bills per seat and dp holds two. A seat
is resource-pool auth, not an identity: both seats act as the one `codex` member, one LCT,
one trust grain, one scope grant. Concurrency between seats is a work-claim problem, not an
identity problem.

## Hardening notes
- **Fail-open + slow FS = a real gap.** On WSL the repo lives on `/mnt/c` (9p), whose cold-load can
  exceed the hook timeout; a timed-out gate fails **open**. Place the hook scripts (or a symlink) on
  ext4 so the shell gate can't silently open. (Same lesson as the snarc/gitnexus ext4 symlinks.)
- **Gate mode** defaults to `enforce` (deny-tight, relax as trust accrues). `HESTIA_CODEX_GATE_MODE=warn`
  for an audit shakedown only.
- **`--dangerously-bypass-hook-trust`** skips the hook *trust prompt*, not the hooks — so it does NOT
  bypass the gate (unlike Kimi's `--yolo`, which we verified also doesn't bypass its gate).
