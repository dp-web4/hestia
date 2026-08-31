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
                outcome: str = "allow", reader: str = "json-hook-commands") -> None:
    plugin = repo / "plugins" / name
    hooks = plugin / "hooks"
    hooks.mkdir(parents=True)
    event = {"hook_event_name": "PreToolUse", "tool_name": "Read",
             "tool_input": {"file_path": "{scratch}"}}
    spec = {
        "install": {
            "registration": {"path": [f".{name}", "settings.json"], "reader": reader},
            "gate_probe": {"entry": "hooks/pre_tool_use.py", "events": [{"label": "read", "event": event}]},
        }
    }
    (plugin / "expects.json").write_text(json.dumps(spec), encoding="utf-8")
    if outcome == "allow":
        body = "import sys; sys.stdin.read(); raise SystemExit(0)\n"
    elif outcome == "payload-deny":
        body = "import json; print(json.dumps({'permissionDecision': 'deny'}))\n"
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


def test_registered_refusal_blocks_the_set_before_installation():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        repo, home = root / "repo", root / "home"
        make_member(repo, home, "alpha", outcome="deny")
        rows, good = gate_preflight.run_probes(repo, home, "http://example.invalid", "/tmp/probe", "/tmp/hold")
        assert not good
        assert rows[0]["status"] == "refused"
        assert rows[0]["member"] == "alpha"


def test_zero_exit_payload_deny_is_not_mistaken_for_an_allow():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        repo, home = root / "repo", root / "home"
        make_member(repo, home, "alpha", outcome="payload-deny")
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
        root = Path(raw)
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
        for declared in events:
            assert isinstance(declared.get("label"), str), f"{expects_path}: event has no label"
            assert isinstance(declared.get("event"), dict), f"{expects_path}: event has no payload"


if __name__ == "__main__":
    test_registered_candidate_must_allow_the_declared_probe()
    test_registered_refusal_blocks_the_set_before_installation()
    test_zero_exit_payload_deny_is_not_mistaken_for_an_allow()
    test_unregistered_member_is_not_a_deployment_requirement()
    test_bad_registration_is_unmeasured_not_absent()
    test_workspace_is_explicit_when_a_checkout_is_nested_in_a_worktree()
    test_every_shipped_gate_declares_its_own_probe_shape()
    print("ok: 7 gate-preflight checks")
