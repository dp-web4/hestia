# Phase-1 Gate Profile — PreToolUse Clients for Fail-Open Hook Engines

**Status:** Normative adapter contract, implementation-divergent · current 2026-08-31.
The shared predicate is wired, but one executed gate is not complete: loaders and native-event
normalization still diverge, and 67.5% of measured law-bearing code remains per-seat. Active
completion plan: [SPRINT_ONE_GATE_EXECUTED_AUTHORITY.md](SPRINT_ONE_GATE_EXECUTED_AUTHORITY.md).
**Wire authority:** [`web4-standard/core-spec/presence-protocol.md`](https://github.com/dp-web4/web4/blob/main/web4-standard/core-spec/presence-protocol.md) §§3.1–3.4 — this profile adds **client-construction requirements**, it does not change the wire protocol.
**Thread:** `hestia-role-orchestration` · answers CBP's "ready for your gate-endpoint contract" (`cbp-to-hub-OQ1-ANSWERED-…-2026-07-09.md`)
**Implementation warning:** no current harness is the normative reference for the whole contract.
The shared predicate is wired, but installed-loader authority, typed event normalization,
timeout/recovery behavior, and remaining decision-bearing shim code are not yet converged. New
adapters conform to this document and the active convergence sprint, never by copying an existing
adapter. A green shared-symbol test is not fleet conformance evidence.

---

## 0. Why this profile exists

CBP's binary trace of Kimi Code's hook engine (OQ1) established: **the engine fails OPEN on every
failure path.** A PreToolUse hook blocks *only* on (a) exit code `2` (stderr = deny reason) or (b) exit
`0` with an explicit deny JSON. Timeout (30 s), spawn failure, crash, exit 1, exit 127, internal
exception — all ALLOW. The same lineage semantics are suspected for Codex/Cursor (verify per agent
before trusting; discovery by measurement, never by asking).

Consequence: for a foreign agent, **the membrane is only as strong as the hook script's own
construction.** The daemon is fail-closed; the harness is fail-open; the hook client is the joint. This
profile specifies that joint.

## 1. The gate endpoint (unchanged, already running)

The gate is the **running hestia daemon** — machine-local, loopback-only:

- **Transport:** MCP JSON-RPC over HTTP, `POST` to the daemon's `/mcp` endpoint.
  Default `http://127.0.0.1:7711/mcp`.
- **Endpoint discovery (in order):** `$HESTIA_ENDPOINT` env → `$HESTIA_HOME/endpoint` file
  (default home `~/.hestia/`) → default above. No discovery result in fail-closed mode ⇒ deny (§3).
- **Call sequence per tool use** (presence-protocol §§3.1, 3.2, 3.4):
  1. `hestia_connect` — establish/refresh the session (cacheable across calls; see the reference
     client's action cache).
  2. `hestia_begin_action` — register the pending act (tool name, target, session).
  3. `hestia_query_policy` — get the verdict for the `action_id`.
- **Verdict shape** (§3.4): `{ decision: "allow"|"warn"|"deny", reason, guidance, ruleId, enforced,
  constraints[], status: "decided"|"evaluating", nextPollMs }`.
- **`guidance` (optional string, null except on enforced deny)** — daemon-composed steering for the
  blocked *agent*: why + "boundary, not a failure" + don't-re-run + what to do instead. Clients MUST
  surface it verbatim on their deny channel when present (it replaces the bare `reason` line) and MUST
  NOT parse it; `reason`/`ruleId`/`ruleName` remain the machine-readable fields. Absent/null `guidance`
  ⇒ fall back to `reason`. A deny that only blocks trains retry-loops; this field is the redirect.
- The daemon fold is in-process and synchronous (µs) — see `core/src/server/handler.rs` (base rules +
  role overlay via `fold_strictest`; the `web4-policy` law input is the third fold input arriving with
  the consolidation task). Transport, not evaluation, is the latency budget.

## 2. Evaluation identity (who is asking)

The client MUST present, via environment at hook-fire time:

| Env | Meaning | Kimi Phase-1 value |
|---|---|---|
| `HESTIA_PLUGIN_ID` | which adapter/member | `kimi` |
| `HESTIA_HOST_AGENT` | the host agent binary | `kimi-code` |
| `HESTIA_ROLE` | the constellation role whose law overlay applies | `role:constellation:foreign-kimi` |
| `HESTIA_PRE_FAIL_CLOSED` | fail-closed switch (§3) | `1` — **MANDATORY for foreign agents** |

The daemon evaluates against the `(plugin_id, role)` grain. *Implementation note (tracked):
`role_policy_engines` currently keys on role alone; the per-plugin policy grain is the daemon-side task
this profile pins (CBP's "remaining leg" — stats ✅, trust ✅, policy ⬜).*

## 3. The fail-closed client contract (normative)

For any hook engine verified or suspected fail-open, the PreToolUse client MUST be
**fail-closed by construction**:

1. **Deny is the default control path.** The script arms denial *first* and disarms it only on a
   confirmed allow. Shell shape:
   ```
   trap 'exit 2' EXIT            # armed before anything can fail
   ...daemon call, verdict parse...
   [ "$decision" = allow-ish ] && { trap - EXIT; exit 0; }
   exit 2                        # everything else
   ```
   A script bug, missing binary (exit 127), OOM-kill, or unhandled error then *lands on deny*, not on
   the engine's allow.
2. **Never rely on `set -e` or natural error propagation.** Only an explicit `exit 2` blocks; any other
   non-zero exit is an ALLOW to the engine.
3. **Internal deadline below the harness allow-timeout, measured per harness.** A universal 2-second
   figure was written before the fleet had a cross-harness latency matrix and is not evidence of a
   safe budget. The client deadline plus worst-case cleanup/witness time MUST leave measured margin
   below the host timeout. Exceeding it denies locally, records a rate-limited Plane-E
   `cause=timeout` event where possible, and gives bounded backoff guidance. The hook itself MUST
   never be allowed to reach a host timeout that the engine interprets as allow.
4. **Daemon unreachable / endpoint undiscovered / malformed response ⇒ deny** with a reason naming the
   failure. (This is `HESTIA_PRE_FAIL_CLOSED=1` — HST-004 — restated as non-optional for foreign
   agents, with the binary evidence for why.)
5. **Forward-compatibility is fail-closed:** any `decision` value outside `{"allow","warn"}` — including
   values this profile does not yet define — maps to **deny**. This reserves `"escalate"` (§5) without a
   client change.
6. **Wait protocol, bounded by the measured client deadline:** on `status:"evaluating"`, the client
   MAY re-poll per `nextPollMs`; an unsettled verdict at deadline denies. Retry count is derived from
   the harness budget rather than fixed here. Human resolution never occupies this hot-path budget.
7. **Thin means thin.** No policy logic, no caching of verdicts across actions, no retries beyond the
   deadline, no network beyond loopback. The client's entire job: identity + wire call + exit-code
   discipline.

## 4. Verdict → engine mapping (Kimi hook engine)

| Daemon verdict | Client behavior |
|---|---|
| `allow` (`status:"decided"`) | `trap - EXIT; exit 0`, silent |
| `warn` | `exit 0`, one-line reason on stderr (surfacing in Kimi's UI is unverified — witness the warn regardless via the observe stream) |
| `deny` | `exit 2`, `guidance` (fallback: one-line reason) on stderr (becomes the engine's deny reason) |
| anything else / error / timeout | `exit 2` (§3 rules 1–6) |

Rollout: Phase 1 starts in **WARN mode** (daemon policy maps would-be-denies to warn; the runbook's
sequence), then flips to ENFORCE — the flip is a *daemon policy change*, not a client change.

## 5. Escalation (reserved, async, never on the hot path)

Post-consolidation (hestia/core consuming `web4-policy`), the law input can yield an **escalate**
verdict. Decision 0013 supersedes the original portable-grant model:

- Wire: `decision:"escalate"` — by §3 rule 5, existing clients already deny on it. The immediate effect
  is a **blocking deny-with-reason** (`escalation queued: <reason>`); the tool call never waits on a
  human.
- Daemon-side: the escalation references the already-recorded denied act by `action_id` and its
  canonical, domain-separated digest. A ruling appends a terminal transition to that act; it does
  not mint a marker token or authorize a merely similar future action. A retry is eligible only when
  it re-presents the same canonical act and, after Sprint 2 identity work, the same signed originating
  role/agent chain. Timeout is recorded as a terminal non-merits denial.
- The `status:"evaluating"` branch stays reserved for engine-internal async (LLM-backed reviewers),
  *not* for human escalation — humans are minutes, the budget is seconds; conflating them re-opens the
  timeout-as-bypass hole.

## 6. Conformance checklist for a new adapter's gate client

- [ ] `exit 2` armed via trap before first fallible statement
- [ ] explicit `exit 0` only after parsing a `decided` `allow`/`warn`
- [ ] internal deadline measured below this harness's allow-timeout with cleanup margin
- [ ] timeout/refusal/crash each fail closed and produce the required Plane-E/outage evidence
- [ ] unknown decision values → deny (test with a mock daemon returning `"escalate"`)
- [ ] daemon-down test → deny (kill daemon, fire hook, confirm block)
- [ ] exit-127 test → engine sees exit 2, not 127 (break the script's interpreter path, confirm block)
- [ ] identity envs set (`HESTIA_PLUGIN_ID`, `HESTIA_HOST_AGENT`, `HESTIA_ROLE`, `HESTIA_PRE_FAIL_CLOSED=1`)
- [ ] warn path witnessed in the observe stream

---
*Graduation path: the profile graduates only after the shared decision core is wired, every installed
harness passes the same idle/load/failure matrix, and act-bound appeal conformance vectors pass across
the adapters and daemon. Copying the prose into a second adapter is not conformance evidence.*
