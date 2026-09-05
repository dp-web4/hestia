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

Module-level law (marker tables, mode defaults, timeout constants, loader fallbacks) sits outside the function grain and is listed per seat under "outside the rows"; #844 owns it with the debt rows.

## claude-code

`plugins/claude-code/hooks/pre_tool_use.py`

| function | class | src | justification |
|---|---|---|---|
| `_set_last_failure` | refusal-channel | 6c8e243c | Records the observed cause of the last daemon failure so this harness's stderr refusal can quote what is known; it chooses no posture. |
| `debug_log` | wiring | b57e6697 | Diagnostic sink under this seat's own state directory, keyed on this harness's env flag; decides nothing. |
| `discover_endpoint` | wiring | 1cd4b7d8 | Endpoint discovery for the installed gate: `HESTIA_ENDPOINT` or the `$HESTIA_HOME/endpoint` file. Named as wiring by the architecture. |
| `_shared_runtime_dir` | wiring | 66a8a074 | The installed-only loader's path resolution, byte-identical across seats (#742); the one text that cannot be loaded from shared authority because it is what reaches it. |
| `_load_shared_module` | wiring | 38815f39 | The installed-only loader, byte-identical across seats (#742, #747); load integrity, not a verdict. Its `BaseException` to `ImportError` boundary hands posture to `main`. |
| `_touches_self` | LAW-DEBT | 3b1a0a95 | Tier-2 gate-self closure matcher: 120 lines deciding which resources are the governance surface and whether a call reaches them. The shared `hestia_governance_closure.classify` owns this (#741, #370); the copy stays only as the import-failure fallback. |
| `_mentions_settings` | LAW-DEBT | b6e5bd22 | A containment predicate over this harness's settings file. The file's location is registration; the predicate is scope, and the marker tuple is gate data (#741). |
| `_hooks_stanza` | registration | d0ea148b | Parses Claude Code's settings blob and returns its `hooks` value: how this harness records its hooks and how that file is read, nothing more. |
| `_touches_registration` | LAW-DEBT | 946cf6f8 | Decides whether a call de-registers the gate, with a per-tool decidability doctrine and an unreadable-is-refused default. Closure determination plus posture; the shared classifier owns the text half (#741, #370). |
| `_emit_gate_event` | LAW-DEBT | 885b45fd | Composes the witness payload (event type, severity, fields) and sets a 1.5s never-block budget. The transport is shared (#371); the payload and the recovery posture are not this harness's. |
| `_witness_self_read` | LAW-DEBT | fdacff68 | One line, but the line picks the witness event class and `record` severity for an allowed governance read: witness content, gate data (#844). |
| `_witness_self_access` | LAW-DEBT | 33df07e4 | Picks the `escalate` severity and event class for a refused write: the record-vs-escalate split is escalation content (#844). |
| `_describe_hit` | LAW-DEBT | c35218e8 | Writes the words of the refusal and of the escalation record, including the payload-vs-destination judgement; denial content, forbidden in a shim (#844). |
| `deny_self_access` | LAW-DEBT | 58d71e99 | The exit code and stderr are this harness's channel; the multi-paragraph refusal, the escalation invitation and the witness-failure-is-not-permission rule are gate content (#844). |
| `_attempted_summary` | LAW-DEBT | c7f1b9c3 | Builds the redacted, bounded escalation reason. Its own docstring says it belongs on `Verdict` in the core; codex and kimi carry copies (#844). |
| `_credential_shaped` | LAW-DEBT | 6efef61c | Redaction predicate over payload text deciding what may enter the witness chain; nothing about it is Claude Code specific (#844). |
| `_connect_session` | LAW-DEBT | fbc90c89 | Passing plugin id, role and protocol version is identity, but the never-raise degrade rule ("the record degrades, never the channel") is recovery policy chosen here (#844). |
| `request_self_write` | LAW-DEBT | 3c206ed5 | The appeal channel: single round trip policy, every-failure-is-refusal posture, and the operator-facing banner. All three are named never-in-a-shim (#844). |
| `_escalation_plugin_id` | identity | cffc0046 | The plugin id this seat escalates under, from env or the module constant; identity passed to the gate (#244 fixed the fallback). |
| `_dig` | LAW-DEBT | 19193d70 | Generic MCP envelope search. It decides nothing, and it is not harness-unique: it duplicates what the shared `unwrap_tool_result` exists for and belongs beside it (#371). |
| `_load_mechanism` | wiring | fbcfca24 | One-return delegation to the installed-only loader for the mechanism module. |
| `McpHttp` | wiring | 315cea49 | Name-compatibility factory over the shared wire client; one return. |
| `unwrap_tool_result` | wiring | 0eec5291 | One-return delegation to the shared envelope unwrapper. |
| `ask_daemon` | wiring | f55d5098 | Marshals this seat's identity and version into the mechanism's `query_society_safety` and hands back its verdict; the no-verdict posture it documents is the mechanism's contract, not invented here. |
| `cache_action` | event-shape | ac22e614 | Writes the action under this harness's `tool_use_id` so this harness's PostToolUse hook can pair the outcome; a correlation artifact of Claude Code's two-hook shape. |
| `_record_plane_e` | wiring | bfd535b8 | One call into the core's `record_gate_unavailable` with this seat's id attached. |
| `deny_no_verdict` | LAW-DEBT | c4a1cf60 | Only `return 2` and stderr are channel; the per-cause remedy paragraphs and the retry advice told to the member are refusal content and retry policy (#844). |
| `_fallback_self_protection` | LAW-DEBT | 6cb6ca62 | A second implementation of the closure decision (read-vs-write split, closure calls, degraded posture) kept alive for import failure: the state the architecture exists to end (#741, #370). |
| `emit_decision` | refusal-channel | e4b2b394 | Maps the mechanism's verdict kind to Claude Code's exit code and writes the mechanism-composed text; re-derives nothing. |
| `main` | LAW-DEBT | 7aa172ae | The spine is channel, event shape and identity. The debt is inline: the `HarnessProfile`'s scope markers, two authored scope-deny messages, the `no-shared-authority` refusal prose, and the branch that keeps the Tier-2 matcher reachable (#741, #844). The row flips to wiring when `main` is translate, evaluate, render. |

Outside the rows (#844): `TOTAL_BUDGET_MS`, `REQUEST_TIMEOUT_S`, `MAX_POLLS`, `MIN_POLL_SLEEP_MS`, `ESCALATION_RPC_TIMEOUT_S` (timeout and poll policy); `_SELF_MARKERS`, `_GOVERNANCE_FILES`, `_HOOKS_DIR_ONLY`, `_SETTINGS_MARKERS`, `_REGISTRATION_TOKENS` (the closure as data, for all five harnesses); `_CREDENTIAL_SHAPES` (redaction table); the module-init import guards that choose Tier-2 versus deny; the `__main__` crash handler's posture; several hundred lines of adjudicated shell-classifier commentary whose code moved to `hestia_shell_classifier` and whose rulings did not.

## codex

`plugins/codex/hooks/pre_tool_use.py`

| function | class | src | justification |
|---|---|---|---|
| `_detect_workspace` | LAW-DEBT | 26d7dddd | Resolves the scope root (env, marker walk, cwd). That root is the containment argument to every scope predicate, and nothing in the rule is codex specific; kimi carries the same bytes (#760, #839). |
| `_shared_runtime_dir` | wiring | 66a8a074 | The installed-only loader's path resolution, byte-identical across seats (#742). |
| `_load_shared_module` | wiring | 38815f39 | The installed-only loader, byte-identical across seats (#742); load integrity, not a verdict. |
| `_load_mechanism` | wiring | bf34d0bf | One-return delegation to the installed-only loader for the mechanism module. |
| `_role_bridge` | identity | cd4c767a | One call into the mechanism's role bridge with this seat's identity path; the except-branch literal is the seat's default role, identity data passed to the gate. |
| `mcp_repo_target` | LAW-DEBT | f9d9a58f | A key-to-repo reach table plus the ruling that an MCP `path` is content, not reach. Section 2 says a shim may spell a key, not say what it means; `apply_patch_targets` already ceded this domain to the engine (#844). |
| `command_of` | event-shape | 6c9793ef | Codex delivers the shell command as a string or an argv list under `tool_input.command`; joining the list is spelling, not meaning. |
| `apply_patch_targets` | event-shape | c0c8537c | Codex alone ships edit targets inside a diff body; extracting the `*** Add/Update/Delete File:` lines is translation of that shape. The key domain is the engine's (#830). |
| `_tally_scope` | wiring | 333fb80c | One call into the mechanism's scope tally with this seat's paths and id; accounting that never changes a decision. |
| `_attempted_summary` | LAW-DEBT | 523c49c9 | A second implementation of what a refusal record may say (credential key list, masking, 400-char bound); claude and kimi carry the same law (#844). |
| `_gate_self_call` | wiring | 0ace81a3 | One call into the mechanism's gate-self exchange with plugin id and role; None on failure feeds the refusal the caller renders. |
| `_witness_gate_self` | wiring | fc41d5d2 | One call into the shared witness with identity, gate path and session id. |
| `_claim_self_write` | LAW-DEBT | 3ea6a3ae | The call is thin; the except branch mints an `unreachable` verdict and its wording locally: denial content and posture authored in the shim (#844). |
| `witness_decision` | LAW-DEBT | 71ef7375 | Holds the local refusal record's schema, redaction rule and cause inference, and imports `record_gate_unavailable` from the checkout path the installed-only loader forbids (#844, #742). |
| `deny` | LAW-DEBT | 8ce642f1 | Exit 2 plus stderr is codex's channel. The `MODE` to deny-or-warn arbitration and the framing sentence around the core's remedy are posture and refusal content (#844). |
| `_fail_closed_internal_error` | LAW-DEBT | 18483b85 | Codex reads a raised hook as allow, which justifies a handler that exits 2; the mode-keyed deny-or-warn choice and both authored sentences are posture and content (#844). |
| `main` | LAW-DEBT | bd41493c | Channel, event shape and identity form the spine. Inline: the `_CLOSURE_FLOOR` substring match, `"Write"` asserted for patch targets, read-class gating of the governor, degraded posture selection, an `AgentPolicy` scope literal, and every deny and escalation sentence (#741, #844). |

Outside the rows (#844): `WORKSPACE` fixed at import; `CODEX_HOME` (a standing grant as a constant, and dead); `_CLOSURE_FLOOR` (the closure list duplicated locally with its own matching rule); `READ_CLASS` empty-set fallback; `MODE` default and its rollout doctrine; `SCOPE_ATTEST_EVERY`; the import guards that arm the floor on failure.

## kimi

`plugins/kimi/hooks/pre_tool_use.py`

| function | class | src | justification |
|---|---|---|---|
| `_detect_workspace` | LAW-DEBT | 26d7dddd | Same bytes as codex: the scope root, an 8-level marker walk and a cwd default, decided in the shim (#760, #839). |
| `command_of` | event-shape | ced21a16 | Kimi spells the shell command under `tool_input.command` as a string; one field read. |
| `_role_bridge` | identity | d6955727 | One call into the mechanism's role bridge with this seat's identity path; the except-branch literal is the seat's default role. |
| `path_in_scope` | wiring | e451487d | One-return delegation to the core's predicate, supplying the workspace and profile; no local predicate survives. |
| `command_in_scope` | wiring | 14833812 | One-return delegation to the core's hardened command predicate. |
| `_tally_scope` | wiring | 1d4567f4 | One call into the mechanism's scope tally; accounting that never changes a decision. |
| `_attempted_summary` | LAW-DEBT | 7a356487 | The third copy of what a refusal record may say (redaction keys, masking, truncation); witness content, not a kimi peculiarity (#844). |
| `_record_refusal` | wiring | 58b9725b | One call into the unified refusal recorder. Its per-call `sys.path` insert is the loader dialect #801 retires; the recorder call itself is the seam. |
| `deny` | LAW-DEBT | 3ead49ff | Exit 2 plus stderr is kimi's channel; the warn-versus-enforce arbitration and the wrapper sentence around the core's remedy are posture and content (#844). |
| `_fallback_touches_self` | LAW-DEBT | 9b14982e | A 59-line second implementation of the gate-self closure, matching raw text against local marker tuples; the shared classifier owns it (#741, #370). |
| `_gate_self_call` | wiring | 7610618f | One call into the mechanism's gate-self exchange with plugin id, role and client name. |
| `_witness_gate_self` | wiring | 15613c91 | One call into the shared witness with this gate's path and session id. |
| `_claim_self_write` | LAW-DEBT | 2ec39706 | Thin on the happy path; the except branch mints the `unreachable` refusal verdict and its wording in the shim (#844). |
| `_fail_closed_internal_error` | LAW-DEBT | be50a408 | Kimi reads a raised hook as allow, so a handler that exits 2 is channel; the mode-keyed posture and both sentences are law (#844). |
| `main` | LAW-DEBT | bdd8532b | Spine is channel and event shape. Inline: read-class gating, the closure authority choice, the read-allowed and write-escalates dispositions with their prose, degraded posture and its read carve-out, a warn-mode `AgentPolicy` literal, and a working-tree `sys.path` insert for the mechanism (#741, #801, #844). |

Outside the rows (#844): the working-tree loader fallback at module level and the unconditional working-tree insert in `main` (#801); `WORKSPACE` at import; `READ_CLASS` empty-set fallback; `MODE` default; `SCOPE_ATTEST_EVERY`; `_SELF_DIR_MARKERS`, `_SELF_GOVERNANCE_FILES`, `_SELF_HOOKS_DIR_ONLY` (the closure as data); the import guards that degrade to the local classifier.

## gemini

`plugins/gemini/hooks/before_tool.py`

| function | class | src | justification |
|---|---|---|---|
| `_shared_runtime_dir` | wiring | 66a8a074 | The installed-only loader's path resolution, byte-identical across seats (#742). |
| `_load_shared_module` | wiring | 38815f39 | The installed-only loader, byte-identical across seats (#742); load integrity, not a verdict. |
| `load_in_scope` | LAW-DEBT | ee182a69 | Returns `[]` to rule that `identity.json` confers no standing grant. A grant-source decision belongs to the gate as a declared parameter (#844). |
| `_launch_grant` | wiring | 2dcd917c | One call into the engine's launch-cwd grant rule; the engine-absent `[]` is reached only in warn mode since #830 made an absent engine an anomaly deny. |
| `command_of` | event-shape | bbea56af | Gemini's `run_shell_command` passes the command under `tool_input.command` as a string or list; joining is spelling. |
| `_strings` | event-shape | 70edd3f5 | Walks string leaves of MCP argument objects whose shape belongs to the server; it selects nothing by meaning. The depth-4 cutoff is a coverage limit a reviewer should see. |
| `egress_targets` | LAW-DEBT | 5fb1a237 | Spelling `url`/`urls`/`prompt`/`query` is translation; ruling that those keys are egress swept by Gate-1a and never containment-checked is a scope predicate (#844). |
| `mcp_strings` | LAW-DEBT | 69b82ca9 | Assigns `mcp_context.cwd` to command scope and `url` away from it: scope-domain classification wearing a field list (#844). |
| `mcp_egress` | LAW-DEBT | 4fd5b2b5 | Declares the MCP url an egress-class target exempt from command scope; what counts as egress is gate law (#844). |
| `dedupe` | LAW-DEBT | 822c7003 | Mechanical, but its only reason to exist is the local composition of the scope list in `_gate`, which is itself debt; it goes with that composition (#844). |
| `to_claude_lineage` | LAW-DEBT | f4f5839f | Renaming gemini fields to Claude-lineage names is translation, but section 2 says the `(tool, key)` mapping is the gate's data, and the regex lift of a url out of `prompt` manufactures a reach the harness did not name (#844). |
| `_scope_path` | wiring | cc4143c3 | One-return delegation to the core's path predicate; the engine-absent `False` is reachable only in warn mode. |
| `_scope_command` | wiring | 0ede4a8b | One-return delegation to the core's command predicate; it drops the offending token, which the reviewer of the deny text should know. |
| `_emit_verdict` | refusal-channel | d132766b | Gemini's verdict channel is stdout JSON at exit 0; this writes the decision object as the only bytes on fd 1 with short-write hardening. |
| `deny` | LAW-DEBT | 11ed889c | The exit-0-plus-stdout mechanism is channel; the innate-or-enforce posture branch and the composed refusal prose are law (#844). |
| `anomaly` | refusal-channel | 276ef153 | Exit 2 with stderr text is how this hook engine is told no on the corruption-safe path; callers choose when. |
| `_gate` | LAW-DEBT | 86b4765e | The per-call pipeline: read-vs-write classification inline, scope composition, the innate sweep, Gate-1b arm selection, a 6s governor timeout, verdict triage and every posture branch (#741, #760, #844). |
| `main` | refusal-channel | 4a1d6ee4 | Exists because gemini reads an uncaught exit 1 as allow, confirmed by repro; turning a crash into exit 2 is this engine's channel. The one deny sentence it carries is content a reviewer should see. |

Outside the rows (#844): the repo-relative `../../lib` `sys.path` insert the installed-only loader forbids; `_shared_check_paths` and `_core` import guards that degrade rather than deny; `WORKSPACE` from cwd; `FORBIDDEN` and `HESTIA_FORBIDDEN_EXTRA` (the seat's own secret denylist); `READ_CLASS` and `EGRESS_CLASS` (read-vs-write and egress classification as module data); `GEMINI_HOME` as an always-in-scope root; `LINEAGE_TOOL`/`LINEAGE_ARG` tables; `MODE` default.
