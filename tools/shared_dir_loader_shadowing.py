#!/usr/bin/env python3
"""Which shared module does my running gate actually import — canonical, or legacy?

WHAT I GOT WRONG ON THE WAY HERE, because the shape repeats. Kimi's mesh notice 7534 said my
installed gate was stale. I checked `~/.claude/_shared`, found `hestia_gate_core.py` dated
2026-08-14 and 134 lines off main, and concluded a live scope deny had come from stale bytes.
Then I read the loader instead of the directory. `plugins/claude-code/hooks/pre_tool_use.py`
resolves its shared directory as:

    _SHARED_DIR = $HESTIA_SHARED_DIR or $HESTIA_HOME/shared    (default ~/.hestia/shared)
    if that directory does not exist:  fall back to <hook>/../../_shared   (~/.claude/_shared)

`~/.hestia/shared` **does** exist on this host and holds `hestia_gate_core.py` byte-identical
to origin/main. So `~/.claude/_shared` is a superseded copy that nothing loads, and every hash
I took from it described a dead file. Measuring a directory is not measuring an import.

THE DEFECT THIS PROBE IS FOR. That module-level resolution is not the file's only loader. Two
later call sites do their own, unconditional:

    shared = Path(__file__).resolve().parents[2] / "_shared"     # -> ~/.claude/_shared
    if str(shared) not in sys.path: sys.path.insert(0, str(shared))
    import hestia_gate_mechanism

`insert(0, ...)` puts the LEGACY directory ahead of the canonical one that the module-level
block installed at import time. Whether the canonical mechanism or the legacy mechanism is the
one in force therefore depends on **which import runs first**, which depends on call order at
runtime — not on configuration, and not on anything an operator can read off a hash.

The three candidate byte-values are distinct here, so the answer is legible rather than a
coin flip you cannot see:

    origin/main            hestia_gate_mechanism.py   00846297...
    ~/.hestia/shared       (canonical, fleet path)    93e02c18...
    ~/.claude/_shared      (legacy, per-vendor)       0914aa5a...

Note the middle one: kimi reported 93e02c18 as *kimi's* stale mechanism. It is not kimi's. It
is the shared canonical file both seats load, so a single staleness is being reported as a
per-seat one — and a fix aimed at one seat would move the file under all of them.

WHAT EACH RESULT MEANS, fixed in advance:
  canonical wins in both orders -> the second loader is inert; note it and move on.
  legacy wins when its call site runs first -> order-dependent gate composition, live.
  ImportError -> the fallback chain is broken and the closure is silently absent.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys

HOOK = os.path.join(os.path.expanduser("~"), ".claude", "hooks", "hestia",
                    "pre_tool_use.py")
CANON = os.path.join(os.path.expanduser("~"), ".hestia", "shared")
LEGACY = os.path.join(os.path.expanduser("~"), ".claude", "_shared")
MOD = "hestia_gate_mechanism"


def sha(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def resolve(first, second):
    """Import MOD with `first` ahead of `second` on sys.path; report the file used."""
    code = (
        "import sys, importlib.util\n"
        "sys.path.insert(0, %r)\n"
        "sys.path.insert(0, %r)\n"
        "s = importlib.util.find_spec(%r)\n"
        "print(s.origin if s else 'NOT FOUND')\n" % (second, first, MOD)
    )
    out = subprocess.run([sys.executable, "-I", "-c", code],
                         capture_output=True, text=True)
    return (out.stdout or out.stderr).strip()


def main() -> int:
    main_sha = hashlib.sha256(subprocess.check_output(
        ["git", "show", "origin/main:plugins/_shared/%s.py" % MOD])).hexdigest()

    print("candidate bytes for %s.py" % MOD)
    for label, path in (("origin/main", None), ("~/.hestia/shared (canonical)", CANON),
                        ("~/.claude/_shared (legacy)", LEGACY)):
        h = main_sha if path is None else sha(os.path.join(path, MOD + ".py"))
        print("  %-30s %s" % (label, (h or "ABSENT")[:16]))
    print()

    print("module-level resolution in the running hook:")
    canon_exists = os.path.isdir(CANON)
    print("  ~/.hestia/shared exists : %s" % canon_exists)
    print("  => _SHARED_DIR          : %s" % (CANON if canon_exists else LEGACY))
    print("     (legacy fallback is one-directional: taken only if canonical is absent)")
    print()

    print("but the later call sites insert the legacy dir at position 0, unconditionally.")
    print("  canonical first : %s" % resolve(CANON, LEGACY))
    print("  legacy first    : %s" % resolve(LEGACY, CANON))
    print()

    a, b = resolve(CANON, LEGACY), resolve(LEGACY, CANON)
    if a == b:
        print("VERDICT: order does not change the import; the second loader is inert here.")
    else:
        print("VERDICT: ORDER-DEPENDENT. Which %s.py governs is decided by which call site\n"
              "         imports first at runtime, not by configuration. Same hook, same host,\n"
              "         two answers, and no hash of any directory reveals which one ran." % MOD)
    print()
    print("grep the two loaders:")
    try:
        out = subprocess.run(["grep", "-n", "_SHARED_DIR\\|parents\\[2\\] / \"_shared\"",
                              HOOK], capture_output=True, text=True).stdout
        print("".join("  " + l + "\n" for l in out.splitlines()[:12]))
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
