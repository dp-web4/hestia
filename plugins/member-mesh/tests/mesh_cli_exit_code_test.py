#!/usr/bin/env python3
"""A daemon refusal must reach the CLI's caller as a non-zero exit code.

The bug: `hestia_member_notify` refusals arrive over a 200 with a well-formed
JSON-RPC result whose payload is `{"_hestia_error": ...}`. hestia-mesh.py printed
that payload and exited 0, so:

    hestia-mesh.py send <to> <kind> <pointer> || handle_failure

never fired, and the sender believed a notice was queued that never was. Measured
2026-07-31 against the live daemon on CBP: an over-length pointer and an unknown
recipient BOTH exited 0.

This is the same class the repo already names twice — "a refusal is only worth the
caller that hears it" (#108) — and session-mesh-inbox.sh:35-45 is written on the
assumption that this CLI signals failure by exit code. It didn't.

Drives the REAL hestia-mesh.py against a stub MCP daemon, same no-test-seam posture
as the other tests here: nothing in the CLI knows it is under test.

Follow-up (kimi-code's nit 1 on #135, sharpened by measurement): the fix above covered
only refusals that arrive as a well-formed `result` payload. Every OTHER way the daemon
can say no escaped as an uncaught Python traceback — rc=1 with an EMPTY stdout, which is
the "I never got there" code, and which breaks the stdout-carries-the-payload contract
that #135 itself established. Confirmed live against the daemon on CBP 2026-07-31:

  unknown method     -> {"jsonrpc":"2.0","id":9,"error":{"code":-32601,...}}  (no `result`)
  stale session id   -> HTTP 404 "Session not found"
  no session id      -> HTTP 422

The first KeyError'd on ["result"]; the other two raised HTTPError out of urlopen. So
`failed()`'s second key `"error"` — the one the nit asked about — was defending a shape
that could not reach it, because rpc() crashed one layer earlier.

Cases:
  A  send refused by the daemon        -> rc=3, and the error payload still on stdout
  B  send accepted                     -> rc=0
  C  peek refused by the daemon        -> rc!=0, so "could not read" != "empty inbox"
  D  response carrying no data: frame  -> rc!=0, not a silent empty result
  E  missing HESTIA_MESH_PLUGIN        -> rc=2 (unchanged; identity != refusal)
  F  JSON-RPC protocol error envelope  -> rc=3 + payload on stdout, not a traceback
  G  daemon answers a non-2xx          -> rc=3 + payload on stdout, not a traceback
  H  result frame in an unknown shape  -> rc=3 + payload on stdout, not a traceback
  I  nothing listening at all          -> rc=1, the one case that IS "never got there"
  J  D/G/H name what DID arrive        -> body excerpt in the payload (nit 2)
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
# The seam is on the HARNESS, not on the CLI: harness_toll_test.py points this at a
# deliberately crashing stub to prove the toll survives. Nothing in hestia-mesh.py
# knows it is under test, which is the posture this file's docstring commits to.
CLI = os.environ.get("HESTIA_MESH_CLI") or os.path.join(os.path.dirname(HERE), "hestia-mesh.py")

# What the stub returns for the next tools/call, set per case.
MODE = {"tool": "ok"}


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or "{}")
        method = body.get("method")

        if method == "initialize":
            return self._json({"jsonrpc": "2.0", "id": body["id"],
                               "result": {"protocolVersion": "2024-11-05"}},
                              sid="stub-session")
        if method == "notifications/initialized":
            self.send_response(202)
            self.end_headers()
            return

        name = body.get("params", {}).get("name")
        if name == "hestia_connect":
            return self._sse(body["id"], {"sessionId": "s-1", "constellationRole":
                                          "role:constellation:member"})

        if MODE["tool"] == "no_frame":
            # A 200 whose body has no `data:` line at all — the shape that used to
            # collapse to {} and print as a successful empty result.
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b": keepalive\n\n")
            return
        if MODE["tool"] == "rpc_error":
            # A JSON-RPC PROTOCOL error: `error` instead of `result`, so indexing
            # ["result"] raised KeyError. Shape copied from the live daemon.
            return self._frame({"jsonrpc": "2.0", "id": body["id"],
                                "error": {"code": -32601, "message": "no/such/method"}})
        if MODE["tool"] == "http_error":
            # What a stale mcp-session-id actually returns. urlopen raises HTTPError.
            raw = b'{"error": "operator authentication failed"}'
            self.send_response(404)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if MODE["tool"] == "bad_shape":
            # 200, well-formed JSON-RPC result, but not the content shape we index.
            return self._frame({"jsonrpc": "2.0", "id": body["id"],
                                "result": {"content": []}})
        if MODE["tool"] == "refuse":
            return self._sse(body["id"], {"_hestia_error": {
                "code": "hestia.member_notify_bad_pointer",
                "message": "pointer_uri must be a single-line pointer (<=512 bytes)",
                "data": {"pointer_len": 672}}})
        return self._sse(body["id"], {"queued_id": 999, "in_reply_to": 444,
                                      "binding_verified": True})

    def _json(self, payload, sid=None):
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        if sid:
            self.send_header("mcp-session-id", sid)
        self.end_headers()
        self.wfile.write(raw)

    def _sse(self, rid, obj):
        return self._frame({"jsonrpc": "2.0", "id": rid,
                            "result": {"content": [{"type": "text",
                                                    "text": json.dumps(obj)}]}})

    def _frame(self, envelope):
        raw = f"event: message\ndata: {json.dumps(envelope)}\n\n".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


# Every subprocess in this file must point HESTIA_MESH_STATE at a tempdir. Without it
# the successful-send case (D) appended a row to the OPERATOR's real ledger at
# ~/.local/state/hestia-mesh/sent/test-member.jsonl — reproduced on CBP, one row dated
# 2026-08-26T13:22, written by a test run (codex, PR #649). A test that mutates live
# member state is a worse defect than the duplicate the guard prevents, and nothing in
# the suite would have said so; the guard only surfaced it by being the first thing to
# WRITE there from a test path. resend_guard_test.py property 6 pins the path itself.
STATE = tempfile.mkdtemp(prefix="mesh-cli-exit-code-")


def base_env(**extra):
    env = dict(os.environ, HESTIA_MESH_PLUGIN="test-member", HESTIA_MESH_STATE=STATE,
               **extra)
    env.pop("HESTIA_ROLE", None)
    return env


def run(args, env_extra=None, mode="ok"):
    MODE["tool"] = mode
    env = base_env(HESTIA_ENDPOINT=EP)
    env.update(env_extra or {})
    p = subprocess.run([sys.executable, CLI] + args, capture_output=True, text=True,
                       env=env, timeout=20)
    return p.returncode, p.stdout, p.stderr


FAILURES = []


def check(name, cond, detail=""):
    """`cond` may be a bool or a zero-arg callable.

    Pass a callable whenever computing the condition can raise on the very input the
    case exists to catch -- `json.loads(out)` on the empty stdout of a crashing CLI is
    the case that motivated this. An eager argument is evaluated BEFORE check() is
    entered, so the raise escapes to __main__ and takes the rest of the run with it.
    A raising callable is a FAIL carrying the exception, and the run continues.
    """
    if callable(cond):
        try:
            cond = bool(cond())
        except Exception as e:
            cond, detail = False, f"raised {type(e).__name__}: {e}"
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  -- {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def report():
    """Print the toll and exit. Called on the clean path AND from the death guard."""
    if FAILURES:
        print(f"\nFAILED ({len(FAILURES)} recorded): {', '.join(FAILURES)}", flush=True)
        sys.exit(1)
    print("\nAll cases passed.", flush=True)


def _death_guard(exc_type, exc, tb):
    """A raise out of the case body must not be able to under-report the toll.

    The callable form of check() covers the checks that remember to use it. This covers
    everything else -- and it is the half that matters, because the failure mode is
    silent: an uncaught exception exits 1, and a clean `FAILED:` exit is ALSO 1, so CI
    cannot tell them apart. The crashed run simply never prints its toll line, and an
    absent count reads as a smaller one. That is how this file reported "13 red" for a
    run whose real toll was 15 (PR #137).

    os._exit because sys.exit() from inside an excepthook is already-unwinding and does
    not reliably set the status; flush explicitly since os._exit skips it.

    WHAT THIS DOES NOT COVER. sys.excepthook is main-thread only, and the stub server
    runs in a daemon thread. Case bodies all run on the main thread, so the toll is
    covered -- but do not read the guard as wider than that. Adding threading.excepthook
    would NOT close it either, and would look like it did: socketserver catches a raise
    inside a request handler in handle_error() and prints it to stderr itself, so NEITHER
    hook ever sees the case that actually threatens this file. Measured, not assumed --
    a probe raising in do_POST fires neither hook. A handler death instead surfaces as a
    client-side RemoteDisconnected, i.e. as a case FAILING, which is the honest shape.
    """
    traceback.print_exception(exc_type, exc, tb)
    FAILURES.append(f"!! HARNESS DIED: {exc_type.__name__}: {exc}")
    print("\n!! the harness raised out of the case body. Every check after this point was\n"
          "!! NEVER EVALUATED -- the toll below is a FLOOR, not the count.", flush=True)
    print(f"\nFAILED ({len(FAILURES)} recorded, TRUNCATED): {', '.join(FAILURES)}", flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(1)


sys.excepthook = _death_guard


if __name__ == "__main__":
    srv = HTTPServer(("127.0.0.1", 0), Stub)
    EP = f"http://127.0.0.1:{srv.server_port}/mcp"
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    print("mesh CLI exit-code test")

    rc, out, _ = run(["send", "kimi-code", "reply", "p.md#x", "444"], mode="refuse")
    check("A  refused send exits non-zero", rc != 0, f"rc={rc}")
    check("A  refused send exits 3 specifically", rc == 3, f"rc={rc}")
    check("A  error payload still on stdout", "_hestia_error" in out, out[:120])

    rc, out, _ = run(["send", "kimi-code", "reply", "p.md#x", "444"], mode="ok")
    check("B  accepted send exits 0", rc == 0, f"rc={rc}")
    check("B  receipt on stdout", "queued_id" in out, out[:120])

    rc, out, _ = run(["peek"], mode="refuse")
    check("C  refused peek exits non-zero -- 'could not read' != 'empty'", rc != 0, f"rc={rc}")

    rc, out, _ = run(["drain"], mode="no_frame")
    check("D  response with no data: frame exits non-zero", rc != 0, f"rc={rc}")

    rc, out, err = run(["send", "kimi-code", "reply", "p.md#x"],
                       env_extra={"HESTIA_MESH_PLUGIN": ""}, mode="ok")
    check("E  missing identity still exits 2 (unchanged)", rc == 2, f"rc={rc}")

    # F/G/H: the daemon answered and declined, but not as a `result` payload. Each of
    # these exited 1 with a traceback and empty stdout on the CLI as merged in #135.
    for label, mode in (("F  JSON-RPC protocol error", "rpc_error"),
                        ("G  non-2xx from the daemon", "http_error"),
                        ("H  unknown result shape", "bad_shape")):
        rc, out, err = run(["peek"], mode=mode)
        check(f"{label} exits 3, not 1", rc == 3, f"rc={rc}")
        check(f"{label} keeps the payload on stdout", "_hestia_error" in out, f"stdout={out[:80]!r}")
        check(f"{label} does not traceback", "Traceback" not in err, err.strip()[-90:])

    # J (nit 2): naming the tool is not enough — the operator needs what DID arrive,
    # and the response is gone by the time they go looking.
    rc, out, _ = run(["drain"], mode="no_frame")
    check("J  no_data_frame names what did arrive", "body_excerpt" in out, f"stdout={out[:160]!r}")
    rc, out, _ = run(["peek"], mode="http_error")
    check("J  http_error carries the response body", "operator authentication failed" in out,
          f"stdout={out[:160]!r}")

    # K: session-mesh-inbox.sh reports a non-zero rc by printing the first two lines of
    # STDERR. Those two lines used to be a traceback header; if the diagnosis moves to
    # stdout (which that caller discards) the branch goes correct-but-mute.
    for label, mode in (("K  payload refusal", "refuse"), ("K  transport refusal", "http_error")):
        rc, out, err = run(["peek"], mode=mode)
        first2 = "\n".join(err.strip().splitlines()[:2])
        check(f"{label} names itself in stderr line 1", "the daemon refused" in first2,
              f"stderr[:2]={first2[:100]!r}")
        # lazy: on a crashing CLI `out` is '', and an eager json.loads('') would raise
        # before check() is entered and abort the run three checks early.
        check(f"{label} stdout stays pure JSON", lambda o=out: json.loads(o) is not None, repr(out[:80]))

    dead = f"http://127.0.0.1:{srv.server_port}/mcp"
    srv.shutdown()
    srv.server_close()  # release the port, so I below is refused rather than timing out

    # I: the one case that really is "I never got there" — nothing listening. Must stay
    # rc=1 and must NOT be reported as a refusal, or the trio collapses again.
    p = subprocess.run([sys.executable, CLI, "peek"], capture_output=True, text=True,
                       env=base_env(HESTIA_ENDPOINT=dead), timeout=20)
    check("I  nothing listening exits 1 (not 3)", p.returncode == 1, f"rc={p.returncode}")
    check("I  nothing listening does not traceback", "Traceback" not in p.stderr,
          p.stderr.strip()[-90:])
    report()
