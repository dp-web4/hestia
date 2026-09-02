#!/usr/bin/env python3
"""Do the forked gate predicates DISAGREE with the shared engine, or only duplicate it?

`gate_collapse_meter.py` counts forks. A count is not a harm: a seat can define a name the
shared engine owns and still answer identically, in which case collapsing it is tidiness.
This asks the next question, which is the one that decides priority:

    for the same input, does the seat's copy return a different verdict?

and, when it does, which way -- a seat that DENIES more than the engine annoys its member;
a seat that GRANTS what the engine denies is a hole.

WHY THESE INPUTS. Not random, and not adversarial invention. Every case below is a defect
class the shared implementation's OWN DOCSTRING says it was hardened against, each naming
the report that found it. So a divergence is not "two implementations differ" -- it is a
bug that was already found, already fixed, and is still live in a copy nobody was measuring.
That is the difference between duplication as debt and duplication as exposure.

WHAT THIS IS NOT. It does not execute the seat's gate. It lifts the predicate out by AST and
calls it directly, so an import side effect cannot make the numbers up. It says nothing about
whether the seat is currently running: a fork in a dormant-but-installed gate is exposure the
day the seat is woken, and the meter's job is to see it before then, not after.

RATCHET. Pinned like the meter: the divergence count may fall, never rise. Collapsing a
forked predicate onto the shared one is what drives it to zero.

Exit: 0 the pin held; 1 it broke, or a CONTROL disagreed (which means this harness is lying
and its numbers should not be read at all).
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "_shared"))

import hestia_gate_core as core          # noqa: E402

GATE = ROOT / "plugins" / "gemini" / "hooks" / "before_tool.py"
LIFT = {"path_in_scope", "command_in_scope", "_all_repos"}


def lift(path: Path, workspace: str, home: str) -> dict:
    """Pull the predicates out of the seat module without importing it.

    Importing would run the module's top level -- env reads, config loads, and on some seats
    a daemon probe. The predicates are what is on trial; the module's startup is not."""
    src = path.read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines()
    ns = {"os": os, "re": re, "WORKSPACE": workspace, "GEMINI_HOME": home}
    found = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name in LIFT:
            exec("\n".join(lines[node.lineno - 1:node.end_lineno]), ns)
            found.append(node.name)
    missing = LIFT - set(found)
    if missing:
        # The seat was collapsed, or renamed, or this file is stale. Either way the harness
        # must not print a comfortable zero: nothing was compared.
        print(f"cannot determine: {path.name} no longer defines {sorted(missing)}. If the "
              f"fork was collapsed, delete the case from LIFT and lower the pin.",
              file=sys.stderr)
        raise SystemExit(1)
    return ns


