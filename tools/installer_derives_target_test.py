#!/usr/bin/env python3
"""`deploy/install-members.sh` must DERIVE each hook's target from the harness
registration, and must SKIP — never fabricate — when there is no registration.

WHY THIS EXISTS, measured rather than imagined. On 2026-08-08 the installer read
each member's declared `install.dest`. Three of four members declared correctly.
`gemini` declared `~/.gemini/hooks`, which does not exist on the box, while its
three hooks were registered and enforcing from a `hestia-plugins` subtree. The
installer therefore printed:

    SKIP  gemini — /home/member/.gemini/hooks does not exist (member not installed on this host)

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

Hermetic: every case builds a throwaway repo root and a throwaway HOME. Dry-run
and real-install cases both stay inside that fixture; nothing touches the real fleet.

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
    os.makedirs(os.path.join(root, "tools"))
    os.makedirs(os.path.join(root, "plugins", "m", "hooks"))
    os.makedirs(os.path.join(root, "plugins", "_shared"))
    os.makedirs(home)
    shutil.copy(SCRIPT, os.path.join(root, "deploy", "install-members.sh"))
    shutil.copy(os.path.join(REPO, "tools", "registration_resolver.py"),
                os.path.join(root, "tools", "registration_resolver.py"))
    for f in files:
        with open(os.path.join(root, "plugins", "m", "hooks", f), "w") as fh:
            fh.write("# fake hook\n")
    # Since #481 stage 1 the installer also deploys the shared engine, and dies rather
    # than ledger an empty one — so a fake repo root must ship a fake engine, declared
    # by a fake manifest (the engine set is a declaration, not a glob: #525 review).
    with open(os.path.join(root, "plugins", "_shared", "engine.py"), "w") as fh:
        fh.write("# fake engine\n")
    with open(os.path.join(root, "plugins", "_shared", "RUNTIME_MANIFEST.txt"), "w") as fh:
        fh.write("engine.py\n")
    with open(os.path.join(root, "plugins", "m", "expects.json"), "w") as fh:
        json.dump({"install": expects}, fh)
    if registration is not None:
        dest = os.path.join(home, reg_name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w") as fh:
            fh.write(registration)
    env = dict(os.environ, HOME=home, HESTIA_HOME=os.path.join(home, ".hestia"), DRY_RUN="1")
    # A test must never depend on the tester's own seat being governed or not.
    for key in ("CLAUDECODE", "HESTIA_ROLE", "HESTIA_GATE_INSTALL_ACK", "HESTIA_SKIP_REGISTER"):
        env.pop(key, None)
    return root, home, env


def normal(env):
    result = dict(env, HESTIA_SKIP_REGISTER="1")
    result.pop("DRY_RUN", None)
    return result


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


def test_absolute_interpreter_registration_reaches_installer():
    with tempfile.TemporaryDirectory() as tmp:
        home = os.path.join(tmp, "home")
        hook = os.path.join(home, ".harness", "hooks", "pre_tool_use.py")
        root, home, env = build(
            tmp,
            expects={
                "dest": "~/.harness/hooks",
                "registration": {"reader": "json-hook-commands",
                                 "path": [".harness", "settings.json"]},
                "files": ["hooks/pre_tool_use.py"],
            },
            files=("pre_tool_use.py",),
            reg_name=os.path.join(".harness", "settings.json"),
            registration=json.dumps({"hooks": {"PreToolUse": [{"hooks": [
                {"type": "command", "command": f"{sys.executable} {hook}"},
            ]}]}}),
        )
        os.makedirs(os.path.dirname(hook))
        rc, out = run(root, env)
        check(rc == 0, f"absolute-interpreter dry run exited {rc}: {out}")
        check("would pre_tool_use.py" in out and "unclassified commands" not in out,
              f"absolute interpreter did not resolve its registered hook: {out}")

        with open(hook, "w") as fh:
            fh.write("old bytes\n")
        rc, out = run(root, normal(env))
        check(rc == 0, f"absolute-interpreter normal install exited {rc}: {out}")
        with open(hook) as fh:
            check(fh.read() == "# fake hook\n", "absolute-interpreter target was not installed")
        with open(os.path.join(home, ".hestia", "current-build.json")) as fh:
            authority = json.load(fh)
        rows = [f for m in authority["members"] if m["member"] == "m" for f in m["files"]]
        check([f["path"] for f in rows] == [hook],
              f"absolute-interpreter install recorded the wrong target: {rows}")


def test_absent_registration_skips_and_creates_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        root, home, env = build(tmp, expects={
            "dest": "~/.nowhere/hooks",
            "registration": {"reader": "json-hook-commands",
                             "path": [".harness", "settings.json"]},
            "files": ["hooks/hook.py"],
        })  # no registration file written
        for label, run_env in (("dry-run", env), ("normal", normal(env))):
            rc, out = run(root, run_env)
            check(rc == 0, f"absent-registration {label} run exited {rc}: {out}")
            check("SKIP" in out, f"absent registration did not produce a {label} SKIP")
            check(not os.path.exists(os.path.join(home, ".nowhere")),
                  f"{label} fabricated a destination directory for an absent member")
            check(not os.path.exists(os.path.join(home, ".hestia", "current-build.json")),
                  f"{label} wrote an authority file when nothing was installed")


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


def test_duplicate_basenames_keep_every_registered_target():
    with tempfile.TemporaryDirectory() as tmp:
        home = os.path.join(tmp, "home")
        first = os.path.join(home, ".first", "pre_tool_use.py")
        second = os.path.join(home, ".second", "pre_tool_use.py")
        root, home, env = build(
            tmp,
            expects={
                "dest": "~/.harness/hooks",
                "registration": {"reader": "json-hook-commands",
                                 "path": [".harness", "settings.json"]},
                "files": ["hooks/pre_tool_use.py"],
            },
            files=("pre_tool_use.py",),
            reg_name=os.path.join(".harness", "settings.json"),
            registration=json.dumps({"hooks": {"PreToolUse": [{"hooks": [
                {"type": "command", "command": f"python3 {first}"},
                {"type": "command", "command": f"python3 {second}"},
            ]}]}}),
        )
        os.makedirs(os.path.dirname(first))
        os.makedirs(os.path.dirname(second))
        rc, out = run(root, env)
        actions = [ln for ln in out.splitlines()
                   if ln.lstrip().startswith(("would ", "ok    ", "wrote "))]
        check(rc == 0, f"duplicate-target dry run exited {rc}: {out}")
        hook_actions = [ln for ln in actions if "pre_tool_use.py" in ln]
        check(len(hook_actions) == 2,
              f"two full-path registrations did not produce two install actions: {actions}")
        check(any(os.path.dirname(first) in ln for ln in actions), "first target was lost")
        check(any(os.path.dirname(second) in ln for ln in actions), "second target was lost")

        for label, target in (("first", first), ("second", second)):
            with open(target, "w") as fh:
                fh.write(f"old {label} bytes\n")
        rc, out = run(root, normal(env))
        check(rc == 0, f"duplicate-target normal install exited {rc}: {out}")
        for label, target in (("first", first), ("second", second)):
            with open(target) as fh:
                check(fh.read() == "# fake hook\n", f"{label} target was not installed")
            with open(target + ".pre-install.bak") as fh:
                check(fh.read() == f"old {label} bytes\n", f"{label} backup was not preserved")
        with open(os.path.join(home, ".hestia", "current-build.json")) as fh:
            authority = json.load(fh)
        rows = [f for m in authority["members"] if m["member"] == "m" for f in m["files"]]
        check(sorted(f["path"] for f in rows) == sorted([first, second]),
              f"authority did not record both full targets: {rows}")


def test_unclassified_registration_blocks_a_partial_install():
    with tempfile.TemporaryDirectory() as tmp:
        home = os.path.join(tmp, "home")
        first = os.path.join(home, ".first", "pre_tool_use.py")
        second = os.path.join(home, ".second", "pre_tool_use.py")
        root, home, env = build(
            tmp,
            expects={
                "dest": "~/.harness/hooks",
                "registration": {"reader": "json-hook-commands",
                                 "path": [".harness", "settings.json"]},
                "files": ["hooks/pre_tool_use.py"],
            },
            files=("pre_tool_use.py",),
            reg_name=os.path.join(".harness", "settings.json"),
            registration=json.dumps({"hooks": {"PreToolUse": [{"hooks": [
                {"type": "command", "command": f"python3 {first}"},
                {"type": "command", "command": f"python3 {second}"},
                {"type": "command", "command": "unknown-wrapper --workspace /abs/directory"},
            ]}]}}),
        )
        for label, target in (("first", first), ("second", second)):
            os.makedirs(os.path.dirname(target))
            with open(target, "w") as fh:
                fh.write(f"old {label} bytes\n")
        for label, run_env in (("dry-run", env), ("normal", normal(env))):
            rc, out = run(root, run_env)
            actions = [ln for ln in out.splitlines()
                       if ln.lstrip().startswith(("would ", "ok    ", "wrote "))]
            check(rc != 0, f"incomplete-registration {label} run exited 0: {out}")
            check("FATAL" in out and "unclassified commands" in out,
                  f"incomplete registration was not named as fatal: {out}")
            check(not actions, f"an incomplete target set still produced {label} actions: {actions}")
            for target in (first, second):
                with open(target) as fh:
                    check(fh.read().startswith("old "), f"{label} changed a registered target")
                check(not os.path.exists(target + ".pre-install.bak"),
                      f"{label} made a backup despite changing no target")
            check(not os.path.exists(os.path.join(home, ".hestia", "current-build.json")),
                  f"{label} recorded a partial install as authoritative")


def test_unparseable_and_unreadable_registrations_are_fatal_without_writes():
    for state in ("unparseable", "unreadable"):
        with tempfile.TemporaryDirectory() as tmp:
            config = os.path.join(".harness", "settings.json")
            root, home, env = build(
                tmp,
                expects={
                    "dest": "~/.harness/hooks",
                    "registration": {"reader": "json-hook-commands", "path": config.split(os.sep)},
                    "files": ["hooks/pre_tool_use.py"],
                },
                files=("pre_tool_use.py",),
                reg_name=config,
                registration="{" if state == "unparseable" else None,
            )
            if state == "unreadable":
                os.makedirs(os.path.join(home, config))
            target = os.path.join(home, ".harness", "hooks", "pre_tool_use.py")
            os.makedirs(os.path.dirname(target))
            with open(target, "w") as fh:
                fh.write("operator bytes\n")
            for label, run_env in (("dry-run", env), ("normal", normal(env))):
                rc, out = run(root, run_env)
                check(rc != 0, f"{state} {label} run exited 0: {out}")
                check("FATAL" in out and state in out, f"{state} was not named as fatal: {out}")
                with open(target) as fh:
                    check(fh.read() == "operator bytes\n", f"{state} {label} changed the target")
                check(not os.path.exists(target + ".pre-install.bak"),
                      f"{state} {label} made a backup despite changing no target")
                check(not os.path.exists(os.path.join(home, ".hestia", "current-build.json")),
                      f"{state} {label} wrote an authority file")


def test_duplicate_hydrate_targets_with_distinct_seed_roots_are_fatal():
    with tempfile.TemporaryDirectory() as tmp:
        home = os.path.join(tmp, "home")
        first = os.path.join(home, ".first", "hooks", "hydrate.sh")
        second = os.path.join(home, ".second", "hooks", "hydrate.sh")
        root, home, env = build(
            tmp,
            expects={
                "dest": "~/.harness/hooks",
                "registration": {"reader": "json-hook-commands",
                                 "path": [".harness", "settings.json"]},
                "files": ["hooks/hydrate.sh"],
            },
            files=("hydrate.sh",),
            reg_name=os.path.join(".harness", "settings.json"),
            registration=json.dumps({"hooks": {"SessionEnd": [{"hooks": [
                {"type": "command", "command": f"bash {first}"},
                {"type": "command", "command": f"bash {second}"},
            ]}]}}),
        )
        for label, target in (("first", first), ("second", second)):
            os.makedirs(os.path.dirname(target))
            with open(target, "w") as fh:
                fh.write(f"old {label} bytes\n")
        seed_dir = os.path.join(root, "plugins", "m", "instance")
        os.makedirs(seed_dir)
        with open(os.path.join(seed_dir, "identity.seed.json"), "w") as fh:
            fh.write('{"entity":"m"}\n')
        for label, run_env in (("dry-run", env), ("normal", normal(env))):
            rc, out = run(root, run_env)
            check(rc != 0, f"ambiguous duplicate-hydrate {label} run exited 0: {out}")
            check("FATAL" in out and "distinct identity-seed roots" in out,
                  f"ambiguous hydrate roots were not named as fatal: {out}")
            actions = [ln for ln in out.splitlines()
                       if ln.lstrip().startswith(("would ", "ok    ", "wrote "))]
            check(not actions, f"ambiguous hydrate roots produced {label} actions: {actions}")
            for target in (first, second):
                with open(target) as fh:
                    check(fh.read().startswith("old "), f"{label} changed a hydrate consumer")
                check(not os.path.exists(target + ".pre-install.bak"),
                      f"{label} made a backup for an ambiguous hydrate consumer")
                seed = os.path.join(os.path.dirname(os.path.dirname(target)),
                                    "instance", "identity.seed.json")
                check(not os.path.exists(seed), f"{label} seeded only one ambiguous consumer")
            check(not os.path.exists(os.path.join(home, ".hestia", "current-build.json")),
                  f"ambiguous hydrate {label} run wrote an authority file")


def test_duplicate_hydrate_targets_with_shared_seed_root_serve_both_consumers():
    with tempfile.TemporaryDirectory() as tmp:
        home = os.path.join(tmp, "home")
        first = os.path.join(home, ".shared", "first-hooks", "hydrate.sh")
        second = os.path.join(home, ".shared", "second-hooks", "hydrate.sh")
        root, home, env = build(
            tmp,
            expects={
                "dest": "~/.harness/hooks",
                "registration": {"reader": "json-hook-commands",
                                 "path": [".harness", "settings.json"]},
                "files": ["hooks/hydrate.sh"],
            },
            files=("hydrate.sh",),
            reg_name=os.path.join(".harness", "settings.json"),
            registration=json.dumps({"hooks": {"SessionEnd": [{"hooks": [
                {"type": "command", "command": f"bash {first}"},
                {"type": "command", "command": f"bash {second}"},
            ]}]}}),
        )
        os.makedirs(os.path.dirname(first))
        os.makedirs(os.path.dirname(second))
        seed_dir = os.path.join(root, "plugins", "m", "instance")
        os.makedirs(seed_dir)
        with open(os.path.join(seed_dir, "identity.seed.json"), "w") as fh:
            fh.write('{"entity":"m"}\n')
        with open(os.path.join(root, "plugins", "m", "hooks", "hydrate.sh"), "w") as fh:
            fh.write("""#!/bin/bash
