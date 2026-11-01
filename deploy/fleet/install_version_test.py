#!/usr/bin/env python3
"""The fleet installer resolves the latest release and never silently downgrades (#520).

Runs install.sh's own resolve_version and guard_downgrade, extracted from the script, with
`curl` and the installed binary replaced by stubs. No network, no install.
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


PRELUDE = "\n".join(line for line in SCRIPT.splitlines()
                    if line.startswith(("REPO=",)))
PRELUDE += "\n" + "\n".join(func(n) for n in ("c_warn", "c_err", "c_dim", "resolve_version", "version_newer",
                                       "downgrade_opted_in", "guard_downgrade"))


def run(*, api_json=None, installed=None, pin="", allow="", raw_version=None, redirect=None):
    """api_json: the API's reply (None = unreachable). redirect: the releases/latest redirect
    target the second lookup sees (None = unreachable). #1444: no floor literal any more."""
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        stub = d / "curl"
        api = "exit 22"
        if api_json is not None:
            (d / "api.json").write_text(api_json)
            api = f"cat '{d / 'api.json'}'"
        red = "exit 22" if redirect is None else f"printf '%s' '{redirect}'"
        stub.write_text(f'#!/bin/sh\ncase "$*" in *redirect_url*) {red} ;; *) {api} ;; esac\n')
        stub.chmod(0o755)
        (d / "sort").write_text("#!/bin/sh\necho 'sort must not be called (no GNU sort -V on macOS)' >&2\nexit 99\n")
        (d / "sort").chmod(0o755)
        binp = d / "hestia"
        if raw_version is not None:
            binp.write_text(f"#!/bin/sh\necho '{raw_version}'\n")
            binp.chmod(0o755)
        elif installed:
            binp.write_text(f"#!/bin/sh\necho 'hestia {installed} (v{installed}-12-gabc1234)'\n")
            binp.chmod(0o755)
        body = (f"set -euo pipefail\nc_ok() {{ :; }}\n{PRELUDE}\nVERSION='{pin}'\nBIN_PATH='{binp}'\n"
                "resolve_version\nguard_downgrade\necho \"VERSION=$VERSION\"\n")
        env = dict(os.environ, PATH=f"{d}:{os.environ['PATH']}")
        if allow:
            env["HESTIA_ALLOW_DOWNGRADE"] = allow
        else:
            env.pop("HESTIA_ALLOW_DOWNGRADE", None)
        r = subprocess.run(["bash", "-c", body], capture_output=True, text=True, env=env)
        return r.returncode, r.stdout + r.stderr


LATEST = '{\n  "url": "x",\n  "tag_name": "v0.3.0",\n  "name": "v0.3.0"\n}\n'

rc, out = run(api_json=LATEST)
check("no pin: resolves GitHub's latest release", rc == 0 and "VERSION=v0.3.0" in out, out)
rc, out = run(api_json=None)
check("API and redirect unreachable: stops, names the remedy, installs nothing (#1444: no floor)",
      rc != 0 and "VERSION=" not in out and "could not resolve" in out and "HESTIA_VERSION" in out, out)
rc, out = run(api_json='{"message": "API rate limit exceeded"}')
check("API answers without a tag, no redirect: stops", rc != 0 and "VERSION=" not in out, out)
rc, out = run(api_json='{"message": "API rate limit exceeded"}',
              redirect="https://github.com/dp-web4/hestia/releases/tag/v0.3.0")
check("API rate-limited: the releases/latest redirect resolves the tag",
      rc == 0 and "VERSION=v0.3.0" in out, out)
rc, out = run(api_json=None, redirect="https://github.com/dp-web4/hestia/releases")
check("a redirect that names no tag is not a version", rc != 0 and "VERSION=" not in out, out)
rc, out = run(api_json=LATEST, pin="v0.0.4")
check("an explicit HESTIA_VERSION wins over latest", rc == 0 and "VERSION=v0.0.4" in out, out)
rc, out = run(api_json=LATEST, installed="0.3.0")
check("same version installed: proceeds (re-install is idempotent)", rc == 0, out)
rc, out = run(api_json=LATEST, installed="0.0.4")
check("older installed: upgrades", rc == 0 and "VERSION=v0.3.0" in out, out)
rc, out = run(pin="v0.0.3", installed="0.0.4")
check("newer installed: REFUSES the downgrade (#520)", rc == 1 and "refusing to downgrade" in out, out)
rc, out = run(pin="v0.0.3", installed="0.0.4", allow="1")
check("newer installed + HESTIA_ALLOW_DOWNGRADE: proceeds, loudly",
      rc == 0 and "downgrading hestia 0.0.4 -> 0.0.3" in out, out)
rc, out = run(pin="v0.0.10", installed="0.0.9")
check("versions compare numerically, not as text (0.0.10 > 0.0.9)", rc == 0, out)
rc, out = run(pin="v0.0.3", installed="0.0.4", allow="0")
check("HESTIA_ALLOW_DOWNGRADE=0 is NOT an opt-in (refuses)", rc == 1 and "refusing to downgrade" in out, out)
rc, out = run(pin="v0.0.3", installed="0.0.4", allow="false")
check("HESTIA_ALLOW_DOWNGRADE=false is NOT an opt-in", rc == 1, out)
for v in ("1", "true", "yes", "TRUE"):
    rc, out = run(pin="v0.0.3", installed="0.0.4", allow=v)
    check(f"HESTIA_ALLOW_DOWNGRADE={v} is an opt-in", rc == 0 and "downgrading" in out, out)
rc, out = run(pin="v0.0.3", raw_version="hestia (unknown build)")
check("installed version unreadable: FAILS CLOSED", rc == 1 and "cannot compare" in out, out)
rc, out = run(pin="v0.0.3", raw_version="hestia (unknown build)", allow="1")
check("installed version unreadable + opt-in: proceeds, loudly", rc == 0 and "cannot compare" in out, out)
rc, out = run(pin="main", installed="0.0.4")
check("target not X.Y.Z: FAILS CLOSED", rc == 1 and "cannot compare" in out, out)
rc, out = run(pin="v0.10.0", installed="0.9.12")
check("numeric per field (0.10.0 > 0.9.12)", rc == 0, out)
rc, out = run(pin="v1.0.0", installed="0.99.99")
check("major field dominates (1.0.0 > 0.99.99)", rc == 0, out)
check("no GNU sort -V in the script", "sort -V" not in SCRIPT)
check("no literal v0.0.3 default remains", 'DEFAULT_VERSION="v0.0.3"' not in SCRIPT)

raise SystemExit(1 if FAILS else 0)
