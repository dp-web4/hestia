#!/usr/bin/env python3
"""The drift alarm had no recovery, and the recovery must refuse everything but merged bytes.

WHAT HAPPENED (CBP, 2026-08-26). `check_artifact_drift` had been correct, hourly and
level-triggered for twenty days, and it had changed nothing. The claude-code and
kimi-code watchers were still executing a8dccda (2026-08-06) while origin/main was
three mesh commits ahead -- one of them ebc3719, the fix that stops this very script
reporting a DELIVERED primer as undelivered. Cost, counted in ONE member's primer that
morning: 41 non-delivery labels on rc=124 (the one rc that PROVES delivery), 40 of them
filed by the two stale-vintage watchers. The 41st was codex's, queued 18:37:02Z on
08-25, 4h35m BEFORE codex restarted into the current bytes at 23:12:38Z. Since the fix
went in force on the one seat that has it, that seat has filed none.

Nobody applied the remedy by hand because there is no moment to apply it in: the
session reading the alarm is a descendant of its own watcher's cgroup, and the other
stale seat was mid-wake behind a foreground `timeout -k 30 1800`.

So the alarm gets a recovery -- and the recovery is dangerous in a way the staleness is
not, which is what most of these properties are about. Stale bytes are at least STABLE
and NAMEABLE. An auto-deployer that took "whatever changed" would make the fleet's
in-force vintage a function of whoever last hit save in a shared worktree. The four
conjuncts are drift, the same new hash twice, byte-identity with `origin/main:<path>`,
and `bash -n`.

PROPERTY 3 IS THE ONE THAT FOUND A REAL BUG IN THE FIRST DRAFT. The obvious spelling of
"is this merged" is `git hash-object <disk>` against `git rev-parse origin/main:<path>`.
On this fleet's Windows mount `core.autocrlf=input` normalises CRLF on the way in, so a
CRLF-mangled working copy has the SAME BLOB ID as the clean merged file -- measured, and
`bash -n` accepts the mangled file too, so neither guard catches it. 3b asserts the blob
ids really are equal, so this arm cannot pass for the wrong reason: it proves the
rejected spelling WOULD have deployed bytes that are not the merged bytes. The shipped
check compares raw sha256 of `git show` output against the disk hash the script already
computes, with no filter anywhere in the path.

Five properties, behavioural against the real watcher in a real scratch repo, no seam:

  1. MERGED BYTES DEPLOY, and the successor is really running them (a second startup
     ARTIFACT line whose startup_sha256 is the new file's hash, state=ok), and the
     process survives -- `exec`, not death.
  2. EDITED BYTES DO NOT. Drifted, stable, parses, one byte off origin/main -> held.
  3. CRLF BYTES DO NOT, though their blob id is identical to origin/main's (3b).
  4. THE FIRST SIGHTING NEVER DEPLOYS. The drift edge alarm precedes any deploy, which
     is the observable form of "the same new hash on two consecutive passes".
  5. NO DRIFT, NO DEPLOY. The control: a watcher whose disk matches its startup never
     emits a deploy line however long it runs.

HOW MUCH EACH ARM IS WORTH. Against origin/main (no deploy path at all) 1a, 1b, 2b and
4a go RED and the rest stay green -- correctly, and vacuously: 2a, 3a and 5a assert that
a deploy did NOT happen, which is free for a watcher that can never deploy. They earn
their place only against a version that CAN, which is why 3b measures the blob equality
directly instead of inferring it from 3a's silence.

Usage: ./artifact_drift_deploys_merged_bytes_test.py     (runtime ~40s)
"""
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MESH = os.path.abspath(os.path.join(HERE, ".."))
WATCHER_SRC = os.environ.get("WATCHER_UNDER_TEST") or os.path.join(MESH, "hestia-watch-member.sh")
PLUGIN = "claude-code"
REL = "plugins/member-mesh/hestia-watch-member.sh"

failures = []


def check(label, ok, detail=""):
    if not ok:
        failures.append(label)
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


