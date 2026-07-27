#!/usr/bin/env python3
"""Amendment 3's CI test: the one-session-per-member bound must be law, not luck.

The bound used to be an emergent property of bash — fire-*.sh ran the CLI in the
foreground, so nothing could start a second session. Nothing enforced it and
nothing tested it, so appending `&` anywhere on the path removed it silently.
This test fails if that is true again.

Six cases. 1-5 drive `with-member-lock.sh` directly (the law). Case 6 drives the
REAL `fire-claude.sh` and `fire-kimi.sh` with a stubbed CLI on PATH and a stubbed
HOME — no test seam in the fire scripts, so the test cannot pass by exercising a
code path only the test uses.

Case 6 is the one that matters for the amendment's literal clause: both fires are
launched with `&` from this harness, and the assertion is on whether the two stub
CLIs ever overlap. If someone re-backgrounds the CLI inside a fire script, or
routes around the lock, case 6 goes red.

Usage: ./fire_concurrency_test.py        (runtime ~15s, mostly deliberate sleeps)
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MESH = os.path.abspath(os.path.join(HERE, ".."))
LOCKER = os.path.join(MESH, "with-member-lock.sh")

EX_TEMPFAIL = 75
EX_UNAVAILABLE = 69

failures = []


def check(label, ok, detail=""):
    failures.append(label) if not ok else None
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))


def payload(events, secs):
    """A command that marks its own start and end in `events`."""
    return ["bash", "-c", f'echo S >> "{events}"; sleep {secs}; echo E >> "{events}"']


def overlapped(events):
    """True if any two payload runs were concurrent.

    Non-overlapping runs write S,E,S,E,... — two S in a row means a second
    session started while the first was live.
    """
    seq = "".join(open(events).read().split()) if os.path.exists(events) else ""
    return "SS" in seq, seq


def run(args, env, **kw):
    return subprocess.run(args, env=env, capture_output=True, text=True, **kw)


def base_env(tmp, wait="30"):
    env = dict(os.environ)
    env["HOME"] = tmp
    env["HESTIA_MESH_LOCK_DIR"] = os.path.join(tmp, "locks")
    env["HESTIA_FIRE_LOCK_WAIT"] = wait
    return env


# ---------------------------------------------------------------------------
# 1. Mutual exclusion: two fires of the same member serialize.
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    ev = os.path.join(tmp, "ev1")
    env = base_env(tmp)
    a = subprocess.Popen([LOCKER, "claude-code"] + payload(ev, 2), env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    b = subprocess.Popen([LOCKER, "claude-code"] + payload(ev, 0.2), env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ra, rb = a.wait(), b.wait()
    ov, seq = overlapped(ev)
    check("1. same member: two fires never overlap", not ov, f"event sequence {seq!r}")
    check("1b. same member: the waiter still runs (serialized, not dropped)",
          seq == "SESE" and ra == 0 and rb == 0, f"seq={seq!r} rc={ra},{rb}")

# ---------------------------------------------------------------------------
# 2. A refused fire exits non-zero and RETRYABLE — the watcher keys off rc to
#    decide whether to keep the consume-once primer.
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    ev = os.path.join(tmp, "ev2")
    env = base_env(tmp, wait="1")
    a = subprocess.Popen([LOCKER, "claude-code"] + payload(ev, 3), env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    r = run([LOCKER, "claude-code"] + payload(ev, 0.1), env)
    a.wait()
    check("2. contended fire past the wait refuses with EX_TEMPFAIL(75)",
          r.returncode == EX_TEMPFAIL, f"rc={r.returncode} stderr={r.stderr.strip()!r}")
    ov, seq = overlapped(ev)
    check("2b. the refused fire did not run its payload", seq == "SE", f"seq={seq!r}")
    check("2c. the refusal names the holder (forensics, not silence)",
          "holder:" in r.stderr and "pid=" in r.stderr, f"stderr={r.stderr.strip()!r}")

# ---------------------------------------------------------------------------
# 3. The lock is PER MEMBER. A global lock would be a cross-member denial
#    channel — the exact defect commit 113a46a fixed for the notice queue.
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    ev = os.path.join(tmp, "ev3")
    env = base_env(tmp)
    a = subprocess.Popen([LOCKER, "claude-code"] + payload(ev, 1.5), env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.4)
    b = subprocess.Popen([LOCKER, "kimi-code"] + payload(ev, 1.5), env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    a.wait(); b.wait()
    ov, seq = overlapped(ev)
    check("3. different members DO run concurrently (no cross-member denial)",
          ov, f"seq={seq!r} — expected an overlap")

# ---------------------------------------------------------------------------
# 4. The amendment's literal clause: backgrounding does not remove the bound.
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    ev = os.path.join(tmp, "ev4")
    env = base_env(tmp)
    cmd = " ".join([LOCKER, "claude-code", "bash", "-c",
                    f"'echo S >> {ev}; sleep 1.5; echo E >> {ev}'"])
    r = run(["bash", "-c", f"{cmd} & {cmd} & wait"], env)
    ov, seq = overlapped(ev)
    check("4. `&`-backgrounded fires still serialize", not ov, f"seq={seq!r}")

# ---------------------------------------------------------------------------
# 5. Fail CLOSED. No flock(1) must mean "do not fire", not "fire unbounded" —
#    degrading to the pre-amendment state would be invisible.
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    ev = os.path.join(tmp, "ev5")
    bindir = os.path.join(tmp, "bin"); os.makedirs(bindir)
    for tool in ("mkdir", "chmod", "bash", "sleep", "echo", "sed", "date", "rm"):
        p = shutil.which(tool)
        if p:
            os.symlink(p, os.path.join(bindir, tool))
    env = base_env(tmp); env["PATH"] = bindir
    r = run([LOCKER, "claude-code"] + payload(ev, 0.1), env)
    check("5. missing flock(1) refuses with EX_UNAVAILABLE(69)",
          r.returncode == EX_UNAVAILABLE, f"rc={r.returncode} stderr={r.stderr.strip()!r}")
    check("5b. missing flock(1) did NOT run the payload",
          not os.path.exists(ev), "payload ran unbounded — fail-open")

# ---------------------------------------------------------------------------
# 6. End to end on the REAL fire scripts, stubbed CLI, no seam.
# ---------------------------------------------------------------------------
PRIMER = """{"notices": [{"id": 1, "kind": "reply", "from_plugin": "%s",
 "to_plugin": "%s", "pointer_uri": "shared-context/x.md", "queued_at": "2026-07-25T00:00:00Z"}],
 "unanswered": {}}"""

for script, stub, sender, me in (("fire-claude.sh", "claude", "kimi-code", "claude-code"),
                                 ("fire-kimi.sh", "kimi", "claude-code", "kimi-code")):
    with tempfile.TemporaryDirectory() as tmp:
        ev = os.path.join(tmp, "ev6")
        bindir = os.path.join(tmp, "bin"); os.makedirs(bindir)
        with open(os.path.join(bindir, stub), "w") as f:
            f.write(f'#!/usr/bin/env bash\necho S >> "{ev}"\nsleep 2\necho E >> "{ev}"\n')
        os.chmod(os.path.join(bindir, stub), 0o755)
        src = os.path.join(tmp, "notice-test.json")
        with open(src, "w") as f:
            f.write(PRIMER % (sender, me))
        env = base_env(tmp)
        env["PATH"] = bindir + os.pathsep + env["PATH"]
        fire = os.path.join(MESH, script)
        a = subprocess.Popen([fire, src], env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True)
        time.sleep(0.8)
        b = subprocess.Popen([fire, src], env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True)
        oa, _ = a.communicate(); ob, _ = b.communicate()
        ov, seq = overlapped(ev)
        check(f"6. {script}: two concurrent fires never overlap the CLI",
              not ov, f"seq={seq!r}\n        a={oa.strip()!r}\n        b={ob.strip()!r}")
        check(f"6b. {script}: the stub CLI actually ran (the test is not vacuous)",
              "S" in seq, f"seq={seq!r} — fire never reached the CLI, so case 6 proved nothing")

# ---------------------------------------------------------------------------
# 7. rc propagation. Added because mutation-testing case 6 found this hole: with
#    `&` appended to the fire line, the lock STILL holds (that is the point of
#    making it law) — but the fire script exits 0 whatever the CLI did, and
#    hestia-watch-member.sh reads rc to decide whether to keep the consume-once
#    primer. That is the 2026-07-25 defect verbatim: 3 dead fires reported
#    success and 2 notices were destroyed. Backgrounding no longer removes the
#    concurrency bound; it would still silently re-open THIS one.
# ---------------------------------------------------------------------------
for script, stub in (("fire-claude.sh", "claude"), ("fire-kimi.sh", "kimi")):
    with tempfile.TemporaryDirectory() as tmp:
        bindir = os.path.join(tmp, "bin"); os.makedirs(bindir)
        with open(os.path.join(bindir, stub), "w") as f:
            f.write("#!/usr/bin/env bash\nexit 3\n")
        os.chmod(os.path.join(bindir, stub), 0o755)
        src = os.path.join(tmp, "notice-test.json")
        sender = "kimi-code" if stub == "claude" else "claude-code"
        with open(src, "w") as f:
            f.write(PRIMER % (sender, "x"))
        env = base_env(tmp)
        env["PATH"] = bindir + os.pathsep + env["PATH"]
        r = run([os.path.join(MESH, script), src], env)
        check(f"7. {script}: a failed CLI makes the fire exit non-zero (primer retained)",
              r.returncode == 3, f"rc={r.returncode} — the watcher would DELETE the "
                                 f"consume-once primer on this rc")

print(f"\nfailures={len(failures)}")
for f in failures:
    print(f"  - {f}")
sys.exit(1 if failures else 0)
