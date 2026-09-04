#!/usr/bin/env python3
"""Contract tests for hestia_single_gate.

These tests pin the properties the consolidation exists to create:
  * one decision sequence for every seat;
  * no per-seat runtime enforcement mode;
  * closure writes cannot bypass the claim path;
  * daemon loss takes one common degraded posture;
  * society no-verdict fails closed but is not member conduct;
  * EVERY final decision, including allow, takes the common witness path.
"""
import os
import sys
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hestia_single_gate as g  # noqa: E402


class CV:
    def __init__(self, classification="none", rule=None, marker=None, resource=None):
        self.classification = classification
        self.rule = rule
        self.marker = marker
        self.resource = resource


@contextmanager
def patched(**items):
    saved = []
    try:
        for dotted, value in items.items():
            obj_name, attr = dotted.split("__", 1)
            obj = getattr(g, obj_name)
            saved.append((obj, attr, getattr(obj, attr)))
            setattr(obj, attr, value)
        yield
    finally:
        for obj, attr, value in reversed(saved):
            setattr(obj, attr, value)


def profile(member="claude-code"):
    return g.GateProfile(
        member_id=member,
        identity_path="/nonexistent/identity.json",
        home_markers=("/home/member",),
        host_agent=member,
        client_name="hestia-test-gate",
        gate_path="/installed/pre_tool_use.py",
    )


def event(tool="Read", tool_input=None):
    return g.GateEvent(
        tool=tool,
        tool_input=tool_input or {"file_path": "/tmp/x"},
        cwd="/tmp",
        session_id="host-s1",
        tool_use_id="tu-1",
        raw={"hook_event_name": "PreToolUse"},
    )


def live_snapshot(role="role:constellation:member"):
    return {
        "in_scope": ["*"],
        "source": "daemon-live",
        "role": role,
        "generation": 1,
        "expires_at": None,
    }


def install_common_fakes(records, *, snapshot=None, local=None, safety=None, closure_v=None):
    if snapshot is None:
        snapshot = live_snapshot()
    if local is None:
        local = g.core.ALLOW
    if safety is None:
        safety = g.mechanism.SafetyVerdict(True, True, "ok", kind="allow", action_id="a1")
    if closure_v is None:
        closure_v = CV()

    return patched(
        closure__classify=lambda *a, **k: closure_v,
        mechanism__fetch_policy_snapshot=lambda *a, **k: snapshot,
        core__resolve_agent_policy=lambda *a, **k: g.core.AgentPolicy(
            member_id=a[0].member_id, scope=("*",), source="vault"),
        core__detect_workspace=lambda p: "/workspace",
        core__evaluate=lambda *a, **k: local,
        mechanism__query_society_safety=lambda *a, **k: safety,
        mechanism__witness_decision_unified=lambda _c, **kw: records.append(kw) or True,
        mechanism__tally_scope=lambda *a, **k: None,
        mechanism__role_bridge=lambda **k: k.get("snapshot_role") or "role:constellation:member",
        mechanism__witness_gate_self=lambda *a, **k: True,
        mechanism__claim_self_write=lambda *a, **k: ("approved", "approved", None, None),
    )


def test_allow_is_witnessed():
    records = []
    with install_common_fakes(records):
        d = g.decide(event("Read"), profile())
    assert d.decision == "allow"
    assert len(records) == 1, records
    assert records[0]["decision"] == "allow"
    assert records[0]["rule"] == "gate.allow"


def test_same_event_same_verdict_across_four_profiles():
    decisions = []
    for member in ("claude-code", "kimi-code", "codex", "gemini"):
        records = []
        with install_common_fakes(records, local=g.core._deny("mrh.path", "outside")):
            decisions.append(g.decide(event("Write"), profile(member)))
    assert {(d.decision, d.rule, d.reason) for d in decisions} == {
        ("deny", "mrh.path", "outside")
    }


def test_per_seat_mode_environment_cannot_change_law():
    names = (
        "HESTIA_CODEX_GATE_MODE", "HESTIA_KIMI_GATE_MODE",
        "HESTIA_GEMINI_GATE_MODE", "HESTIA_CLAUDE_GATE_MODE",
    )
    old = {n: os.environ.get(n) for n in names}
    try:
        for n in names:
            os.environ[n] = "warn"
        records = []
        with install_common_fakes(records, local=g.core._deny("mrh.path", "outside")):
            d = g.decide(event("Write"), profile("codex"))
        assert d.decision == "deny"
        assert profile("codex").core_profile().mode_env == ""
    finally:
        for n, v in old.items():
            if v is None:
                os.environ.pop(n, None)
            else:
                os.environ[n] = v


