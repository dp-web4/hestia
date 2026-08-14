#!/usr/bin/env python3
"""Sprint E acceptance tests — one society-safety transport, one deny recorder.

Runs against the PATCHED copies in build/ (setup_build.py + work edits + sync_back.py):
  build/plugins/_shared/          patched mechanism (+ pristine core + its 18-test suite)
  build/plugins/codex/hooks/      patched codex hook + codex_gate_boundary_test.py
  build/plugins/claude-code/hooks/ patched claude hook

Arms (per the Sprint E design requirements):
  (a) mechanism accepts lowercase "bash" and populates begin_action `target` for a
      codex-shaped event (the one-character audit hole);
  (b) SafetyVerdict.kind present, populated per decision, backward-compatible;
  (c) the unified deny recorder always carries target + verdict_available, and falls back
      to the per-shim diagnostic log on witness failure (never raising, never silent);
  (d) patched codex hook: no subprocess import, no CLAUDE_PRE, py_compile green;
  (e) patched claude hook: no private McpHttp class, py_compile green;
  (f) codex_gate_boundary_test.py against the patched codex copy: the transport-owned
      arms pass (the self-protection arms are Sprint B's and stay red until B lands).

check() RAISES so pytest sees each case; the __main__ runner collects.
"""
import importlib.util
import json
import os
import py_compile
import subprocess
import sys
import tempfile

HOOK = "pre_" + "tool_use.py"  # keep the verbatim marker out of shell-visible text
E = os.path.dirname(os.path.abspath(__file__))
_PLUGINS = os.path.dirname(E)


def _pick(in_repo, staged):
    # Prefer the live repo tree (this file at plugins/_shared/ post-apply); the drafting
    # build/ staging remains for out-of-tree verification.
    return in_repo if os.path.isfile(in_repo) else staged


SHARED = E if os.path.isfile(os.path.join(E, "hestia_gate_mechanism.py")) \
    else os.path.join(E, "build", "plugins", "_shared")
CODEX_HOOK = _pick(os.path.join(_PLUGINS, "codex", "hooks", HOOK),
                   os.path.join(E, "build", "plugins", "codex", "hooks", HOOK))
CLAUDE_HOOK = _pick(os.path.join(_PLUGINS, "claude-code", "hooks", HOOK),
                    os.path.join(E, "build", "plugins", "claude-code", "hooks", HOOK))
BOUNDARY = _pick(os.path.join(_PLUGINS, "codex", "hooks", "codex_gate_boundary_test.py"),
                 os.path.join(E, "build", "plugins", "codex", "hooks",
                              "codex_gate_boundary_test.py"))

spec = importlib.util.spec_from_file_location(
    "hestia_gate_mechanism", os.path.join(SHARED, "hestia_gate_mechanism.py"))
m = importlib.util.module_from_spec(spec)
sys.modules["hestia_gate_mechanism"] = m
spec.loader.exec_module(m)


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {detail}")


class RecordingClient:
    """Scripted MCP client that records every call_tool (name, args)."""

    def __init__(self, connect=None, begin=None, policy=None, raise_on=None):
        self.connect = {"sessionId": "s1"} if connect is None else connect
        self.begin = {"actionId": "a1"} if begin is None else begin
        self.policy = {"status": "decided", "decision": "allow"} if policy is None else policy
        self.raise_on = raise_on
        self.calls = []

    def initialize(self):
        return {"result": {}}

    def initialized(self):
        pass

    def call_tool(self, name, args):
        self.calls.append((name, args))
        if self.raise_on == name:
            raise RuntimeError("boom")
        payload = {"hestia_connect": self.connect,
                   "hestia_begin_action": self.begin,
                   "hestia_query_policy": self.policy,
                   "hestia_witness_decision": {"ok": True}}[name]
        return {"result": {"structuredContent": payload}}

    def args_of(self, name):
        return [a for n, a in self.calls if n == name]


def _drive(fake, event):
    m._discover_endpoint = lambda: "http://fake/mcp"
    m._McpHttp = lambda ep, deadline: fake
    return m.query_society_safety(event, plugin_id="codex", host_agent="codex")


# ---- (a) case-insensitive shell tool names → populated target ----
def test_lowercase_bash_extract_target():
    for name in ("bash", "Bash", "shell", "Shell", "BASH"):
        check(f"extract-{name}",
              m._extract_target({"command": "rm -rf /x"}, name) == "rm", name)
    check("non-shell-still-none", m._extract_target({"command": "rm x"}, "bashful") is None,
          "substring/prefix names must NOT be treated as shell")
    check("non-str-tool", m._extract_target({"command": "rm x"}, None) is None, "None tool_name")


def test_codex_shaped_event_populates_begin_target():
    fake = RecordingClient()
    v = _drive(fake, {"tool_name": "bash", "tool_input": {"command": "git push origin HEAD"}})
    check("allow", v.allow and v.decided, str(v))
    begins = fake.args_of("hestia_begin_action")
    check("begin-called", len(begins) == 1, str(fake.calls))
    check("target-populated", begins[0].get("target") == "git",
          f"codex-shaped event must carry a non-empty target; got {begins[0].get('target')!r}")


