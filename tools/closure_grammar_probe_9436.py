#!/usr/bin/env python3
"""Offline classifier probe for escalation ed1863d468b73ac0 (claude-code, 2026-09-02).

Runs the SAME closure engine the kimi hook loaded (~/.hestia/shared, sha256 f648556d...,
byte-identical to main and to .wt/kimi-810) against the exact refused bytes and against
the single-simple-command variants kimi's transcript said it believed would ALSO be
refused ("cmp is unrecognized -> out-of-grammar -> vocabulary present -> refused").
No hook runs; nothing is written; no gate row is minted.
"""
import json, sys
sys.path.insert(0, "/home/dp/.hestia/shared")
import hestia_governance_closure as g

WIRE = ("/home/dp/.kimi-code/sessions/wd_ai-agents_777c4901744b/"
        "session_66215da4-d292-442c-ac19-2e73ee213b01/agents/agent-0/wire.jsonl")
CWD = "/mnt/c/exe/projects/ai-agents/hestia/.wt/kimi-810"

exact = None
with open(WIRE, encoding="utf-8", errors="replace") as fh:
    for line in fh:
        if "tool_aVgMjq1YdLVhriMfVNmcJlIQ" not in line:
            continue
        r = json.loads(line)
        ev = r.get("event", {})
        if ev.get("type") == "tool.call":
            exact = ev["args"]["command"]
            break
assert exact, "exact refused command not found in kimi wire"

A = "plugins/kimi/hooks/pre_tool_use.py"
B = "/tmp/k810-pre_tool_use.py.6e20ae003eae490e"
variants = [
    ("exact refused bytes", exact),
    ("bare cmp, relative marker path", f"cmp -s {A} {B}"),
    ("bare cmp, absolute marker path", f"cmp -s {CWD}/{A} {B}"),
    ("cd && cmp", f"cd {CWD} && cmp -s {A} {B}"),
    ("cmp ; cmp ; cmp (semicolons only)",
     f"cmp -s {A} {B}; cmp -s plugins/codex/hooks/pre_tool_use.py /tmp/x; cmp -s plugins/claude-code/hooks/pre_tool_use.py /tmp/y"),
    ("sha256sum both", f"sha256sum {A} {B}"),
    ("for loop, NO closure vocabulary", 'for p in /tmp/a /tmp/b; do cmp -s "$p" /tmp/c; done'),
    ("for loop over /tmp copies only (marker basename in /tmp path)",
     'for p in /tmp/k810-pre_tool_use.py.6e20ae003eae490e; do cat "$p" >/dev/null; done'),
    ("md5sum via pipe", f"cat {A} | md5sum"),
    ("diff", f"diff {A} {B}"),
    ("stat && echo || echo (09-01 22efdf shape, closure arm only)", f"stat {A} && echo ok || echo no"),
    ("H=marker; md5sum $H (09-01 3d56a8 shape)", f"H={A}; md5sum $H"),
    ("ls -la marker after git &&", f"git status --short && ls -la {A}"),
    ("brace group with marker (09-01 f470e8 shape)", f"cd {CWD} && {{ git status; ls -la {A}; sha256sum {A} {B}; }}"),
    ("marker inside $( )", f"EP=$(grep -n def {A} | head -1); echo $EP"),
]
c = g.default_closure()
print("closure source:", c.source)
print("engine:", g.__file__)
for label, cmd in variants:
    v = g.classify("Bash", {"command": cmd}, cwd=CWD, closure=c)
    print(f"{v.classification:6} rule={v.rule!s:45} marker={v.marker!s:22} resource={str(v.resource)[:60]!s:62} | {label}")
