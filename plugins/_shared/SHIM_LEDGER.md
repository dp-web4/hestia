# Shim ledger: why each function is in a shim and not in the common gate

Ruling (dp, GATE_ARCHITECTURE section 2): a line may live in a shim only if it is demonstrably unique to the peculiarities of that harness. The burden of proof is on the shim. This ledger is that proof, one row per top-level function or class in each seat's gate module, read by `tools/shim_ledger_check.py` in CI.

A row's class is one of the five things section 2 lets a shim own, the wiring that reaches the gate, or admitted debt:

| class | meaning |
|---|---|
| event-shape | how this harness spells its event; translation only, assigns no meaning |
| refusal-channel | how this harness is told no: exit code, stdout payload, the fail-open default of its hook engine |
| registration | where this harness records its hooks and how that file is read |
| identity | the plugin id and role this seat acts under, passed to the gate |
| launch | platform launch and restart verbs |
| wiring | the installed-only loader, endpoint discovery, and thin one-call delegation to the engine |
| LAW-DEBT | no section-2 justification: either law that still decides in the shim, or shared mechanism that is not harness-unique. Names the issue that owns its move. |

`src` is a hash of the function's source. Change the function and its row is stale until the justification is re-read and re-affirmed in the same change; `tools/shim_ledger_check.py --refresh` rewrites the hash, never the words. The check judges nothing about a justification. A reviewer does. dp, 2026-09-02: every heuristic can be gamed by a competent reasoner; governing reasoners needs reason in the loop.

**One-gate stage C (2026-10-04): every seat is the certified template.** Each seat's gate module is `plugins/_template/shim_template.py` — five byte-identical bootstrap/main functions, three per-seat adapters, and two dicts of data (`PROFILE`: who this seat is; `HARNESS`: where its harness records the hook and what its timeout means). Every law-bearing step — closure, egress, snapshot, `core.evaluate`, society safety, the record, C11, the launch-role bound, the rollout — is `hestia_single_gate.decide()`. The LAW-DEBT rows the pre-template shims carried (#844, #741, #370) are discharged, not moved: their code is deleted and the common gate is the one implementation. `plugins/_shared/shim_structure_test.py` checks that the function set is exactly the template's, the five common functions are byte-identical to it, and PROFILE/HARNESS are data; this ledger carries the reasons.

Module-level data sits outside the function grain. For every seat it is: the certification scalars (equal to the template's), `MEMBER_ID`, `_START` (the monotonic instant the harness spawned the process, the anchor of the deadline), `PROFILE` and `HARNESS` (literals and one-argument reads of the projected environment, nothing else), and `_ROLE_PERMITTED`/`_PROJECTION_ERROR` (the projection loader's recorded outcome, judged by the gate). No seat carries a timeout constant, a rollout knob, a marker table or a fallback.

## claude-code

`plugins/claude-code/hooks/pre_tool_use.py`

