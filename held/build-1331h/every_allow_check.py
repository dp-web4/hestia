#!/usr/bin/env python3
"""Nova's #1435 review of 748469d2: a reach past link_reach's bound must never be ALLOWED on a partly swept Gate 1a,
on any path that can allow. Four authorities over one past-the-cap glob (`cat <dir>/*`, LINK_GLOB_LIMIT + 44 files):
  (a) ordinary in-scope grant        -> deny mrh.command.unenumerated
  (b) authoritative unscoped `*`     -> deny mrh.command.unenumerated (was: allow)
  (c) degraded_verdict, read-only    -> deny mrh.command.unenumerated (was: allow), Bash `cat` and `ls`
  (d) the glob OUTSIDE every grant   -> the scope refusal, NOT unenumerated (the escalation path survives)
plus controls: a small glob is allowed under (a) (b) (c), and link_reach_too_wide takes the single gate's GateEvent
(no command, no paths) without raising. Not test-shaped: on the applied core (b) and (c) allow, by design.
Run under held/build-1331h/run_overlay.py <worktree> <dir with core_rev.py> <this file>."""
import os
import sys

import grant_modes_gate_test as g

core = g.core
bad = []


def row(name, got, want):
    ok = want(got) if callable(want) else got == want
    print(f"{'ok  ' if ok else 'FAIL'} {name}: {got}")
    if not ok:
        bad.append(name)


def main():
    with g._Workspace() as ws:
        repo = os.path.join(ws, "hestia")
        wide, small = os.path.join(repo, "wide"), os.path.join(repo, "small")
        outside = os.path.join(ws, "outside", "wide")
        for d in (wide, small, outside):
            os.makedirs(d)
        n = getattr(core, "LINK_GLOB_LIMIT", 256) + 44
        for d in (wide, outside):
            for i in range(n):
                open(os.path.join(d, f"f{i}.txt"), "w").close()
        for i in range(3):
            open(os.path.join(small, f"f{i}.txt"), "w").close()

        snap = g._snapshot(ws, standing=[{"path": repo, "recursive": True}])
        prof, scoped = g._policy(snap)
        unscoped = core.AgentPolicy(member_id=prof.member_id, scope=("*",), source="vault")
        assert unscoped.is_unscoped() and not unscoped.stale

        def ev(cmd):
            return core.NormalizedEvent(tool="Bash", paths=[], command=cmd, cwd=repo)

        def v(cmd, pol):
            r = core.evaluate(ev(cmd), prof, ws, policy=pol)
            return f"{r.decision}/{r.rule or '-'}"

        def dg(cmd):
            r = core.degraded_verdict(ev(cmd), prof)
            return f"{r.decision}/{r.rule or '-'}"

        UN = "deny/mrh.command.unenumerated"
        row("(a) in-scope past the cap", v("cat wide/*", scoped), UN)
        row("(b) unscoped past the cap", v("cat wide/*", unscoped), UN)
        row("(c) degraded cat past the cap", dg("cat wide/*"), UN)
        row("(c) degraded ls past the cap", dg("ls wide/*"), UN)
        row("(d) outside every grant", v(f"cat {outside}/*", scoped),
            lambda s: s.startswith("deny/") and s != UN)
        row("control (a) small glob", v("cat small/*", scoped), "allow/-")
        row("control (b) small glob", v("cat small/*", unscoped), "allow/-")
        row("control (c) small glob", dg("cat small/*"), "allow/-")

        class GateEventShape:          # the single gate's event: tool_input, no command/paths
            tool = "Bash"
            tool_input = {"command": "cat wide/*"}
        try:
            got = core.link_reach_too_wide(GateEventShape(), None)
            row("GateEvent through link_reach_too_wide", repr(got), lambda s: True)
        except Exception as e:  # noqa: BLE001
            row("GateEvent through link_reach_too_wide", f"raised {type(e).__name__}: {e}", lambda s: False)

    print("FAIL:", bad) if bad else print("PASS - every allow path refuses a partly swept reach")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
