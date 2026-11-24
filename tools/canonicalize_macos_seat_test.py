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


def seat(tmp, *, inline=True, passfile=None, argv_tail=("serve",), sub="hestia"):
    home = Path(tmp) / sub; home.mkdir(); os.chmod(home, 0o755)
    agents = Path(tmp) / "agents"; agents.mkdir()
    # The fake daemon RECORDS what it is handed: its env's passphrase and its argv, one per line.
    binp = Path(tmp) / "bin hestia"
    binp.write_text('#!/bin/sh\nprintf "%s\\n" "$HESTIA_PASSPHRASE" "$@" > "$(dirname "$0")/daemon.out"\n')
    os.chmod(binp, 0o755)
    env = {"HESTIA_HOME": str(home), "HESTIA_WORKSPACE": "/w", "HESTIA_CURRENT_BUILD_FILE": str(home / "current-build.json")}
    if inline:
        env["HESTIA_PASSPHRASE"] = FAKE
    pl = {"Label": "com.web4.hestia.daemon", "ProgramArguments": [str(binp), *argv_tail],
          "EnvironmentVariables": env, "RunAtLoad": True, "KeepAlive": True,
          "StandardOutPath": "/tmp/x.log"}
    p = agents / "com.web4.hestia.daemon.plist"
    p.write_bytes(plistlib.dumps(pl)); os.chmod(p, 0o644)
    if passfile is not None:
        (home / ".passphrase").write_text(passfile); os.chmod(home / ".passphrase", 0o600)
    return home, agents, p, binp


def run(home, agents, *args, **extra):
    e = dict(os.environ, HESTIA_HOME=str(home), CANON_AGENT_DIR=str(agents), CANON_NO_RESTART="1")
    e.update(extra)
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
        check("ProgramArguments is the installer's /bin/sh -c shape", pl["ProgramArguments"][:2], ["/bin/sh", "-c"])
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
        # EXECUTE the rewritten line, as launchd will: the fake daemon records the passphrase it
        # inherited and the argv it got. What runs, not a string about it.
        ex = subprocess.run(["/bin/sh", "-c", plistlib.loads(p.read_bytes())["ProgramArguments"][2]],
                            capture_output=True, text=True)
        check("executed: the rewritten command line runs at all", (ex.returncode, ex.stderr[-160:]), (0, ""))
        out = binp.parent / "daemon.out"
        check("executed: the daemon gets the passphrase and exactly its original argv",
              out.read_text().splitlines() if out.exists() else None, [FAKE, "serve"])

    with tempfile.TemporaryDirectory(dir=str(Path.home())) as tmp:
        home, agents, p, _ = seat(tmp, passfile="a-different-one")
        r = run(home, agents, "--apply")
        check("inline and file DISAGREE: refused", (r.returncode != 0, "DIFFER" in r.stderr), (True, True))
        check("...and nothing was touched", "HESTIA_PASSPHRASE" in plistlib.loads(p.read_bytes())["EnvironmentVariables"], True)

    with tempfile.TemporaryDirectory(dir=str(Path.home())) as tmp:
        home, agents, p, _ = seat(tmp, inline=False)
        r = run(home, agents, "--apply")
        check("no passphrase source at all: refused", (r.returncode != 0, "no passphrase source" in r.stderr), (True, True))

    # GPT, review of #1154: paths with SPACES, and a seat's own non-default bind and options, must
    # survive; the first cut rebuilt `serve --bind <default>` from unquoted paths.
    with tempfile.TemporaryDirectory(prefix="with space ", dir=str(Path.home())) as tmp:
        home, agents, p, binp = seat(tmp, sub="hestia home",
                                     argv_tail=("serve", "--bind", "127.0.0.1:7799", "--verbose"))
        r = run(home, agents, "--apply")
        check("spaces + a non-default bind: applies", (r.returncode, r.stderr[-200:]), (0, ""))
        ex = subprocess.run(["/bin/sh", "-c", plistlib.loads(p.read_bytes())["ProgramArguments"][2]],
                            capture_output=True, text=True)
        check("spaces: the rewritten command line runs at all", (ex.returncode, ex.stderr[-160:]), (0, ""))
        out = binp.parent / "daemon.out"
        check("spaces: both paths work and the argv is kept verbatim",
              out.read_text().splitlines() if out.exists() else None,
              [FAKE, "serve", "--bind", "127.0.0.1:7799", "--verbose"])
        check("...and it is recognised as canonical on the next run", "already canonical" in run(home, agents).stdout)

    with tempfile.TemporaryDirectory(dir=str(Path.home())) as tmp:
        home, agents, p, _ = seat(tmp, argv_tail=("status",))
        r = run(home, agents)
        check("an agent that does not run `hestia serve` is refused, not rewritten",
              (r.returncode != 0, "does not run" in r.stderr), (True, True))

    # THE ROLLBACK, both ways the restart can fail. A mock launchctl records every call and can
    # refuse the FIRST bootstrap (the rewritten agent) while accepting the rollback's.
    def mock_launchctl(tmp, fail_first_bootstrap):
        log, n, m = Path(tmp) / "launchctl.log", Path(tmp) / "boot.count", Path(tmp) / "launchctl"
        m.write_text(f"""#!/bin/sh
echo "$@" >> "{log}"
if [ "$1" = bootstrap ]; then
  c=$(cat "{n}" 2>/dev/null || echo 0); c=$((c+1)); echo $c > "{n}"
  [ "{int(fail_first_bootstrap)}" = 1 ] && [ $c = 1 ] && exit 5
fi
exit 0
""")
        os.chmod(m, 0o755)
        return m, log

    for label, fail_boot in (("bootstrap refused", True), ("daemon never answers", False)):
        with tempfile.TemporaryDirectory(dir=str(Path.home())) as tmp:
            # A bind NOTHING listens on. The default (7711) is this machine's REAL daemon, which
            # answered the health check in the first run of this test -- so "the daemon never
            # answers" passed as a success. The health check follows the agent's own --bind.
            home, agents, p, _ = seat(tmp, argv_tail=("serve", "--bind", "127.0.0.1:9"))
            original = p.read_bytes()
            m, log = mock_launchctl(tmp, fail_boot)
            r = run(home, agents, "--apply", CANON_NO_RESTART="0", CANON_LAUNCHCTL=str(m), CANON_HEALTH_TRIES="1")
            calls = [c.split()[0] for c in log.read_text().splitlines()]
            check(f"{label}: exits non-zero, saying it rolled back",
                  (r.returncode != 0, "ROLLING BACK" in r.stderr), (True, True))
            check(f"{label}: the ORIGINAL agent is back, byte for byte", p.read_bytes() == original, True)
            check(f"{label}: ...and was restarted", calls, ["bootout", "bootstrap", "bootout", "bootstrap"])
            check(f"{label}: the restored agent is 600, since it holds the passphrase", mode(p), 0o600)
            check(f"{label}: the passphrase file is kept", (home / ".passphrase").read_text(), FAKE)
            check(f"{label}: the passphrase is never printed", FAKE in r.stdout + r.stderr, False)

    for f in FAILS:
        print("FAIL", f)
    print(f"canonicalize macOS seat: {'FAIL' if FAILS else 'PASS'} ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
