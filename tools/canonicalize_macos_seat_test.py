#!/usr/bin/env python3
"""canonicalize-macos-seat.sh, run against a FAKE legacy seat (temp HESTIA_HOME, temp agent dir,
a made-up passphrase, no restart). macOS only -- it needs plutil, as the script does.

The shape under test is McNugget's own (hestia #1152): passphrase inline in the plist, the plist
world-readable, HESTIA_HOME 755, unconditional KeepAlive, the binary run directly.

Run: python3 tools/canonicalize_macos_seat_test.py     (exit 1 on failure)
"""
import os
import platform
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy/fleet/canonicalize-macos-seat.sh"
FAILS = []
FAKE = "not-a-real-passphrase-7Qx"


def check(name, got, want=True):
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


def mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def seat(tmp, *, inline=True, passfile=None):
    home = Path(tmp) / "hestia"; home.mkdir(); os.chmod(home, 0o755)
    agents = Path(tmp) / "agents"; agents.mkdir()
    binp = Path(tmp) / "bin-hestia"; binp.write_text("#!/bin/sh\n"); os.chmod(binp, 0o755)
    env = {"HESTIA_HOME": str(home), "HESTIA_WORKSPACE": "/w", "HESTIA_CURRENT_BUILD_FILE": str(home / "current-build.json")}
    if inline:
        env["HESTIA_PASSPHRASE"] = FAKE
    pl = {"Label": "com.web4.hestia.daemon", "ProgramArguments": [str(binp), "serve"],
          "EnvironmentVariables": env, "RunAtLoad": True, "KeepAlive": True,
          "StandardOutPath": "/tmp/x.log"}
    p = agents / "com.web4.hestia.daemon.plist"
    p.write_bytes(plistlib.dumps(pl)); os.chmod(p, 0o644)
    if passfile is not None:
        (home / ".passphrase").write_text(passfile); os.chmod(home / ".passphrase", 0o600)
    return home, agents, p, binp


def run(home, agents, *args):
    e = dict(os.environ, HESTIA_HOME=str(home), CANON_AGENT_DIR=str(agents), CANON_NO_RESTART="1")
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=e)


def main():
    if platform.system() != "Darwin" or not shutil.which("plutil"):
        print("SKIPPED: macOS only (needs plutil)")
        return 0
    with tempfile.TemporaryDirectory(dir=str(Path.home())) as tmp:
        home, agents, p, binp = seat(tmp)
        before = p.read_bytes()
        r = run(home, agents)
        check("dry run succeeds", r.returncode, 0)
        check("dry run changes NOTHING", (p.read_bytes() == before, (home / ".passphrase").exists(), mode(home)),
              (True, False, 0o755))
        check("dry run names the passphrase move", "move the inline passphrase" in r.stdout)
        check("the passphrase is never printed, dry run", FAKE in r.stdout + r.stderr, False)

        r = run(home, agents, "--apply")
        check("apply succeeds", r.returncode, 0, ) if r.returncode == 0 else FAILS.append(f"apply failed: {r.stderr}")
        out = r.stdout + r.stderr
        check("the passphrase is never printed, apply", FAKE in out, False)
        check(".passphrase holds exactly the value, no newline", (home / ".passphrase").read_text(), FAKE)
        check(".passphrase is 600", mode(home / ".passphrase"), 0o600)
        check("HESTIA_HOME is 700", mode(home), 0o700)
        pl = plistlib.loads(p.read_bytes())
        check("the passphrase is GONE from the agent", "HESTIA_PASSPHRASE" in pl["EnvironmentVariables"], False)
        check("every other env key survives", sorted(pl["EnvironmentVariables"]),
              ["HESTIA_CURRENT_BUILD_FILE", "HESTIA_HOME", "HESTIA_WORKSPACE"])
        check("ProgramArguments is the installer's shape, reading the file",
              pl["ProgramArguments"][:2] == ["/bin/sh", "-c"]
              and f'HESTIA_PASSPHRASE="$(cat {home}/.passphrase)" exec {binp} serve' in pl["ProgramArguments"][2], True)
        check("KeepAlive restarts on a crash only", pl["KeepAlive"], {"SuccessfulExit": False})
        check("unrelated keys survive", (pl["Label"], pl["RunAtLoad"], pl["StandardOutPath"]),
              ("com.web4.hestia.daemon", True, "/tmp/x.log"))
        check("the agent lints", subprocess.run(["plutil", "-lint", str(p)], capture_output=True).returncode, 0)
        backups = list(home.glob("launchd-before-canonical-*.plist"))
        check("a rollback copy is kept", len(backups), 1)
        check("...mode 600, since it still holds the passphrase", backups and mode(backups[0]), 0o600)
        check("no temp file is left behind", list(home.glob(".canonical-*.plist")), [])

        r = run(home, agents)
        check("a second run is a no-op", ("already canonical" in r.stdout, r.returncode), (True, 0))
        # And the migrated agent really does run: the shell line, executed, finds the value.
        # The daemon is replaced by `env`, exec'd exactly as the daemon would be, so what it prints
        # is the environment the daemon would inherit. (A printf probe is wrong here: in
        # `VAR=x cmd "$VAR"` the shell expands $VAR BEFORE the assignment applies -- the first cut
        # of this check failed on exactly that, with the real line correct all along.)
        line = plistlib.loads(p.read_bytes())["ProgramArguments"][2]
        line = line[:line.index(f"exec {binp}")] + "exec /usr/bin/env"
        got = subprocess.run(["/bin/sh", "-c", line], capture_output=True, text=True, check=True).stdout
        check("the rewritten command line hands the daemon the right passphrase",
              f"HESTIA_PASSPHRASE={FAKE}" in got.splitlines(), True)

    with tempfile.TemporaryDirectory(dir=str(Path.home())) as tmp:
        home, agents, p, _ = seat(tmp, passfile="a-different-one")
        r = run(home, agents, "--apply")
        check("inline and file DISAGREE: refused", (r.returncode != 0, "DIFFER" in r.stderr), (True, True))
        check("...and nothing was touched", "HESTIA_PASSPHRASE" in plistlib.loads(p.read_bytes())["EnvironmentVariables"], True)

    with tempfile.TemporaryDirectory(dir=str(Path.home())) as tmp:
        home, agents, p, _ = seat(tmp, inline=False)
        r = run(home, agents, "--apply")
        check("no passphrase source at all: refused", (r.returncode != 0, "no passphrase source" in r.stderr), (True, True))

    for f in FAILS:
        print("FAIL", f)
    print(f"canonicalize macOS seat: {'FAIL' if FAILS else 'PASS'} ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
