#!/usr/bin/env python3
"""Execute `egress-drain.sh`'s dispatch arms against a stub MCP endpoint.

WHY THIS EXISTS AS AN EXECUTED TEST RATHER THAN A READING
=========================================================
G4 was a live silent-black-hole defect in this script that survived a hand
review, a `bash -n`, and a grep: `IFS=$'\t' read` collapses adjacent tabs
(tab is IFS whitespace), so a row with an empty `dest_peer_lct` lost the field
entirely and every later value shifted one place left. The `-z "$lct"` guard was
unreachable dead code and the drain forwarded on the row's KIND as if it were an
LCT — then marked the row FORWARDED on a zero exit. Nothing about the source
looks wrong; the only way to see it is to run it and watch which arm fires.

So this asserts on BEHAVIOUR — which RPCs the drain actually issues — not on the
text of the script. The four dispatch arms and the field alignment are the
contract; each case below is one arm.

Usage:  python3 plugins/member-mesh/drain-dispatch-check.py     (from the repo root)
Exit:   0 = all arms behave, 1 = an arm regressed (prints the diff)
"""
import json, os, subprocess, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "egress-drain.sh")


def run_drain(pending, notifier):
    """Run the real script once against a stub endpoint; return its RPCs + log."""
    calls = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if body.get("method") == "initialize":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("mcp-session-id", "sid-1")
                self.end_headers()
                self.wfile.write(b"{}")
                return
            if body.get("method") == "notifications/initialized":
                self.send_response(202)
                self.end_headers()
                return
            name, args = body["params"]["name"], body["params"]["arguments"]
            if name == "hestia_connect":
                result = {"sessionId": "sess-1"}
            else:
                calls.append(args)
                if "mark_failed" in args or "mark_forwarded" in args:
                    result = {"marked": args.get("mark_failed") or args.get("mark_forwarded"),
                              "disposition": "retry"}
                else:
                    # First poll hands the rows over; later polls are empty.
                    result = {"pending": pending if len(calls) == 1 else []}
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            payload = {"result": {"content": [{"text": json.dumps(result)}]}}
            self.wfile.write(("data: " + json.dumps(payload) + "\n\n").encode())

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ)
        env["HESTIA_ENDPOINT"] = f"http://127.0.0.1:{srv.server_address[1]}/mcp"
        env["HUB_NOTIFY"] = notifier
        env["EGRESS_DRAIN_LOG"] = os.path.join(tmp, "drain.log")
        p = subprocess.run(["bash", SCRIPT, "--once"], capture_output=True,
                           text=True, env=env, timeout=60)
    srv.shutdown()
    return calls, p.stdout.strip(), p.returncode


def stub(tmpdir, name, rc):
    path = os.path.join(tmpdir, name)
    with open(path, "w") as f:
        f.write(f"#!/usr/bin/env bash\nexit {rc}\n")
    os.chmod(path, 0o755)
    return path


def main():
    tmp = tempfile.mkdtemp()
    ok, refused, wedged = stub(tmp, "ok.sh", 0), stub(tmp, "no.sh", 2), stub(tmp, "w.sh", 127)
    good = [{"id": 9, "dest_peer": "thor-sage", "dest_peer_lct": "lct:thor-9",
             "kind": "reply", "pointer_uri": "p.md"}]
    # The migration population: parked before `dest_peer_lct` existed.
    no_lct = [{"id": 7, "dest_peer": "thor-sage", "dest_peer_lct": "",
               "kind": "reply", "pointer_uri": "p.md"}]

    failures = []

    def check(label, cond, detail):
        print(f"  {'ok  ' if cond else 'FAIL'}  {label}")
        if not cond:
            failures.append(f"{label}: {detail}")

    print("arm: rc=0 — a hand-off the mesh accepted")
    calls, log, _ = run_drain(good, ok)
    check("marks the row forwarded", any("mark_forwarded" in c for c in calls), calls)
    # Field alignment: the shifted parse printed the KIND here and still "passed".
    check("logs the LCT as the LCT, not the kind", "(lct:thor-9) kind=reply" in log, log)

    print("arm: rc=2 — a real answer from a notifier that ran")
    calls, log, _ = run_drain(good, refused)
    check("marks the row failed", any("mark_failed" in c for c in calls), calls)

    print("arm: rc=127 in-loop — the notifier went away underneath us (B5)")
    calls, log, _ = run_drain(good, wedged)
    check("burns no attempt", not any("mark_failed" in c for c in calls), calls)
    check("says WEDGED", "WEDGED" in log, log)

    print("arm: no dest_peer_lct — a row this box can never send (G1/G4)")
    calls, log, _ = run_drain(no_lct, ok)
    check("never invokes the notifier / never claims delivery",
          not any("mark_forwarded" in c for c in calls), calls)
    check("emits no evidence about the peer", not any("mark_failed" in c for c in calls), calls)
    check("says UNSENDABLE", "UNSENDABLE" in log, log)

    # G5 (Thor, hop 3). Blank is not only "". Both daemon-side predicates treat a
    # whitespace-only LCT as absent — `resolve_peer_at` trims, `undeliverable_egress`
    # is `TRIM(dest_peer_lct) = ''` — so the drain's backstop must spell it the same
    # way. It did not: `[ -z "$lct" ]` is false for " ", which forwarded on a blank
    # destination and marked the row FORWARDED. Same outcome as G4, different door,
    # and it lives in the one skew this arm exists for (new drain, old daemon with
    # no sweep). Parameterised because the population is a hand-edited peers.json.
    for shape, lct in [("a space", " "), ("a tab", "\t")]:
        blank = [dict(no_lct[0], dest_peer_lct=lct)]
        calls, log, _ = run_drain(blank, ok)
        check(f"treats {shape} as absent, not as a destination",
              not any("mark_forwarded" in c for c in calls) and "UNSENDABLE" in log,
              f"{calls} | {log}")

    print("preflight: an absent notifier is a config error, not an outage (B5)")
    _, log, rc = run_drain(good, os.path.join(tmp, "absent.sh"))
    check("exits 78 (EX_CONFIG) without draining", rc == 78, f"rc={rc} log={log}")

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nall dispatch arms behave")
    return 0


if __name__ == "__main__":
    sys.exit(main())