# ---- (b) SafetyVerdict.kind — present, populated, backward-compatible ----
def test_kind_field_populated():
    cases = [
        ({"status": "decided", "decision": "allow"}, "allow", True),
        ({"status": "decided", "decision": "warn", "reason": "r"}, "warn", True),
        ({"status": "decided", "decision": "deny", "enforced": True, "reason": "r"}, "deny", False),
        ({"status": "decided", "decision": "deny", "enforced": False, "reason": "r"}, "warn", True),
    ]
    for policy, want_kind, want_allow in cases:
        v = _drive(RecordingClient(policy=policy), {"tool_name": "Bash",
                                                    "tool_input": {"command": "x"}})
        check(f"kind-{want_kind}", v.kind == want_kind, f"{policy} -> {v}")
        check(f"allow-{want_kind}", v.allow is want_allow, f"{policy} -> {v}")
    audit = _drive(RecordingClient(policy=cases[3][0]), {"tool_name": "Bash",
                                                         "tool_input": {"command": "x"}})
    check("audit-message-distinct", "would-deny (audit-only)" in audit.message, audit.message)


def test_kind_none_on_no_verdict_and_backcompat():
    m._discover_endpoint = lambda: None
    v = m.query_society_safety({"tool_name": "Bash", "tool_input": {}},
                               plugin_id="codex", host_agent="codex")
    check("no-verdict-kind", v.kind == "none" and not v.allow and not v.decided, str(v))
    # Backward compatibility: the pre-extension constructor shape still works, defaults hold.
    old_shape = m.SafetyVerdict(allow=False, decided=False, message="x")
    check("default-kind", old_shape.kind == "none", str(old_shape))
    check("default-action-id", old_shape.action_id is None, str(old_shape))
    # allow/decided truthiness contract unchanged by the new fields.
    check("truthiness", (not old_shape.allow) and (not old_shape.decided), str(old_shape))


def test_action_id_attached_on_decided():
    v = _drive(RecordingClient(), {"tool_name": "Write", "tool_input": {"file_path": "/tmp/x"}})
    check("action-id", v.action_id == "a1", str(v))


# ---- (c) the ONE deny recorder ----
def test_unified_recorder_carries_target_and_verdict_available():
    fake = RecordingClient()
    ok = m.witness_decision_unified(
        fake, plugin_id="codex", decision="deny", rule="scope: out of MRH",
        tool_name="bash", target="rm", session_id="sess-1",
        verdict_available=False, attempted_summary="bash: rm -rf /x")
    check("delivered", ok is True, "recorder should report delivery on a healthy client")
    wit = fake.args_of("hestia_witness_decision")
    check("witness-called", len(wit) == 1, str(fake.calls))
    check("carries-target", wit[0].get("target") == "rm", str(wit))
    check("carries-verdict-available", wit[0].get("verdict_available") is False, str(wit))
    check("carries-plugin", wit[0].get("plugin_id") == "codex", str(wit))
    check("carries-session", wit[0].get("session_id") == "sess-1", str(wit))


def test_unified_recorder_falls_back_to_diagnostic_log():
    with tempfile.TemporaryDirectory() as tmp:
        old = os.environ.get("HESTIA_HOME")
        os.environ["HESTIA_HOME"] = tmp
        try:
            failing = RecordingClient(raise_on="hestia_witness_decision")
            ok = m.witness_decision_unified(
                failing, plugin_id="codex", decision="deny", rule="scope: out of MRH",
                tool_name="bash", target="rm", session_id="sess-1",
                verdict_available=True, attempted_summary="bash: rm -rf /x")
            check("not-delivered", ok is False, "failing client must report False")
            log = os.path.join(tmp, "telemetry", "gate-denies-codex.jsonl")
            check("fallback-exists", os.path.isfile(log), f"missing {log}")
            row = json.loads(open(log, encoding="utf-8").readlines()[-1])
            check("fallback-target", row.get("target") == "rm", str(row))
            check("fallback-verdict-available", row.get("verdict_available") is True, str(row))
            check("fallback-names-failure", "witness_delivery_failed" in row, str(row))
            # No-client path (endpoint down) must also land in the log, not vanish.
            m._discover_endpoint = lambda: None
            ok2 = m.witness_decision_unified(
                None, plugin_id="codex", decision="deny", rule="r", tool_name="Write",
                target="/tmp/x", session_id=None, verdict_available=False,
                attempted_summary="Write -> /tmp/x")
            check("no-endpoint-fallback", ok2 is False, "no endpoint must fall back")
            rows = open(log, encoding="utf-8").readlines()
            check("two-rows", len(rows) == 2, f"{len(rows)} rows")
        finally:
            if old is None:
                os.environ.pop("HESTIA_HOME", None)
            else:
                os.environ["HESTIA_HOME"] = old


