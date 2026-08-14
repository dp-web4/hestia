# Sprint F — cutover notes (drafts only; nothing written into the hestia repo)

Base: the CURRENT TRAIN TIP at `/tmp/wt-sprinte` (branch `cbp/sprint-e-transport`, carrying
B+C+D+E). All diffs are against base copies taken from that tip (`base/`), applied and
verified in `tree/` (a full copy of the tip's `plugins/`).

## What F does

1. **Authenticated policy path (mechanism, not core).** `fetch_policy_snapshot(plugin_id, …)`
   added to `hestia_gate_mechanism` — one in-process MCP session (same client as the
   society-safety path): connect → `hestia_operating_law(session_id)` →
   `hestia_scope_status(plugin_id)`. Per-process cache (= per-invocation; gate processes are
   short-lived). Returns **None on any transport failure** — that None IS the ratified
   degraded trigger. A **reachable** daemon lacking a surface (older build, test stubs)
   yields a THIN snapshot instead: thin grants nothing extra, and reachable-but-thin is not
   the degraded trigger — society safety still governs writes on that path.
2. **Ratified degraded mode in the core (Tier 1).** `degraded_verdict(event, profile)` added:
   deny-writes-allow-reads keyed on `READ_CLASS`, with the innate egress invariant still
   binding the reads it allows. Registered rule `gate.degraded` + remedy (names no tools).
   Tier-2 shim literal backstop unchanged (the existing `_core is None` deny — a documented
   tightening: no read carve-out when the posture-computer itself won't import).
3. **Cutover: kimi + codex main() call `evaluate()` and render the Verdict.** Local Gate
   1a/1b copies deleted (egress loop, path/command scope loops, codex's whole pre-hardening
   `path_in_scope`/`command_in_scope`/`_all_repos`, both shims' `_agent_scopes` +
   `_launch_scope_bridge`, shim-side `FORBIDDEN`). The snapshot rides the core's seam **as
   built**: `resolve_agent_policy(vault_reader=λ→snapshot)`; the snapshot always carries an
   `in_scope` list, so resolution can never fall through to the local replica on the enforce
   path (criterion 5). Degraded denies render as `deny [degraded]`, are tallied, and are
   recorded via `witness_decision_unified(verdict_available=False)` → the E-built per-shim
   diagnostic log when the daemon (the normal witness) is the unreachable thing. Degraded
   read-allows are recorded on the gate-availability telemetry (`record_gate_unavailable`)
   rather than the deny log — the deny log's readers expect denies; the availability series
   is exactly the "how often could the gate not decide" gauge. KEPT: Gate 1c closure
   protection (B), society-safety Gate 2 (E), the read-class Gate-2 skip, kimi's
   `path_in_scope`/`command_in_scope` **thin delegation adapters** (pure pass-through to the
   core; the Sprint C parity battery pins them by identity).
4. **Order change, deliberate and test-pinned:** Gate 1c now runs BEFORE the policy stage
   (matching the claude adapter), so a governance-surface write with the daemon down is
   still refused **as gate-self** with its escalation, never blurred into the degraded
   class. Pinned by `test_gate_self_write_daemon_down_stays_gate_self` and the existing
   boundary arms.
5. **`mrh.repo` moved into law.** `NormalizedEvent.repos` + a Gate 1b clause in `evaluate()`
   (repo-named MCP calls scoped on the NAME; their repo-relative paths egress-scanned but
   not re-scoped — the 2026-07-26 false-deny class). This deletes codex's last shim-side
   scope decision.

## What resolved vs what stays bridged + RED

**Resolved**
- Role attribution (`_role_bridge`): **partially resolved** — fed from the snapshot's
  daemon-resolved `identity.role` (`hestia_operating_law`) whenever the daemon answers;
  identity.json remains only as the daemon-unreachable fallback for witness attribution.
- Enforce-path replica: **gone.** No code path in enforce mode reads identity.json for
  scope any more (criterion 5). `resolve_agent_policy`'s replica branch remains in the core
  for non-enforce/diagnostic callers, but neither shim reaches it.

**RED — declared open, with the reason (§9: no daemon protocol redesign, so nothing was invented)**

> **R1 RESOLVED + R4/#407 FIXED (2026-08-14, dp: "might as well do the real fix" —
> `cbp/standing-scope-surface`).** The daemon now owns a durable standing-scope store
> (`core/src/server/standing_scope.rs`): vault document `scope`/`standing`, loaded at
> startup, written atomically through the vault's temp-file-and-rename on every operator
> decision, per-grant `expires_at`, witnessed revoke, and a monotonic `generation` moved
> by every mutation. Mutations only via the operator-walled `POST /api/scope/decide
> {standing:true}` promotion + `POST /api/scope/standing/revoke`; no MCP tool (pinned by
> `no_mcp_tool_can_mutate_standing_scope`). `hestia_scope_status` serves
> `standing_grants` + `generation` + `snapshot_expires_at` additively beside
> `live_grants`; `hestia_operating_law` discloses standing grants inside the hashed body
> AND its projection now forwards both grant lists (#407 — R4 below). The mechanism's
> `fetch_policy_snapshot` composes them (repo-root → repo NAME, deeper paths stay
> faithful-but-inert "path:" entries — R2 still stands), and `resolve_agent_policy`
> stamps the daemon-issued `generation`/`expires_at` onto the returned policy, refusing
> a snapshot past its horizon. The certified-replica fields are therefore now ISSUED,
> not just honoured; the remaining gap is signing (issued ≠ authenticated). R3
> (launch-cwd grant surface) remains open; claude-code's recorded `*` grant (see below)
> is now UNBLOCKED but deliberately not made in the same change — a reach-defining grant
> is dp's act, through the new operator surface, not a PR default.

- **R1. Standing repo scope has NO daemon surface.** `in_scope` appears nowhere in
  `core/src/server/*.rs`; the vault the daemon fronts holds presets/roles/lists, not member
  MRH. A live snapshot therefore cannot carry standing repo grants. Consequence (a real
  live-behavior tightening, deploy-gating — dp should rule before install): after F, a
  kimi/codex session's reach = launch-cwd repo + member home + /tmp + live grants, even
  with the daemon up. This is the ratified direction ("absent data grants nothing") but it
  retires the certified-replica standing scope that D still honoured. Remaining step: a
  vault/daemon surface for standing member scope (needs its own PR + operator sign-off; it
  is an *addition*, and §9 kept it out of F).
- **R2. Live path grants are carried but INERT.** `hestia_scope_status.live_grants` land in
  the snapshot as `path:<abs>` entries, but the core's scope model is workspace-child
  **segment** keyed, so an absolute granted path never matches. Deliberately NOT widened
  into a repo grant nobody made (a file grant must not front for its whole repo). Remaining
  step: a core path-grant predicate (G). Note R1+R2 together mean `hestia_request_scope`
  is not yet an effective relief valve for out-of-launch-repo work — part of the deploy
  ruling above.
- **R3. Launch-cwd grant surface absent.** The core's `launch_cwd_repo` bridge STAYS (now
  parameterised per-shim via `HarnessProfile.launch_cwd_env`); its SPRINT-F marker updated
  to say F ran and could not delete it.
- **R4. Daemon defect found while reading the surface** (worth filing upstream): 
  `tool_operating_law` computes `scope_grants` into the hashed body, then its final
  allowlist projection DROPS the field (handler.rs ~981 vs ~1013-1046) — the exact
  "re-projection loses a field" class its own comments catalogue. `law_hash` covers data
  the caller never receives.
- **R5. codex boundary battery: 6 arms red on the TIP and identically red after F**
  (`test_gate_file_write_refused_locally`, `apply_patch_to_gate`, `bash_write`,
  `approved_gate_write`, `shared_mechanism_write`, `gate_file_read_witnessed`) — codex's
  Sprint-B refuse-and-witness layer has no escalate/claim flow and its gate-self deny rule
  is an unregistered sentence. Pre-existing, not F's; sprintE's gate (E-owned transport
  arms) passes. Fixing it is the B-completion work item, not F's.
- **R6. Perf watch (criterion 10):** the fetch adds one extra MCP session (~5 HTTP
  round-trips) per write-class invocation ahead of Gate 2's own session. Against a local
  daemon this is milliseconds, but the idle-timeout pair-audit should be re-read after
  deploy; G can fold fetch + begin/poll into one session.

## claude-code: assessed — DECLARED, not landed

Measured state (tip `plugins/claude-code/hooks`, main() at ~2557): Gate 1c closure
classify → `ask_daemon` (the E mechanism) → fail-closed `deny_no_verdict` (or legacy
fallback under the non-fail-closed profile). There is **no local scope/egress decision at
all** — its refusal semantics are already daemon-driven; Gate 2 IS its decision path, and
its daemon-down posture (deny everything, reads included, under the fail-closed profile)
is a TIGHTENING of the ratified degraded posture, so criterion 9 is boundedly satisfied
there today. Its evaluate() adoption reduces to inserting the same ~30-line policy stage
between Gate 1c and `ask_daemon` — mechanically contained — **but the policy precondition
does not exist**: claude's unlimited reach must arrive as a *recorded `*` grant from the
authenticated path* (core docstring + PRD §3.1), and per R1 no daemon surface can carry
it. Wiring the stage now would either collapse the operator's primary seat to launch-cwd
scope (a live policy change F is not chartered to impose) or hardcode `*` in the shim (the
shim granting authority — exactly what §4 forbids). Exact remaining step, in order: (1)
land the standing-scope vault/daemon surface (R1) with claude's explicit `*` written as an
auditable grant; (2) then add the identical policy stage — same fetch, same degraded path
— and delete `invoke_legacy_fallback`. Declared here rather than half-landed.

## Battery updates (companion hunks, sanctioned by the batteries' own text)

- `test_gate_core.py` (`batteries_update.diff`): `KNOWN_DUPLICATE_OWNERS` codex 2→1 — the
  test's own instruction is "shrink as harnesses consolidate onto the core"; codex's
  remaining 1 is `*.orig` (history, not enforcement); kimi's 1 is the thin delegation
  adapters the parity battery pins.
- `sprintD_test.py` (`batteries_update_sprintD.diff`): the `{shim}_uses_rule_ids ≥3`
  check now accepts the cutover shape (`_core.evaluate(` + `degraded_verdict` present)
  instead of requiring the shim to AUTHOR ≥3 rule literals — post-F a shim holding rule
  literals would violate §4 ("no decision in the shim"). Any literal that remains must
  still be registered; the ghost-door and remedy-inlining checks are untouched.
- kimi/codex keep ≥3 honest `# SPRINT-F: replace with certified snapshot` markers (the
  bridges that genuinely remain: standing scope R1, launch grant R3, role fallback), so
  sprintD's marker count stays meaningful rather than gamed.

## Verification transcript (patched tree; all commands in `verify.py`)

| suite | result |
|---|---|
| py_compile (6 patched files) | OK |
| test_gate_core (bare runner) | all checks pass (inventory now "4 places") |
| _shared pytest (whole dir) | **88 passed** |
| hestia_gate_mechanism_test (pytest) | 18 passed |
| hestia_governance_closure_test (pytest) | 26 passed |
| cross_harness_closure_test | 5/5 |
| sprintD_test | **65 passed, 0 failed** |
| sprintE_test | 11/11 (boundary: 4 E-owned/neutral green, 6 B-owned red = tip baseline) |
| kimi hooks pytest (parity + boundary) | **15 passed** |
| kimi_gate_boundary_test | 9/9 |
| codex_gate_boundary_test | 4/10 — failing set byte-identical to the TIP baseline (R5) |
| sprintF_test.py (new) | **9/9** — criteria 5, 9(c), 2 pre-proof, no-regression, fetch, order |
| break_the_core_test.py (new) | **2/2** — missing + poisoned core, both shims, Write AND Read fail closed |

Criterion mapping: 5 → `test_criterion5_*` (+ egress-in-degraded); 9(b) →
`break_the_core_test.py`; 9(c) → `test_degraded_denies_are_recorded`; 2 (pre-proof; full
convergence is G) → `test_differential_inputs_converge`; no-regression →
`test_ordinary_in_scope_write_allowed_with_live_snapshot`.

## Deliverables (this directory)

`core_additions_f.diff`, `mechanism_policy_fetch.diff`, `kimi_cutover.diff`,
`codex_cutover.diff`, `batteries_update.diff`, `batteries_update_sprintD.diff`,
`sprintF_test.py`, `break_the_core_test.py`, `F_NOTES.md`, plus the machinery that proves
them: `stage.py` (anchored edits; every anchor must match exactly once), `verify.py`,
`base/` (tip base copies), `tree/` (patched tree the numbers above were measured on).
No `claude_cutover.diff` — declared above, with the exact remaining step.
