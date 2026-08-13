# Gate — current state ("as-is"), from source

**Companion to `PRD_GATE_CONSOLIDATION.md`** (the "to-be"). That PRD's status is **"Not started."**
This doc is the map of what is *actually enforcing today*, read from source (2026-08-13), so the gap
is inspectable rather than asserted. Every claim carries a `file:line` pointer.

> **Why this exists.** dp, repeatedly: *"we MUST have one gate with thin shims."* The design for that
> is written (the PRD) and the shared core is built — but it was never wired as the decider. Today the
> word "gate" names **five different implementations** with divergent behaviour. This session alone
> surfaced three consequences of that divergence (§6). This doc says exactly where we are so the
> wiring work has a baseline.

---

## 1. The one-line answer to "why don't we have it yet?"

The consolidation is **planned and half-built, not wired**:

- The shared **law core** `plugins/_shared/hestia_gate_core.py` (1016 lines, `evaluate() -> Verdict`,
  transport-free) **exists but nothing imports its decision function.** Its own header says *"NOT
  WIRED. Nothing imports this."* The only symbol imported from it anywhere is the telemetry helper
  `record_gate_unavailable` (`plugins/claude-code/hooks/pre_tool_use.py:2544`,
  `plugins/codex/hooks/pre_tool_use.py:516`).
- The shared **mechanism** (transport) `plugins/_shared/hestia_gate_mechanism.py::query_society_safety`
  is imported by **exactly one gate** — kimi (`plugins/kimi/hooks/pre_tool_use.py:800`), via PR #371/#372.
  That extraction got done because it *also* fixed the kimi/codex timeout firefight — the efficient
  path and the needed path coincided there. Nowhere else did.
- Everything else — the scope/egress **law**, the deny/witness **recorder**, and **self-protection** —
  is still **N hand-maintained forks**, one per harness, in their pre-hardening form.

So: the core is built, one transport is wired, and the decision logic is still copy-pasted. That is the
whole of "why not yet."

---

## 2. Five live topologies (there is no single "gate")

| Harness | Gate entry | Society-safety (daemon) path | Self-protection | Scope/egress law |
|---|---|---|---|---|
| **claude-code** | `plugins/claude-code/hooks/pre_tool_use.py:2663` | **own private** MCP client (`McpHttp` :2282) | **yes**, local (`_GOVERNANCE_FILES` :2262) | own copy |
| **kimi** | `plugins/kimi/hooks/pre_tool_use.py:716` | **shared** `query_society_safety` (:800) | **yes**, local, *re-added 2026-08-12* (:756-784) | own copy (:78-177) |
| **codex** | `plugins/codex/hooks/pre_tool_use.py:653` | **spawns the claude gate as a subprocess** (:722) | **none** | own copy (:134-259) |
| **gemini** | `plugins/gemini/hooks/before_tool.py:?` | **spawns the claude gate** (:464) | **none** | shared `lib/path_scope` (:108) |
| **cursor** | — | **no PreToolUse gate at all** (witness only) | **none** | — |

Four decision topologies plus one harness with no gate. codex and gemini reach "the authority" by
`subprocess.run([...claude gate file...])` — a hard-coded cross-plugin file path
(`CLAUDE_PRE`, codex:108 / gemini:115).

---

## 3. Per-plugin gate path, from entry to allow/deny

### claude-code — `plugins/claude-code/hooks/pre_tool_use.py`, `main()` @2663
1. Parse / fail-closed skeleton; unparseable → `deny_no_verdict` under `fail_closed()` (2664-2678).
2. **Self-protection (LOCAL, first, unconditional)** — `_touches_self` (2689) + `_touches_registration`
   (2691). Read → `_witness_self_read` (allowed+recorded, 2715). Write → `request_self_write` (2718);
   unapproved → `deny_self_access` (2725, def @1910). Scans **path keys AND command text** — this is
   the path that denied a read-only `find` this session because `pre_tool_use.py` was a substring of argv.
3. **Society safety** — `ask_daemon` (2734) via its **own** `McpHttp` (2282), `extract_target` (2265),
   `hestia_begin_action` (2445), poll → `emit_decision` (2742).
4. Daemon down → `deny_no_verdict` under `fail_closed()` (2747), else `invoke_legacy_fallback` (2754).

Shared imports: **only** `record_gate_unavailable` (2544, telemetry). The transport is a private duplicate.

