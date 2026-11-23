#!/usr/bin/env python3
"""The drain maps only review_request at the fleet hand-off (#904)."""
import json
import os
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT = Path(os.environ.get(
    "EGRESS_DRAIN_SCRIPT",
    Path(__file__).resolve().parents[1] / "egress-drain.sh",
))
FAILURES = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f" -- {detail}"))
    if not ok:
        FAILURES.append(name)


class Daemon(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))))
        method = body.get("method")
        if method == "initialize":
            return self.reply({"jsonrpc": "2.0", "id": body.get("id"), "result": {}})
        if method == "notifications/initialized":
            return self.reply({"jsonrpc": "2.0", "result": {}})
        params = body.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "hestia_connect":
            result = {"sessionId": "egress-test-session"}
        elif name == "hestia_egress_pending":
            if args.get("mark_forwarded") in getattr(self.server, "fail_forward", ()):
                # the hand-off landed but the daemon cannot record it (NOVA, #1654)
                self.server.refused.append(args)
                result = {"_hestia_error": {"code": "unavailable", "message": "mark_forwarded"}}
            elif "mark_forwarded" in args or "mark_failed" in args:
                self.server.calls.append(args)
                result = {"ok": True}
            else:
                result = {"pending": self.server.rows}
        else:
            result = {"_hestia_error": {"code": "unexpected", "message": name}}
        payload = {
            "jsonrpc": "2.0", "id": body.get("id"),
            "result": {"content": [{"type": "text", "text": json.dumps(result)}]},
        }
        self.reply(payload)

    def reply(self, payload):
        raw = (f"data: {json.dumps(payload)}\n\n").encode()
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("mcp-session-id", "egress-test-session")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


bash = shutil.which("bash")
check("bash is available", bash is not None)
if bash:
    syntax = subprocess.run([bash, "-n", str(SCRIPT)], capture_output=True, text=True)
    check("the drain parses", syntax.returncode == 0, syntax.stderr[:300])

with tempfile.TemporaryDirectory() as raw:
    tmp = Path(raw)
    notifier_log = tmp / "notifier.jsonl"
    notifier = tmp / "hub-notify"
    notifier.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "with open(os.environ['HUB_KIND_LOG'], 'a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "sys.exit(1 if len(sys.argv) > 2 and sys.argv[2] in ('review_request', 'review_request.pr') else 0)\n",
        encoding="utf-8",
    )
    notifier.chmod(0o755)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Daemon)
    server.calls = []
    server.rows = [
        {"id": 60, "dest_peer": "peer/member", "forward_on": "peer/member",
         "forward_on_is_lct": True, "kind": "review_request", "pointer_uri": "thread:60"},
        {"id": 61, "dest_peer": "peer/member", "forward_on": "peer/member",
         "forward_on_is_lct": True, "kind": "reply", "pointer_uri": "thread:61"},
        {"id": 62, "dest_peer": "peer/member", "forward_on": "peer/member",
         "forward_on_is_lct": True, "kind": "review_request.pr", "pointer_uri": "thread:62"},
    ]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = os.environ.copy()
    env.update({
        "HESTIA_ENDPOINT": f"http://127.0.0.1:{server.server_address[1]}/mcp",
        "HESTIA_HUB_NOTIFY": str(notifier),
        "EGRESS_DRAIN_LOG": str(tmp / "drain.log"),
        "EGRESS_DRAIN_PLUGIN_ID": "egress-test",
        "HUB_KIND_LOG": str(notifier_log),
    })
    try:
        if bash:
            run = subprocess.run([bash, str(SCRIPT), "--once"], env=env,
                                 capture_output=True, text=True, timeout=60)
            check("the real drain completes", run.returncode == 0,
                  (run.stdout + run.stderr)[-1000:])
            check("the root kind maps at hand-off", notifier_log.exists()
                  and json.loads(notifier_log.read_text().splitlines()[0])[1] == "pr_review_request",
                  notifier_log.read_text() if notifier_log.exists() else "notifier was not called")
            lines = [json.loads(line) for line in notifier_log.read_text().splitlines()] if notifier_log.exists() else []
            check("reply remains byte-identical", len(lines) > 1 and lines[1][1] == "reply", repr(lines))
            check("a specialization is not collapsed into the legacy PR atom",
                  len(lines) > 2 and lines[2][1] == "review_request.pr", repr(lines))
            marks = server.calls
            check("the mapped root is marked forwarded",
                  any(call.get("mark_forwarded") == 60 for call in marks), repr(marks))
            check("the unchanged reply is marked forwarded",
                  any(call.get("mark_forwarded") == 61 for call in marks), repr(marks))
            check("the failed specialization is marked failed, never forwarded",
                  any(call.get("mark_failed") == 62 for call in marks)
                  and not any(call.get("mark_forwarded") == 62 for call in marks), repr(marks))
            log = (tmp / "drain.log").read_text() if (tmp / "drain.log").exists() else ""
            check("the log records both local and transport spellings",
                  "kind=review_request hub_kind=pr_review_request" in log, log[-1000:])
            check("the queued record was not rewritten", server.rows[0]["kind"] == "review_request")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

