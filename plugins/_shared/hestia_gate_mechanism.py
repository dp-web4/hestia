#!/usr/bin/env python3
"""Shared in-process daemon-query mechanism — the society-safety verdict path.

PRD gate-consolidation §6.E (the shared TRANSPORT / mechanism module). Extracted from the
claude-code adapter's tested client so every harness can obtain a society-safety verdict
IN-PROCESS — no subprocess spawn, no cross-mount re-import of a 2760-line gate. This is what
lets a shim be *thin* and closes the criterion-10 timeout asymmetry: kimi/codex were reaching
the verdict by forking the whole claude gate off the slow /mnt/c mount, cold, every call, and
that path could not complete inside budget (kimi still timed out 2026-08-12).

This is the MECHANISM, deliberately distinct from the LAW core (hestia_gate_core, which is
transport-free and must never open a socket). The mechanism MAY talk to the daemon; the law
may not. Keep that boundary: scope/egress/policy predicates belong in the core, the daemon
round-trip belongs here.

FAIL-CLOSED CONTRACT (load-bearing — read before editing; hardened per GPT NOT-SAME review of #371):
  query_society_safety NEVER returns allow except on an EXPLICITLY recognized daemon verdict.
  It never raises. Specifically, every one of these fails closed (allow=False, decided=False):
    - config: a non-numeric/invalid budget env var (parsed safely at import, never raising);
    - transport: no endpoint, initialize failure, connect rejection, network/unexpected exception;
    - authentication: connect returning no sessionId (a missing session is not an optional downgrade);
    - budget: the whole-run deadline exhausted — no request may START after it;
    - WIRE SHAPE: a missing/unknown `status`, or a decision whose `decision` field is not exactly
      one of {allow, warn, deny}. "Faithful to the claude adapter" is NOT the contract here — the
      claude adapter defaults unknowns to allow, which on a fail-open engine would un-govern the
      member. This module treats any unrecognized shape as NO VERDICT.
  Only `decision in {allow, warn, deny}` (with `enforced`) may authorize or block.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


# ── Budget / timeout contract (env-overridable; parsed SAFELY so a bad value cannot raise at
# import and, on a fail-open engine, turn a config typo into an ALLOW). Invalid → default. ─────
def _num_env(name: str, default: float, cast) -> float:
    try:
        v = cast(os.environ.get(name, default))
        return v if v > 0 else default
    except (ValueError, TypeError):
        return default


# 2500ms (was 800): the 800 default predates Sprint F — it assumed ONE lean round-trip.
# The consolidated path runs TWO legs (policy snapshot + society verdict), and the daemon
# shows a measured multi-second COLD window after restart (5.7s first-connect, 1ms after;
# filed as a daemon regression). 2500 fits inside codex's ~3s engine clamp with margin,
# keeps the gate the fail-closed party, and gives steady-state (1-30ms/leg) wide headroom.
# Env-overridable as ever: HESTIA_PRE_TOTAL_BUDGET_MS.
# 4000 (was 2500): first FIELD-DIAGNOSED dropout (2026-08-14, cause telemetry) was a
# raw socket TimeoutError on an idle box — the daemon has intermittent multi-second
# stall windows (#423: latency jitter 2-228ms + spikes past 2.5s, 10% idle CPU busy
# loop). 4000 x (1 try + 1 retry) absorbs stalls to ~8s, still well inside the
# measured engine clamps (codex 15s config, kimi 30s config).
TOTAL_BUDGET_MS = int(_num_env("HESTIA_PRE_TOTAL_BUDGET_MS", 4000, int))
REQUEST_TIMEOUT_S = float(_num_env("HESTIA_PRE_REQUEST_TIMEOUT_S", 5.0, float))
MAX_POLLS = 5
MIN_POLL_SLEEP_MS = 50
PROTOCOL_VERSION = 1
DEFAULT_HESTIA_HOME = Path.home() / ".hestia"

_RECOGNIZED_DECISIONS = ("allow", "warn", "deny")


@dataclass
class SafetyVerdict:
    """Result of a society-safety query. `allow` is the ONLY field a caller acts on to proceed.

    allow=True   -> daemon returned an explicit allow, warn, or audit-only-deny: may proceed.
    allow=False  -> an enforced daemon deny (decided=True) OR no verdict at all
                    (decided=False: infra failure, missing session, or an unrecognized wire shape).
                    The caller fails closed either way.
    `decided` distinguishes a real verdict from a fail-closed non-verdict so the caller can render
    the two differently and so non-verdicts are never scored as member conduct.

    `kind` (Sprint E) is the RENDER hint: "allow" | "warn" | "deny" | "none". It exists so a
    renderer (claude-code's emit_decision) keeps its distinct warn/deny messaging without
    re-parsing `message`. Non-breaking: it never changes the allow/decided contract — an
    audit-only deny renders as kind="warn" (surfaced on stderr, exit 0; `message` still says
    would-deny) and a fail-closed non-verdict is kind="none". Callers that ignore `kind`
    (kimi, codex) behave exactly as before.

    `action_id` (Sprint E) is the daemon's actionId when begin/poll produced one — the
    correlation key claude-code's PostToolUse outcome cache uses. None when no verdict.
    """
    allow: bool
    decided: bool
    message: str
    cause: str = "unknown"   # when not decided: "timeout" | "refused" | "unknown"
    kind: str = "none"       # "allow" | "warn" | "deny" | "none" — render hint only
    action_id: Optional[str] = None


# ── MCP-over-HTTP client (in-process; MAY open a socket — mechanism, not law) ─────────────────
def _parse_json_or_sse(text: str) -> dict:
    text = text.strip()
    if not text:
        return {}
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("data:"):
            body = line[5:].strip()
            if body and body.startswith("{"):
                try:
                    return json.loads(body)
                except json.JSONDecodeError:
                    continue
    return {}


def _unwrap_tool_result(rpc_response: dict) -> dict:
    result = rpc_response.get("result") or {}
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            try:
                return json.loads(block.get("text", ""))
            except (json.JSONDecodeError, TypeError):
                pass
    return {}


class _McpHttp:
    def __init__(self, endpoint: str, deadline: float) -> None:
        self.endpoint = endpoint
        self.session_id: Optional[str] = None
        self.next_id = 0
        self.deadline = deadline  # monotonic time after which we give up

    def _id(self) -> int:
        self.next_id += 1
        return self.next_id

    def _request(self, body: dict, *, is_notification: bool = False) -> Optional[dict]:
        # FAIL-CLOSED budget guard: refuse to START a request once the whole-run deadline is
        # exhausted (GPT #4). Raising here surfaces as a timeout the entry-point catches.
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("whole-run budget exhausted before request")
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        req = urllib.request.Request(self.endpoint, data=data, headers=headers, method="POST")
        timeout = min(REQUEST_TIMEOUT_S, max(0.01, remaining))
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if not self.session_id:
                sid = resp.headers.get("mcp-session-id")
                if sid:
                    self.session_id = sid
            if is_notification:
                return None
            payload = resp.read().decode("utf-8", errors="replace")
        return _parse_json_or_sse(payload)

    def initialize(self) -> dict:
        return self._request({
            "jsonrpc": "2.0", "id": self._id(), "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "hestia-shared-gate", "version": "1"}},
        }) or {}

    def initialized(self) -> None:
        self._request({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                      is_notification=True)

    def call_tool(self, name: str, arguments: dict) -> dict:
        return self._request({
            "jsonrpc": "2.0", "id": self._id(), "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }) or {}


def _discover_endpoint() -> Optional[str]:
    env = os.environ.get("HESTIA_ENDPOINT")
    if env:
        return env
    home = Path(os.environ.get("HESTIA_HOME", str(DEFAULT_HESTIA_HOME)))
    try:
        v = (home / "endpoint").read_text().strip()
        return v or None
    except OSError:
        return None


def _extract_target(tool_input: Any, tool_name: str) -> Optional[str]:
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "path", "url", "notebook_path"):
        v = tool_input.get(key)
        if isinstance(v, str):
            return v
    # CASE-INSENSITIVE (Sprint E, §3.3 audit hole): codex's engine emits the shell tool as
    # "bash" lowercase; the old {"Bash", "Shell"} literal missed it, so every codex shell act
    # reached the daemon with target=None and its chain records carried an EMPTY target — a
    # one-character audit hole. Normalize before comparing; never widen beyond shell names.
    if isinstance(tool_name, str) and tool_name.lower() in {"bash", "shell"}:
        cmd = tool_input.get("command")
        if isinstance(cmd, str) and cmd.strip():
            return cmd.split()[0]
    return None


def _poll_policy(client: _McpHttp, action_id: str, session_id: Optional[str],
                 deadline: float) -> Optional[dict]:
    """Call hestia_query_policy, honoring the wait protocol. Returns the decided payload, or
    None on timeout / error / an UNRECOGNIZED status. None -> caller fails closed.

    STRICT (GPT #1): a missing or unknown `status` is NOT treated as decided — that would let a
    garbled response authorize. Only status == "decided" returns a body; "evaluating" re-polls;
    anything else is no verdict."""
    for _ in range(MAX_POLLS):
        if time.monotonic() >= deadline:
            return None
        args: dict = {"action_id": action_id}
        if session_id:
            args["session_id"] = session_id
        body = _unwrap_tool_result(client.call_tool("hestia_query_policy", args))
        if "_hestia_error" in body:
            return None
        status = body.get("status")
        if status == "decided":
            return body
        if status != "evaluating":
            return None  # missing/unknown status -> NO verdict (strict; not "assume decided")
        next_poll_ms = body.get("nextPollMs")
        if not isinstance(next_poll_ms, int) or next_poll_ms < 0:
            next_poll_ms = 200
        sleep_ms = max(MIN_POLL_SLEEP_MS, next_poll_ms)
        remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
        sleep_ms = min(sleep_ms, remaining_ms)
        if sleep_ms <= 0:
            return None
        time.sleep(sleep_ms / 1000.0)
    return None


def _interpret(decision: dict) -> Optional[SafetyVerdict]:
    """Map a daemon PolicyResult dict to a SafetyVerdict, STRICTLY. Returns None if the decision
    is not an explicitly recognized {allow, warn, deny} shape — the caller then fails closed.

    Unlike the claude adapter's emit_decision (which defaults unknowns to allow), an unrecognized
    decision here is NO VERDICT, never an allow (GPT #1)."""
    if not isinstance(decision, dict):
        return None
    verdict = decision.get("decision")
    if verdict not in _RECOGNIZED_DECISIONS:
        return None  # missing or unknown decision vocabulary -> no verdict
    enforced = bool(decision.get("enforced", True))
    reason = decision.get("reason", "")
    rule_name = decision.get("ruleName")
    label = f" [{rule_name}]" if rule_name else ""
    if verdict == "deny" and enforced:
        guidance = decision.get("guidance")
        return SafetyVerdict(allow=False, decided=True, kind="deny",
                             message=(guidance or f"hestia: deny{label} — {reason}"))
    if verdict == "warn":
        return SafetyVerdict(allow=True, decided=True, kind="warn",
                             message=f"hestia: warn{label} — {reason}")
    if verdict == "deny":  # not enforced -> audit-only: surfaced like a warn, exit 0
        return SafetyVerdict(allow=True, decided=True, kind="warn",
                             message=f"hestia: would-deny (audit-only){label} — {reason}")
    return SafetyVerdict(allow=True, decided=True, kind="allow", message="")  # verdict == "allow"


def _no_verdict(plugin_id: str, tool_name: str, cause: str, detail: str) -> SafetyVerdict:
    """Compose the fail-closed 'no verdict' result and record the infra failure (never scored as
    member conduct). NEVER raises."""
    remedy = {
        "timeout": ("The daemon did not answer within the gate's budget — most likely ALIVE BUT "
                    "LOADED, not down. Wait and retry with backoff; if it persists across "
                    "minutes, report to your operator."),
        "refused": ("Nothing is listening on the daemon endpoint, so no action can be approved. "
                    "Report this to your operator and wait — retrying will not help."),
    }.get(cause, ("The gate could not obtain a verdict and cannot tell whether the daemon is down "
                  "or slow. Retry once with backoff; if it repeats, report to your operator."))
    msg = (f"hestia: no verdict [fail-closed] — the policy daemon did not return a usable decision "
           f"({detail}; cause={cause}). This is NOT a policy boundary and NOT a tool failure — the "
           f"referee is unreachable or its answer was unusable, so the gate fails closed for "
           f"safety. {remedy}")
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        from hestia_gate_core import record_gate_unavailable  # type: ignore
        record_gate_unavailable(plugin_id, tool_name, cause, detail, home=str(DEFAULT_HESTIA_HOME))
    except Exception:
        pass
    return SafetyVerdict(allow=False, decided=False, message=msg, cause=cause)


def query_society_safety(event: dict, *, plugin_id: str, host_agent: str,
                         plugin_version: Optional[str] = None,
                         host_agent_version: Optional[str] = None,
                         host_session_id: Optional[str] = None) -> SafetyVerdict:
    """Obtain the daemon's society-safety verdict for a write/exec act, IN-PROCESS.

    Replaces "spawn the claude gate as a subprocess" for a thin shim. Returns a SafetyVerdict;
    NEVER raises; on any failure/malformed/missing-session yields allow=False, decided=False.

    `plugin_version` / `host_agent_version` are the shim's REAL version facts and are omitted
    from the connect payload when unknown — the mechanism does not manufacture provenance (GPT #3).
    """
    tool_name = event.get("tool_name") or "?"
    tool_input = event.get("tool_input") or {}
    try:
        endpoint = _discover_endpoint()
        if endpoint is None:
            return _no_verdict(plugin_id, tool_name, "refused", "no daemon endpoint discovered")
        deadline = time.monotonic() + (TOTAL_BUDGET_MS / 1000.0)
        target = _extract_target(tool_input, tool_name)
        client = _McpHttp(endpoint, deadline)
        init = client.initialize()
        if "result" not in init:
            return _no_verdict(plugin_id, tool_name, "unknown", "initialize failed")
        client.initialized()
        connect_args: dict = {
            "plugin_id": plugin_id,
            "host_agent": host_agent,
            "requested_role": "citizen",
            "protocol_version": PROTOCOL_VERSION,
        }
        if plugin_version:
            connect_args["plugin_version"] = plugin_version
        if host_agent_version:
            connect_args["host_agent_version"] = host_agent_version
        role = os.environ.get("HESTIA_ROLE")
        if role:
            connect_args["role"] = role
        if host_session_id:
            connect_args["host_session_id"] = host_session_id
        connect = _unwrap_tool_result(client.call_tool("hestia_connect", connect_args))
        if "_hestia_error" in connect:
            return _no_verdict(plugin_id, tool_name, "unknown", "connect rejected")
        session_id = connect.get("sessionId")
        if not session_id:
            # A governance verdict must ride an authenticated session. Missing sessionId is
            # fail-closed, not an optional downgrade (GPT #2).
            return _no_verdict(plugin_id, tool_name, "unknown", "connect returned no sessionId")
        begin_args: dict = {
            "tool_name": tool_name,
            "target": target,
            "parameters": dict(tool_input) if isinstance(tool_input, dict) else {},
            "session_id": session_id,
        }
        if host_session_id:
            begin_args["host_session_id"] = host_session_id
        begin = _unwrap_tool_result(client.call_tool("hestia_begin_action", begin_args))
        if "_hestia_error" in begin:
            return _no_verdict(plugin_id, tool_name, "unknown", "begin_action rejected")
        action_id = begin.get("actionId")
        if not action_id:
            return _no_verdict(plugin_id, tool_name, "unknown", "begin_action missing actionId")
        decision = _poll_policy(client, action_id, session_id, deadline)
        if decision is None:
            return _no_verdict(plugin_id, tool_name, "timeout",
                               "query_policy never returned a decided verdict within budget")
        verdict = _interpret(decision)
        if verdict is None:
            return _no_verdict(plugin_id, tool_name, "unknown",
                               "daemon returned a malformed or unrecognized decision")
        verdict.action_id = action_id  # correlation key for the caller's outcome cache
        return verdict
    except (urllib.error.URLError, TimeoutError, socket.timeout) as e:
        reason = getattr(e, "reason", None)
        if isinstance(reason, TimeoutError) or isinstance(e, (TimeoutError, socket.timeout)):
            cause = "timeout"
        elif isinstance(reason, ConnectionRefusedError):
            cause = "refused"
        else:
            cause = "unknown"
        return _no_verdict(plugin_id, tool_name, cause, f"network: {type(e).__name__}")
    except Exception as e:  # noqa: BLE001 — FAIL-CLOSED: any unexpected error is no-verdict, never allow
        return _no_verdict(plugin_id, tool_name, "unknown", f"unexpected: {type(e).__name__}")


# ── ONE deny recorder (Sprint E — PRD §3.3 bullets 4-6, §6.E) ─────────────────────────────────
# Before this, the deny recorder varied by vendor: codex reported to the chain (with its own
# private client), kimi recorded only inside a bare `except: pass`, claude wrote no refusal
# record at all on this path — and NO plugin's deny record carried the command/target (only
# claude's begin_action did), so the trust chain's denominator differed by harness and the
# record could not say WHAT was refused. Every shim now calls witness_decision_unified for
# refusal records. Contract:
#   - ALWAYS carries `target` (the audit hole) and `verdict_available` (kimi previously could
#     not distinguish a real deny from an infra fail-close — §3.3 bullet 5);
#   - NEVER raises and never changes the caller's decision (the deny stands regardless);
#   - NON-SILENT failure: if the daemon witness cannot be delivered, the full record — with the
#     delivery error — is appended to the per-shim diagnostic log
#     ~/.hestia/telemetry/gate-denies-<plugin_id>.jsonl (criterion 9(c) fallback witness), so a
#     dead daemon degrades the record's REACH, never its existence.

def _deny_fallback_path(plugin_id: str) -> Path:
    home = Path(os.environ.get("HESTIA_HOME", str(DEFAULT_HESTIA_HOME)))
    safe = "".join(c if (c.isalnum() or c in "-_.") else "-" for c in (plugin_id or "unknown"))
    return home / "telemetry" / f"gate-denies-{safe}.jsonl"


def _append_deny_fallback(plugin_id: str, record: dict) -> None:
    """Criterion 9(c) fallback witness: append-only, per-shim, never raises."""
    try:
        path = _deny_fallback_path(plugin_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
    except Exception:
        pass  # the fallback of the fallback is silence; the deny itself already stood



def _loaded_core_digest():
    try:
        import sys as _s
        _c = _s.modules.get("hestia_gate_" + "core")
        return getattr(_c, "_CORE_DIGEST", None) if _c is not None else None
    except Exception:
        return None

def witness_decision_unified(client_or_none, *, plugin_id: str, decision: str, rule: str,
                             tool_name: str, target: Optional[str], session_id: Optional[str],
                             verdict_available: bool, attempted_summary: str) -> bool:
    """Record a refusal (deny/warn) to the daemon's witness chain — the ONE deny recorder.

    `client_or_none`: an already-initialized MCP client to reuse, or None to open a short
    single-shot session (deadline ~1.5s; only ever runs on the deny/warn path, so no
    hook-clamp pressure on allows). Returns True when the daemon acknowledged the record;
    False when it went to the fallback log instead. NEVER raises."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    record = {
        "plugin_id": plugin_id,
        "decision": decision,                       # deny | warn
        "rule": (rule or "")[:300],
        "tool_name": tool_name or "",
        "target": target,                           # ALWAYS present — the audit hole, closed
        "session_id": session_id,
        "verdict_available": bool(verdict_available),
        # Deployed-generation attestation (§7.2(7)): the digest of the core THIS process
        # imported, or absent when no core is loaded — never a bystander file hash.
        "core_digest": _loaded_core_digest(),
        "attempted": attempted_summary,
        "ts": ts,
    }
    try:
        client = client_or_none
        if client is None:
            endpoint = _discover_endpoint()
            if endpoint is None:
                raise RuntimeError("no daemon endpoint discovered")
            client = _McpHttp(endpoint, time.monotonic() + 1.5)
            if "result" not in client.initialize():
                raise RuntimeError("initialize failed")
            client.initialized()
        out = client.call_tool("hestia_witness_decision", {
            "plugin_id": plugin_id,
            "decision": decision,
            "adjudicator": f"plugin-gate:{plugin_id}",
            "reason": (rule or "")[:300],
            # False => the gate could not REACH a verdict (infra fail-close). Structurally not
            # conduct: "I could not judge" is not "I judged you badly" — derivation excludes
            # these from temperament with no exoneration needed (codex's discrimination, now
            # every harness's — §6.E).
            "verdict_available": bool(verdict_available),
            "tool_name": tool_name or "",
            "target": target,
            "session_id": session_id,
            "attempted": attempted_summary,
            # REPAIR 5 (GPT fleet-review blocker 5): the deployed-generation attestation
            # rides the HEALTHY witness call too, not only the fallback log — before this,
            # the digest that #7.2(7) exists for reached no chain record at all. The daemon
            # accepts extra arguments (hestia tools accept any argument), which ALSO means
            # a schema that does not persist this field would discard it SILENTLY - so the
            # local fallback record above keeps carrying it regardless, and daemon-side
            # persistence needs its own verification (R345_NOTES.md).
            "core_digest": record["core_digest"],
        })
        if not (isinstance(out, dict) and "result" in out):
            raise RuntimeError("witness call returned no result")
        return True
    except Exception as e:  # noqa: BLE001 — non-silent: the record survives in the fallback log
        record["witness_delivery_failed"] = f"{type(e).__name__}: {e}"
        _append_deny_fallback(plugin_id, record)
        return False


# ── Authenticated policy path (Sprint F — PRD §6.F; §7.1 criteria 2/5) ─────────────────
# fetch_policy_snapshot: the LIVE, in-process fetch of this member's policy from the
# daemon — the snapshot evaluate() consumes in enforce mode, riding the SAME MCP client
# as the society-safety path. Returns None on ANY transport failure: that is the ratified
# degraded-mode trigger (the daemon is unreachable), and the shim then takes the core's
# degraded_verdict — never a local-replica fallback. A daemon that ANSWERS but lacks a
# surface (an older build; the boundary-test stub) yields a THIN snapshot instead: thin
# grants NOTHING extra (the tighter direction), and reachable-but-thin is not the
# degraded trigger — society safety still governs writes on that path.
#
# WHAT THE DAEMON CAN CERTIFY TODAY (measured 2026-08-13, core/src/server/handler.rs;
# extended 2026-08-14, Sprint F R1 — the standing-scope surface, ending R1's "no daemon
# surface for standing repo scope"):
#   - hestia_operating_law(session_id): identity{plugin_id, role} — the daemon-resolved
#     role for this session (replacing the identity.json role bridge when present) — plus
#     the composed law and its law_hash, and any disclosed operator_grant (and, with R1,
#     a projection that finally carries the scope_grants its own hash covers — #407);
#   - hestia_scope_status(plugin_id): the live, memory-only PATH grants minted by
#     hestia_request_scope (carried as "path:<path>" entries in `in_scope`), PLUS the
#     durable operator-promoted `standing_grants` from the daemon's vault-persisted
#     store, with the store's monotonic `generation` and a daemon-issued
#     `snapshot_expires_at` — the certification pair AgentPolicy has required since
#     2026-08-04 with nothing issuing it. A standing grant naming a REPO ROOT directly
#     under the workspace is carried as the bare repo NAME (the form the core's
#     segment-keyed scope model admits); a deeper path keeps the faithful "path:" form
#     (a file grant must not front for its whole repo).
# WHAT IT STILL CANNOT (declared RED in Sprint F's notes):
#   no launch-cwd grant surface exists, and deeper-than-root "path:" entries stay inert
#   against the core's segment-keyed model (R2). Absent surfaces contribute NOTHING to
#   the snapshot: an older daemon without `standing_grants` yields the pre-R1 snapshot.

def _workspace_root() -> str:
    """The ONE workspace-root answer for grant mapping — delegated to the core's portable
    `detect_workspace` (env `HESTIA_WORKSPACE` when it names a real directory, else the
    marker-based cwd climb, else the core's documented default), so live and standing
    grants cannot diverge from the boundary the core's scope model actually enforces.
    GPT review of #431, blocker 4: a second resolver here carried a machine-specific
    fallback, so a repo-root grant admitted on one box and stayed inert on every layout
    where the core discovered the workspace without the env var."""
    try:
        from hestia_gate_core import HarnessProfile, detect_workspace
        return detect_workspace(HarnessProfile(member_id="", identity_path=""))
    except Exception:
        env = os.environ.get("HESTIA_WORKSPACE")
        return env if env and os.path.isdir(env) else os.getcwd()


def _scope_entry_for_grant(path: str) -> str:
    """A granted path becomes the `in_scope` spelling the core can actually honour —
    the ONE mapping, used by live and standing grants alike (GPT #431 blocker 4;
    subsumes #430's inline live-grant fix).

    A grant naming a REPO ROOT directly under the workspace maps to the bare repo NAME —
    the only form evaluate()'s segment-keyed scope model admits. Anything deeper keeps
    the faithful "path:" form, which the core matches only at that resolved boundary and
    below: a FILE grant must not front for its whole repo (Sprint F R2's conservatism,
    still binding). Lexical + realpath, no stat: the daemon records
    grants while this gate enforces them, and the two must agree on what a path names
    even when the object does not exist yet."""
    p = os.path.realpath(os.path.expanduser(path.strip()))
    ws = os.path.realpath(os.path.expanduser(_workspace_root()))
    par, name = os.path.split(p.rstrip("/"))
    if par == ws and name:
        return name
    return "path:" + path.strip()


#: One fetch per gate invocation — gate processes are short-lived, so a per-process cache
#: is a per-invocation cache; it exists so a shim may consult the snapshot at several
#: seams without paying several round-trips.
_POLICY_SNAPSHOT_CACHE: dict = {}


def fetch_policy_snapshot(plugin_id, **kw):
    """One retry before None: the measured failure mode is TRANSIENT starvation (a
    session-start hook herd overlapping the first tool calls — codex, 2026-08-14),
    not a down daemon. A 250ms-backoff second attempt absorbs the blip; a genuinely
    unreachable daemon still returns None inside one extra budget and the ratified
    degraded mode proceeds. Never raises (same contract as the single attempt)."""
    snap = _fetch_policy_snapshot_once(plugin_id, **kw)
    if snap is not None:
        return snap
    try:
        import time as _t
        _t.sleep(0.25)
    except Exception:
        pass
    return _fetch_policy_snapshot_once(plugin_id, **kw)


def _fetch_policy_snapshot_once(plugin_id: str, *, host_agent: Optional[str] = None,
                          host_session_id: Optional[str] = None,
                          use_cache: bool = True) -> Optional[dict]:
    """Fetch this member's policy snapshot from the daemon, in-process. NEVER raises.

    None  -> the daemon is unreachable / did not authenticate the session (no sessionId):
             the caller must take the ratified degraded path in enforce mode.
    dict  -> a snapshot the daemon answered for. ALWAYS carries an `in_scope` LIST (so the
             core's resolve_agent_policy(vault_reader=...) seam can never fall through to
             the local replica on this path), plus `role`, `law_hash`, `operator_grant`,
             `scope_grants`, `standing_grants`, `generation`, `expires_at`, `source`,
             `fetched_at`, `session_id`. `generation`/`expires_at` are the daemon-issued
             certification pair (Sprint F R1): resolve_agent_policy stamps them onto the
             AgentPolicy it returns, and refuses the snapshot outright past its horizon."""
    if use_cache and plugin_id in _POLICY_SNAPSHOT_CACHE:
        return _POLICY_SNAPSHOT_CACHE[plugin_id]
    snap = _fetch_policy_snapshot_uncached(plugin_id, host_agent, host_session_id)
    if use_cache and snap is not None:
        _POLICY_SNAPSHOT_CACHE[plugin_id] = snap
    return snap


def _snapshot_unavailable(plugin_id: str, cause: str) -> None:
    """Field telemetry for a failed snapshot fetch (never raises): the 2026-08-14 codex
    dropouts were unreproducible from another seat precisely because every failure path
    collapsed to a causeless None — a 'daemon unreachable' that could be refused/timeout/
    port-exhaustion/EPERM. Each is a different fix; the log now says which."""
    try:
        from hestia_gate_core import record_gate_unavailable  # type: ignore
        record_gate_unavailable(plugin_id, "policy-snapshot", "snapshot-fetch", cause,
                                home=str(DEFAULT_HESTIA_HOME))
    except Exception:
        pass


def _fetch_policy_snapshot_uncached(plugin_id: str, host_agent: Optional[str],
                                    host_session_id: Optional[str]) -> Optional[dict]:
    try:
        endpoint = _discover_endpoint()
        if endpoint is None:
            _snapshot_unavailable(plugin_id, "no-endpoint")
            return None
        deadline = time.monotonic() + (TOTAL_BUDGET_MS / 1000.0)
        client = _McpHttp(endpoint, deadline)
        if "result" not in client.initialize():
            _snapshot_unavailable(plugin_id, "init-no-result")
            return None
        client.initialized()
        connect_args: dict = {
            "plugin_id": plugin_id,
            "host_agent": host_agent or plugin_id,
            "requested_role": "citizen",
            "protocol_version": PROTOCOL_VERSION,
            "instance_name": "gate-policy-fetch",
            # Runtime SELF-REPORT from this gate engine. The daemon keeps the last accepted
            # report separate from its own build freshness, but it has no identity,
            # session, freshness, or build binding: A1 historical evidence only. It cannot
            # prove which gate is currently loaded; the governed installed-artifact problem
            # remains #481.
            "gate_capabilities": ["society-floor:v1"],
        }
        role_env = os.environ.get("HESTIA_ROLE")
        if role_env:
            connect_args["role"] = role_env
        if host_session_id:
            connect_args["host_session_id"] = host_session_id
        connect = _unwrap_tool_result(client.call_tool("hestia_connect", connect_args))
        if "_hestia_error" in connect:
            _snapshot_unavailable(plugin_id, "connect-refused:" + str(
                (connect.get("_hestia_error") or {}).get("code", "?"))[:80])
            return None
        session_id = connect.get("sessionId")
        if not session_id:
            # A policy snapshot must ride an authenticated session; an unattributed answer
            # certifies nothing (same rule as the society-safety path, GPT #2).
            return None
        snap: dict = {
            "member_id": plugin_id,
            "source": "daemon-live",
            "fetched_at": int(time.time()),
            "session_id": session_id,
            "role": None,
            "law_hash": None,
            "operator_grant": None,
            "in_scope": [],
            "scope_grants": [],
            "standing_grants": [],
            # Initialised HERE, with its siblings. The omission was a real bug for the ten
            # minutes it existed: the floor block below appends to this key, and an
            # uninitialised key raises KeyError INSIDE the try — where the bare
            # `except Exception` converts it into `_snapshot_unavailable`, i.e. every member
            # drops to DEGRADED MODE. A missing dict key would have presented as "the daemon
            # is unreachable" fleet-wide, which is the most expensive possible disguise for a
            # typo. Latent rather than live only because the append is guarded on a daemon
            # that serves a floor, and no deployed daemon did yet.
            "society_floor": [],
            "society_floor_digest": None,
            "generation": None,
            "expires_at": None,
        }
        law = _unwrap_tool_result(
            client.call_tool("hestia_operating_law", {"session_id": session_id}))
        if isinstance(law, dict) and "_hestia_error" not in law:
            ident = law.get("identity")
            if isinstance(ident, dict) and isinstance(ident.get("role"), str):
                snap["role"] = ident["role"]
            if isinstance(law.get("law_hash"), str):
                snap["law_hash"] = law["law_hash"]
            grant = law.get("operator_grant")
            if isinstance(grant, dict):
                snap["operator_grant"] = grant
        scope = _unwrap_tool_result(
            client.call_tool("hestia_scope_status", {"plugin_id": plugin_id}))
        if isinstance(scope, dict) and "_hestia_error" not in scope:
            grants = scope.get("live_grants")
            if isinstance(grants, list):
                for g in grants:
                    p = g.get("path") if isinstance(g, dict) else None
                    if isinstance(p, str) and p.strip():
                        snap["scope_grants"].append(p.strip())
                        # ONE mapping for both grant channels (GPT #431 blocker 4;
                        # subsumes #430's inline fix): a live grant naming a repo root
                        # under the core-discovered workspace admits as the repo NAME;
                        # anything deeper keeps the faithful typed "path:" form; the core
                        # admits only that resolved boundary and descendants (R2) — a file
                        # grant must not front for its whole repo.
                        snap["in_scope"].append(_scope_entry_for_grant(p))
            # STANDING grants (Sprint F R1) — the durable, operator-promoted list the
            # daemon persists in its vault. Additive beside live_grants; absent on an
            # older daemon, in which case everything below is a no-op and the snapshot
            # is exactly the pre-R1 one.
            standing = scope.get("standing_grants")
            if isinstance(standing, list):
                for g in standing:
                    p = g.get("path") if isinstance(g, dict) else None
                    if isinstance(p, str) and p.strip():
                        snap["standing_grants"].append({
                            "path": p.strip(),
                            "expires_at": g.get("expires_at"),
                            "granted_by": g.get("granted_by"),
                            "reason": g.get("reason"),
                        })
                        snap["scope_grants"].append(p.strip())
                        snap["in_scope"].append(_scope_entry_for_grant(p))
            # CERTIFICATION, issued by the authority (Sprint F R1): the standing store's
            # monotonic generation ("WHICH policy is this copy") and the daemon's honor
            # horizon for it. Booleans are excluded deliberately — isinstance(True, int)
            # holds in Python, and a `true` here must not read as generation 1.
            gen = scope.get("generation")
            if isinstance(gen, int) and not isinstance(gen, bool):
                snap["generation"] = gen
            exp = scope.get("snapshot_expires_at")
            if isinstance(exp, int) and not isinstance(exp, bool):
                snap["expires_at"] = exp
            # THE SOCIETY FLOOR (dp, 2026-08-16) — paths every member of this society may
            # reach, served identically to all of them and additive to whatever this member
            # holds of its own: effective(m) = floor ∪ member(m), never a subtraction.
            #
            # Mapped through the SAME `_scope_entry_for_grant` the two grant channels use, so
            # a floor path admits by exactly the rule a granted path does — a repo root as a
            # repo-name grant, anything deeper as a boundary-scoped `path:` entry. A second mapping
            # here would be a second law for the same question, which is the drift this list
            # exists to prevent.
            #
            # Absent on an older daemon, in which case every line below is a no-op and the
            # snapshot is exactly the pre-floor one: a member talking to a daemon that has no
            # floor gets no floor, rather than an error or a guess.
            floor = scope.get("society_floor")
            if isinstance(floor, list):
                for f in floor:
                    p = f.get("path") if isinstance(f, dict) else None
                    if isinstance(p, str) and p.strip():
                        snap["society_floor"].append(p.strip())
                        snap["in_scope"].append(_scope_entry_for_grant(p))
            floor_digest = scope.get("society_floor_digest")
            if isinstance(floor_digest, str) and len(floor_digest) == 64:
                snap["society_floor_digest"] = floor_digest
        return snap
    except Exception as e:  # noqa: BLE001 — any failure is "unreachable"; the caller degrades
        _snapshot_unavailable(
            plugin_id, f"{type(e).__name__}:{getattr(e, 'errno', '')}:{str(e)[:120]}")
        return None


# ── COLLAPSED FROM THE SEATS (2026-08-25) ─────────────────────────────────────────────────
# `emit_attestation` lived as a byte-identical copy in BOTH the codex
# and kimi gates: 19/19 and 62/62 lines, matching line for line. Nothing flagged them,
# because the collapse ratchet can only see a seat overriding a name the engine ALREADY owns,
# and the engine never owned these. Two seats answering the same question with two bodies is
# the shape every drift incident so far has come out of; the copies were identical today only
# because nobody had edited one yet.
#
# THE SHIM BOUNDARY, stated once here because every later slice inherits it: the ENGINE owns
# the logic, the SEAT supplies its identity. Neither function is seat-specific — what was
# seat-specific was `HESTIA_PLUGIN_ID` and `_role_bridge()` closed over from module scope,
# which is exactly why the code could not be shared without being parameterised first. They
# are arguments now, and a seat that forgets to pass them gets a TypeError at the call rather
# than a plausible default attributing its acts to somebody else.


def emit_attestation(allows, denies, *, plugin_id, role_lct, endpoint=None):
    """Attest this gate's effective scope to the daemon, best effort.

    `plugin_id` and `role_lct` are REQUIRED and keyword-only. In the seat-local copies both
    were read from module scope, so the identity a record carried was decided by which file
    the function happened to live in. Making them arguments is what let one body serve every
    seat; keyword-only is what stops the two ever being passed in the wrong order, since they
    are both strings and a silent swap would attribute the attestation to a role.
    """
    endpoint = endpoint or os.environ.get("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")

    def post(payload, timeout, hdrs=None):
        req = urllib.request.Request(
            endpoint, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream", **(hdrs or {})})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), r.headers.get("mcp-session-id")

    _, sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                              "clientInfo": {"name": "hestia-gate-attest", "version": "1"}}}, 1.0)
    h = {"mcp-session-id": sid} if sid else {}
    post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, 0.4, h)
    # `hestia_request_witness` is an ATTRIBUTED append: it refuses an unconnected caller,
    # because what lands on the chain must carry a proven WHO and not only caller-supplied
    # data. Connect first and pass the session, or the attestation is silently refused —
    # which is exactly how the first cut of this failed.
    raw, _ = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                   "params": {"name": "hestia_connect",
                              "arguments": {"plugin_id": plugin_id,
                                            "host_agent": plugin_id,
                                            # DECLARE THE ROLE ON CONNECT (dp, 2026-07-28:
                                            # "kimi's member alias still shows unmeasured
                                            # with over 3k actions"). This gate has always
                                            # KNOWN its role — it writes the role bridge
                                            # into the attestation payload below — and never
                                            # told the daemon on connect, so the session
                                            # defaulted to role:constellation:member and the
                                            # attestation landed on a grain the member does
                                            # not act under. Acts on one grain, the decisions
                                            # governing them on another, and NEITHER can score
                                            # conduct. The capability to declare arrived with
                                            # the connect-echoes-role work; this is the caller
                                            # that never started using it.
                                            "role": role_lct,
                                            "instance_name": "gate-attest"}}}, 1.5, h)
    sess = None
    for line in raw.decode("utf-8", "replace").splitlines():
        if line.startswith("data: {"):
            try:
                pl = json.loads(line[6:])
                if "result" in pl:
                    sess = json.loads(pl["result"]["content"][0]["text"]).get("sessionId")
            except Exception:
                pass
    if not sess:
        return
    post({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
          "params": {"name": "hestia_request_witness",
                     "arguments": {"session_id": sess,
                                   "event_type": "scope_attestation",
                                   "event_data": {
                                       "plugin_id": plugin_id,
                                       "role_lct": role_lct,
                                       "allows": allows,
                                       "denies": denies,
                                       "attested_by": "plugin-gate:" + plugin_id,
                                   }}}}, 1.5, h)

# ── Gate-self surface (slice 3: one body per behaviour, seat context as arguments) ──────────
# codex and kimi carried these five as byte-identical or near-identical copies, each closing
# over module scope (HESTIA_PLUGIN_ID, _EVENT, IDENTITY, _SNAPSHOT_ROLE, the tally knobs), so
# what a witness or a claim carried was decided by which file the function happened to live
# in. Same rule emit_attestation established: seat context is REQUIRED and keyword-only —
# most of these values are strings, and a silent positional swap would attribute a witness to
# a filename. The seats keep signature-identical thin wrappers that pass their own context;
# the wrappers are the adapter, this is the law.


def role_bridge(*, snapshot_role, identity_path):
    """Attribution-only: the role string that witnesses and connects carry. Never used to
    widen reach.

    Resolution order, unchanged from the seat-local copies this replaces: the daemon's
    session-resolved role (`hestia_operating_law` identity.role) wins when the snapshot
    answered, because the alternative is a member-writable file deciding attribution. The
    identity.json read remains ONLY as the daemon-absent fallback, where the alternative is
    silently changing the witness grain mid-train.
    """
    if isinstance(snapshot_role, str) and snapshot_role.startswith("role:"):
        return snapshot_role
    try:
        r = json.load(open(identity_path, encoding="utf-8")).get("role")
        if isinstance(r, str) and r.startswith("role:"):
            return r
    except Exception:
        pass
    return "role:constellation:member"


def gate_self_call(tool, args, *, plugin_id, role, client_name, host_session_id=None):
    """One short daemon round trip for a gate-self event: initialize, connect (session-bound),
    one tools/call. Returns the unwrapped result dict, or None on ANY failure.

    Never raises and stays inside a ~2.5s budget: the fail-open engines would treat a hook
    that hangs past its clamp as an allow, so a gate-self exchange that stalls would be
    strictly worse than a refusal. Callers treat None as refusal (writes) or best-effort
    loss (witnesses).

    `host_session_id`, when the caller has one, is threaded into the connect so the
    gate-self session this call mints joins to the per-wake session the outcome rows carry."""
    endpoint = os.environ.get("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")

    def post(payload, hdrs, timeout):
        req = urllib.request.Request(
            endpoint, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream", **hdrs})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), r.headers.get("mcp-session-id")

    def unwrap(raw):
        """The result payload of a tools/call: structuredContent, or the content[0] text JSON —
        and the body may be plain JSON or SSE-framed (`data: {...}` lines)."""
        for line in raw.decode("utf-8", "replace").splitlines():
            line = line.strip()
            if not (line.startswith("{") or line.startswith("data: {")):
                continue
            try:
                pl = json.loads(line[line.index("{"):])
            except Exception:
                continue
            res = pl.get("result")
            if not isinstance(res, dict):
                continue
            sc = res.get("structuredContent")
            if isinstance(sc, dict):
                return sc
            content = res.get("content") or []
            if content and isinstance(content[0], dict):
                try:
                    d = json.loads(content[0].get("text") or "{}")
                    return d if isinstance(d, dict) else None
                except Exception:
                    return None
        return None

    try:
        _, sid_hdr = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                      "clientInfo": {"name": client_name,
                                                     "version": "1"}}}, {}, 0.8)
        h = {"mcp-session-id": sid_hdr} if sid_hdr else {}
        post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, h, 0.4)
        connect_args = {"plugin_id": plugin_id,
                        "host_agent": plugin_id,
                        "role": role,
                        "instance_name": "gate-self"}
        if host_session_id:
            connect_args["host_session_id"] = host_session_id
        raw, _ = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                       "params": {"name": "hestia_connect",
                                  "arguments": connect_args}}, h, 0.8)
        conn = unwrap(raw)
        sess = conn.get("sessionId") if conn else None
        if not sess:
            return None  # an unconnected witness/claim is refused by the daemon anyway
        args = dict(args)
        args.setdefault("session_id", sess)
        raw, _ = post({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": tool, "arguments": args}}, h, 0.9)
        return unwrap(raw)
    except Exception:
        return None


def witness_gate_self(event_type, marker, tool_name, rule=None, *,
                      plugin_id, role, gate_path, client_name, host_session_id=None):
    """Record a governance-surface event as its OWN class — `gate_self_read` for a permitted
    read, `gate_self_access` (appealable) for a refused write. The two stay distinct so an
    alert on the refusal keeps its meaning. Best effort: a failed record never changes the
    decision — the daemon's health is not a precondition for reading one's own law, and the
    deny already happened locally."""
    return gate_self_call("hestia_request_witness", {
        "event_type": event_type,
        "event_data": {"plugin_id": plugin_id,
                       "tool_name": tool_name,
                       "marker": marker,
                       "rule": rule,
                       "gate_path": gate_path,
                       "severity": "record" if event_type == "gate_self_read" else "escalate",
                       "role_lct": role}},
        plugin_id=plugin_id, role=role, client_name=client_name,
        host_session_id=host_session_id) is not None


def claim_self_write(marker, tool_name, attempted, *,
                     plugin_id, role, client_name, host_session_id=None):
    """Ask ONCE whether a human has already approved this exact (member, marker) write.
    Returns (verdict, detail, escalation_id, how_to_decide); only 'approved' permits.

    Never waits. The first attempt is refused and the refusal opens an escalation; a human
    decides out of band; the member RE-ISSUES the write and the second attempt claims the
    approval. Every failure — unreachable, malformed, a daemon with no escalation channel —
    is a refusal: a daemon that cannot answer must not be a way to get a governance write
    through."""
    claim_args = {
        "plugin_id": plugin_id,
        "role": role,
        "tool_name": tool_name,
        "marker": marker,
        # `reason` carries the ATTEMPTED ACT, not a rationale: an auto-opened escalation HAS no
        # stated why — the member did not choose to escalate; the gate opened it on a refused
        # write. Presenting the act as though it were a rationale would look like the member had
        # explained itself. A member that wants to state a why opens the escalation itself.
        "reason": attempted or f"{tool_name} -> {marker}",
        "detail": ("Auto-opened by the gate on a refused write; the member stated no rationale "
                   "because it did not choose to escalate. Approving authorises this one write."),
    }
    # The claimed-row join key (reply-2005/reply-2006, 2026-08-12): of the three session-id
    # namespaces in a claim window, only the per-wake host session appears on the outcome rows
    # an auditor joins from — the gate-self connect session above joins only to gate witnesses.
    # Sent only when in hand: the daemon writes explicit null, and a fabricated placeholder
    # would be a lie in the exact record used to argue about who authorised what.
    if host_session_id:
        claim_args["host_session_id"] = host_session_id
    r = gate_self_call("hestia_gate_escalation_claim", claim_args,
                       plugin_id=plugin_id, role=role, client_name=client_name,
                       host_session_id=host_session_id)
    if not isinstance(r, dict):
        return "unreachable", "no answer from the daemon — refused", None, None
    # BOTH flags, and the daemon owns both — two places deciding what "approved" means is how
    # they come to disagree, so the hook re-derives nothing.
    if r.get("claimed") is True and r.get("permits_write") is True:
        who = r.get("decided_by") or "a human"
        via = r.get("decided_via") or "unknown-channel"
        return ("approved",
                f"claimed an approval from {who} via {via} (single use, now spent)", None, None)
    esc_id = r.get("escalation_id")
    if not esc_id:
        # An old daemon answers {} to a tool it does not know — which must not permit a write by
        # failing to understand the question, but also cannot open an escalation. Say which.
        why = r.get("error") or "this daemon has no escalation channel (is it upgraded?)"
        return "no-channel", f"refused, and NO escalation was opened — {why}", None, None
    return ("escalated", "refused; escalation opened for out-of-band decision",
            esc_id, r.get("how_to_decide") or f"hestia gate approve {esc_id}")


def tally_scope(allowed, *, tally_dir, tally_path, attest_every, plugin_id, role_lct):
    """Count this decision; emit an attestation when the window closes."""
    try:
        os.makedirs(tally_dir, exist_ok=True)
        try:
            t = json.load(open(tally_path))
        except Exception:
            t = {"allows": 0, "denies": 0}
        t["allows" if allowed else "denies"] += 1
        if t["allows"] + t["denies"] >= attest_every:
            emit_attestation(t["allows"], t["denies"],
                             plugin_id=plugin_id, role_lct=role_lct)
            t = {"allows": 0, "denies": 0}
        json.dump(t, open(tally_path, "w"))
    except Exception:
        pass  # accounting must never change a decision
