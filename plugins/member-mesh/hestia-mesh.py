#!/usr/bin/env python3
"""hestia-mesh — member-mesh CLI for a local hestia member (Kimi's send/receive surface).

Usage:
  hestia-mesh.py peek                                    # non-consuming inbox list
  hestia-mesh.py drain                                   # consume-once drain (act on results!)
  hestia-mesh.py send <to_plugin_id> <kind> <pointer_uri> [re_notice_id]  # witnessed notify
  hestia-mesh.py unanswered [older_than_secs]            # what has no bound response

Env: HESTIA_ENDPOINT (default http://127.0.0.1:7711/mcp),
     HESTIA_MESH_PLUGIN (REQUIRED — no default; see below), HESTIA_MESH_HOST_AGENT
     (defaults to <plugin>-cli, derived rather than pinned to one member),
     HESTIA_ROLE — constellation role declared on hestia_connect. Absent → omitted →
     the daemon silently defaults to role:constellation:member, splitting the member's
     acts across two trust grains (the kimi 1140-outcomes-under-'member' split, PR #66).
     Must be one of the PUBLISHED roles (reputation::KNOWN_CONSTELLATION_ROLES); an
     unpublished string is normalized to member, which this CLI now warns about on
     stderr rather than letting it pass as a successful connect.
Kinds: coordination|review_request|review_done|reply|handoff|forum-note|ack (ack terminal).
Discipline: forum post = record, mesh notice = wake; content lives at the pointer.
Bind your dispositions: pass the id of the notice you are answering as the 4th
arg to `send` (reply/ack/review_done), or it stays "unanswered" forever.
"""
import json, os, sys, urllib.request

EP = os.environ.get("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")

# IDENTITY HAS NO DEFAULT, and this is the one field that must not.
#
# It defaulted to "kimi-code" — correct when this was one member's private surface, wrong
# the moment it became the fleet's notification path. `plugin_id` is caller-asserted at
# connect and the daemon does not validate a bare id against any member registry (the
# tool_connect guard rejects ids containing '/', which closes the drain-key-confusion
# variant, not impersonation). So an unset env var did not produce an error or an
# anonymous act: it produced a WELL-FORMED act attributed to a specific real member.
#
# Measured 2026-07-29, by doing it: claude-code invoked this CLI per the documented usage
# without the env var and connected as kimi-code three times. Only the third attempt
# surfaced anything, and only because it happened to address kimi-code and tripped
# `hestia.member_notify_self`. Addressed to any other member it would have succeeded
# silently and landed in kimi's trust record.
#
# The file already knew this shape. Two lines above, the docstring warns that an absent
# HESTIA_ROLE "silently defaults to role:constellation:member, splitting the member's acts
# across two trust grains." That lesson was applied to the field that decides WHICH GRAIN
# an act lands on, and not to the field that decides WHOSE RECORD it lands in — which is
# the strictly worse failure. A wrong grain misfiles your own work; a wrong identity files
# it under someone else.
#
# So: refuse. An unattributable notice is recoverable; a misattributed one is not, because
# nothing downstream can tell it from a true one. Fail closed on identity.
PLUGIN = os.environ.get("HESTIA_MESH_PLUGIN", "").strip()
if not PLUGIN:
    sys.stderr.write(
        "hestia-mesh: HESTIA_MESH_PLUGIN is unset and has no default.\n"
        "  This CLI speaks AS a member: every act it sends is witnessed under that identity.\n"
        "  Guessing would file your work in another member's trust record.\n"
        "  Set it to your own member id, e.g.:  HESTIA_MESH_PLUGIN=claude-code "
        + " ".join([os.path.basename(sys.argv[0])] + sys.argv[1:]) + "\n"
    )
    sys.exit(2)
# Derived from the identity above, so it cannot drift to a different member than PLUGIN.
HOST = os.environ.get("HESTIA_MESH_HOST_AGENT", f"{PLUGIN}-cli")

