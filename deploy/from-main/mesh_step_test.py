#!/usr/bin/env python3
"""`install_mesh` may fail in every way it likes, and never stops a deploy (#1373).

The same contract as install_inventory (inventory_step_test.py, whose harness this copies): the step that installs the
member-mesh watchers RETURNS 0 UNDER `set -euo pipefail` in every case, and leaves a `mesh=` value a human can act on.
It runs on every DEPLOYED and CURRENT cycle, so a step that could kill the deploy would kill it every 4 h on every host.

The installer is stubbed: what is pinned here is the deploy step's handling of what the installer does (refuse inside a
governed session, skip when absent or switched off, record the installer's last line, survive an installer that dies or
prints nothing). plugins/member-mesh/tests/install_watchers_test.sh covers the installer itself.

Run: python3 mesh_step_test.py     (no pytest; exit 1 on failure)
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
    m = re.search(rf"^{re.escape(fname)}\(\) *\{{\s*$", text, re.M)
    assert m, f"{fname}() not found in hestia-deploy.sh"
    depth, i = 0, m.start()
    for j in range(m.start(), len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    raise AssertionError(f"{fname}() is not brace-balanced")


def clean_env(**extra: str) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDECODE", "HESTIA_ROLE", "HESTIA_WORKSPACE", "HESTIA_DEPLOY_MESH")}
    env.update(extra)
    return env


def run(fn_src: str, deploy_root: Path, env: dict) -> tuple[int, str]:
    prog = (f"set -euo pipefail\nDEPLOY_ROOT={deploy_root}\nLOG={deploy_root}/deploy.log\nHESTIA_HOME={deploy_root}/hh\n"
            f"MODE=full\n{fn_src}\ninstall_mesh\nprintf 'STATUS=%s\\n' \"$mesh\"\n")
    r = subprocess.run(["bash", "-c", prog], capture_output=True, text=True, env=env, timeout=60)
    m = re.search(r"^STATUS=(.*)$", r.stdout, re.M)
    return r.returncode, (m.group(1) if m else f"<no status; stderr: {r.stderr.strip()[:160]}>")


def stub(root: Path, body: str | None) -> None:
    d = root / "hestia" / "plugins" / "member-mesh"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "install-watchers.sh"
    if body is None:
        if p.exists():
            p.unlink()
        return
    p.write_text("#!/usr/bin/env bash\n" + body + "\n")


def main() -> int:
    text = SCRIPT.read_text()
    fn = extract_function(text, "install_mesh")
    # the step is called on every path the inventory is called on (HOOKS-ONLY, manifest repair, CURRENT, DEPLOYED)
    check("install_mesh calls", text.count("\n  install_mesh\n") + text.count("\n    install_mesh\n")
          + text.count("install_inventory; install_mesh;") + text.count("\ninstall_mesh\n"), 4)
    for word in ("HOOKS-ONLY", "manifest-repair", "DEPLOYED"):
        # the cycle's summary line (HALF-DEPLOYED lines are hook-repair messages, not summaries)
        lines = [ln for ln in text.splitlines() if 'log "' in ln and word in ln and "hooks=$hooks " in ln
                 and "HALF-DEPLOYED" not in ln]
        check(f"{word}: one summary line", len(lines), 1)
        check(f"{word} line records mesh=", all("mesh=$mesh" in ln for ln in lines), True)
    plain = [ln for ln in text.splitlines() if 'log "CURRENT $target${inventory' in ln]
    check("plain CURRENT line records mesh=", len(plain) == 1 and "mesh=$mesh" in plain[0], True)

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "hh").mkdir()
        cases = [
            ("governed session (CLAUDECODE)", 'echo "mesh: claude-code=active"', clean_env(CLAUDECODE="1"),
             "refused(governed session)"),
            ("governed session (HESTIA_ROLE)", 'echo "mesh: claude-code=active"',
             clean_env(HESTIA_ROLE="role:x"), "refused(governed session)"),
            ("switched off", 'echo "mesh: claude-code=active"', clean_env(HESTIA_DEPLOY_MESH="0"),
             "skipped(HESTIA_DEPLOY_MESH=0)"),
            ("no installer in the checkout", None, clean_env(), "skipped(no installer in the checkout)"),
            ("summary recorded, spaces become commas",
             'echo "  claude-code: active(print-only)"; echo "mesh: claude-code=active kimi-code=absent"',
             clean_env(), "claude-code=active,kimi-code=absent"),
            ("an empty summary still says something", 'echo "mesh:"', clean_env(), "none"),
            ("installer prints no summary", 'echo "half a line"', clean_env(),
             "FAILED(no summary line from install-watchers.sh)"),
            # a dying installer must not end the deploy (set -e + pipefail), and a summary it printed before dying
            # is not believed: rc != 0 means it did not finish
            ("installer dies", 'echo "mesh: x=y"; exit 7', clean_env(), "FAILED(install-watchers.sh rc=7)"),
            ("installer killed mid-line", 'printf "mesh: claude-code=act"; kill -9 $$', clean_env(),
             "FAILED(install-watchers.sh rc=137)"),
        ]
        for name, body, env, want in cases:
            stub(root, body)
            rc, got = run(fn, root, env)
            check(f"{name}: rc", rc, 0)
            check(f"{name}: mesh", got, want)

    for f in FAILS:
        print("FAIL", f)
    print(f"mesh_step_test: {'FAIL' if FAILS else 'ok'} ({len(FAILS)} failures)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
