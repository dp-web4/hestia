#!/usr/bin/env python3
"""The startup baseline is derived from the fd bash is reading, not believed from a handover.

WHAT THIS CLOSES. #636 bound the deployed bytes to a verified object and handed the
successor its baseline on the exec line (`HESTIA_WATCH_SOURCE` / `HESTIA_WATCH_STARTUP_SHA256`,
`unset` once consumed). Both reviewing seats signed that off and both named the same
residual, left open on purpose: the successor's baseline moved from a re-read to a TRUST.
An operator who exports those two variables can tell a fresh watcher what it is running,
and `unset` bounds the lie to one process without removing the affordance.

The shape proposed for closing it was a sidecar the predecessor writes into `$STATE` under
the flock it already holds. That does not close it -- it moves the lie from an environment
variable to a FILE, which outlives the process the `unset` was bounding, and adds a
writable surface where there was none. Same trust, larger blast radius.

WHAT ACTUALLY CLOSES IT is that bash will say what it is reading if you ask. Bash holds
the script open on a descriptor for the life of the process and reads the not-yet-parsed
tail from it. `/proc/<pid>/fd/<n>` is that same open file description -- opening it does
not re-resolve the pathname -- so hashing it names the bytes this interpreter is actually
executing, with nothing to believe and nothing new to write.

MEASURED ON THIS HOST, and these are the two facts the design rests on:

  * Replace the script by RENAME underneath a running process: the fd still hashes the
    ORIGINAL bytes and readlink appends "(deleted)", while hashing "$0" returns the
    impostor that never ran. Rename-replace is the shape `maybe_self_deploy` uses.
  * The descriptor number is NOT 255. Bash takes the highest FREE fd: 255 normally, 254
    when the parent already holds 255, 249 with 250-255 taken. Hardcoding 255 does not
    fail loudly -- it hashes whatever unrelated fd was inherited at that number. Arm 1d
    measures that directly rather than inferring it from 1c's silence.

THE BLIND SPOT IS PINNED, NOT PAPERED OVER (arm 4a). A same-LENGTH in-place rewrite of our
own inode is followed by this fd, because it is the same inode. No spelling sees it; a
length-changing in-place rewrite corrupts the running parse instead. 4a asserts the miss,
so "the baseline is self-derived" can never be read as "the baseline is unspoofable".

A SECOND, SMALLER THING. `startup_sha256=` is a CONTENT hash. It has already been misread
as a commit sha in a published table -- #636's own vintage column prints `a8dccda` and
`cfb7bb9` (commits) beside `a7dde01` (a content-hash prefix). Recovering a commit from the
line needs a reverse lookup that only succeeds while some commit still holds those exact
bytes. Every line that prints the baseline now prints `startup_origin=` beside it, saying
which question the number answers and how much the answer is worth.

THE RESIDUAL IS BIGGER THAN EITHER SEAT CREDITED, and arm 3e is how that was found. Both
reviews called the handover trust a disclosure problem: not blocking. But a false baseline
is compared against the real file on every pass, so a lie MANUFACTURES DRIFT -- and #636
wired drift to a recovery. Measured against `bc24ad5`: exporting one variable makes the
watcher emit a spurious `ARTIFACT DRIFT` and then a real `ARTIFACT DEPLOY`, i.e. exec. The
four conjuncts still hold, so it cannot deploy arbitrary bytes; it can only force a restart
into merged ones -- which kills that seat's in-flight wake. That is a denial-of-wake
affordance available to anyone who can set an environment variable, and it did not exist
before the recovery landed. 2c is its control: with no handover, nothing deploys.

WHAT EACH ARM IS WORTH. Against `bc24ad5`, 1a-1d, 2a, 3a, 3b and 3e go RED: it has no
self-derivation, no origin token, it adopts a lying handover verbatim, and it execs on the
strength of it. 2b, 2c, 3c, 3d, 4a and 5a stay green there -- 2b/2c/3c are not-vacuous
arms for other checks, 4a is a property of bash rather than of either version, and 5a is
hygiene. The load is carried by 1d, 3a, 3b and 3e.

  WATCHER_UNDER_TEST=<path> ./watch_baseline_is_self_derived_test.py   (runtime ~35s)
"""
import hashlib
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# The #636 battery already owns a real watcher-in-a-scratch-repo harness (stub daemon,
# origin/main carrying the watcher byte for byte, startup line pumped off stdout). Reuse
# it: a second copy would drift from the first and quietly test a different watcher.
import artifact_drift_deploys_merged_bytes_test as H  # noqa: E402

