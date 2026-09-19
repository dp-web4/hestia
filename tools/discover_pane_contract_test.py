#!/usr/bin/env python3
"""Discover pane contract (agent-lifecycle PRD R2): it is present, it is READ-ONLY, and it never
renders "could not look" as "nothing there".

Source-level where the claim is about what EXISTS or is ABSENT, in the house idiom
(runtime_config_operator_surface_test.py): each check names the construct it pins. Behavioural
where the claim is about what the pane DOES: `discoverModel` and `discoverRow` are pure -- report
in, view-model out, no DOM -- so they are lifted out of the dashboard and run under node.

WHY READ-ONLY IS PINNED AS AN ABSENCE. This pane is the first sprint of work whose later sprints
register and retire agents. Those are operator acts with their own review. The easiest way for
one to arrive unreviewed is as a convenient button on the screen that already lists the agents,
and no test of present behaviour notices a request that was not there yesterday. So the Discover
block is checked for what it must NOT contain: any request but one GET.

THE THREE ANSWERS THAT MUST STAY THREE (PRD P4), each of which this fleet has shipped as the
wrong one at least once: the scan could not run (UNKNOWN, with its reason -- never an empty
list); the scan ran and a group is empty (omitted); and an installed agent the report did not
classify (kept, under its own heading -- a row that vanishes is the defect).

Run: python3 tools/discover_pane_contract_test.py     (exit 1 on failure)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "core/src/server/dashboard/index.html").read_text()
FAILS: list[str] = []


def check(name: str, got, want=True) -> None:
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


def discover_block() -> str:
    a = UI.index("// ── Discover (agent-lifecycle PRD R2)")
    b = UI.index("const GOVERN_PANES = {", a)
    return UI[a:b]


def source_contract() -> None:
    check("govern sub-nav has the chip", 'data-gov="discover"' in UI)
    check("pane is registered, and mounts by loading",
          "discover: { el: 'govern-discover', mount: () => discoverLoad() }" in UI)
    check("pane section exists", '<section class="govern-pane" id="govern-discover" hidden>' in UI)
    check("rescan is wired", "e.target.id === 'disc-rescan'" in UI)

    block = discover_block()
    fetches = re.findall(r"apiFetch\(\s*'([^']+)'\s*(?:,\s*\{([^}]*)\})?", block)
    check("READ-ONLY: exactly one request in the Discover block", len(fetches), 1)
    if fetches:
        check("READ-ONLY: and it is the inventory read", fetches[0][0], "/api/agents")
        check("READ-ONLY: with no method override", "method" in fetches[0][1], False)
    for verb in ("'POST'", "'PUT'", "'DELETE'", "'PATCH'", '"POST"', '"PUT"', '"DELETE"', '"PATCH"'):
        check(f"READ-ONLY: no {verb} anywhere in the Discover block", verb in block, False)
    check("no timer of its own -- a filesystem walk is fetched on show and on rescan only",
          "setInterval" in block, False)

    check("a fetch failure is rendered as UNKNOWN, not as an empty machine",
          "could not reach the inventory" in block and "unknown: true" in block)
    check("UNKNOWN says it is not 'nothing found'", 'this is not "nothing found"' in block)
    check("undefined failure mode is its own state", "failure mode unknown" in block)
    check("both names are shown, and the grant-relevant one is labelled",
          "governance id" in block and "atlas <code>" in block)


def run_model(report) -> dict:
    block = discover_block()
    pure = block[block.index("const DISCOVER_GROUPS"):block.index("function discoverRender(")]
    prog = pure + "\nprocess.stdout.write(JSON.stringify(discoverModel(JSON.parse(process.argv[1]))));"
    r = subprocess.run(["node", "-e", prog, json.dumps(report)], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        FAILS.append(f"node failed: {r.stderr.strip()[:300]}")
        return {"groups": [], "unknown": None}
    return json.loads(r.stdout)


def agent(atlas_id, plugin, installed, atlas=None, **kw):
    return {"agent": atlas_id, "plugin": plugin, "installed": installed, "atlas": atlas or {},
            "configs_read": [], "findings": [], **kw}


def behaviour() -> None:
    ok_report = {
        "status": "OK", "governed": ["claude"],
        "gaps": {"miswired": ["gemini"], "ungoverned": ["codex"], "ungovernable": ["aider"],
                 "dormant_plugin": ["cursor"], "partial": [], "miswired_3p": [], "unknown": []},
        "scope": {"workspace": "/w", "agent_enumeration": "agent-atlas",
                  "agent_enumeration_complete": True, "atlas": "/a", "atlas_source": "env"},
        "detail": [
            agent("claude", "claude-code", True, {"harness": "Claude Code", "fails_open": True,
                                                   "blocking_events": ["PreToolUse"], "fidelity": "verified"}),
            agent("gemini", "gemini", True, {"harness": "Gemini CLI", "fails_open": False}),
            agent("codex", "codex", True, {"harness": "Codex"}),
            agent("aider", None, True, {"harness": "Aider", "fails_open": True}),
            agent("cursor", "cursor", False),
        ],
    }
    m = run_model(ok_report)
    check("OK report is not unknown", m.get("unknown"), False)
    check("WORST FIRST: miswired leads, governed follows the gaps, dormant is last",
          [g["key"] for g in m["groups"]], ["miswired", "ungoverned", "ungovernable", "governed", "dormant_plugin"])
    rows = {r["atlasId"]: r for g in m["groups"] for r in g["rows"]}
    check("the two names are distinct fields", (rows["claude"]["atlasId"], rows["claude"]["governanceId"]),
          ("claude", "claude-code"))
    check("display name comes from the atlas descriptor", rows["claude"]["name"], "Claude Code")
    check("fails_open true  -> open", rows["claude"]["failure"], "open")
    check("fails_open false -> closed", rows["gemini"]["failure"], "closed")
    check("fails_open ABSENT -> unknown, NOT closed and NOT open", rows["codex"]["failure"], "unknown")
    check("no plugin -> no governance id, rather than echoing the atlas id", rows["aider"]["governanceId"], "")
    check("scope carries where the atlas came from", m["scope"]["atlasSource"], "env")

    # UNKNOWN that still saw things: the banner AND the rows. The inventory deliberately keeps
    # walking when the atlas is missing; dropping its rows here would undo that.
    partial = dict(ok_report, status="UNKNOWN", reason="agent-atlas registry not readable",
                   scope=dict(ok_report["scope"], agent_enumeration_complete=False))
    m = run_model(partial)
    check("UNKNOWN keeps its reason", (m["unknown"], m["reason"]), (True, "agent-atlas registry not readable"))
    check("UNKNOWN still lists what it saw", sum(len(g["rows"]) for g in m["groups"]), 5)
    check("an incomplete enumeration is flagged", m["scope"]["complete"], False)

    # The daemon's own UNKNOWN when the inventory is not installed: status + reason, nothing else.
    m = run_model({"status": "UNKNOWN", "reason": "agent-inventory is not installed on this machine"})
    check("not-installed: unknown, with the daemon's reason, no invented rows",
          (m["unknown"], m["reason"], m["groups"]),
          (True, "agent-inventory is not installed on this machine", []))

    # Garbage in. None of these may throw, and none may read as a clean machine.
    for label, junk in (("empty object", {}), ("null", None), ("detail is not a list", {"status": "OK", "detail": 7}),
                        ("rows are not objects", {"status": "OK", "detail": [None, 3, "x"], "governed": ["ghost"]})):
        m = run_model(junk)
        check(f"garbage ({label}): survives", isinstance(m.get("groups"), list))
    m = run_model({})
    check("no status at all is UNKNOWN, with a reason", (m["unknown"], bool(m["reason"])), (True, True))
    m = run_model({"status": "OK", "governed": ["ghost"], "detail": []})
    check("an id with no detail record still gets a row, by its id", m["groups"][0]["rows"][0]["name"], "ghost")

    # An installed agent no group claims must not vanish.
    stray = dict(ok_report, detail=ok_report["detail"] + [agent("windsurf", None, True, {"harness": "Windsurf"})])
    m = run_model(stray)
    check("unclassified installed agent is SHOWN, and first", (m["groups"][0]["key"], m["groups"][0]["rows"][0]["atlasId"]),
          ("unclassified", "windsurf"))
    quiet = dict(ok_report, detail=ok_report["detail"] + [agent("windsurf", None, False)])
    check("a NOT-installed unclassified agent is not noise", run_model(quiet)["groups"][0]["key"], "miswired")


def live() -> None:
    """The real report from this machine, when there is one. It is the only fixture nobody wrote."""
    inv = Path.home() / ".local/bin/hestia-agent-inventory"
    if not inv.is_file():
        print("SKIPPED: live report -- hestia-agent-inventory is not installed here (fixtures still ran)")
        return
    r = subprocess.run([str(inv), "--no-witness", "--json"], capture_output=True, text=True, timeout=120)
    try:
        report = json.loads(r.stdout)
    except ValueError:
        print("SKIPPED: live report -- the installed inventory did not return JSON")
        return
    m = run_model(report)
    listed = {row["atlasId"] for g in m["groups"] for row in g["rows"]}
    expected = set(report.get("governed") or []) | {i for ids in (report.get("gaps") or {}).values() for i in ids
                                                    if isinstance(ids, list)} - set((report.get("gaps") or {}).get("unknown") or [])
    check("live: every agent the report groups is drawn", sorted(expected - listed), [])
    check("live: the model's unknown flag agrees with the report", m["unknown"], report.get("status") == "UNKNOWN")
    print(f"live report: status={report.get('status')} groups={[ (g['key'], len(g['rows'])) for g in m['groups'] ]}")


def main() -> int:
    source_contract()
    if shutil.which("node"):
        behaviour()
        live()
    else:
        print("SKIPPED: behaviour -- no node on PATH (the source contract above still ran)")
    for f in FAILS:
        print("FAIL", f)
    print(f"discover pane contract: {'FAILED' if FAILS else 'PASS'} ({len(FAILS)} failure(s))")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
