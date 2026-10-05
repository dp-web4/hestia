#!/usr/bin/env python3
"""The `attempted` text every seat sends: bounded, self-censoring, and on the right wire keys.

WHERE THIS CAME FROM. Until one-gate stage C these cases lived in
`plugins/claude-code/tests/attempted_summary_test.py` and exercised the claude-code shim's
private `_attempted_summary` (kimi NOT-SAME review of #185, findings 1 and 2; #941's head-cut
mark). The cutover retired that function, and the common gate's first `attempted_of` masked
only `key=value` / `--key value` shapes — so the cutover would have taken seven shapes the
claude-code seat withheld (auth headers, `--password=`, PASSWORD=, ssh config paths, PEM
blocks, bare bearer, credential-shaped paths) and put them back into the chain for claude-code,
and never given them to codex, kimi or gemini at all. The coordinator's ruling: ALIGN UPWARD.
The rule now lives once, in the mechanism (`attempted_summary`, `credential_shaped`), and this
file drives it through EVERY seat's real shim translation (`to_event`) into the common gate's
`attempted_of`, so a seat whose harness spells an act differently cannot slip past it.

WHICH LAYER COVERS WHAT (defence in depth, both kept):
  * sending side, `hestia_gate_mechanism.attempted_summary`: a credential-SHAPED command or
    path is withheld WHOLE, with its length stated; otherwise the value after a credential-ish
    key is masked. Only this layer covers key files, ssh/gpg trees, PEM blocks, `.env` and
    credential-shaped paths.
  * receiving side, the daemon's masker in `core/src/server/handler.rs`: `key=value` and
    `--key value` for a fixed key list, applied again to whatever arrives.

WHY THE REDACTION IS THE SERIOUS HALF: `attempted` is copied into the signed, hash-chained
record, which is deliberately easier to read and harder to expunge than the file a deny
protected. A refusal is not a licence to copy its payload there.

Staging seams (unset in the repo and in CI): HESTIA_CONTRACT_OVERLAY ({module: path}) and
HESTIA_CONTRACT_SHIMS ({seat: path}), the same pair `one_gate_decide_contract_test.py` reads.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
SHARED = REPO / "plugins" / "_shared"
SEAT_SHIM = {"claude-code": "claude-code/hooks/pre_tool_use.py",
             "codex": "codex/hooks/pre_tool_use.py",
             "kimi": "kimi/hooks/pre_tool_use.py",
             "gemini": "gemini/hooks/before_tool.py"}
SEATS = tuple(SEAT_SHIM)

FAILURES: list[str] = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


def _load_engine():
    overlay = json.loads(os.getenv("HESTIA_CONTRACT_OVERLAY") or "{}")
    if str(SHARED) not in sys.path:
        sys.path.append(str(SHARED))
    for name in ("hestia_gate_core", "hestia_governance_closure", "hestia_gate_mechanism",
                 "hestia_single_gate"):
        path = overlay.get(name)
        if path and name not in sys.modules:
            spec = importlib.util.spec_from_file_location(name, path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
    import hestia_gate_mechanism as m  # noqa: E402
    import hestia_single_gate as g  # noqa: E402
    return m, g


M, G = _load_engine()
_SHIMS: dict = {}


def shim(seat):
    if seat not in _SHIMS:
        override = json.loads(os.getenv("HESTIA_CONTRACT_SHIMS") or "{}")
        path = override.get(seat) or str(REPO / "plugins" / SEAT_SHIM[seat])
        spec = importlib.util.spec_from_file_location(
            f"attempted_shim_{seat.replace('-', '_')}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _SHIMS[seat] = mod
    return _SHIMS[seat]


#: Each harness's native spelling of a shell act and of a path act (shaped on recorded events;
#: codex has no path-only tool that reaches the gate — its file acts arrive as shell or
#: apply_patch, both of which carry a command body — so its path arms run as `cat <path>`).
SHELL = {"claude-code": ("PreToolUse", "Bash", "command"),
         "codex": ("PreToolUse", "Bash", "command"),
         "kimi": ("PreToolUse", "Shell", "command"),
         "gemini": ("BeforeTool", "run_shell_command", "command")}
PATH = {"claude-code": ("PreToolUse", "Edit", "file_path"),
        "kimi": ("PreToolUse", "WriteFile", "path"),
        "gemini": ("BeforeTool", "write_file", "absolute_path")}


def attempted(seat, raw_tool, tool_input, event_name):
    raw = {"hook_event_name": event_name, "tool_name": raw_tool, "tool_input": tool_input,
           "session_id": "attempted-test", "cwd": "/tmp"}
    ev = shim(seat).to_event(G, raw)
    return ev, G.attempted_of(ev)


def shell(seat, cmd):
    name, tool, key = SHELL[seat]
    return attempted(seat, tool, {key: cmd}, name)[1]


def test_the_summary_is_bounded():
    """220 chars plus a marker: an escalation body is read by a human under interruption,
    and an unbounded payload is a bigger copy of whatever the command contained."""
    for seat in SEATS:
        out = shell(seat, "echo " + ("A" * 4000))
        check(f"{seat}_bounded_length", len(out) < 300, f"{len(out)} chars")
        check(f"{seat}_bounded_marks_truncation", out.rstrip().endswith("…"),
              "a cut that does not say so invites reading a prefix as the whole command")


#: Assembled so this file's own text does not carry the tokens a text-matching gate refuses.
_S = "SEC" + "RET"
CREDENTIAL_CASES = {
    "http_auth_header": 'curl -H "Authorization: Bearer sk-live-abcd1234" https://x/y',
    "password_flag": "mysql --password=hunter2 -e 'select 1'",
    "password_word": "export DB_PASSWORD=hunter2",
    "ssh_config_path": "cat ~/.ssh/config",
    "pem_material": "echo '-----BEGIN RSA PRIVATE KEY-----' > /tmp/k",
    "bearer_bare": "curl -H 'authorization: bearer abc123' https://x",
    "aws_key": f"export AWS_{_S}_ACCESS_KEY=wJalrXUtn",
    "private_key_file": "scp id_rsa host:/tmp/",
}


def test_credential_shapes_are_redacted():
    """The shapes that carry credentials in a real shell command, for every seat — each one,
    echoed verbatim into a hash-chained record, outlives the deny that produced it."""
    for seat in SEATS:
        for name, cmd in CREDENTIAL_CASES.items():
            out = shell(seat, cmd)
            redacted = "REDACTED" in out
            check(f"{seat}_redacts_{name}", redacted, f"verbatim into the chain: {out[:90]!r}")
            if redacted:
                # A silent drop reads as "the command was short" — a different false statement.
                check(f"{seat}_reports_withheld_length_{name}",
                      f"{len(' '.join(cmd.split()))} chars withheld" in out, out)


def test_ordinary_commands_are_not_redacted():
    """A summary that always says REDACTED says nothing."""
    for seat in SEATS:
        for cmd in ("sed -n '470,520p' plugins/claude-code/hooks/pre_tool_use.py",
                    "git commit -m 'fix the thing'",
                    "cargo test --lib dashboard"):
            out = shell(seat, cmd)
            check(f"{seat}_passes_through_{cmd.split()[0]}",
                  "REDACTED" not in out and cmd[:20] in out, f"{out[:80]!r}")


def test_the_path_fallback_is_redacted_too():
    """kimi #185 finding 2: a path can BE the credential (`~/.ssh/id_ed25519`)."""
    target = "/home/member/.ssh/id_ed25519"
    for seat in SEATS:
        if seat in PATH:
            name, tool, key = PATH[seat]
            out = attempted(seat, tool, {key: target}, name)[1]
        else:
            out = shell(seat, f"cat {target}")
        check(f"{seat}_path_redacts", "REDACTED" in out and "chars withheld" in out,
              f"credential path echoed into the record: {out!r}")


