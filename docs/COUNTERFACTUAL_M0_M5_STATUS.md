# Counterfactual governance query — M0–M5 implementation status

Audit baseline: main `93b8dd458789ec0839dea1bc700ddb3cd1656744` (2026-11-22).

This is an implementation audit, not a conformance claim, an intent classifier, or a curiosity score. The PRD remains the semantic authority: [PRD_COUNTERFACTUAL_GOVERNANCE_QUERY](PRD_COUNTERFACTUAL_GOVERNANCE_QUERY.md).

## Executive finding

No `hestia_query_counterfactual` surface exists. `hestia_query_policy` and `hestia policy test` are not that surface:

- `tool_query_policy` in `core/src/server/handler.rs` requires an in-flight `action_id` and can append live chain entries (for a non-allow decision, and for a probe it could not evaluate; an evaluated allow appends nothing), so it is not a hypothetical, side-effect-free query.
- `cmd_policy_test` in `core/src/cli.rs` opens the operator vault directly and evaluates only the preset/destructive-rule family. It cannot evaluate scope or governance-closure decisions, and it is not a member-facing query.
- Pure evaluators exist in `evaluate` and `command_scope_reach` (`plugins/_shared/hestia_gate_core.py`) and `classify` (`plugins/_shared/hestia_governance_closure.py`). Calling them from a checkout supplies caller-asserted profiles, grants, and engine bytes. It does not supply an authoritative deployed context, and it does not create the PRD's typed response or side-effect guarantees.

## Milestone matrix

| Milestone | Status | Current evidence | Missing acceptance |
|---|---|---|---|
| **M0 — semantic fixtures** | **PARTIAL** | `plugins/_shared/test_gate_core.py` exercises allow, `mrh.path`/`mrh.command`, scope/grant edge cases, and unavailable/unknown cases. `plugins/_shared/seat_gate_boundary_test.py` covers self-law refusal, ordinary allow, degraded/unavailable, missing/poisoned engine, internal error, and missing timeout/projection. `plugins/_shared/hestia_governance_closure_test.py` covers closure and opaque-writer classes. | No fixture set describes the expected **hypothetical** response schema, no-mutator contract, temporal drift, or live/hypothetical pairing. The table below freezes those required cases, not an implementation. |
| **M1 — pure counterfactual evaluator** | **PARTIAL** | [#1713](https://github.com/dp-web4/hestia/pull/1713) adds `hestia_gate_evaluate`, a session-resolved, read-only AuthZEN-shaped society-law evaluation. Its separate `society_law_allows` result can be true while local MRH, closure, or egress is unevaluated; fail-closed `decision` and `permits` remain false, so the society result is not a permit. This is not full M1: local stages are not evaluated and the response is not the PRD's complete typed counterfactual result. | Full live-gate parity, the complete `would_allow`/`would_refuse`/`unavailable`/`unknown` response with feedback and policy/authority references, and proof that grants, scope, reputation, escalation, live witness, execution, and trust projection do not change. |
| **M2 — feedback parity** | **PARTIAL** | Live `VerdictFeedback` and rule/remedy text exist. Gate fixtures assert several refusal rules and remedies. | Matched hypothetical/live decisions, feedback subjects, and next-door semantics under unchanged and drifting policy/authority state. |
| **M3 — evidence separation** | **MISSING** | There is no `event_class = counterfactual_query` and no hypothetical-only traffic class. | Ordinary allow/deny statistics and trust projections are byte-for-byte unchanged after arbitrary hypothetical-only traffic. No query record may become reusable authority. |
| **M4 — SAGE integration** | **MISSING** | No SAGE exploration episode queries alternatives and then independently re-adjudicates the selected live act. | One episode with mutually exclusive hypothetical acts, one independently authorized live act, and provenance linking the two without conflating them. |
| **M5 — legibility experiment** | **MISSING** | No blind-live-attempt versus hypothetical-planning comparison exists. | Matched tasks measuring valid inquiry, avoidable denials, repeat loops, outcomes, and risk, including null outcomes. |

## Frozen semantic fixture inventory for M1/M2

These are expected **test cases**, not claims that a query currently returns them.

| Case | Expected decision family | Required no-side-effect assertion |
|---|---|---|
| Ordinary allowed act | `would_allow` | No grant is minted, no act executes, and a later live act is re-adjudicated. |
| Society law allows while local MRH/closure/egress is unevaluated | `unknown` with the incomplete stage named, never `would_allow` from the society result alone | A #1713-style partial response keeps `decision` and `permits` false; no grant is minted and no act executes. |
| Society law allows but a local stage denies | `would_refuse` with the local rule, never `would_allow` from the society result alone | No grant is minted, no act executes, and the society-only result cannot override local policy. |
| Ordinary policy refusal | `would_refuse` with rule and lawful next doors | No appeal/escalation opens and no door executes merely because it was named. |
| Scope refusal | `would_refuse` with `mrh.path` or `mrh.command` | No scope request opens and no scope/reputation changes occur. |
| Self-law/closure refusal | `would_refuse` with the closure rule and law-change path | No governed file changes and no gate-self approval opens. |
| Invariant/secret refusal | `would_refuse` with no bypass door | Protected facts are normalized/redacted; no enumeration oracle or egress occurs. |
| Daemon/transport unavailable | `unavailable`, never `would_allow` or `would_refuse` | No local fallback silently widens authority and no outage is charged as member conduct. |
| Missing engine/projection | `unavailable` | No guessed law, grant, or home is invented. |
| Insufficient/uncertain facts | `unknown` with the missing fact named where safe | No expansion, target-home, role, or unenumerated value is guessed. |
| Policy or authority drift between query and live act | Fresh live adjudication, never replayed authority | Response names the evaluated policy/authority snapshot and time; no future state is reserved. |
| Hypothetical-only traffic burst | No semantic decision mutation | Live decision counts, trust, scope, escalation, and execution stores remain byte-for-byte unchanged. |

## Implementation guidance that follows from the audit

1. Reuse live normalization and evaluation behind one side-effect-free call. Do not create a second advice engine or overload `tool_query_policy`.
2. Derive the evaluated actor, role, policy, scope, and engine from authoritative state, not caller-supplied profile files. Return those references with the response.
3. Keep `would_allow` free of reservation semantics, `unavailable` distinct from refusal, and `unknown` distinct from infrastructure failure.
4. Add the no-mutator tests before any public query registration. A hypothetical allow must never become spendable authority.
5. Run the M2 parity harness before SAGE integration or an M5 experiment. Null results and negative controls are evidence, not defects to hide.

## Current acceptance boundary

No production counterfactual API, daemon surface, SAGE episode, or legibility result is claimed by this audit PR. The #1713 reference is to another draft, not a claim that its surface has merged or deployed. This document supplies the M0–M5 audit and the semantic corpus those implementations must satisfy; it does not close M1–M5.
