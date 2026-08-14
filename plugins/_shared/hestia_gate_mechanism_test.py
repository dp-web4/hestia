#!/usr/bin/env python3
"""Fail-closed contract + wire-shape tests for the shared society-safety mechanism.

The load-bearing assertions are FAIL-CLOSED: on every failure or unrecognized-wire shape
(no endpoint, init failure, connect/begin rejection, MISSING SESSION, poll timeout, unknown
status, missing/unknown decision, empty payload, network + unexpected exception, exhausted
deadline, bad budget env) query_society_safety must return allow=False. One allow-on-error
here silently un-governs a fail-open member.

check() RAISES on failure so pytest sees each case (GPT #CI-b); the __main__ runner collects.
Run: python3 -m pytest <thisdir> -q   or   python3 hestia_gate_mechanism_test.py
"""
import os
import sys
import time
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hestia_gate_mechanism as m  # noqa: E402

# Capture the REAL client class before any test monkeypatches m._McpHttp (the fake-injection in
# _drive() clobbers the module global; the deadline test needs the genuine _request).
_REAL_MCP = m._McpHttp


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {detail}")


class FakeClient:
    """Scripted MCP client. Each stage returns a structuredContent dict, or raises."""
    def __init__(self, connect=None, begin=None, policy=None, init_ok=True, raise_on=None):
        self.connect = {"sessionId": "s1"} if connect is None else connect
        self.begin = {"actionId": "a1"} if begin is None else begin
        self.policy = {"status": "decided", "decision": "allow"} if policy is None else policy
        self.init_ok = init_ok
        self.raise_on = raise_on

    def initialize(self):
        if self.raise_on == "initialize":
            raise urllib.error.URLError("boom")
        return {"result": {}} if self.init_ok else {}

    def initialized(self):
        pass

    def call_tool(self, name, args):
        if self.raise_on == name:
            raise urllib.error.URLError("boom")
        payload = {"hestia_connect": self.connect,
                   "hestia_begin_action": self.begin,
                   "hestia_query_policy": self.policy}
        payload.update(getattr(self, "extra", {}))
        return {"result": {"structuredContent": payload[name]}}


def _drive(fake, endpoint="http://fake/mcp"):
    m._discover_endpoint = (lambda: endpoint)
    m._McpHttp = lambda ep, deadline: fake
    return m.query_society_safety({"tool_name": "Bash", "tool_input": {"command": "echo hi"}},
                                  plugin_id="kimi-code", host_agent="kimi-code")


# ---- interpretation: only explicit allow/warn/deny authorize or block ----
def test_allow_proceeds():
    v = _drive(FakeClient(policy={"status": "decided", "decision": "allow"}))
    check("allow_proceeds", v.allow and v.decided, str(v))


def test_deny_enforced_blocks():
    v = _drive(FakeClient(policy={"status": "decided", "decision": "deny", "enforced": True,
                                  "reason": "nope", "guidance": "hestia: deny — nope"}))
    check("deny_enforced_blocks", (not v.allow) and v.decided, str(v))
    check("deny_message", "deny" in v.message.lower(), repr(v.message))


def test_warn_allows():
    v = _drive(FakeClient(policy={"status": "decided", "decision": "warn", "reason": "careful"}))
    check("warn_allows", v.allow and v.decided, str(v))


def test_audit_deny_allows():
    v = _drive(FakeClient(policy={"status": "decided", "decision": "deny", "enforced": False}))
    check("audit_deny_allows", v.allow and v.decided, str(v))


# ---- FAIL-CLOSED: transport / session / budget ----
def test_no_endpoint_failcloses():
    m._discover_endpoint = lambda: None
    m._McpHttp = lambda ep, dl: FakeClient()
    v = m.query_society_safety({"tool_name": "Bash", "tool_input": {}},
                               plugin_id="kimi-code", host_agent="kimi-code")
    check("no_endpoint", (not v.allow) and (not v.decided) and v.cause == "refused", str(v))


def test_init_failure_failcloses():
    v = _drive(FakeClient(init_ok=False))
    check("init_failure", (not v.allow) and (not v.decided), str(v))


