#!/usr/bin/env python3
"""The deploy names an old unit that cannot read the current-build manifest (#1069)."""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEXT = (HERE / "hestia-deploy.sh").read_text()
FAILS: list[str] = []


def check(name: str, got, want) -> None:
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


def extract_function(fname: str) -> str:
    m = re.search(rf"^{re.escape(fname)}\(\) *\{{", TEXT, re.M)
    assert m, f"{fname}() not found"
    depth = 0
    for j in range(m.start(), len(TEXT)):
        if TEXT[j] == "{":
            depth += 1
        elif TEXT[j] == "}":
            depth -= 1
            if depth == 0:
                return TEXT[m.start():j + 1]
    raise AssertionError(f"{fname}() never closes")


def run(*, mode="full", os_name="Linux", environment="", manifest=True, systemctl=True) -> str:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        home = root / ".hestia"
        home.mkdir()
        if manifest:
            (home / "current-build.json").write_text('{"build_id":"v0.0.4-test"}\n')
        mock = root / "mockbin"
        mock.mkdir()
        if systemctl:
            rendered = environment.replace("<HOME>", str(home))
            (mock / "systemctl").write_text(f"#!/bin/sh\nprintf '%s\\n' '{rendered}'\n")
            (mock / "systemctl").chmod(0o755)
        body = (
            "set -euo pipefail\n"
            f"MODE={mode}\nOS={os_name}\nUNIT=hestia.service\n"
            f"HESTIA_HOME={home}\nLOG={root / 'log'}\n"
            "log() { printf '%s\\n' \"$*\" >&2; }\n"
            + extract_function("warn_current_build_env")
            + "\nwarn_current_build_env\n"
        )
        path = f"{mock}:/usr/bin:/bin" if systemctl else str(mock)
        env = {"PATH": path, "HOME": str(root)}
        r = subprocess.run(["/bin/bash", "-c", body], capture_output=True, text=True, env=env, timeout=30)
        assert r.returncode == 0, r.stderr
        return r.stderr.strip()


OLD = run(environment="HESTIA_HOME=/tmp/home")
check("an old unit warns and names the manifest", "HESTIA_CURRENT_BUILD_FILE=" in OLD and "deployment: unknown" in OLD, True)
check("the warning names the unit", "hestia.service does not export" in OLD, True)
check("the exact path stays quiet", run(environment="HESTIA_CURRENT_BUILD_FILE=<HOME>/current-build.json"), "")
check("a different manifest path warns", "HESTIA_CURRENT_BUILD_FILE=" in run(environment="HESTIA_CURRENT_BUILD_FILE=/elsewhere/current-build.json"), True)
check("the exact path among other variables stays quiet",
      run(environment="HESTIA_HOME=<HOME> HESTIA_CURRENT_BUILD_FILE=<HOME>/current-build.json PATH=/usr/bin"), "")
check("the path under another variable name warns",
      "HESTIA_CURRENT_BUILD_FILE=" in run(environment="OTHER_FILE=<HOME>/current-build.json"), True)
check("a longer path that starts with the expected one warns",
      "HESTIA_CURRENT_BUILD_FILE=" in run(environment="HESTIA_CURRENT_BUILD_FILE=<HOME>/current-build.json.bak"), True)
check("no manifest means no authority warning", run(manifest=False), "")
check("check mode does not warn", run(mode="--check"), "")
check("non-Linux is not probed", run(os_name="Darwin"), "")
check("no systemctl is not an error", run(systemctl=False), "")
check("all three success boundaries call the warning", TEXT.count("warn_current_build_env\n") >= 3, True)

if FAILS:
    print("FAIL\n  " + "\n  ".join(FAILS))
    raise SystemExit(1)
print("ok: old units warn at deploy success; exact paths and unsupported arms stay quiet")