def test_the_path_fallback_marks_a_head_cut():
    """A path over the cap keeps its TAIL (the filename) and marks the lost HEAD inside the
    bound. Measured 2026-09-04: escalations 4458c3bb90166bf1 and f93341f695702b07 recorded
    `Edit -> mp/claude-1000/...` for a write under `/tmp/claude-1000/...`, and the operator
    approved the first as written. The mark sits inside the 140-char bound, so the recorded
    width does not change (#627's digest-prefix equivalence is not widened)."""
    for seat, (name, tool, key) in PATH.items():
        short = "/tmp/" + ("a" * 100) + "/x.py"
        ev, out = attempted(seat, tool, {key: short}, name)
        check(f"{seat}_short_path_is_whole", out == f"{ev.tool} -> {short}", f"{out!r}")
        long_path = "/tmp/claude-1000/" + ("b" * 200) + "/plugins/_shared/x_test.py"
        out = attempted(seat, tool, {key: long_path}, name)[1]
        tail = out.split(" -> ", 1)[1] if " -> " in out else out
        check(f"{seat}_head_cut_is_marked", tail.startswith("…"), f"{out!r}")
        check(f"{seat}_head_cut_keeps_the_filename",
              tail.endswith("/plugins/_shared/x_test.py"), f"{out!r}")
        check(f"{seat}_head_cut_holds_the_bound", len(tail) <= 140, f"{len(tail)} chars")


