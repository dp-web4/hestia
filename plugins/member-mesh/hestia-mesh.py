#!/usr/bin/env python3
"""hestia-mesh — member-mesh CLI for a local hestia member (Kimi's send/receive surface).

Usage:
  hestia-mesh.py peek                                    # non-consuming inbox list
  hestia-mesh.py drain                                   # consume-once drain (act on results!)
  hestia-mesh.py send <to_plugin_id> <kind> <pointer_uri> [re_notice_id]  # witnessed notify
  hestia-mesh.py unanswered [older_than_secs]            # what has no bound response

Env: HESTIA_ENDPOINT (default http://127.0.0.1:7711/mcp),
     HESTIA_MESH_PLUGIN (default kimi-code), HESTIA_MESH_HOST_AGENT (default kimi-code-cli),
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
PLUGIN = os.environ.get("HESTIA_MESH_PLUGIN", "kimi-code")
HOST = os.environ.get("HESTIA_MESH_HOST_AGENT", "kimi-code-cli")

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
    return {}

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
    print(json.dumps(out, indent=1))

if __name__ == "__main__":
    main()
