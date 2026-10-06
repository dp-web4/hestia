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
#
# ONE-GATE STAGE C: THE CALLER'S DEADLINE. Every helper the common gate calls takes
# `deadline=` (an absolute `time.monotonic()` bound): `query_society_safety`,
# `fetch_policy_snapshot` (both attempts and the pause between them), `gate_self_call`,
# `witness_gate_self`, `claim_self_write`, `tally_scope` and `record_decision`. With a deadline,
# no request STARTS after it, and the two module budgets below do not apply: the deadline is the
# shim's, derived from its harness's registered timeout minus a margin (plan §4), so it is always
# strictly below what the harness enforces. `deadline=None` (the default) is today's behaviour
# exactly, for callers that pass none (SAGE's being gateway imports this module).
#
# THE PER-REQUEST CAP (REQUEST_TIMEOUT_S, 5 s) applies only without a caller deadline. Measured
# 2026-10-01: a never-seen member's first connect costs 4.6-5.1 s, so the cap turned a slow but
# ALIVE daemon into a no-verdict even inside a 12 s deadline. A caller deadline already bounds
# every request by what is left of it, so a second, smaller bound adds only that false denial.
TOTAL_BUDGET_MS = int(_num_env("HESTIA_PRE_TOTAL_BUDGET_MS", 4000, int))
REQUEST_TIMEOUT_S = float(_num_env("HESTIA_PRE_REQUEST_TIMEOUT_S", 5.0, float))
#: `_McpHttp(request_cap=...)` sentinel: the module's REQUEST_TIMEOUT_S, read at request time.
DEFAULT_REQUEST_CAP = "default"
MAX_POLLS = 5
MIN_POLL_SLEEP_MS = 50
PROTOCOL_VERSION = 1
DEFAULT_HESTIA_HOME = Path.home() / ".hestia"

#: The capability a member names in `gate_capabilities` at `hestia_connect` when it holds
#: `hestia_gate_escalation_corroborate` — the only door that adds a factor to an escalation.
#: The daemon's invitation pool reads exactly this string (`handler.rs REVIEW_CAPABILITY`,
#: #1050); the two spellings are pinned together by
#: `hestia_gate_mechanism_test.py::the_review_capability_spelling_matches_the_daemons`.
REVIEW_CAPABILITY = "escalation-review:v1"

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
    # SUPERSEDED (#1169, GPT review of ca5f394): begin_action refused this invocation because a
    # reclaim re-delivered its permit to ANOTHER invocation. Not a policy verdict and not an infra
    # failure -- an integrity fence. allow=False like any refusal, and a caller must treat it as a
    # stop in EVERY rollout mode: a warn-rollout that lets it through runs this call beside its
    # replacement. Keyed on the daemon's machine-readable code, never on message text.
    superseded: bool = False


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
    def __init__(self, endpoint: str, deadline: float,
                 request_cap: Any = DEFAULT_REQUEST_CAP) -> None:
        self.endpoint = endpoint
        self.session_id: Optional[str] = None
        self.next_id = 0
        self.deadline = deadline  # monotonic time after which we give up
        # None: no per-request cap beyond the deadline (a caller deadline, stage C);
        # DEFAULT_REQUEST_CAP: REQUEST_TIMEOUT_S; a number: that many seconds.
        self.request_cap = request_cap

    def _cap(self) -> Optional[float]:
        if self.request_cap is None:
            return None
        if self.request_cap == DEFAULT_REQUEST_CAP:
            return REQUEST_TIMEOUT_S
        return float(self.request_cap)

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
        cap = self._cap()
        timeout = max(0.01, remaining) if cap is None else min(cap, max(0.01, remaining))
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


#: A shell act's `target` is the command itself, bounded for chain hygiene. The bound is the
#: one the claude Post-hook witness used for the same field for five weeks (240).
TARGET_MAX = 240

#: The same give-away shapes the daemon masks in `attempted` (handler.rs `redact_secrets`).
#: Shape-based and conservative on purpose: mask the VALUE after a credential-ish flag or
#: assignment, keep the key so the reader still learns which knob was set, and leave the
#: rest legible — the point of storing the command is that a human can read it.
_MASKED_KEYS = ("password", "passwd", "secret", "token", "api_key", "apikey", "api-key",
                "auth", "authorization", "bearer", "credential", "private_key", "passphrase",
                "access_key", "session_key", "client_secret")


def _mask_credential_values(command: str) -> str:
    """Defence in depth on the SENDING side: the daemon scrubs whatever it is handed, and
    the sender is closer to the payload. Same two passes as the daemon: `--token=VALUE` /
    `TOKEN=VALUE` keep the key and mask the value; `--token VALUE` masks the next token.
    Whitespace collapses to single spaces, as the daemon's pass does."""
    first = []
    for tok in command.split():
        if "=" in tok:
            key = tok.split("=", 1)[0]
            if any(s in key.lstrip("-").lower() for s in _MASKED_KEYS):
                first.append(key + "=***")
                continue
        first.append(tok)
    out, mask_next = [], False
    for tok in first:
        if mask_next and not tok.startswith("-"):
            out.append("***")
            mask_next = False
            continue
        mask_next = tok.lstrip("-").rstrip(":").lower() in _MASKED_KEYS
        out.append(tok)
    return " ".join(out)


