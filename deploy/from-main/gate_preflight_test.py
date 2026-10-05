#!/usr/bin/env python3
"""Behavioural pins for the per-member candidate gate preflight."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile


HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SPEC = importlib.util.spec_from_file_location("gate_preflight", HERE / "gate-preflight.py")
assert SPEC and SPEC.loader
gate_preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate_preflight)


def make_member(repo: Path, home: Path, name: str, *, registered: bool = True,
                outcome: str = "allow", reader: str = "json-hook-commands",
                advisory: bool = False, body: str | None = None,
                seat: str | None = None) -> None:
    plugin = repo / "plugins" / name
    hooks = plugin / "hooks"
    hooks.mkdir(parents=True)
    event = {"hook_event_name": "PreToolUse", "tool_name": "Read",
             "tool_input": {"file_path": "{scratch}"}}
    declared = {"label": "read", "event": event}
    if advisory:
        declared["advisory"] = True
    spec = {
        "install": {
            "registration": {"path": [f".{name}", "settings.json"], "reader": reader},
            "gate_probe": {"entry": "hooks/pre_tool_use.py", "events": [declared]},
        }
    }
    if seat is not None:
        spec["install"]["member"] = seat
    (plugin / "expects.json").write_text(json.dumps(spec), encoding="utf-8")
    if body is not None:
        pass
    elif outcome == "allow":
        body = "import sys; sys.stdin.read(); raise SystemExit(0)\n"
    elif outcome == "payload-deny":
        body = "import json; print(json.dumps({'permissionDecision': 'deny'}))\n"
    elif outcome == "decision-deny":
        body = "import json; print(json.dumps({'decision': 'deny'}))\n"
    else:
        body = "import sys; sys.stdin.read(); raise SystemExit(2)\n"
    (hooks / "pre_tool_use.py").write_text(body, encoding="utf-8")

    if registered:
        config = home / f".{name}" / "settings.json"
        config.parent.mkdir(parents=True)
        installed = home / f".{name}" / "hooks" / "pre_tool_use.py"
        config.write_text(json.dumps({"hooks": [{"command": f"python3 {installed}"}]}), encoding="utf-8")


def test_registered_candidate_must_allow_the_declared_probe():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        repo, home = root / "repo", root / "home"
        make_member(repo, home, "alpha")
        rows, good = gate_preflight.run_probes(repo, home, "http://example.invalid", "/tmp/probe", "/tmp/hold")
        assert good
        assert rows == [{"member": "alpha", "probe": "read", "status": "ok"}]


def _consumer_body() -> str:
    """A candidate that acts only under a supplied locator, the way a projection consumer does."""
    return ("import os, sys; sys.stdin.read()\n"
            "home = os.environ.get('HESTIA_HOME')\n"
            "if not home: sys.stderr.write('hestia: deny [config.unbacked] - HESTIA_HOME is not set\\n'); raise SystemExit(2)\n"
            "raise SystemExit(0)\n")


def test_a_projection_consumer_is_probed_under_the_launcher_env_not_the_deploy_units():
    """2026-09-05, CBP: the deploy unit carries HESTIA_HOME, the interactive launcher did not,
    and a consumer candidate answered the preflight it would have failed in the seat. The
    probe must run under the LAUNCHER's supply: without it the consumer is refused (and the
    seat keeps its old gate); with the locator on the registered hook line it is allowed."""
    import os
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        repo, home = root / "repo", root / "home"
        make_member(repo, home, "alpha", body=_consumer_body())
        # the deploy unit's own locator must NOT reach the probe
        saved = os.environ.get("HESTIA_HOME")
        os.environ["HESTIA_HOME"] = str(root / "deploy-units-home")
        try:
            rows, good = gate_preflight.run_probes(repo, home, "http://example.invalid", "/tmp/probe", "/tmp/hold")
            assert not good, rows
            assert rows[0]["status"] == "refused" and "config.unbacked" in rows[0]["reason"], rows
            # the launcher supplies it on the registered hook line -> the same candidate is allowed
            config = home / ".alpha" / "settings.json"
            installed = home / ".alpha" / "hooks" / "pre_tool_use.py"
            config.write_text(json.dumps({"hooks": [{"command": f'HESTIA_HOME="{root}/launcher-home" python3 {installed}'}]}),
                              encoding="utf-8")
            rows, good = gate_preflight.run_probes(repo, home, "http://example.invalid", "/tmp/probe", "/tmp/hold")
            assert good, rows
            assert rows == [{"member": "alpha", "probe": "read", "status": "ok"}]
            # and a `${HESTIA_HOME:-...}` default on the launcher line counts as the launcher's supply
            config.write_text(json.dumps({"hooks": [{"command": f'HESTIA_HOME="${{HESTIA_HOME:-{root}/launcher-home}}" python3 {installed}'}]}),
                              encoding="utf-8")
            del os.environ["HESTIA_HOME"]
            rows, good = gate_preflight.run_probes(repo, home, "http://example.invalid", "/tmp/probe", "/tmp/hold")
            assert good, rows
        finally:
            if saved is None:
                os.environ.pop("HESTIA_HOME", None)
            else:
                os.environ["HESTIA_HOME"] = saved


def test_registered_refusal_blocks_the_set_before_installation():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        repo, home = root / "repo", root / "home"
        make_member(repo, home, "alpha", outcome="deny")
        rows, good = gate_preflight.run_probes(repo, home, "http://example.invalid", "/tmp/probe", "/tmp/hold")
        assert not good
        assert rows[0]["status"] == "refused"
        assert rows[0]["member"] == "alpha"


def test_advisory_refusal_is_logged_and_does_not_block():
    """#767: a probe declared advisory keeps its row and loses its veto. The SAME deny that
    blocks above must not block here, and the row must say it was refused, not ok."""
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        repo, home = root / "repo", root / "home"
        make_member(repo, home, "alpha", outcome="deny", advisory=True)
        rows, good = gate_preflight.run_probes(repo, home, "http://example.invalid", "/tmp/probe", "/tmp/hold")
        assert good, rows
        assert rows == [{"member": "alpha", "probe": "read", "status": "advisory-refused",
                         "reason": "candidate exited 2"}]


def test_candidate_gate_is_probed_against_the_candidate_engine():
    """The first cycle after #747 merged probed the new gate against the still-installed
    3-module engine; the gate refused `no-shared-authority` and the preflight blocked the
    install that shipped the missing module. The candidate hook must see HESTIA_SHARED_DIR
    naming the checkout's own plugins/_shared, the tree about to be installed."""
    with tempfile.TemporaryDirectory() as raw:
        # RESOLVED, as production resolves it: the CLI entry passes `args.repo.resolve()` to
        # run_probes. Unresolved, this compared `/var/folders/...` (what run_probes was handed)
        # with `/private/var/folders/...` (the expectation), which on macOS -- where /var is a
        # symlink to /private/var -- never matched: the probe exited 2 and the test failed on
        # every Mac while passing on Linux, where /tmp has one spelling (McNugget, 2026-09-28).
        root = Path(raw).resolve()
        repo, home = root / "repo", root / "home"
        expected = str((repo / "plugins" / "_shared").resolve())
        body = ("import os, sys; sys.stdin.read()\n"
                f"raise SystemExit(0 if os.environ.get('HESTIA_SHARED_DIR') == {expected!r} else 2)\n")
        make_member(repo, home, "alpha", body=body)
        rows, good = gate_preflight.run_probes(repo, home, "http://example.invalid", "/tmp/probe", "/tmp/hold")
        assert good, rows
        assert rows == [{"member": "alpha", "probe": "read", "status": "ok"}]


