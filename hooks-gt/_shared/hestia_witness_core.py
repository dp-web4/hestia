# hestia-gt-sha256: 750c7197cd4fc8d7188b53ef7351712c73bc8c034bb039b321e55c69534eb777  (published ground truth; manifest: hooks-gt)
"""The outcome witness — ONE implementation for every harness; the shims only say who they are.

WHY THIS EXISTS (findings/per-harness-witness-drift-2026-09-28.md; dp agreed all five
recommendations the same day). The gate was consolidated into a shared core; the OUTCOME side
was not, and it forked the same way the gate had:

  * claude-code shipped the witness with act-identity continuity (#977) and the spool (#696);
  * codex shipped an older copy with neither — 0 of its warned acts closed by a same-id outcome;
  * kimi shipped none; its seat ran a private 07-26 copy of claude-code's, frozen when the hooks
    moved off 9p — 0 of 37 warned acts closed, and every PostToolUseFailure unwitnessed;
  * gemini shipped none, and its outcomes never reached the daemon at all.

A fix to a per-harness copy was a fix to that harness. This module is the copy there is now
only one of. It holds, in one place, BOTH halves of the gate<->outcome seam:

  * the GATE half — `correlation_key(event)` and `cache_authorized_action(...)`, which
    hestia_gate_mechanism.query_society_safety calls when it has begun an action, so every gate
    that reaches the daemon through the mechanism caches the id, not only claude-code's;
  * the WITNESS half — `run(event)`, which closes that same action with the act's outcome,
    spools on a transient failure, and names every cold path on the row.

THE SEAM'S KEY (the one thing the harnesses disagree on). Pre and Post must compute the same key
for the same call, from different events:

  * claude-code, codex: `tool_use_id` on both events (codex's pre-tool-use schema requires it);
  * kimi: `tool_call_id` on both (kimi's hook runner sends `toolCallId: ctx.toolCall.id`);
  * gemini: no call id in its hook payloads, so the key is derived from what both events do
    carry — host session, the harness-native tool name, and the canonical tool input. Gemini's
    gate hands the governor a TRANSLATED event, so the pre side keys on its `source_event`
    (the untranslated gemini fields it carries for exactly this kind of reader).

The literal `/tmp/hestia-actions` is kept: it is the directory claude-code's deployed witnesses
read today, and moving it in the same change that multiplies its writers would make a failed
join impossible to attribute (#977's own reasoning, unchanged). #944 carries the move.

Pure stdlib, fail-open at every layer: nothing here may block or fail the tool call.

The transport helpers (`_McpHttp`, `_unwrap_tool_result`, `_discover_endpoint`, `_debug_log`) are
private, as the mechanism's are: they are plumbing, not law, and a public engine name would make
every gate's own transport copy read as a fork (tools/installed_seat_readiness.py). One shared
transport for gate, mechanism and witness is the follow-up that removes the copies themselves.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Optional

PROTOCOL_VERSION = "2024-11-05"
CORE_VERSION = "1.0.0"

# The Post-side events this witness closes. PostToolUseFailure is kimi's: a failed call fires it
# INSTEAD of PostToolUse, so a witness that read only PostToolUse (kimi's fork did) never
# witnessed a single failed act.
OUTCOME_EVENTS = {"PostToolUse": None, "PostToolUseFailure": False, "AfterTool": None}

# ---- Identity: set once by the shim -------------------------------------------------------

PLUGIN_ID = "unconfigured"
HOST_AGENT = "unconfigured"
HOST_AGENT_VERSION = "unconfigured"
HOOK_VERSION = CORE_VERSION
STATE_DIR = Path.home() / ".hestia-unconfigured"
SPOOL_DIR = STATE_DIR / "spool"


def configure(*, plugin_id: str, host_agent: Optional[str] = None,
              host_agent_version: Optional[str] = None, hook_version: Optional[str] = None) -> None:
    """Called by the shim AFTER it has loaded its seat projection (the state dir may come from it)."""
    global PLUGIN_ID, HOST_AGENT, HOST_AGENT_VERSION, HOOK_VERSION, STATE_DIR, SPOOL_DIR
    PLUGIN_ID = plugin_id
    HOST_AGENT = host_agent or os.environ.get("HESTIA_HOST_AGENT") or plugin_id
    HOST_AGENT_VERSION = host_agent_version or plugin_id
    HOOK_VERSION = hook_version or CORE_VERSION
    STATE_DIR = Path(
        os.environ.get("HESTIA_STATE_DIR")
        or str(Path.home() / (".hestia-claude" if plugin_id == "claude-code" else f".hestia-{plugin_id}"))
    )
    SPOOL_DIR = STATE_DIR / "spool"


def timeout_s() -> float:
    return float(os.environ.get("HESTIA_WITNESS_TIMEOUT_S") or "2.0")


def _debug_log(msg: str) -> None:
    if os.environ.get("HESTIA_HOOK_DEBUG") != "1":
        return
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with (STATE_DIR / "hook.log").open("a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        pass


def _discover_endpoint() -> Optional[str]:
    """Mirror the SDK's discovery order: env → file → default."""
    env = os.environ.get("HESTIA_ENDPOINT")
    if env:
        return env
    home = os.environ.get("HESTIA_HOME")
    if not home:
        return None
    try:
        return (Path(home) / "endpoint").read_text().strip() or None
    except OSError:
        return None  # daemon hasn't run; let warn_once handle the UX


