#!/usr/bin/env python3
"""`deploy/install-members.sh` must DERIVE each hook's target from the harness
registration, and must SKIP — never fabricate — when there is no registration.

WHY THIS EXISTS, measured rather than imagined. On 2026-08-08 the installer read
each member's declared `install.dest`. Three of four members declared correctly.
`gemini` declared `~/.gemini/hooks`, which does not exist on the box, while its
three hooks were registered and enforcing from a `hestia-plugins` subtree. The
installer therefore printed:

    SKIP  gemini — /home/dp/.gemini/hooks does not exist (member not installed on this host)

about a member that was fully installed and currently enforcing, and would have
left its gate stale indefinitely while reporting the member absent. A declared
value stood where an audited one was available — the same class as
`merged != deployed` and `registration != reachability`.

The failure direction is the one worth pinning. The invariant was written as "a
directory can exist with nothing invoking it"; what actually happened was the
mirror image — *nothing was at the declared directory while something WAS
invoking, from elsewhere* — and that shape reads as a clean skip, not as an
error. So the assertions below check the derivation AND check that each way of
having no registration produces a distinguishable outcome, because "skipped" and
"deployed" being told apart is the whole point of the script.

Hermetic: every case builds a throwaway repo root and a throwaway HOME. Nothing
reads or writes the real fleet, and DRY_RUN=1 means no case can install.

Run:  python3 tools/installer_derives_target_test.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "deploy", "install-members.sh")

FAILS = []


def check(cond, label):
    if not cond:
        FAILS.append(label)


def build(tmp, *, expects, registration=None, reg_name=None, files=("hook.py",)):
    """A fake repo root + fake HOME. Returns (repo_root, home, env)."""
    root = os.path.join(tmp, "repo")
    home = os.path.join(tmp, "home")
    os.makedirs(os.path.join(root, "deploy"))
    os.makedirs(os.path.join(root, "plugins", "m", "hooks"))
    os.makedirs(home)
    shutil.copy(SCRIPT, os.path.join(root, "deploy", "install-members.sh"))
    for f in files:
        with open(os.path.join(root, "plugins", "m", "hooks", f), "w") as fh:
            fh.write("# fake hook\n")
    with open(os.path.join(root, "plugins", "m", "expects.json"), "w") as fh:
        json.dump({"install": expects}, fh)
    if registration is not None:
        dest = os.path.join(home, reg_name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w") as fh:
            fh.write(registration)
    env = dict(os.environ, HOME=home, DRY_RUN="1")
    # A test must never depend on the tester's own seat being governed or not.
    env.pop("CLAUDECODE", None)
    env.pop("HESTIA_ROLE", None)
    return root, home, env


def run(root, env):
    p = subprocess.run(
        ["bash", os.path.join(root, "deploy", "install-members.sh")],
        capture_output=True, text=True, env=env,
    )
    return p.returncode, p.stdout + p.stderr


def test_derives_target_when_declaration_is_wrong():
    """The gemini shape: declared dest absent, real invocation somewhere else."""
    with tempfile.TemporaryDirectory() as tmp:
        real = os.path.join(".elsewhere", "deep", "hooks")
        home = os.path.join(tmp, "home")
        root, home, env = build(
            tmp,
            expects={
                "dest": "~/.nowhere/hooks",           # a lie, and an absent one
                "registration": {"reader": "json-hook-commands",
                                 "path": [".harness", "settings.json"]},
                "files": ["hooks/hook.py"],
            },
            reg_name=os.path.join(".harness", "settings.json"),
            registration=json.dumps({"hooks": {"PreToolUse": [{"hooks": [
                {"type": "command",
                 "command": f"E=1 python3 {os.path.join(home, real, 'hook.py')}"}]}]}}),
        )
        os.makedirs(os.path.join(home, real))
        rc, out = run(root, env)
        check(rc == 0, f"wrong-declaration run exited {rc}: {out}")
        check(os.path.join(home, real) in out,
              "installer did not resolve the hook to its REGISTERED directory")
        # Only the ACTION lines may be scanned: the divergence WARN names the declared
        # path on purpose, so a naive whole-output search fails on the fix it is meant
        # to certify. (This assertion was written the naive way first and red-flagged
        # itself — recorded because a guard that has never been wrong has never run.)
        actions = [ln for ln in out.splitlines()
                   if ln.lstrip().startswith(("would ", "ok    ", "wrote "))]
        check(actions, "no install action lines at all")
        check(not any("/.nowhere/hooks" in ln for ln in actions),
              "installer still routed an action to the declared (wrong) destination")
        check("WARN" in out and "declares" in out,
              "divergence between declared and registered was not reported")


def test_absent_registration_skips_and_creates_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        root, home, env = build(tmp, expects={
            "dest": "~/.nowhere/hooks",
            "registration": {"reader": "json-hook-commands",
                             "path": [".harness", "settings.json"]},
            "files": ["hooks/hook.py"],
        })  # no registration file written
        rc, out = run(root, env)
        check(rc == 0, f"absent-registration run exited {rc}: {out}")
        check("SKIP" in out, "absent registration did not produce a SKIP")
        check(not os.path.exists(os.path.join(home, ".nowhere")),
              "installer fabricated a destination directory for an absent member")
        check(not os.path.exists(os.path.join(home, ".hestia", "current-build.json")),
              "authority file written when nothing was installed")


def test_registered_but_this_file_is_not():
    """A member on the box whose SOME files are unregistered: partial, and said so."""
    with tempfile.TemporaryDirectory() as tmp:
        real = os.path.join(".harness", "hooks")
        home = os.path.join(tmp, "home")
        root, home, env = build(
            tmp,
            expects={
                "dest": "~/.harness/hooks",
                "registration": {"reader": "toml-hook-commands",
                                 "path": [".harness", "config.toml"]},
                "files": ["hooks/hook.py", "hooks/unregistered.py"],
            },
            files=("hook.py", "unregistered.py"),
            reg_name=os.path.join(".harness", "config.toml"),
            registration="[[hooks]]\ncommand = "
                         f'"{os.path.join(home, real, "hook.py")}"\n',
        )
        os.makedirs(os.path.join(home, real), exist_ok=True)
        rc, out = run(root, env)
        check(rc == 0, f"partial run exited {rc}: {out}")
        check("unregistered.py" in out and "not registered" in out,
              "an unregistered file was not reported as skipped")
        check("would hook.py" in out or "ok    hook.py" in out,
              "the registered sibling was not processed")


def test_unknown_reader_is_fatal_not_empty():
    """A typo'd reader must not read as 'this member registers no hooks'."""
    with tempfile.TemporaryDirectory() as tmp:
        root, _home, env = build(tmp, expects={
            "dest": "~/.harness/hooks",
            "registration": {"reader": "jsn-hook-comands",   # typo
                             "path": [".harness", "settings.json"]},
            "files": ["hooks/hook.py"],
        }, reg_name=os.path.join(".harness", "settings.json"), registration="{}")
        rc, out = run(root, env)
        check(rc != 0, "an unknown registration reader exited 0 (silently skipped)")
        check("unknown install.registration.reader" in out,
              f"unknown reader did not name itself: {out}")


