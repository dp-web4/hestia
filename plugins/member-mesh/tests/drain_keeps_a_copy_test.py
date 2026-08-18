#!/usr/bin/env python3
"""A consume-once drain must leave a durable copy before stdout is anyone's problem.

WHAT HAPPENED (claude-code, CBP, 2026-08-18). `hestia-mesh.py drain` empties the
mailbox server-side and returns the notices in ONE place: this process's stdout. A
wake ran the drain and piped stdout through a summarizer that printed only the ids.
Seven notices were consumed; six had already been read via `peek`, and the seventh —
notice 3097 — had not. It was gone: `hestia_query_history` filtered by tool_name
returns an empty page on this store, and nothing else had ever seen the pointer. The
remedy was asking the sender to send it again.

This is a class the repo already fixed on the OTHER path and never carried across.
`fire-*.sh` copies the primer to the member's home BEFORE the sender filter runs, and
`fire_sender_allowlist_test.py` records that this is the only reason notice 160
survived being dropped by an allowlist. Meanwhile the SessionStart hook on every seat
tells the member to run `hestia-mesh.py drain` in-session — the path with no copy.

Nothing could catch it, because a destroyed notice looks exactly like a notice that
was never sent. So:

  A. drain writes a copy under the state dir, keyed by member, before the caller can
     lose stdout — and says where on stderr, so the line is in the log even when the
     caller is throwing stdout away.
  B. peek does NOT write one (it consumes nothing; a copy per poll is litter).
  C. an empty drain writes nothing (an empty file is a false record of mail).
  D. stdout stays PURE JSON — the contract act() commits to, and the reason the
     announcement goes to stderr.
  E. when the copy CANNOT be written the command still succeeds (the mailbox is
     already empty; failing here would strand the notices for no gain) but the
     failure is loud AND the payload is repeated on stderr, so a lossy stdout
     consumer is not the last copy.

RED arm: HESTIA_MESH_CLI=<pre-fix hestia-mesh.py> — A, D(stderr-mention) and E fail.

Usage: ./drain_keeps_a_copy_test.py     (runtime ~3s, stub daemon, no network)
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

NOTICES = [{"id": 3097, "kind": "review_done", "from_plugin": "kimi-code",
            "pointer_uri": "hestia://escalation/deadbeef#the-one-that-was-lost",
            "queued_at": "2026-08-18T15:10:00Z"},
           {"id": 3098, "kind": "reply", "from_plugin": "codex",
            "pointer_uri": "shared-context/x.md#second", "queued_at": "2026-08-18T15:11:00Z"}]

MODE = {"empty": False}
failures = []


def check(label, ok, detail=""):
    if not ok:
        failures.append(label)
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or "{}")
        if body.get("method") == "initialize":
            return self._json({"jsonrpc": "2.0", "id": body["id"],
                               "result": {"protocolVersion": "2024-11-05"}}, sid="stub-session")
        if body.get("method") == "notifications/initialized":
            self.send_response(202)
            self.end_headers()
            return
        params = body.get("params", {})
        if params.get("name") == "hestia_connect":
            return self._sse(body["id"], {"sessionId": "s-1",
                                          "constellationRole": "role:constellation:member"})
        peek = bool(params.get("arguments", {}).get("peek"))
        notices = [] if (MODE["empty"] and not peek) else NOTICES
        return self._sse(body["id"], {"notices": notices, "total": len(notices),
                                      "evicted": 0, "peeked": peek})

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
        raw = (f"event: message\ndata: "
               f"{json.dumps({'jsonrpc': '2.0', 'id': rid, 'result': {'content': [{'type': 'text', 'text': json.dumps(obj)}]}})}\n\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


srv = HTTPServer(("127.0.0.1", 0), Stub)
EP = f"http://127.0.0.1:{srv.server_port}/mcp"
threading.Thread(target=srv.serve_forever, daemon=True).start()


def run(cmd, state, member="test-member"):
    env = dict(os.environ, HESTIA_ENDPOINT=EP, HESTIA_MESH_PLUGIN=member,
               HESTIA_MESH_STATE=state)
    env.pop("HESTIA_ROLE", None)
    p = subprocess.run([sys.executable, CLI, cmd], capture_output=True, text=True,
                       env=env, timeout=25)
    return p


def copies(state, member="test-member"):
    d = os.path.join(state, "drained", member)
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, f) for f in sorted(os.listdir(d))]


# A. the copy exists, holds the notice, and is announced
with tempfile.TemporaryDirectory() as tmp:
    p = run("drain", tmp)
    files = copies(tmp)
    check("A1. drain leaves exactly one copy under the member's state dir",
          p.returncode == 0 and len(files) == 1,
          f"rc={p.returncode} files={files}\n        stderr={p.stderr.strip()[:300]!r}")
    if files:
        kept = json.load(open(files[0]))
        got = [n["id"] for n in kept.get("notices", [])]
        check("A2. the copy holds every drained notice, pointer intact",
              got == [3097, 3098] and "the-one-that-was-lost" in json.dumps(kept),
              f"ids={got}")
        check("A3. the copy is not world-readable (it is another member's mail)",
              (os.stat(files[0]).st_mode & 0o077) == 0,
              f"mode={oct(os.stat(files[0]).st_mode)}")
    check("A4. stderr names the path, so the location survives a discarded stdout",
          "3097" in p.stderr and (files and files[0] in p.stderr),
          f"stderr={p.stderr.strip()[:300]!r}")

    # D. stdout stays pure JSON — callers parse it.
    try:
        parsed = json.loads(p.stdout)
        ok = [n["id"] for n in parsed.get("notices", [])] == [3097, 3098]
    except Exception as e:
        parsed, ok = None, False
    check("D. stdout is still pure parseable JSON carrying the payload", ok,
          f"stdout={p.stdout[:300]!r}")

# B. peek consumes nothing, so it must leave nothing
with tempfile.TemporaryDirectory() as tmp:
    p = run("peek", tmp)
    check("B. peek writes no copy (it consumes nothing; a file per poll is litter)",
          p.returncode == 0 and copies(tmp) == [],
          f"rc={p.returncode} files={copies(tmp)}")

# C. an empty drain must not write an empty file
with tempfile.TemporaryDirectory() as tmp:
    MODE["empty"] = True
    p = run("drain", tmp)
    MODE["empty"] = False
    check("C. an empty drain writes nothing (an empty file is a false record of mail)",
          p.returncode == 0 and copies(tmp) == [],
          f"rc={p.returncode} files={copies(tmp)}")

# E. an unwritable state dir: still succeeds, loudly, with the payload on stderr
with tempfile.TemporaryDirectory() as tmp:
    blocked = os.path.join(tmp, "blocked")
    open(blocked, "w").write("not a directory")   # makedirs under a FILE must fail
    p = run("drain", blocked)
    check("E1. a failed copy does not fail the drain (the mailbox is already empty)",
          p.returncode == 0, f"rc={p.returncode} stderr={p.stderr.strip()[:300]!r}")
    check("E2. the failure is loud and repeats the payload on stderr",
          "WARNING" in p.stderr and "3097" in p.stderr
          and "the-one-that-was-lost" in p.stderr,
          f"stderr={p.stderr.strip()[:400]!r}")

print()
if failures:
    print(f"{len(failures)} FAILURE(S): " + ", ".join(failures))
    sys.exit(1)
print("all checks passed")
