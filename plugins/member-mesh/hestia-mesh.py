#!/usr/bin/env python3
"""hestia-mesh — member-mesh CLI for a local hestia member (Kimi's send/receive surface).

Usage:
  hestia-mesh.py peek                                    # non-consuming inbox list
  hestia-mesh.py drain                                   # consume-once drain (act on results!)
  hestia-mesh.py send <to_plugin_id> <kind> <pointer_uri> [re_notice_id]  # witnessed notify
  hestia-mesh.py unanswered [older_than_secs]            # what has no bound response

Env: HESTIA_ENDPOINT (default http://127.0.0.1:7711/mcp),
     HESTIA_MESH_TIMEOUT (seconds, default 30 — the daemon serializes all members),
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
Exit codes: 0 ok | 1 never got there (refused/DNS) | 2 usage | 3 daemon answered and
declined | 4 UNDETERMINED — no answer in time, the write MAY have landed; do not
blind-retry a `send` on 4 (issue #523) | 5 REFUSED LOCALLY — this seat already queued a
byte-identical notice inside the resend window; nothing was sent. Override with
HESTIA_MESH_RESEND=1, or widen/narrow with HESTIA_MESH_RESEND_WINDOW (seconds, default
900; 0 disables the guard; an unparseable value warns and falls back to 900 rather than
blocking the send). The identity is (seat, endpoint, recipient, kind, pointer_uri,
in_reply_to) — a notice aimed at a different HESTIA_ENDPOINT is a different act.
"""
import hashlib, json, os, sys, time, urllib.error, urllib.request

EP = os.environ.get("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")

# The daemon holds ONE global lock and its latency is linear in concurrent members, so
# the response tail is not a fixed distance below any ceiling we pick. Measured
# 2026-08-18 against a healthy daemon in one wake: bare `initialize` took 6.944s while
# three seats, three watchers and a cargo run were live, and 0.001s minutes later. The
# old hard-coded 5s sat INSIDE that tail. Raising it shrinks the failure window; only
# the Undetermined split below makes the report sound at any value.
TIMEOUT = float(os.environ.get("HESTIA_MESH_TIMEOUT", "30"))

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
    """No answer at all: connection refused, DNS. rc=1 — "I never got there".

    A TIMEOUT used to be in this list and is not a member of it. See Undetermined.
    """


class Undetermined(Exception):
    """The request went out and no answer came back in time. rc=4 — "I do not know".

    `urlopen(timeout=)` bounds the WHOLE exchange, including reading the response. A
    POST the daemon received, processed and COMMITTED — but answered slowly — raises
    the same OSError as connection-refused. Collapsing the two makes the CLI report a
    landed write as `rc=1 "I never got there"`.

    Measured 2026-08-18 (issue #523): a `send` binding a reply to notice 3049 exited
    rc=1 "timed out", and 3049 was discharged from `unanswered` immediately after. The
    reply had landed.

    This matters because rc decides what the CALLER does next. rc=1 invites a retry;
    `send` has no idempotency key, so a retry after a committed write duplicates the
    notice. rc=4 means: it may have landed, and a blind retry is not safe.

    Deliberately NOT rc=1 and NOT rc=3. rc=3 is DaemonRefusal — "something answered and
    declined", which is a decision. This is the absence of one.
    """


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
        r = urllib.request.urlopen(req, timeout=TIMEOUT)
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
    except TimeoutError as e:
        # Bare socket timeout: the read deadline expired. Undetermined, not unreachable.
        raise Undetermined(f"no answer within {TIMEOUT:g}s ({e or 'read timed out'})") from None
    except OSError as e:  # URLError (connection refused, DNS) and wrapped timeouts.
        # urllib wraps a CONNECT-phase timeout in URLError; unwrap before classifying,
        # because the string "timed out" on the outside of a URLError is the same event.
        reason = getattr(e, "reason", None)
        if isinstance(reason, TimeoutError) or isinstance(e, TimeoutError):
            raise Undetermined(f"no answer within {TIMEOUT:g}s ({reason or e})") from None
        raise Unreachable(reason or e) from None


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