def test_governed_session_is_refused_but_dry_run_is_not():
    with tempfile.TemporaryDirectory() as tmp:
        root, _home, env = build(tmp, expects={
            "dest": "~/.harness/hooks",
            "registration": {"reader": "json-hook-commands",
                             "path": [".harness", "settings.json"]},
            "files": ["hooks/hook.py"],
        })
        governed = dict(env, CLAUDECODE="1")
        governed.pop("DRY_RUN")
        rc, out = run(root, governed)
        check(rc == 3, f"a governed session was not refused (exit {rc})")
        check("REFUSED" in out, "refusal did not say so")

        rc, _ = run(root, dict(env, CLAUDECODE="1"))   # DRY_RUN=1 still set
        check(rc == 0, f"DRY_RUN was refused inside a session (exit {rc}); "
                       "measuring a deployment is not performing one")

        acked = dict(governed, HESTIA_GATE_INSTALL_ACK="i-am-the-operator")
        rc, out = run(root, acked)
        check("OVERRIDE" in out, "an acked override did not announce itself")


def test_every_shipped_member_declares_a_reader_the_core_implements():
    """Guards the data half: a member added without a registration block, or with a
    reader nobody implements, must fail HERE and not on the operator's box."""
    with open(SCRIPT, encoding="utf-8") as fh:
        script = fh.read()
    implemented = {r for r in ("json-hook-commands", "toml-hook-commands")
                   if f'"{r}"' in script}
    check(len(implemented) == 2,
          f"core no longer implements the expected readers: {implemented}")
    plugins = os.path.join(REPO, "plugins")
    for member in sorted(os.listdir(plugins)):
        path = os.path.join(plugins, member, "expects.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            install = (json.load(fh).get("install") or {})
        if not install.get("files"):
            continue
        reg = install.get("registration") or {}
        check(bool(reg.get("path")),
              f"{member}/expects.json installs files but declares no registration path")
        check(reg.get("reader") in implemented,
              f"{member}/expects.json declares reader {reg.get('reader')!r}, "
              f"which the installer does not implement")


if __name__ == "__main__":
    test_derives_target_when_declaration_is_wrong()
    test_absent_registration_skips_and_creates_nothing()
    test_registered_but_this_file_is_not()
    test_unknown_reader_is_fatal_not_empty()
    test_governed_session_is_refused_but_dry_run_is_not()
    test_every_shipped_member_declares_a_reader_the_core_implements()
    for f in FAILS:
        print("FAIL", f)
    print(f"{'FAILED' if FAILS else 'ok'}: {len(FAILS)} failure(s)")
    sys.exit(1 if FAILS else 0)
