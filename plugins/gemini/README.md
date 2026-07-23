# Hestia adapter for Google Gemini CLI

Governance scaffold that onboards the **Gemini CLI** (Google) as a foreign member of the fleet — the
third after Kimi (#1) and Codex (#2). Modeled on `hestia/plugins/codex/`, but Gemini is an
**independent lineage** (Google's own hook engine + a native policy engine), so the contract was read
from Google's docs rather than inherited. Verifying the harness contract instead of assuming it is the
whole method.

> **Fidelity: source-verified contract + LIVE-VERIFIED adapter pass (2026-07-22).** The exit-code /
> deny / fail-open contract below is read from gemini-cli **source** (file+line cited), not just docs
> or blogs — per CBP's method note (a blog claim that Codex PreToolUse was "Bash-only" was wrong;
> source corrected it). CBP then wired this gate in as the real `BeforeTool` hook of an installed
> gemini-cli 0.52.0 and fired it with model round-trips: in-scope read allowed; out-of-scope read,
> `../` traversal, symlink escape, absolute out-of-scope, out-of-scope shell command, governor deny
> and malformed JSON all denied `exit 2`, with the hestia reason surfaced verbatim to the model. Arg
> names confirmed live (`read_file` → `file_path` absolute, `run_shell_command` → `command`). The
> same pass found two holes (ungated web egress, `mcp_context` unread), closed here. Nomad built the
> adapter from the descriptor + vendor source; CBP owns the rig and the live tier.

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

Unlike Codex, Gemini's adapter does **not** lean on a sandbox for structural write/network
confinement — so scope rests entirely on this fail-closed gate (hardened path containment for explicit
paths + command-scope string-parsing for shell). Real read-confinement (bind-mount/container) and
using Gemini's sandbox flags are future hardening, same as the Codex `find .` relative-traversal limit.

**Gemini does have a native containment layer — but only for file tools.** Live-verified by CBP
(2026-07-22): out of the box the file tools are confined to the launch dir (plus
`--include-directories`), and `.env` files are natively refused — an out-of-scope read and a secret
read were both denied by the CLI *before* this hook mattered (CBP had to widen the native boundary
with `--include-directories` to exercise the gate at all). **Shell commands, MCP calls and the web
tools have no such native layer.** So the "layer" column below is not decoration: it is the hardening
priority map. Where this gate is the *only* layer is exactly where its weakest mechanism
(command-scope string-parsing) lives.

| Act | Enforced by | Layer | Strength |
|---|---|---|---|
| Access to a secret/credential path | **Gate-1a** innate denylist (paths, shell command, `url`/`prompt`/`query`, `mcp_context` args) | 2nd (CLI natively refuses `.env`) | strong (always on, trust-independent) |
| READ/WRITE of out-of-scope repo (explicit path) | **Gate-1b** — shared `path_scope` realpath containment | 2nd (CLI confines file tools to launch dir) | strong for explicit paths (`../`, symlink, absolute all denied) |
| READ/WRITE of out-of-scope repo (via shell) | **command-scope** + launch-in-task-repo | **ONLY layer** | weak (string-parse; relative-traversal escapes) |
| Out-of-scope reach via an MCP server | **Gate-1a + command-scope** over `mcp_context.command`/`args`, then Gate-2 | **ONLY layer** | moderate (transport args are inspected; server-internal semantics are not) |
| Network egress (`web_fetch` / `google_web_search`) | **Gate-1a** sweep of `url`/`prompt`/`query`, then **Gate-2** governor | **ONLY layer** | moderate — and this is the irreversible direction |
| Unsafe write/exec (society safety) | **Gate-2** → claude-code governor | **ONLY layer** | strong for explicit; fail-closed |
| Witness / continuity | **observe.sh** + **hydrate.sh** | — | fail-open by design |

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

### Standing grants beyond `mrh.in_scope` (deliberate — know them)

The gate grants three roots on top of the member's MRH. They are design choices, not oversights:

- `~/.gemini` — the member's own home (identity, state, config). Without it the gate would deny the
  member reading its own identity.
- **`/tmp` and `/var/tmp`** — unconditional staging grant, so scratch work doesn't need a scope
  request. **On a shared host this is a cross-member channel**: anything gemini writes to `/tmp` is
  readable by every other member on the box, and anything they write there is reachable by gemini.
  Treat `/tmp` as public, never as a place to stage anything scoped. (It also swallowed CBP's first
  smoke run whole — a test workspace under `/tmp` makes every out-of-scope path trivially "contained",
  which is why `tests/gate_holes_repro.sh` refuses to sandbox there.)
- the **launch cwd's repo** — a per-session dynamic grant (see `HESTIA_GEMINI_LAUNCH_CWD`), so a
  task-specific launch dir is reachable without widening the standing grant.

(Shared env names — `HESTIA_WORKSPACE`, `HESTIA_SOCIETY_GATE`, `HESTIA_FORBIDDEN_EXTRA`,
`HESTIA_OBSERVE_DIR`, `HESTIA_REPO_REGISTRY` — and the per-member `HESTIA_GEMINI_*` prefix follow the
codex convention so nothing drifts across adapters.)

## Install

1. Deploy `instance/identity.seed.json` → `~/.gemini/hestia-instance/identity.json`, then set
   `mrh.in_scope` to the repos this member is granted. **Hand-editing is the truth today** — the seed's
   `_note` describes the *target* state (hydrate regenerating `in_scope` from the repo registry, as
   `plugins/codex` does), and that port has not landed here yet; this `hydrate.sh` is a stub. Until it
   does, hand-edit, and re-check after the port so a hand-edit doesn't get silently overwritten.
2. Deploy `GEMINI.md` → the granted repo root and `~/.gemini/GEMINI.md`.
3. Merge `hooks/hooks.json`'s `hooks` block into `~/.gemini/settings.json`, fixing the absolute paths
   and `HESTIA_WORKSPACE` for the host.
4. **Install at USER level (`~/.gemini/settings.json`), not project level.** Gemini gates
   Project-source hooks behind `isTrustedFolder()` — a project-scoped gate does not execute in an
   untrusted folder, i.e. it is absent exactly where you most want it.
5. **Pin the kill-switch explicitly** in `~/.gemini/settings.json`:
   ```json
   "hooksConfig": { "enabled": true }
   ```
   It defaults to `true` in 0.52.0, but `"enabled": false` disarms *every* hook, and a
   `hooksConfig.disabled` array (written by the `/hooks` UI) can disable this gate by command
   string. That is the operator's prerogative — but it must be a **visible** fact, not a silent one.
   Anything auditing this member should read `hooksConfig` as part of the gate's state.
6. (Optional) Add a Gemini **policy-engine** rule set for coarse allow/ask defaults; this gate handles
   the Web4 boundary on top. Note the gate sits *before* the policy engine: hook deny beats
   `--approval-mode yolo` (LIVE-VERIFIED, CBP 2026-07-22).

## Verification

Smoke-tested against synthetic `BeforeTool` events (2026-07-22, on Nomad):

- wrong event (`AfterTool`) → passthrough exit 0 ✓
- read in-scope repo → allow exit 0 ✓
- read out-of-scope repo → deny exit 2 (shared `path_scope` realpath reason) ✓
- secret path (`.env`) → deny exit 2 (innate) ✓
- shell command reaching an out-of-scope repo → deny exit 2 (command-scope) ✓
- malformed event JSON → deny exit 2 (fail-closed) ✓

**Fail-open holes found by repro and closed (2026-07-22, nomad).** The first cut of this gate passed
the smoke tests above while still allowing all four of these. Regression tests live in `tests/`:

```sh
plugins/gemini/tests/gate_holes_repro.sh          # 17/17 here, 12/17 against the pre-fix gate
plugins/gemini/tests/wrapper_failclosed_test.py   # 5/5 — fault-injects the deny-on-exception wrapper
```

They point `HESTIA_SOCIETY_GATE` at a nonexistent path on purpose: a correct gate fails **closed**
when it cannot reach the governor, so every write/exec/egress case must come back exit 2. Pass a
gate path as `$1` to test a different revision (keep the copy **inside `hooks/`** — from elsewhere the
relative `../../lib` import fails and the gate silently falls back to the string check, which
over-denies and makes a baseline look worse than it is).

The last section is different and deliberately so: it swaps in a governor stub that **allows**, so
the only thing that can deny is Gate-1. Egress and MCP are not `READ_CLASS`, so with the governor
down they deny at Gate-2 regardless of what Gate-1 does — a deny there would prove nothing about the
sweep. Any future Gate-1 assertion belongs in that section, not the first one.

| Hole | Why it was open | Fix |
|---|---|---|
| `read_many_files` skipped Gate-1b entirely | gate scanned `paths`/`file_paths`; the real params are `include`/`exclude` (source: `tools/definitions/base-declarations.ts`) | scan `include`/`exclude` too |
| `web_fetch` / `google_web_search` skipped Gate-2 | both sat in `READ_CLASS`; they *are* reads, but of the **network** — and gemini has no sandbox behind the gate | split out `EGRESS_CLASS`; egress now meets the governor |
| a crashing gate **allowed** the call | an uncaught Python exception exits 1, and exit 1 is ALLOW+warning, not a block | top-level deny-on-exception in `main()` |
| the governor was consulted but **blind** | it extracts targets from `file_path`/`path`/`url` and only reads `command` for `Bash`/`Shell` — gemini emits none of those names, so every shell command arrived as `target=None` | `to_claude_lineage()` translates at the boundary |

**Two more found by CBP's live adapter pass and closed (2026-07-22).** Both were Gate-1 blind spots
that the first fix round left behind — it moved egress into Gate-2 but never taught Gate-1 to *look* at
egress arguments at all:

| Hole | Why it was open | Fix |
|---|---|---|
| `web_fetch` reached the network with **zero Gate-1 inspection** (live: `?leak=SECRETDATA` ran clean) | `path_targets()`/`command_of()` never read `url`/`prompt`/`query`, so the innate secret denylist saw nothing — making GEMINI.md's "you cannot launder a secret out through … a web fetch" false | `egress_targets()` feeds those into the Gate-1a sweep; they are deliberately **not** fed to Gate-1b (realpath-containing a URL would deny every fetch) |
| MCP arguments were invisible to Gate-1 (live: an out-of-scope path in `mcp_context.args` passed) | an `mcp_<server>_<tool>` call's `tool_input` is the *server's* object; the transport surface lives in `mcp_context.{command,args}`, which the gate read only for naming | `mcp_strings()` feeds command + every string leaf of args into both the Gate-1a sweep and `command_in_scope` |

The exit-code contract these depend on is LIVE-VERIFIED on gemini-cli 0.52.0 by CBP
(`shared-context/forum/cbp-to-nomad-gemini-hook-contract-LIVE-VERIFIED-2026-07-22.md`): exit 0 =
allow, **exit 1 = allow+warning**, exit 2+ = deny, and empty output on *both* streams = no decision
= allow. So `sys.exit(2)` without writing a reason is itself a hole; every deny path here writes to
stderr first.

**Live tier (CBP's rig, gemini-cli 0.52.0 + real API, 2026-07-22)** — the `verified` bar is met for
the core paths: in-scope read allowed and returned contents; out-of-scope read denied with the full
hestia reason rendered to the model; `../`, symlink and absolute escapes denied; `run_shell_command`
into an out-of-scope repo denied; governor deny propagated with stderr preserved; malformed event
JSON denied. `tool_input` arg names confirmed (`read_file` → `file_path` absolute,
`run_shell_command` → `command`), and `BeforeTool` confirmed firing for MCP + shell + writes.

**Still unverified:** the two fixes above (egress sweep, `mcp_context`) are source-tier + regression
tests only — they landed after that pass. Re-fire on the rig to close them out. Also unverified: the
fail-open timeout behavior empirically (contract-read only).

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
