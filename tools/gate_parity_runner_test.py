#!/usr/bin/env python3
"""Behavioural pins for tools/gate_parity_runner.py.

Asserts the runner's parsing/normalization on CANNED shim outputs (the subprocess layer is
stubbed or fed a trivial fake shim) plus the stub daemon's wire shape. Live verdicts are NOT
asserted here — measuring them is the report's job (tools/gate_parity_report.json).

Run:  python3 tools/gate_parity_runner_test.py   (exit 1 on failure)
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import urllib.request

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("gate_parity_runner", HERE / "gate_parity_runner.py")
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
# Registered before exec: the runner's dataclasses resolve their string annotations
# (PEP 563) through sys.modules[__module__].
sys.modules["gate_parity_runner"] = runner
SPEC.loader.exec_module(runner)


def canned(rc, stdout="", stderr="", timed_out=False):
    return runner.ProbeResult(rc, stdout, stderr, timed_out)


# ── classify_cell: the exit-code seats (claude-code / kimi / codex share the contract) ──────
def test_allow_is_silent_exit_zero():
    cell = runner.classify_cell("claude-code", canned(0))
    assert (cell.verdict, cell.family, cell.degraded) == ("allow", "none", False), cell


def test_warn_is_exit_zero_with_warn_text():
    cell = runner.classify_cell("claude-code",
                                canned(0, stderr="hestia: warn [mrh.path] — noted\n"))
    assert cell.verdict == "warn" and cell.family == "scope" and not cell.degraded, cell


def test_core_deny_carries_its_rule_id_on_claude():
    cell = runner.classify_cell(
        "claude-code",
        canned(2, stderr="hestia: deny [egress.secret] — 'Read' touches a forbidden path\n"))
    assert (cell.verdict, cell.family, cell.rule) == ("deny", "scope", "egress.secret"), cell
    assert not cell.escalatable and not cell.degraded, cell


def test_kimi_scope_bracket_reads_as_scope_family():
    cell = runner.classify_cell(
        "kimi", canned(2, stderr="hestia: deny [scope] — 'Write' targets '/etc/x' outside "
                                 "your granted scope: it is outside the workspace\n"))
    assert (cell.verdict, cell.family) == ("deny", "scope"), cell


def test_gate_self_deny_is_governance_closure_and_escalatable():
    kimi_text = ("hestia: deny [gate-self] — 'Edit' would WRITE to the governance surface: "
                 "/r/plugins/_shared/hestia_gate_core.py (matched marker 'plugins/_shared'; "
                 "rule governance-closure-write; refused). Escalation stub-esc-1 is open — a "
                 "human decides out of band\n")
    cell = runner.classify_cell("kimi", canned(2, stderr=kimi_text))
    assert (cell.verdict, cell.family, cell.rule) == (
        "deny", "governance-closure", "governance-closure-write"), cell
    assert cell.escalatable and not cell.degraded, cell
    claude_text = ("hestia: deny [gate-self-access] — Write would WRITE to /r/x (matched "
                   "governance marker 'plugins/_shared'). ... is escalatable.\n")
    cell = runner.classify_cell("claude-code", canned(2, stderr=claude_text))
    assert (cell.verdict, cell.family) == ("deny", "governance-closure"), cell
    assert cell.escalatable, cell


def test_fail_closed_no_verdict_is_degraded_not_a_ruling():
    cell = runner.classify_cell(
        "claude-code",
        canned(2, stderr="hestia: no verdict [fail-closed] — the policy daemon did not "
                         "return a decision (daemon path failed; cause=refused).\n"))
    assert cell.verdict == "deny" and cell.degraded and cell.family == "degraded", cell


def test_config_refusal_is_degraded():
    cell = runner.classify_cell(
        "claude-code", canned(2, stderr="hestia: deny [config.unbacked] — HESTIA_HOME is not set\n"))
    assert cell.degraded, cell


def test_crash_exit_is_degraded():
    cell = runner.classify_cell("codex", canned(1, stderr="Traceback (most recent call last): ..."))
    assert cell.verdict == "deny" and cell.degraded and "exit 1" in cell.note, cell


def test_timeout_is_degraded_no_verdict():
    cell = runner.classify_cell("kimi", canned(None, timed_out=True))
    assert cell.degraded and "timeout" in cell.note, cell


def test_harness_timeout_unknown_is_degraded_not_a_verdict():
    # The exact wording main measured red-on-green with post-#1231: the shim failed closed
    # before reaching the gate, which must never classify as the seat's ruling (F1).
    cell = runner.classify_cell(
        "claude-code",
        canned(2, stderr="hestia: deny [gate.harness_timeout_unknown] — 'Bash' was not "
                         "judged: no registration found. Without the timeout its harness "
                         "enforces, the gate cannot finish before the harness kills it\n"))
    assert cell.verdict == "deny" and cell.degraded and cell.family == "degraded", cell


def test_one_gate_internal_error_dot_spelling_is_degraded():
    cell = runner.classify_cell(
        "kimi", canned(2, stderr="hestia: deny [gate.internal_error] — the common gate could "
                                 "not complete the decision: boom\n"))
    assert cell.degraded and cell.family == "degraded", cell


def test_seat_that_never_contacts_the_daemon_is_flagged_not_measured():
    # F1 close 2: a post-cutover seat whose shim fails closed before the wire leaves ZERO
    # requests in the stub log. Even if its wording drifts past _DEGRADED_RE, a seat that
    # never reached the daemon is a broken harness, and every one of its cells is degraded.
    orig_run_shim = runner.run_shim

    def silent_deny(*_a, **_k):
        return canned(2, stderr="hestia: deny [scope] — wording drift, looks like a verdict\n")

    runner.run_shim = silent_deny
    try:
        report = runner.run_matrix(["kimi"], list(runner.CORPUS)[:3], 5.0)
    finally:
        runner.run_shim = orig_run_shim
    assert report["seats_without_daemon_contact"] == ["kimi"], report.get(
        "seats_without_daemon_contact")
    for row in report["rows"]:
        seat = row["seats"]["kimi"]
        assert seat["degraded"] and seat["matches_expected"] is None, row
        assert not row["agreement"], row
    for key, cell in report["cells"].items():
        assert cell["degraded"] and "never contacted the stub daemon" in cell["note"], key


# ── classify_cell: gemini's two-channel contract ────────────────────────────────────────────
def test_gemini_policy_deny_is_stdout_json_at_exit_zero():
    payload = json.dumps({"decision": "deny",
                          "reason": "hestia: deny [scope] - 'write_file' targets ... outside"})
    cell = runner.classify_cell("gemini", canned(0, stdout=payload + "\n"))
    assert (cell.verdict, cell.family) == ("deny", "scope") and not cell.degraded, cell


def test_gemini_anomaly_channel_is_degraded():
    cell = runner.classify_cell(
        "gemini", canned(2, stderr="hestia: deny [gate] - the gate crashed (RuntimeError) "
                                   "and cannot vouch for this call; failing closed.\n"))
    assert cell.verdict == "deny" and cell.degraded, cell


def test_gemini_warn_is_exit_zero_stderr():
    cell = runner.classify_cell(
        "gemini", canned(0, stderr="hestia: warn [scope] - ... (warn-rollout: allowed)\n"))
    assert cell.verdict == "warn", cell


def test_gemini_allow_is_silent_exit_zero():
    cell = runner.classify_cell("gemini", canned(0))
    assert cell.verdict == "allow" and not cell.degraded, cell


def test_stdout_payload_deny_spellings_are_honoured_on_every_seat():
    # The preflight's _payload_denies pair, both spellings, as a belt on the lineage seats too.
    for payload in ({"permissionDecision": "deny"}, {"decision": "deny"}):
        cell = runner.classify_cell("claude-code", canned(0, stdout=json.dumps(payload)))
        assert cell.verdict == "deny", cell


# ── native event rendering ──────────────────────────────────────────────────────────────────
def test_render_event_gemini_native_vocabulary():
    ev = runner.render_event("gemini", "Edit",
                             {"file_path": "/r/x", "old_string": "a", "new_string": "b"},
                             "/r", "s-1")
    assert ev["hook_event_name"] == "BeforeTool", ev
    assert ev["tool_name"] == "replace", ev
    assert ev["tool_input"]["file_path"] == "/r/x", ev
    ev = runner.render_event("gemini", "Bash", {"command": "ls"}, "/r", "s-1")
    assert ev["tool_name"] == "run_shell_command", ev


def test_render_event_lineage_shapes():
    ev = runner.render_event("claude-code", "Read", {"file_path": "/r/x"}, "/r", "s-1")
    assert ev["hook_event_name"] == "PreToolUse" and "tool_use_id" in ev, ev
    ev = runner.render_event("kimi", "Read", {"file_path": "/r/x"}, "/r", "s-1")
    assert ev["hook_event_name"] == "PreToolUse" and "tool_call_id" in ev, ev
    ev = runner.render_event("codex", "Bash", {"command": "ls"}, "/r", "s-1")
    assert ev["hook_event_name"] == "PreToolUse" and "tool_use_id" in ev, ev


def test_placeholder_substitution_recurses():
    out = runner.render_value({"command": "ls {REPO} && cat {HOME}/.env > {SCRATCH}/{SELF}"},
                              {"{REPO}": "/r", "{SCRATCH}": "/s", "{HOME}": "/h",
                               "{SELF}": "kimi"})
    assert out["command"] == "ls /r && cat /h/.env > /s/kimi", out


# ── expected-value comparison ───────────────────────────────────────────────────────────────
def test_expected_parsing_and_alias():
    assert runner.parse_expected("allow") == ("allow", None)
    assert runner.parse_expected("deny:scope") == ("deny", "scope")
    assert runner.parse_expected("PIN") == ("PIN", None)
    # The documented alias: the corpus's settings-surface label compares as the closure family.
    assert runner.parse_expected("deny:gate-self") == ("deny", "governance-closure")


def test_cell_matching():
    deny_closure = runner.Cell("deny", "governance-closure-write", "governance-closure", True, False)
    assert runner.cell_matches_expected(deny_closure, "deny:governance-closure") is True
    assert runner.cell_matches_expected(deny_closure, "deny:scope") is False
    assert runner.cell_matches_expected(deny_closure, "allow") is False
    assert runner.cell_matches_expected(deny_closure, "PIN") is None
    degraded = runner.Cell("deny", "", "degraded", False, True)
    assert runner.cell_matches_expected(degraded, "deny:scope") is None


# ── the stub daemon's wire shape ────────────────────────────────────────────────────────────
def _post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.headers.get("mcp-session-id"), json.loads(resp.read().decode())


def test_stub_daemon_speaks_the_mechanisms_protocol():
    with runner.StubDaemon() as stub:
        sid, init = _post(stub.url, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                     "params": {}})
        assert "result" in init and sid, init
        # a notification gets an empty 200 and is logged
        req = urllib.request.Request(
            stub.url, data=json.dumps(
                {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}).encode(),
            method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200 and resp.read() == b""
        _sid, conn = _post(stub.url, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                      "params": {"name": "hestia_connect",
                                                 "arguments": {"plugin_id": "claude-code"}}})
        payload = conn["result"]["structuredContent"]
        assert payload["sessionId"].startswith("stub-session-"), payload
        # the same payload must ride content[0].text for the text-channel readers
        assert json.loads(conn["result"]["content"][0]["text"]) == payload
        _sid, qp = _post(stub.url, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                    "params": {"name": "hestia_query_policy",
                                               "arguments": {"action_id": "a1"}}})
        payload = qp["result"]["structuredContent"]
        assert payload["status"] == "decided" and payload["decision"] == "allow", payload
        _sid, claim = _post(stub.url, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                       "params": {"name": "hestia_gate_escalation_claim",
                                                  "arguments": {"marker": "m"}}})
        payload = claim["result"]["structuredContent"]
        assert payload["claimed"] is False and payload["escalation_id"], payload
        _sid, unk = _post(stub.url, {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                                     "params": {"name": "hestia_future_tool", "arguments": {}}})
        assert unk["result"]["structuredContent"]["ok"] is True
        summary = stub.summary()
        assert summary["initialize"] == 1 and summary["hestia_connect"] == 1, summary
        assert summary["notifications/initialized"] == 1, summary


# ── one smoke act against a trivial fake shim (the real subprocess path) ────────────────────
FAKE_SHIM = """\
import json, sys
ev = json.load(sys.stdin)
if ev.get("hook_event_name") != "PreToolUse":
    sys.exit(0)