def test_connect_rejected_failcloses():
    v = _drive(FakeClient(connect={"_hestia_error": "denied"}))
    check("connect_rejected", (not v.allow) and (not v.decided), str(v))


def test_missing_session_failcloses():
    v = _drive(FakeClient(connect={}))  # no sessionId (GPT #2)
    check("missing_session", (not v.allow) and (not v.decided), str(v))


def test_begin_missing_action_failcloses():
    v = _drive(FakeClient(begin={}))
    check("begin_missing_action", (not v.allow) and (not v.decided), str(v))


def test_poll_timeout_failcloses():
    v = _drive(FakeClient(policy={"status": "evaluating", "nextPollMs": 0}))
    check("poll_timeout", (not v.allow) and (not v.decided) and v.cause == "timeout", str(v))


def test_network_exception_failcloses():
    v = _drive(FakeClient(raise_on="hestia_connect"))
    check("network_exc", (not v.allow) and (not v.decided), str(v))


def test_init_exception_failcloses():
    v = _drive(FakeClient(raise_on="initialize"))
    check("init_exc", (not v.allow) and (not v.decided), str(v))


# ---- FAIL-CLOSED: wire shape (GPT #1 — the ones that used to fail OPEN) ----
def test_empty_policy_payload_failcloses():
    v = _drive(FakeClient(policy={}))  # no status, no decision
    check("empty_payload", (not v.allow) and (not v.decided), str(v))


def test_unknown_status_failcloses():
    v = _drive(FakeClient(policy={"status": "quantum", "decision": "allow"}))
    check("unknown_status", (not v.allow) and (not v.decided), str(v))


def test_missing_decision_failcloses():
    v = _drive(FakeClient(policy={"status": "decided"}))  # decided but no decision field
    check("missing_decision", (not v.allow) and (not v.decided), str(v))


def test_unknown_decision_value_failcloses():
    v = _drive(FakeClient(policy={"status": "decided", "decision": "maybe"}))
    check("unknown_decision", (not v.allow) and (not v.decided), str(v))


# ---- standing scope (Sprint F R1): daemon-certified snapshot admits ----
def test_standing_grant_becomes_admitting_scope_with_certification():
    """A durable standing grant served by the daemon must land in the snapshot as an
    ADMITTING in_scope entry (repo-root -> repo name), carry the daemon-issued
    certification pair (generation + expires_at), and flow through the core's
    resolve_agent_policy vault branch onto an AgentPolicy that path_in_scope honours.
    The expired arm is the tighten half: a snapshot past its own horizon grants NOTHING."""
    import tempfile
    import hestia_gate_core as core
    ws = tempfile.mkdtemp(prefix="sswt-ws-")
    old_ws = os.environ.get("HESTIA_WORKSPACE")
    os.environ["HESTIA_WORKSPACE"] = ws
    try:
        horizon = int(time.time()) + 3600
        fake = FakeClient()
        fake.extra = {
            "hestia_operating_law": {
                "identity": {"plugin_id": "kimi-code", "role": "role:constellation:member"},
                "law_hash": "h-std"},
            "hestia_scope_status": {
                "plugin_id": "kimi-code", "requests": [], "live_grants": [],
                "standing_grants": [
                    {"path": ws + "/web4", "granted_by": "operator",
                     "reason": "standing repo grant", "expires_at": None},
                    {"path": ws + "/web4/deep/file.txt", "granted_by": "operator",
                     "reason": "file grant stays a path grant", "expires_at": None},
                ],
                "generation": 4,
                "snapshot_expires_at": horizon},
        }
        m._discover_endpoint = lambda: "http://fake/mcp"
        m._McpHttp = lambda ep, dl: fake
        snap = m.fetch_policy_snapshot("kimi-code", use_cache=False)
        check("standing_snap_present", isinstance(snap, dict), repr(snap))
        check("standing_repo_root_maps_to_name", "web4" in snap["in_scope"], str(snap))
        check("standing_deep_path_stays_path",
              ("path:" + ws + "/web4/deep/file.txt") in snap["in_scope"], str(snap))
        check("standing_list_carried", len(snap["standing_grants"]) == 2, str(snap))
        check("standing_generation", snap["generation"] == 4, str(snap))
        check("standing_expires_at", snap["expires_at"] == horizon, str(snap))

        prof = core.HarnessProfile(member_id="kimi-code",
                                   identity_path="/nonexistent/identity.json")
        pol = core.resolve_agent_policy(prof, vault_reader=lambda mid: snap)
        check("standing_source_vault", pol.source == "vault", str(pol))
        check("standing_scope_admits_name", "web4" in pol.scope, str(pol))
        check("standing_cert_generation", pol.generation == 4, str(pol))
        check("standing_cert_expires_at", pol.expires_at == horizon, str(pol))
        check("standing_path_in_scope_admits",
              core.path_in_scope(ws + "/web4/anything.rs", pol.scope, ws, prof, None),
              f"scope={pol.scope} ws={ws}")

        expired = dict(snap)
        expired["expires_at"] = 1
        pol2 = core.resolve_agent_policy(prof, vault_reader=lambda mid: expired)
        check("standing_expired_grants_nothing",
              pol2.scope == () and pol2.source == "vault-expired" and pol2.stale,
              str(pol2))
    finally:
        if old_ws is None:
            os.environ.pop("HESTIA_WORKSPACE", None)
        else:
            os.environ["HESTIA_WORKSPACE"] = old_ws


