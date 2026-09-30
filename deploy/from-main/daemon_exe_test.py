#!/usr/bin/env python3
"""On macOS, `daemon_exe` names the file the daemon runs -- never the /bin/sh that wraps it.

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

GPT on #1185: the first fix still answered `program` for a daemon that is NOT running, which for
the wrapper is /bin/sh again -- refusing exactly the deploy that would bring a stopped daemon
back. So a stopped wrapper now answers its `exec` target (a literal $HOME, as install.sh writes,
expanded), or nothing when it cannot be read; a legacy direct-program agent still answers its
`program`.

This runs the real `canon` and `daemon_exe`, brace-matched out of the real script, and the real
guard block, under `set -euo pipefail`, with `launchctl` and `ps` mocked on PATH.

Run: python3 daemon_exe_test.py     (no pytest needed; exit 1 on failure)
"""
from __future__ import annotations

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
    m = re.search(rf"^{re.escape(fname)}\(\) *\{{", text, re.M)
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


def extract_guard(text: str) -> str:
    """The real BIN guard: from `exe="$(daemon_exe)"` through its closing `fi`."""
    m = re.search(r'^exe="\$\(daemon_exe\)"\n(?:.*\n)*?fi\n', text, re.M)
    assert m, "the BIN guard was not found in hestia-deploy.sh"
    return m.group(0)


def agent(program: str, args: list[str], pid: int | None) -> str:
    lines = ["gui/501/com.web4.hestia.daemon = {", "\tactive count = 1",
             f"\tstate = {'running' if pid else 'not running'}", f"\tprogram = {program}",
             "\targuments = {"] + [f"\t\t{a}" for a in args] + ["\t}"]
    if pid:
        lines.append(f"\tpid = {pid}")
    return "\n".join(lines + ["}", ""])


PP = 'HESTIA_PASSPHRASE="$(cat /Users/x/.hestia/.passphrase)"'


def run(launchctl_out: str | None, ps_out: str, bin_path: str | None = None, home: str | None = None):
    """(rc, stdout) of daemon_exe; with bin_path, (rc, stderr) of the real guard instead."""
    text = SCRIPT.read_text()
    fns = extract_function(text, "canon") + "\n" + extract_function(text, "daemon_exe")
    with tempfile.TemporaryDirectory() as d:
        bindir = Path(d) / "mockbin"
        bindir.mkdir()
        (bindir / "launchctl.out").write_text(launchctl_out or "")
        (bindir / "ps.out").write_text(ps_out)
        lc = bindir / "launchctl"
        lc.write_text("#!/bin/sh\n" + (f'cat "{bindir}/launchctl.out"\n' if launchctl_out is not None
                                         else "echo 'Could not find service' >&2; exit 113\n"))
        ps = bindir / "ps"
        ps.write_text(f'#!/bin/sh\ncat "{bindir}/ps.out"\n')
        for f in (lc, ps):
            f.chmod(0o755)
        prelude = "set -euo pipefail\nOS=Darwin\nLAUNCHD_LABEL=com.web4.hestia.daemon\nUNIT=hestia.service\n"
        if bin_path is None:
            body = "daemon_exe\n"
        else:
            body = ('die() { echo "FAIL $*" >&2; exit 1; }\n'
                    f'BIN="{bin_path}"\n' + extract_guard(text) + 'echo "guard passed" >&2\n')
        env = {"PATH": f"{bindir}:/usr/bin:/bin", "HOME": home or d}
        p = subprocess.run(["bash", "-c", prelude + fns + "\n" + body],
                           capture_output=True, text=True, env=env, timeout=30)
        return p.returncode, (p.stdout if bin_path is None else p.stderr).strip()


WRAP_ABS = ["/bin/sh", "-c", f"{PP} exec /opt/homebrew/bin/hestia serve"]
WRAP_HOME = ["/bin/sh", "-c", 'HESTIA_PASSPHRASE="$(cat $HOME/.hestia/.passphrase)" exec $HOME/.local/bin/hestia serve --bind 127.0.0.1:7711']
WRAP_QUOTED = ["/bin/sh", "-c", f"{PP} exec '/opt/homebrew/bin/hestia' 'serve'"]
WRAP_NO_EXEC = ["/bin/sh", "-c", "/opt/homebrew/bin/hestia serve"]
DIRECT = ["/opt/homebrew/bin/hestia", "serve"]

# Running: the image, whatever launchd started.
rc, out = run(agent("/bin/sh", WRAP_ABS, 2062), "/opt/homebrew/bin/hestia\n")
check("running wrapper: rc", rc, 0)
check("running wrapper resolves to the running image, not /bin/sh", out, "/opt/homebrew/bin/hestia")

# Stopped wrapper: its exec target, never /bin/sh.
rc, out = run(agent("/bin/sh", WRAP_ABS, None), "")
check("stopped wrapper: rc", rc, 0)
check("stopped wrapper resolves to its exec target", out, "/opt/homebrew/bin/hestia")

rc, out = run(agent("/bin/sh", WRAP_ABS, 2062), "")
check("unseen pid, wrapper: rc", rc, 0)
check("unseen pid on a wrapper resolves to its exec target", out, "/opt/homebrew/bin/hestia")

rc, out = run(agent("/bin/sh", WRAP_HOME, None), "", home="/Users/x")
check("stopped install.sh wrapper: rc", rc, 0)
check("stopped install.sh wrapper expands its literal $HOME", out, "/Users/x/.local/bin/hestia")

rc, out = run(agent("/bin/sh", WRAP_QUOTED, None), "")
check("stopped quoted wrapper strips the quotes", out, "/opt/homebrew/bin/hestia")

rc, out = run(agent("/bin/sh", WRAP_NO_EXEC, None), "")
check("unreadable wrapper: rc", rc, 0)
check("a wrapper with no exec target is unknown, not /bin/sh", out, "")

# Stopped legacy direct-program agent: its program, as before.
rc, out = run(agent("/opt/homebrew/bin/hestia", DIRECT, None), "")
check("stopped direct agent: rc", rc, 0)
check("stopped direct agent resolves to its program", out, "/opt/homebrew/bin/hestia")

rc, out = run(None, "")
check("no launchd job: rc", rc, 0)
check("no launchd job prints nothing", out, "")

# The guard itself, with a real BIN file for canon to resolve.
with tempfile.TemporaryDirectory() as h:
    real_bin = Path(h) / ".local/bin/hestia"
    real_bin.parent.mkdir(parents=True)
    real_bin.write_text("")
    rc, err = run(agent("/bin/sh", WRAP_HOME, None), "", bin_path=str(real_bin), home=h)
    check("guard: stopped canonical wrapper passes", (rc, err), (0, "guard passed"))
    rc, err = run(agent("/bin/sh", WRAP_HOME, 77), f"{real_bin}\n", bin_path=str(real_bin), home=h)
    check("guard: running canonical wrapper passes", (rc, err), (0, "guard passed"))
    rc, err = run(agent("/usr/local/bin/hestia", ["/usr/local/bin/hestia", "serve"], None), "",
                  bin_path=str(real_bin), home=h)
    check("guard: a real mismatch still refuses", rc, 1)
    check("guard: the refusal names the other path", "executing /usr/local/bin/hestia" in err, True)

if FAILS:
    print("FAIL\n  " + "\n  ".join(FAILS))
    sys.exit(1)
print("ok: daemon_exe and the BIN guard on macOS (running, stopped, wrapper, direct, guard)")