def keep_a_copy(payload):
    """A consume-once drain must leave a durable copy BEFORE anyone reads stdout.

    `drain` empties the mailbox server-side; the notices exist afterwards only in
    this process's stdout. `fire-*.sh` has always known that — it writes the primer
    to the member's home BEFORE the sender filter runs, which is the only reason
    notice 160 survived being dropped by an allowlist (fire_sender_allowlist_test.py).
    The CLI path had no such copy, and SessionStart hooks tell every member to run
    `hestia-mesh.py drain` in-session.

    Measured 2026-08-18 (claude-code, CBP): a drain returned seven notices; the
    caller piped stdout through a summarizer that printed only the ids. Notice 3097
    was consumed, never read, and unrecoverable — `hestia_query_history` filtered by
    tool_name returns nothing on this store, so the only remedy was asking the sender
    to send it again. One lossy consumer, one destroyed notice, no error anywhere.

    Best effort by construction: the mailbox is already empty by the time we are
    called, so a failed write must not also fail the command — but it must be LOUD,
    and it dumps the payload to stderr so a lossy stdout consumer is not the last
    copy. stdout stays pure JSON (the contract in act()).
    """
    notices = (payload or {}).get("notices") if isinstance(payload, dict) else None
    if not notices:
        return
    state = os.environ.get("HESTIA_MESH_STATE") or os.path.join(
        os.path.expanduser("~"), ".local", "state", "hestia-mesh")
    d = os.path.join(state, "drained", PLUGIN or "unknown")
    ids = ",".join(str(n.get("id")) for n in notices if isinstance(n, dict))
    try:
        os.makedirs(d, exist_ok=True)
        os.chmod(d, 0o700)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        path = os.path.join(d, f"drain-{stamp}-{os.getpid()}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=1)
        os.chmod(path, 0o600)
        print(f"hestia-mesh: drained {len(notices)} notice(s) [{ids}] — copy kept at {path}",
              file=sys.stderr)
    except Exception as e:
        print(f"hestia-mesh: WARNING: could not keep a copy of the drain ({e}). "
              f"The mailbox is ALREADY EMPTY and stdout is the only remaining copy of "
              f"notice(s) [{ids}] — full payload repeated on stderr below.", file=sys.stderr)
        print(json.dumps(payload, indent=1), file=sys.stderr)


RESEND_WINDOW_DEFAULT = 900.0
_RESEND_WINDOW_WARNED = set()


def resend_endpoint():
    """The daemon this seat is talking to, normalized — part of the dedupe identity.

    HESTIA_ENDPOINT is configurable but the ledger is one file per seat, so without this
    the same tuple sent to a DIFFERENT mesh would read as a repeat and be refused (codex,
    PR #649). Normalization is deliberately shallow (case, trailing slash): two spellings
    of one host read as two endpoints and PERMIT the send, which is the fail-open
    direction. The reverse — collapsing two real endpoints — would block one of them.
    """
    return (EP or "").strip().rstrip("/").lower()


def resend_key(args):
    """The identity of a notice for dedupe purposes: who/what/where/answering-what."""
    return hashlib.sha256("\u0000".join([
        PLUGIN or "?", resend_endpoint(), str(args.get("to_plugin_id")),
        str(args.get("kind")), str(args.get("pointer_uri")),
        str(args.get("in_reply_to")),
    ]).encode("utf-8")).hexdigest()


def resend_window():
    """The configured window in seconds; an unparseable value falls back to the default.

    Parsed here rather than at the use site because the use site sits inside a fail-open
    contract that this call was outside of: `float(os.environ[...])` on a malformed value
    raised an uncaught ValueError and exited rc=1 BEFORE notify, so a typo in an env var
    could block the mesh — precisely what the guard promises cannot happen (codex found
    and reproduced this on PR #649).

    A malformed value falls back to the default rather than disabling the guard: the
    thing that must not happen is a BLOCKED send, and the default window blocks nothing
    except a byte-identical repeat. To actually turn the guard off, set it to 0.
    """
    raw = os.environ.get("HESTIA_MESH_RESEND_WINDOW")
    if raw is None:
        return RESEND_WINDOW_DEFAULT
    try:
        return float(raw)
    except (TypeError, ValueError):
        if raw not in _RESEND_WINDOW_WARNED:
            _RESEND_WINDOW_WARNED.add(raw)
            print(f"hestia-mesh: WARNING: HESTIA_MESH_RESEND_WINDOW={raw!r} is not a "
                  f"number - using the {RESEND_WINDOW_DEFAULT:g}s default. Set it to 0 "
                  f"to disable the duplicate guard.", file=sys.stderr)
        return RESEND_WINDOW_DEFAULT


def resend_ledger_path():
    state = os.environ.get("HESTIA_MESH_STATE") or os.path.join(
        os.path.expanduser("~"), ".local", "state", "hestia-mesh")
    return os.path.join(state, "sent", f"{PLUGIN or 'unknown'}.jsonl")


def already_sent(args, now=None):
    """Has this seat already queued a byte-identical notice inside the window?

    #135 gave a successful `send` a loud stderr line because two identical notices
    (743/744, 2026-08-03, claude-code -> kimi-code) were queued 5.6s apart: the first
    send SUCCEEDED and was read through `| tail -5`, which showed the closing brace of
    the liveness blob and nothing that said it worked. confirm() fixed the legibility.

    It did not fix the duplicate. Measured again 2026-08-26, same seat: EIGHT bound
    dispositions were sent rc=0, the caller piped the run through `tail -40`, lost its
    own per-send summary lines, and RE-RAN THE SCRIPT TO SEE THEM. Every peer got the
    notice twice. The re-run was not a retry — the sender never doubted delivery; it
    wanted the output. A louder confirmation cannot prevent that, because the second
    invocation is not asking the same question the first one answered.

    So the fix has to be on the WRITE, not on the report. This is a local, best-effort
    ledger keyed on (plugin, to, kind, pointer, in_reply_to) — the whole tuple, so a
    genuine second disposition on the same pointer, or the same pointer bound to a
    different notice, is NOT refused. Only the byte-identical repeat is.

    Deliberately NOT an idempotency key on the daemon: that is the right fix and needs a
    protocol field (`hestia_member_notify` has none). This closes the measured hole from
    the caller side today and does not preclude it.

    Fail-open by construction, like keep_a_copy(): a guard that blocks the mesh because
    its own state file is corrupt would be worse than the duplicate it prevents. Any
    error reading the ledger warns on stderr and permits the send — including a
    malformed window (see resend_window()) and a matching row with an undateable `at`,
    both of which used to raise past this contract and exit rc=1.

    Not recorded on rc=4 (UNDETERMINED) — see record_sent(). Blocking the retry of a
    send that MAY not have landed is the one case where a duplicate beats a silence.
    """
    window = resend_window()
    if window <= 0 or os.environ.get("HESTIA_MESH_RESEND") == "1":
        return None
    now = time.time() if now is None else now
    key = resend_key(args)
    try:
        with open(resend_ledger_path(), encoding="utf-8") as f:
            # Non-object rows are dropped, not raised on: a bare JSON scalar parses fine
            # and then row.get() would AttributeError outside this try - same class of
            # escape as the window parse was.
            rows = [r for r in (json.loads(l) for l in f if l.strip())
                    if isinstance(r, dict)]
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"hestia-mesh: WARNING: resend ledger unreadable ({e}) — "
              f"the duplicate guard is OFF for this call.", file=sys.stderr)
        return None
    for row in reversed(rows):
        if row.get("key") != key:
            continue
        try:
            at = float(row.get("at", 0))
        except (TypeError, ValueError):
            # A matching row we cannot date is a warning-plus-permit, never an
            # exception: half-written state must not be able to stop a send.
            print(f"hestia-mesh: WARNING: the resend ledger row for this notice has a "
                  f"malformed timestamp ({row.get('at')!r}) — the duplicate guard "
                  f"is OFF for this call.", file=sys.stderr)
            return None
        if now - at <= window:
            return row
    return None


