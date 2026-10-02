#!/usr/bin/env python3
"""mesh-timeout.sh must bound commands without GNU timeout(1).

Stock macOS has no `timeout`. fire-claude/kimi/codex used to call bare
`timeout` / `timeout -k`, so cases 6b/7 of fire_concurrency_test.py never
reached the stub CLI on this host (#1105 follow-up).

This test hides timeout/gtimeout from PATH and drives the helper directly:
success rc preserved, overdue commands exit 124, a TERM-ignoring command is
not SIGKILLed when -k is absent, -k that actually sends SIGKILL exits 137,
and a descendant that ignores SIGTERM is SIGKILLed at the grace deadline
even if its leader has already exited.
"""
import os
import shutil
import signal
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

    t0 = time.monotonic()
    r = run([HELPER, "-k", "2", "0.4", "sleep", "30"], env)
    elapsed = time.monotonic() - t0
    check("3c. -k exits 124 when TERM reaps the command before kill-after",
          r.returncode == 124, f"rc={r.returncode}")
    check("3d. that path returns before kill-after", elapsed < 1.5, f"elapsed={elapsed:.2f}s")

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
    check("4. -k kills a SIGTERM-ignoring child (rc 137)", r.returncode == 137, f"rc={r.returncode}")
    check("4b. -k path finishes near duration+kill-after", 1.5 < elapsed < 6, f"elapsed={elapsed:.2f}s")

    # Without -k, GNU timeout sends TERM and waits. It must not SIGKILL a
    # command that ignores TERM, so the helper is still running afterwards
    # and the command is still alive.
    nok_pid = os.path.join(tmp, "nok-pid")
    nok = os.path.join(tmp, "ignore-term-nok")
    with open(nok, "w") as f:
        f.write("#!/usr/bin/env bash\ntrap '' TERM\nprintf '%s\\n' \"$$\" > \"$1\"\nwhile true; do sleep 0.2; done\n")
    os.chmod(nok, 0o755)
    held = subprocess.Popen([HELPER, "1", nok, nok_pid], env=env)
    try:
        time.sleep(1.6)
        alive_helper = held.poll() is None
        child_alive = False
        if os.path.isfile(nok_pid):
            try:
                os.kill(int(open(nok_pid).read().strip()), 0)
                child_alive = True
            except (ProcessLookupError, ValueError):
                child_alive = False
        check("4c. no -k does not return after TERM is ignored", alive_helper)
        check("4d. no -k does not SIGKILL a TERM-ignoring command", child_alive)
    finally:
        if held.poll() is None:
            try:
                os.kill(held.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                held.wait(timeout=2)
            except subprocess.TimeoutExpired:
                held.kill()
                held.wait(timeout=2)
        if os.path.isfile(nok_pid):
            try:
                os.kill(int(open(nok_pid).read().strip()), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass

    # Leader dies on SIGTERM. Descendant ignores SIGTERM (and SIGHUP, so a
    # session-leader exit cannot reap it for us) and writes a marker at 1.5s,
    # after -k 0.3 0.5's kill deadline. The wrapper must SIGKILL the group
    # at that deadline instead of returning when the leader exits.
    marker = os.path.join(tmp, "descendant-marker")
    pidfile = os.path.join(tmp, "descendant-pid")
    started = os.path.join(tmp, "descendant-started")
    parent = os.path.join(tmp, "descendant-parent.py")
    with open(parent, "w") as f:
        f.write(
            "#!/usr/bin/env python3\n"
            "import os, signal, sys, time\n"
            "marker, pidfile, started = sys.argv[1], sys.argv[2], sys.argv[3]\n"
            "pid = os.fork()\n"
            "if pid == 0:\n"
            "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "    signal.signal(signal.SIGHUP, signal.SIG_IGN)\n"
            "    open(pidfile, 'w').write(str(os.getpid()))\n"
            "    open(started, 'w').write('1\\n')\n"
            "    time.sleep(1.5)\n"
            "    open(marker, 'w').write('alive\\n')\n"
            "    os._exit(0)\n"
            "os.waitpid(pid, 0)\n"
        )
    os.chmod(parent, 0o755)
    t0 = time.monotonic()
    r = run([HELPER, "-k", "0.3", "0.5", "python3", parent, marker, pidfile, started], env)
    elapsed = time.monotonic() - t0
    check("6. descendant still alive at the deadline is killed (rc 137)",
          r.returncode == 137, f"rc={r.returncode} err={r.stderr!r}")
    check("6b. wrapper stays through the grace period after the leader exits",
          0.7 < elapsed < 1.4, f"elapsed={elapsed:.2f}s")
    remain = 1.8 - (time.monotonic() - t0)
    if remain > 0:
        time.sleep(remain)
    check("6c. descendant did not write the marker after the deadline",
          not os.path.exists(marker))
    check("6e. descendant actually started", os.path.isfile(started))
    if not os.path.isfile(pidfile):
        check("6d. descendant pid was recorded", False, "no pidfile")
    else:
        pid = int(open(pidfile).read().strip())
        alive = False
        poll_until = time.monotonic() + 1.0
        while time.monotonic() < poll_until:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                alive = False
                break
            except PermissionError:
                alive = True
                time.sleep(0.05)
                continue
            st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                                capture_output=True, text=True)
            stat = st.stdout.strip()
            if not stat or stat.startswith("Z"):
                alive = False
                break
            alive = True
            time.sleep(0.05)
        if alive:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        check("6d. descendant is dead after the deadline", not alive, f"pid={pid}")

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
