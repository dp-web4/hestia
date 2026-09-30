#!/usr/bin/env python3
"""On macOS, `daemon_exe` names the file the daemon is RUNNING, not the program launchd started.

WHY THIS EXISTS (McNugget, 2026-09-29).

The deploy refuses to install unless BIN is the file the daemon execs (the guard below
`daemon_exe` in hestia-deploy.sh). On Darwin, `daemon_exe` read launchd's `program`. The
canonical macOS agent -- what install.sh writes, and what canonicalize-macos-seat.sh converts a
legacy seat to -- is

    /bin/sh -c 'HESTIA_PASSPHRASE="$(cat ~/.hestia/.passphrase)" exec /opt/homebrew/bin/hestia serve'

so `program` is /bin/sh. After the exec the process IS hestia, but the guard compared /bin/sh to
BIN and failed. McNugget was canonicalized on 2026-09-28, and each of the next six deploys failed
with "BIN=/opt/homebrew/bin/hestia but the daemon ... is executing /bin/sh", while the daemon
fell 13 commits behind main. Linux never had this: it reads /proc/<pid>/exe, the running image.

This runs the real function, brace-matched out of the real script, under `set -euo pipefail`,
with `launchctl` and `ps` mocked on PATH:
  * the wrapped canonical agent resolves to the running hestia, not /bin/sh;
  * a daemon that is not running (no pid) falls back to `program`;
  * a pid that `ps` cannot see also falls back to `program`;
  * no launchd job at all prints nothing and still returns 0.

Run: python3 daemon_exe_test.py     (no pytest needed; exit 1 on failure)
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "hestia-deploy.sh"
FAILS: list[str] = []


def check(name: str, got, want) -> None:
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


def extract_function(text: str, fname: str) -> str:
    """The real function body, brace-matched from the real script -- not a copy of it."""
    m = re.search(rf"^{re.escape(fname)}\(\) *\{{\s*$", text, re.M)
    assert m, f"{fname}() not found in hestia-deploy.sh"
    depth = 0
    for j in range(m.start(), len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[m.start():j + 1]
    raise AssertionError(f"{fname}() never closes")


WRAPPED = """gui/501/com.web4.hestia.daemon = {
\tactive count = 1
\tpath = /Users/x/Library/LaunchAgents/com.web4.hestia.daemon.plist
\tstate = running
\tprogram = /bin/sh
\targuments = {
\t\t/bin/sh
\t\t-c
\t\tHESTIA_PASSPHRASE="$(cat /Users/x/.hestia/.passphrase)" exec /opt/homebrew/bin/hestia serve
\t}
\tpid = 2062
}
"""
STOPPED = WRAPPED.replace("\tstate = running\n", "\tstate = not running\n").replace("\tpid = 2062\n", "")


def run(launchctl_out: str | None, ps_out: str) -> tuple[int, str]:
    fn = extract_function(SCRIPT.read_text(), "daemon_exe")
    with tempfile.TemporaryDirectory() as d:
        bindir = Path(d)
        (bindir / "launchctl.out").write_text(launchctl_out or "")
        (bindir / "ps.out").write_text(ps_out)
        lc = bindir / "launchctl"
        lc.write_text("#!/bin/sh\n" + (f'cat "{bindir}/launchctl.out"\n' if launchctl_out is not None
                                         else "echo 'Could not find service' >&2; exit 113\n"))
        ps = bindir / "ps"
        ps.write_text(f'#!/bin/sh\ncat "{bindir}/ps.out"\n')
        for f in (lc, ps):
            f.chmod(0o755)
        prog = f"set -euo pipefail\nOS=Darwin\nLAUNCHD_LABEL=com.web4.hestia.daemon\n{fn}\ndaemon_exe\n"
        env = {"PATH": f"{bindir}:/usr/bin:/bin", "HOME": d}
        p = subprocess.run(["bash", "-c", prog], capture_output=True, text=True, env=env, timeout=30)
        return p.returncode, p.stdout.strip()


rc, out = run(WRAPPED, "/opt/homebrew/bin/hestia\n")
check("wrapped agent: rc", rc, 0)
check("wrapped agent resolves to the running image, not /bin/sh", out, "/opt/homebrew/bin/hestia")

rc, out = run(STOPPED, "")
check("stopped: rc", rc, 0)
check("stopped daemon falls back to program", out, "/bin/sh")

rc, out = run(WRAPPED, "")
check("pid ps cannot see: rc", rc, 0)
check("pid ps cannot see falls back to program", out, "/bin/sh")

rc, out = run(None, "")
check("no launchd job: rc", rc, 0)
check("no launchd job prints nothing", out, "")

if FAILS:
    print("FAIL\n  " + "\n  ".join(FAILS))
    sys.exit(1)
print("ok: daemon_exe reads the running image on macOS (4 cases)")
