#!/usr/bin/env python3
"""Tests for the one policy gate.

The load-bearing one is `remedies_name_only_real_doors`. Four times in two days a refusal
named a door the recipient could not open, and every time it was written by an author who
was not subject to the constraint. This suite makes that class fail at test time instead of
at a blocked member.

Run:  python3 test_gate_core.py          (offline checks only)
      HESTIA_MCP=http://127.0.0.1:7711/mcp python3 test_gate_core.py   (also checks the
                                                                        live tool list)
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hestia_gate_core as G  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


# ── the remedy inventory ─────────────────────────────────────────────────────────────────
def live_tool_names():
    """The daemon's ACTUAL tool list. Returns None if the daemon is not reachable — in which
    case this check is SKIPPED and says so, rather than passing vacuously. A green that means
    'nothing was checked' is the null-state twin of a green that means 'checked and fine'."""
    url = os.environ.get("HESTIA_MCP")
    if not url:
        return None
    H = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    sid = {}

    def rpc(method, params, rid=1):
        h = dict(H)
        if sid.get("v"):
            h["Mcp-Session-Id"] = sid["v"]
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if rid is not None:
            body["id"] = rid
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=h)
        resp = urllib.request.urlopen(req, timeout=20)
        sid.setdefault("v", resp.headers.get("Mcp-Session-Id"))
        return resp.read().decode()

    try:
        rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "gate-core-test", "version": "1"}})
        rpc("notifications/initialized", {}, rid=None)
        raw = rpc("tools/list", {}, rid=2)
        for line in raw.splitlines():
            if line.startswith("data: {"):
                j = json.loads(line[6:])
                if "result" in j and "tools" in j["result"]:
                    return {t["name"] for t in j["result"]["tools"]}
    except Exception as e:
        print(f"  note  daemon unreachable ({e.__class__.__name__}) — live check SKIPPED")
    return None


def test_remedies_name_only_real_doors():
    """THE test. A remedy may not name a tool the daemon does not register.

    This is the check that would have caught `request_scope` on the day it was written,
    instead of costing kimi a blocked session, a misdirected appeal and a correct-but-useless
    arbitration."""
    live = live_tool_names()
    if live is None:
        print("  skip  remedies_name_only_real_doors (set HESTIA_MCP to run it)")
        return
    named = G.remedy_tools()
    missing = sorted(named - live)

    # RECORD THE DISCRIMINATOR. "The running daemon lacks this tool" has two causes that look
    # identical here and are not remotely the same defect:
    #
    #   NEVER BUILT   — the `request_scope` class. An authoring error: someone wrote a remedy
    #                   for a door that does not exist anywhere. Fix the remedy, or build it.
    #   NOT DEPLOYED  — the tool is in the source and the daemon is running an older binary.
    #                   The remedy is correct and will be true after a restart.
    #
    # Reporting both as "the daemon does NOT have it" would support a count, not a judgement —
    # and the first thing anyone does with an undiscriminated red is relax the check.
    src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "core", "src")
    in_source = set()
    for root, _dirs, files in os.walk(src_dir):
        for fn in files:
            if not fn.endswith(".rs"):
                continue
            try:
                body = open(os.path.join(root, fn), encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for t in missing:
                if f'"{t}"' in body:
                    in_source.add(t)
    never_built = sorted(set(missing) - in_source)
    undeployed = sorted(in_source)

    detail = ""
    if never_built:
        detail += (f"NEVER BUILT (authoring error — fix the remedy or build the door): "
                   f"{never_built}. ")
    if undeployed:
        detail += (f"NOT DEPLOYED (remedy is correct; the running daemon is older than the "
                   f"source): {undeployed}. ")
    # Only a never-built door is an authoring failure. An undeployed one is a true statement
    # about a stale daemon, and it must still be RED — a member reading that remedy today
    # cannot use the door — but the fix is a deploy, not an edit.
    check("remedies_name_only_real_doors", not missing, detail)
    # And the inverse worth knowing, though not a failure: doors that exist and no remedy
    # points at. A door nobody is ever told about is only marginally better than no door.
    unmentioned = sorted(t for t in live
                         if t in {"hestia_request_scope", "hestia_appeal",
                                  "hestia_gate_escalation_open"} and t not in named)
    if unmentioned:
        print(f"  note  existing doors no remedy names: {unmentioned}")


def test_remedy_text_declares_every_tool_it_names():
    """`tools` is what the check above reads, so a remedy that names a tool in prose but omits
    it from `tools` would slip past. Scan the prose too."""
    bad = []
    for rule, r in G.REMEDIES.items():
        in_prose = set(re.findall(r"\bhestia_[a-z_]+\b", r.text))
        undeclared = in_prose - set(r.tools)
        if undeclared:
            bad.append((rule, sorted(undeclared)))
    check("remedy_text_declares_every_tool_it_names", not bad, str(bad))


def test_every_deny_path_has_a_remedy():
    """`_deny` raises on an unregistered rule, so a refusal cannot ship without a remedy. Assert
    that rather than trusting the raise stays."""
    try:
        G._deny("rule.that.does.not.exist", "x")
        check("every_deny_path_has_a_remedy", False, "an unregistered rule produced a Verdict")
    except KeyError:
        check("every_deny_path_has_a_remedy", True)


def test_egress_offers_no_door():
    """The one refusal that must NOT name a remedy tool. A leaked secret has no undo, so
    offering a channel would imply the act is available at a price."""
    check("egress_offers_no_door", G.REMEDIES["egress.secret"].tools == ())


def test_scope_remedy_distinguishes_itself_from_appeal():
    """The confusion that cost kimi a cycle. Both scope remedies must name the scope door AND
    say the appeal channel cannot deliver a path."""
    for rule in ("mrh.path", "mrh.command"):
        t = G.REMEDIES[rule].text.lower()
        check(f"{rule}_names_the_scope_door", "hestia_request_scope" in t)
        check(f"{rule}_distinguishes_appeal", "hestia_appeal" in t)


# ── policy behaviour ─────────────────────────────────────────────────────────────────────
def _strip_prose(src):
    """Code lines only — no comments, no docstrings.

    Written as a helper because I got this wrong twice in one session: a drift detector that
    hashed function TEXT reported comment edits as semantic drift, and the first version of
    `core_never_calls_sys_exit` matched the phrase inside the core's own docstring saying it
    never calls it. A check that reads prose is measuring the wrong artifact."""
    out, ds = [], False
    for line in src.splitlines():
        s = line.strip()
        if s.startswith('"""') or s.startswith("'''"):
            q = s[:3]
            ds = not (s.count(q) >= 2 and len(s) > 3)
            continue
        if ds or s.startswith("#") or not s:
            continue
        out.append(line)
    return "\n".join(out)