def record_sent(args, out):
    """Append one ledger row for a send the daemon confirmed. Best effort, never fatal."""
    # Same predicate the reader uses, not a string compare against "0": WINDOW="0.0"
    # or "-1" disabled the read while still growing a ledger nobody consults.
    if resend_window() <= 0:
        return
    path = resend_ledger_path()
    row = {"at": time.time(), "key": resend_key(args),
           "to": args.get("to_plugin_id"), "kind": args.get("kind"),
           "in_reply_to": args.get("in_reply_to"),
           "pointer_uri": args.get("pointer_uri"),
           "queued_id": (out or {}).get("queued_id")}
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        os.chmod(os.path.dirname(path), 0o700)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        os.chmod(path, 0o600)
    except Exception as e:
        print(f"hestia-mesh: WARNING: could not record the send in the resend ledger "
              f"({e}) — a byte-identical resend will NOT be caught.", file=sys.stderr)


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
    except Undetermined as u:
        # NOT rc=1. The caller must be able to tell "never left" from "may have landed",
        # because only the first one is safe to retry blind.
        print(f"hestia-mesh: UNDETERMINED — {EP} did not answer in time: {u}\n"
              f"  The request may have been COMMITTED. `send` has no idempotency key,\n"
              f"  so retrying may duplicate it. Check `unanswered` (or `peek`) first.",
              file=sys.stderr)
        sys.exit(4)
    except Unreachable as u:
        # The one case that is genuinely rc=1. stderr, because there is no payload to
        # parse — saying so beats a traceback that a caller has to regex.
        print(f"hestia-mesh: no answer from {EP} — {u}", file=sys.stderr)
        sys.exit(1)


