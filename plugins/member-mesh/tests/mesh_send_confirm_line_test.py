#!/usr/bin/env python3
"""A successful send must say so in a line that survives `2>&1 | tail -N`.

The bug, measured rather than imagined. Notices **743 and 744** (2026-08-03,
claude-code -> kimi-code) carry an identical pointer 5.6 seconds apart. kimi-code
flagged the duplicate on the mesh; the producer was in the *reading* of a success,
not in any error path — both sends worked.

    05:49:25  hestia-mesh.py send kimi-code reply "$(cat /tmp/ptr.txt)" 723 2>&1 | tail -5
              ->   "mailbox_reads": 5220
                  },
                  "to_plugin_id": "kimi-code",
                  "witnessEntryHash": "8fc1a741..."
                  }
    05:49:31  (same pointer, resent)

`send` prints its payload as sorted JSON at `indent=1`. The only proof of delivery,
`queued_id`, sorts into the MIDDLE — after `binding_verified`, `egress_queued_to`,
`in_reply_to`, `kind` — and is followed by a seven-line nested
`recipient_liveness_evidence`. So the last five lines of a *successful* send are the
tail of the liveness blob and a closing brace: byte-for-byte as uninformative as a
failure. The pipe also eats the exit code, so rc=0 never reached the caller either.

The asymmetry is the defect: #135 gave a refusal a sentence on stderr
(`summarize()`), and gave a success nothing. A caller who cannot see success retries,
and a retry on this surface is a duplicate wake — the notice is queued twice and the
recipient burns a session on the second.

Same no-test-seam posture as the other tests in this directory: the real
hestia-mesh.py is driven against a stub MCP daemon and nothing in it knows it is
under test.

Cases:
  A  a successful send names queued_id on stderr
  B  that line is the LAST line of the `2>&1` stream (the property `tail -N` needs)
  C  it survives an actual `tail -5` over the combined stream — the measured shape
  D  stdout stays a single parseable JSON document (json.load(sys.stdin) callers)
  E  a REFUSED send emits no success line, and still exits 3
  F  peek/drain get no "sent" line — the claim is about sends
  G  an egress-routed payload with no queued_id says ABSENT, not a bare success
  H  an unverified binding is marked on the line, not silently dropped
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.environ.get("HESTIA_MESH_CLI") or os.path.join(os.path.dirname(HERE), "hestia-mesh.py")

MODE = {"tool": "ok"}

# The real payload shape, copied from the live daemon's answer to the send that
# produced notice 743. Key order is irrelevant (the CLI sorts), but the SIZE of
# recipient_liveness_evidence is not: it is what pushes queued_id out of `tail -5`.
OK_PAYLOAD = {
    "binding_verified": True,
    "egress_queued_to": None,
    "in_reply_to": 723,
    "kind": "reply",
    "queued_id": 743,
    "recipient_liveness": "live",
    "recipient_liveness_evidence": {
        "first_seen": "2026-07-25T20:04:13.944689644+00:00",
        "last_inbox_touch": "2026-08-03T05:49:11.000000000+00:00",
        "live_within_secs": 300,
        "mailbox_reads": 5220,
    },
    "to_plugin_id": "kimi-code",
    "witnessEntryHash": "8fc1a741bd35a458a30c0684c414d2eaef2e7f59a0f61868b6e375ca47df2cd6",
}


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
            return self._sse(body["id"], {"sessionId": "s-1"})
        if MODE["tool"] == "refuse":
            return self._sse(body["id"], {"_hestia_error": {
                "code": "hestia.member_notify_bad_pointer",
                "message": "pointer_uri must be a single-line pointer (<=512 bytes)",
                "data": {"pointer_len": 518}}})
        if MODE["tool"] == "egress":
            p = dict(OK_PAYLOAD, egress_queued_to="thor", recipient_liveness=None)
            p.pop("queued_id")
            return self._sse(body["id"], p)
        if MODE["tool"] == "unverified":
            return self._sse(body["id"], dict(OK_PAYLOAD, binding_verified=False))
        if MODE["tool"] == "inbox":
            return self._sse(body["id"], {"notices": [], "total": 0})
        return self._sse(body["id"], dict(OK_PAYLOAD))

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
        raw = ("event: message\ndata: " + json.dumps(
            {"jsonrpc": "2.0", "id": rid,
             "result": {"content": [{"type": "text", "text": json.dumps(obj)}]}})
            + "\n\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


STATE_DIR = tempfile.mkdtemp(prefix="mesh-confirm-state-")


def run(args, mode="ok", combine=False):
    """combine=True reproduces `2>&1` — one stream, real interleaving, real ordering.

    Not a simulation: stdout and stderr share a pipe exactly as the shell arranges
    it, which is the only way the buffering question (block-buffered stdout vs
    unbuffered stderr) is answered honestly rather than assumed.
    """
    MODE["tool"] = mode
    # HESTIA_MESH_STATE: this test repeats the IDENTICAL send six times, which is what
    # a duplicate looks like to already_sent(). Two things follow and both are the
    # test's job, not the guard's. Point the state dir at a tempdir so a test run can
    # never append to the operator's real ledger (it would have, before this line),
    # and disable the resend window so the repeats are permitted -- this file is
    # pinning confirm(), and an opt-out that is visible in the env beats a guard that
    # quietly does not apply.
    env = dict(os.environ, HESTIA_ENDPOINT=EP, HESTIA_MESH_PLUGIN="test-member",
               HESTIA_MESH_STATE=STATE_DIR, HESTIA_MESH_RESEND_WINDOW="0")
    env.pop("HESTIA_ROLE", None)
    # Explicit stdout=PIPE rather than capture_output=True: the two cannot be combined
    # with an explicit stderr=, and capture_output is what makes `2>&1` unrepresentable.
    p = subprocess.run([sys.executable, CLI] + args, text=True, env=env, timeout=20,
                       stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT if combine else subprocess.PIPE)
    return p.returncode, p.stdout, (p.stderr or "")


FAILURES = []


def check(name, cond, detail=""):
    if callable(cond):
        try:
            cond = bool(cond())
        except Exception as e:
            cond, detail = False, f"raised {type(e).__name__}: {e}"
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  -- {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


SEND = ["send", "kimi-code", "reply", "shared-context/forum/x.md#t", "723"]


def main():
    print("A  a successful send names queued_id on stderr")
    rc, out, err = run(SEND)
    check("rc is 0", rc == 0, f"rc={rc}")
    check("stderr names the queued_id", "queued_id=743" in err, repr(err[-200:]))
    check("stderr names the recipient", "to=kimi-code" in err, repr(err[-200:]))

    print("B  the success line is LAST in the combined stream")
    rc, both, _ = run(SEND, combine=True)
    lines = [l for l in both.splitlines() if l.strip()]
    check("last line is the success line",
          bool(lines) and lines[-1].startswith("hestia-mesh: sent —"),
          f"last={lines[-1]!r}" if lines else "no output")

    print("C  it survives `tail -5` over the combined stream (the measured shape)")
    tail5 = "\n".join(both.splitlines()[-5:])
    check("tail -5 proves delivery", "queued_id=743" in tail5,
          "this is exactly the 743/744 duplicate: " + repr(tail5))
    check("tail -1 alone is sufficient", "queued_id=743" in both.splitlines()[-1])

    print("D  stdout is still one parseable JSON document")
    rc, out, err = run(SEND)
    check("json.load(stdout) works", lambda: json.loads(out)["queued_id"] == 743)
    check("no success line leaked onto stdout", "hestia-mesh: sent" not in out)

    print("E  a refused send gets no success line and still exits 3")
    rc, out, err = run(SEND, mode="refuse")
    check("rc is 3", rc == 3, f"rc={rc}")
    check("no success line", "hestia-mesh: sent" not in err, repr(err))
    check("the refusal line is still there", "the daemon refused" in err, repr(err))

    print("F  peek/drain get no success line")
    for cmd in ("peek", "drain"):
        rc, out, err = run([cmd], mode="inbox")
        check(f"{cmd} emits no send line", "hestia-mesh: sent" not in err, repr(err))

    print("G  no queued_id says ABSENT rather than reading as a plain success")
    rc, out, err = run(SEND, mode="egress")
    check("rc is 0", rc == 0, f"rc={rc}")
    check("ABSENT is stated", "queued_id=ABSENT" in err, repr(err))

    print("H  an unverified binding is marked on the line")
    rc, out, err = run(SEND, mode="unverified")
    check("UNVERIFIED is stated", "UNVERIFIED" in err, repr(err))
    check("the bound id is still named", "in_reply_to=723" in err, repr(err))

    report()


def report():
    if FAILURES:
        print(f"\nFAILED ({len(FAILURES)} recorded): {', '.join(FAILURES)}", flush=True)
        sys.exit(1)
    print("\nAll cases passed.", flush=True)


def _death_guard(exc_type, exc, tb):
    """A raise out of a case body must not under-report the toll (sibling test, #137).

    Earned here on the first run: a `capture_output`/`stderr=` ValueError in run() took
    the process down after case A, and the two real FAILs never reached a `FAILED:`
    line. An uncaught exception exits 1 and a clean toll exits 1, so the count is the
    only thing distinguishing them — and the crashed run prints no count at all.
    Main-thread only (sys.excepthook is); every case body runs there.
    """
    import traceback
    traceback.print_exception(exc_type, exc, tb)
    print(f"\n!! run died in-flight after {len(FAILURES)} recorded failure(s): "
          f"{', '.join(FAILURES) or 'none yet'} -- the toll below is a LOWER BOUND",
          flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(1)


sys.excepthook = _death_guard

srv = HTTPServer(("127.0.0.1", 0), Stub)
EP = f"http://127.0.0.1:{srv.server_address[1]}/mcp"
threading.Thread(target=srv.serve_forever, daemon=True).start()

if __name__ == "__main__":
    main()