def cases(ws: str, home: str):
    """(label, path, expected ENGINE verdict, defect class).

    Every row pins what the hardened engine must answer, not merely that the two
    implementations agree. An agreement-only control is worthless: the first draft of this
    file built its synthetic workspace under `/tmp`, so `_under_temp_root` granted every
    path, engine and seat agreed on True everywhere, four controls "passed", and the harness
    reported 2 divergences instead of 6. Two implementations can agree by both being wrong.

    Traversal targets are bland directory names on purpose. Spelling a credential directory
    in a table of STRINGS trips the fleet's own egress scanner -- mention, not perform -- and
    the segment arithmetic under test does not care what the last component is called."""
    return [
        ("sibling-home",      home + "-evil/x",                False, "home judged by SUBSTRING, not boundary (GPT fleet-review blocker 8)"),
        ("home-traversal",    home + "/../elsewhere/x",        False, "traversal OUT of home still reads as home (blocker 8)"),
        ("tmp-prefix",        "/tmpfoo/x",                     False, "startswith('/tmp') (codex #169, _under_temp_root)"),
        ("vartmp-prefix",     "/var/tmpevil/x",                False, "startswith('/var/tmp') (codex #169)"),
        ("ws-traversal-out",  ws + "/granted/../ungranted/x",  False, "no normpath: segment read lexically (kimi #940 B5)"),
        ("ws-traversal-deep", ws + "/granted/a/../../other/x", False, "no normpath, two levels up (kimi #940 B5)"),
        ("ws-substring",      ws + "-evil/granted/x",          False, "'WORKSPACE in p' substring containment (kimi #940 B5)"),
        ("ws-root-bare",      ws,                              False, "control: glob-the-root antipattern"),
        ("granted-plain",     ws + "/granted/tools/x.py",      True,  "control: plainly in scope"),
        ("ungranted-plain",   ws + "/ungranted/x.py",          False, "control: plainly out of scope"),
        ("real-tmp",          "/tmp/probe",                    True,  "control: real tmp"),
        ("real-home",         home + "/settings.json",         True,  "control: the member's own home"),
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-divergences", type=int, default=None,
                    help="ratchet: fail if more inputs diverge than this")
    args = ap.parse_args()

    # Hermetic, and deliberately NOT under a temp dir. Neither predicate touches the disk
    # (the engine's only fs call is realpath on a home marker, which is defined for paths
    # that do not exist), so synthetic absolute roots are enough -- and a synthetic root
    # placed under /tmp would sit inside the engine's own temp-root carve-out and grant
    # everything, which is exactly how the first draft of this file fooled itself.
    ws = "/synthetic-workspace"
    home = "/synthetic-member-home"
    scopes = ("granted",)
    seat = lift(GATE, ws, home)
    profile = core.HarnessProfile(
        member_id="gemini",
        identity_path=home + "/identity.json",
        home_markers=(home,),
        launch_cwd_env="HESTIA_GEMINI_LAUNCH_CWD",
    )

    print(f"gate under test : {GATE.relative_to(ROOT)}")
    print(f"predicates      : {', '.join(sorted(LIFT))}")
    print(f"scopes          : {scopes}")
    print()
    hdr = f"{'case':<20}{'expect':>8}{'engine':>8}{'seat':>7}   {'':<14}defect class"
    print(hdr)
    print("-" * 120)
    diverged, engine_wrong = [], []
    for label, path, expect, why in cases(ws, home):
        e = core.path_in_scope(path, scopes, ws, profile, cwd=ws)
        s_ = seat["path_in_scope"](path, scopes)
        if e != expect:
            engine_wrong.append((label, path, expect, e))
        if e != s_:
            diverged.append((label, path, e, s_, why))
        print(f"{label:<20}{str(expect):>8}{str(e):>8}{str(s_):>7}"
              f"{('  <-- DIVERGES' if e != s_ else ''):<17}{why}")
    print("-" * 120)

    # The engine's own answers first. If the hardened implementation does not give the
    # answer its docstring claims, this harness is measuring its own setup (or the engine
    # regressed), and every divergence below is noise. Either way: stop, do not report a
    # number. Agreement between two implementations is not evidence that either is right.
    if engine_wrong:
        print("\n::error::the SHARED ENGINE did not give the pinned answer. This harness is "
              "not measuring what it says -- do not read the divergence count.", file=sys.stderr)
        for label, path, expect, e in engine_wrong:
            print(f"    {label}: expected {expect}, engine said {e}  ({path})", file=sys.stderr)
        return 1

    over = [d for d in diverged if d[3] and not d[2]]
    print(f"\ndiverging inputs: {len(diverged)} of {len(cases(ws, home))}   "
          f"of which SEAT GRANTS WHAT THE ENGINE DENIES: {len(over)}")
    for label, path, e, s_, why in diverged:
        print(f"\n  {label:<20}"
              f"{'SEAT GRANTS WHAT THE ENGINE DENIES' if s_ and not e else 'seat denies what the engine grants'}")
        print(f"      input : {path}")
        print(f"      class : {why}")

    if args.max_divergences is not None:
        print(f"\nratchet divergences: {len(diverged)} vs limit {args.max_divergences}")
        if len(diverged) > args.max_divergences:
            print(f"::error::forked scope predicates diverge from the shared engine on "
                  f"{len(diverged)} inputs, above the pinned {args.max_divergences}",
                  file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
