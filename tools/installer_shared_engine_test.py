#!/usr/bin/env python3
"""`deploy/install-members.sh` must install the shared decision engine as a
digested install artifact whose ACTIVE set is exactly the RECORDED set, and
must record every installed engine file in the authority file's
`shared_engine` section.

WHY THIS EXISTS (#481, stage 1; #525 review). Until this change the ledger
bound each member's hook entrypoints and ZERO bytes of the engine those
entrypoints import. The first cut of the fix still failed the invariant one
level down: a per-file overwrite loop leaves a deleted or renamed module live
on disk while the ledger stops naming it — bytes executable that no deployment
truth represents. So the engine now installs as ONE content-addressed build:
stage the declared set into a fresh directory, verify every digest there, then
flip the `shared` symlink to it with a single atomic rename. The tests below
pin the failure directions in order: drift on disk must read as drift against
the ledger; a file removed from the source must leave the active set; a re-run
must neither churn the ledger nor rebuild what already verifies.

WHAT IS INSTALLED IS WHAT THE MANIFEST DECLARES (the #525 "option B" ruling):
`plugins/_shared/RUNTIME_MANIFEST.txt`, one filename per line. `_shared` holds
the tests beside the engine, so the engine set is a declaration, not a glob —
and the last test below pins the declaration against what the hooks actually
import, in both directions.

The section is ADDITIVE: the authority file's only shipped consumer
(core/src/server/dashboard.rs's deployment_health) reads `build_id` alone, so
one test also asserts the pre-existing keys survive unchanged in shape.

Hermetic: every case builds a throwaway repo root and a throwaway HOME; real
installs point HESTIA_HOME at a sandbox inside the same tmpdir. Nothing reads
or writes the real fleet, and the governed-session refusal rail is never
touched — the env carries no session markers, so no ACK is ever needed.

Run:  python3 tools/installer_shared_engine_test.py
"""

import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "deploy", "install-members.sh")

ENGINE_FILES = ("hestia_gate_core.py", "hestia_gate_mechanism.py",
                "hestia_governance_closure.py")
# Lives in the fake _shared but NOT in the fake manifest: the installed set
# must be the DECLARED set, so this must never reach the active directory.
DECOY_TEST = "sprintZ_test.py"

FAILS = []


def check(cond, label):
    if not cond:
        FAILS.append(label)


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def write_manifest(root, names):
    with open(os.path.join(root, "plugins", "_shared", "RUNTIME_MANIFEST.txt"),
              "w") as fh:
        fh.write("# fake manifest\n" + "\n".join(names) + "\n")


def build(tmp):
    """A fake repo root (member `m` with one registered hook, plus a _shared
    engine dir with a manifest and a decoy test file) and a fake HOME holding
    the harness registration. Returns (repo_root, home, hestia_home, env) with
    env already sandboxed: DRY_RUN off, HESTIA_HOME under tmp, and no session
    markers — so the refusal rail is legitimately uninvolved, not overridden."""
    root = os.path.join(tmp, "repo")
    home = os.path.join(tmp, "home")
    hestia_home = os.path.join(tmp, "hestia-home")
    os.makedirs(os.path.join(root, "deploy"))
    os.makedirs(os.path.join(root, "plugins", "m", "hooks"))
    shared = os.path.join(root, "plugins", "_shared")
    os.makedirs(shared)
    os.makedirs(home)
    shutil.copy(SCRIPT, os.path.join(root, "deploy", "install-members.sh"))
    with open(os.path.join(root, "plugins", "m", "hooks", "hook.py"), "w") as fh:
        fh.write("# fake hook\n")
    for f in ENGINE_FILES + (DECOY_TEST,):
        with open(os.path.join(shared, f), "w") as fh:
            fh.write(f"# fake engine: {f}\n")
    write_manifest(root, ENGINE_FILES)
    with open(os.path.join(root, "plugins", "m", "expects.json"), "w") as fh:
        json.dump({"install": {
            "dest": "~/.harness/hooks",
            "registration": {"reader": "json-hook-commands",
                             "path": [".harness", "settings.json"]},
            "files": ["hooks/hook.py"],
        }}, fh)
    hook_dir = os.path.join(home, ".harness", "hooks")
    os.makedirs(hook_dir)
    with open(os.path.join(home, ".harness", "settings.json"), "w") as fh:
        json.dump({"hooks": {"PreToolUse": [{"hooks": [
            {"type": "command",
             "command": f"E=1 python3 {os.path.join(hook_dir, 'hook.py')}"}]}]}}, fh)
    env = dict(os.environ, HOME=home, HESTIA_HOME=hestia_home)
    # A test must never depend on the tester's own seat being governed or not.
    env.pop("CLAUDECODE", None)
    env.pop("HESTIA_ROLE", None)
    env.pop("DRY_RUN", None)
    return root, home, hestia_home, env


