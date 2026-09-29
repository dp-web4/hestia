#!/usr/bin/env python3
"""hestia-deploy's secret_hygiene(): warn-only, every cycle (hestia #1152).

The function is lifted out of hestia-deploy.sh and run under bash with a stub `log`, against
fake homes: a legacy seat (passphrase inline, home 755), a canonical one (nothing to say), and a
Linux-shaped unit with an Environment= line vs the installer's ExecStart `cat` form. The macOS
cases need plutil and run only on a Mac; the Linux-unit case runs anywhere.

Run: python3 deploy/from-main/secret_hygiene_test.py     (exit 1 on failure)
"""
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SRC = (Path(__file__).resolve().parent / "hestia-deploy.sh").read_text()
FN = re.search(r"^secret_hygiene\(\) \{.*?^\}$", SRC, re.S | re.M).group(0)
FAILS = []


def check(name, got, want=True):
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


def run(home, os_name, label="com.web4.hestia.daemon", unit="hestia.service"):
    prog = (f'log() {{ printf "%s\\n" "$*"; }}\nOS={os_name}\nLAUNCHD_LABEL={label}\nUNIT={unit}\n'
            f'DEPLOY_ROOT=/deploy\nHESTIA_HOME={home}/.hestia\n{FN}\nsecret_hygiene; echo "rc=$?"')
    return subprocess.run(["bash", "-c", prog], capture_output=True, text=True,
                          env=dict(os.environ, HOME=str(home))).stdout


def plist(path, inline):
    env = {"HESTIA_HOME": "/h"}
    if inline:
        env["HESTIA_PASSPHRASE"] = "not-a-real-one"
    path.write_bytes(plistlib.dumps({"Label": "com.web4.hestia.daemon", "EnvironmentVariables": env}))


def main():
    mac = platform.system() == "Darwin" and shutil.which("plutil")
    with tempfile.TemporaryDirectory(dir=str(Path.home())) as tmp:
        home = Path(tmp)
        (home / ".hestia").mkdir()
        agents = home / "Library/LaunchAgents"; agents.mkdir(parents=True)
        if mac:
            os.chmod(home / ".hestia", 0o755)
            plist(agents / "com.web4.hestia.daemon.plist", inline=True)
            out = run(home, "Darwin")
            check("legacy mac seat: the inline passphrase is named", "passphrase is INLINE" in out)
            check("...with the fix", "canonicalize-macos-seat.sh" in out)
            check("...and the loose home", "is mode 755, not 700" in out)
            check("the value itself is never printed", "not-a-real-one" in out, False)
            check("warn-only: the function returns 0", out.strip().endswith("rc=0"))
            os.chmod(home / ".hestia", 0o700)
            plist(agents / "com.web4.hestia.daemon.plist", inline=False)
            out = run(home, "Darwin")
            check("canonical mac seat: silent", [l for l in out.splitlines() if l.startswith("WARN")], [])
        units = home / ".config/systemd/user"; units.mkdir(parents=True)
        (units / "hestia.service").write_text(
            "[Service]\nEnvironment=HESTIA_HOME=%h/.hestia\n"
            "ExecStart=/bin/sh -c 'HESTIA_PASSPHRASE=\"$(cat %h/.hestia/.passphrase)\" exec hestia serve'\n")
        out = run(home, "Linux")
        check("linux, installer's cat form: NOT flagged", "INLINE" in out, False)
        (units / "hestia.service").write_text("[Service]\nEnvironment=\"HESTIA_PASSPHRASE=hunter2\"\n")
        out = run(home, "Linux")
        check("linux, Environment= line: flagged", "passphrase is INLINE" in out)
        check("linux: the value is never printed", "hunter2" in out, False)
    if not mac:
        print("SKIPPED: the macOS cases (need plutil); the Linux-unit cases ran")
    for f in FAILS:
        print("FAIL", f)
    print(f"secret hygiene: {'FAIL' if FAILS else 'PASS'} ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
