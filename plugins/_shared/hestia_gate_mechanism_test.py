#!/usr/bin/env python3
"""Fail-closed contract + decision-interpretation tests for the shared society-safety mechanism.

The load-bearing assertions are the FAIL-CLOSED ones: on every failure shape (no endpoint,
init failure, connect/begin rejection, poll timeout, network exception, unexpected exception),
query_society_safety must return allow=False. A single allow-on-error here silently un-governs
a fail-open member. Run: python3 -m pytest <thisdir> -q   (or execute directly)."""
import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hestia_gate_mechanism as m  # noqa: E402


class FakeClient:
    """Scripted MCP client. Each stage returns a structuredContent dict, or raises."""
    def __init__(self, connect=None, begin=None, policy=None, init_ok=True, raise_on=None):
        self.connect = {"sessionId": "s1"} if connect is None else connect
        self.begin = {"actionId": "a1"} if begin is None else begin
        self.policy = {"status": "decided", "decision": "allow"} if policy is None else policy
        self.init_ok = init_ok
        self.raise_on = raise_on   # tool name (or "initialize") that raises URLError

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
                   "hestia_query_policy": self.policy}[name]
        return {"result": {"structuredContent": payload}}


def _drive(fake, endpoint="http://fake/mcp", monkeypatch_endpoint=None):
    m._discover_endpoint = (lambda: endpoint) if monkeypatch_endpoint is None else monkeypatch_endpoint
    m._McpHttp = lambda ep, deadline: fake
    return m.query_society_safety({"tool_name": "Bash", "tool_input": {"command": "echo hi"}},
                                  plugin_id="kimi-code", host_agent="kimi-code")


FAILURES = []


def check(name, cond, detail=""):
    ok = bool(cond)
    print(("PASS" if ok else "FAIL"), name, "" if ok else f"— {detail}")
    if not ok:
        FAILURES.append(name)


def test_allow():
    v = _drive(FakeClient(policy={"status": "decided", "decision": "allow"}))
    check("allow_proceeds", v.allow and v.decided, f"{v}")


def test_deny_enforced_blocks():
    v = _drive(FakeClient(policy={"status": "decided", "decision": "deny", "enforced": True,
                                  "reason": "nope", "guidance": "hestia: deny — nope"}))
    check("deny_enforced_blocks", (not v.allow) and v.decided, f"{v}")
    check("deny_message_present", "deny" in v.message.lower(), f"{v.message!r}")


def test_warn_allows():
    v = _drive(FakeClient(policy={"status": "decided", "decision": "warn", "reason": "careful"}))
    check("warn_allows", v.allow and v.decided, f"{v}")


def test_audit_deny_allows():
    v = _drive(FakeClient(policy={"status": "decided", "decision": "deny", "enforced": False,
                                  "reason": "would-block"}))
    check("audit_deny_allows", v.allow and v.decided, f"{v}")


# ---- the FAIL-CLOSED family: every failure shape must yield allow=False ----
def test_no_endpoint_failcloses():
    v = _drive(FakeClient(), monkeypatch_endpoint=lambda: None)
    check("no_endpoint_failclosed", (not v.allow) and (not v.decided), f"{v}")
    check("no_endpoint_cause_refused", v.cause == "refused", f"{v.cause}")


def test_init_failure_failcloses():
    v = _drive(FakeClient(init_ok=False))
    check("init_failure_failclosed", (not v.allow) and (not v.decided), f"{v}")


def test_connect_rejected_failcloses():
    v = _drive(FakeClient(connect={"_hestia_error": "denied"}))
    check("connect_rejected_failclosed", (not v.allow) and (not v.decided), f"{v}")


def test_begin_missing_action_failcloses():
    v = _drive(FakeClient(begin={}))  # no actionId
    check("begin_missing_action_failclosed", (not v.allow) and (not v.decided), f"{v}")


def test_poll_never_decides_failcloses():
    # status stays 'evaluating' forever -> poll runs out -> None -> fail closed
    v = _drive(FakeClient(policy={"status": "evaluating", "nextPollMs": 0}))
    check("poll_timeout_failclosed", (not v.allow) and (not v.decided), f"{v}")
    check("poll_timeout_cause", v.cause == "timeout", f"{v.cause}")


def test_network_exception_failcloses():
    v = _drive(FakeClient(raise_on="hestia_connect"))
    check("network_exc_failclosed", (not v.allow) and (not v.decided), f"{v}")


def test_init_exception_failcloses():
    v = _drive(FakeClient(raise_on="initialize"))
    check("init_exc_failclosed", (not v.allow) and (not v.decided), f"{v}")


ALL = [test_allow, test_deny_enforced_blocks, test_warn_allows, test_audit_deny_allows,
       test_no_endpoint_failcloses, test_init_failure_failcloses, test_connect_rejected_failcloses,
       test_begin_missing_action_failcloses, test_poll_never_decides_failcloses,
       test_network_exception_failcloses, test_init_exception_failcloses]

if __name__ == "__main__":
    print("shared society-safety mechanism — fail-closed contract")
    for t in ALL:
        t()
    print()
    if FAILURES:
        print(f"FAILURES: {FAILURES}")
        sys.exit(1)
    print(f"OK — {len(ALL)} tests, fail-closed on every failure shape")