# ---- FAIL-CLOSED: deadline exhaustion + bad env (GPT #4) ----
def test_exhausted_deadline_refuses_request():
    c = _REAL_MCP("http://x", deadline=time.monotonic() - 1.0)  # already past
    raised = False
    try:
        c._request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    except TimeoutError:
        raised = True
    check("exhausted_deadline_raises", raised, "expected TimeoutError before any request")


def test_bad_budget_env_defaults_not_raises():
    os.environ["X_TEST_BUDGET"] = "notanumber"
    check("bad_env_defaults", m._num_env("X_TEST_BUDGET", 800, int) == 800, "non-numeric")
    os.environ["X_TEST_BUDGET"] = "-5"
    check("neg_env_defaults", m._num_env("X_TEST_BUDGET", 800, int) == 800, "negative")
    os.environ["X_TEST_BUDGET"] = "1500"
    check("good_env_used", m._num_env("X_TEST_BUDGET", 800, int) == 1500, "valid")
    del os.environ["X_TEST_BUDGET"]


# Explicit list — NOT a globals() comprehension — so every test name is a static reference
# (tools/ci_selfexec_test.py rejects test functions whose execution cannot be established
# statically; a dynamic sweep leaves each name un-referenced and reads as inert).
ALL = [
    test_allow_proceeds,
    test_deny_enforced_blocks,
    test_warn_allows,
    test_audit_deny_allows,
    test_no_endpoint_failcloses,
    test_init_failure_failcloses,
    test_connect_rejected_failcloses,
    test_missing_session_failcloses,
    test_begin_missing_action_failcloses,
    test_poll_timeout_failcloses,
    test_network_exception_failcloses,
    test_init_exception_failcloses,
    test_empty_policy_payload_failcloses,
    test_unknown_status_failcloses,
    test_missing_decision_failcloses,
    test_unknown_decision_value_failcloses,
    test_standing_grant_becomes_admitting_scope_with_certification,
    test_exhausted_deadline_refuses_request,
    test_bad_budget_env_defaults_not_raises,
]

if __name__ == "__main__":
    print("shared society-safety mechanism — fail-closed + wire-shape contract")
    failed = []
    for t in ALL:
        try:
            t()
            print("PASS", t.__name__)
        except AssertionError as e:
            failed.append(t.__name__)
            print("FAIL", t.__name__, "::", e)
    print()
    if failed:
        print(f"FAILURES: {failed}")
        sys.exit(1)
    print(f"OK — {len(ALL)} tests, fail-closed on every failure + wire-boundary shape")
