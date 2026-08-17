#!/usr/bin/env python3
"""`_attempted_summary` — the behavioural claims, machine-proven.

kimi NOT-SAME review of #185, findings 1 and 2. The PR asserted four properties in prose —
bounded to 220, redacts credential-shaped tokens, reports the withheld length, sends the
correct wire keys — and tested none of them. House norm is machine-proven claims, and *this
exact surface already produced a silent wire-name failure* (documented in the function's own
docstring: hestia tools accept unknown keys, so a wrong key succeeds and renders
`why: (none stated)` forever).

WHY THE REDACTION IS THE SERIOUS HALF. Before #185 nothing was sent at all. That PR is what
*starts* copying denied command text into the signed, hash-chained record. So it introduces a
bounded egress path for secret values: a denied command carrying `-H "Authorization: Bearer …"`
would be echoed verbatim into the witness chain — which is deliberately easier to read, and
harder to expunge, than the file the deny was protecting.

The original list caught key-material filenames and a few English nouns. It missed the shapes
that actually carry secrets in a shell command: HTTP auth headers, `--password=`, ssh config
paths, bearer tokens, and PEM material.

Lives in `tests/` rather than beside the hook because `plugins/claude-code/hooks/` is
governance surface and every edit there costs an operator approval. That is also exactly the
gap #175 is about — `tests/` has no `hooks` segment, so it is *not* protected — and this file
being writable without escalation is a live instance of it, noted rather than exploited.
"""
from __future__ import annotations

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "hooks", "pre_tool_use.py")

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