def warn_once_daemon_missing() -> None:
    """Surface a single one-time hint if the daemon was never set up."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        marker = STATE_DIR / "daemon-warned"
        if marker.exists():
            return
        marker.touch()
        sys.stderr.write(
            "hestia: daemon not detected — install at https://hestia.tools "
            "to start recording tool calls. (This message shown once.)\n"
        )
    except OSError:
        pass


# ---- The seat's key: shared by the gate half and the witness half --------------------------

ACTIONS_DIR = Path("/tmp/hestia-actions")

# Typed on the outcome row via the action's `intent`, so a discontinuity is READ rather than
# inferred from a join that does not close.
COLD_NO_CACHE = "hestia:cold-record:no-authorized-action-cached"
COLD_STALE = "hestia:cold-record:authorized-action-not-resident"


def _canonical_input(tool_input: Any) -> Any:
    """A tool input as both events see it. Some harnesses hand it over as a JSON string."""
    if isinstance(tool_input, str):
        try:
            return json.loads(tool_input)
        except ValueError:
            return tool_input
    return tool_input


def correlation_key(event: dict) -> str:
    """The key under which the gate caches the action it authorized and the witness finds it.

    Explicit call ids first — they are the harness's own identity for the call. Only a harness
    with none (gemini) falls to a content key, and that key is built from the fields BOTH events
    carry, in the harness's own vocabulary (the pre side reads `source_event` when the gate
    translated the event for the governor). The result is a filename component, so it is always
    `[A-Za-z0-9_.-]`.
    """
    if not isinstance(event, dict):
        return "no-id"
    for field in ("tool_use_id", "tool_call_id"):
        v = event.get(field)
        if isinstance(v, str) and v:
            return "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in v)[:200]
    src = event.get("source_event") if isinstance(event.get("source_event"), dict) else event
    basis = json.dumps(
        [event.get("session_id") or "", src.get("tool_name") or "",
         _canonical_input(src.get("tool_input"))],
        sort_keys=True, default=str, separators=(",", ":"),
    )
    return "content-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:40]


def cache_authorized_action(key: str, action_id: str, tool_name: str) -> None:
    """GATE HALF: record the action the gate began, for the witness to close. Never raises."""
    if not key or not action_id:
        return
    try:
        ACTIONS_DIR.mkdir(parents=True, exist_ok=True)
        (ACTIONS_DIR / f"{key}.json").write_text(
            json.dumps({"action_id": action_id, "tool_name": tool_name, "ts": time.time()})
        )
    except OSError as e:
        _debug_log(f"action cache failed: {e}")


def cached_action_id(key: Optional[str]) -> Optional[str]:
    """The id of the action the gate authorized for this call, or None (a normal value: a call
    the gate never sent to the daemon, a cleared cache, a gate predating the cache)."""
    if not key:
        return None
    try:
        blob = json.loads((ACTIONS_DIR / f"{key}.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    action_id = blob.get("action_id")
    return action_id if isinstance(action_id, str) and action_id else None


def retire_cached_action(key: Optional[str]) -> None:
    """Drop this call's correlation file once its act is durably handled — never before."""
    if not key:
        return
    try:
        (ACTIONS_DIR / f"{key}.json").unlink()
    except OSError:
        pass