def test_advisory_flag_must_be_literal_true():
    """A truthy-but-wrong spelling ("yes", 1) must NOT demote a blocking probe."""
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        repo, home = root / "repo", root / "home"
        make_member(repo, home, "alpha", outcome="deny")
        spec_path = repo / "plugins" / "alpha" / "expects.json"
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        spec["install"]["gate_probe"]["events"][0]["advisory"] = "yes"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        rows, good = gate_preflight.run_probes(repo, home, "http://example.invalid", "/tmp/probe", "/tmp/hold")
        assert not good
        assert rows[0]["status"] == "refused"


def test_zero_exit_payload_deny_is_not_mistaken_for_an_allow():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        repo, home = root / "repo", root / "home"
        make_member(repo, home, "alpha", outcome="payload-deny")
        rows, good = gate_preflight.run_probes(repo, home, "http://example.invalid", "/tmp/probe", "/tmp/hold")
        assert not good
        assert rows[0]["status"] == "refused"


def test_gemini_zero_exit_decision_deny_is_not_mistaken_for_an_allow():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        repo, home = root / "repo", root / "home"
        make_member(repo, home, "alpha", outcome="decision-deny")
        rows, good = gate_preflight.run_probes(repo, home, "http://example.invalid", "/tmp/probe", "/tmp/hold")
        assert not good
        assert rows[0]["status"] == "refused"