def test_unified_recorder_never_raises():
    class Hostile:
        def call_tool(self, *a, **k):
            raise MemoryError("worst case")
    # Even with a hostile client AND an unwritable fallback home, the recorder must not raise.
    old = os.environ.get("HESTIA_HOME")
    os.environ["HESTIA_HOME"] = "/dev/null/impossible"
    try:
        ok = m.witness_decision_unified(
            Hostile(), plugin_id="codex", decision="deny", rule="r", tool_name="t",
            target=None, session_id=None, verdict_available=False, attempted_summary="")
        check("no-raise", ok is False, "must swallow and report False")
    finally:
        if old is None:
            os.environ.pop("HESTIA_HOME", None)
        else:
            os.environ["HESTIA_HOME"] = old


# ---- (d) patched codex hook — spawn machinery deleted ----
def test_codex_copy_no_spawn_machinery():
    src = open(CODEX_HOOK, encoding="utf-8").read()
    check("no-subprocess-import", "import subprocess" not in src,
          "gate 2 must be in-process; codex had no other subprocess use")
    check("no-claude-pre", "CLAUDE_PRE" not in src, "spawn config constant must be gone")
    check("no-society-gate-env", "HESTIA_SOCIETY_GATE" not in src,
          "the spawn-target env knob must be gone with the spawn")
    check("uses-mechanism", "query_society_safety" in src, "in-process call missing")
    check("uses-unified-recorder", "witness_decision_unified" in src, "ONE deny recorder missing")
    py_compile.compile(CODEX_HOOK, doraise=True)


# ---- (e) patched claude hook — private client deleted ----
def test_claude_copy_no_private_client():
    src = open(CLAUDE_HOOK, encoding="utf-8").read()
    check("no-private-class", "class McpHttp" not in src, "private client class must be gone")
    check("no-private-poller", "def poll_policy" not in src, "private wait-poller must be gone")
    check("no-private-sse", "def parse_json_or_sse" not in src, "private SSE parser must be gone")
    check("uses-mechanism", "query_society_safety" in src, "in-process call missing")
    py_compile.compile(CLAUDE_HOOK, doraise=True)


# ---- (f) boundary test against the patched codex copy ----
# Transport-owned arms (Sprint E) must pass; the self-protection arms are Sprint B's
# codex work (codex has NO self-protection layer yet — PRD §5) and stay red until B lands.
E_OWNED = {
    "test_ordinary_write_uses_policy_path",
    "test_hooks_dir_only_names_do_not_overreach",
    "test_ordinary_write_daemon_down_fails_closed",
}
B_OWNED = {
    "test_gate_file_write_refused_locally",
    "test_apply_patch_to_gate_refused_locally",
    "test_gate_file_bash_write_refused_locally",
    "test_approved_gate_write_proceeds_to_policy",
    "test_shared_mechanism_write_refused_anywhere",
    "test_gate_file_read_allowed_and_witnessed",
    "test_gate_write_refused_with_daemon_down",
}


def test_boundary_transport_arms_pass():
    p = subprocess.run([sys.executable, BOUNDARY], capture_output=True, text=True, timeout=300)
    passed = {ln.split()[1] for ln in p.stdout.splitlines() if ln.startswith("ok ")}
    failed = {ln.split()[1] for ln in p.stdout.splitlines() if ln.startswith("FAIL ")}
    check("boundary-ran", passed or failed, p.stdout + p.stderr)
    missing = E_OWNED - passed
    check("transport-arms-pass", not missing, f"E-owned arms red: {missing}\n{p.stdout}")
    # Red B-owned arms are EXPECTED pre-B; a green one is a bonus, not a failure. But an arm
    # neither passing nor failing means the test file changed shape — surface that.
    unaccounted = (E_OWNED | B_OWNED) - passed - failed
    check("all-arms-accounted", not unaccounted, f"unaccounted: {unaccounted}")
    print(f"    boundary: {len(passed)} passed ({sorted(passed)}), "
          f"{len(failed & B_OWNED)} B-owned red (expected pre-B)")


ALL = [
    test_lowercase_bash_extract_target,
    test_codex_shaped_event_populates_begin_target,
    test_kind_field_populated,
    test_kind_none_on_no_verdict_and_backcompat,
    test_action_id_attached_on_decided,
    test_unified_recorder_carries_target_and_verdict_available,
    test_unified_recorder_falls_back_to_diagnostic_log,
    test_unified_recorder_never_raises,
    test_codex_copy_no_spawn_machinery,
    test_claude_copy_no_private_client,
    test_boundary_transport_arms_pass,
]

if __name__ == "__main__":
    print("Sprint E — one transport, one deny recorder")
    failed = []
    for t in ALL:
        try:
            t()
            print("PASS", t.__name__)
        except Exception as e:  # noqa: BLE001 — collect, don't stop
            failed.append(t.__name__)
            print("FAIL", t.__name__, "::", e)
    print()
    if failed:
        print(f"FAILURES: {failed}")
        sys.exit(1)
    print(f"OK — {len(ALL)} tests")