### kimi — `plugins/kimi/hooks/pre_tool_use.py`, `main()` @716
1. Parse / fail-closed (718-722).
2. **Gate 1a** egress/secret innate invariant (LOCAL, 734-739) — `FORBIDDEN` tokens (:78).
3. **Gate 1b** MRH scope (LOCAL, 741-754) — `path_in_scope` (:153), `command_in_scope` (:177).
4. **Gate 1c** self-protection (LOCAL, 756-784) — `_touches_self` (:508); write → `_claim_self_write`,
   unapproved → `exit(2)`. **Re-added 2026-08-12** after the in-process rewire silently dropped it
   (comment 471-490).
5. **Gate 2** society safety — **shared** `query_society_safety` (:800, `plugin_id="kimi-code"`).
6. Allow → `exit(0)` (825-826).

### codex — `plugins/codex/hooks/pre_tool_use.py`, `main()` @653
1. Parse / fail-closed (655-659).
2. `apply_patch` special-case: check target paths only, not the patch body (668-673).
3. **Gate 1a** egress/secret innate (LOCAL, 678-682).
4. **Gate 1b** MRH scope (LOCAL, 684-706).
5. **No self-protection gate exists** (grep for `_touches_self`/`gate_self` in codex → nothing). It is
   inherited only by side-effect of step 6.
6. **Gate 2** society safety — `subprocess.run([sys.executable, CLAUDE_PRE], input=event, timeout=2)`
   (:722). `CLAUDE_PRE` = `$WORKSPACE/hestia/plugins/claude-code/hooks/pre_tool_use.py` (:108).
7. Allow → `exit(0)`.

### gemini — `plugins/gemini/hooks/before_tool.py`
Local scope via **shared** `path_scope.check_paths` (:108), then society safety by **spawning the
claude gate** (:464). No local self-protection. Independent exit-code contract.

### cursor
`plugins/cursor/hooks/witness.py` only — a PostToolUse witness. **No gate.**

---

## 4. Why the audit trail differs per member (the §6 symptom, root cause)

Only the `begin_action` **chain** record carries a command `target`; the `hestia_witness_decision`
**deny** record carries **no `target` field for any plugin** (kimi 442-450, codex 623-637).

- **claude-code:** target **populated** — `extract_target` (2265) matches its native `"Bash"`
  (`tool_name in {"Bash","Shell"}`, 2272) and stores the executable in `begin_args` (2437).
- **codex:** target **empty** — codex spawns the claude gate, which runs `extract_target` on *codex's*
  event, whose shell `tool_name` is **lowercase `"bash"`** (codex docstring 13-14). `{"Bash","Shell"}`
  does not contain `"bash"` → returns `None` → `target=None`. **This is a case-sensitivity bug in the
  shared-by-spawn path, confirmed from source.**
- **kimi:** *Not reproducible from current source.* Kimi's present in-process path uses the shared
  mechanism's `_extract_target`, which recognises `"Bash"` (mechanism:187) and kimi emits `"Bash"`
  — so today's code path *would* populate the target. An observed empty target for kimi matches either
  kimi's **pre-migration** spawn behaviour or the target-less deny-witness record, **not** the current
  path. Flagged, not asserted.

> **Correction to an earlier claim this session:** I told dp "codex *and kimi* strip the command text
> because their audit-write paths diverged." Accurate for codex (the `"bash"` vs `"Bash"` bug); for
> kimi the current source does *not* reproduce it. The uniform true statement is narrower: **no deny
> record carries a target for anyone, and codex's chain record loses it to a case mismatch.**

---

## 5. What is shared vs forked (quantified)

**Genuinely shared (runtime imports):**
- `query_society_safety` — kimi only (kimi:800).
- `record_gate_unavailable` — claude (2544) + codex (516); **telemetry, not a decision**.
- `path_scope.check_paths` — gemini only (before_tool:108).

**Forked (the decision logic itself):**
- claude-code carries a private copy of the whole transport (`McpHttp` 2282, `extract_target` 2265,
  poll/emit) duplicating `_shared/hestia_gate_mechanism.py`.
- Scope/egress law — `path_in_scope`, `command_in_scope`, `FORBIDDEN`, `READ_CLASS`, `load_in_scope`,
  `launch_cwd_repo`, `_all_repos`, `command_of` — re-implemented per gate in pre-hardening
  substring/lexical form, while the hardened versions sit **unused** in `hestia_gate_core.py`
  (`PRD_GATE_CONSOLIDATION.md:19,38-39`).