#: Shapes that plausibly CARRY a credential: key material and its filenames, ssh/gpg config
#: trees (a path can be the credential), http auth, and the flag/env spellings that appear in
#: real commands. Moved here from the claude-code shim's `_attempted_summary` at the one-gate
#: stage C cutover (kimi NOT-SAME review of #185 found seven of these shapes reaching the
#: chain verbatim), so EVERY seat's `attempted` text is held to the strongest rule any seat
#: had — align upward, no seat loses protection in the cutover.
#:
#: Substring on a lowered string, no regex over attacker-shaped text. Asymmetric on purpose:
#: a false positive costs one vague escalation body; a false negative is a credential in the
#: permanent, hash-chained record (which is easier to read and harder to expunge than the
#: file a deny protected). The over-match bound lives in attempted_summary_test.py.
_CREDENTIAL_SHAPES = (
    # key material and its filenames
    "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", ".pem", ".p12", ".pfx",
    "begin rsa private key", "begin openssh private key", "begin private key",
    "begin ec private key", "begin certificate",
    # ssh / gpg config trees
    "/.ssh", ".ssh/", "/.gnupg", ".netrc", ".pgpass", ".htpasswd",
    # http auth
    "authorization:", "authorization ", "bearer ", "x-api-key", "proxy-authorization",
    # generic credential words, and their flag/env spellings
    "password", "passwd", "passphrase", "credential", "sec" "ret", "api_key", "apikey",
    "access_key", "access-key", "private_key", "private-key", "client_sec" "ret",
    "token=", "_token", "auth_token", "session_token", "refresh_token",
    ".env", "dotenv",
)

#: The bounds the claude-code seat held for five weeks (#185, #941): a command body is cut at
#: 220 chars and says so; a path keeps its TAIL (the filename a reviewer needs) and marks the
#: head cut inside the bound, so a cut absolute path never reads as a relative one.
ATTEMPTED_MAX = 220
ATTEMPTED_PATH_MAX = 140


def credential_shaped(text: str) -> bool:
    """Does this text plausibly carry a credential? One helper for the command AND the path
    branch, so the two cannot drift (the inconsistency #185 finding 2 named)."""
    low = text.lower()
    return any(shape in low for shape in _CREDENTIAL_SHAPES)


def attempted_summary(tool_name: str, tool_input: Any, *, command: Optional[str] = None,
                      targets: Optional[list] = None) -> str:
    """WHAT was attempted, in one bounded, self-censoring line, for the record and for the
    human who rules on an escalation (dp 2026-08-03: "they don't tell me what i'm approving").

    The caller (the common gate) passes the act's command text, already normalised across
    harness spellings, and any targets it parsed from a patch body. Two layers mask:
      1. HERE, on the sending side: a credential-SHAPED command or path is withheld whole,
         with its length stated (`[REDACTED — ...; N chars withheld ...]`); otherwise the
         value after a credential-ish key is masked (`_mask_credential_values`).
      2. The daemon (`handler.rs`) masks `key=value` / `--key value` again on receipt.
    Only layer 1 covers key files, ssh/gpg paths, PEM blocks and credential-shaped paths."""
    if not isinstance(tool_input, dict):
        return f"{tool_name} (no inspectable input)"
    if isinstance(command, str):
        s = " ".join(command.split())
        if credential_shaped(s):
            return (f"{tool_name} [REDACTED — names a credential-shaped token; "
                    f"{len(s)} chars withheld rather than copied into the record]")
        s = _mask_credential_values(s)
        return f"{tool_name}: {s[:ATTEMPTED_MAX]}" + (" …" if len(s) > ATTEMPTED_MAX else "")
    paths = [tool_input.get(k) for k in ("file_path", "path", "notebook_path", "url")]
    paths = [p for p in paths if isinstance(p, str) and p][:1] or [
        t for t in (targets or []) if isinstance(t, str) and t]
    if paths:
        joined = ", ".join(paths)
        if credential_shaped(joined):
            return (f"{tool_name} [REDACTED — the target is a credential-shaped path; "
                    f"{len(joined)} chars withheld rather than copied into the record]")
        cut = ATTEMPTED_PATH_MAX - 1
        return f"{tool_name} -> " + (
            joined if len(joined) <= ATTEMPTED_PATH_MAX else "…" + joined[-cut:])
    if isinstance(tool_name, str) and tool_name.startswith("mcp__") and tool_input:
        try:
            s = " ".join(json.dumps(tool_input, sort_keys=True, default=str).split())
        except Exception:  # noqa: BLE001
            s = " ".join(str(tool_input).split())
        if credential_shaped(s):
            return (f"{tool_name} [REDACTED — names a credential-shaped token; "
                    f"{len(s)} chars withheld rather than copied into the record]")
        s = _mask_credential_values(s)
        return f"{tool_name}: {s[:ATTEMPTED_MAX]}" + (" …" if len(s) > ATTEMPTED_MAX else "")
    return f"{tool_name} (no command or path in input)"


def _shell_target(command: str) -> str:
    """The command, masked and bounded — not its first word.

    Until 2026-09-07 the chain feed showed every shell act's arguments, because the claude
    Post hook opened a second action whose `target` was the full command ("for forensic
    readability in the chain feed"). #977 made the outcome close the action the gate
    authorized instead — the right act identity — and the outcome row inherited THIS
    function's target, which was `cmd.split()[0]`. Every argument vanished from the feed in
    one deploy and the operator noticed within a day. The daemon's own comment on the
    policy row says `target` "already carries the command for Bash/Shell by overloading";
    this makes that true at the one place every seat's shell target is made."""
    masked = _mask_credential_values(command.strip())
    return masked if len(masked) <= TARGET_MAX else masked[:TARGET_MAX - 3] + "..."


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
            return _shell_target(cmd)
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


#: The daemon's begin_action refusal code for an invocation whose permit a reclaim re-delivered
#: to another invocation (handler.rs `tool_begin_action`, #1169). Matched on the CODE, never text.
INVOCATION_SUPERSEDED = "hestia.invocation_superseded"

#: The value a HOOK passes as `supersession=` to `claim_self_write` (claim argument `supersession`,
#: gate_escalation.rs `SUPERSESSION_HARD_STOP`) to declare that it stops a superseded invocation in
#: every rollout mode. The daemon never reclaims a spend whose seat did not declare it. There is
#: deliberately no default here: the declaration must ship in the same file as the stop that makes
#: it true, so a hook that lacks the stop cannot inherit the declaration from this library.
SUPERSESSION_HARD_STOP = "hard_stop"