# ---- Spool: a slow referee must not DESTROY the record (#696) ----------------------------

SPOOL_MAX_ENTRIES = 500
SPOOL_DRAIN_PER_RUN = 8


def spool_save(intent: dict) -> bool:
    """Best-effort append; FIFO by act time; when full, drop the NEWEST. Returns whether the row
    is now durable — the caller releases the correlation file only on True (#977 review)."""
    try:
        SPOOL_DIR.mkdir(parents=True, exist_ok=True)
        if len(list(SPOOL_DIR.glob("*.json"))) >= SPOOL_MAX_ENTRIES:
            _debug_log(f"spool FULL ({SPOOL_MAX_ENTRIES}) — dropping newest row; backlog preserved")
            return False
        (SPOOL_DIR / f"{intent['client_ts']:.3f}-{uuid.uuid4().hex}.json").write_text(json.dumps(intent))
    except (OSError, KeyError) as e:
        _debug_log(f"spool save failed: {e}")
        return False
    return True


def spool_drain(client: "_McpHttp", session_id: Optional[str]) -> None:
    """Replay spooled intents, oldest first, bounded per run. Record-then-unlink: a crash between
    the two replays the row (a detectable duplicate), never loses it."""
    try:
        files = sorted(SPOOL_DIR.glob("*.json"))[:SPOOL_DRAIN_PER_RUN]
    except OSError:
        return
    if not files:
        return
    lock_file = None
    fcntl = None
    if os.name != "nt":
        try:
            import fcntl as _fcntl
            fcntl = _fcntl
            lock_file = open(SPOOL_DIR / ".lock", "w")
            fcntl.flock(lock_file, fcntl.LOCK_EX)
        except (OSError, ImportError):
            lock_file = None
    try:
        for f in files:
            try:
                intent = json.loads(f.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            verdict = witness_one(client, session_id, intent)
            if verdict == "transient":
                continue  # referee still unreachable; the row stays
            try:
                f.unlink()
            except OSError:
                pass
            _debug_log(f"spool: {verdict} {f.name} (client_ts {intent.get('client_ts')})")
    finally:
        if lock_file is not None:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_UN)
                lock_file.close()
            except OSError:
                pass


# ---- What the act was --------------------------------------------------------------------

def magnitude_for(tool_name: str) -> float:
    """R6 magnitude in [0..1] by tool class (harness-native names included)."""
    if tool_name in {"Bash", "Shell", "run_shell_command", "shell", "exec_command"}:
        return 0.8
    if tool_name in {"Write", "Edit", "MultiEdit", "NotebookEdit", "write_file", "replace", "apply_patch"}:
        return 0.6
    if tool_name in {"WebFetch", "WebSearch", "web_fetch", "google_web_search"}:
        return 0.4
    if tool_name in {"Read", "Glob", "Grep", "TodoWrite", "read_file", "read_many_files", "glob",
                     "search_file_content", "list_directory"}:
        return 0.2
    return 0.4


def extract_target(tool_input: Any) -> Optional[str]:
    tool_input = _canonical_input(tool_input)
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "path", "absolute_path", "dir_path", "url", "notebook_path"):
        v = tool_input.get(key)
        if isinstance(v, str):
            return v
    cmd = tool_input.get("command")
    if isinstance(cmd, str) and cmd.strip():
        s = cmd.strip()  # forensic readability in the chain feed; the gate saw the full command
        return s if len(s) <= 240 else s[:237] + "..."
    return None


