#!/usr/bin/env python3
"""`deploy/install-members.sh` must install the shared decision engine
(`plugins/_shared/*.py`) as a digested install artifact, and must record every
installed engine file in the authority file's `shared_engine` section.

WHY THIS EXISTS (#481, stage 1). Until this change the ledger bound each
member's hook entrypoints and ZERO bytes of the engine those entrypoints
import: the hooks digested to installed paths while `hestia_gate_core.py` and
its siblings executed from the mutable workspace checkout, digested nowhere.
An audit that digests the hook but not the engine the hook imports proves the
shape of the gate, not its decisions. The failure direction worth pinning is
the quiet one — an installed engine file that DRIFTS (tampered, hand-edited,
stale) while the ledger still claims the original bytes — so the assertions
below check not just that the section exists but that a tampered byte is
detectable against it, and that a re-run neither churns the ledger nor leaves
drift in place.

The section is ADDITIVE: the authority file's only shipped consumer
(core/src/server/dashboard.rs's deployment_health) reads `build_id` alone, so
one test also asserts the pre-existing keys survive unchanged in shape.

Hermetic: every case builds a throwaway repo root and a throwaway HOME; real
installs point HESTIA_HOME at a sandbox inside the same tmpdir. Nothing reads
or writes the real fleet, and the governed-session refusal rail is never
touched — the env carries no session markers, so no ACK is ever needed.

Run:  python3 tools/installer_shared_engine_test.py
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "deploy", "install-members.sh")

ENGINE_FILES = ("hestia_gate_core.py", "hestia_gate_mechanism.py",
                "hestia_governance_closure.py")

FAILS = []


def check(cond, label):
    if not cond:
        FAILS.append(label)


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def build(tmp):
    """A fake repo root (member `m` with one registered hook, plus a _shared
    engine dir) and a fake HOME holding the harness registration. Returns
    (repo_root, home, hestia_home, env) with env already sandboxed: DRY_RUN
    off, HESTIA_HOME under tmp, and no session markers — so the refusal rail
    is legitimately uninvolved rather than overridden."""
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
    for f in ENGINE_FILES:
        with open(os.path.join(shared, f), "w") as fh:
            fh.write(f"# fake engine: {f}\n")
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
            installed = os.path.join(hestia_home, "shared", f)
            check(os.path.isfile(installed), f"{f} was not installed to HESTIA_HOME/shared")
            entry = recorded.get(f, {})
            check(entry.get("path") == installed,
                  f"{f}: ledger path {entry.get('path')!r} is not the installed location")
            check(entry.get("sha256") == sha256(installed),
                  f"{f}: ledger digest does not match the installed copy")
            src = os.path.join(root, "plugins", "_shared", f)
            check(sha256(installed) == sha256(src),
                  f"{f}: installed bytes differ from the checkout")
        check(not audit_engine(ledger), "fresh install failed its own audit")

        # The pre-existing contract must be untouched by the additive key.
        check(isinstance(ledger.get("build_id"), str) and ledger["build_id"],
              "build_id missing or changed shape")
        check(isinstance(ledger.get("members"), list) and
              ledger["members"][0].get("member") == "m",
              "members section missing or changed shape")


def test_tampered_installed_engine_file_is_detectable():
    """The whole point of the section: drift on disk must read as drift
    against the ledger, and a re-run must put the recorded bytes back."""
    with tempfile.TemporaryDirectory() as tmp:
        root, _home, hestia_home, env = build(tmp)
        rc, out = run(root, env)
        check(rc == 0, f"install exited {rc}: {out}")

        victim = os.path.join(hestia_home, "shared", "hestia_gate_core.py")
        with open(victim, "a") as fh:
            fh.write("# a hand-edit the ledger never approved\n")
        bad = audit_engine(load_ledger(hestia_home))
        check(bad == ["hestia_gate_core.py"],
              f"tampered engine file was not detectable against the ledger (audit: {bad})")

        rc, out = run(root, env)
        check(rc == 0, f"re-run exited {rc}: {out}")
        check(not audit_engine(load_ledger(hestia_home)),
              "re-run did not restore the recorded bytes")
        check("wrote hestia_gate_core.py" in out,
              "re-run did not report rewriting the tampered file")


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
        check("ok    hestia_gate_core.py (already current)" in out,
              "second run did not report the engine as already current")
        check("wrote hestia_gate_" not in out,
              "second run rewrote engine files that were already current")


def test_dry_run_reports_the_engine_but_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        root, _home, hestia_home, env = build(tmp)
        rc, out = run(root, dict(env, DRY_RUN="1"))
        check(rc == 0, f"dry run exited {rc}: {out}")
        for f in ENGINE_FILES:
            check(f"would {f}" in out, f"dry run did not report it would install {f}")
        check(not os.path.exists(os.path.join(hestia_home, "shared")),
              "dry run created the shared engine directory")
        check(not os.path.exists(os.path.join(hestia_home, "current-build.json")),
              "dry run wrote the authority file")


def teardown_module(_module=None):
    """Deliver the accumulator to pytest as well as to the bare runner — see
    installer_derives_target_test.py, where a green-under-pytest that meant
    nothing was caught by tools/ci_selfexec_test.py."""
    assert not FAILS, "recorded failures: " + "; ".join(FAILS)


if __name__ == "__main__":
    test_shared_engine_is_installed_and_digested()
    test_tampered_installed_engine_file_is_detectable()
    test_rerun_is_idempotent_except_timestamps()
    test_dry_run_reports_the_engine_but_writes_nothing()
    for f in FAILS:
        print("FAIL", f)
    print(f"{'FAILED' if FAILS else 'ok'}: {len(FAILS)} failure(s)")
    sys.exit(1 if FAILS else 0)