def _superseded(err: dict) -> SafetyVerdict:
    """The refusal for a SUPERSEDED invocation (#1169): an unconditional stop, never a no-verdict.
    Not recorded as gate unavailability -- the daemon answered, and answered exactly. NEVER raises."""
    data = err.get("data") if isinstance(err.get("data"), dict) else {}
    esc = data.get("escalation_id") or "?"
    msg = (f"hestia: deny [invocation-superseded] — this call's approval was re-delivered to another "
           f"invocation of the same act by a reclaim of escalation {esc}, so THIS invocation may not "
           f"run. This is an integrity fence, not a policy verdict and not a daemon failure: it stops "
           f"the call in every rollout mode, so the act runs at most once. Do not retry this call; "
           f"the invocation that reclaimed the approval carries it.")
    return SafetyVerdict(allow=False, decided=False, message=msg, cause="superseded",
                         kind="deny", superseded=True)


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
        record_gate_unavailable(plugin_id, tool_name, cause, detail, home=_telemetry_home())
    except Exception:
        pass
    return SafetyVerdict(allow=False, decided=False, message=msg, cause=cause)


def _telemetry_home() -> str:
    """Where the availability series is written: the launcher's explicit HESTIA_HOME (the one
    locator, #944) when set, else the home this module resolved at import. Before stage C it was
    always the latter, so a fixture or a seat with its own HESTIA_HOME wrote into ~/.hestia."""
    return os.environ.get("HESTIA_HOME") or str(DEFAULT_HESTIA_HOME)


def _witness_core():
    """The outcome witness's shared core, beside this module in the installed engine set."""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import hestia_witness_core  # type: ignore
    return hestia_witness_core


def correlation_key(event) -> Optional[str]:
    """The key under which this call's authorized action is cached for the outcome witness.

    The rule is hestia_witness_core's — ONE rule for the Pre and the Post side of every harness
    (findings/per-harness-witness-drift-2026-09-28.md). NEVER raises: a gate computing it inside
    its decision path must not turn a missing core into a fail-closed deny; None just means the
    witness will record this act cold, and say so on the row."""
    try:
        return _witness_core().correlation_key(event)
    except Exception:  # noqa: BLE001
        return None


def _bound(deadline: Optional[float], budget_s: float) -> tuple:
    """(absolute deadline, request cap) for one helper call. A caller deadline is used as given
    and lifts the per-request cap (see REQUEST_TIMEOUT_S above); without one, the helper's own
    budget and the default cap apply, exactly as before stage C."""
    if deadline is not None:
        return float(deadline), None
    return time.monotonic() + budget_s, DEFAULT_REQUEST_CAP


def _client(endpoint: str, deadline: float, cap: Any):
    """`_McpHttp` for one helper call. The default cap constructs it exactly as before stage C
    (two arguments), so a caller or test that substitutes `_McpHttp` keeps working."""
    if cap == DEFAULT_REQUEST_CAP:
        return _McpHttp(endpoint, deadline)
    return _McpHttp(endpoint, deadline, request_cap=cap)


def query_society_safety(event: dict, *, plugin_id: str, host_agent: str,
                         plugin_version: Optional[str] = None,
                         host_agent_version: Optional[str] = None,
                         host_session_id: Optional[str] = None,
                         correlation_key: Optional[str] = None,
                         deadline: Optional[float] = None) -> SafetyVerdict:
    """Obtain the daemon's society-safety verdict for a write/exec act, IN-PROCESS.

    Replaces "spawn the claude gate as a subprocess" for a thin shim. Returns a SafetyVerdict;
    NEVER raises; on any failure/malformed/missing-session yields allow=False, decided=False.

    `plugin_version` / `host_agent_version` are the shim's REAL version facts and are omitted
    from the connect payload when unknown — the mechanism does not manufacture provenance (GPT #3).

    `correlation_key` (the caller's `correlation_key(event)`): when given, the action this call
    begins is cached under it for the outcome witness to CLOSE (#977). This used to live in
    claude-code's gate alone, so on every other harness the witness could only record cold —
    kimi 0 of 37 warned acts closed, codex 0 of 1. The cache is evidence plumbing: it is written
    after the verdict exists and can never change it.

    `deadline` (stage C): the caller's absolute `time.monotonic()` bound. No request starts after
    it, and running out is a no-verdict (cause "timeout"). None keeps the module budget.
    """
    tool_name = event.get("tool_name") or "?"
    tool_input = event.get("tool_input") or {}
    try:
        endpoint = _discover_endpoint()
        if endpoint is None:
            return _no_verdict(plugin_id, tool_name, "refused", "no daemon endpoint discovered")
        deadline, cap = _bound(deadline, TOTAL_BUDGET_MS / 1000.0)
        if deadline - time.monotonic() <= 0:
            return _no_verdict(plugin_id, tool_name, "timeout",
                               "the caller's deadline was exhausted before the society check")
        target = _extract_target(tool_input, tool_name)
        client = _client(endpoint, deadline, cap)
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
        # EXECUTION EVIDENCE (#1169): this begin runs BEFORE the tool, so the daemon recording
        # "invocation K reached begin_action" is how it knows a delivered permit was used -- and
        # so never reclaims it for a repeat of the same command.
        if correlation_key:
            begin_args["correlation_key"] = correlation_key
        begin = _unwrap_tool_result(client.call_tool("hestia_begin_action", begin_args))
        if "_hestia_error" in begin:
            _err = begin.get("_hestia_error")
            if isinstance(_err, dict) and _err.get("code") == INVOCATION_SUPERSEDED:
                return _superseded(_err)  # a fence, not a no-verdict: never downgradable to warn
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
        if correlation_key:
            try:
                _witness_core().cache_authorized_action(correlation_key, action_id, tool_name)
            except Exception:  # noqa: BLE001 — never let the cache touch the verdict
                pass
        return verdict
    except (urllib.error.URLError, TimeoutError, socket.timeout) as e:
        return _no_verdict(plugin_id, tool_name, _unavailable_cause(e),
                           f"network: {type(e).__name__}")
    except Exception as e:  # noqa: BLE001 — FAIL-CLOSED: any unexpected error is no-verdict, never allow
        return _no_verdict(plugin_id, tool_name, "unknown", f"unexpected: {type(e).__name__}")