- Deny/witness recorder — divergent three ways: kimi `_daemon_witness` (:414, swallowed try/except,
  **no `verdict_available` flag** so it cannot distinguish a real deny from an infra fail-close) vs
  codex `_daemon_witness` (:576, carries `verdict_available` :632) vs claude's `witness.py`.
- Self-protection — exists in claude-code and (re-added) kimi; **absent in codex, gemini, cursor**
  (`PRD_GATE_CONSOLIDATION.md:71` — "a member editing its own hook is caught by no one").

`_shared/README.md` counts **24 function names appearing in two or more gates**.

---

## 6. This session's evidence that the divergence is active harm

1. **codex/kimi deny records have no command text** (§4) — the dashboard faithfully shows the fleet
   getting blocked with no way to tell a false positive from real containment. Root cause is a forked
   audit path + a case-sensitivity bug, not policy.
2. **The destructive preset FP'd a chained `rm /tmp/...`** — allowed standalone, blocked when chained
   with benign git commands (the compound over-match, issue #393).
3. **The self-access matcher FP'd a read-only `find`** — because `pre_tool_use.py` appeared as a string
   in argv. Matching text, not the act. A single core with a write-position predicate (the
   `PRD_GATE_CONSOLIDATION.md` design) has one place to fix this; five forks have five.

---

## 7. How a new plugin's gate is added TODAY

From `deploy/install-members.sh`, each plugin's `expects.json`, and `docs/PLUGIN_AUTHORING_GUIDE.md`:

1. **Create `plugins/<name>/hooks/<gate>.py`** — a PreToolUse gate (or `BeforeTool` for gemini-lineage),
   **fail-closed by construction** (default deny; reach `exit 0` only on an explicit allow).
2. **Create `plugins/<name>/expects.json`** — the install manifest: `"gate": ["PreToolUse"]`,
   `"observe": ["PostToolUse"]`, and `"install": { "dest": <~/harness/hooks>, "registration": {
   "reader": "json-hook-commands" | "toml-hook-commands", "path": [<config dir>, <config file>] },
   "files": [...] }`.
3. **Register the hook in the harness's own config first** — `.claude/settings.json` (json) or
   `.codex/config.toml` (toml). `install-members.sh` **reads** the already-registered command and
   installs only to registered paths; it never `mkdir`s or fabricates a registration (comment 30-33,
   227-232). An unregistered hook is **silently skipped**.
4. **Run `deploy/install-members.sh`** — guarded (a governed session needs
   `HESTIA_GATE_INSTALL_ACK=i-am-the-operator`, lines 69-106); it backs up, `install -m 0755` copies,
   and **verifies installed hash == source hash** (249-253).

**What a new author must NOT forget — the anti-thin-shim couplings:**
- **Self-protection is per-gate and hardcoded.** A new plugin's own hook files are protected by *no
  one* unless its `hooks` dir/filenames are added to the marker lists — which live **inside other
  plugins' gates** (kimi `_SELF_DIR_MARKERS` :498, claude `_GOVERNANCE_FILES` :2262). So adding a
  plugin means **editing other plugins' gate files** — the exact cross-plugin coupling "thin shims"
  was meant to remove.
- If the gate delegates society-safety by spawning (codex/gemini), it hard-codes the path to
  `plugins/claude-code/hooks/pre_tool_use.py`.
- **There is no shared decision core to import**, so the author copies the scope/egress predicates (as
  codex/kimi did) or spawns the claude gate. Either way the fork count grows by one.

Adding a plugin does **not** require editing `_shared` — but it **does** require editing peer gates
(self-protection markers). Until the core is wired and self-protection is centralised, "add a plugin
without touching existing code" is not achievable.

---

## 8. The shortest path to the PRD's target (from here)

The PRD has the full plan; the current-state delta is small in surface, large in risk:
1. Wire `hestia_gate_core.evaluate()` as the decider behind all five shims (it is built and tested).
2. Move the transport to `query_society_safety` for claude-code and codex/gemini (kimi already there),
   deleting the private `McpHttp` copy and the subprocess-spawn coupling.
3. Centralise self-protection markers (one registry the core reads) so a new plugin is protected
   without editing peers — and fix the `"bash"`/`"Bash"` target case bug on the way (§4).
4. One deny recorder with a `target` field and a `verdict_available` flag, so the audit trail is
   uniform (fixes §6.1).
5. cursor: decide whether it gets a gate or is documented as witness-only-by-design.
