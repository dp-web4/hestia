#!/usr/bin/env python3
"""`run_post_deploy` runs the operator's steps after a deploy, and never stops the deploy.

WHY THIS EXISTS (cbp-claude, 2026-10-22).

hestia #1362 deployed on CBP at 01:59Z. The being's readable copy of its law, a read-only
snapshot of the deployed source that SAGE's scripts/governance_snapshot.sh builds, stayed on
the previous build until dp ran the script by hand at 02:44Z. In between, the being looked for
the fix, could not find it in the only copy it may read, and spent its beats asking for scope
on paths that do not exist. The snapshot is derived from the deployed build, so the deploy is
the moment to refresh it. But it is SAGE's, not hestia's, so hestia-deploy runs whatever the
operator put in $HESTIA_HOME/post-deploy.d and knows nothing about what it is.

Pinned here, each under `set -euo pipefail` as the script runs:
  - no directory, an opt-out, or a governed session: nothing runs, and the status says why;
  - a step runs with the deployed build in HESTIA_DEPLOYED_BUILD, and a symlinked step runs
    (the CBP install is a symlink to the SAGE script);
  - a failing step, a hung step (where timeout(1) exists) and a step a member could have
    written (group/world writable) each return 0 from the function with a count that says so;
  - every cycle that ends DEPLOYED or CURRENT calls it, and its status is on that log line.

Run: python3 post_deploy_step_test.py     (no pytest; exit 1 on failure)
"""
from __future__ import annotations

import os
import re
import shutil
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
    m = re.search(rf"^{re.escape(fname)}\(\) *\{{\s*$", text, re.M)
    assert m, f"{fname}() not found in hestia-deploy.sh"
    depth = 0
    for j in range(m.start(), len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[m.start():j + 1]
    raise AssertionError(f"{fname}() is not brace-balanced")


def clean_env(**extra: str) -> dict:
    """The session running this test is itself governed; strip the markers so each case states its own."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDECODE", "HESTIA_ROLE", "HESTIA_DEPLOY_POST", "POST_DEPLOY_SECS")}
    env.update(extra)
    return env


def run(fn_src: str, home: Path, env: dict) -> tuple[int, str, str]:
    prog = (f"set -euo pipefail\nHESTIA_HOME={home}\nLOG={home}/deploy.log\n"
            "log() { printf '%s\\n' \"$*\" >>\"$LOG\"; }\n"
            f"{fn_src}\nrun_post_deploy v0.0.0-1-gabc1234\n"
            "printf 'STATUS=%s\\n' \"$post_deploy\"\n")
    r = subprocess.run(["bash", "-c", prog], capture_output=True, text=True, env=env, timeout=60)
    m = re.search(r"^STATUS=(.*)$", r.stdout, re.M)
    log = (home / "deploy.log").read_text() if (home / "deploy.log").exists() else ""
    return r.returncode, (m.group(1) if m else f"<no status; stderr: {r.stderr.strip()[:160]}>"), log


def step(d: Path, name: str, body: str, mode: int = 0o755) -> Path:
    p = d / name
    p.write_text("#!/bin/bash\n" + body + "\n")
    p.chmod(mode)
    return p


def main() -> int:
    text = SCRIPT.read_text()
    fn = extract_function(text, "run_post_deploy")
    tmp = Path(tempfile.mkdtemp(prefix="post-deploy-test-"))
    try:
        # 1. No directory: nothing to run, and that is not a failure.
        home = tmp / "h1"; home.mkdir()
        rc, st, _ = run(fn, home, clean_env())
        check("no dir rc", rc, 0); check("no dir status", st, "none")

        # 2. A step runs, sees the build, and a symlinked step runs too.
        home = tmp / "h2"; d = home / "post-deploy.d"; d.mkdir(parents=True)
        out = tmp / "seen"
        step(d, "10-record", f'echo "$HESTIA_DEPLOYED_BUILD" >> {out}')
        real = step(tmp, "real-step.sh", f'echo linked >> {out}')
        (d / "20-linked").symlink_to(real)
        step(d, "30-not-executable", f'echo WRONG >> {out}', mode=0o644)
        rc, st, _ = run(fn, home, clean_env())
        check("ok rc", rc, 0); check("ok status", st, "ok=2 failed=0")
        check("ok saw build, in name order", out.read_text().split(), ["v0.0.0-1-gabc1234", "linked"])

        # 3. A failing step returns 0 from the function, counted and logged.
        home = tmp / "h3"; d = home / "post-deploy.d"; d.mkdir(parents=True)
        step(d, "10-fails", "exit 7")
        step(d, "20-ok", "true")
        rc, st, log = run(fn, home, clean_env())
        check("fail rc", rc, 0); check("fail status", st, "ok=1 failed=1")
        check("fail logged with its code", "10-fails exited 7" in log, True)

        # 4. A step a member could have written is skipped, not run.
        home = tmp / "h4"; d = home / "post-deploy.d"; d.mkdir(parents=True)
        out4 = tmp / "seen4"
        step(d, "10-group-writable", f'echo RAN >> {out4}', mode=0o775)
        rc, st, log = run(fn, home, clean_env())
        check("writable rc", rc, 0); check("writable status", st, "ok=0 failed=1")
        check("writable not run", out4.exists(), False)
        check("writable logged", "skipped 10-group-writable" in log, True)

        # 5. Opt-out and governed session: nothing runs.
        home = tmp / "h5"; d = home / "post-deploy.d"; d.mkdir(parents=True)
        out5 = tmp / "seen5"
        step(d, "10-record", f'echo RAN >> {out5}')
        rc, st, _ = run(fn, home, clean_env(HESTIA_DEPLOY_POST="0"))
        check("opt-out status", st, "skipped(HESTIA_DEPLOY_POST=0)")
        rc, st, _ = run(fn, home, clean_env(CLAUDECODE="1"))
        check("governed status", st, "refused(governed session)")
        check("neither ran", out5.exists(), False)

        # 6. A hung step is bounded where timeout(1) exists.
        if shutil.which("timeout"):
            home = tmp / "h6"; d = home / "post-deploy.d"; d.mkdir(parents=True)
            step(d, "10-hangs", "sleep 30")
            rc, st, _ = run(fn, home, clean_env(POST_DEPLOY_SECS="1"))
            check("hung rc", rc, 0); check("hung status", st, "ok=0 failed=1")

        # 7. Every cycle that ends DEPLOYED or CURRENT calls it and reports it.
        calls = re.findall(r"^\s*(?:if .*then )?.*run_post_deploy \"\$(newv|target)\"", text, re.M)
        check("call sites (DEPLOYED, CURRENT, CURRENT manifest-repair)", len(calls), 3)
        check("DEPLOYED line reports it",
              bool(re.search(r'log "DEPLOYED .*post_deploy=\$post_deploy', text)), True)
        check("CURRENT line reports it", "post_deploy:+ post_deploy=$post_deploy" in text, True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if FAILS:
        print("FAIL\n  " + "\n  ".join(FAILS))
        return 1
    print("ok: run_post_deploy never stops a deploy, runs only the operator's steps, and reports on every cycle")
    return 0


if __name__ == "__main__":
    sys.exit(main())
