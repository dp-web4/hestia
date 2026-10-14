#!/usr/bin/env python3
"""Codex's earlier counterexamples against the RE-STACKED gate + closure (merged/), in memory.
Run through run_one.py so the patched modules are preloaded:
  W=<wt> python3 run_one.py tools/_probe.py probe_codex.py"""
import os
import sys
import tempfile

g = sys.modules["hestia_governance_" + "closure"]
gate = sys.modules["hestia_single_" + "gate"]
fails = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        fails.append(name)


# Codex 18931 P2: escaped wildcard; 18830 P1: caret / POSIX class
with tempfile.TemporaryDirectory(prefix="rs-probe-") as d:
    for pattern, entry in ((r"x\[ab]y*", "x[ab]yes"), (r"x\[ab]efore_*", "x[ab]efore_tool.py"),
                           ("[^z]efore_tool.py", "before_tool.py"),
                           ("[[:alpha:]]efore_tool.py", "before_tool.py"),
                           ("[[=b=]]efore_tool.py", "[=]efore_tool.py"), ("before_*", "before_tool.py")):
        check(f"entry-matcher {pattern!r} -> {entry!r}",
              gate._reaches_registered_entry(os.path.join(d, pattern), [os.path.join(d, entry)]))
    check("negative control after_* does not reach before_tool.py",
          not gate._reaches_registered_entry(os.path.join(d, "after_*"), [os.path.join(d, "before_tool.py")]))

# `resolved` stays #1239's tuple; #1247's location is `landing`
with tempfile.TemporaryDirectory(prefix="rs-probe-") as d:
    hooks = os.path.join(os.path.realpath(d), "w", "plugins", "kimi", "hooks")
    os.makedirs(hooks)
    entry = os.path.join(hooks, "pre_tool_use.py")
    alias = os.path.join(os.path.realpath(d), "alias")
    os.symlink(hooks, alias)
    v = g.write_verdicts("Write", {"file_path": entry}, cwd="/")[0]
    check("absolute: resolved is an empty tuple", v.resolved == (), v)
    check("absolute: landing is the path", v.landing == entry, v)
    v = g.write_verdicts("Write", {"file_path": "pre_tool_use.py"}, cwd=hooks)[0]
    check("relative: resolved is a tuple carrying the cwd-joined form",
          isinstance(v.resolved, tuple) and entry in v.resolved, v)
    check("relative: landing is the location", v.landing == entry, v)
    v = g.write_verdicts("Bash", {"command": f"cd {hooks} && touch pre_tool_use.py"}, cwd="/")[0]
    check("cd-then-touch: landing is the location", v.landing == entry, v)
    v = g.write_verdicts("Bash", {"command": f"echo x > {alias}/pre_tool_use.py"}, cwd="/")[0]
    check("alias: resolved tuple carries the realpath", entry in v.resolved, v)
    check("alias: landing is the realpath", v.landing == entry, v)

    ev = gate.GateEvent
    # the write set: #1239's order (resource, spellings), landing appended only when new
    t, c = gate._closure_write_set(ev("Bash", {"command": f"echo x > {alias}/pre_tool_use.py"}, cwd="/"))
    check("write set alias == [alias, realpath]", t == [f"{alias}/pre_tool_use.py", entry] and c, (t, c))
    t, c = gate._closure_write_set(ev("Write", {"file_path": "pre_tool_use.py"}, cwd=hooks))
    check("write set relative carries the location, complete", entry in t and c, (t, c))
    t, c = gate._closure_write_set(ev("Write", {"file_path": "pre_tool_use.py"}, cwd=None))
    check("relative with no cwd: incomplete", not c, (t, c))
    t, c = gate._closure_write_set(ev("Bash", {"command": 'touch "$TARGET"'}, cwd="/"))
    check("$TARGET: incomplete", not c, (t, c))
    t, c = gate._closure_write_set(ev("Bash", {"command": f'touch {entry} "$TARGET"'}, cwd="/"))
    check("known target beside $TARGET: incomplete, known target rides", (not c) and entry in t, (t, c))
    long_src = "/tmp/" + "s" * 230 + "/staged/x.py"
    t, c = gate._closure_write_set(ev("Bash", {"command": f"cp {long_src} {hooks}/pre_tool_use.py"}, cwd="/"))
    check("summary-cut: the target rides whole", entry in t and c, (t, c))

print(f"{'FAILED ' + str(fails) if fails else 'all probes passed'}")
sys.exit(1 if fails else 0)