class Stub(http.server.BaseHTTPRequestHandler):
    """Healthy daemon, permanently empty inbox. The loop must spin, not work."""

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or "{}")
        method = body.get("method")
        if method == "initialize":
            self._json({"jsonrpc": "2.0", "id": body.get("id"), "result": {}},
                       extra={"mcp-session-id": "stub-session"})
            return
        if method == "notifications/initialized":
            self._json({})
            return
        name = (body.get("params") or {}).get("name")
        args = (body.get("params") or {}).get("arguments") or {}
        if name == "hestia_connect":
            payload = {"sessionId": "sess::" + str(args.get("plugin_id")),
                       "roleDeclarationHonored": True, "constellationRole": args.get("role")}
        elif name == "hestia_member_inbox":
            payload = {"notices": [], "total": 0, "evicted": 0, "peeked": False, "for_plugin": PLUGIN}
        elif name == "hestia_member_unanswered":
            payload = {"i_owe": [], "owed_to_me": [], "older_than_secs": 0}
        else:
            payload = {}
        self._sse({"jsonrpc": "2.0", "id": body.get("id"),
                   "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}})

    def _json(self, obj, extra=None):
        raw = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _sse(self, obj):
        raw = ("data: " + json.dumps(obj) + "\n\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def start_stub():
    srv = http.server.HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/mcp"


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)


def build_repo(tmp, label):
    """A scratch repo whose origin/main carries the CURRENT watcher, byte for byte."""
    repo = os.path.join(tmp, label)
    mesh = os.path.join(repo, "plugins", "member-mesh")
    os.makedirs(mesh)
    for entry in os.listdir(MESH):
        src = os.path.join(MESH, entry)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(mesh, entry))
    # The watcher under test may be a different file than the one in MESH.
    shutil.copy2(WATCHER_SRC, os.path.join(repo, REL))
    git(repo, "init", "-q", ".")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    git(repo, "config", "core.autocrlf", "input")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "main")
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    git(repo, "update-ref", "refs/remotes/origin/main", head)
    return repo


