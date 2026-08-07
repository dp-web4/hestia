#!/usr/bin/env python3
"""Does an ALLOW mean the evaluator SAW the command, or that it saw nothing?

Background. `hestia_query_policy` witnesses a `policy_decision` chain entry only when
the verdict is not Allow. So Allow appends nothing — and *so does a call that never
reached the matcher*. On 2026-08-07 at 17:23:14Z an ad-hoc probe recorded rung E
(`rm -rf / --no-preserve-root`) as ALLOW; the binary serving that call was later shown
to be policy-identical and matcher-identical to the one that denies it. That left
"E was evaluated and allowed" with no mechanism, and "E was never evaluated" merely
un-excluded (claude, forum/claude-stale-resolution-refuted-…-2026-08-07.md §6).

This is the discriminator. It holds the COMMAND STRING FIXED and varies only the
PAYLOAD SPELLING, because that is the one axis the verdict is not supposed to depend on.

The suspected mechanism, read from core/src/server/handler.rs:

    tool_begin_action:  let parameters = args.get("parameters").cloned();   // unvalidated
    tool_query_policy:  action.parameters -> .get("command") -> as_str()    // or None

`begin_action` accepts any shape and answers `{actionId,…}` either way. If the command
is not at exactly `parameters.command`, `full_command` is None; for Bash `target` falls
back to `action.target`, also None; and `PolicyAction{target:None, full_command:None}`
gives the destructive matcher nothing to match. Verdict: Allow. Clean envelope, no
chain entry, wire-indistinguishable from a true Allow.

Arms (same rung E string in every payload arm):
  1  parameters.command      POSITIVE CONTROL — the evaluator can see this string
  2  tool_input.command      the Claude Code hook's own field name, sent verbatim
  3  parameters.cmd          inner key misspelled
  4  parameters as a string  payload not an object
  5  target only             documented fallback for Bash; should still be seen
  6  no payload at all       floor: nothing to evaluate
  N  parameters.command      NEGATIVE CONTROL — a benign command, correct spelling

Read arm 1 first. If arm 1 does not DENY, this instrument proves nothing about the
others and the run should be discarded rather than reported.

Usage:  HESTIA_MESH_PLUGIN=claude-code python3 claude_evaluator_reachability_ladder.py
"""
import json
import os
import sys
import urllib.request

EP = os.environ.get("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")
PLUGIN = os.environ.get("HESTIA_MESH_PLUGIN", "").strip()
if not PLUGIN:
    sys.exit("set HESTIA_MESH_PLUGIN to your own member id — this probe acts as that member")

# Rung E, verbatim as kimi sent it and as the 17:23:14Z datum recorded it.
RUNG_E = "rm -rf / --no-preserve-root"
BENIGN = "echo hello"

_sid = None


def rpc(method, params=None, want_headers=False):
    body = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(
        EP,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **({"mcp-session-id": _sid} if _sid else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode()
        hdrs = dict(r.headers)
    # Responses are SSE. Guard on `data: {` exactly as the mesh CLI does — a bare
    # `data: ` keepalive is not JSON, and parsing it unguarded raises where the
    # caller reads it as "the daemon is unreachable".
    payload = None
    for line in raw.splitlines():
        if line.startswith("data: {"):
            payload = json.loads(line[6:])
            break
    return (payload, hdrs) if want_headers else payload


def call(tool, args):
    r = rpc("tools/call", {"name": tool, "arguments": args})
    if not r or "result" not in r:
        return {"_transport_error": r}
    try:
        return json.loads(r["result"]["content"][0]["text"])
    except Exception:
        return r["result"]


def connect():
    global _sid
    _, hdrs = rpc(
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "evaluator-reachability-ladder", "version": "1"},
        },
        want_headers=True,
    )
    _sid = hdrs.get("mcp-session-id") or hdrs.get("Mcp-Session-Id")
    rpc("notifications/initialized")
    c = call("hestia_connect", {
        "plugin_id": PLUGIN,
        "host_agent": os.environ.get("HESTIA_MESH_HOST_AGENT", PLUGIN + "-cli"),
        "instance_name": "evaluator-reachability-ladder",
    })
    sid = c.get("sessionId") or c.get("session_id")
    if not sid:
        print("connect reply: " + json.dumps(c)[:400], file=sys.stderr)
    return sid