def post(payload, hdrs={}):
    req = urllib.request.Request(EP, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream", **hdrs})
    r = urllib.request.urlopen(req, timeout=5)
    return r.read().decode(), r.headers.get("mcp-session-id")

def rpc(h, name, args):
    body, _ = post({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                    "params": {"name": name, "arguments": args}}, h)
    for line in body.splitlines():
        if line.startswith("data: {"):
            return json.loads(json.loads(line[6:])["result"]["content"][0]["text"])
    # No `data:` frame at all. Returning {} here made an unparseable response
    # indistinguishable from an empty inbox — see the exit-code note in main().
    return {"_hestia_error": {"code": "hestia_mesh.no_data_frame",
                              "message": f"{name}: response carried no data: frame"}}


def failed(out):
    """A tool call the DAEMON refused still arrives over a 200 with a JSON-RPC result.

    The refusal is in the payload (`_hestia_error`), so exiting 0 on it reported a
    rejected notice as a sent one. That is the failure this repo already writes down
    twice: a refusal is only worth the caller that hears it (#108's rc=2 rendering as
    an empty inbox), and session-mesh-inbox.sh:35-45 exists precisely to say "could not
    read" is not "empty" — but it can only say it if this CLI signals.

    Measured 2026-07-31 before this fix: `send` with an over-length pointer, and `send`
    to a member id that does not exist, BOTH printed `_hestia_error` and exited 0. Any
    caller writing `hestia-mesh.py send ... || handle` never fired, and the sender
    believed a notice was queued that never was.
    """
    return isinstance(out, dict) and ("_hestia_error" in out or "error" in out)

def connect():
    _, sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                              "clientInfo": {"name": "hestia-mesh", "version": "1"}}})
    h = {"mcp-session-id": sid} if sid else {}
    post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, h)
    c = rpc(h, "hestia_connect", {"plugin_id": PLUGIN, "host_agent": HOST,
                                  "instance_name": f"mesh-{PLUGIN}",
                                  **({"role": os.environ["HESTIA_ROLE"]}
                                     if os.environ.get("HESTIA_ROLE") else {})})
    s = c.get("sessionId") or c.get("session_id")
    if not s:
        print(json.dumps({"error": "connect failed", "detail": c}), file=sys.stderr)
        sys.exit(1)
    # Declaring a role and having it TAKE are different events. A typo, or an
    # unpublished string, normalizes to role:constellation:member and the connect
    # succeeds identically — so "it connected" never verified the role. Say so on
    # stderr (never stdout: callers parse that as JSON) when the daemon reports the
    # declaration did not survive. Older daemons omit the field; stay quiet then
    # rather than crying wolf about a readback that does not exist yet.
    declared = os.environ.get("HESTIA_ROLE")
    if declared and c.get("roleDeclarationHonored") is False:
        print(f"hestia-mesh: WARNING: declared HESTIA_ROLE={declared!r} but this session "
              f"is {c.get('constellationRole')!r}"
              f"{' (reused session keeps its minted role)' if c.get('reused') else ''}"
              " — acts land on that grain, not the one you declared.", file=sys.stderr)
    return h, s

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("peek", "drain", "send", "unanswered"):
        print(__doc__); sys.exit(2)
    cmd = sys.argv[1]
    h, s = connect()
    if cmd in ("peek", "drain"):
        out = rpc(h, "hestia_member_inbox", {"session_id": s, "peek": cmd == "peek"})
    elif cmd == "unanswered":
        args = {"session_id": s}
        if len(sys.argv) > 2:
            args["older_than_secs"] = int(sys.argv[2])
        out = rpc(h, "hestia_member_unanswered", args)
    else:
        if len(sys.argv) < 5:
            print("usage: hestia-mesh.py send <to_plugin_id> <kind> <pointer_uri> [re_notice_id]")
            sys.exit(2)
        args = {"to_plugin_id": sys.argv[2], "kind": sys.argv[3],
                "pointer_uri": sys.argv[4], "session_id": s}
        if len(sys.argv) > 5:
            args["in_reply_to"] = int(sys.argv[5])
        out = rpc(h, "hestia_member_notify", args)
    # stdout keeps carrying the full payload either way — callers parse it as JSON and
    # the error body is the diagnostic. Only the exit code changes: 3 = the daemon
    # answered and refused, distinct from 2 (usage/identity) and 1 (connect failed), so
    # a caller can tell "I asked wrong" from "it said no" from "I never got there".
    print(json.dumps(out, indent=1))
    if failed(out):
        sys.exit(3)

if __name__ == "__main__":
    main()
