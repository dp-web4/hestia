# One gate: the convergence plan (stages A–D)

2026-10-01. Author: cbp-claude (stage A owner), on GPT's current-main finish-line proposal
(#934, comment of 2026-10-01). dp's direction: land one-gate now; build a fresh current-main
stack rather than resurrect the old one.

**Merge criterion (GPT, adopted):** one decision implementation, one decision witness, one
outcome witness, four syntax adapters, zero seat-local law, exact published/resident bytes, and
live decision→outcome joins.

## 0. Why a fresh stack, not #934 / #1139 / #1140

| PR | state | why it is not landed as-is |
|---|---|---|
| #934 `gpt/single-gate-collapse` | draft since 09-06, CONFLICTING | The quarry. Its contract suite never passed: 8 of 12 arms are red on its own engine, because `_record` hand-rolls the MCP client and the fakes patch a name nothing calls. It also carries a `/tmp/hestia-actions` `_cache_action` keyed on `tool_use_id`, which is the claude-only rule (C13), and a `~/.hestia` guess in `_plane_e_path` (#944). Comments 2026-09-22 and 09-28. |
| #1139 `gpt/common-gate-witness-v1` | red, held | Its `witness_decision()` treats any outer RPC `result` as committed. The daemon still refuses `allow` (handler.rs `tool_witness_decision`) and charges every accepted call. Its three new tests are missing from the bare runner, and the shared name `witness_decision` collides with codex's private function, which tripped gate_collapse_meter. GPT's own review of 72a05e9 says the same. |
| #1140 `gpt/common-gate-engine-v1` | red, held | Stacked on #1139. It calls `query_society_safety` without `correlation_key`, so C13 is broken. Its witness mock returns True, so `require_commit=True` can return `evidence_committed=True` with nothing appended. The test file is mode 100644, which ci_selfexec rejects. |

## 1. Already on main

- **Stage 0 / certification:**
  - the criteria PRD (`docs/PRD_SHIM_CERTIFICATION.md`, C1–C13);
  - the template (`plugins/_template/shim_template.py`);
  - the drift tool (#1104);
  - decision reconciliation (#933).
- **One outcome witness (#1149):**
  - `plugins/_shared/hestia_witness_core.py` provides `correlation_key(event)`, a single Pre/Post key rule: `tool_use_id`, then `tool_call_id`, then a gemini content key built from `source_event`;
  - receipt-validated `witness_one`, where "recorded" requires a `witnessEntryHash`;
  - byte-identical per-seat `hooks/witness.py` shims;
  - `query_society_safety(..., correlation_key=)` writes the gate half of the cache.
- **Gauges and publication:**
  - `tools/witness_closure_census.py` is the C13 acceptance gauge;
  - hooks-gt (`tools/hooks_gt.py`, #1160/#1161) publishes and stores the hook trees;
  - per-gate ratification (#1150/#1159).
- **Still open on main:** witness-path parity (criterion 11, PRD_GATE_CONSOLIDATION §13.2/§14) and allow-side recording. `witness_decision_unified` is deny/warn-only, and the daemon refuses `allow`.

## 2. Stage A: one receipt-validated decision witness (this PR)

Additive and unwired: no seat calls the new recorder, and deployed refusal calls behave exactly
as before.

### What was wrong on main (file:line at d95d6b4)

1. **Refusals counted as delivered.**
   - Every tool error reaches the wire as a successful MCP `result` carrying `_hestia_error`. This covers a refused verdict and a failed chain append alike (handler.rs:131 `call_tool`: `dispatch.unwrap_or_else` → `CallToolResult::success`).
   - `witness_decision_unified` checks only `"result" in out` (hestia_gate_mechanism.py:619), so it reports both as delivered.
   - `tools/decision_witness_contract_test.py::test_a_failed_append_is_not_committed` pins this.
2. **Allow had no door.** `tool_witness_decision` refuses anything except deny/warn (handler.rs:3928-3936). It also charges a negative outcome for every accepted call.
3. **A naive allow row would distort scores.**
   - `policy_decision` is in `DERIVATION_GOVERNANCE_EVENT_TYPES`, the sparse half of the derivation window that "must not be crowded out" (derivation.rs:277-286). Allow volume is outcome volume.
   - Readers that take every `policy_decision` as a refusal:
     - `governed_acts`, which weights conduct against volume (derivation.rs:1110-1114);
     - the retry match (derivation.rs:695-704);
     - the sibling-role count (derivation.rs:1030-1040);
     - calib_export gate mode, which labels every decision 0 (calib_export.rs:278).
   - Writing allows there would move trust levels and push real denies out of the window. That is why #1139's "accept allow" could not simply be switched on.
4. **One refusal, two rows, two charges.**
   - The daemon's own `query_policy` witnesses and charges its warn/deny with `action_id` (handler.rs:1572-1655, Conduct 0.2/0.5).
   - Codex then records the same society deny again through the hook recorder (codex pre_tool_use.py:880-909): a second row with no `action_id`, and a second Unclassified charge.
5. **query_policy discarded its own write.** It threw away the result of its own `policy_decision` append (`let _ = s.append_chain(...)`, handler.rs:1578), so a verdict could be returned with no committed row behind it.
6. **`core_digest` was dropped.** The hooks have sent it since REPAIR 5 (hestia_gate_mechanism.py:610-617), but the daemon never stored it.

### The contract

**Daemon (`hestia_witness_decision`, core/src/server/decision_witness.rs + handler.rs)**

| verdict | chain event | reputation | notes |
|---|---|---|---|
| `allow` | `policy_allow` (new, reserved) | none | Same reason the daemon's own gate charges nothing on allow, and scope attestation's "farm trust" argument. |
| `warn` | `policy_decision` | Unclassified 0.2 | Unchanged. |
| `deny` | `policy_decision` | Unclassified 0.5 | Unchanged. |
| anything else | nothing appended | none | `_hestia_error hestia.witness_decision_kind` |

- **Join keys.** `action_id` (a UUID from `begin_action`) and `correlation_key` (the core's rule; `valid_correlation_key`) are optional. A key that is sent but unusable is refused with `hestia.witness_decision_arg`, never dropped.
- **Row fields.** When sent, the keys ride the row as `action_id`, `action_resident` and `correlation_key`. `core_digest` is stored bounded to 128 chars. A deployed refusal call sends none of these and writes the row it always wrote.
- **One verdict, one row.**
  - `query_policy` now keeps the hash of its own committed row on the in-flight action. It also returns it as `decisionEntryHash`, which is null for allow or when the append failed.
  - A decision witness for the same action, member and verdict is answered with that row: `recorded: "existing"`, `charged: false`, nothing appended.
  - A different verdict (a warn-rollout `warn` for a daemon `deny`) or a different member gets its own row.
- **Receipt.**
  ```
  {witnessEntryHash, eventType, decision, recorded: appended|existing, charged,
   actionId, correlationKey, updatedTrust}
  ```

**Client (`hestia_gate_mechanism.record_decision`)**

- **Signature.** `record_decision(client_or_none, *, plugin_id, decision, rule, tool_name, target, session_id, verdict_available, attempted_summary, action_id=None, correlation_key=None, deadline=None) -> DecisionReceipt`.
- **Status.** `DecisionReceipt.status` is one of `committed`, `refused`, `ambiguous` or `unreachable`. Only `committed` is evidence.
- **Reply classification.** The reply is classified by the outcome witness's own `_classify_reply` (ok / ruled / ambiguous), so the two halves of the join can never disagree about what the daemon said.
- **What counts as committed.** All of the following must hold:
  - `witnessEntryHash` is a chain hash (64 lowercase hex);
  - `decision` echoes the verdict sent;
  - `eventType` is the verdict's event;
  - `actionId` and `correlationKey` echo whatever was sent.
- **Older daemons fail closed.** A daemon from before this PR cannot produce that receipt, so it reads as not committed.
- **Deadline.** `deadline` is absolute (`time.monotonic()`). No request starts after it, and the helper mints no time of its own, so stage B's single invocation deadline passes straight through.
- **Fallback.** An uncommitted record is kept in `$HESTIA_HOME/telemetry/gate-decisions-<member>.jsonl` only under an explicit `HESTIA_HOME`; it never guesses `~/.hestia`. It is never evidence.
- **Never raises, never decides.** The function never raises and never changes a verdict. What to do with an uncommitted permit is stage B's decision.
- **Name.** `record_decision`, not `witness_decision`, so it cannot collide with codex's private function.

### Contract tests

- **Rust:** 6 unit tests in `decision_witness.rs`, plus 8 tests in `handler.rs::decision_witness_tests`:
  - allow is its own event and charges nothing;
  - the deployed refusal row is unchanged;
  - unknown verdicts are refused before any append;
  - unusable join keys are refused;
  - join keys and core_digest reach the row and the receipt;
  - one verdict gives one row (and a different verdict or member gets its own);
  - an allowed action is joined by its allow row;
  - `policy_allow` cannot be forged through `request_witness`.
- **Python:** `tools/decision_witness_contract_test.py`, 19 tests against a stub daemon in the real wire shape (JSON and SSE framing). It covers:
  - every refusal, error and malformed-receipt class;
  - deadline bounding;
  - the fallback home rule;
  - C13 keys from the raw event;
  - an unwired guard;
  - an isolated real-daemon arm, run in CI's `sdk-conformance` job on :7799. It refuses :7711.

## 3. Stage B: the common orchestrator `decide()` (successor to #1140)

**Shape.** One public contract, harvested from #934/#1140 onto current main:
`GateEvent -> hestia_single_gate.decide(event, profile) -> GateDecision`, additive and unwired
like A. `GateEvent` must carry the **raw harness event** (`raw`), unmodified.

**What `decide()` owns**, as the one law-bearing sequence (#1140's order, with the fixes below):

1. **One absolute deadline.**
   - Taken from `GATE_DEADLINE_SECONDS` (3 s, under the shortest measured harness clamp of 4 s).
   - Passed explicitly as `deadline=` to `record_decision`. Extend the same parameter to `query_society_safety` and `fetch_policy_snapshot` in B, rather than #1140's monkeypatching of `_McpHttp` and the module budgets. That patching is interface debt #1140 itself names.
2. **Correlation key.** `key = mechanism.correlation_key(event.raw)`, computed once from the RAW event (C13). It is never computed from the normalized event, because gemini's `source_event` and kimi's `tool_call_id` do not survive normalization (pinned in A's `test_the_correlation_key_is_the_cores_rule_from_the_raw_event`).
3. **Governance closure.**
   - `closure.classify`: a read is witnessed through `witness_gate_self`.
   - A write needs `claim_self_write(..., invocation_key=key)`.
   - Anything unclaimed is denied `gate.self_access`.
4. **Egress precheck** (innate) gives `egress.secret`.
5. **Policy snapshot** via `fetch_policy_snapshot`.
   - If it is missing, use `core.degraded_verdict`.
   - Degraded denies are innate when the core says so, and an anomaly otherwise.
   - A degraded read becomes `allow gate.degraded.allow_read` with `verdict_available=False`.
6. **Local law** via `core.evaluate`. A block becomes a deny with its rule.
7. **Read class** gives allow with `require_commit=False` (the ratified degraded-read posture).
8. **Society safety:** `mechanism.query_society_safety(event.raw, ..., correlation_key=key)`.
   - This is the ONLY writer of the action cache (C13 rule 2). The orchestrator carries **no cache of its own**: no `_cache_action` and no `/tmp/hestia-actions`.
   - A superseded verdict is a hard deny in every mode.
   - Not decided means `society.unreachable` (anomaly, `verdict_available=False`).
   - A decided refusal is a deny with `action_id`.
   - Allow or warn is a permit with `require_commit=True`.
9. **Finalize.** `_finalize` calls `mechanism.record_decision(..., action_id=verdict.action_id, correlation_key=key, deadline=deadline)` for EVERY final verdict, and nothing else records it.
   - **C11:** a write/exec allow/warn whose receipt is not `committed` becomes `deny gate.evidence_uncommitted`. That deny is recorded through the same call, and the result names the superseded verdict.
   - A daemon-ruled warn/deny is answered `deduplicated` with the daemon's own row, so the census sees one row per verdict.
   - Reads that fail to commit stay allowed, surface `evidence_committed=False`, and are flagged as an anomaly.
10. **Tally** via `tally_scope`, unchanged.

**B's acceptance (contract suite in the repo's real runners):**
- run the real `record_decision` against a refusing stub, requiring `gate.evidence_uncommitted` for a consequential permit (GPT's #1140 HOLD);
- show that `key` from a raw kimi/gemini event reaches both `begin_action` and `record_decision`;
- show that no symbol in `hestia_single_gate.py` writes an action cache or opens an MCP client;
- avoid `globals()` sweeps and set the exec bit, so ci_selfexec and gate_collapse_meter stay green;
- `hestia_single_gate.py` is not in `RUNTIME_MANIFEST.txt` until C.

### Stage B as built (2026-10-01): where it departs from the design above

Contract suite: `tools/one_gate_decide_contract_test.py`. It runs 12 in-process contract tests, plus a parity matrix that drives every seat's CURRENT gate and `decide()` with the same four real harness event shapes under the same stub policy. Every verdict-class divergence is declared there with its reason, and the test fails on an undeclared divergence and on a stale declaration.

1. **The daemon is asked about the translated act; the key still comes from the raw event (step 8).** `query_society_safety` receives `{"tool_name": event.tool, "tool_input": event.tool_input}`, not `event.raw`. The daemon's target extraction and presets speak lineage names. A raw gemini `run_shell_command` reaches it with `target=None`, which is the "blind governor" gemini's own shim was written to prevent. The correlation key is unchanged: `correlation_key(event.raw)`, computed once and passed explicitly (C13 holds).
2. **The deadline is coarse in B; stage C makes it exact (step 1).** B does not modify `hestia_gate_mechanism.py`: dp ruled 2026-10-01 that B must stay approvable at the single-approver bar, and the mechanism carries the sovereign bar.
   - So `query_society_safety`, `fetch_policy_snapshot` and the gate-self calls keep their own budgets.
   - `decide()` bounds each of them from outside (`_bounded`): it runs the call in a daemon thread, waits only for what the invocation has left, and reads a late call as a no-verdict.
   - The harness sees the 3 s bound. The daemon may still receive an abandoned request late.
   - `record_decision` already takes `deadline=` (stage A), so the record is exact.
3. **gemini asks the daemon as gemini.** Today gemini's Gate 2 spawns claude-code's gate, which hardcodes `PLUGIN_ID="claude-code"`. So every gemini society verdict is attributed to claude-code and is also judged by claude-code's scope and home markers. `decide()` asks as the profile's member. The parity suite pins both halves.
4. **C11 holds in warn-rollout.** C11 admits no exempt class, so an uncommitted consequential permit is `gate.evidence_uncommitted` in every mode. With the daemon down, a warn-rollout seat that used to let a write through unwitnessed now denies it. **Behaviour change for dp.**
5. **Degraded reads on claude-code are a LOOSENING that needs dp's ruling.** claude-code asks the daemon about every tool, reads included. So a degraded Read is a no-verdict deny there today, and daemon law can deny a read. `decide()` takes the ratified posture every other seat already has: READ_CLASS is allowed locally and recorded with `verdict_available=false`.
6. **A daemon `warn` is surfaced on every seat.** kimi and codex read only `verdict.allow`, and gemini reads only its governor's exit code. So a daemon warn reached those members as a silent allow. The act is permitted either way.
7. **gemini gains the closure layer.** This resolves #1195's one divergent row: the settings write was denied by gemini's scope layer, and is now denied as `gate.self_access`, which is escalatable.
8. **hooks-gt is unchanged by B.** `hooks_gt.py` publishes `RUNTIME_MANIFEST.txt`, and the new module is outside it until C. So B's republish is a no-op, by design.

## 4. Stage C: thin-shim cutover and certification (separate PR)

0. **Items carried from B.**
   - **Thread `deadline=` through the mechanism.** That means `query_society_safety`, `fetch_policy_snapshot` (both attempts and the pause between them), `gate_self_call`, `witness_gate_self` and `claim_self_write`, with a default of `None` meaning today's behaviour. Then no request starts after the invocation deadline, and `_bounded` becomes a belt. This edits `hestia_gate_mechanism.py`, so it goes to dp.
   - **One rollout knob.** `HESTIA_GATE_MODE` is projected per seat from the vault, replacing the four `HESTIA_<SEAT>_GATE_MODE` names.
   - **Template profile keys.** The template's `PERMITTED_PROFILE_KEYS` gains `launch_cwd_env` and `declares_review_door`. kimi, codex and gemini scope by the launch-cwd grant, and three seats hold the review door.
   - **Remedy text.** The remedies `decide()` mints (`invocation.superseded`, `gate.evidence_uncommitted`, `gate.internal_error`) move into the core's REMEDIES table.
   - **gemini MCP transport.** gemini's command-scoping of the MCP transport (`mcp_context.command/args`) is not in B. B checks those strings for egress only, so this is a C10 item.

1. **Shims become the template.** Each seat's `hooks/pre_tool_use.py` (gemini: `before_tool.py`) is replaced by the certified template:
   - five byte-identical common functions;
   - only `to_event`, `emit` and `read_harness_event` differ;
   - gemini's `_string_leaves` is surfaced under C10.
   All four seats move in one PR, never four drifting PRs.
2. **Retire the old recorder path.** `witness_decision_unified` and the per-seat refusal recorders are deleted. Codex's private `witness_decision` and its `observe.jsonl` refusal log go with them.
3. **Runtime manifest.** `hestia_single_gate.py` enters `RUNTIME_MANIFEST.txt`.
4. **Republish and re-certify.** hooks-GT republishes from the exact union head (`tools/hooks_gt.py`), and certification is re-run on those bytes. The guards stay as they are; they are not loosened. The guards are:
   - shim_certification;
   - gate_collapse_meter, with a zero-fork limit;
   - scope_fork_differential;
   - shim_ledger_check;
   - installed_seat_readiness.
5. **Deploy order.**
   - The daemon from A deploys **before** C's hooks reach any seat. A seat running B against an older daemon would correctly fail closed on every consequential permit, because an old receipt is not a stage-A receipt; that would be an outage, not a governance gain.
   - C's PR must name the deployed daemon version it was verified against.

Alternative on record: GPT's proposal folds B and C into one reviewed train. This plan keeps
them separate so B's contract suite is green and reviewed before any seat depends on it.
dp/GPT can merge the two PRs back to back if they prefer the single train.

## 5. Stage D: acceptance census (after deploy)

Deploy the exact merged build, then:

1. **Bytes.** Repo == published == resident: hooks-gt store vs installed seats vs runtime manifest.
2. **Joins.**
   - `tools/witness_closure_census.py --since <deploy> --min-rate R --min-warns N` per member.
   - kimi-code and codex must reach claude-code's warned-act closure rate (1985/1986 baseline), with a thin sample reported as thin.
   - Extend the census to also join `policy_allow.action_id` → `outcome.action_id`. This is the allow-side join stage A makes possible.
3. **One row per verdict.**
   - For warn/deny since deploy, count `policy_decision` rows per `action_id`; anything above 1 is a defect.
   - Charges per refusal in the reputation sink should equal 1.
4. **Parity and liveness.**
   - Per-seat installed readiness, the gate differential, and the Class-T timeout pair audit.
   - A canary act per seat after the wiring change, asserting both decision and outcome rows (§13.3's open half).
5. **Chain-growth cost.**
   - Count `policy_allow` rows per hour per member against `outcome` rows.
   - Report the derivation governance window's reach before and after; `policy_allow` is outside it, so reach should be unchanged.
6. **Docs.** Update PRD_GATE_CONSOLIDATION §13.2/§14 and C11 status from measured results.

Close #934, #1139 and #1140 only after D passes.

## 6. What each stage subsumes (for retiring #934 / #1139 / #1140)

| item | from | subsumed by |
|---|---|---|
| all-verdict witness entry point (`witness_decision`) | #1139 | **A** `record_decision` (renamed to avoid the codex collision) |
| daemon allow support + correct reputation | #1139 review P1 | **A** (`policy_allow`, no charge, de-dup) |
| receipt validation (reject isError / `_hestia_error` / empty / malformed) | #1139 review P1 | **A** |
| daemon-backed acceptance test | #1139 review P1 | **A** real-daemon arm in CI `sdk-conformance` |
| new tests registered in the bare runner | #1139 review P2 | **A** (module-level `TESTS` list, exec bit) |
| generic fallback never guesses HESTIA_HOME | #1139 | **A** `_decision_fallback_path` |
| legacy `gate-denies-*` fallback preserved | #1139 | **A** (`witness_decision_unified` untouched) → removed in **C** |
| `hestia_single_gate.py` orchestrator, `GateEvent`/`GateProfile`/`GateDecision` | #934, #1140 | **B** |
| one absolute deadline | #934 (`453c7d0`), #1140 | **B** (explicit `deadline=`, not monkeypatching) |
| `_finalize` / `require_commit` / `gate.evidence_uncommitted` (C11) | #934, #1140 | **B**, on A's receipt |
| `correlation_key(raw)` into `query_society_safety` | C13 note on #1140 | **B** |
| removal of `_cache_action` / `/tmp/hestia-actions` / private MCP recorder / `_plane_e_path` guess | #934 | **B** (none ported) |
| 12-arm contract suite + 2 pinning arms | #934, #1140 | **B** (rewritten against the real recorder seam, C12b) |
| shim template cutover, four seats | #934 (`8c2ec13`…`8e1a297`) | **C** |
| installer deploys orchestrator; RUNTIME_MANIFEST; certification preimage | #934 | **C** |
| `_emergency_block` Plane-E evidence; `GATE_API_VERSION` check | #934 | **C** (template bootstrap) |
| test migration (31 of 103 bare tests) | #934 status list | **C** |
| CI wiring for certification tests | #934 (`ci.yml`) | **C** |
| #977 identity falsifiers, decision↔outcome join measured | #934 comment 09-06 | **D** census (+ A's `action_id` on allow rows) |

## 7. Open design questions (stage A)

Restated with recommendations in the stage-A PR body.

1. **Volume.** Record every allow, including reads (C11 says yes), or only consequential ones?
2. **Attribution.** Decision rows are caller-attributed (no session check), as before. Bind them to an authenticated session in B, at the cost of a `hestia_connect` per hook?
3. **Warn-rollout divergence.** A seat records `warn` while the daemon ruled `deny`, which gives two rows and two charges. Keep that, or charge only the daemon's verdict?
4. **`verdict_available=false` still charges an Unclassified delta.** Derivation excludes it, but the sink row exists. Stop charging infra no-verdicts?
5. **Deploy order.** Is daemon-before-hooks acceptable as a hard precondition for C?
6. **B/C as two PRs or one train.**