def _load_hook():
    """Import the gate as a module WITHOUT running it as a hook.

    It reads stdin only under `__main__`, so a plain import is inert."""
    spec = importlib.util.spec_from_file_location("hestia_gate_under_test", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_summary_is_bounded():
    """220 chars plus an ellipsis marker. An escalation body is read by a human under
    interruption, and an unbounded payload is both unreadable and a bigger copy of whatever
    the command contained."""
    m = _load_hook()
    long_cmd = "echo " + ("A" * 4000)
    out = m._attempted_summary("Bash", {"command": long_cmd})
    check("bounded_length", len(out) < 300, f"{len(out)} chars — the bound is not holding")
    check("bounded_marks_truncation", out.rstrip().endswith("…"),
          "a truncated summary that does not say it was truncated invites the reader to treat "
          "a prefix as the whole command")


def test_credential_shapes_are_redacted():
    """The ones that carry secrets in a real shell command — not just filenames.

    Each of these, echoed verbatim into a hash-chained record, is a leak that outlives the
    deny that produced it."""
    m = _load_hook()
    cases = {
        "http_auth_header":  'curl -H "Authorization: Bearer sk-live-abcd1234" https://x/y',
        "password_flag":     "mysql --password=hunter2 -e 'select 1'",
        "password_word":     "export DB_PASSWORD=hunter2",
        "ssh_config_path":   "cat ~/.ssh/config",
        "pem_material":      "echo '-----BEGIN RSA PRIVATE KEY-----' > /tmp/k",
        "bearer_bare":       "curl -H 'authorization: bearer abc123' https://x",
        "aws_key":           "export AWS_SECRET_ACCESS_KEY=wJalrXUtn",
        "private_key_file":  "scp id_rsa host:/tmp/",
    }
    for name, cmd in cases.items():
        out = m._attempted_summary("Bash", {"command": cmd})
        redacted = "REDACTED" in out
        check(f"redacts_{name}", redacted,
              f"echoed verbatim into the signed chain: {out[:90]!r}")
        if redacted:
            # The operator still needs to know SOMETHING was withheld and how much — a silent
            # drop reads as "the command was short", which is a different false statement.
            check(f"reports_withheld_length_{name}", "chars withheld" in out,
                  "a redaction that does not say how much it withheld hides its own action")


def test_ordinary_commands_are_not_redacted():
    """Redaction must not swallow the normal case — a summary that always says REDACTED is a
    summary that says nothing, and the whole point is to tell the operator what was attempted."""
    m = _load_hook()
    for cmd in ("sed -n '470,520p' plugins/claude-code/hooks/pre_tool_use.py",
                "git commit -m 'fix the thing'",
                "cargo test --lib dashboard"):
        out = m._attempted_summary("Bash", {"command": cmd})
        check(f"passes_through_{cmd.split()[0]}", "REDACTED" not in out and cmd[:20] in out,
              f"ordinary command was redacted or dropped: {out[:80]!r}")


def test_the_path_fallback_is_redacted_too():
    """kimi #185, finding 2 (second half). The `file_path` fallback returned the path with no
    redaction at all. Lower risk than a command — paths, not contents — but a path can BE the
    secret (`~/.ssh/id_ed25519`), and an inconsistent rule is one a reader cannot rely on."""
    m = _load_hook()
    out = m._attempted_summary("Read", {"file_path": "/home/member/.ssh/id_ed25519"})
    check("path_fallback_redacts", "REDACTED" in out,
          f"credential path echoed into the record verbatim: {out!r}")


def test_no_input_is_stated_not_guessed():
    m = _load_hook()
    check("non_dict_input", "no inspectable input" in m._attempted_summary("Bash", None))
    check("no_command_or_path", "no command or path" in m._attempted_summary("Bash", {"x": 1}))


def teardown_module(_module=None):
    """PYTEST-VISIBLE DELIVERY of the accumulated result (codex/gpt audit of #185, blocker A).

    `check()` records into `FAILURES` and only `__main__` exits non-zero. Under bare `python3`
    that is red; under `pytest` every test function returns None, nothing raises, and the file
    reports GREEN while carrying failures. Red under one invocation and green under another is
    the same null-state twin this repo's own self-execution guard exists to catch — and it was
    sitting in the test written to prove a security fix.

    `teardown_module` runs once after the module's tests under pytest and is inert under bare
    execution, so both invocations now agree. The accumulate-then-report shape is deliberately
    kept: it is what printed all seven leaking payloads at once instead of stopping at the
    first, and that is why the finding was actionable rather than a single symptom."""
    assert not FAILURES, f"{len(FAILURES)} check(s) failed: {FAILURES}"


class _RecordingClient:
    """Captures the outgoing MCP payload instead of sending it.

    Substituted for the hook's real client so the test observes exactly what the daemon would
    receive — no socket, no daemon, no timing."""

    calls = []

    def __init__(self, *_a, **_kw):
        pass

    def initialize(self):
        return {"result": {}}

    def initialized(self):
        return None

    def call_tool(self, name, args):
        type(self).calls.append((name, args))
        # Deny the claim so `request_self_write` takes its refusal path and the caller is not
        # told a write was permitted. The payload is what we came for.
        return {"result": {"claimed": False, "escalation_id": "stub-esc"}}


def test_the_claim_sends_reason_and_detail_not_the_stored_names():
    """THE LOAD-BEARING WIRE PROPERTY, actually captured (blocker B).

    The previous suite exercised `_attempted_summary()` and never observed the call it feeds.
    That is the gap the function's own docstring warns about: hestia tools accept unknown
    properties, so sending `stated_reason`/`stated_detail` — the names the daemon *stores* them
    under — SUCCEEDS silently and renders `why: (none stated)` forever. A green test proving
    the summary is well-formed says nothing about whether it arrives.

    So: swap in a recording client, drive the real code path, and assert on the emitted keys."""
    m = _load_hook()
    _RecordingClient.calls = []
    real = m.McpHttp
    try:
        m.McpHttp = _RecordingClient
        m.request_self_write("some/marker", "Edit", "Edit: touched a governed file")
    finally:
        m.McpHttp = real

    claims = [a for (n, a) in _RecordingClient.calls if n == "hestia_gate_escalation_claim"]
    check("claim_was_sent", len(claims) == 1, f"{len(claims)} claim calls captured")
    if not claims:
        return
    payload = claims[0]
    check("sends_reason", payload.get("reason") == "Edit: touched a governed file",
          f"reason not delivered: {payload.get('reason')!r}")
    check("sends_detail", isinstance(payload.get("detail"), str) and payload["detail"],
          "detail missing — the operator surface renders it as `what:`")
    # The exact trap, asserted: the stored names must NOT be on the wire, because sending them
    # succeeds and produces a permanently reasonless escalation.
    check("does_not_send_stated_reason", "stated_reason" not in payload,
          "sending the STORED name succeeds silently and yields 'why: (none stated)' forever")
    check("does_not_send_stated_detail", "stated_detail" not in payload)


ALL_TESTS = [
    "test_the_claim_sends_reason_and_detail_not_the_stored_names",
    "test_the_summary_is_bounded",
    "test_credential_shapes_are_redacted",
    "test_ordinary_commands_are_not_redacted",
    "test_the_path_fallback_is_redacted_too",
    "test_no_input_is_stated_not_guessed",
]


def test_every_test_is_registered():
    defined = {k for k in globals() if k.startswith("test_")}
    missing = sorted(defined - set(ALL_TESTS) - {"test_every_test_is_registered"})
    check("every_test_is_registered", not missing, f"defined but never run: {missing}")


if __name__ == "__main__":
    print("attempted_summary")
    test_every_test_is_registered()
    test_the_claim_sends_reason_and_detail_not_the_stored_names()
    test_the_summary_is_bounded()
    test_credential_shapes_are_redacted()
    test_ordinary_commands_are_not_redacted()
    test_the_path_fallback_is_redacted_too()
    test_no_input_is_stated_not_guessed()
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} — {FAILURES}")
        sys.exit(1)
    teardown_module()
    print("all checks pass")