def test_unregistered_member_is_not_a_deployment_requirement():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        repo, home = root / "repo", root / "home"
        make_member(repo, home, "alpha", registered=False, outcome="deny")
        rows, good = gate_preflight.run_probes(repo, home, "http://example.invalid", "/tmp/probe", "/tmp/hold")
        assert good
        assert rows == [{"member": "alpha", "status": "not-registered"}]


def test_bad_registration_is_unmeasured_not_absent():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        repo, home = root / "repo", root / "home"
        make_member(repo, home, "alpha")
        config = home / ".alpha" / "settings.json"
        config.write_text("not json", encoding="utf-8")
        rows, good = gate_preflight.run_probes(repo, home, "http://example.invalid", "/tmp/probe", "/tmp/hold")
        assert not good
        assert rows[0]["status"] == "unmeasured"


def test_workspace_is_explicit_when_a_checkout_is_nested_in_a_worktree():
    with tempfile.TemporaryDirectory() as raw:
        # RESOLVED for the same reason as the candidate-engine test above: run_probes resolves
        # the workspace it exports (`(workspace or repo.parent).resolve()`), so the candidate
        # must compare against the resolved spelling. Unresolved, every Mac failed this test.
        root = Path(raw).resolve()
        repo, home, workspace = root / "nested" / "repo", root / "home", root / "workspace"
        workspace.mkdir()
        make_member(repo, home, "alpha")
        candidate = repo / "plugins" / "alpha" / "hooks" / "pre_tool_use.py"
        candidate.write_text(
            "import os, sys; sys.stdin.read(); raise SystemExit(0 if os.environ.get('HESTIA_WORKSPACE') == '" +
            str(workspace) + "' else 2)\n",
            encoding="utf-8",
        )
        rows, good = gate_preflight.run_probes(
            repo, home, "http://example.invalid", "/tmp/probe", "/tmp/hold", workspace=workspace,
        )
        assert good, rows
        assert rows[0]["status"] == "ok"


def test_every_shipped_gate_declares_its_own_probe_shape():
    """A new harness must contribute data, never inherit Claude's event schema."""
    for expects_path in sorted((REPO / "plugins").glob("*/expects.json")):
        spec = json.loads(expects_path.read_text(encoding="utf-8"))
        if not spec.get("gate"):
            continue
        probe = (spec.get("install") or {}).get("gate_probe")
        assert isinstance(probe, dict), f"{expects_path}: missing install.gate_probe"
        assert isinstance(probe.get("entry"), str), f"{expects_path}: probe has no entry"
        events = probe.get("events")
        assert isinstance(events, list) and events, f"{expects_path}: probe has no events"
        environment = probe.get("environment") or {}
        obsolete = {"HESTIA_PRE_FAIL_CLOSED", "HESTIA_PRE_NO_FALLBACK"} & set(environment)
        assert not obsolete, f"{expects_path}: obsolete fail-closed switches: {sorted(obsolete)}"
        for declared in events:
            assert isinstance(declared.get("label"), str), f"{expects_path}: event has no label"
            assert isinstance(declared.get("event"), dict), f"{expects_path}: event has no payload"


