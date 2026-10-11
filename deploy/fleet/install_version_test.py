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
                    if line.startswith(("REPO=", "FALLBACK_VERSION=")))
PRELUDE += "\n" + "\n".join(func(n) for n in ("c_warn", "c_err", "resolve_version", "guard_downgrade"))


def run(*, api_json=None, installed=None, pin="", allow=""):
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        stub = d / "curl"
        if api_json is None:
            stub.write_text("#!/bin/sh\nexit 22\n")
        else:
            (d / "api.json").write_text(api_json)
            stub.write_text(f"#!/bin/sh\ncat '{d / 'api.json'}'\n")
        stub.chmod(0o755)
        binp = d / "hestia"
        if installed:
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
check("API unreachable: falls back to the floor, and says so",
      rc == 0 and "VERSION=v0.0.4" in out and "could not resolve" in out, out)
rc, out = run(api_json='{"message": "API rate limit exceeded"}')
check("API answers without a tag: falls back", rc == 0 and "VERSION=v0.0.4" in out, out)
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
check("no literal v0.0.3 default remains", 'DEFAULT_VERSION="v0.0.3"' not in SCRIPT)

raise SystemExit(1 if FAILS else 0)