def test_closure_write_requires_claim_and_records_refusal():
    records = []
    gate_events = []
    with install_common_fakes(records, closure_v=CV(
            "write", "governance-closure-write", "plugins/_shared", "/x/plugins/_shared/a.py")):
        with patched(
            mechanism__claim_self_write=lambda *a, **k: (
                "escalated", "refused", "esc-1", "hestia gate approve esc-1"),
            mechanism__witness_gate_self=lambda *a, **k: gate_events.append((a, k)) or True,
        ):
            d = g.decide(event("Write"), profile())
    assert d.decision == "deny" and d.rule == "gate.self_access"
    assert gate_events and gate_events[0][0][0] == "gate_self_access"
    assert records and records[-1]["decision"] == "deny"


def test_closure_approved_write_still_runs_ordinary_gate():
    records = []
    with install_common_fakes(records, closure_v=CV(
            "write", "governance-closure-write", "plugins/_shared", "/x/plugins/_shared/a.py"),
            local=g.core._deny("mrh.path", "ordinary gate still applies")):
        d = g.decide(event("Write"), profile())
    assert d.decision == "deny" and d.rule == "mrh.path"


def test_degraded_write_denies_as_infrastructure_and_is_witnessed():
    records = []
    with install_common_fakes(records):
        with patched(
            mechanism__fetch_policy_snapshot=lambda *a, **k: None,
            core__degraded_verdict=lambda *a, **k: g.core._deny(
                "gate.degraded", "daemon absent"),
        ):
            d = g.decide(event("Write"), profile())
    assert d.decision == "deny" and d.rule == "gate.degraded"
    assert d.anomaly and not d.verdict_available
    assert records[-1]["verdict_available"] is False


def test_degraded_read_allows_and_is_witnessed_without_society_query():
    records = []
    called = {"society": 0}
    with install_common_fakes(records):
        with patched(
            mechanism__fetch_policy_snapshot=lambda *a, **k: None,
            core__degraded_verdict=lambda *a, **k: g.core.ALLOW,
            core__record_gate_unavailable=lambda *a, **k: None,
            mechanism__query_society_safety=lambda *a, **k: called.__setitem__(
                "society", called["society"] + 1),
        ):
            d = g.decide(event("Read"), profile())
    assert d.decision == "allow" and d.anomaly and not d.verdict_available
    assert called["society"] == 0
    assert records[-1]["decision"] == "allow"
    assert records[-1]["verdict_available"] is False


def test_degraded_innate_secret_is_a_real_verdict():
    records = []
    with install_common_fakes(records):
        with patched(
            mechanism__fetch_policy_snapshot=lambda *a, **k: None,
            core__degraded_verdict=lambda *a, **k: g.core._deny(
                "egress.secret", "secret", innate=True),
        ):
            d = g.decide(event("Read"), profile())
    assert d.decision == "deny" and d.rule == "egress.secret"
    assert d.verdict_available and not d.anomaly
    assert records[-1]["verdict_available"] is True


def test_society_no_verdict_fails_closed_not_conduct():
    records = []
    safety = g.mechanism.SafetyVerdict(False, False, "timeout", cause="timeout", kind="none")
    with install_common_fakes(records, safety=safety):
        d = g.decide(event("Bash", {"command": "echo hi"}), profile())
    assert d.decision == "deny" and d.rule == "society.unreachable"
    assert d.anomaly and not d.verdict_available
    assert records[-1]["verdict_available"] is False


def test_society_warn_is_law_supplied_not_seat_selected():
    records = []
    safety = g.mechanism.SafetyVerdict(True, True, "careful", kind="warn", action_id="a2")
    with install_common_fakes(records, safety=safety):
        d = g.decide(event("Bash", {"command": "echo hi"}), profile())
    assert d.decision == "warn" and not d.blocks
    assert d.rule == "society.safety.warn"
    assert records[-1]["decision"] == "warn"


def test_unexpected_internal_error_fails_closed_and_is_witnessed():
    records = []
    with install_common_fakes(records):
        with patched(closure__classify=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))):
            d = g.decide(event("Read"), profile())
    assert d.decision == "deny" and d.rule == "gate.internal_error"
    assert d.anomaly and not d.verdict_available
    assert records[-1]["rule"] == "gate.internal_error"


def test_gate_artifact_digest_is_full_sha256():
    digest = g.gate_artifact_digest()
    assert len(digest) == 64
    int(digest, 16)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"PASS: {len(tests)} single-gate contract tests")