def test_a_projection_consuming_candidate_is_probed_against_the_candidate_engine():
    """#1171: the gate loads $HESTIA_HOME/seats/<member>.env at import and exports every key
    OVER the probe environment, so the HESTIA_SHARED_DIR env pin alone pairs the candidate gate
    with the INSTALLED engine (measured 2026-09-29 on CBP and Legion: #1149's correlation_key
    deploy refused on every cycle). The probe must run under a throwaway seat home whose
    projection names the candidate tree. The stub below reproduces the loader's override."""
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw).resolve()
        repo, home = root / "repo", root / "home"
        launcher_home = root / "launcher-home"
        # the seat's real rendered projection names the INSTALLED engine
        seats = launcher_home / "seats"
        seats.mkdir(parents=True)
        (seats / "alpha.env").write_text(
            f"# member: alpha\nHESTIA_HOME={launcher_home}\n"
            f"HESTIA_SHARED_DIR={root / 'installed-shared'}\n",
            encoding="utf-8",
        )
        # the candidate loads its projection at import and exports it over the probe env,
        # exactly as _load_projection does, then answers by the engine it was paired with
        expected = str((repo / "plugins" / "_shared").resolve())
        body = (
            "import os, sys; sys.stdin.read()\n"
            "for line in open(os.path.join(os.environ['HESTIA_HOME'], 'seats', 'alpha.env')):\n"
            "    line = line.strip()\n"
            "    if line and not line.startswith('#') and '=' in line:\n"
            "        k, v = line.split('=', 1); os.environ[k] = v\n"
            f"raise SystemExit(0 if os.environ.get('HESTIA_SHARED_DIR') == {expected!r} else 2)\n"
        )
        make_member(repo, home, "alpha", body=body)
        config = home / ".alpha" / "settings.json"
        installed = home / ".alpha" / "hooks" / "pre_tool_use.py"
        config.write_text(json.dumps({"hooks": [{"command": f'HESTIA_HOME="{launcher_home}" python3 {installed}'}]}),
                          encoding="utf-8")
        rows, good = gate_preflight.run_probes(repo, home, "http://example.invalid", "/tmp/probe", "/tmp/hold")
        assert good, rows
        assert rows == [{"member": "alpha", "probe": "read", "status": "ok"}]


def test_the_throwaway_projection_is_keyed_by_the_seat_id_not_the_plugin_dir():
    """kimi's plugin dir is `kimi` but its seat (install.member) and projection are `kimi-code`.
    Keyed by the dir, the throwaway lookup missed `seats/kimi.env`, the probe kept the real
    home, and the candidate loaded the INSTALLED engine (CBP 2026-10-05T22:20Z: kimi refused
    `gate.bootstrap_unavailable`, codex and gemini -- whose names match -- passed)."""
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw).resolve()
        repo, home = root / "repo", root / "home"
        launcher_home = root / "launcher-home"
        seats = launcher_home / "seats"
        seats.mkdir(parents=True)
        (seats / "beta-code.env").write_text(
            f"HESTIA_HOME={launcher_home}\nHESTIA_SHARED_DIR={root / 'installed-shared'}\n",
            encoding="utf-8",
        )
        expected = str((repo / "plugins" / "_shared").resolve())
        body = (
            "import os, sys; sys.stdin.read()\n"
            "for line in open(os.path.join(os.environ['HESTIA_HOME'], 'seats', 'beta-code.env')):\n"
            "    line = line.strip()\n"
            "    if line and '=' in line:\n"
            "        k, v = line.split('=', 1); os.environ[k] = v\n"
            f"raise SystemExit(0 if os.environ.get('HESTIA_SHARED_DIR') == {expected!r} else 2)\n"
        )
        make_member(repo, home, "beta", body=body, seat="beta-code")
        config = home / ".beta" / "settings.json"
        installed = home / ".beta" / "hooks" / "pre_tool_use.py"
        config.write_text(json.dumps({"hooks": [{"command": f'HESTIA_HOME="{launcher_home}" python3 {installed}'}]}),
                          encoding="utf-8")
        rows, good = gate_preflight.run_probes(repo, home, "http://example.invalid", "/tmp/probe", "/tmp/hold")
        assert good, rows
        assert rows == [{"member": "beta", "probe": "read", "status": "ok"}]


if __name__ == "__main__":
    test_registered_candidate_must_allow_the_declared_probe()
    test_registered_refusal_blocks_the_set_before_installation()
    test_advisory_refusal_is_logged_and_does_not_block()
    test_advisory_flag_must_be_literal_true()
    test_candidate_gate_is_probed_against_the_candidate_engine()
    test_zero_exit_payload_deny_is_not_mistaken_for_an_allow()
    test_gemini_zero_exit_decision_deny_is_not_mistaken_for_an_allow()
    test_unregistered_member_is_not_a_deployment_requirement()
    test_bad_registration_is_unmeasured_not_absent()
    test_workspace_is_explicit_when_a_checkout_is_nested_in_a_worktree()
    test_every_shipped_gate_declares_its_own_probe_shape()
    test_a_projection_consumer_is_probed_under_the_launcher_env_not_the_deploy_units()
    test_a_projection_consuming_candidate_is_probed_against_the_candidate_engine()
    test_the_throwaway_projection_is_keyed_by_the_seat_id_not_the_plugin_dir()
    print("ok: 13 gate-preflight checks")
