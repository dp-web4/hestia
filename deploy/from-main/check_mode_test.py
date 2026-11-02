#!/usr/bin/env python3
"""hestia-deploy --check only checks, and says what it found in deploy-check.tsv.

Runs the REAL deploy/from-main/hestia-deploy.sh in --check mode against a throwaway HOME: a local
bare "origin" for the deploy checkout and its web4 sibling, a stub daemon binary, and a tiny
HTTP server that answers the MCP `initialize` the script uses to read the running version. No
network, no build, nothing outside the temporary directory. HESTIA_UNIT names a unit that does
not exist, so the script's "which binary is the daemon executing" guard never reads the real
hestia.service on the box running this test.

What is asserted (the operator's ask, tl-dell 2026-10-21: "check for update means ONLY to
check", and the dashboard should show when it last checked):
  1. main == running        -> exit 0, state up-to-date, latest = running
  2. main moved             -> exit 3, state available, latest = the new describe
  3. --check never self-updates the installed hestia-deploy, even when main ships a newer one
  4. an operator hold does not stop a check (a check builds and restarts nothing)
  5. a check that cannot sync records state failed instead of a stale verdict
"""
import http.server
import json
import os
import pathlib
import subprocess
import tempfile
import threading

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE / "hestia-deploy.sh"
FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f" -- {detail}"))
    if not ok:
        FAILS.append(name)


def git(*args, cwd=None):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True,
                          text=True).stdout.strip()


class Daemon:
    """Answers `initialize` with whatever version `self.version` holds."""

    def __init__(self):
        outer = self
        self.version = ""

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {
                    "serverInfo": {"name": "hestia", "version": f"0.0.0 ({outer.version})"}}},
                    separators=(",", ":")).encode()  # compact, as the daemon sends it
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/mcp"


def setup(t):
    t = pathlib.Path(t)
    home = t / "home"
    hh = home / ".hestia"
    (home / ".local/bin").mkdir(parents=True)
    hh.mkdir(parents=True)
    # Source repo -> bare origin, with a deploy script in it so self-update has something to do.
    src = t / "src"
    (src / "deploy/from-main").mkdir(parents=True)
    git("init", "-q", "-b", "main", str(src))
    (src / "deploy/from-main/hestia-deploy.sh").write_text("#!/bin/sh\necho newer\n")
    git("add", "-A", cwd=src)
    git("commit", "-q", "-m", "one", cwd=src)
    git("tag", "v0.1.0", cwd=src)
    origin = t / "hestia.git"
    git("clone", "-q", "--bare", str(src), str(origin))
    w4src = t / "w4"
    git("init", "-q", "-b", "main", str(w4src))
    git("commit", "-q", "--allow-empty", "-m", "w", cwd=w4src)
    w4 = t / "web4.git"
    git("clone", "-q", "--bare", str(w4src), str(w4))
    atlas = t / "atlas.git"
    git("clone", "-q", "--bare", str(w4src), str(atlas))
    git("clone", "-q", str(origin), str(hh / "deploy/hestia"))
    git("clone", "-q", str(w4), str(hh / "deploy/web4"))
    # The daemon binary the script reads with --version; its answer is set per case.
    binf = home / ".local/bin/hestia"
    return t, home, hh, src, origin, binf


def set_bin(binf, version):
    binf.write_text(f"#!/bin/sh\necho 'hestia 0.0.0 ({version})'\n")
    binf.chmod(0o755)


def run(home, hh, daemon, atlas):
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(home),
        "HESTIA_HOME": str(hh),
        "HESTIA_ENDPOINT": daemon.endpoint,
        "HESTIA_UNIT": "hestia-check-mode-test-no-such.service",
        "HESTIA_ATLAS_URL": str(atlas),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    r = subprocess.run(["bash", str(SCRIPT), "--check"], env=env, capture_output=True, text=True,
                       timeout=120)
    tsv = hh / "deploy-check.tsv"
    fields = tsv.read_text().rstrip("\n").split("\t") if tsv.exists() else []
    return r.returncode, fields, r.stderr


with tempfile.TemporaryDirectory() as tmp:
    t, home, hh, src, origin, binf = setup(tmp)
    atlas = t / "atlas.git"
    daemon = Daemon()

    # 1. Up to date.
    daemon.version = "v0.1.0"
    set_bin(binf, "v0.1.0")
    rc, f, err = run(home, hh, daemon, atlas)
    check("up to date: exit 0", rc == 0, err)
    check("up to date: state up-to-date", f[:1] == ["up-to-date"], f)
    check("up to date: four fields, a timestamp, running and latest named",
          len(f) == 4 and f[1].endswith("Z") and f[2] == "v0.1.0" and f[3] == "v0.1.0", f)

    # 2. Main moves: an update is available, and nothing is installed.
    (src / "deploy/from-main/hestia-deploy.sh").write_text("#!/bin/sh\necho newest\n")
    git("commit", "-q", "-am", "two", cwd=src)
    git("push", "-q", str(origin), "main", cwd=src)
    rc, f, err = run(home, hh, daemon, atlas)
    check("main moved: exit 3", rc == 3, err)
    check("main moved: state available", f[:1] == ["available"], f)
    check("main moved: latest is the new commit", len(f) == 4 and f[3].startswith("v0.1.0-1-g"), f)
    check("main moved: running is still the old build", len(f) == 4 and f[2] == "v0.1.0", f)

    # 3. A check never installs anything, the deploy script included.
    check("check does not self-update hestia-deploy",
          not (home / ".local/bin/hestia-deploy").exists(), err)
    check("check does not touch the daemon binary", binf.read_text().count("v0.1.0") == 1)

    # 4. A hold stops deploys, not checks.
    (hh / "deploy.hold").write_text("test hold\n")
    rc, f, err = run(home, hh, daemon, atlas)
    check("hold present: check still runs", rc == 3 and f[:1] == ["available"], err)
    (hh / "deploy.hold").unlink()

    # 5. A check that cannot sync says so.
    (hh / "deploy/hestia").rename(hh / "deploy/hestia.away")
    rc, f, err = run(home, hh, daemon, atlas)
    check("no deploy checkout: non-zero, not 3", rc not in (0, 3), err)
    check("no deploy checkout: state failed", f[:1] == ["failed"], f)
    (hh / "deploy/hestia.away").rename(hh / "deploy/hestia")

    daemon.server.shutdown()

if FAILS:
    raise SystemExit(f"{len(FAILS)} check(s) failed: " + ", ".join(FAILS))
print("hestia-deploy --check: PASS")
