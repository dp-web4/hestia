# Hestia adapter for Google Antigravity CLI (`agy`)

Governance scaffold that onboards **Antigravity** (Google's closed-source `agy`, the successor to
gemini-cli) as a foreign member of the fleet — the sixth (after kimi #1, codex #2, gemini #3, kiro #4,
crush #5). Antigravity is gemini-lineage, so this adapter is the **gemini gate inverted**: same scope
machinery, opposite output contract and failure model.

> **Fidelity: documented, not live-verified (2026-07-28).** Antigravity is closed-source, so the
> contract is from its docs, the gemini lineage, and the manaflow-ai/cmux issue threads — not source.
> The gate is smoke-tested against synthetic events but has **not** run against a live `agy`. The
> verified pass belongs on CBP's rig. **A fail-closed engine makes this caveat sharper than gemini's:**
> an over-strict guess here *blocks work* rather than failing safe, so the live pass must confirm normal
> `agy` events **allow cleanly**, not just that denies deny.

## What Antigravity is — and the two inversions

`agy` v1.1.x, installed via `curl -fsSL https://antigravity.google/cli/install.sh | bash` (binary in
`~/.local/bin/agy`, reuses the `~/.gemini/` config tree). Access is **subscription/usage-limited**
(Free 20 req/day, Pro $20/mo, Ultra $250/mo, + $0.01 credit overflow), not per-token API. Its hook
engine is gemini-lineage but inverted where it counts:

| | gemini-cli | Antigravity (`agy`) |
|---|---|---|
| block event | `BeforeTool` | **`PreToolUse`** (renamed) |
| verdict channel | exit code (2 = deny) + stderr | **stdout `{"decision":"allow"\|"deny","reason":...}`**, exit 0 |
| failure model | **fails OPEN** (error/timeout/odd-exit = allow) | **fails CLOSED** (error / non-zero exit = **deny**) |
| the danger | crash → *allow* (ungoverned) | crash/slow/over-strict → *block everything* (unusable) |

The failure-model flip is the whole lesson of this adapter. gemini's gate carried a **deny**-on-exception
because a crash there would allow. Antigravity's gate does the opposite work: because a crash already
denies (and `agy` will block *every* tool call on a broken hook — cmux #4768/#5358), the imperatives are
**(a)** emit an *explicit, reasoned* verdict on both paths (stdout JSON + exit 0) so a deny is legible
instead of `agy`'s generic "hook failed" block, **(b)** stay robust and fast so normal work never
spuriously blocks, **(c)** still fail closed on genuine inability to vouch, but via an explicit
`{"decision":"deny"}` (the engine's implicit non-zero=deny is only the backstop). Bonus: this is the
clean deny-UX gemini's exit-2 path could not give.

## Gate design

Only ever exits 0 with a stdout decision. Three gates (identical scope logic to gemini):

1. **Gate-1a — innate egress/secret denylist**, swept across file paths, the shell command,
   `web_fetch`/`google_web_search` URLs+prompts, and MCP arguments.
2. **Gate-1b — MRH scope** via the shared `../lib/path_scope.py` realpath containment for file paths;
   command-scope for the shell command + MCP transport. Egress URLs are not realpath-scoped.
3. **Gate-2 — society safety.** Write/exec + egress + MCP defer to the claude-code governor via the
   gemini-shaped `to_claude_lineage` translation; local reads skip it. Fail-closed → explicit deny.

## Files

- `hooks/pre_tool_use.py` — the fail-closed PreToolUse gate (decision-JSON output, translator,
  crash→clean-deny guard, `path_scope`).
- `hooks/observe.sh`, `hooks/hydrate.sh` — fire-and-forget; **emit `{}` + exit 0** (on a fail-closed
  engine even an observer must return a clean allow or it would block). Wire to SessionStart / Stop.
- `hooks/hooks.json` — the block to merge into `~/.gemini/config/hooks.json` (or ship as a plugin under
  `~/.gemini/antigravity-cli/plugins/<name>/`).
- `instance/identity.seed.json` — member #6, honest 0.5 T3, `web4`-scoped.
- `AGENTS.md` — the standing law.

## Install & hardening

1. Deploy `instance/identity.seed.json` → `~/.gemini/antigravity-cli/hestia-instance/identity.json`.
2. Deploy `AGENTS.md` → the granted repo root (+ `~/.gemini/` per agy's context convention).
3. Merge `hooks/hooks.json` into `~/.gemini/config/hooks.json`, fixing absolute paths + `HESTIA_WORKSPACE`.
- **ext4, not `/mnt/c`.** Because deny is the failure mode, a slow 9p hook load that exceeds the timeout
  *blocks* the call (the opposite of gemini, but just as bad for usability). Keep the scripts fast/local.
- Repoint the `/mnt/c` paths per install.

## Verification

Smoke-tested against synthetic events (2026-07-28, Nomad), asserting the stdout `decision` + exit 0:
wrong-event → allow; in-scope read → allow; out-of-scope read → deny (path_scope reason); secret →
deny; out-of-scope shell → deny; `web_fetch` secret-in-prompt → deny; malformed JSON → deny
(fail-closed); forced-crash → clean `{decision:deny}` + exit 0. **Not yet done (the `verified` bar):**
run against a live `agy` — confirm the real event/tool/arg names, confirm `PreToolUse` fires for
shell/write/MCP, and **confirm normal events ALLOW cleanly** (the fail-closed usability risk). CBP's rig.

## Accountability self-audit (RWOA + S + V)

```
surface: antigravity PreToolUse gate   act: allow/deny a foreign member's tool call (read/write/exec/egress scope)
S: med/reversible (one gated tool call; irreversible egress is the high-stakes tail) [construct: MODE=enforce]
R: n/a — authorizes on MRH scope from role-sourced identity, not reachability [construct: load_in_scope]
W: pass — scope from grant-time identity, not a hook-time editable input; safety defers to the witnessed claude-code governor [construct: Gate-2 to_claude_lineage]
O: pass — runs PreToolUse, before any side effect; a denied act leaves state bit-identical (decision:deny, no mutation) [construct: _gate before _emit]
A: n/a — enforcement point, not a ledger writer; witness rides observe.sh + the governor's record [construct: observe.sh]
V: present — egress/secret innate always-deny; crash → explicit deny (engine also fails closed); operator holds widen/veto [construct: deny(innate=True) + main() guard]
verdict: PASS (documented; re-audit after live-CLI verification)
```
