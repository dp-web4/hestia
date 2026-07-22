# Hestia adapter for Google Gemini CLI

Governance scaffold that onboards the **Gemini CLI** (Google) as a foreign member of the fleet — the
third after Kimi (#1) and Codex (#2). Modeled on `hestia/plugins/codex/`, but Gemini is an
**independent lineage** (Google's own hook engine + a native policy engine), so the contract was read
from Google's docs rather than inherited. Verifying the harness contract instead of assuming it is the
whole method.

> **Fidelity: source-verified contract, live firing not yet verified (2026-07-22).** The exit-code /
> deny / fail-open contract below is read from gemini-cli **source** (file+line cited), not just docs
> or blogs — per CBP's method note (a blog claim that Codex PreToolUse was "Bash-only" was wrong;
> source corrected it). The base/`BeforeTool` field names are from `docs/hooks/reference.md`. The
> gate's logic is smoke-tested against synthetic events (see "Verification"), but has **not** run
> against a real Gemini CLI. Mark it `verified` only after a live run — that step belongs on CBP's
> onboarding rig (the harness-lane owner). Nomad built this from the descriptor + vendor source.

## What Gemini actually is (documented 2026-07-22, from Google's hooks reference)

Gemini ships its **own** hook engine — a distinct event vocabulary (`SessionStart`, `SessionEnd`,
`BeforeTool`, `AfterTool`, `BeforeModel`, `AfterModel`, `BeforeToolSelection`, `BeforeAgent`,
`AfterAgent`, `Notification`, `PreCompress`), configured in the `hooks` object of
`~/.gemini/settings.json` (user), a project `.gemini/settings.json`, or an extension-shipped
`hooks/hooks.json`. But the **wire protocol is concept-parallel to the Claude lineage**, and on the
fields this gate needs it is near-identical:

- Base stdin JSON: `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `timestamp`.
- `BeforeTool` adds `tool_name` (string) and `tool_input` (object — the raw model arguments).
- **Exit-code contract, source-verified from `packages/core/src/hooks/hookRunner.ts@main`**
  (`convertPlainTextToHookOutput` L537-560, `close`-handler L434-506, `DEFAULT_HOOK_TIMEOUT` L36):

  | exit | runner result | effect |
  |---|---|---|
  | `0` | `{decision:'allow', systemMessage:text}` | allow |
  | `1` (`EXIT_CODE_NON_BLOCKING_ERROR`) | `{decision:'allow', systemMessage:'Warning: '+text}` | **allow** (non-blocking warning — the tool STILL RUNS) |
  | `2` or any other non-zero | `{decision:'deny', reason:text}` | **block** |
  | timeout (60000ms default) / spawn error | `success:false`, **no output** | **fail open** (tool proceeds) |

  Two load-bearing consequences: (a) **exit 1 does NOT block** (correcting the "any non-zero warns"
  reading) — a gate must use `2`, never `1`, to deny; (b) a block **requires emitted text**: the
  runner parses `stdout.trim() || stderr.trim()` (L455), so `exit 2` with empty output leaves
  `output` undefined and does **not** deny. This gate always writes a stderr reason before `exit 2`.
  The only fail-open surface is a **timeout / spawn error** — which is exactly why the hook scripts
  belong on ext4 (see Hardening).

Two Gemini-specific things shape the design:

1. **Blocking events are `BeforeTool` / `BeforeAgent` / `BeforeModel` / `BeforeToolSelection`.** This
   gate is the `BeforeTool` layer (scope + society-safety on the actual tool call). The model/selection
   events are complementary hook points, not reimplemented here.
2. **Gemini has a native policy engine** (`docs/reference/policy-engine.md`, allow/deny/ask rules on
   tool calls). That is a *complement*, not a competitor: the policy engine handles coarse
   allow/deny/ask by tool; this gate handles MRH scope + egress/secret invariants + delegation to the
   society-safety governor. Compose them (policy engine for broad rules, hook for the Web4-specific
   boundary), do not duplicate.

Unlike Codex, Gemini's adapter does **not** yet lean on a sandbox for structural write/network
confinement — so scope rests entirely on this fail-closed gate (hardened path containment for explicit
paths + command-scope string-parsing for shell). Real read-confinement (bind-mount/container) and
using Gemini's sandbox flags are future hardening, same as the Codex `find .` relative-traversal limit.

| Act | Enforced by | Strength |
|---|---|---|
| Access to a secret/credential path | **BeforeTool gate** Gate-1a innate denylist | strong (always on, trust-independent) |
| READ/WRITE of out-of-scope repo (explicit path) | **BeforeTool gate** Gate-1b — shared `path_scope` realpath containment | strong for explicit paths (../, symlink, absolute all denied) |
| READ/WRITE of out-of-scope repo (via shell) | **BeforeTool gate** command-scope + launch-in-task-repo | weak (string-parse; relative-traversal escapes) |
| Unsafe write/exec (society safety) | **BeforeTool gate** Gate-2 → claude-code governor | strong for explicit; fail-closed |
| Witness / continuity | **observe.sh** + **hydrate.sh** | fail-open by design |

## Files

- `hooks/before_tool.py` — the fail-closed `BeforeTool` gate (Gate-1a egress/secret innate · Gate-1b
  MRH scope via the shared `../lib/path_scope.py` realpath containment · Gate-2 society-safety
  delegation to the claude-code governor). **First adopter of the shared `path_scope` lib** — one impl,
  no drift across adapters.
- `hooks/observe.sh` — fire-and-forget observation (SessionStart / AfterTool), always exit 0.
- `hooks/hydrate.sh` — identity persistence on SessionEnd, always exit 0.
- `hooks/hooks.json` — the `hooks` block to merge into `~/.gemini/settings.json` (or ship in a Gemini
  extension). Adjust the absolute paths per install.
- `instance/identity.seed.json` — the seed identity (foreign member #3, honest 0.5 T3, zero
  observations, `web4`-scoped MRH). Shape mirrors `plugins/codex` (substrate object, `mrh.scope_policy`
  prose, `milestones`, `sessions`). Copied to `~/.gemini/hestia-instance/identity.json` on first run.
  **`mrh.in_scope` is not hand-maintained** — hydrate regenerates it from
  `private-context/infrastructure/repos.jsonl` (visibility==public) + shared-context + launch cwd, so
  new public repos auto-grant and private stays denied-by-default (the current `hydrate.sh` here is a
  minimal stub; porting the full codex regeneration is the tracked follow-up).
- `GEMINI.md` — the standing law the member reads natively (siblings CLAUDE.md / AGENTS.md). Deploy to
  the granted repo root and `~/.gemini/GEMINI.md`.

## Configuration (env, all overridable)

| Var | Meaning | Default |
|---|---|---|
| `HESTIA_WORKSPACE` | root holding the granted repos | `~/ai-workspace` (set per host in hooks.json) |
| `HESTIA_SOCIETY_GATE` | society-safety governor to delegate to | `$WORKSPACE/hestia/plugins/claude-code/hooks/pre_tool_use.py` |
| `HESTIA_GEMINI_IDENTITY` | live identity.json | `~/.gemini/hestia-instance/identity.json` |
| `HESTIA_GEMINI_GATE_MODE` | `warn` \| `enforce` | `enforce` (deny-tight; relax as trust accrues) |
| `HESTIA_GEMINI_LAUNCH_CWD` | launch dir auto-granted for the session | `cwd` |
| `HESTIA_GEMINI_INSTANCE_DIR` | live identity + state dir | `~/.gemini/hestia-instance` |
| `HESTIA_OBSERVE_DIR` | observation log dir | `~/.gemini/hestia-observe` |
| `HESTIA_FORBIDDEN_EXTRA` | extra forbidden path tokens (comma-sep) | — |

(Shared env names — `HESTIA_WORKSPACE`, `HESTIA_SOCIETY_GATE`, `HESTIA_FORBIDDEN_EXTRA`,
`HESTIA_OBSERVE_DIR`, `HESTIA_REPO_REGISTRY` — and the per-member `HESTIA_GEMINI_*` prefix follow the
codex convention so nothing drifts across adapters.)

## Install

1. Deploy `instance/identity.seed.json` → `~/.gemini/hestia-instance/identity.json` (edit `mrh.in_scope`
   to the repos this member is granted).
2. Deploy `GEMINI.md` → the granted repo root and `~/.gemini/GEMINI.md`.
3. Merge `hooks/hooks.json`'s `hooks` block into `~/.gemini/settings.json`, fixing the absolute paths
   and `HESTIA_WORKSPACE` for the host.
4. (Optional) Add a Gemini **policy-engine** rule set for coarse allow/ask defaults; this gate handles
   the Web4 boundary on top.

## Verification

Smoke-tested against synthetic `BeforeTool` events (2026-07-22, on Nomad):

- wrong event (`AfterTool`) → passthrough exit 0 ✓
- read in-scope repo → allow exit 0 ✓
- read out-of-scope repo → deny exit 2 (shared `path_scope` realpath reason) ✓
- secret path (`.env`) → deny exit 2 (innate) ✓
- shell command reaching an out-of-scope repo → deny exit 2 (command-scope) ✓
- malformed event JSON → deny exit 2 (fail-closed) ✓

**Not yet done (the `verified` bar):** run against a real Gemini CLI, confirm the exact `tool_input` arg
names for each builtin tool (shell / file), confirm `BeforeTool` fires for MCP calls, confirm the
fail-open behavior empirically. That belongs on the onboarding rig.

## Hardening (deployment notes)

- **Put the hook scripts on ext4, not `/mnt/c`.** The only fail-open surface is a **timeout** (or
  spawn error); on WSL, a 9p cold-load of a `/mnt/c` script can exceed the hook timeout, and a
  timed-out gate on this fail-open engine ALLOWS the call. Deploy the scripts (or a symlink to them)
  under `~` / ext4 so the gate's cold-start stays well under the timeout. The `hooks.json` timeouts
  here (15s gate) are generous vs Gemini's 60s default, but ext4 is the real mitigation.
- **Compose with, don't fight, Gemini's native policy engine.** Use the policy engine for coarse
  allow/ask/deny-by-tool defaults; this hestia gate owns the Web4 boundary (MRH scope + egress/secret
  innate + society-safety delegation). State explicitly per deployment which acts native policy covers
  vs. this gate, so there is no silent gap between the two layers.
- **A block must emit text.** Any custom exit-2 path added later MUST write a reason to stderr (empty
  output + exit 2 does not deny — see the contract table). Never `exit 1` to deny (it allows).

## Accountability self-audit (RWOA + S + V)

```
surface: gemini BeforeTool gate   act: allow/deny a foreign member's tool call (write/exec/read scope)
S: med/reversible (a single denied-or-allowed tool call; irreversible egress is the high-stakes tail) [construct: MODE=enforce default]
R: n/a — the gate does not authorize on reachability; it authorizes on MRH scope read from role-sourced identity [construct: load_in_scope]
W: pass — scope comes from the member's identity (role-sourced, grant-time), not a hook-time editable input; society-safety defers to the witnessed claude-code governor [construct: Gate-2 delegation]
O: pass — the gate runs BeforeTool, before any side effect; a denied act leaves state bit-identical (exit 2, no mutation) [construct: main() before sys.exit]
A: n/a here — this is an enforcement point, not a ledger writer; witness/continuity is observe.sh + the governor's record [construct: observe.sh]
V: present — egress/secret is an innate always-deny (the catastrophic-irreversible tail); operator holds the widen/veto [construct: deny(..., innate=True)]
verdict: PASS (documented; re-audit after live-CLI verification)
```