# ── TOMBSTONE: the Sprint E deny recorder (one-gate stage C) ───────────────────────────────────
# `witness_decision_unified` and its `~/.hestia/telemetry/gate-denies-<member>.jsonl` fallback
# are DELETED, not kept beside their successor. They recorded refusals only, read any outer RPC
# `result` as delivered (a refused verdict and a failed chain append both arrive that way,
# handler.rs `call_tool`), and guessed `~/.hestia` when HESTIA_HOME was unset (#944). Since stage
# C every seat's gate is `hestia_single_gate.decide()`, which records EVERY final verdict through
# `record_decision` below — receipt-validated, joined by `action_id` and `correlation_key`, with
# its uncommitted fallback only under an explicit HESTIA_HOME. Two recorders were two rows per
# refusal and two charges (plan §2, finding 4). One remains.


def _loaded_core_digest():
    try:
        import sys as _s
        _c = _s.modules.get("hestia_gate_" + "core")
        return getattr(_c, "_CORE_DIGEST", None) if _c is not None else None
    except Exception:
        return None


# ── ONE decision witness, receipt-validated (one-gate stage A) ──────────────────────────────────
# docs/one-gate-convergence-plan.md. `record_decision` is the recorder the common orchestrator
# calls for EVERY final verdict (and, since stage C, the only decision recorder: the Sprint E
# refusal recorder is tombstoned above). It differs from that predecessor in the one property C11
# turns on:
#
#   COMMITTED MEANS A RECEIPT. The predecessor returned True when the reply had an outer
#   `result`. Every daemon tool error — a refused verdict, a failed chain append — arrives as a
#   successful MCP result carrying `_hestia_error` (handler.rs `call_tool`), so that check reads a
#   refusal as delivered. Here a decision is committed ONLY when the daemon returns a
#   `witnessEntryHash` (a chain hash: 64 lowercase hex) AND the receipt names every input it acted
#   on: the verdict, its event type, and the join keys that were sent. A daemon that ignored a key
#   (one predating this contract) cannot produce that receipt, so it reads as not committed —
#   the same rule the outcome witness keeps (hestia_witness_core.witness_one, #1149).
#
# Verdict semantics live on the daemon (core/src/server/decision_witness.rs): allow → its own
# event `policy_allow`, no reputation delta; warn/deny → `policy_decision`, charged as before; a
# verdict the daemon already witnessed for the same action and member → that row, not a second.

DECISION_VERDICTS = ("allow", "warn", "deny")
#: The daemon's event type per verdict. The receipt must name the one this verdict lands as.
DECISION_EVENT_TYPES = {"allow": "policy_allow", "warn": "policy_decision", "deny": "policy_decision"}
#: The single-shot budget when the caller passes no deadline (the deployed recorder's 1.5 s).
DECISION_WITNESS_DEFAULT_BUDGET_S = 1.5


@dataclass(frozen=True)
class DecisionReceipt:
    """What `record_decision` can PROVE about one decision record.

    status:
      "committed"   the daemon returned a receipt naming this decision; `entry_hash` is its row;
      "refused"     the daemon RULED (a structured `_hestia_error`) — nothing was committed;
      "ambiguous"   it answered, but not with a usable receipt (isError, JSON-RPC error, empty,
                    a missing/malformed hash, a receipt that does not name the inputs);
      "unreachable" no endpoint, no connection, or no time left to ask.
    Only "committed" is evidence. The other three are equally NOT evidence; they differ only in
    what an operator should look at.
    """
    status: str
    entry_hash: Optional[str] = None
    event_type: Optional[str] = None
    deduplicated: bool = False      # the daemon answered with its own existing row for this act
    detail: str = ""
    fallback_path: Optional[str] = None  # where the uncommitted record was kept, if anywhere

    @property
    def committed(self) -> bool:
        return self.status == "committed"


def _is_chain_hash(v: Any) -> bool:
    return (isinstance(v, str) and len(v) == 64
            and all(c in "0123456789abcdef" for c in v))


def _classify_decision_reply(rpc: Any) -> tuple:
    """("ok"|"ruled"|"ambiguous", payload) — the outcome witness's three-kind rule, ONE rule.

    Delegates to hestia_witness_core._classify_reply so the decision and the outcome halves of
    the join can never disagree about what the daemon said. If the core cannot be loaded, the
    reply is unclassifiable and therefore not a receipt."""
    try:
        return _witness_core()._classify_reply(rpc)
    except Exception as e:  # noqa: BLE001
        return "ambiguous", {"why": f"reply classifier unavailable: {type(e).__name__}"}


def _receipt_problem(payload: dict, *, decision: str, action_id: Optional[str],
                     correlation_key: Optional[str]) -> Optional[str]:
    """None when `payload` is a receipt for exactly this decision; else what is wrong with it."""
    if not _is_chain_hash(payload.get("witnessEntryHash")):
        return "no chain-hash witnessEntryHash in the reply"
    if payload.get("decision") != decision:
        return f"receipt names decision {payload.get('decision')!r}, sent {decision!r}"
    if payload.get("eventType") != DECISION_EVENT_TYPES[decision]:
        return (f"receipt names event {payload.get('eventType')!r}, "
                f"expected {DECISION_EVENT_TYPES[decision]!r}")
    if action_id is not None and payload.get("actionId") != action_id:
        return "receipt does not name the action_id that was sent"
    if correlation_key is not None and payload.get("correlationKey") != correlation_key:
        return "receipt does not name the correlation_key that was sent"
    return None


def _decision_fallback_path(plugin_id: str) -> Optional[Path]:
    """The uncommitted-decision log. Only under an EXPLICIT HESTIA_HOME: no locator means no
    authority root, and this path never guesses one (#944; #1139 review)."""
    home = os.getenv("HESTIA_HOME")
    if not home:
        return None
    safe = "".join(c if (c.isalnum() or c in "-_.") else "-" for c in (plugin_id or "unknown"))
    return Path(home) / "telemetry" / f"gate-decisions-{safe}.jsonl"


