#!/usr/bin/env python3
"""mesh-timeout.sh must bound commands without GNU timeout(1).

Stock macOS has no `timeout`. fire-claude/kimi/codex used to call bare
`timeout` / `timeout -k`, so cases 6b/7 of fire_concurrency_test.py never
reached the stub CLI on this host (#1105 follow-up).

This test hides timeout/gtimeout from PATH and drives the helper directly:
success rc preserved, overdue commands exit 124, and -k still SIGKILLs a
SIGTERM-ignoring child.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MESH = os.path.abspath(os.path.join(HERE, ".."))
HELPER = os.path.join(MESH, "mesh-timeout.sh")

failures = []


def check(label, ok, detail=""):
    if not ok:
        failures.append(label)
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))


def path_without_timeouts(tmp):
    """PATH with common tools but no timeout/gtimeout."""
    bindir = os.path.join(tmp, "bin")
    os.makedirs(bindir)
    for tool in ("bash", "sleep", "true", "false", "echo", "python3", "chmod", "cat"):
        p = shutil.which(tool)
        if p and not os.path.exists(os.path.join(bindir, tool)):
            os.symlink(p, os.path.join(bindir, tool))
    assert not os.path.exists(os.path.join(bindir, "timeout"))
    assert not os.path.exists(os.path.join(bindir, "gtimeout"))
    return bindir


def run(args, env, **kw):
    return subprocess.run(args, env=env, capture_output=True, text=True, **kw)


assert os.path.isfile(HELPER) and os.access(HELPER, os.X_OK), HELPER

with tempfile.TemporaryDirectory() as tmp:
    env = dict(os.environ)
    env["PATH"] = path_without_timeouts(tmp)
    # Prove the harness actually removed GNU timeout.
    missing = run(["bash", "-c", "command -v timeout || command -v gtimeout || true"], env)
    check("0. harness PATH has neither timeout nor gtimeout",
          missing.stdout.strip() == "", f"stdout={missing.stdout!r}")

    r = run([HELPER, "2", "true"], env)
    check("1. short success preserves exit 0", r.returncode == 0, f"rc={r.returncode} err={r.stderr!r}")

    r = run([HELPER, "2", "bash", "-c", "exit 7"], env)
    check("2. short failure preserves exit 7", r.returncode == 7, f"rc={r.returncode}")

    t0 = time.monotonic()
    r = run([HELPER, "1", "sleep", "30"], env)
    elapsed = time.monotonic() - t0
    check("3. overdue command exits 124", r.returncode == 124, f"rc={r.returncode}")
    check("3b. overdue command returns well before 30s", elapsed < 5, f"elapsed={elapsed:.2f}s")

    # Child ignores SIGTERM; -k must escalate to SIGKILL.
    ignore_term = (
        "#!/usr/bin/env bash\n"
        "trap '' TERM\n"
        "while true; do sleep 0.2; done\n"
    )
    stub = os.path.join(tmp, "ignore-term")
    with open(stub, "w") as f:
        f.write(ignore_term)
    os.chmod(stub, 0o755)
    t0 = time.monotonic()
    r = run([HELPER, "-k", "1", "1", stub], env)
    elapsed = time.monotonic() - t0
    check("4. -k kills a SIGTERM-ignoring child (rc 124)", r.returncode == 124, f"rc={r.returncode}")
    check("4b. -k path finishes near duration+kill-after", 1.5 < elapsed < 6, f"elapsed={elapsed:.2f}s")

# Fire scripts must not call bare timeout anymore.
for name in ("fire-claude.sh", "fire-kimi.sh", "fire-codex.sh"):
    text = open(os.path.join(MESH, name)).read()
    bare = [ln for ln in text.splitlines()
            if "timeout" in ln and "mesh-timeout" not in ln and not ln.lstrip().startswith("#")]
    # Allow comment-adjacent prose lines that mention the word without invoking it.
    invokes = [ln for ln in bare if "$(timeout " in ln or ln.lstrip().startswith("timeout ")
               or " timeout -k" in ln or ln.lstrip().startswith("timeout -k")]
    check(f"5. {name} has no bare timeout invocation", not invokes, f"lines={invokes!r}")
    check(f"5b. {name} routes through mesh-timeout.sh",
          '"$HERE_DIR/mesh-timeout.sh"' in text)

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nall passed")