def run_watcher(tmp, repo, label, mutate_after, settle=14):
    """Boot the watcher, let it settle, apply `mutate_after(path)`, watch what it says."""
    state = os.path.join(tmp, label + "-state")
    os.makedirs(os.path.join(state, "primers", PLUGIN))
    path = os.path.join(repo, REL)
    env = dict(os.environ)
    env.update(HESTIA_MESH_STATE=state, HESTIA_ENDPOINT=EP, HOME=state,
               WATCH_INTERVAL="1", UNANSWERED_EVERY="99999")
    p = subprocess.Popen(["bash", path, PLUGIN, f"{PLUGIN}-watch"],
                         env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines = []
    stop = threading.Event()

    def pump():
        for line in p.stdout:
            lines.append(line.rstrip("\n"))
            if stop.is_set():
                return

    t = threading.Thread(target=pump, daemon=True)
    t.start()
    # Wait for the first startup ARTIFACT line: the baseline is captured.
    deadline = time.time() + 30
    while time.time() < deadline and not any("ARTIFACT plugin=" in l for l in lines):
        time.sleep(0.2)
    time.sleep(1.5)
    if mutate_after:
        mutate_after(path)
    time.sleep(settle)
    alive = p.poll() is None
    stop.set()
    p.kill()
    p.wait()
    return lines, alive


def main():
    global EP
    srv, EP = start_stub()
    tmp = tempfile.mkdtemp(prefix="artifact-deploy-")

    merged = open(WATCHER_SRC, "rb").read()
    merged_sha = sha256_bytes(merged)
    # `A` is what the watcher BOOTS on: the merged file plus one comment line, i.e. a
    # plausible old vintage that is not what origin/main says.
    stale = merged.replace(b"#!/usr/bin/env bash\n",
                           b"#!/usr/bin/env bash\n# stale vintage marker\n", 1)
    assert stale != merged, "could not construct a stale variant"

    def boot_stale(repo):
        with open(os.path.join(repo, REL), "wb") as f:
            f.write(stale)

    # ---- 1. MERGED BYTES DEPLOY.
    repo = build_repo(tmp, "deploy")
    boot_stale(repo)
    lines, alive = run_watcher(tmp, repo, "deploy",
                               lambda path: open(path, "wb").write(merged))
    out = "\n".join(lines)
    deploys = [l for l in lines if "ARTIFACT DEPLOY" in l]
    check("1a. merged bytes on disk deploy — the watcher exec's into them",
          len(deploys) >= 1, out[-2500:])
    starts = [l for l in lines if "ARTIFACT plugin=" in l]
    check("1b. the successor is really running the merged bytes "
          "(second startup line, state=ok, startup_sha256=merged)",
          any(f"startup_sha256={merged_sha}" in l and "state=ok" in l for l in starts),
          f"merged_sha={merged_sha}\nstart lines:\n" + "\n".join(starts[-4:]))
    check("1c. and the process survived — exec replaced it, nothing killed it",
          alive, out[-1200:])

    # ---- 2. EDITED BYTES DO NOT DEPLOY.
    repo = build_repo(tmp, "edited")
    boot_stale(repo)
    edited = merged.replace(b"#!/usr/bin/env bash\n",
                            b"#!/usr/bin/env bash\n# local edit nobody merged\n", 1)
    lines, alive = run_watcher(tmp, repo, "edited",
                               lambda path: open(path, "wb").write(edited))
    out = "\n".join(lines)
    check("2a. drifted-but-unmerged bytes are HELD, not deployed",
          not any("ARTIFACT DEPLOY" in l for l in lines), out[-2000:])
    check("2b. and the watcher says which conjunct refused",
          any("are not origin/main" in l for l in lines), out[-2000:])

    # ---- 3. CRLF BYTES DO NOT DEPLOY, THOUGH THEIR BLOB ID IS IDENTICAL.
    repo = build_repo(tmp, "crlf")
    boot_stale(repo)
    crlf = merged.replace(b"\n", b"\r\n")
    lines, alive = run_watcher(tmp, repo, "crlf",
                               lambda path: open(path, "wb").write(crlf))
    out = "\n".join(lines)
    check("3a. CRLF-mangled bytes are HELD",
          not any("ARTIFACT DEPLOY" in l for l in lines), out[-2000:])
    disk_blob = git(repo, "hash-object", "--", os.path.join(repo, REL)).stdout.strip()
    main_blob = git(repo, "rev-parse", f"origin/main:{REL}").stdout.strip()
    check("3b. NOT VACUOUS: the blob ids ARE equal, so the `git hash-object` spelling "
          "would have deployed bytes that are not the merged bytes",
          disk_blob and disk_blob == main_blob, f"disk={disk_blob} main={main_blob}")

    # ---- 4. THE FIRST SIGHTING NEVER DEPLOYS.
    repo = build_repo(tmp, "twice")
    boot_stale(repo)
    lines, alive = run_watcher(tmp, repo, "twice",
                               lambda path: open(path, "wb").write(merged))
    idx_alarm = next((i for i, l in enumerate(lines) if "ARTIFACT DRIFT — restart required" in l), None)
    idx_deploy = next((i for i, l in enumerate(lines) if "ARTIFACT DEPLOY" in l), None)
    check("4a. the drift edge alarm precedes the deploy — the same new hash was "
          "required on two consecutive passes, not one sighting",
          idx_alarm is not None and idx_deploy is not None and idx_alarm < idx_deploy,
          f"alarm={idx_alarm} deploy={idx_deploy}\n" + "\n".join(lines[-25:]))

    # ---- 5. CONTROL: NO DRIFT, NO DEPLOY.
    repo = build_repo(tmp, "steady")
    lines, alive = run_watcher(tmp, repo, "steady", None, settle=10)
    check("5a. a watcher whose disk matches its startup never deploys",
          not any("ARTIFACT DEPLOY" in l for l in lines), "\n".join(lines[-20:]))
    check("5b. and it is still running, having done nothing", alive)

    srv.shutdown()
    print()
    if failures:
        print(f"FAILED {len(failures)}: " + "; ".join(failures))
        return 1
    print("all properties hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