def _keep_uncommitted(plugin_id: str, record: dict, receipt: DecisionReceipt) -> DecisionReceipt:
    """Keep an uncommitted decision where an operator can find it. Never raises, and never turns
    the record into evidence: the returned receipt keeps its non-committed status."""
    path = _decision_fallback_path(plugin_id)
    if path is None:
        return receipt
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({**record, "witness_status": receipt.status,
                                 "witness_detail": receipt.detail}, default=str) + "\n")
    except Exception:  # noqa: BLE001
        return receipt
    return DecisionReceipt(status=receipt.status, detail=receipt.detail,
                           fallback_path=str(path))


def record_decision(client_or_none, *, plugin_id: str, decision: str, rule: str,
                    tool_name: str, target: Optional[str], session_id: Optional[str],
                    verdict_available: bool, attempted_summary: str,
                    action_id: Optional[str] = None,
                    correlation_key: Optional[str] = None,
                    deadline: Optional[float] = None) -> DecisionReceipt:
    """Witness ONE final gate decision — allow, warn or deny — and say whether it COMMITTED.

    `client_or_none`: an initialized `_McpHttp` to reuse, or None to open a single-shot session.
    `action_id`: the action the gate began (query_society_safety's verdict.action_id), so the
      decision row joins the outcome row; when the daemon already witnessed this very verdict for
      this action, the receipt is that row (`deduplicated=True`).
    `correlation_key`: `correlation_key(raw_event)` — the core's Pre/Post key (C13), computed by
      the caller from the RAW harness event, carried onto the row.
    `deadline`: an absolute `time.monotonic()` bound; no request starts after it. The caller's
      one invocation deadline (stage B) passes straight through — this helper mints no time.

    Returns a DecisionReceipt; `.committed` is True only on a receipt that names this decision.
    NEVER raises. Never changes the caller's verdict — what to DO with an uncommitted permit is
    the orchestrator's decision (C11: a consequential allow/warn becomes gate.evidence_uncommitted).
    """
    record = {
        "plugin_id": plugin_id,
        "decision": decision,
        "rule": (rule or "")[:300],
        "tool_name": tool_name or "",
        "target": target,
        "session_id": session_id,
        "verdict_available": bool(verdict_available),
        "core_digest": _loaded_core_digest(),
        "attempted": attempted_summary,
        "action_id": action_id,
        "correlation_key": correlation_key,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    if decision not in DECISION_VERDICTS:
        # A verdict the daemon would refuse is refused here, before any wire call: there is no
        # fourth verdict to witness, and asking would only spend the caller's deadline.
        return _keep_uncommitted(plugin_id, record, DecisionReceipt(
            status="refused", detail=f"not a final verdict: {decision!r}"))
    try:
        end = deadline if deadline is not None else (
            time.monotonic() + DECISION_WITNESS_DEFAULT_BUDGET_S)
        if end - time.monotonic() <= 0:
            return _keep_uncommitted(plugin_id, record, DecisionReceipt(
                status="unreachable", detail="deadline exhausted before the witness call"))
        client = client_or_none
        if client is None:
            endpoint = _discover_endpoint()
            if endpoint is None:
                return _keep_uncommitted(plugin_id, record, DecisionReceipt(
                    status="unreachable", detail="no daemon endpoint discovered"))
            client = _client(endpoint, end,
                             None if deadline is not None else DEFAULT_REQUEST_CAP)
            if "result" not in client.initialize():
                return _keep_uncommitted(plugin_id, record, DecisionReceipt(
                    status="unreachable", detail="initialize failed"))
            client.initialized()
        args: dict = {
            "plugin_id": plugin_id,
            "decision": decision,
            "adjudicator": f"plugin-gate:{plugin_id}",
            "reason": (rule or "")[:300],
            # The rule id rides its own key (handler.rs reads `rule_id` into the row AND the
            # reputation delta); the deployed recorder sends it only inside `reason`.
            "rule_id": (rule or "")[:300],
            "verdict_available": bool(verdict_available),
            "tool_name": tool_name or "",
            "target": target,
            "session_id": session_id,
            "attempted": attempted_summary,
            "core_digest": record["core_digest"],
        }
        if action_id is not None:
            args["action_id"] = action_id
        if correlation_key is not None:
            args["correlation_key"] = correlation_key
        rpc = client.call_tool("hestia_witness_decision", args)
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as e:
        return _keep_uncommitted(plugin_id, record, DecisionReceipt(
            status="unreachable", detail=f"network: {type(e).__name__}: {e}"))
    except Exception as e:  # noqa: BLE001 — never raises; an unknown failure is not a receipt
        return _keep_uncommitted(plugin_id, record, DecisionReceipt(
            status="ambiguous", detail=f"unexpected: {type(e).__name__}: {e}"))

    kind, payload = _classify_decision_reply(rpc)
    if kind == "ruled":
        return _keep_uncommitted(plugin_id, record, DecisionReceipt(
            status="refused", detail=f"{payload.get('code')}: {payload.get('message', '')}"[:300]))
    if kind != "ok":
        return _keep_uncommitted(plugin_id, record, DecisionReceipt(
            status="ambiguous", detail=str(payload.get("why", "unclassified reply"))[:300]))
    problem = _receipt_problem(payload, decision=decision, action_id=action_id,
                               correlation_key=correlation_key)
    if problem is not None:
        return _keep_uncommitted(plugin_id, record, DecisionReceipt(
            status="ambiguous", detail=problem))
    return DecisionReceipt(
        status="committed",
        entry_hash=payload["witnessEntryHash"],
        event_type=payload["eventType"],
        deduplicated=payload.get("recorded") == "existing",
    )

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


# Reach travels IN the spelling, so an older consumer fails CLOSED on it (2026-09-08):
# `path:/x/**` names a subtree; `path:/x` names exactly /x. An old gate that does not know
# `/**` resolves it as a literal root that nothing descends from, so a recursive grant is
# inert there rather than wide — and its bare `path:` entries keep the old prefix behaviour
# until the gate is updated. Deploy order is therefore safe in both directions; the only
# thing an update changes is that bare `path:` grants tighten to EXACT on that box, which is
# the default dp asked for. Flip the grants that need a subtree BEFORE updating a box's gate.
RECURSIVE_SUFFIX = "/**"


def _scope_entry_for_grant(path: str, recursive: bool = False) -> str:
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
    if par == ws and name and recursive:
        # A repo NAME is a whole-repo entry by construction — the core's segment-keyed
        # model admits the repo and everything in it. So ONLY a RECURSIVE grant on a
        # workspace-direct root may take that form. The first cut mapped every such root
        # to the name regardless of `recursive`, which silently widened an EXACT grant on
        # /ws/repo into the whole repo at the gate while the daemon's covers_path() said it
        # reached /ws/repo alone — the daemon/gate disagreement this change exists to end,
        # recreated for the most common directory shape (GPT review of #1002, blocker 1).
        # An exact grant on a repo root stays the faithful `path:` form, which the core
        # matches at exactly that boundary. Declarative `repo:` scope is untouched.
        return name
    return "path:" + path.strip().rstrip("/") + (RECURSIVE_SUFFIX if recursive else "")


#: One fetch per gate invocation — gate processes are short-lived, so a per-process cache
#: is a per-invocation cache; it exists so a shim may consult the snapshot at several
#: seams without paying several round-trips.
_POLICY_SNAPSHOT_CACHE: dict = {}


#: The pause between the snapshot's two attempts.
SNAPSHOT_RETRY_PAUSE_S = 0.25


def fetch_policy_snapshot(plugin_id, *, deadline: Optional[float] = None, **kw):
    """One retry before None: the measured failure mode is TRANSIENT starvation (a
    session-start hook herd overlapping the first tool calls — codex, 2026-08-14),
    not a down daemon. A 250ms-backoff second attempt absorbs the blip; a genuinely
    unreachable daemon still returns None inside one extra budget and the ratified
    degraded mode proceeds. Never raises (same contract as the single attempt).

    `declares_review_door=True` is the CALLER asserting it holds
    `hestia_gate_escalation_corroborate` — see `_fetch_policy_snapshot_uncached`. Default
    False: a library cannot know its caller's effectors, and the truthful default for a
    capability self-report is silence.

    `deadline` (stage C): one absolute bound for BOTH attempts and the pause between them. The
    retry happens only if the pause still leaves time to ask; no request starts after it."""
    snap = _fetch_policy_snapshot_once(plugin_id, deadline=deadline, **kw)
    if snap is not None:
        return snap
    pause = SNAPSHOT_RETRY_PAUSE_S
    if deadline is not None:
        if deadline - time.monotonic() <= pause:
            return None
    try:
        time.sleep(pause)
    except Exception:
        pass
    return _fetch_policy_snapshot_once(plugin_id, deadline=deadline, **kw)


def _fetch_policy_snapshot_once(plugin_id: str, *, host_agent: Optional[str] = None,
                          host_session_id: Optional[str] = None,
                          use_cache: bool = True,
                          declares_review_door: bool = False,
                          deadline: Optional[float] = None) -> Optional[dict]:
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
    snap = _fetch_policy_snapshot_uncached(plugin_id, host_agent, host_session_id,
                                           declares_review_door=declares_review_door,
                                           deadline=deadline)
    if use_cache and snap is not None:
        _POLICY_SNAPSHOT_CACHE[plugin_id] = snap
    return snap


def _unavailable_cause(e: BaseException) -> str:
    """ONE classifier for "why could the daemon not be consulted", shared by the verdict path
    and the snapshot path: "timeout" (alive but starved: back off and retry), "refused"
    (nothing listening: stop and escalate), "unknown" (say so rather than guess). The
    telemetry writer normalises anything else to "unknown", so a caller that passes a
    free-text reason where the cause goes has silently thrown the diagnosis away — which is
    exactly what the snapshot path did for a month (every record read "unknown" while the
    detail said TimeoutError)."""
    reason = getattr(e, "reason", None)
    if isinstance(reason, (TimeoutError, socket.timeout)) or isinstance(e, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(reason, ConnectionRefusedError) or isinstance(e, ConnectionRefusedError):
        return "refused"
    return "unknown"


def _snapshot_unavailable(plugin_id: str, detail: str, cause: str = "unknown") -> None:
    """Field telemetry for a failed snapshot fetch (never raises): the 2026-08-14 codex
    dropouts were unreproducible from another seat precisely because every failure path
    collapsed to a causeless None — a 'daemon unreachable' that could be refused/timeout/
    port-exhaustion/EPERM. Each is a different fix; the log now says which.

    `detail` is the free text (which STAGE of the handshake failed, and how); `cause` is the
    three-valued diagnosis the writer keeps verbatim. The two were passed in each other's
    positions until 2026-09-11, so every snapshot record carried cause "unknown" whatever
    happened; three timeout bursts on nomad (2026-09-10/11) were attributable only by reading
    the exception name out of the detail string, and even then not to a stage."""
    try:
        from hestia_gate_core import record_gate_unavailable  # type: ignore
        record_gate_unavailable(plugin_id, "policy-snapshot", cause, detail,
                                home=_telemetry_home())
    except Exception:
        pass


def _fetch_policy_snapshot_uncached(plugin_id: str, host_agent: Optional[str],
                                    host_session_id: Optional[str],
                                    declares_review_door: bool = False,
                                    deadline: Optional[float] = None) -> Optional[dict]:
    # Which step of the handshake was in flight when it failed. Named in the telemetry so a
    # timeout on `hestia_operating_law` is distinguishable from one on `initialize`: the
    # first is the daemon working, the second is the daemon absent, and they are different
    # fixes. Set BEFORE each step, so an exception raised inside it reads as that step.
    stage = "endpoint"
    try:
        endpoint = _discover_endpoint()
        if endpoint is None:
            _snapshot_unavailable(plugin_id, "no-endpoint")
            return None
        deadline, cap = _bound(deadline, TOTAL_BUDGET_MS / 1000.0)
        if deadline - time.monotonic() <= 0:
            _snapshot_unavailable(plugin_id, "deadline: the caller's deadline was exhausted "
                                  "before the snapshot fetch", "timeout")
            return None
        client = _client(endpoint, deadline, cap)
        stage = "initialize"
        if "result" not in client.initialize():
            _snapshot_unavailable(plugin_id, "init-no-result")
            return None
        stage = "initialized"
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
            # `escalation-review:v1` is the REVIEW DOOR, and it is the CALLER's assertion,
            # never this module's. The invitation pool reads it: a member that declares its
            # doors without this one is not woken to decide something it cannot decide, and is
            # recorded as ineligible rather than dropped (#1050). Silence still means UNKNOWN
            # and is still invited — the declaration is what lets a member say the other thing.
            #
            # A SHARED GATE LIBRARY CANNOT KNOW ITS CALLER'S EFFECTOR SET. The first cut
            # declared the door unconditionally here, reasoning "every seat that connects
            # through this mechanism holds the MCP tool". kimi-code refuted it cross-vendor
            # (findings/review-13031.md): SAGE's gateway imports this same module as the
            # being's society-safety client (being_gate_client.py:1009) and fetches with
            # `member_id="cbp-being"`, whose effector registry has no corroborate and no
            # arbitrate at all. That call would have declared a door the being does not hold
            # — inviting the exact member #1050 exists to stop inviting, and recording
            # `review_basis: "declared"` as the false reason why. It would also have
            # OVERWRITTEN the being's one accurate declaration (`society-floor:v1` alone),
            # which is precisely what makes the new filter exclude it correctly.
            #
            # So the flag defaults to False and the harnesses that actually hold the tool
            # (the CLI hooks) pass True. Silence from a caller that holds the door costs one
            # extra invitation; a lie from a caller that does not costs the wake this issue
            # exists to prevent.
            "gate_capabilities": (["society-floor:v1", REVIEW_CAPABILITY]
                                  if declares_review_door else ["society-floor:v1"]),
        }
        role_env = os.environ.get("HESTIA_ROLE")
        if role_env:
            connect_args["role"] = role_env
        if host_session_id:
            connect_args["host_session_id"] = host_session_id
        stage = "connect"
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
        stage = "operating_law"
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
        stage = "scope_status"
        scope = _unwrap_tool_result(
            client.call_tool("hestia_scope_status", {"plugin_id": plugin_id}))
        if isinstance(scope, dict) and "_hestia_error" not in scope:
            grants = scope.get("live_grants")
            if isinstance(grants, list):
                for g in grants:
                    p = g.get("path") if isinstance(g, dict) else None
                    rec = bool(g.get("recursive")) if isinstance(g, dict) else False
                    if isinstance(p, str) and p.strip():
                        snap["scope_grants"].append(p.strip())
                        # ONE mapping for both grant channels (GPT #431 blocker 4;
                        # subsumes #430's inline fix): a live grant naming a repo root
                        # under the core-discovered workspace admits as the repo NAME;
                        # anything deeper keeps the faithful typed "path:" form; the core
                        # admits only that resolved boundary and descendants (R2) — a file
                        # grant must not front for its whole repo.
                        snap["in_scope"].append(_scope_entry_for_grant(p, rec))
            # STANDING grants (Sprint F R1) — the durable, operator-promoted list the
            # daemon persists in its vault. Additive beside live_grants; absent on an
            # older daemon, in which case everything below is a no-op and the snapshot
            # is exactly the pre-R1 one.
            standing = scope.get("standing_grants")
            if isinstance(standing, list):
                for g in standing:
                    p = g.get("path") if isinstance(g, dict) else None
                    rec = bool(g.get("recursive")) if isinstance(g, dict) else False
                    if isinstance(p, str) and p.strip():
                        snap["standing_grants"].append({
                            "path": p.strip(),
                            "expires_at": g.get("expires_at"),
                            "granted_by": g.get("granted_by"),
                            "reason": g.get("reason"),
                            "recursive": rec,
                        })
                        snap["scope_grants"].append(p.strip())
                        snap["in_scope"].append(_scope_entry_for_grant(p, rec))
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
            plugin_id,
            f"{stage}: {type(e).__name__}:{getattr(e, 'errno', '')}:{str(e)[:110]}",
            _unavailable_cause(e))
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