set -eu
seed="$(cd "$(dirname "$0")/.." && pwd)/instance/identity.seed.json"
grep -qx '{"entity":"m"}' "$seed"
printf '%s\\n' "$0" >> "$HOME/hydrated"
""")
        run_env = normal(env)
        rc, out = run(root, run_env)
        check(rc == 0, f"shared-root duplicate-hydrate install exited {rc}: {out}")
        shared_seed = os.path.join(home, ".shared", "instance", "identity.seed.json")
        check(os.path.isfile(shared_seed), "shared hydrate root has no identity seed")
        with open(os.path.join(home, ".hestia", "current-build.json")) as fh:
            authority = json.load(fh)
        check([row["path"] for row in authority["identity_seeds"]] == [shared_seed],
              f"authority recorded the wrong shared seed: {authority['identity_seeds']}")
        for target in (first, second):
            p = subprocess.run(["bash", target], capture_output=True, text=True, env=run_env)
            check(p.returncode == 0,
                  f"installed hydrate consumer {target} could not read the shared seed: {p.stderr}")
        with open(os.path.join(home, "hydrated")) as fh:
            check(fh.read().splitlines() == [first, second],
                  "both registered hydrate consumers did not execute successfully")


def test_later_member_failure_happens_before_any_member_write():
    for state in ("unparseable", "unclassified", "ambiguous-hydrate"):
        with tempfile.TemporaryDirectory() as tmp:
            broken_file = "hydrate.sh" if state == "ambiguous-hydrate" else "hook.py"
            root, home, env = build(
                tmp,
                expects={
                    "dest": "~/.b/hooks",
                    "registration": {"reader": "json-hook-commands",
                                     "path": [".b", "settings.json"]},
                    "files": [f"hooks/{broken_file}"],
                },
                files=(broken_file,),
            )
            os.rename(os.path.join(root, "plugins", "m"), os.path.join(root, "plugins", "b"))

            healthy = os.path.join(home, ".a", "hooks", "hook.py")
            os.makedirs(os.path.dirname(healthy))
            with open(healthy, "w") as fh:
                fh.write("operator bytes\n")
            os.makedirs(os.path.join(root, "plugins", "a", "hooks"))
            with open(os.path.join(root, "plugins", "a", "hooks", "hook.py"), "w") as fh:
                fh.write("# fake hook\n")
            with open(os.path.join(root, "plugins", "a", "expects.json"), "w") as fh:
                json.dump({"install": {
                    "dest": "~/.a/hooks",
                    "registration": {"reader": "json-hook-commands",
                                     "path": [".a", "settings.json"]},
                    "files": ["hooks/hook.py"],
                }}, fh)
            os.makedirs(os.path.join(home, ".a"), exist_ok=True)
            with open(os.path.join(home, ".a", "settings.json"), "w") as fh:
                fh.write(json.dumps({"hooks": {"PreToolUse": [{"hooks": [
                    {"type": "command", "command": f"{sys.executable} {healthy}"},
                ]}]}}))

            os.makedirs(os.path.join(home, ".b"), exist_ok=True)
            broken_config = os.path.join(home, ".b", "settings.json")
            if state == "unparseable":
                with open(broken_config, "w") as fh:
                    fh.write("{")
            elif state == "unclassified":
                with open(broken_config, "w") as fh:
                    fh.write(json.dumps({"hooks": {"PreToolUse": [{"hooks": [
                        {"type": "command", "command": f"{sys.executable} {home}/.b/hooks/hook.py"},
                        {"type": "command", "command": "unknown-wrapper --workspace /abs/directory"},
                    ]}]}}))
            else:
                first = os.path.join(home, ".first", "hooks", "hydrate.sh")
                second = os.path.join(home, ".second", "hooks", "hydrate.sh")
                with open(broken_config, "w") as fh:
                    fh.write(json.dumps({"hooks": {"SessionEnd": [{"hooks": [
                        {"type": "command", "command": f"bash {first}"},
                        {"type": "command", "command": f"bash {second}"},
                    ]}]}}))
                os.makedirs(os.path.join(root, "plugins", "b", "instance"))
                with open(os.path.join(root, "plugins", "b", "instance", "identity.seed.json"), "w") as fh:
                    fh.write('{"entity":"b"}\n')

            os.makedirs(os.path.join(home, ".hestia", "shared.builds", "old"))
            os.symlink("shared.builds/old", os.path.join(home, ".hestia", "shared"))
            rc, out = run(root, normal(env))
            check(rc != 0, f"{state}: later broken member exited 0: {out}")
            with open(healthy) as fh:
                check(fh.read() == "operator bytes\n", f"{state}: healthy member was written first")
            check(not os.path.exists(healthy + ".pre-install.bak"),
                  f"{state}: healthy member was backed up before the failure")
            check(os.readlink(os.path.join(home, ".hestia", "shared")) == "shared.builds/old",
                  f"{state}: shared engine moved before the failure")
            check(not os.path.exists(os.path.join(home, ".hestia", "current-build.json")),
                  f"{state}: partial install was recorded as authoritative")


def test_missing_resolver_is_fatal_not_an_empty_registration():
    with tempfile.TemporaryDirectory() as tmp:
        root, _home, env = build(tmp, expects={
            "dest": "~/.harness/hooks",
            "registration": {"reader": "json-hook-commands",
                             "path": [".harness", "settings.json"]},
            "files": ["hooks/pre_tool_use.py"],
        })
        os.unlink(os.path.join(root, "tools", "registration_resolver.py"))
        rc, out = run(root, env)
        check(rc != 0, "a missing canonical resolver exited 0")
        check("resolver is missing" in out, f"missing resolver was not named: {out}")


def test_resolver_crash_is_fatal_not_an_empty_registration():
    with tempfile.TemporaryDirectory() as tmp:
        root, _home, env = build(tmp, expects={
            "dest": "~/.harness/hooks",
            "registration": {"reader": "json-hook-commands",
                             "path": [".harness", "settings.json"]},
            "files": ["hooks/pre_tool_use.py"],
        })
        with open(os.path.join(root, "tools", "registration_resolver.py"), "w") as fh:
            fh.write("raise RuntimeError('boom')\n")
        rc, out = run(root, env)
        check(rc != 0, "a crashing canonical resolver exited 0")
        check("resolver failed (rc=1)" in out, f"resolver crash was not named: {out}")


def test_not_declared_is_a_skip_not_a_resolver_failure():
    with tempfile.TemporaryDirectory() as tmp:
        root, home, env = build(tmp, expects={
            "dest": "~/.nowhere/hooks",
            "files": ["hooks/pre_tool_use.py"],
        })
        rc, out = run(root, env)
        check(rc == 0, f"not-declared run exited {rc}: {out}")
        check("declares no install.registration" in out,
              f"not-declared was not reported distinctly: {out}")
        check(not os.path.exists(os.path.join(home, ".nowhere")),
              "not-declared fabricated a destination directory")


def test_every_shipped_member_declares_a_reader_the_core_implements():
    """Guards the data half: a member added without a registration block, or with a
    reader nobody implements, must fail HERE and not on the operator's box."""
    with open(os.path.join(REPO, "tools", "registration_resolver.py"), encoding="utf-8") as fh:
        resolver = fh.read()
    implemented = {r for r in ("json-hook-commands", "toml-hook-commands")
                   if f'"{r}"' in resolver}
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