cmd = (ev.get("tool_input") or {}).get("command") or ""
if "rm -rf" in cmd:
    sys.stderr.write("hestia: deny [scope] — fake shim refuses rm -rf\\n")
    sys.exit(2)
sys.exit(0)
"""


def test_smoke_act_against_a_fake_shim():
    with tempfile.TemporaryDirectory() as tmp:
        shim = Path(tmp) / "fake_shim.py"
        shim.write_text(FAKE_SHIM, encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith("HESTIA_")}
        deny_ev = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                   "tool_input": {"command": "rm -rf /tmp/x"}}
        result = runner.run_shim(shim, deny_ev, env, Path(tmp), 10)
        cell = runner.classify_cell("kimi", result)
        assert (cell.verdict, cell.family, cell.degraded) == ("deny", "scope", False), cell
        allow_ev = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                    "tool_input": {"command": "ls /tmp"}}
        cell = runner.classify_cell("kimi", runner.run_shim(shim, allow_ev, env, Path(tmp), 10))
        assert cell.verdict == "allow", cell


def test_seat_env_strips_ambient_and_pins_the_stub():
    saved = {k: os.environ.get(k) for k in ("HESTIA_ROLE", "HESTIA_ENDPOINT", "HESTIA_HOME")}
    os.environ["HESTIA_ROLE"] = "role:ambient-leak"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            env = runner.seat_env("kimi", Path(tmp), "http://127.0.0.1:9/mcp")
        assert "HESTIA_ROLE" not in env, "ambient HESTIA_* must not leak into a probe"
        assert env["HESTIA_ENDPOINT"] == "http://127.0.0.1:9/mcp", env
        assert env["HESTIA_HOME"] == env["HOME"] == tmp, env
        assert env["HESTIA_SHARED_DIR"] == runner.SHARED_DIR, env
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_corpus_is_loaded_and_unmodified_shape():
    assert len(runner.CORPUS) == 32, len(runner.CORPUS)
    for act in runner.CORPUS:
        act_id, act_class, tool, tool_input, expected, note = act
        assert isinstance(act_id, str) and tool_input is not None
        verdict, _fam = runner.parse_expected(expected)
        assert verdict in ("allow", "warn", "deny", "PIN"), expected


if __name__ == "__main__":
    test_allow_is_silent_exit_zero()
    test_warn_is_exit_zero_with_warn_text()
    test_core_deny_carries_its_rule_id_on_claude()
    test_kimi_scope_bracket_reads_as_scope_family()
    test_gate_self_deny_is_governance_closure_and_escalatable()
    test_fail_closed_no_verdict_is_degraded_not_a_ruling()
    test_config_refusal_is_degraded()
    test_crash_exit_is_degraded()
    test_timeout_is_degraded_no_verdict()
    test_harness_timeout_unknown_is_degraded_not_a_verdict()
    test_one_gate_internal_error_dot_spelling_is_degraded()
    test_seat_that_never_contacts_the_daemon_is_flagged_not_measured()
    test_gemini_policy_deny_is_stdout_json_at_exit_zero()
    test_gemini_anomaly_channel_is_degraded()
    test_gemini_warn_is_exit_zero_stderr()
    test_gemini_allow_is_silent_exit_zero()
    test_stdout_payload_deny_spellings_are_honoured_on_every_seat()
    test_render_event_gemini_native_vocabulary()
    test_render_event_lineage_shapes()
    test_placeholder_substitution_recurses()
    test_expected_parsing_and_alias()
    test_cell_matching()
    test_stub_daemon_speaks_the_mechanisms_protocol()
    test_smoke_act_against_a_fake_shim()
    test_seat_env_strips_ambient_and_pins_the_stub()
    test_corpus_is_loaded_and_unmodified_shape()
    print("ok: 26 gate-parity-runner checks")