def derive_success(event: dict) -> tuple[bool, Optional[str]]:
    """Best-effort success flag across the harnesses' outcome shapes."""
    forced = OUTCOME_EVENTS.get(event.get("hook_event_name"))
    if forced is False:  # kimi's PostToolUseFailure: the event IS the failure
        err = event.get("error")
        if isinstance(err, dict):
            err = err.get("message") or json.dumps(err)
        return False, str(err or "tool error")[:500]
    resp = event.get("tool_response")
    if isinstance(resp, dict):
        if resp.get("is_error") or resp.get("isError"):
            err = resp.get("error") or resp.get("message") or "tool error"
            return False, str(err)[:500]
        if resp.get("error"):  # gemini's AfterTool carries a populated `error` on failure
            err = resp["error"]
            if isinstance(err, dict):
                err = err.get("message") or json.dumps(err)
            return False, str(err)[:500]
    return True, None


# ---- Minimal MCP-over-HTTP client --------------------------------------------------------

class _McpHttp:
    """Tiny synchronous MCP client. Just enough to fire init + a few tool calls."""

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
        self.session_id: Optional[str] = None
        self.next_id = 0

    def _id(self) -> int:
        self.next_id += 1
        return self.next_id

    def _request(self, body: dict[str, Any], *, is_notification: bool = False) -> Optional[dict[str, Any]]:
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        req = urllib.request.Request(self.endpoint, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout_s()) as resp:
            if not self.session_id:
                sid = resp.headers.get("mcp-session-id")
                if sid:
                    self.session_id = sid
            if is_notification:
                return None
            payload = resp.read().decode("utf-8", errors="replace")
        return parse_json_or_sse(payload)

    def initialize(self) -> dict[str, Any]:
        return self._request({
            "jsonrpc": "2.0", "id": self._id(), "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                       "clientInfo": {"name": PLUGIN_ID, "version": HOOK_VERSION}},
        }) or {}

    def initialized(self) -> None:
        self._request({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                      is_notification=True)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._request({
            "jsonrpc": "2.0", "id": self._id(), "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }) or {}


def parse_json_or_sse(text: str) -> dict[str, Any]:
    """Hestia returns either a plain JSON-RPC body or an SSE stream containing it."""
    text = text.strip()
    if not text:
        return {}
    if text.startswith("{"):
        return json.loads(text)
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


def _unwrap_tool_result(rpc_response: dict[str, Any]) -> dict[str, Any]:
    result = rpc_response.get("result") or {}
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            try:
                return json.loads(block.get("text", ""))
            except json.JSONDecodeError:
                pass
    return {}



def _classify_reply(rpc) -> tuple[str, dict]:
    """What the daemon SAID, in three kinds -- never inferred from an absence (#1149 review).

    ("ok", payload)        a readable tool result with a non-empty payload;
    ("ruled", error)       the daemon RULED: a structured `_hestia_error` carrying a `code`;
    ("ambiguous", {why})   anything else -- an outer JSON-RPC error, an MCP `isError`, an empty
                           or unreadable result. Nobody ruled, so nothing may be discarded on it.

    GPT reproduced the defect this replaces: `_unwrap_tool_result` reduced an outer -32603, an
    `isError` text and an empty `{}` alike to `{}`, and "no `_hestia_error`" read as success. The
    witness then retired the act's correlation file and unlinked its spool row -- the only
    evidence, destroyed under a claim that it had landed.
    """
    if not isinstance(rpc, dict) or not rpc:
        return "ambiguous", {"why": "no reply"}
    if "error" in rpc:
        return "ambiguous", {"why": f"json-rpc error {rpc.get('error')}"}
    result = rpc.get("result")
    if not isinstance(result, dict):
        return "ambiguous", {"why": "no result"}
    payload = _unwrap_tool_result(rpc)
    err = payload.get("_hestia_error") if isinstance(payload, dict) else None
    if isinstance(err, dict) and isinstance(err.get("code"), str) and err["code"]:
        return "ruled", err
    if result.get("isError"):
        return "ambiguous", {"why": "the tool reported isError without a ruling"}
    if not isinstance(payload, dict) or not payload:
        return "ambiguous", {"why": "empty result"}
    return "ok", payload


# ---- Closing the authorized action (#977) ------------------------------------------------

def begin_cold_action(client: "_McpHttp", session_id: Optional[str], intent: dict,
                      why: str) -> tuple[Optional[str], Optional[str]]:
    """Begin an action HERE because no authorized one is usable, and SAY SO on the row."""
    resp = client.call_tool("hestia_begin_action", {
        "tool_name": intent["tool_name"],
        "target": intent.get("target"),
        "intent": why,
        **({"session_id": session_id} if session_id else {}),
        **({"host_session_id": intent["host_session_id"]} if intent.get("host_session_id") else {}),
    })
    kind, begin = _classify_reply(resp)
    if kind == "ruled":
        _debug_log(f"begin_action rejected: {begin}")
        return None, "rejected"
    action_id = begin.get("actionId") if kind == "ok" else None
    if not isinstance(action_id, str) or not action_id:
        # No ruling and no action: the daemon answered nothing usable, so the act is kept.
        _debug_log(f"begin_action gave no actionId ({kind}: {begin}); keeping the act")
        return None, "transient"
    return action_id, None


def record_outcome_for(client: "_McpHttp", session_id: Optional[str], intent: dict,
                       action_id: str) -> tuple[str, dict]:
    """Close one action with this act's outcome -> `_classify_reply`'s (kind, payload). Raises on
    network failure."""
    resp = client.call_tool("hestia_record_outcome", {
        "action_id": action_id,
        "success": intent["success"],
        "magnitude": intent["magnitude"],
        "error": intent.get("error"),
        "client_ts": intent["client_ts"],  # the act's own clock (#696)
        **({"session_id": session_id} if session_id else {}),
    })
    return _classify_reply(resp)


def witness_one(client: "_McpHttp", session_id: Optional[str], intent: dict) -> str:
    """Close the AUTHORIZED action with this act's outcome: "recorded" | "transient" | "rejected".

    The normal path begins nothing — it closes the action the gate authorized, whose id
    `intent["action_id"]` carries. Two cold paths remain, and both name themselves on the row:
    no cached id at all (COLD_NO_CACHE), or an id the daemon no longer holds (COLD_STALE: its
    action table is RAM, so a restart between decision and outcome loses it).
    """
    action_id = intent.get("action_id")
    try:
        if action_id:
            kind, outcome = record_outcome_for(client, session_id, intent, action_id)
            if kind == "ruled" and outcome.get("code") == "hestia.action_not_found":
                _debug_log(f"authorized action {action_id} no longer resident; cold-recording")
                action_id, verdict = begin_cold_action(client, session_id, intent, COLD_STALE)
                if action_id is None:
                    return verdict
                kind, outcome = record_outcome_for(client, session_id, intent, action_id)
        else:
            action_id, verdict = begin_cold_action(client, session_id, intent, COLD_NO_CACHE)
            if action_id is None:
                return verdict
            kind, outcome = record_outcome_for(client, session_id, intent, action_id)
    except (urllib.error.URLError, OSError, ValueError) as e:
        _debug_log(f"witness network: {e}")
        return "transient"
    if kind == "ruled":
        _debug_log(f"record_outcome rejected: {outcome}")
        return "rejected"
    # RECORDED IS A RECEIPT, never an absence (#1149 review): the daemon's success reply is
    # `{"witnessEntryHash", "updatedTrustState"}` (handler.rs `tool_record_outcome`), so the
    # chain hash of the outcome row is what proves it landed.
    receipt = outcome.get("witnessEntryHash") if kind == "ok" else None
    if isinstance(receipt, str) and receipt:
        return "recorded"
    _debug_log(f"record_outcome gave no receipt ({kind}: {outcome}); keeping the act")
    return "transient"


def intent_from(event: dict) -> Optional[dict]:
    """Map one harness outcome event onto the intent the chain records, or None if it is not one.

    Everything harness-specific the witness needs is here and in `correlation_key`; a shim that
    needs more than its identity to be witnessed is a shim that has started to fork.
    """
    if not isinstance(event, dict) or event.get("hook_event_name") not in OUTCOME_EVENTS:
        return None
    tool_name = event.get("tool_name") or "?"
    success, error = derive_success(event)
    return {
        "tool_name": tool_name,
        "target": extract_target(event.get("tool_input")),
        "success": success,
        "magnitude": magnitude_for(tool_name),
        "error": error,
        "host_session_id": event.get("session_id"),
        # Captured BEFORE any network work: the act's timestamp, unchanged across a spool replay.
        "client_ts": time.time(),
        # The act's identity, read from the gate's cache before any network work for the same
        # reason: it rides into the spool, so a replay closes the action that was authorized.
        "action_id": cached_action_id(correlation_key(event)),
    }


def run(event: dict) -> int:
    """Witness one outcome event. Always returns 0: the witness never fails the tool call."""
    intent = intent_from(event)
    if intent is None:
        return 0
    key = correlation_key(event)

    def hand_off_to_spool() -> None:
        """Park the act durably, then release its correlation file — never before."""
        if spool_save(intent):
            retire_cached_action(key)

    endpoint = _discover_endpoint()
    if endpoint is None:
        warn_once_daemon_missing()
        _debug_log("no endpoint discovered; spooling")
        hand_off_to_spool()
        return 0

    client = _McpHttp(endpoint)
    try:
        init_resp = client.initialize()
        if "result" not in init_resp:
            _debug_log(f"initialize failed: {init_resp}")
            hand_off_to_spool()
            return 0
        client.initialized()
        connect_args: dict[str, Any] = {
            "plugin_id": PLUGIN_ID,
            "plugin_version": HOOK_VERSION,
            "host_agent": HOST_AGENT,
            "host_agent_version": HOST_AGENT_VERSION,
            "requested_role": "citizen",
        }
        # Launch context, never config: absent → the daemon's default member role.
        if os.environ.get("HESTIA_ROLE"):
            connect_args["role"] = os.environ["HESTIA_ROLE"]
        if os.environ.get("HESTIA_ROLE_BASIS"):
            connect_args["role_basis"] = os.environ["HESTIA_ROLE_BASIS"]
        if os.environ.get("HESTIA_PROJECTION_SHA256"):  # liveness (#944)
            connect_args["projection_sha256"] = os.environ["HESTIA_PROJECTION_SHA256"]
        # The host session makes connect idempotent across hook invocations (#981 prerequisite):
        # without it every PostToolUse minted a fresh daemon session (#320).
        if intent.get("host_session_id"):
            connect_args["host_session_id"] = intent["host_session_id"]
        kind, connect = _classify_reply(client.call_tool("hestia_connect", connect_args))
        if kind == "ruled":
            _debug_log(f"connect rejected: {connect}")  # ruled on: nothing to spool
            return 0
        session_id = connect.get("sessionId") if kind == "ok" else None
        if not isinstance(session_id, str) or not session_id:
            # No session, no attributable outcome (#1149 review): keep the act for a later run.
            _debug_log(f"connect gave no session ({kind}: {connect}); spooling")
            hand_off_to_spool()
            return 0

        spool_drain(client, session_id)  # older acts outrank this one

        verdict = witness_one(client, session_id, intent)
        if verdict == "transient":
            hand_off_to_spool()
        else:
            retire_cached_action(key)
            if verdict == "recorded":
                _debug_log(f"post {intent['tool_name']} success={intent['success']} "
                          f"magnitude={intent['magnitude']} action={'warm' if intent['action_id'] else 'cold'}")
    except urllib.error.URLError as e:
        _debug_log(f"network: {e}")
        warn_once_daemon_missing()
        hand_off_to_spool()
    except Exception as e:  # noqa: BLE001 — fail-open at top level
        _debug_log(f"unexpected: {type(e).__name__}: {e}")
        hand_off_to_spool()
    return 0
