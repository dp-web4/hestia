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
import json, os, sys, urllib.error, urllib.request

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

class Unreachable(Exception):
    """No answer at all: connection refused, DNS, timeout. rc=1 — "I never got there"."""


class DaemonRefusal(Exception):
    """The daemon ANSWERED and declined, below the JSON-RPC payload layer. rc=3.

    Carries a synthesized `_hestia_error` so the stdout contract holds: every path
    that reaches the daemon prints a JSON payload, never a traceback.
    """

    def __init__(self, payload):
        super().__init__(payload)
        self.payload = payload


def excerpt(raw, limit=300):
    """The first bytes of what DID arrive.

    Naming only the tool that failed tells an operator nothing they can act on. The
    first time a shape-error fires against a real proxy truncating SSE, the body is
    the whole diagnosis — and it is exactly what a caller cannot recover afterwards,
    because the response is gone by then.
    """
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    raw = (raw or "").strip()
    return raw[:limit] + (f"… [+{len(raw) - limit} more bytes]" if len(raw) > limit else "")


def shape_error(name, code, message, body):
    return {"_hestia_error": {"code": f"hestia_mesh.{code}",
                              "message": f"{name}: {message}",
                              "data": {"body_excerpt": excerpt(body),
                                       "body_bytes": len(body or "")}}}


def post(payload, hdrs={}):
    req = urllib.request.Request(EP, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream", **hdrs})
    try:
        r = urllib.request.urlopen(req, timeout=5)
        return r.read().decode(), r.headers.get("mcp-session-id")
    except urllib.error.HTTPError as e:
        # The daemon answered — with a non-2xx. urlopen raises here, and an uncaught
        # HTTPError exits 1 with a traceback and an EMPTY stdout, which reads to a
        # caller as "never got there" when in fact it got there and was declined.
        # Measured 2026-07-31 against the live daemon: a stale mcp-session-id returns
        # 404 "Session not found", and a tools/call with no session returns 422. Both
        # exited 1 with a traceback on the CLI as merged in #135.
        # rc=3, not 1: the observable fact is that something answered. Only silence is 1.
        raise DaemonRefusal({"_hestia_error": {
            "code": "hestia_mesh.http_error",
            "message": f"daemon answered HTTP {e.code} ({e.reason})",
            "data": {"status": e.code, "body_excerpt": excerpt(e.read())}}}) from None
    except OSError as e:  # URLError (connection refused, DNS) and socket timeouts.
        raise Unreachable(getattr(e, "reason", None) or e) from None


def rpc(h, name, args):
    body, _ = post({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                    "params": {"name": name, "arguments": args}}, h)
    for line in body.splitlines():
        if not line.startswith("data: {"):
            continue
        try:
            envelope = json.loads(line[6:])
        except json.JSONDecodeError as e:
            return shape_error(name, "unparseable_frame", f"data: frame is not JSON ({e})", body)
        # A JSON-RPC PROTOCOL error has no `result` key at all — the envelope carries
        # `error` instead. Indexing ["result"] raised KeyError here, so this shape also
        # exited 1 with a traceback. Confirmed live on CBP 2026-07-31: an unknown method
        # returns {"jsonrpc":"2.0","id":9,"error":{"code":-32601,...}}. Normalizing it
        # into `_hestia_error` is what makes it exit 3 like any other refusal.
        if "error" in envelope and "result" not in envelope:
            return {"_hestia_error": {
                "code": "hestia_mesh.jsonrpc_error",
                "message": f"{name}: daemon returned a JSON-RPC protocol error",
                "data": {"jsonrpc_error": envelope["error"]}}}
        try:
            return json.loads(envelope["result"]["content"][0]["text"])
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
            return shape_error(name, "unexpected_result_shape",
                               f"result frame not in the expected shape ({type(e).__name__}: {e})",
                               body)
    # No `data:` frame at all. Returning {} here made an unparseable response
    # indistinguishable from an empty inbox — see the exit-code note in main().
    return shape_error(name, "no_data_frame", "response carried no data: frame", body)


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

    On the second key, `"error"` (kimi-code's nit on #135 — two payload shapes trusted,
    one documented): it is NOT the MCP tool layer's shape. Every tool refusal uses the
    `_hestia_error` envelope (ADR-0005 Mechanism A, core/src/server/handler.rs:5); a
    bare `"error"` payload is emitted only by the OPERATOR REST surface in
    core/src/server/http.rs, which this CLI never calls and could not authenticate to.
    So it defended nothing that could reach it — and the JSON-RPC envelope error it
    looks like it was named for never arrived either, because rpc() raised KeyError on
    the missing `result` one layer earlier. It is kept, and now reachable: post() turns
    a non-2xx into a payload carrying the body verbatim, and an operator-surface body
    is exactly that `{"error": ...}` shape.
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
    try:
        act(cmd)
    except DaemonRefusal as r:
        # Same contract as a payload-level refusal: full JSON on stdout, rc=3.
        print(json.dumps(r.payload, indent=1))
        summarize(r.payload)
        sys.exit(3)
    except Unreachable as u:
        # The one case that is genuinely rc=1. stderr, because there is no payload to
        # parse — saying so beats a traceback that a caller has to regex.
        print(f"hestia-mesh: no answer from {EP} — {u}", file=sys.stderr)
        sys.exit(1)


def act(cmd):
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
        summarize(out)
        sys.exit(3)


def summarize(payload):
    """One human line on stderr naming the refusal. Not a duplicate of stdout.

    session-mesh-inbox.sh:35-45 reports a non-zero rc by printing the FIRST TWO LINES
    OF STDERR. Before this change those two lines were "Traceback (most recent call
    last):" and a frame — technically present, operationally useless. Routing the
    diagnosis to stdout as JSON (which that caller discards) would have left the branch
    correct but mute, so the rc gets a sentence to go with it. stdout stays pure JSON.
    """
    err = payload.get("_hestia_error") or payload.get("error") or {}
    if isinstance(err, dict):
        detail = f"{err.get('code', '?')}: {err.get('message', '')}".strip().rstrip(":")
    else:
        detail = str(err)
    print(f"hestia-mesh: the daemon refused this call — {detail}", file=sys.stderr)

if __name__ == "__main__":
    main()