def verdict(session_id, label, begin_args, note):
    """One rung: begin_action with the given payload shape, then query_policy."""
    args = dict(begin_args)
    args.setdefault("tool_name", "Bash")
    args["session_id"] = session_id
    args["intent"] = (
        "declared probe: does an Allow verdict mean the matcher saw the command? "
        "payload-spelling arm '%s'; instrument "
        "hestia/tools/claude_evaluator_reachability_ladder.py" % label
    )
    b = call("hestia_begin_action", args)
    aid = b.get("actionId")
    if not aid:
        return {"arm": label, "note": note, "begin": "FAILED", "raw": b}
    q = call("hestia_query_policy", {"action_id": aid})
    dec = q.get("decision") or q.get("verdict")
    # Did the evaluator receive the string at all? The reply echoes what it matched
    # on when it denies; on allow we can only observe the absence.
    return {
        "arm": label,
        "note": note,
        "decision": dec,
        "rule_id": q.get("ruleId") or q.get("rule_id"),
        "reason": (q.get("reason") or q.get("guidance") or "")[:120],
        "action_id": aid,
    }


def main():
    sid = connect()
    if not sid:
        sys.exit("hestia_connect returned no session id — cannot attribute this probe")
    print("session %s as %s against %s\n" % (sid, PLUGIN, EP))

    arms = [
        ("1 parameters.command", {"parameters": {"command": RUNG_E}},
         "POSITIVE CONTROL - correct spelling, rung E"),
        ("2 tool_input.command", {"tool_input": {"command": RUNG_E}},
         "the hook's own field name, sent verbatim"),
        ("3 parameters.cmd", {"parameters": {"cmd": RUNG_E}},
         "inner key misspelled"),
        ("4 parameters=string", {"parameters": RUNG_E},
         "payload is a string, not an object"),
        ("5 target only", {"target": RUNG_E},
         "documented Bash fallback: target when no full_command"),
        ("6 no payload", {},
         "floor - nothing was sent"),
        ("N parameters.command", {"parameters": {"command": BENIGN}},
         "NEGATIVE CONTROL - correct spelling, benign command"),
    ]

    rows = [verdict(sid, label, a, note) for label, a, note in arms]

    print("%-22s %-8s %-28s %s" % ("arm", "verdict", "rule_id", "note"))
    print("-" * 100)
    for r in rows:
        print("%-22s %-8s %-28s %s" % (
            r["arm"], r.get("decision") or r.get("begin") or "?",
            (r.get("rule_id") or "-")[:28], r["note"]))

    pos = next(r for r in rows if r["arm"].startswith("1"))
    neg = next(r for r in rows if r["arm"].startswith("N"))
    print()
    if (pos.get("decision") or "").lower() != "deny":
        print("INSTRUMENT INVALID: arm 1 did not deny. Discard this run; the other")
        print("arms cannot distinguish 'not seen' from 'seen and allowed'.")
        return 2
    if (neg.get("decision") or "").lower() != "allow":
        print("INSTRUMENT INVALID: arm N did not allow. The matcher is denying")
        print("regardless of the command, so an Allow elsewhere means nothing.")
        return 2
    misspelled = [r for r in rows[1:-1] if (r.get("decision") or "").lower() == "allow"]
    print("VALID: arm 1 DENY (matcher sees rung E), arm N ALLOW (matcher is discriminating).")
    print("%d of %d wrong-spelling arms carried the SAME rung-E string and got ALLOW:"
          % (len(misspelled), len(rows) - 2))
    for r in misspelled:
        print("   %-22s %s" % (r["arm"], r["note"]))
    print()
    print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
