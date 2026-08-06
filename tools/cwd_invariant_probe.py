#!/usr/bin/env python3
"""Does the base the matcher PRICES against equal the base the executor WRITES from?

WHY THIS EXISTS. `tools/marker_bar_probe.py` answers "given an act, which marker and
which bar". `tools/permit_spend_set.py` answers "given a permit, what else does it
buy". Both take the matcher's verdict as the price of the act. This one asks whether
that verdict is about the file the act actually touches.

It is not always. The matcher resolves a relative path key with `os.path.realpath()`,
which prepends *the matcher process's* cwd. The tool executor resolves the same
string from *its own* cwd. Nothing in either harness couples the two. When they
differ, a write to a governed file can be priced `None` -- no marker, no escalation,
no witness -- and still land on the governed file. Layers 1-3 of the marker stack
mis-PRICE a write the gate sees; this one is a write the gate does not see, which is
strictly worse, and it is invisible to both probes above because their act space only
ever spells absolute paths.

WHAT IT DOES NOT DO. It routes no tool call and writes no file. It imports a matcher
module by path, calls its `_touches_self` directly under `os.chdir()`, and restores
the cwd. Safe to run repeatedly; no cleanup, no escalation, no conduct record.

THE MATCHER PATH IS AN ARGUMENT, NOT A LITERAL. Same constraint `marker_bar_probe.py`
documents: the gate scans proposed file content for its own path and for governance
FILENAMES anywhere, so a probe that hardcoded its target could not be written to disk.
Taking `--matcher` on the command line is also what makes this cross-harness -- the
question is per-harness and the answer differs by harness, so the instrument must not
be pinned to one.

THE INVARIANT, STATED PER TOOL. "The cwd the hook prices against == the cwd the
executor writes from." It is well-formed only for tools that declare a path in the
tool input (Write / Edit / NotebookEdit). It is NOT well-formed for Bash: a shell
command's target is not a function of the event at all -- the matcher matches the
command text raw, and no base exists to compare. A harness verdict must therefore
name its tool set. Reporting "harness X passes" without that qualifier is the summary
outliving the finding.

RED CONDITION. Exit 1 if there exists a spelling that resolves to a governed file
from the LANDING base while pricing `None` from the HOOK base. That is Layer 4 live,
computed rather than routed.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import os
import sys
from typing import Iterable, Optional


@contextlib.contextmanager
def _in_dir(path: str):
    """chdir with restore. The whole probe is a statement about this call."""
    prev = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


def load_matcher(path: str):
    """Import a harness's matcher module from an explicit path.

    Deliberately not a package import: the enforcing copy and the repo copy are
    different files with different absolute self-markers, and which one you loaded
    is part of the answer.
    """
    spec = importlib.util.spec_from_file_location("_probe_matcher", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load matcher from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for attr in ("_touches_self", "_GOVERNANCE_FILES"):
        if not hasattr(mod, attr):
            raise SystemExit(f"{path} has no {attr} -- not a matcher this probe reads")
    return mod


def governed_files(mod, root: str) -> list[str]:
    """Every real file under `root` whose basename the matcher treats as governance.

    Derived from the matcher's own tuple at runtime, never transcribed -- a
    transcribed list is a constant that stops tracking its producer the day someone
    adds a name.
    """
    names = set(mod._GOVERNANCE_FILES)
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", "node_modules", "target"}]
        for fn in filenames:
            if fn in names:
                hits.append(os.path.join(dirpath, fn))
    return sorted(hits)


def price(mod, base: str, tool: str, spelling: str) -> Optional[str]:
    """The marker the matcher returns for `spelling`, priced from `base`."""
    with _in_dir(base):
        return mod._touches_self(tool, {"file_path": spelling})


def relative_spellings(target: str, landing_base: str) -> Optional[str]:
    """The spelling that reaches `target` from `landing_base`, if it is below it."""
    try:
        rel = os.path.relpath(target, landing_base)
    except ValueError:
        return None
    if rel.startswith(".."):
        return None  # not reachable downward; a `..` spelling is a different class
    return rel


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--matcher", required=True,
                    help="path to the harness matcher module to import and call")
    ap.add_argument("--hook-base", required=True,
                    help="cwd the matcher process runs in (the PRICED base)")
    ap.add_argument("--landing-base", required=True,
                    help="cwd the tool executor resolves relative paths from (the LANDING base)")
    ap.add_argument("--root", default=None,
                    help="tree to enumerate governed files in (default: landing base)")
    ap.add_argument("--tool", default="Write",
                    help="tool name to price as; the invariant is only well-formed "
                         "for path-declaring tools (default: Write)")
    args = ap.parse_args(list(argv) if argv is not None else None)

    for label, p in (("--matcher", args.matcher), ("--hook-base", args.hook_base),
                     ("--landing-base", args.landing_base)):
        if not os.path.exists(p):
            raise SystemExit(f"{label}: no such path: {p}")

    mod = load_matcher(args.matcher)
    root = args.root or args.landing_base
    hook_base = os.path.realpath(args.hook_base)
    landing_base = os.path.realpath(args.landing_base)

    print(f"matcher      : {args.matcher}")
    print(f"hook base    : {hook_base}   (what the matcher prices against)")
    print(f"landing base : {landing_base}   (what the executor writes from)")
    print(f"tool         : {args.tool}")
    print()

    if hook_base == landing_base:
        print("BASES AGREE for this pair. That is a statement about these two "
              "arguments, not about the harness: it holds only while nothing moves "
              "either cwd. Re-run after disturbing every cwd source the harness "
              "exposes (a persisted `cd`, a per-call cwd parameter, a subshell).")

    targets = governed_files(mod, root)
    if not targets:
        print(f"no governed files under {root} -- the probe is blind here, not clean.")
        return 2

    divergent = []
    for target in targets:
        spelling = relative_spellings(target, landing_base)
        if spelling is None:
            continue
        priced = price(mod, hook_base, args.tool, spelling)
        landed = price(mod, landing_base, args.tool, spelling)
        if priced != landed:
            divergent.append((spelling, target, priced, landed))

    print(f"governed files under root : {len(targets)}")
    print(f"reachable by a relative spelling from the landing base : "
          f"{sum(1 for t in targets if relative_spellings(t, landing_base))}")
    print()

    if not divergent:
        print("PASS (this tool, these bases): every governed file reachable by a "
              "relative spelling prices the same from both bases.")
        return 0

    print(f"FAIL: {len(divergent)} governed file(s) price differently from the two bases.")
    print("Each row is a write that lands on the governed file while the gate prices "
          "what the row's PRICED column says -- `None` means no marker, no "
          "escalation, no witness.\n")
    for spelling, target, priced, landed in divergent:
        print(f"  spelling : {spelling}")
        print(f"  lands on : {target}")
        print(f"  PRICED   : {priced!r}   (from the hook base)")
        print(f"  would be : {landed!r}   (had the matcher used the landing base)")
        print()

    silent = [d for d in divergent if d[2] is None]
    if silent:
        print(f"{len(silent)} of these price None: the gate does not see the act at all.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