# NOVA (#1654): the hand-off is at-least-once. When the notifier accepts a mapped root but
# mark_forwarded fails, the row stays pending and the next tick sends it AGAIN; the duplicate
# must be exposed in the log under the transport spelling, never silently swallowed.
with tempfile.TemporaryDirectory() as raw:
    tmp = Path(raw)
    notifier_log = tmp / "notifier.jsonl"
    notifier = tmp / "hub-notify"
    notifier.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "with open(os.environ['HUB_KIND_LOG'], 'a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n",
        encoding="utf-8",
    )
    notifier.chmod(0o755)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Daemon)
    server.calls, server.refused, server.fail_forward = [], [], {70}
    server.rows = [
        {"id": 70, "dest_peer": "peer/member", "forward_on": "peer/member",
         "forward_on_is_lct": True, "kind": "review_request", "pointer_uri": "thread:70"},
    ]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = os.environ.copy()
    env.update({
        "HESTIA_ENDPOINT": f"http://127.0.0.1:{server.server_address[1]}/mcp",
        "HESTIA_HUB_NOTIFY": str(notifier),
        "EGRESS_DRAIN_LOG": str(tmp / "drain.log"),
        "EGRESS_DRAIN_PLUGIN_ID": "egress-test",
        "HUB_KIND_LOG": str(notifier_log),
    })
    try:
        if bash:
            for _tick in range(2):
                subprocess.run([bash, str(SCRIPT), "--once"], env=env,
                               capture_output=True, text=True, timeout=60)
            sent = [json.loads(line) for line in notifier_log.read_text().splitlines()] \
                if notifier_log.exists() else []
            check("an unrecorded hand-off is re-sent next tick (duplicate exposed, not dropped)",
                  [s[1] for s in sent] == ["pr_review_request", "pr_review_request"], repr(sent))
            check("a hand-off the daemon could not record is never counted forwarded",
                  len(server.refused) == 2 and not server.calls, repr((server.refused, server.calls)))
            log = (tmp / "drain.log").read_text() if (tmp / "drain.log").exists() else ""
            check("each duplicate risk is logged under the transport spelling",
                  log.count("DUPRISK   id=70") == 2
                  and log.count("kind=review_request hub_kind=pr_review_request (hub accepted it") == 2,
                  log[-1000:])
            server.fail_forward = set()
            subprocess.run([bash, str(SCRIPT), "--once"], env=env,
                           capture_output=True, text=True, timeout=60)
            check("once the daemon records it, the row is marked forwarded exactly once",
                  [c.get("mark_forwarded") for c in server.calls] == [70], repr(server.calls))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

if FAILURES:
    raise SystemExit(f"{len(FAILURES)} failure(s): {FAILURES}")
print("egress review-kind contract: PASS")
