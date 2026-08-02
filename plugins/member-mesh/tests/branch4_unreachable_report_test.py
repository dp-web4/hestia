#!/usr/bin/env python3
"""Branch 4 (report-unreachable) CI test — the r6-routing exploration's first ask.

When a fire fails, the watcher must REPORT the delivery failure back to each
notice's sender (shared-context/explorations/r6-routing-tcpip-of-trust-2026-07-26
§2, branch 4). Before this, a dead fire and a notice never sent produced
identical observations at both ends: the sender's unanswered view read
"delivered, unanswered" for mail the member never saw.

Drives the REAL `hestia-watch-member.sh` against a stub MCP daemon (in-process
HTTP) and a stub fire command that always fails — same no-test-seam posture as
fire_concurrency_test.py: the test cannot pass by exercising a path only the
test uses.

Four cases:
  A  ordinary notice          -> one `reply` report, bound (in_reply_to=id),
                                 pointer keeps naming the content and gains
                                 `#undelivered:fire-rc=N;via=watch-<member>` —
                                 the fragment names the routing verdict AND the
                                 observer, because the chain cannot otherwise
                                 tell gateway from member (CBP review §4);
                                 primer retained.
  B  ack notice               -> NO report (terminal; loop closed at send).
  C  pointer already carrying #undelivered -> NO report (ICMP-about-ICMP
                                 suppression — reports never report themselves).
  D  daemon denies the report -> watcher journals the failure, keeps the
                                 primer, and KEEPS POLLING (report generation
                                 must not kill the router).
  E  pointer at the 512-byte MTU -> the routing verdict SURVIVES truncation.
                                 The content name is what degrades, never the
                                 `#undelivered` marker — the marker is the
                                 one-hop visited bit case C relies on, so a
                                 truncation that eats it turns suppression off
                                 exactly where pointers are longest.
  G  report receipt           -> the journal line carries the daemon's
                                 recipient_liveness verdict — a report that
                                 itself queued into a name nothing drains must
                                 not read as success (CBP review §5).

Usage: ./branch4_unreachable_report_test.py   (runtime ~25s, deliberate waits)
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
WATCHER = os.path.abspath(os.path.join(HERE, "..", "hestia-watch-member.sh"))

failures = []


def check(label, ok, detail=""):
    failures.append(label) if not ok else None
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))


class StubDaemon:
    """A minimal hestia MCP endpoint: connect, inbox (scripted), unanswered, notify."""

    def __init__(self, notices, notify_error=False):
        self.notices = notices
        self.notify_error = notify_error
        self.notify_calls = []
        self.inbox_calls = 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, hdrs=None):
                self.send_response(code)
                for k, v in (hdrs or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(n) or b"{}")
                method = req.get("method")
                if method == "initialize":
                    return self._send(200, b'{"jsonrpc":"2.0","id":1,"result":{}}',
                                      {"mcp-session-id": "stub-sid"})
                if method == "notifications/initialized":
                    return self._send(202, b"")
                if method != "tools/call":
                    return self._send(400, b"{}")

                tool = req["params"]["name"]
                args = req["params"].get("arguments", {})
                if tool == "hestia_connect":
                    payload = {"sessionId": "stub-session"}
                elif tool == "hestia_member_inbox":
                    outer.inbox_calls += 1
                    # Consume-once: the first drain carries the batch, later
                    # polls are empty — like the real daemon.
                    payload = {"total": len(outer.notices), "notices": outer.notices}
                    outer.notices = []
                elif tool == "hestia_member_unanswered":
                    payload = {"i_owe": [], "owed_to_me": []}
                elif tool == "hestia_member_notify":
                    outer.notify_calls.append(args)
                    if outer.notify_error:
                        payload = {"_hestia_error": {"code": "hestia.stub_deny",
                                                     "message": "stub denies the report"}}
                    else:
                        payload = {"queued_id": 9000 + len(outer.notify_calls),
                                   "witnessEntryHash": "stubhash",
                                   "recipient_liveness": "live"}
                else:
                    payload = {}
                rpc = {"jsonrpc": "2.0", "id": req.get("id", 9),
                       "result": {"content": [{"type": "text",
                                               "text": json.dumps(payload)}]}}
                body = f"data: {json.dumps(rpc)}\n\n".encode()
                return self._send(200, body, {"Content-Type": "text/event-stream"})

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def run_watcher(notices, notify_error=False, run_secs=4.0, plant_fire_log=None):
    """Run the real watcher once against a stub daemon + always-failing fire.

    `plant_fire_log` writes that text as the fired member's most recent fire log
    ($STATE/logs/<prefix>-*.log, prefix derived from the fire command's basename)
    so `classify_fire_failure` has something real to read. None means no log
    exists at all — the honest default, and the case that must yield
    `why=unknown` rather than a guess.
    """
    tmp = tempfile.mkdtemp(prefix="branch4-test-")
    state = os.path.join(tmp, "state")
    fire_log = os.path.join(tmp, "fire.log")
    fire_stub = os.path.join(tmp, "fire-stub.sh")
    with open(fire_stub, "w") as f:
        f.write(f'#!/usr/bin/env bash\necho "$1" >> "{fire_log}"\nexit 3\n')
    os.chmod(fire_stub, 0o755)
    if plant_fire_log is not None:
        # fire-stub.sh -> prefix "stub", matching the watcher's own derivation.
        os.makedirs(os.path.join(state, "logs"), exist_ok=True)
        with open(os.path.join(state, "logs", "stub-20260731-000000.log"), "w") as f:
            f.write(plant_fire_log)

    daemon = StubDaemon(notices, notify_error=notify_error)
    env = dict(os.environ)
    env.update({
        "HESTIA_ENDPOINT": f"http://127.0.0.1:{daemon.port}/mcp",
        "HESTIA_MESH_STATE": state,
        "WATCH_INTERVAL": "1",
        "UNANSWERED_EVERY": "3600",
    })
    proc = subprocess.Popen(
        ["bash", WATCHER, "dest-member", "dest-agent", fire_stub],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, start_new_session=True)
    time.sleep(run_secs)
    os.killpg(proc.pid, signal.SIGTERM)
    out = proc.stdout.read() if proc.stdout else ""
    proc.wait()
    daemon.stop()

    # Retained primers live one level down, in a per-member directory
    # ($STATE/primers/$PLUGIN/) since 2026-07-31 — a flat shared directory let one
    # member's watcher re-fire another member's consume-once work list. Walked rather
    # than listed so this counts what is retained wherever the layout puts it; the
    # assertion is still "exactly one".
    primers = []
    pdir = os.path.join(state, "primers")
    for root, _, files in os.walk(pdir):
        primers += [os.path.relpath(os.path.join(root, p), pdir)
                    for p in files if p.startswith("notice-")]
    fire_attempts = 0
    if os.path.exists(fire_log):
        fire_attempts = len(open(fire_log).read().split())
    return daemon, out, primers, fire_attempts


NOTICE_A = {"id": 42, "kind": "coordination", "from_plugin": "claude-code",
            "from_role": "role:constellation:member",
            "pointer_uri": "shared-context/explorations/r6-routing/README.md#thread=r6",
            "queued_at": "2026-07-26T00:00:00Z"}
NOTICE_ACK = {"id": 43, "kind": "ack", "from_plugin": "claude-code",
              "pointer_uri": "shared-context/forum/x.md", "queued_at": "2026-07-26T00:00:00Z"}
NOTICE_REPORT = {"id": 44, "kind": "reply", "from_plugin": "claude-code",
                 "pointer_uri": "shared-context/forum/y.md#undelivered:fire-rc=3",
                 "queued_at": "2026-07-26T00:00:00Z"}
# A pointer AT the MTU is legal (handler.rs MAX_POINTER_URI_BYTES = 512, `>` not
# `>=`), so this is an ordinary notice, not a hostile one.
MAX_POINTER = "shared-context/forum/" + "a" * (512 - len("shared-context/forum/"))
NOTICE_MAX = {"id": 45, "kind": "coordination", "from_plugin": "claude-code",
              "pointer_uri": MAX_POINTER, "queued_at": "2026-07-26T00:00:00Z"}


def main():
    # Case A — the branch-4 report itself.
    daemon, out, primers, fires = run_watcher([dict(NOTICE_A)])
    check("A: failing fire attempted and primer retained (consume-once copy survives)",
          len(primers) == 1 and fires >= 1, f"primers={primers} fires={fires}\n{out}")
    reports = [c for c in daemon.notify_calls]
    ok = (len(reports) == 1
          and reports[0].get("to_plugin_id") == "claude-code"
          and reports[0].get("kind") == "reply"
          and reports[0].get("in_reply_to") == 42
          and reports[0].get("pointer_uri")
          == NOTICE_A["pointer_uri"]
          + "#undelivered:fire-rc=3;why=unknown;via=watch-dest-member")
    check("A: exactly one bound reply report to the original sender, pointer names "
          "the undelivered content + the routing verdict + the observer", ok,
          f"notify_calls={json.dumps(reports)}\n{out}")
    check("A: report journaled", "UNREACHABLE reported" in out, out)

    # Case G (CBP review §5) — the report's own receipt is not success-shaped:
    # the journal line carries the daemon's recipient_liveness verdict, so a
    # report that queued into a name nothing drains reads as what it is.
    check("G: the report receipt journals the daemon's recipient_liveness verdict",
          "UNREACHABLE reported (recipient: live)" in out, out)

    # Case B — acks are terminal; an undelivered ack is not reported.
    daemon, out, primers, _ = run_watcher([dict(NOTICE_ACK)])
    check("B: undelivered ack is NOT reported (loop closed daemon-side at send)",
          len(daemon.notify_calls) == 0 and len(primers) == 1,
          f"notify_calls={json.dumps(daemon.notify_calls)} primers={primers}\n{out}")

    # Case C — ICMP-about-ICMP suppression.
    daemon, out, primers, _ = run_watcher([dict(NOTICE_REPORT)])
    check("C: undelivered report is NOT re-reported (#undelivered pointer suppressed)",
          len(daemon.notify_calls) == 0 and len(primers) == 1,
          f"notify_calls={json.dumps(daemon.notify_calls)} primers={primers}\n{out}")

    # Case D — a failed report must not kill the router.
    daemon, out, primers, fires = run_watcher([dict(NOTICE_A)], notify_error=True)
    check("D: denied report is journaled as FAILED, primer retained, router keeps polling",
          len(daemon.notify_calls) >= 1 and "unreachable-report FAILED" in out
          and len(primers) == 1 and daemon.inbox_calls >= 2,
          f"notify={len(daemon.notify_calls)} inbox={daemon.inbox_calls} "
          f"primers={primers}\n{out}")

    # Case E — truncation must eat the CONTENT NAME, never the routing verdict.
    # Appending the fragment and then cutting to the MTU loses the marker for
    # any pointer over 500 bytes, and at exactly 512 the report is byte-identical
    # to the notice it reports on: the verdict vanishes, case C's suppression
    # goes blind, and two gateways with failing fires report each other's
    # reports once per poll forever.
    daemon, out, primers, _ = run_watcher([dict(NOTICE_MAX)])
    reports = list(daemon.notify_calls)
    ptr = reports[0].get("pointer_uri", "") if reports else ""
    check("E: at the 512-byte MTU the routing verdict survives — marker AND "
          "observer intact, still within MTU, and not byte-identical to the "
          "reported notice",
          len(reports) == 1
          and "#undelivered:fire-rc=3" in ptr
          and ";via=watch-dest-member" in ptr
          and len(ptr.encode()) <= 512
          and ptr != MAX_POINTER,
          f"len={len(ptr.encode())} marker={'#undelivered' in ptr} "
          f"via={';via=watch-dest-member' in ptr} "
          f"identical={ptr == MAX_POINTER}\n        ptr={ptr!r}\n{out}")
    # ...and the report it produced must itself be suppressed on the next hop,
    # which is the property case C asserts and the only reason the marker matters.
    daemon2, out2, _, _ = run_watcher([dict(NOTICE_MAX, id=46, pointer_uri=ptr or MAX_POINTER)])
    check("E: the MTU-length report is suppressed as an input (no report about a report)",
          len(daemon2.notify_calls) == 0,
          f"notify_calls={json.dumps(daemon2.notify_calls)}\n{out2}")

    # F — not branch 4, found by reading this test's own output: the unanswered
    # JOURNAL asker (the weak half of the two-asker design) died on a Python
    # SyntaxError on every run and `|| true` ate it. A watcher that reports a
    # crash from the code whose job is making silent debt visible is the
    # thread's subject, not a lint.
    check("F: the unanswered asker actually runs (no swallowed SyntaxError)",
          "SyntaxError" not in out, out)

    # H — the exit reason must reach the report. `fire-rc=1` spanned at least four
    # worlds (out-of-credits / egress-blocked / timeout / usage error) and codex's
    # four-day "silence" was spent inside that ambiguity: rc=1 read as a dead fire
    # path while codex had answered 126 of 127 notices and the sandbox ate every
    # disposition. Each branch is fired here against a REAL planted log, because a
    # classifier that has never run on anything but the default is a claim.
    #
    # Sabotage case first: the classifier must NOT be a constant. `why=unknown`
    # for every input would satisfy any test that only checks the field exists —
    # so the assertions below require the branches to DISAGREE with each other.
    seen = {}
    for label, planted in [
        ("out-of-credits", "starting\nERROR: Your workspace is out of credits.\nbye\n"),
        ("egress-blocked", "starting\nurllib.error.URLError: <EPERM Operation not permitted>\n"),
        ("timeout", "starting\nthe request timed out after 600s\n"),
        ("unknown", "starting\nsomething nobody has a pattern for yet\n"),
    ]:
        d, o, _, _ = run_watcher([dict(NOTICE_A)], plant_fire_log=planted)
        rp = list(d.notify_calls)
        seen[label] = rp[0].get("pointer_uri", "") if rp else ""
        check(f"H: fire log naming {label} is classified as why={label}",
              f";why={label};" in seen[label],
              f"ptr={seen[label]!r}\n{o}")

    check("H: the classifier is not a constant (the four inputs give >1 verdict)",
          len({v.split(";why=")[-1].split(";")[0] for v in seen.values() if v}) > 1,
          f"verdicts={seen}")
    dnl, onl, _, _ = run_watcher([dict(NOTICE_A)], plant_fire_log=None)
    rnl = list(dnl.notify_calls)
    check("H: a fire log that does not exist yields unknown, never a guess",
          len(rnl) == 1 and ";why=unknown;" in rnl[0].get("pointer_uri", ""),
          f"calls={json.dumps(dnl.notify_calls)}\n{onl}")

    print()
    if failures:
        print(f"{len(failures)} FAILURES: {failures}")
        sys.exit(1)
    print("all branch-4 cases pass")


if __name__ == "__main__":
    main()
