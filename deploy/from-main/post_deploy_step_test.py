#!/usr/bin/env python3
"""`run_post_deploy` runs only the operator's steps after a deploy, and never stops the deploy.

WHY THIS EXISTS (cbp-claude, 2026-10-22).

hestia #1362 deployed on CBP at 01:59Z. The being's readable copy of its law, a read-only
snapshot of the deployed source that SAGE's scripts/governance_snapshot.sh builds, stayed on
the previous build until dp ran the script by hand at 02:44Z. In between, the being looked for
the fix, could not find it in the only copy it may read, and spent its beats asking for scope
on paths that do not exist. The snapshot is derived from the deployed build, so the deploy is
the moment to refresh it. But it is SAGE's, not hestia's, so hestia-deploy runs whatever the
operator put in $HESTIA_HOME/post-deploy.d and knows nothing about what it is.

That runs code with the deploy's privileges, so (Nova's hold on #1368) the trust boundary is
checked on the RESOLVED path: what runs must be a file only the operator could have put there.

Pinned here, each under `set -euo pipefail` as the script runs:
  - no directory, an opt-out, or a governed session: nothing runs, and the status says why;
  - a step runs with the deployed build in HESTIA_DEPLOYED_BUILD; a symlink to a file inside
    post-deploy.d runs; a symlink OUT of it is skipped and not run (the escape);
  - a step whose resolved target is group-writable, through a link or directly, is skipped;
  - a group-writable post-deploy.d or $HESTIA_HOME, or a post-deploy.d that is a symlink,
    refuses everything;
  - a failing step, and a hung step that leaves a grandchild holding its output, each return
    from the function within the bound, and the CALLER'S NEXT LINE STILL RUNS (sentinel);
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
import time
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
           if k not in ("CLAUDECODE", "HESTIA_ROLE", "HESTIA_DEPLOY_POST", "POST_DEPLOY_SECS",
                        "POST_DEPLOY_KILL_SECS")}
    env.update(extra)
    return env


def run(fn_src: str, home: Path, env: dict) -> tuple[int, str, str, float, bool]:
    """Run the function as the script does; a sentinel line after it proves the caller continues."""
    prog = (f"set -euo pipefail\nHESTIA_HOME={home}\nLOG={home}/deploy.log\n"
            "log() { printf '%s\\n' \"$*\" >>\"$LOG\"; }\n"
            f"{fn_src}\nrun_post_deploy v0.0.0-1-gabc1234\n"
            "printf 'STATUS=%s\\n' \"$post_deploy\"\nprintf 'SENTINEL\\n'\n")
    t0 = time.monotonic()
    r = subprocess.run(["bash", "-c", prog], capture_output=True, text=True, env=env, timeout=60)
    took = time.monotonic() - t0
    m = re.search(r"^STATUS=(.*)$", r.stdout, re.M)
    log = (home / "deploy.log").read_text() if (home / "deploy.log").exists() else ""
    return (r.returncode, (m.group(1) if m else f"<no status; stderr: {r.stderr.strip()[:160]}>"),
            log, took, "SENTINEL" in r.stdout)


def step(d: Path, name: str, body: str, mode: int = 0o755) -> Path:
    p = d / name
    p.write_text("#!/bin/bash\n" + body + "\n")
    p.chmod(mode)
    return p


def home_with_dir(tmp: Path, label: str) -> tuple[Path, Path]:
    home = tmp / label
    d = home / "post-deploy.d"
    d.mkdir(parents=True)
    home.chmod(0o700)
    d.chmod(0o700)
    return home, d


def main() -> int:
    text = SCRIPT.read_text()
    fn = "\n".join(extract_function(text, f) for f in
                   ("_post_deploy_real", "_post_deploy_operator_only", "run_post_deploy"))
    tmp = Path(tempfile.mkdtemp(prefix="post-deploy-test-"))
    try:
        # 1. No directory: nothing to run, and that is not a failure.
        home = tmp / "h1"; home.mkdir(); home.chmod(0o700)
        rc, st, _, _, _ = run(fn, home, clean_env())
        check("no dir rc", rc, 0); check("no dir status", st, "none")

        # 2. A step runs and sees the build; a symlink to a file INSIDE the dir runs too; a
        #    non-executable file is not a step.
        home, d = home_with_dir(tmp, "h2")
        out = tmp / "seen"
        step(d, "10-record", f'echo "$HESTIA_DEPLOYED_BUILD" >> {out}')
        step(d, ".inner-target", f'echo linked >> {out}')
        (d / "20-linked-inside").symlink_to(d / ".inner-target")
        step(d, "30-not-executable", f'echo WRONG >> {out}', mode=0o644)
        rc, st, _, _, ok = run(fn, home, clean_env())
        # .inner-target is itself a step (a dotfile matches no `*` glob, so it runs only via the link)
        check("ok rc", rc, 0); check("ok status", st, "ok=2 failed=0"); check("ok sentinel", ok, True)
        check("ok saw build, in name order", out.read_text().split(), ["v0.0.0-1-gabc1234", "linked"])

        # 3. A symlink that ESCAPES the directory is skipped and never run, even when its target
        #    is ours and not writable by anyone else: the operator installs a copy.
        home, d = home_with_dir(tmp, "h3")
        out3 = tmp / "seen3"
        outside = tmp / "outside"; outside.mkdir()
        (d / "10-escapes").symlink_to(step(outside, "real.sh", f'echo RAN >> {out3}'))
        rc, st, log, _, ok = run(fn, home, clean_env())
        check("escape rc", rc, 0); check("escape status", st, "ok=0 failed=1")
        check("escape not run", out3.exists(), False)
        check("escape logged", "skipped 10-escapes (escapes post-deploy.d" in log, True)
        check("escape sentinel", ok, True)

        # 4. Group-writable target: directly, and through a link inside the dir. Neither runs.
        home, d = home_with_dir(tmp, "h4")
        out4 = tmp / "seen4"
        step(d, "10-group-writable", f'echo RAN >> {out4}', mode=0o775)
        step(d, ".gw-target", f'echo RAN >> {out4}', mode=0o775)
        (d / "20-link-to-gw").symlink_to(d / ".gw-target")
        rc, st, log, _, _ = run(fn, home, clean_env())
        check("writable rc", rc, 0); check("writable status", st, "ok=0 failed=2")
        check("writable not run", out4.exists(), False)
        check("writable logged", "skipped 10-group-writable" in log and "skipped 20-link-to-gw" in log, True)

        # 5. The directory, or the home above it, writable by others, or the directory a
        #    symlink: nothing runs at all.
        out5 = tmp / "seen5"
        home, d = home_with_dir(tmp, "h5a")
        step(d, "10-record", f'echo RAN >> {out5}')
        d.chmod(0o770)
        rc, st, _, _, ok = run(fn, home, clean_env())
        check("dir writable status", st, "refused(post-deploy.d not operator-only)")
        check("dir writable sentinel", ok, True)
        home, d = home_with_dir(tmp, "h5b")
        step(d, "10-record", f'echo RAN >> {out5}')
        home.chmod(0o770)
        rc, st, _, _, _ = run(fn, home, clean_env())
        check("home writable status", st, "refused(post-deploy.d not operator-only)")
        home = tmp / "h5c"; home.mkdir(); home.chmod(0o700)
        elsewhere = tmp / "elsewhere"; elsewhere.mkdir(); elsewhere.chmod(0o700)
        step(elsewhere, "10-record", f'echo RAN >> {out5}')
        (home / "post-deploy.d").symlink_to(elsewhere)
        rc, st, _, _, _ = run(fn, home, clean_env())
        check("symlinked dir status", st, "refused(post-deploy.d not operator-only)")
        check("none of the refused ran", out5.exists(), False)

        # 6. A failing step returns 0 from the function, counted and logged, and the next step runs.
        home, d = home_with_dir(tmp, "h6")
        step(d, "10-fails", "exit 7")
        step(d, "20-ok", "true")
        rc, st, log, _, ok = run(fn, home, clean_env())
        check("fail rc", rc, 0); check("fail status", st, "ok=1 failed=1")
        check("fail logged with its code", "10-fails exited 7" in log, True)
        check("fail sentinel", ok, True)

        # 7. Opt-out and governed session: nothing runs.
        home, d = home_with_dir(tmp, "h7")
        out7 = tmp / "seen7"
        step(d, "10-record", f'echo RAN >> {out7}')
        rc, st, _, _, _ = run(fn, home, clean_env(HESTIA_DEPLOY_POST="0"))
        check("opt-out status", st, "skipped(HESTIA_DEPLOY_POST=0)")
        rc, st, _, _, _ = run(fn, home, clean_env(CLAUDECODE="1"))
        check("governed status", st, "refused(governed session)")
        check("neither ran", out7.exists(), False)

        # 8. A hung step is bounded where timeout(1) exists -- including one that ignores TERM
        #    and leaves a background grandchild holding its stdout/stderr. The function returns
        #    within the bound plus the kill grace, the caller's next line runs, and the step
        #    after it still runs.
        if shutil.which("timeout"):
            home, d = home_with_dir(tmp, "h8")
            out8 = tmp / "seen8"
            step(d, "10-hangs", "trap '' TERM\n( sleep 30; echo LATE ) &\nsleep 30")
            step(d, "20-after", f'echo AFTER >> {out8}')
            rc, st, log, took, ok = run(fn, home, clean_env(POST_DEPLOY_SECS="1", POST_DEPLOY_KILL_SECS="1"))
            check("hung rc", rc, 0); check("hung status", st, "ok=1 failed=1")
            check("hung bounded (s < 10)", took < 10, True)
            check("hung logged as a timeout", "10-hangs timed out after 1s" in log, True)
            check("hung sentinel", ok, True)
            check("step after the hung one ran", out8.exists(), True)

        # 9. Every cycle that ends DEPLOYED or CURRENT calls it and reports it.
        calls = re.findall(r"^\s*(?:if .*then )?.*run_post_deploy \"\$(newv|target)\"", text, re.M)
        check("call sites (DEPLOYED, CURRENT, CURRENT manifest-repair)", len(calls), 3)
        check("DEPLOYED line reports it",
              bool(re.search(r'log "DEPLOYED .*post_deploy=\$post_deploy', text)), True)
        check("CURRENT line reports it", "post_deploy:+ post_deploy=$post_deploy" in text, True)
    finally:
        for p in tmp.rglob("*"):
            if p.is_dir() and not p.is_symlink():
                p.chmod(0o700)
        shutil.rmtree(tmp, ignore_errors=True)

    if FAILS:
        print("FAIL\n  " + "\n  ".join(FAILS))
        return 1
    print("ok: run_post_deploy runs only the operator's steps, never stops a deploy, and reports on every cycle")
    return 0


if __name__ == "__main__":
    sys.exit(main())
