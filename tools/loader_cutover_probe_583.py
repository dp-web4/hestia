#!/usr/bin/env python3
"""Which bytes of the shared gate engine does each seat actually LOAD?

Read-only driver for the finding "the #583 shared-dir cutover missed codex".

It does three things, in order of increasing strength:

  1. STATIC — counts the `_HESTIA_HOME` cutover marker in each seat's PreToolUse hook,
     for the deployed copy and the canonical repo copy. A seat with 0 is pre-cutover.
  2. VINTAGE — sha256 + mtime for every copy of the three shared modules in the three
     locations that matter, and the agreement verdict per module.
  3. DRIVEN — imports codex's REAL hook (it has a __main__ guard) and reports the
     resolved __file__ for each module the gate actually binds. This is the arm that
     matters: 1 and 2 are consistent with several stories, only 3 pins which one.

Usage:  HESTIA_WORKSPACE=/path/to/workspace python3 tools/codex_loader_cutover_probe.py
"""
import datetime
import hashlib
import importlib.util
import os
import sys

WORKSPACE = os.getenv("HESTIA_WORKSPACE", "/mnt/c/exe/projects/ai-agents")
HOME = os.path.expanduser("~")

SEATS = [
    ("claude-code", os.path.join(HOME, ".claude/hooks/hestia/pre_tool_use.py"),
     os.path.join(WORKSPACE, "hestia/plugins/claude-code/hooks/pre_tool_use.py")),
    ("kimi", os.path.join(HOME, ".kimi-code/hooks/pre_tool_use.py"),
     os.path.join(WORKSPACE, "hestia/plugins/kimi/hooks/pre_tool_use.py")),
    ("codex", os.path.join(HOME, ".codex/hooks/pre_tool_use.py"),
     os.path.join(WORKSPACE, "hestia/plugins/codex/hooks/pre_tool_use.py")),
]

LOCS = [
    ("installed (fleet canonical)", os.path.join(HOME, ".hestia/shared")),
    ("codex private _shared", os.path.join(HOME, ".codex/_shared")),
    ("live shared working tree", os.path.join(WORKSPACE, "hestia/plugins/_shared")),
]
MODS = ["hestia_gate_mechanism.py", "hestia_gate_core.py", "hestia_governance_closure.py"]

MARKER = "_HESTIA_HOME"


def digest(path):
    if not os.path.isfile(path):
        return None
    data = open(path, "rb").read()
    st = os.stat(path)
    return (hashlib.sha256(data).hexdigest()[:16], len(data),
            datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"))


def count_marker(path):
    if not os.path.isfile(path):
        return None
    return open(path, "r", errors="replace").read().count(MARKER)


def arm1_static():
    print("== ARM 1 (static): is each seat cut over to $HESTIA_HOME/shared? ==")
    print("   marker counted: %s   (0 == pre-cutover loader)" % MARKER)
    print()
    print("   %-12s %-9s %-9s %s" % ("SEAT", "DEPLOYED", "CANONICAL", "SAME BYTES?"))
    for seat, dep, can in SEATS:
        d, c = count_marker(dep), count_marker(can)
        dd, cd = digest(dep), digest(can)
        same = "n/a"
        if dd and cd:
            same = "yes" if dd[0] == cd[0] else "NO (deploy lag)"
        print("   %-12s %-9s %-9s %s" % (
            seat,
            "absent" if d is None else d,
            "absent" if c is None else c,
            same))
    print()


def arm2_vintage():
    print("== ARM 2 (vintage): which bytes sit in each location? ==")
    table = {}
    for label, d in LOCS:
        for m in MODS:
            r = digest(os.path.join(d, m))
            table[(label, m)] = r[0] if r else None
    for m in MODS:
        shas = {}
        for label, _ in LOCS:
            s = table[(label, m)]
            if s:
                shas.setdefault(s, []).append(label)
        verdict = "AGREE" if len(shas) == 1 else "DIVERGE (%d versions)" % len(shas)
        print("   %-28s %s" % (m, verdict))
        for s, who in shas.items():
            print("       %s  <- %s" % (s, ", ".join(who)))
        missing = [l for (l, _) in LOCS if table[(l, m)] is None]
        if missing:
            print("       ABSENT from: %s" % ", ".join(missing))
    print()


def arm3_driven():
    print("== ARM 3 (driven): what does codex's real loader BIND? ==")
    hook = os.path.join(HOME, ".codex/hooks/pre_tool_use.py")
    if not os.path.isfile(hook):
        print("   codex hook absent at %s — arm skipped" % hook)
        return
    before = list(sys.path)
    spec = importlib.util.spec_from_file_location("codex_pre_tool_use", hook)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        print("   module-level exec raised %s: %s" % (type(e).__name__, e))
        return
    added = [p for p in sys.path if p not in before]
    print("   sys.path added at import: %s" % (added or "<none>"))
    for name in ("hestia_governance_closure", "hestia_gate_core"):
        m = sys.modules.get(name)
        print("   %-28s -> %s" % (name, m.__file__ if m else "<NOT IMPORTED>"))
    fn = next((getattr(mod, n) for n in dir(mod)
               if "mech" in n.lower() and callable(getattr(mod, n, None))), None)
    if fn is None:
        print("   %-28s -> <no lazy loader found>" % "hestia_gate_mechanism")
        return
    try:
        mech = fn()
        print("   %-28s -> %s" % ("hestia_gate_mechanism", mech.__file__))
    except Exception as e:
        print("   mechanism loader raised %s: %s" % (type(e).__name__, e))


if __name__ == "__main__":
    print("workspace: %s\n" % WORKSPACE)
    arm1_static()
    arm2_vintage()
    arm3_driven()