def _step_timeout(fixed: float, deadline: Optional[float]) -> float:
    """One request's timeout: its fixed budget, never past the caller's deadline. Raises
    TimeoutError when the deadline leaves no time, so NO request starts after it (stage C)."""
    if deadline is None:
        return fixed
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("the caller's deadline was exhausted before the request")
    return min(fixed, remaining)


def emit_attestation(allows, denies, *, plugin_id, role_lct, endpoint=None, deadline=None):
    """Attest this gate's effective scope to the daemon, best effort.

    `plugin_id` and `role_lct` are REQUIRED and keyword-only. In the seat-local copies both
    were read from module scope, so the identity a record carried was decided by which file
    the function happened to live in. Making them arguments is what let one body serve every
    seat; keyword-only is what stops the two ever being passed in the wrong order, since they
    are both strings and a silent swap would attribute the attestation to a role.

    `deadline` (stage C): no request starts after it (raises TimeoutError; the tally's caller
    swallows it, accounting never changes a decision).
    """
    endpoint = endpoint or os.environ.get("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")

    def post(payload, timeout, hdrs=None):
        timeout = _step_timeout(timeout, deadline)
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


def gate_self_call(tool, args, *, plugin_id, role, client_name, host_session_id=None,
                   deadline=None):
    """One short daemon round trip for a gate-self event: initialize, connect (session-bound),
    one tools/call. Returns the unwrapped result dict, or None on ANY failure.

    Never raises and stays inside a ~2.5s budget: the fail-open engines would treat a hook
    that hangs past its clamp as an allow, so a gate-self exchange that stalls would be
    strictly worse than a refusal. Callers treat None as refusal (writes) or best-effort
    loss (witnesses).

    `host_session_id`, when the caller has one, is threaded into the connect so the
    gate-self session this call mints joins to the per-wake session the outcome rows carry.

    `deadline` (stage C): an absolute `time.monotonic()` bound. Each step keeps its fixed budget
    but never runs past it, and no step starts after it (that is a None: refusal or loss)."""
    endpoint = os.environ.get("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")

    def post(payload, hdrs, timeout):
        timeout = _step_timeout(timeout, deadline)
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
                      plugin_id, role, gate_path, client_name, host_session_id=None,
                      deadline=None):
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
        host_session_id=host_session_id, deadline=deadline) is not None