def _workspace():
    """A scratch workspace that is NOT under /tmp.

    /tmp is unconditionally in scope, so a fake workspace built with plain `mkdtemp()` is
    allowed wholesale and every scope assertion passes for the wrong reason — five green
    checks that measured nothing. Exactly the null-state twin: a pass bit-identical to 'the
    gate is not running'."""
    base = os.path.expanduser("~/.cache/hestia-gate-core-tests")
    os.makedirs(base, exist_ok=True)
    ws = tempfile.mkdtemp(dir=base)
    assert not ws.startswith(("/tmp", "/var/tmp")), ws
    return ws


def _profile(tmp, scope):
    p = os.path.join(tmp, "identity.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"mrh": {"in_scope": scope}, "role": "role:constellation:member"}, fh)
    return G.HarnessProfile(member_id="test-member", identity_path=p,
                            home_markers=("~/.test-member",))


def test_path_and_command_scope():
    ws = _workspace()
    for r in ("granted", "notgranted"):
        os.makedirs(os.path.join(ws, r), exist_ok=True)
    prof = _profile(ws, ["repo:granted"])

    ev = G.NormalizedEvent(tool="Read", paths=[f"{ws}/granted/a.md"], cwd=ws)
    check("in_scope_path_allows", G.evaluate(ev, prof, ws).decision == "allow")

    ev = G.NormalizedEvent(tool="Read", paths=[f"{ws}/notgranted/a.md"], cwd=ws)
    v = G.evaluate(ev, prof, ws)
    check("out_of_scope_path_denies", v.blocks and v.rule == "mrh.path")
    check("deny_carries_a_remedy", "hestia_request_scope" in v.remedy)
    check("deny_names_the_offending_target", "notgranted" in v.reason)

    ev = G.NormalizedEvent(tool="Read", paths=[f"{ws}"], cwd=ws)
    check("bare_workspace_root_denies", G.evaluate(ev, prof, ws).blocks)

    # /tmp and the member's own home are always reachable.
    ev = G.NormalizedEvent(tool="Read", paths=["/tmp/x"], cwd=ws)
    check("tmp_allows", G.evaluate(ev, prof, ws).decision == "allow")


def test_path_grant_reaches_a_sibling_of_the_repos():
    """`.git-inbox` is a sibling of the repos, so a repo: grant never reaches it — the exact
    refusal kimi hit on 2026-08-02 while reading the directory the push guard names."""
    ws = _workspace()
    os.makedirs(os.path.join(ws, ".git-inbox"), exist_ok=True)
    ev = G.NormalizedEvent(tool="Read", paths=[f"{ws}/.git-inbox/submissions"], cwd=ws)

    without = _profile(ws, ["repo:granted"])
    check("sibling_denied_without_path_grant", G.evaluate(ev, without, ws).blocks)

    with_grant = _profile(_workspace(), ["repo:granted", "path:.git-inbox"])
    check("sibling_allowed_with_path_grant",
          G.evaluate(ev, with_grant, ws).decision == "allow")


def test_egress_beats_scope():
    """Innate invariants dominate: a secret inside a GRANTED repo is still denied."""
    ws = _workspace()
    os.makedirs(os.path.join(ws, "granted"), exist_ok=True)
    prof = _profile(ws, ["repo:granted"])
    ev = G.NormalizedEvent(tool="Read", paths=[f"{ws}/granted/.env"], cwd=ws)
    v = G.evaluate(ev, prof, ws)
    check("egress_beats_scope", v.blocks and v.rule == "egress.secret" and v.innate)


def test_missing_identity_fails_narrow_not_wide():
    """A malformed or absent identity must not grant reach. The default is deliberately one
    repo, not the workspace."""
    prof = G.HarnessProfile(member_id="x", identity_path="/nonexistent/identity.json")
    check("missing_identity_is_narrow", G.load_in_scope(prof) == ["web4"])


def test_core_never_exits():
    """The core returns a Verdict; only shims exit. Every lineage hook engine fails OPEN, so a
    shim must never be able to confuse 'no verdict' with 'allowed'."""
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "hestia_gate_core.py"), encoding="utf-8").read()
    check("core_never_calls_sys_exit", "sys.exit" not in _strip_prose(src))