def run(root, env):
    p = subprocess.run(
        ["bash", os.path.join(root, "deploy", "install-members.sh")],
        capture_output=True, text=True, env=env,
    )
    return p.returncode, p.stdout + p.stderr


def load_ledger(hestia_home):
    with open(os.path.join(hestia_home, "current-build.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def audit_engine(ledger):
    """The stage-1 audit shape: every ledger entry must name an installed file
    whose current bytes hash to the recorded digest. Returns the mismatches —
    the list a tampered install must appear on."""
    bad = []
    for entry in ledger["shared_engine"]:
        path = entry["path"]
        if not os.path.isfile(path) or sha256(path) != entry["sha256"]:
            bad.append(entry["file"])
    return bad


def active_dir(hestia_home):
    return os.path.join(hestia_home, "shared")


def test_shared_engine_is_installed_and_digested():
    with tempfile.TemporaryDirectory() as tmp:
        root, _home, hestia_home, env = build(tmp)
        rc, out = run(root, env)
        check(rc == 0, f"install exited {rc}: {out}")
        ledger = load_ledger(hestia_home)

        recorded = {e["file"]: e for e in ledger.get("shared_engine", [])}
        check(set(recorded) == set(ENGINE_FILES),
              f"shared_engine records {sorted(recorded)}, expected {sorted(ENGINE_FILES)}")
        for f in ENGINE_FILES:
            installed = os.path.join(active_dir(hestia_home), f)
            check(os.path.isfile(installed), f"{f} is not in the active engine directory")
            entry = recorded.get(f, {})
            check(entry.get("path") == installed,
                  f"{f}: ledger path {entry.get('path')!r} is not the stable active path")
            check(entry.get("sha256") == sha256(installed),
                  f"{f}: ledger digest does not match the installed copy")
            src = os.path.join(root, "plugins", "_shared", f)
            check(sha256(installed) == sha256(src),
                  f"{f}: installed bytes differ from the checkout")
        check(not audit_engine(ledger), "fresh install failed its own audit")

        # The active set is EXACTLY the declared set — the decoy test file that
        # lives beside the engine in _shared must never be installed.
        active_set = set(os.listdir(active_dir(hestia_home)))
        check(active_set == set(ENGINE_FILES),
              f"active set {sorted(active_set)} is not exactly the manifest set")
        check(DECOY_TEST not in active_set,
              "a file absent from the manifest was installed anyway (the glob defect)")
        # The mechanism the exactness rests on: `shared` is a symlink to one
        # content-addressed build, so the swap is atomic and interruption-safe.
        check(os.path.islink(active_dir(hestia_home)),
              "shared is not a symlink — the install is not the atomic-flip design")
        check(os.path.basename(os.path.realpath(active_dir(hestia_home))) in out,
              "the activated build digest was not reported in the output")

        # The pre-existing contract must be untouched by the additive key.
        check(isinstance(ledger.get("build_id"), str) and ledger["build_id"],
              "build_id missing or changed shape")
        check(isinstance(ledger.get("members"), list) and
              ledger["members"][0].get("member") == "m",
              "members section missing or changed shape")


def test_tampered_installed_engine_file_is_detectable():
    """The whole point of the section: drift on disk must read as drift against
    the ledger, and a re-run must put the recorded bytes back."""
    with tempfile.TemporaryDirectory() as tmp:
        root, _home, hestia_home, env = build(tmp)
        rc, out = run(root, env)
        check(rc == 0, f"install exited {rc}: {out}")

        victim = os.path.join(active_dir(hestia_home), "hestia_gate_core.py")
        with open(victim, "a") as fh:
            fh.write("# a hand-edit the ledger never approved\n")
        bad = audit_engine(load_ledger(hestia_home))
        check(bad == ["hestia_gate_core.py"],
              f"tampered engine file was not detectable against the ledger (audit: {bad})")

        rc, out = run(root, env)
        check(rc == 0, f"re-run exited {rc}: {out}")
        check(not audit_engine(load_ledger(hestia_home)),
              "re-run did not restore the recorded bytes")
        check("FAILED re-verification" in out,
              "a build whose bytes no longer match their address was reused silently")


def test_removed_source_file_leaves_the_active_set():
    """The #525 blocker's counterexample, pinned: install {A,B,C}, remove B
    from the source tree and the manifest, reinstall. B must be gone from the
    ACTIVE set, and the ledger's set must equal the active set exactly."""
    with tempfile.TemporaryDirectory() as tmp:
        root, _home, hestia_home, env = build(tmp)
        rc, out = run(root, env)
        check(rc == 0, f"install exited {rc}: {out}")
        check(set(os.listdir(active_dir(hestia_home))) == set(ENGINE_FILES),
              "initial install did not activate the full manifest set")

        removed = "hestia_gate_mechanism.py"
        os.remove(os.path.join(root, "plugins", "_shared", removed))
        write_manifest(root, [f for f in ENGINE_FILES if f != removed])
        rc, out = run(root, env)
        check(rc == 0, f"reinstall after removal exited {rc}: {out}")

        active_set = set(os.listdir(active_dir(hestia_home)))
        check(removed not in active_set,
              "a file deleted from the source is still loadable in the active engine set")
        check(active_set == {"hestia_gate_core.py", "hestia_governance_closure.py"},
              f"active set after removal is {sorted(active_set)}")
        recorded = {e["file"] for e in load_ledger(hestia_home)["shared_engine"]}
        check(recorded == active_set,
              f"ledger set {sorted(recorded)} != active set {sorted(active_set)}")
        check(not audit_engine(load_ledger(hestia_home)),
              "post-removal install failed its own audit")


def test_rerun_is_idempotent_except_timestamps():
    with tempfile.TemporaryDirectory() as tmp:
        root, _home, hestia_home, env = build(tmp)
        rc, out = run(root, env)
        check(rc == 0, f"first install exited {rc}: {out}")
        first = load_ledger(hestia_home)

        rc, out = run(root, env)
        check(rc == 0, f"second install exited {rc}: {out}")
        second = load_ledger(hestia_home)

        for stamp in ("installed_at", "installed_at_iso"):
            first.pop(stamp, None)
            second.pop(stamp, None)
        check(first == second,
              "re-run changed the ledger beyond its timestamps")
        check("(already current)" in out,
              "second run did not report the engine as already current")
        check("wrote build" not in out,
              "second run rebuilt an engine build that already verified")


def test_dry_run_reports_the_engine_but_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        root, _home, hestia_home, env = build(tmp)
        rc, out = run(root, dict(env, DRY_RUN="1"))
        check(rc == 0, f"dry run exited {rc}: {out}")
        for f in ENGINE_FILES:
            check(f"would {f}" in out, f"dry run did not report it would install {f}")
        check(not os.path.exists(active_dir(hestia_home)),
              "dry run created the active engine path")
        check(not os.path.exists(os.path.join(hestia_home, "shared.builds")),
              "dry run created the builds directory")
        check(not os.path.exists(os.path.join(hestia_home, "current-build.json")),
              "dry run wrote the authority file")


def test_no_registered_member_is_state_neutral():
    """A no-member run must not change executable bytes without deployment truth.

    Moving engine activation before member discovery made this path install and activate
    the shared engine, then report "no member installed" and withhold the authority record.
    A real registered target must be the trigger for activation.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root, home, hestia_home, env = build(tmp)
        os.remove(os.path.join(home, ".harness", "settings.json"))
        rc, out = run(root, env)
        check(rc == 0, f"no-member install exited {rc}: {out}")
        check("no member installed" in out,
              "no-member run did not state that no deployment occurred")
        check(not os.path.exists(hestia_home),
              "no-member run mutated Hestia state despite withholding authority")


def test_manifest_declares_exactly_what_the_runtime_imports():
    """The drift guard for option B, in both directions: every manifest entry
    must exist and be a runtime module (never a test), and every _shared module
    any hook — or any declared engine module — imports must be declared. A
    static import scan is deliberately sufficient: this is a drift alarm, not
    a proof of non-import."""
    shared = os.path.join(REPO, "plugins", "_shared")
    manifest_path = os.path.join(shared, "RUNTIME_MANIFEST.txt")
    check(os.path.isfile(manifest_path), "plugins/_shared/RUNTIME_MANIFEST.txt is missing")
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = [ln.strip() for ln in fh
                    if ln.strip() and not ln.startswith("#")]
    check(manifest, "RUNTIME_MANIFEST.txt declares no files")
    present = set(os.listdir(shared)) if os.path.isdir(shared) else set()
    for f in manifest:
        check(f in present, f"manifest declares {f}, which does not exist in _shared")
        check(f.endswith(".py") and not f.endswith("_test.py")
              and not f.startswith("test_"),
              f"manifest entry {f} is not a runtime-module shape (tests are not engine)")

    scan = [os.path.join(shared, f) for f in manifest]
    for hooks_dir in glob.glob(os.path.join(REPO, "plugins", "*", "hooks")):
        scan.extend(glob.glob(os.path.join(hooks_dir, "*.py")))
    imported = set()
    for path in scan:
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as fh:
            for m in re.finditer(r"^\s*(?:from|import)\s+([A-Za-z_]\w*)",
                                 fh.read(), re.M):
                mod = m.group(1) + ".py"
                if mod in present:
                    imported.add(mod)
    undeclared = imported - set(manifest)
    check(not undeclared,
          f"_shared modules imported at runtime but absent from RUNTIME_MANIFEST.txt: "
          f"{sorted(undeclared)}")


def test_shared_engine_activation_precedes_member_entrypoints():
    """The cutover's ordering is a safety property, not explanatory prose.

    A newly installed hook may require a module that the previous shared build did not
    contain. The installer must therefore finish the verified engine activation before it
    enters the member loop that writes hook entrypoints. This source-order assertion is
    intentionally narrow: it guards the two transaction boundaries without duplicating the
    shell implementation in the test.
    """
    with open(SCRIPT, encoding="utf-8") as fh:
        source = fh.read()
    member_loop = source.find('for expects in "$REPO_ROOT"/plugins/*/expects.json; do')
    check(member_loop >= 0, "member entrypoint loop was not found")
    activation_call = source.find("    activate_shared_engine\n", member_loop)
    hook_install = source.find('      install -m 0755 "$src" "$target"', member_loop)
    check(activation_call >= 0, "shared-engine activation call was not found in member loop")
    check(hook_install >= 0, "member hook install was not found")
    check(member_loop < activation_call < hook_install,
          "member hook entrypoints can be installed before the shared engine is active")


def teardown_module(_module=None):
    """Deliver the accumulator to pytest as well as to the bare runner — see
    installer_derives_target_test.py, where a green-under-pytest that meant
    nothing was caught by tools/ci_selfexec_test.py."""
    assert not FAILS, "recorded failures: " + "; ".join(FAILS)


if __name__ == "__main__":
    test_shared_engine_is_installed_and_digested()
    test_tampered_installed_engine_file_is_detectable()
    test_removed_source_file_leaves_the_active_set()
    test_rerun_is_idempotent_except_timestamps()
    test_dry_run_reports_the_engine_but_writes_nothing()
    test_no_registered_member_is_state_neutral()
    test_manifest_declares_exactly_what_the_runtime_imports()
    test_shared_engine_activation_precedes_member_entrypoints()
    for f in FAILS:
        print("FAIL", f)
    print(f"{'FAILED' if FAILS else 'ok'}: {len(FAILS)} failure(s)")
    sys.exit(1 if FAILS else 0)
