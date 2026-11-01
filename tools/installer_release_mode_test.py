#!/usr/bin/env python3
"""A release install (`curl | sh`, no checkout) runs with HESTIA_WORKSPACE set to empty.

WHY THIS EXISTS. install.sh runs under `set -euo pipefail`. Its header derives the workspace
from the checkout it sits in, and for a release install "keeps the empty value" -- but it
left the name UNSET, and the first bare `${HESTIA_WORKSPACE}` (the systemd unit heredoc on
Linux, the environment report on macOS) killed the install with "unbound variable". Every
PR-mode install smoke passed, because a checkout always derives a value. The v0.3.0-rc.5
smoke, the first against a published release, failed on three of five arms.

Runs the script's own top section (everything before BIN_DIR=) from a copy outside any
checkout, from a copy inside a fake checkout, and with an explicit value.
"""
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "deploy" / "fleet" / "install.sh").read_text()
FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f" -- {detail}"))
    if not ok:
        FAILS.append(name)


HEAD = SCRIPT[:SCRIPT.index("\nBIN_DIR=")]
assert "set -euo pipefail" in HEAD


def run(where: pathlib.Path, workspace=None):
    where.mkdir(parents=True, exist_ok=True)
    copy = where / "install.sh"
    copy.write_text(HEAD + '\nprintf "[%s]" "${HESTIA_WORKSPACE}"\n')
    env = {k: v for k, v in os.environ.items() if k != "HESTIA_WORKSPACE"}
    if workspace is not None:
        env["HESTIA_WORKSPACE"] = workspace
    return subprocess.run(["bash", str(copy)], capture_output=True, text=True, env=env, timeout=30)


with tempfile.TemporaryDirectory() as d:
    d = pathlib.Path(d).resolve()

    r = run(d / "release")
    check("release install: workspace is set, and empty", r.returncode == 0 and r.stdout == "[]",
          f"rc={r.returncode} out={r.stdout!r} err={r.stderr.strip()[-200:]!r}")

    ws = d / "ws"
    (ws / "hestia").mkdir(parents=True)
    (ws / "hestia" / ".git").mkdir()
    r = run(ws / "hestia" / "deploy" / "fleet")
    check("checkout install: workspace derived from the checkout", r.stdout == f"[{ws}]",
          f"rc={r.returncode} out={r.stdout!r} err={r.stderr.strip()[-200:]!r}")

    r = run(d / "release2", workspace="/srv/explicit")
    check("explicit HESTIA_WORKSPACE wins", r.stdout == "[/srv/explicit]",
          f"rc={r.returncode} out={r.stdout!r}")

print(f"\n{len(FAILS)} failure(s)")
sys.exit(1 if FAILS else 0)
