# `decide()` — reconciliation matrix

**Step 0 of `PRD_SHIM_CERTIFICATION.md` §6.** Working document, 2026-09-04 (cbp-claude),
opened at GPT's direction: build the behaviour matrix before writing the orchestrator, and
let no seat be normative.

> we thought we had one gate with four shims.
> we actually had four gates sharing a utility library. — *chatgpt-gpt5.6-sol*

## Method, and why no seat is the baseline

Codex's `main` is the longest at 279 lines. **Length is evidence, not authority.** Taking
it as the baseline would silently promote one seat's accidents into fleet law, so every
branch below is adjudicated on its own attribution:

- **survives** — the branch encodes a real requirement; `decide()` must reproduce it.
- **generalized** — the requirement is real but the seat's expression of it is local;
  `decide()` implements the general form.
- **dropped** — the branch is an artifact of its seat and nothing is lost.
- **UNATTRIBUTED** — nobody can say what incident or law produced it. This is a finding in
  its own right, not a default-survives.

Nothing here is decided yet. Attribution and adjudication columns marked `?` are the work.

## Measured starting position

| seat | entry | lines | `if` | `try` | where the logic lives |
|---|---|---|---|---|---|
| claude-code | `main` | 193 | 12 | 3 | in `main` |
| codex | `main` | 279 | 25 | 5 | in `main` |
| kimi | `main` | 234 | 18 | 4 | in `main` |
| gemini | `main` → `_gate` | 22 → 110 | 0 → 15 | 1 | in `_gate` |

Gemini's short `main` is structure, not simplicity: `_gate` carries 110 lines and 15
branches. Counting `main` alone would have mis-ranked it, which is the same error as
ranking codex first by length.

## The spine that already exists in three seats

Extracted call order, deduplicated. This sequence appears in claude-code, codex and kimi
and is the skeleton `decide()` should own:

```
path_targets -> NormalizedEvent -> fetch_policy_snapshot -> resolve_agent_policy
             -> evaluate -> degraded_verdict
```

Gemini runs **none** of it (see stage 5).

## Stage matrix

Stages per GPT's proposed pipeline. `decide()` is one public call over these; they stay
individually testable so C7a/C7b can be proven per stage rather than asserted.

### 1. normalize — harness event → `NormalizedEvent`

| seat | how | adjudication |
|---|---|---|
| claude-code | `read` → `loads` → `path_targets` → `NormalizedEvent` | **survives** — becomes the `to_event` adapter |
| codex | `loads` → `command_of` → `path_targets` → `mcp_repo_target` → `apply_patch_targets` → `NormalizedEvent` | **generalized** — `apply_patch_targets` is codex's `apply_patch` verb; the general form is "harness-specific write verbs contribute targets" |
| kimi | `loads` → `command_of` → `path_targets` → `NormalizedEvent` | **survives** |
| gemini | `to_claude_lineage` (37L, 7 branches) → `command_of` → `egress_targets` → `mcp_strings` → `mcp_egress` → `dedupe` | **generalized** — gemini converts to Claude-lineage shape *then* proceeds. That conversion is exactly the `to_event` adapter and belongs in the shim; `egress_targets`/`mcp_egress` are extraction and belong in shared normalization |

**Finding.** All four already agree that normalization is separable — every one of them
does it first and does nothing else until it is done. This stage is the least contentious
and should be built first.

### 2. establish identity / context