def teardown_module(_module=None):
    """Deliver the accumulator to pytest as well as to the bare runner.

    `FAILS` is read in `__main__` only, so under `python3 -m pytest` every test
    would record its failures, return normally, and be reported PASSED — a green
    indistinguishable from the null state, in exactly the invocation a `*_test.py`
    name invites. Caught by `tools/ci_selfexec_test.py` on this file's first CI run,
    which is the guard doing its job on the commit that introduced the hazard.
    """
    assert not FAILS, "recorded failures: " + "; ".join(FAILS)


TESTS = [
    test_derives_target_when_declaration_is_wrong,
    test_absolute_interpreter_registration_reaches_installer,
    test_absent_registration_skips_and_creates_nothing,
    test_registered_but_this_file_is_not,
    test_unknown_reader_is_fatal_not_empty,
    test_governed_session_is_refused_but_dry_run_is_not,
    test_duplicate_basenames_keep_every_registered_target,
    test_unclassified_registration_blocks_a_partial_install,
    test_unparseable_and_unreadable_registrations_are_fatal_without_writes,
    test_duplicate_hydrate_targets_with_distinct_seed_roots_are_fatal,
    test_duplicate_hydrate_targets_with_shared_seed_root_serve_both_consumers,
    test_later_member_failure_happens_before_any_member_write,
    test_missing_resolver_is_fatal_not_an_empty_registration,
    test_resolver_crash_is_fatal_not_an_empty_registration,
    test_not_declared_is_a_skip_not_a_resolver_failure,
    test_every_shipped_member_declares_a_reader_the_core_implements,
]


if __name__ == "__main__":
    defined = {k for k in globals() if k.startswith("test_")}
    listed = {t.__name__ for t in TESTS}
    if defined != listed:
        print(f"TESTS list is stale: defined-not-listed {sorted(defined - listed)}, "
              f"listed-not-defined {sorted(listed - defined)}")
        sys.exit(1)
    for t in TESTS:
        t()
    for f in FAILS:
        print("FAIL", f)
    print(f"{'FAILED' if FAILS else 'ok'}: {len(FAILS)} failure(s), {len(TESTS)} test function(s)")
    sys.exit(1 if FAILS else 0)