| function | class | src | justification |
|---|---|---|---|
| `_load_projection` | wiring | cca6c6ca | Exports the vault-rendered projection `$HESTIA_HOME/seats/<member>.env` into the environment before the gate is located; byte-identical to the template. It decides nothing about a tool call: it drops a launcher-supplied rollout (the projection alone may set it, C5), keeps `HESTIA_ROLE_PERMITTED` aside unjudged for the gate's launch-role verdict (#1084), and records any miswire for `main` to refuse. It cannot live in shared authority because it is what makes shared authority findable. |
| `_authority_dir` | wiring | 92b53007 | The installed engine directory: the projection's explicit HESTIA_SHARED_DIR, else $HESTIA_HOME/shared, never a checkout (#742, C1). Byte-identical to the template. |
| `_load_gate` | wiring | 2226ad10 | The installed-only loader for the common gate: canonical sys.path precedence, every `hestia_*` module cached from outside the selected authority evicted before the gate loads (#747: a cached module beats sys.path, so the gate's sibling imports would bind it), the loaded file verified to be the required one, initialisation failure converted to ImportError, and the gate API version checked (C1). Byte-identical to the template; the one law-adjacent text that cannot be loaded from shared authority because it reaches it. |
| `_emergency_block` | refusal-channel | 29e2591c | The refusal when the common gate itself is unavailable (no projection, no engine, an unreadable event, a broken shim): exit 2 with text on stderr, which blocks on all four harnesses, plus a local availability row because the recorder is the thing that is gone (C7b). Byte-identical to the template. |
| `to_event` | event-shape | f723c94c | Claude Code speaks the lineage vocabulary the law is written in, so translation is the identity: tool name, input object, cwd, session id and tool_use_id, with the raw event riding along for the correlation key. A non-PreToolUse event is not a tool event; a non-object tool_input is refused, never guessed. |
| `emit` | refusal-channel | a56e1cc2 | Claude Code's blocking protocol: exit 2 blocks with the gate's rendered text on stderr; exit 0 allows, a warn or an approved-write notice shown on stderr. The words are the gate's one renderer (`render`, C6); only the channel is this harness's. |
| `read_harness_event` | event-shape | 92202719 | One JSON object on stdin, as Claude Code delivers it. An empty or non-object event is no event, which the template refuses (no verdict, no act). |
| `main` | wiring | 111a36c5 | The template's spine, byte-identical: refuse an unconfigured seat, read the event, load the gate, translate, ask `harness_bound` for the deadline the harness's REAL registration allows, `decide`, render. It sequences no governance and chooses no posture. |

## codex

`plugins/codex/hooks/pre_tool_use.py`

| function | class | src | justification |
|---|---|---|---|
| `_load_projection` | wiring | cca6c6ca | Byte-identical to the template (see the claude-code row): exports the seat's projection, drops a launcher rollout, keeps the launch-role bound aside for the gate, records a miswire for `main`. Before stage C codex read no projection at all and guessed `~/.hestia` (#944). |
| `_authority_dir` | wiring | 92b53007 | Byte-identical to the template: the projection's HESTIA_SHARED_DIR or $HESTIA_HOME/shared, never a checkout (#742, C1). |
| `_load_gate` | wiring | 2226ad10 | Byte-identical to the template: the installed-only loader for the common gate with stale-sibling eviction (#747) and file and API-version verification (C1). |
| `_emergency_block` | refusal-channel | 29e2591c | Byte-identical to the template: exit 2 with stderr text when the gate is unavailable, which Codex treats as a block (its engine fails OPEN on every other failure), plus a local availability row (C7b). |
| `to_event` | event-shape | f723c94c | Codex is Claude-Code lineage and its tool names are ones the gate already understands (`bash` with a string or argv list, `apply_patch` with its targets in the diff body, `mcp__*`), so translation is the identity; the raw event rides along for the correlation key. A non-PreToolUse event is not a tool event. |
| `emit` | refusal-channel | a56e1cc2 | Codex's blocking protocol: exit 2 with the rendered text on stderr blocks; exit 0 allows, a warn or notice on stderr. The words are the gate's renderer (C6). |
| `read_harness_event` | event-shape | 92202719 | One JSON object on stdin. An empty event is refused (the pre-template gate read empty stdin as `{}` and allowed it as "not our event"). |
| `main` | wiring | 111a36c5 | Byte-identical to the template: the translate, bound, decide, render spine; no governance of its own. |

## kimi

`plugins/kimi/hooks/pre_tool_use.py`

| function | class | src | justification |
|---|---|---|---|
| `_load_projection` | wiring | cca6c6ca | Byte-identical to the template (see the claude-code row). Before stage C kimi had no installed-only loader at all and no projection (C1's named failure). |
| `_authority_dir` | wiring | 92b53007 | Byte-identical to the template: the projection's HESTIA_SHARED_DIR or $HESTIA_HOME/shared; the working-tree fallback kimi carried (#801) is gone. |
| `_load_gate` | wiring | 2226ad10 | Byte-identical to the template: the installed-only loader for the common gate with stale-sibling eviction (#747) and file and API-version verification (C1). |
| `_emergency_block` | refusal-channel | 29e2591c | Byte-identical to the template: exit 2 with stderr text when the gate is unavailable; Kimi's engine fails OPEN on every other exit, timeout or crash, so this is the only safe refusal. |
| `to_event` | event-shape | f723c94c | Kimi is Claude-Code lineage: its `path`-keyed inputs are in the law's reach table and its `tool_call_id` is read from the raw event by the gate's correlation key, so translation is the identity. A non-PreToolUse event is not a tool event. |
| `emit` | refusal-channel | a56e1cc2 | Kimi's blocking protocol: exit 2 with the rendered text on stderr blocks; exit 0 allows, a warn or notice on stderr. The words are the gate's renderer (C6). |
| `read_harness_event` | event-shape | 92202719 | One JSON object on stdin. An empty event is refused (the pre-template gate allowed it). |
| `main` | wiring | 111a36c5 | Byte-identical to the template: the translate, bound, decide, render spine; no governance of its own. |

## gemini

`plugins/gemini/hooks/before_tool.py`

| function | class | src | justification |
|---|---|---|---|
| `_load_projection` | wiring | cca6c6ca | Byte-identical to the template (see the claude-code row). Before stage C gemini read no projection and spawned claude-code's gate as its governor, which asked the daemon AS claude-code (stage B finding 1). |
| `_authority_dir` | wiring | 92b53007 | Byte-identical to the template: the projection's HESTIA_SHARED_DIR or $HESTIA_HOME/shared; the repo-relative `../../lib` insert is gone. |
| `_load_gate` | wiring | 2226ad10 | Byte-identical to the template: the installed-only loader for the common gate with stale-sibling eviction (#747) and file and API-version verification (C1). |
| `_emergency_block` | refusal-channel | 29e2591c | Byte-identical to the template: exit 2 with stderr text, which gemini-cli's runner denies on any emitted text (its fail-open surfaces are only a timeout or a spawn error), plus a local availability row (C7b). |
| `to_event` | event-shape | a709fe74 | Gemini's own vocabulary becomes the lineage vocabulary the law is written in (run_shell_command, read_file, replace, absolute_path, mcp_<server>_<tool> via mcp_context); `include` globs and URLs inside a web_fetch prompt or an HTTP MCP server's url are lifted to the keys the law reads, and the MCP transport context rides as `_hestia_mcp_context` for the gate's egress and command scope. Pure translation: the tables were the old gate's LINEAGE_TOOL/LINEAGE_ARG. |
| `emit` | refusal-channel | ad7b1d76 | Gemini's TWO DENY CHANNELS, chosen by cause: a decided policy deny is exit 0 with a stdout JSON decision written in a full-write loop (a held boundary raises no operator "hook failed" banner); a deny the gate could not decide (an anomaly) is exit 2 with stderr text, where corrupted output still denies. The words are the gate's renderer (C6). |
| `read_harness_event` | event-shape | 1c5f5e1c | Rebinds sys.stdout to stderr first (fd 1 is gemini's verdict channel, and a stray byte there could shadow a deny into an allow), then reads one JSON object from stdin. |
| `main` | wiring | 111a36c5 | Byte-identical to the template: the translate, bound, decide, render spine; no governance of its own. |
