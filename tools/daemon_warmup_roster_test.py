#!/usr/bin/env python3
"""deploy/daemon-warmup.sh warms every member on the ROSTER, read at run time (one-gate stage C).

The roster is the seat projections the daemon renders, $HESTIA_HOME/seats/<member>.env. The
script used to carry four hard-coded ids, so a seat added later met the cold first-connect
(4.6-5.7 s per member) on its first act — which since stage C is a recorded denial whenever it
outlives a short registration. Arms: every rostered member is connected once; a `_`-prefixed
(shared) projection is not a member; an empty roster warms nothing and still exits 0.

Run: python3 tools/daemon_warmup_roster_test.py   (bare; exit 1 on failure)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "deploy" / "daemon-warmup.sh"
FAILS: list = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}" + (f" -- {detail}" if not ok else ""))
    if not ok:
        FAILS.append(name)


def serve():
    seen: list = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            p = body.get("params") or {}
            if p.get("name") == "hestia_connect":
                seen.append(p["arguments"]["plugin_id"])
            data = json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result": {}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Mcp-Session-Id", "s")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, seen


def run(home: Path, url: str):
    env = {k: v for k, v in os.environ.items() if not k.startswith("HESTIA_")}
    env.update({"HESTIA_HOME": str(home), "HESTIA_ENDPOINT": url})
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env, timeout=120)


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        home = Path(d)
        (home / "seats").mkdir()
        for name in ("alpha-seat", "beta-seat", "_shared"):
            (home / "seats" / (name + "." + "env")).write_text("# fixture\n")
        srv, seen = serve()
        try:
            r = run(home, f"http://127.0.0.1:{srv.server_address[1]}/mcp")
            check("exits-0", r.returncode == 0, r.stderr)
            check("every-rostered-member-warmed-once", sorted(seen) == ["alpha-seat", "beta-seat"], seen)
            check("the-run-names-who-it-warmed", "alpha-seat" in r.stdout and "beta-seat" in r.stdout, r.stdout)
            check("no-hard-coded-member-left", "kimi-code" not in seen and "claude-code" not in seen, seen)
            seen.clear()
            for f in (home / "seats").iterdir():
                f.unlink()
            r = run(home, f"http://127.0.0.1:{srv.server_address[1]}/mcp")
            check("empty-roster-warms-nothing", seen == [] and r.returncode == 0, (seen, r.returncode))
            check("empty-roster-says-so", "no members on the roster" in r.stderr, r.stderr)
        finally:
            srv.shutdown()
    print(f"{'FAIL' if FAILS else 'OK'} — warm-up roster")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