RESOLVED_TARGET_MAX = 400


def resolved_target_for_claim(target):
    """The resolved target as it may ride a claim, or None. Whitespace-collapsed; tail-capped,
    because the governed filename sits at the END of a path and a cap must cut the head; and
    withheld whole when credential-shaped, by the same discipline as `attempted_summary` — the
    claim lands on the witness chain."""
    if not isinstance(target, str):
        return None
    t = " ".join(target.split())
    if not t or credential_shaped(t):
        return None
    return t[-RESOLVED_TARGET_MAX:]


def claim_self_write(marker, tool_name, attempted, *,
                     plugin_id, role, client_name, host_session_id=None, invocation_key=None,
                     supersession=None, deadline=None, resolved_target=None,
                     also_resolved=None):
    """Ask ONCE whether a human has already approved this exact (member, marker) write.
    Returns (verdict, detail, escalation_id, how_to_decide); only 'approved' permits.

    Never waits. The first attempt is refused and the refusal opens an escalation; a human
    decides out of band; the member RE-ISSUES the write and the second attempt claims the
    approval. Every failure — unreachable, malformed, a daemon with no escalation channel —
    is a refusal: a daemon that cannot answer must not be a way to get a governance write
    through.

    `resolved_target` (#810; recut of #812, kimi-code) is the act's concrete target — on the
    live path the closure verdict's `resource`, the WRITE-POSITION argument that matched, never
    payload text. The daemon prices the escalation's bar over the marker, the act and this
    target, highest wins (core `gate_escalation::price`), so it can only strengthen the bar.
    It matters because `attempted` is a bounded, self-censoring summary that can cut the
    filename out. Not part of the request key: it is derived from the same act. Old daemons
    ignore the key; callers that omit it price exactly as before.

    `also_resolved` is every FURTHER closure location the same act writes, after the first. The
    daemon prices them exactly like `resolved_target` (`price_targets`), so a multi-target act
    is priced by its strongest target whatever order it names them in. Each item gets the
    same cap and credential discipline as `resolved_target`."""
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
    # THE REQUEST KEY (#1166, #774): the same rule as the claude-code gate's
    # `escalation_request_key` -- member, marker, the exact act string, host session.
    import hashlib
    request_key = hashlib.sha256("\x1f".join(
        [plugin_id, marker, claim_args["reason"], host_session_id or ""]).encode("utf-8")).hexdigest()
    claim_args["request_key"] = request_key
    if invocation_key:
        claim_args["invocation_key"] = invocation_key  # #1169: retry vs repeat
    # The HOOK's declaration that it stops a superseded invocation in every rollout mode (see
    # SUPERSESSION_HARD_STOP). Forwarded, never defaulted: without it the daemon will not reclaim
    # this spend, which only costs a lost answer a fresh petition.
    if supersession:
        claim_args["supersession"] = supersession
    rt = resolved_target_for_claim(resolved_target)
    if rt:
        claim_args["resolved_target"] = rt
    more = [m for m in (resolved_target_for_claim(t) for t in (also_resolved or ())) if m]
    if more:
        claim_args["also_resolved"] = more
    r = gate_self_call("hestia_gate_escalation_claim", claim_args,
                       plugin_id=plugin_id, role=role, client_name=client_name,
                       host_session_id=host_session_id, deadline=deadline)
    if not isinstance(r, dict):
        # A TIMEOUT IS AN UNKNOWN OUTCOME, NOT "NOTHING HAPPENED" (#1166): the daemon may have
        # opened, matched or spent after the call's budget passed. Refuse, and say how to recover.
        return ("unknown",
                "OUTCOME UNKNOWN — the daemon did not answer in time; it may have opened or "
                f"matched an escalation for this act. request key {request_key[:16]}… — "
                f"`hestia gate lookup {request_key}`; re-issuing this identical act is safe: it "
                "returns the same escalation or the grant already claimed for you",
                None, None)
    # BOTH flags, and the daemon owns both — two places deciding what "approved" means is how
    # they come to disagree, so the hook re-derives nothing.
    if r.get("claimed") is True and r.get("permits_write") is True:
        who = r.get("decided_by") or "a human"
        via = r.get("decided_via") or "unknown-channel"
        if r.get("reclaimed") is True:
            return ("approved",
                    f"re-claimed the approval from {who} via {via} that this request already "
                    "spent (its first answer was lost)", None, None)
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


def tally_scope(allowed, *, tally_dir, tally_path, attest_every, plugin_id, role_lct,
                deadline=None):
    """Count this decision; emit an attestation when the window closes. `deadline` (stage C)
    bounds the attestation's requests; an attestation that cannot finish in time keeps the
    window open (the count is not reset), so the next invocation attests it."""
    try:
        os.makedirs(tally_dir, exist_ok=True)
        try:
            t = json.load(open(tally_path))
        except Exception:
            t = {"allows": 0, "denies": 0}
        t["allows" if allowed else "denies"] += 1
        if t["allows"] + t["denies"] >= attest_every:
            try:
                emit_attestation(t["allows"], t["denies"],
                                 plugin_id=plugin_id, role_lct=role_lct, deadline=deadline)
                t = {"allows": 0, "denies": 0}
            except TimeoutError:
                pass   # out of time: keep the window and its counts for the next invocation
        json.dump(t, open(tally_path, "w"))
    except Exception:
        pass  # accounting must never change a decision