WATCHER = H.WATCHER_SRC
failures = []


def check(label, ok, detail=""):
    if not ok:
        failures.append(label)
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))


def extract_function(src_text, name):
    """Lift one shell function out of the watcher under test, so the arms below exercise
    the SHIPPED discovery code and not a restatement of it that can silently agree."""
    m = re.search(rf"^{re.escape(name)}\(\) \{{\n(.*?)^\}}\n", src_text, re.S | re.M)
    return None if m is None else m.group(0)


def run_bash(script, pre=""):
    env = dict(os.environ)
    env.pop("HESTIA_WATCH_STARTUP_SHA256", None)
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as fh:
        fh.write(script)
        path = fh.name
    os.chmod(path, 0o755)
    cmd = ["bash", "-c", f"{pre}exec bash {path}"] if pre else ["bash", path]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)
    return r, path


def main():
    raw = open(WATCHER, "rb").read()
    src_text = raw.decode("utf-8", "replace")
    watcher_sha = hashlib.sha256(raw).hexdigest()

    # ---- 1. the descriptor is DISCOVERED, and 255 is the wrong constant --------------
    fn = extract_function(src_text, "watch_own_fd_path")
    check("1a. the watcher derives its own descriptor (watch_own_fd_path is present)",
          fn is not None, "no watch_own_fd_path in " + WATCHER)

    if fn is None:
        # Every arm below depends on it. Fail them explicitly rather than skipping, so a
        # sabotage control reports a set of arms and not merely a shorter run.
        for lbl in ("1b. discovery finds the running script's own descriptor",
                    "1c. discovery follows bash when 255 is already taken",
                    "1d. NOT VACUOUS: a hardcoded 255 reads a DIFFERENT file there"):
            check(lbl, False, "watch_own_fd_path absent")
    else:
        probe = fn + '\nwatch_own_fd_path "$0" || echo NONE\n'
        r, _ = run_bash(probe)
        found = r.stdout.strip()
        check("1b. discovery finds the running script's own descriptor",
              found.startswith("/proc/") and found.endswith("/255"),
              f"stdout={found!r} stderr={r.stderr[-400:]!r}")

        # Parent holds 255, so bash must take 254 for the script.
        r2, _ = run_bash(probe, pre="exec 255</dev/null; ")
        found2 = r2.stdout.strip()
        check("1c. discovery follows bash when 255 is already taken",
              found2.startswith("/proc/") and found2.endswith("/254"),
              f"stdout={found2!r} stderr={r2.stderr[-400:]!r}")

        # And the naive spelling is not merely unnecessary -- it is WRONG: fd 255 in that
        # same process is the parent's /dev/null, so a hardcoded read hashes THAT.
        r3, _ = run_bash('readlink /proc/$$/fd/255 || echo NONE\n', pre="exec 255</dev/null; ")
        naive = r3.stdout.strip()
        check("1d. NOT VACUOUS: a hardcoded 255 reads a DIFFERENT file there",
              naive == "/dev/null",
              f"expected /dev/null at fd 255, got {naive!r}")

    # ---- 2/3. behavioural: what the running watcher reports as its baseline ----------
    srv, ep = H.start_stub()
    H.EP = ep
    try:
        with tempfile.TemporaryDirectory() as tmp:
            repo = H.build_repo(tmp, "self")
            repo_watcher_sha = hashlib.sha256(
                open(os.path.join(repo, H.REL), "rb").read()).hexdigest()

            lines, _alive = H.run_watcher(tmp, repo, "self", None, settle=2)
            out = "\n".join(lines)
            check("2a. a normally-started watcher says its baseline came from its own fd",
                  any("startup_origin=own-fd" in l for l in lines), out[-1500:])
            check("2b. NOT VACUOUS: that baseline is the real hash of the file it runs",
                  any(f"startup_sha256={repo_watcher_sha}" in l for l in lines),
                  f"expected {repo_watcher_sha}\n{out[-1500:]}")
            check("2c. CONTROL for 3e: with no handover at all, nothing drifts and "
                  "nothing deploys",
                  not any("ARTIFACT DEPLOY" in l for l in lines), out[-1500:])

            # The residual, exercised: an operator lies about what this watcher is running.
            lie = hashlib.sha256(b"a well-formed sha that is not ours").hexdigest()
            check("3c. NOT VACUOUS: the lie is well-formed 64-hex and is not the truth",
                  re.fullmatch(r"[0-9a-f]{64}", lie) is not None and lie != repo_watcher_sha)

            os.environ["HESTIA_WATCH_STARTUP_SHA256"] = lie
            try:
                lines2, alive2 = H.run_watcher(tmp, repo, "lied", None, settle=2)
            finally:
                os.environ.pop("HESTIA_WATCH_STARTUP_SHA256", None)
            out2 = "\n".join(lines2)
            check("3a. a lying handover is NOT adopted; the self-derived hash wins",
                  any(f"startup_sha256={repo_watcher_sha}" in l for l in lines2)
                  and not any(f"startup_sha256={lie}" in l for l in lines2),
                  f"lie={lie}\ntruth={repo_watcher_sha}\n{out2[-1500:]}")
            check("3b. and the disagreement is REPORTED, not silently discarded",
                  any("startup_origin=own-fd-handover-mismatch" in l for l in lines2),
                  out2[-1500:])
            check("3d. and the watcher survives the mismatch path under `set -e`",
                  alive2, out2[-1500:])
            # THE ARM THAT RESIZES THE RESIDUAL. Both reviewing seats called the handover
            # trust cosmetic -- worth an origin token, not blocking. It is not cosmetic. A
            # false baseline is compared against the real file every pass, so the lie
            # MANUFACTURES DRIFT, and drift is now wired to a recovery: measured against
            # bc24ad5, one exported variable makes the watcher exec. The four conjuncts
            # still hold, so it cannot deploy arbitrary bytes -- it can only force a
            # restart into merged ones, which kills that seat's in-flight wake. That is a
            # denial-of-wake affordance handed to anyone who can set an env var, and
            # self-derivation removes it because a lie can no longer contradict the disk.
            check("3e. and the lie CANNOT manufacture drift, so it cannot force an exec",
                  not any("ARTIFACT DEPLOY" in l for l in lines2),
                  "a lying handover triggered a self-deploy:\n" + out2[-2000:])
    finally:
        srv.shutdown()

    # ---- 4. the blind spot, asserted so it cannot be silently claimed closed ---------
    inplace = r'''
self="$0"
before=$(sha256sum /proc/$$/fd/255 | cut -d" " -f1)
len=$(stat -Lc %s "$self")
python3 - "$self" "$len" <<'PY'
import sys
p, n = sys.argv[1], int(sys.argv[2])
b = open(p, "rb").read().replace(b"#PADPADPAD", b"#XXXXXXXXX")
assert len(b) == n, (len(b), n)
fh = open(p, "r+b"); fh.write(b); fh.close()
PY
after=$(sha256sum /proc/$$/fd/255 | cut -d" " -f1)
[ "$before" = "$after" ] && echo STABLE || echo FOLLOWED
#PADPADPAD
'''
    r4, _ = run_bash(inplace)
    check("4a. BLIND SPOT PINNED: a same-length in-place rewrite of our own inode IS "
          "followed by the fd (self-derivation is rename-proof, not spoof-proof)",
          r4.stdout.strip().endswith("FOLLOWED"),
          f"stdout={r4.stdout.strip()!r} stderr={r4.stderr[-400:]!r}")

    # ---- 5. hygiene -----------------------------------------------------------------
    r5 = subprocess.run(["bash", "-n", WATCHER], capture_output=True, text=True)
    check("5a. the watcher under test parses", r5.returncode == 0, r5.stderr[-400:])

    print()
    print(f"watcher under test: {WATCHER}\n  sha256 {watcher_sha}")
    if failures:
        print(f"FAILED {len(failures)}: " + "; ".join(sorted(set(failures))))
        return 1
    print("all properties hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