def test_core_is_vendor_agnostic():
    """No harness may be named in the core — that is what the profile is for. MEMBER_ADDRESSES
    is the one allowed exception and is checked separately below."""
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "hestia_gate_core.py"), encoding="utf-8").read()
    code = []
    ds = False
    for line in src.splitlines():
        s = line.strip()
        if s.startswith('"""') or s.startswith("'''"):
            q = s[:3]
            ds = not (s.count(q) >= 2 and len(s) > 3)
            continue
        if ds or s.startswith("#") or not s:
            continue
        code.append(line)
    code = "\n".join(code)
    # Strip the one sanctioned list of member addresses before scanning.
    code = re.sub(r"MEMBER_ADDRESSES = frozenset\(\{[^}]*\}\)", "", code)
    leaked = [v for v in ("kimi", "codex", "cursor", "gemini", "claude-code")
              if v in code.lower()]
    check("core_is_vendor_agnostic", not leaked,
          f"vendor names in core logic: {leaked} — add a HarnessProfile field instead")


if __name__ == "__main__":
    print("hestia_gate_core")
    for fn in sorted(
        (v for k, v in list(globals().items()) if k.startswith("test_")),
        key=lambda f: f.__code__.co_firstlineno,
    ):
        fn()
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} — {FAILURES}")
        sys.exit(1)
    print("all checks pass")