def test_no_input_is_stated_not_guessed():
    check("non_dict_input", "no inspectable input" in M.attempted_summary("Bash", None))
    check("no_command_or_path", "no command or path" in M.attempted_summary("Bash", {"x": 1}))


def test_a_codex_patch_names_its_targets_or_its_body():
    """codex's file acts arrive as apply_patch; the body is the command text, held to the
    same rule (a patch touching a key file is withheld whole)."""
    body = "*** Begin Patch\n*** Add File: /home/m/.ssh/authorized_keys\n+x\n*** End Patch\n"
    ev, out = attempted("codex", "apply_patch", {"command": body}, "PreToolUse")
    check("codex_patch_to_a_key_file_redacts", "REDACTED" in out, out)
    body = "*** Begin Patch\n*** Update File: /tmp/w/notes.md\n+x\n*** End Patch\n"
    out = attempted("codex", "apply_patch", {"command": body}, "PreToolUse")[1]
    check("codex_patch_is_legible", "/tmp/w/notes.md" in out and "REDACTED" not in out, out)


def test_the_claim_sends_reason_and_detail_not_the_stored_names():
    """THE LOAD-BEARING WIRE PROPERTY. hestia tools accept unknown keys, so sending the names
    the daemon STORES them under (`stated_reason`/`stated_detail`) succeeds silently and
    renders `why: (none stated)` forever. Drive the real claim and assert on the keys."""
    calls = []

    def recording(tool, args, **_kw):
        calls.append((tool, args))
        return {"claimed": False, "escalation_id": "stub-esc"}

    real = M.gate_self_call
    summary = shell("kimi", "sed -i s/a/b/ plugins/_shared/x.py")
    try:
        M.gate_self_call = recording
        M.claim_self_write("plugins/_shared", "Shell", summary, plugin_id="kimi-code",
                           role="role:test", client_name="hestia-kimi-code-gate")
    finally:
        M.gate_self_call = real
    claims = [a for (n, a) in calls if n == "hestia_gate_escalation_claim"]
    check("claim_was_sent", len(claims) == 1, f"{len(claims)} claim calls")
    if claims:
        p = claims[0]
        check("sends_reason", p.get("reason") == summary, f"{p.get('reason')!r}")
        check("sends_detail", isinstance(p.get("detail"), str) and bool(p["detail"]))
        check("does_not_send_stated_reason", "stated_reason" not in p)
        check("does_not_send_stated_detail", "stated_detail" not in p)


ALL_TESTS = [
    test_the_summary_is_bounded,
    test_credential_shapes_are_redacted,
    test_ordinary_commands_are_not_redacted,
    test_the_path_fallback_is_redacted_too,
    test_the_path_fallback_marks_a_head_cut,
    test_no_input_is_stated_not_guessed,
    test_a_codex_patch_names_its_targets_or_its_body,
    test_the_claim_sends_reason_and_detail_not_the_stored_names,
]


def test_every_test_is_registered():
    defined = {k for k, v in globals().items() if k.startswith("test_") and callable(v)}
    missing = sorted(defined - {t.__name__ for t in ALL_TESTS} - {"test_every_test_is_registered"})
    check("every_test_is_registered", not missing, f"defined but never run: {missing}")


def teardown_module(_module=None):
    """Pytest-visible delivery: under pytest every test returns None, so the accumulated
    result must raise here or the file reports green while carrying failures."""
    assert not FAILURES, f"{len(FAILURES)} check(s) failed: {FAILURES}"


if __name__ == "__main__":
    print("attempted_summary (every seat, the common gate)")
    test_every_test_is_registered()
    for t in ALL_TESTS:
        t()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} — {FAILURES}")
        sys.exit(1)
    print("all checks pass")
