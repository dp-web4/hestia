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
  (c) ONE decision recorder: since one-gate stage C that is `record_decision` (the Sprint E
      refusal recorder is retired; its arms live in tools/decision_witness_contract_test.py);
  (d) codex hook: no subprocess import, no CLAUDE_PRE, py_compile green — and since stage C
      no transport or recorder of its own: it delegates to the common gate;
  (e) claude hook: no private McpHttp class, py_compile green — and the same delegation;
  (f) retired: the codex boundary arms run on all four seats in seat_gate_boundary_test.py.

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

# Staging seams (unset in the repo and in CI), shared with the one-gate contract suites.
_OVERLAY = json.loads(os.environ.get("HESTIA_CONTRACT_OVERLAY") or "{}")
_SHIMS = json.loads(os.environ.get("HESTIA_CONTRACT_SHIMS") or "{}")
CODEX_HOOK = _SHIMS.get("codex", CODEX_HOOK)
CLAUDE_HOOK = _SHIMS.get("claude-code", CLAUDE_HOOK)
spec = importlib.util.spec_from_file_location(
    "hestia_gate_mechanism",
    _OVERLAY.get("hestia_gate_mechanism") or os.path.join(SHARED, "hestia_gate_mechanism.py"))
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
    # The target is the COMMAND, not its first word (2026-09-08: the feed lost every
    # argument when the outcome row began inheriting this target — see `_shell_target`).
    for name in ("bash", "Bash", "shell", "Shell", "BASH"):
        check(f"extract-{name}",
              m._extract_target({"command": "rm -rf /x"}, name) == "rm -rf /x", name)
    check("non-shell-still-none", m._extract_target({"command": "rm x"}, "bashful") is None,
          "substring/prefix names must NOT be treated as shell")
    check("non-str-tool", m._extract_target({"command": "rm x"}, None) is None, "None tool_name")
    # Paths are untouched: only the shell target is a command.
    check("path-target-unchanged",
          m._extract_target({"file_path": "/w/auth=1/x"}, "Read") == "/w/auth=1/x")


def test_shell_target_is_masked_and_bounded():
    # `--token VALUE` masks the next token; `PASSWORD=VALUE` keeps the key, masks the value.
    t = m._extract_target({"command": "curl --token abc123 -H x PASSWORD=hunter2 https://h"}, "Bash")
    check("space-flag-value-masked", "abc123" not in t and "--token ***" in t, t)
    check("assignment-value-masked", "hunter2" not in t and "PASSWORD=***" in t, t)
    check("the-rest-stays-legible", t.startswith("curl --token *** -H x") and "https://h" in t, t)
    # A bare flag whose next token is another flag masks nothing.
    t = m._extract_target({"command": "cmd --token --verbose"}, "Bash")
    check("flag-followed-by-flag-not-masked", t == "cmd --token --verbose", t)
    # Bounded at TARGET_MAX with a visible cut; whitespace collapses like the daemon's pass.
    long = "echo " + "x" * 500
    t = m._extract_target({"command": long}, "Bash")
    check("bounded-with-visible-cut", len(t) == m.TARGET_MAX and t.endswith("..."), str(len(t)))
    t = m._extract_target({"command": "cat > f <<'EOF'\nline one\nEOF"}, "Bash")
    check("heredoc-collapses-to-one-line", t == "cat > f <<'EOF' line one EOF", t)


def test_codex_shaped_event_populates_begin_target():
    fake = RecordingClient()
    v = _drive(fake, {"tool_name": "bash", "tool_input": {"command": "git push origin HEAD"}})
    check("allow", v.allow and v.decided, str(v))
    begins = fake.args_of("hestia_begin_action")
    check("begin-called", len(begins) == 1, str(fake.calls))
    # The target is the command, not its verb (2026-09-08) — the arm's point stands: non-empty.
    check("target-populated", begins[0].get("target") == "git push origin HEAD",
          f"codex-shaped event must carry the command as target; got {begins[0].get('target')!r}")


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


# ---- (c) ONE decision recorder ----
# The Sprint E refusal recorder (`witness_decision_unified`, its gate-denies-<member>.jsonl
# fallback) is RETIRED in one-gate stage C: it recorded refusals only and read any outer RPC
# `result` as delivered. Every seat's gate now records every final verdict through stage A's
# receipt-validated `record_decision` (tools/decision_witness_contract_test.py owns its arms:
# target, verdict_available, the fallback rule, never raising). What stays here is the
# sprint's own claim, re-asserted on the new shape: there is exactly ONE recorder.
def test_one_decision_recorder():
    check("the-sprint-E-recorder-is-retired", not hasattr(m, "witness_decision_unified"))
    check("its-fallback-log-is-retired", not hasattr(m, "_append_deny_fallback")
          and not hasattr(m, "_deny_fallback_path"))
    check("record_decision-is-the-recorder", callable(getattr(m, "record_decision", None)))


# ---- (d) codex hook — spawn machinery deleted, and since stage C nothing of its own ----
def test_codex_copy_no_spawn_machinery():
    src = open(CODEX_HOOK, encoding="utf-8").read()
    check("no-subprocess-import", "import subprocess" not in src,
          "gate 2 must be in-process; codex had no other subprocess use")
    check("no-claude-pre", "CLAUDE_PRE" not in src, "spawn config constant must be gone")
    check("no-society-gate-env", "HESTIA_SOCIETY_GATE" not in src,
          "the spawn-target env knob must be gone with the spawn")
    check("delegates-to-the-common-gate", "gate.decide(" in src, "decide() call missing")
    check("no-transport-or-recorder-of-its-own", "query_society_safety" not in src
          and "witness_decision" not in src, "a shim must not ask or record by itself")
    py_compile.compile(CODEX_HOOK, doraise=True)


# ---- (e) claude hook — private client deleted, and since stage C nothing of its own ----
def test_claude_copy_no_private_client():
    src = open(CLAUDE_HOOK, encoding="utf-8").read()
    check("no-private-class", "class McpHttp" not in src, "private client class must be gone")
    check("no-private-poller", "def poll_policy" not in src, "private wait-poller must be gone")
    check("no-private-sse", "def parse_json_or_sse" not in src, "private SSE parser must be gone")
    check("delegates-to-the-common-gate", "gate.decide(" in src, "decide() call missing")
    check("no-transport-of-its-own", "query_society_safety" not in src and "urllib" not in src)
    py_compile.compile(CLAUDE_HOOK, doraise=True)


# (f) RETIRED with codex_gate_boundary_test.py: every arm it ran (transport- and
# self-protection-owned) now runs against all four seats' real gates in
# plugins/_shared/seat_gate_boundary_test.py.


ALL = [
    test_lowercase_bash_extract_target,
    test_shell_target_is_masked_and_bounded,
    test_codex_shaped_event_populates_begin_target,
    test_kind_field_populated,
    test_kind_none_on_no_verdict_and_backcompat,
    test_action_id_attached_on_decided,
    test_one_decision_recorder,
    test_codex_copy_no_spawn_machinery,
    test_claude_copy_no_private_client,
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
