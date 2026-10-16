#!/usr/bin/env python3
"""install.sh installs the deploy supervisor on a checkout install, with the timer OFF.

Runs install.sh's own step_deploy_supervisor, extracted from the script, in a temporary HOME
with `git`, `cargo`, `systemctl` and `uname` replaced by stubs. No network, no real install.
The stub systemctl records every call, so "the timer stays off" is checked as "nothing asked
systemd to enable it", not inferred from a missing file.
"""
import os
import pathlib
import re
import subprocess
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = (HERE / "install.sh").read_text()
FAILS = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f" -- {detail}"))
    if not ok:
        FAILS.append(name)


def func(name):
    m = (re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", SCRIPT, re.S | re.M)
         or re.search(rf"^{name}\(\)\s+\{{[^\n]*\}}\n", SCRIPT, re.M))  # one-line form
    assert m, name
    return m.group(0)


BODY = "\n".join(func(n) for n in ("c_dim", "c_ok", "c_warn", "c_err", "c_hdr",
                                   "step_deploy_supervisor"))

# The REAL shipped files, so the HESTIA_WORKSPACE substitution is tested against the unit that
# actually ships, not a copy of what it looked like when this test was written.
FROM_MAIN = HERE.parent / "from-main"
assert "\nEnvironment=HESTIA_WORKSPACE=\n" in (FROM_MAIN / "hestia-deploy.service").read_text(), \
    "hestia-deploy.service no longer ships an empty HESTIA_WORKSPACE= line; update install.sh's sed"


def stub(d, name, body):
    p = d / name
    p.write_text("#!/bin/sh\n" + body)
    p.chmod(0o755)


def run(*, workspace="ws", cargo=True, os_name="Linux", env_extra=None, timer_enabled=False):
    with tempfile.TemporaryDirectory() as t:
        t = pathlib.Path(t)
        home, bin_stubs = t / "home", t / "stubs"
        home.mkdir()
        bin_stubs.mkdir()
        calls = t / "systemctl.log"
        # git clone <url> <dest>: lay down the deploy/from-main files a real clone would carry.
        stub(bin_stubs, "git", f"""dest="$4"
mkdir -p "$dest/.git" "$dest/deploy/from-main"
cp "{FROM_MAIN}/hestia-deploy.sh" "{FROM_MAIN}/hestia-deploy.service" "{FROM_MAIN}/hestia-deploy.timer" "$dest/deploy/from-main/"
""")
        if cargo:
            stub(bin_stubs, "cargo", "exit 0\n")
        stub(bin_stubs, "systemctl", f"""echo "$*" >> "{calls}"
case "$*" in *is-enabled*) [ "{int(timer_enabled)}" = 1 ] && exit 0 || exit 1 ;; esac
exit 0
""")
        stub(bin_stubs, "uname", f"echo {os_name}\n")
        ws = ""
        if workspace:
            ws = str(t / workspace)
            os.makedirs(ws)
        env = {
            "PATH": f"{bin_stubs}:/usr/bin:/bin",
            "HOME": str(home),
            "HESTIA_HOME": str(home / ".hestia"),
            "HESTIA_WORKSPACE": ws,
            "BIN_DIR": str(home / ".local/bin"),
        }
        env.update(env_extra or {})
        script = "set -euo pipefail\n" + BODY + "\nstep_deploy_supervisor\n"
        r = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
        unit = home / ".config/systemd/user/hestia-deploy.service"
        return {
            "rc": r.returncode,
            "out": r.stdout + r.stderr,
            "calls": calls.read_text().splitlines() if calls.exists() else [],
            "unit": unit.read_text() if unit.exists() else None,
            "timer": (home / ".config/systemd/user/hestia-deploy.timer").exists(),
            "script": (home / ".local/bin/hestia-deploy").exists(),
            "ws": ws,
        }


# 1. A checkout install gets a working update button, and the schedule stays off.
r = run()
check("checkout install exits 0", r["rc"] == 0, r["out"])
check("hestia-deploy script installed", r["script"], r["out"])
check("service unit installed", r["unit"] is not None, r["out"])
check("timer unit installed", r["timer"], r["out"])
check("HESTIA_WORKSPACE rendered into the unit",
      r["unit"] is not None and f"Environment=HESTIA_WORKSPACE={r['ws']}\n" in r["unit"], r["unit"])
check("units reloaded", "--user daemon-reload" in r["calls"], r["calls"])
check("timer NOT enabled by default", not any("enable" in c and "is-enabled" not in c for c in r["calls"]),
      r["calls"])
check("says auto-update is off", "auto-update OFF" in r["out"], r["out"])

# 2. Opt-in arms the timer.
r = run(env_extra={"HESTIA_AUTO_UPDATE": "1"})
check("HESTIA_AUTO_UPDATE=1 enables the timer",
      "--user enable --now hestia-deploy.timer" in r["calls"], r["calls"])

# 3. A re-run on a box whose timer is already on leaves it on.
r = run(timer_enabled=True)
check("armed timer is left armed", not any("disable" in c for c in r["calls"]), r["calls"])
check("says it left it on", "already ON" in r["out"], r["out"])

# 4. Release install (no checkout): skipped with the reason, nothing written.
r = run(workspace="")
check("release install skips", r["rc"] == 0 and r["unit"] is None and not r["script"], r["out"])
check("release install says why", "release install" in r["out"], r["out"])

# 5. No cargo: skipped with the reason, nothing written.
r = run(cargo=False)
check("missing cargo skips", r["rc"] == 0 and r["unit"] is None, r["out"])
check("missing cargo is named", "needs cargo" in r["out"], r["out"])

# 6. Explicit opt-out, and macOS (not automated yet).
r = run(env_extra={"HESTIA_SKIP_DEPLOY": "1"})
check("HESTIA_SKIP_DEPLOY skips", r["unit"] is None and r["calls"] == [], r["out"])
r = run(os_name="Darwin")
check("macOS points at the README", r["unit"] is None and "README" in r["out"], r["out"])

if FAILS:
    raise SystemExit(f"{len(FAILS)} check(s) failed: " + ", ".join(FAILS))
print("deploy supervisor install step: PASS")