| seat | how | adjudication |
|---|---|---|
| claude-code | `HarnessProfile` → `detect_workspace` **in `main`** | **generalized** — profile construction survives; calling `detect_workspace` from `main` does not. It belongs inside `decide()` |
| codex | `HarnessProfile`, private `_detect_workspace` | **dropped** (the private copy) — C2 |
| kimi | `HarnessProfile`, private `_detect_workspace`, `_role_bridge` | **dropped** (the private copy) — C2 |
| gemini | `_launch_grant` → `launch_cwd_repo`, `load_in_scope` | **generalized** — launch-cwd granting is a real requirement (#647: fail-closed MRH bricks sessions launched in per-fire worktrees). The general form goes in `decide()`; `load_in_scope` is profile data |

### 3. classify act

| seat | how | adjudication |
|---|---|---|
| claude-code | `_closure_classify` **plus** private `_is_read_only` (`hestia_shell_classifier`) | **generalized, and this is the big one.** The closure call survives. The private read/write classifier must move into shared — it is where FP12/13/14 live, and it is why 4 of 8 parity cases diverge |
| codex | `_closure_classify` | **survives** |
| kimi | `_closure_classify` | **survives** |
| gemini | *none* | **finding** — gemini performs no closure classification at all (`_closure_classify` count: 0) |

**The C8 divergence is entirely in this stage.** Unifying it is what makes the parity test
go green, and it cannot be done by moving functions alone: the shared closure and the
claude-only classifier *disagree* (`for`/`if` reads: claude read, closure write; `awk` and
`$( )`: claude write, closure read). One of them has to win per case, and each case is a
separate adjudication with a corpus row behind it.

### 4. resolve scope

| seat | how | adjudication |
|---|---|---|
| claude-code | via `evaluate` | **survives** |
| codex | via `evaluate`, plus `_tally_scope` accounting | **survives**; tally is stage 9 |
| kimi | via `evaluate`, plus `_tally_scope` | **survives** |
| gemini | `_scope_path`/`_scope_command` → `path_in_scope`/`command_in_scope` **directly** | **generalized** — same shared primitives, called around `evaluate` rather than through it |

### 5. select applicable law + evaluate

| seat | how | adjudication |
|---|---|---|
| claude-code | `fetch_policy_snapshot` → `resolve_agent_policy` → `evaluate` → `ask_daemon` → `deny_no_verdict` | **survives** |
| codex | `fetch_policy_snapshot` → `resolve_agent_policy` → `evaluate` → `AgentPolicy` | **survives** |
| kimi | same, plus `query_society_safety` in `main` | **survives**; society-safety is a stage, not a seat feature |
| gemini | **none of it** | **finding, and the most serious in this document** |

**Gemini does not run the policy path.** No `fetch_policy_snapshot`, no
`resolve_agent_policy`, no `evaluate`, no `degraded_verdict`, no closure. It performs scope
and egress checks and stops. Consistent with #730 (CLOSED — "gemini's gate does not refuse
on an unreachable daemon where codex and kimi do — one law, three behaviours"), which the
symbol counts now explain: there is no daemon path in gemini to be unreachable.

This is why gemini onboarding is a governance question and not a config question.

### 6. escalation / authority

| seat | how | adjudication |
|---|---|---|
| claude-code | `request_self_write` → `deny_self_access`, `_witness_self_read`, `_fallback_self_protection` | **survives** — the fallback is the fail-safe literal from `hestia_gate_core.py:167-173`; it must survive in some form |
| codex | `_witness_gate_self` → `_claim_self_write` | **survives**, as shared calls |
| kimi | `_witness_gate_self` → `_claim_self_write`, `_fallback_touches_self` | **survives** |
| gemini | *none* | **finding** — no gate-self path |

### 7. construct verdict + 8. witness / record

| seat | how | adjudication |
|---|---|---|
| claude-code | `emit_decision`, `_attempted_summary` (56L), `cache_action` | **generalized** — one renderer (C6) |
| codex | `witness_decision_unified` direct, `_extract_target`, `_attempted_summary` (39L) | **generalized** |
| kimi | `_record_refusal` wrapper, `_attempted_summary` (36L) | **generalized** |
| gemini | `_emit_verdict` → `deny`/`anomaly` | **generalized** |

Three renderings of the attempted act; `rule_triggered` is `None` on all 1727
`policy_decision` rows across all seats (#156). C6 collapses this to one.

### 9. failure posture

| seat | how | adjudication |
|---|---|---|
| claude-code | 3 `try`, no `MODE` | **?** — see C5 |
| codex | 5 `try`, `_fail_closed_internal_error` (39L), `MODE` at ~10 sites | **?** |
| kimi | 4 `try`, `_fail_closed_internal_error` (28L), `MODE` at ~10 sites | **?** |
| gemini | 1 `try`, `anomaly` | **?** |

**Deliberately unadjudicated.** C5 requires that either every seat honours a warn/enforce
mode or none does, and that decision is not mine to make in a matrix — it changes what a
refusal *is* on two seats. It needs an explicit ruling, and it is the one item here I would
put in front of dp rather than resolve in review.

## Open questions for ratification

1. **C5 / `MODE`.** Fleet-wide warn/enforce, or nowhere? Today codex and kimi can downgrade
   a non-innate deny to a warn via an environment variable; claude-code cannot. Note that
   an env-selectable mode is C1b's problem in another costume.
2. **Stage 3 case-by-case.** Each of the 4 divergent parity cases needs a ruling on which
   classifier is correct. FP16 (`case`/`esac`) looks safe to fix in the closure's favour;
   FP17 (`$( )` wrapping a read) is the hard one and the highest-volume.
3. **Gemini's missing stages 3, 5, 6.** Bring gemini up to the pipeline before onboarding,
   or onboard it explicitly as a lower-assurance seat with that recorded? The second is
   defensible under web4's "inspectable evidence, not prescribed trust" — but it must be a
   decision, not an accident.
4. **UNATTRIBUTED branches.** 25 `if`s in codex's `main`, 18 in kimi's, 15 in gemini's
   `_gate`. The per-branch attribution pass is the remaining bulk of step 0 and is not done
   in this revision.

## Accountability self-audit

```
surface: docs/DECIDE_RECONCILIATION_MATRIX.md
act:     none — analysis document, no runtime path, no code changed
S:       n/a [construct: document only; no caller can drive it]
R: n/a   W: n/a   O: n/a   A: n/a   V: n/a
verdict: PASS (no surface created)
```

The `decide()` implementation this matrix feeds is high-stakes and irreversible-in-effect,
and its PR carries a full RWOA+S+V block with V mandatory, per `PRD_SHIM_CERTIFICATION.md`
§7. No deployed shim is modified by this document or by step 0.