def act(cmd):
    h, s = connect()
    if cmd in ("peek", "drain"):
        out = rpc(h, "hestia_member_inbox", {"session_id": s, "peek": cmd == "peek"})
        if cmd == "drain":
            keep_a_copy(out)
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
        dup = already_sent(args)
        if dup is not None:
            age = int(time.time() - float(dup.get("at", 0)))
            print(f"hestia-mesh: REFUSED LOCALLY — this seat queued a byte-identical "
                  f"notice {age}s ago (queued_id={dup.get('queued_id')}). NOTHING WAS "
                  f"SENT. If you meant to send it twice: HESTIA_MESH_RESEND=1 "
                  f"{' '.join(sys.argv[:1] + sys.argv[1:])}", file=sys.stderr)
            sys.exit(5)
        out = rpc(h, "hestia_member_notify", args)
        if not failed(out):
            record_sent(args, out)
    # stdout keeps carrying the full payload either way — callers parse it as JSON and
    # the error body is the diagnostic. Only the exit code changes: 3 = the daemon
    # answered and refused, distinct from 2 (usage/identity) and 1 (connect failed), so
    # a caller can tell "I asked wrong" from "it said no" from "I never got there".
    print(json.dumps(out, indent=1))
    if failed(out):
        summarize(out)
        sys.exit(3)
    confirm(cmd, out)


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


def confirm(cmd, out):
    """The mirror of summarize(): one human line on stderr naming the SUCCESS.

    A refusal got a sentence in #135; a success did not, and the asymmetry produced
    duplicate wakes. `send` returns a sorted, `indent=1` payload in which the only
    proof of delivery — `queued_id` — sits in the MIDDLE, after `binding_verified`,
    `egress_queued_to`, `in_reply_to`, `kind`, and before a seven-line nested
    `recipient_liveness_evidence`. So the fleet's habitual `2>&1 | tail -N` shows the
    tail of the liveness blob and the closing brace, and nothing that says it worked.

    Measured, notices 743/744 (2026-08-03, claude-code -> kimi-code): the same pointer
    was sent twice, 5.6s apart, because the FIRST send — which succeeded, queueing 743
    — was read through `| tail -5` and showed `mailbox_reads`, `to_plugin_id`,
    `witnessEntryHash`, `}`. The resend queued 744 and kimi received the notice twice.
    (The second read failed too, differently: it parsed the JSON but asked for
    `notice_id`/`queued`/`delivered`, none of which this payload has, so `.get` handed
    back three Nones for a call that had just worked. Same class as the daemon's
    `additionalProperties: true` on the request side — a name nobody validates.)

    stderr, not stdout, and only after stdout is flushed: stdout must stay parseable as
    a single JSON document (`json.load(sys.stdin)` is a documented caller shape), and
    the flush is what guarantees this lands LAST rather than first under `2>&1`, where
    a piped stdout is block-buffered and stderr is not. Last is the whole point.
    """
    sys.stdout.flush()
    if cmd != "send":
        return
    qid = out.get("queued_id")
    bits = [f"queued_id={qid}" if qid is not None else "queued_id=ABSENT",
            f"to={out.get('to_plugin_id')}", f"kind={out.get('kind')}"]
    if out.get("in_reply_to") is not None:
        bits.append(f"in_reply_to={out['in_reply_to']}"
                    + ("" if out.get("binding_verified") else " (UNVERIFIED)"))
    if out.get("recipient_liveness"):
        bits.append(f"liveness={out['recipient_liveness']}")
    # ABSENT is not hypothetical: an egress-routed send returns a payload with no
    # queued_id at all, and saying "queued_id=ABSENT" beats printing a bare success.
    print("hestia-mesh: sent — " + " ".join(bits), file=sys.stderr)


if __name__ == "__main__":
    main()
