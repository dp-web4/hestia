#!/usr/bin/env python3
"""How much of the gate still executes per-seat instead of in the shared engine.

WHY THIS EXISTS. "The seats all import the shared closure" has been true, and reported as
done, for weeks. It was never the question. Every seat imports the shared engine AND keeps
its own copy of law-bearing code wrapped around it, so a fix lands in one seat's file, CI
runs each seat's tests from its own directory, everything is green, and the seats drift.
The claim that could not be over-reported is a RATIO, not a verdict:

    how many decision-making lines still live in a per-seat file?

Collapsed means that number is zero. Until then it is a percentage, and this file is what
prints it. A verdict can be sincere and wrong. A number that goes to zero cannot.

TWO MEASUREMENTS, because one of them takes a judgment call and one does not.

  1. REDEFINED (no judgment). A function defined in a seat file whose name is also defined
     in the shared engine. That is not a wrapper, it is a second implementation of a name
     the shared engine already owns: the exact shape that lets two seats answer the same
     question differently. Nothing here is a matter of opinion, which is why this is the
     number CI ratchets on.

  2. LAW-BEARING LOCAL (judgment, and the judgment is printed). A seat-local function whose
     source mentions the decision vocabulary below. It over-counts on purpose: a helper that
     merely formats a deny message is counted. An over-count that shrinks to zero is still a
     usable meter, and the vocabulary is in the file so the call can be argued with.

GRAIN: one Python function definition, at any nesting depth, in a seat's pre_tool_use.py.
SLOC: end_lineno - lineno + 1 (blank and comment lines included; the same rule on both
sides of the ratio, which is what makes it a ratio).
PRODUCER: this file, over the three seat hooks and plugins/_shared/hestia_*.py, on whatever
tree it is run in. It holds no opinion about the topology: if a seat is added or the shared
engine is renamed, discovery below picks it up and no line here needs editing.

Exit status is a verdict, not an error:
  0  the ratchet held (redefined count <= --max-redefined)
  1  the ratchet broke, or discovery found nothing to measure
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# Printed in the report, so the classifier can be argued with instead of trusted.
LAW_VOCABULARY = (
    "deny", "denied", "allow", "refuse", "refused", "escalat", "classif",
    "marker", "claim", "permits_write", "governance", "gate", "approve",
)

SHARED_GLOB = "hestia_*.py"
SEAT_HOOK = "hooks/pre_tool_use.py"


def repo_root(start: Path) -> Path:
    """Walk up to the checkout this file sits in. No literal path is spelled here."""
    for p in [start, *start.parents]:
        if (p / "plugins" / "_shared").is_dir():
            return p
    raise SystemExit("cannot determine: no plugins/_shared above this file")


def shared_symbols(shared_dir: Path) -> tuple[set[str], list[Path]]:
    """Every name the shared engine defines. Tests are not the engine."""
    names: set[str] = set()
    files: list[Path] = []
    for f in sorted(shared_dir.glob(SHARED_GLOB)):
        if f.name.endswith("_test.py"):
            continue
        files.append(f)
        tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"), filename=str(f))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
    return names, files


def seat_functions(path: Path):
    """Every function a seat defines, with its own source extent."""
    src = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src, filename=str(path))
    lines = src.splitlines()
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            body = "\n".join(lines[node.lineno - 1:end]).lower()
            out.append({
                "name": node.name,
                "sloc": end - node.lineno + 1,
                "line": node.lineno,
                "law_bearing": any(v in body or v in node.name.lower() for v in LAW_VOCABULARY),
            })
    return out, len(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-redefined", type=int, default=None,
                    help="ratchet: fail if the redefined-function count exceeds this")
    ap.add_argument("--max-pct", type=float, default=None,
                    help="ratchet: fail if the still-per-seat percentage exceeds this. "
                         "This is the number that matters; --max-redefined is the one "
                         "that is beyond argument. Pin both.")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = repo_root(Path(__file__).resolve())
    shared_dir = root / "plugins" / "_shared"
    names, shared_files = shared_symbols(shared_dir)

    seats = sorted(p.parent.parent for p in root.glob(f"plugins/*/{SEAT_HOOK}"))
    # A discovery that matches nothing must fail loudly. Silent zero reads as collapsed,
    # which is the failure this whole file exists to refuse.
    if not seats:
        print("cannot determine: no seat hooks discovered", file=sys.stderr)
        return 1
    if not names:
        print("cannot determine: shared engine defines no symbols", file=sys.stderr)
        return 1

    print(f"shared engine : {len(shared_files)} module(s), {len(names)} names")
    for f in shared_files:
        print(f"                {f.name}")
    print(f"vocabulary    : {', '.join(LAW_VOCABULARY)}")
    print()

    tot_redef = tot_redef_sloc = tot_law = tot_local = 0
    rows = []
    for seat in seats:
        fns, filelines = seat_functions(seat / SEAT_HOOK)
        redef = [f for f in fns if f["name"] in names]
        law = [f for f in fns if f["law_bearing"]]
        local_sloc = sum(f["sloc"] for f in fns)
        rows.append((seat.name, len(fns), len(redef), sum(f["sloc"] for f in redef),
                     len(law), sum(f["sloc"] for f in law), local_sloc, filelines, redef))
        tot_redef += len(redef)
        tot_redef_sloc += sum(f["sloc"] for f in redef)
        tot_law += sum(f["sloc"] for f in law)
        tot_local += local_sloc

    hdr = f"{'seat':<14}{'funcs':>7}{'redef':>7}{'redef':>8}{'law':>7}{'law':>8}{'local':>8}{'file':>8}"
    print(hdr)
    print(f"{'':<14}{'':>7}{'':>7}{'sloc':>8}{'fns':>7}{'sloc':>8}{'sloc':>8}{'lines':>8}")
    print("-" * len(hdr))
    for name, nf, nr, nrs, nl, nls, ls, fl, _ in rows:
        print(f"{name:<14}{nf:>7}{nr:>7}{nrs:>8}{nl:>7}{nls:>8}{ls:>8}{fl:>8}")
    print("-" * len(hdr))
    print(f"{'TOTAL':<14}{'':>7}{tot_redef:>7}{tot_redef_sloc:>8}{'':>7}{tot_law:>8}{tot_local:>8}")
    print()

    if not args.quiet:
        for name, _, _, _, _, _, _, _, redef in rows:
            if redef:
                print(f"{name}: redefines names the shared engine already owns")
                for f in sorted(redef, key=lambda r: -r["sloc"]):
                    print(f"    {f['sloc']:>5} sloc  line {f['line']:>5}  {f['name']}")
                print()

    # The per-seat law figure means nothing on its own: 3,000 lines is small next to a
    # 30,000-line engine and enormous next to a 3,000-line one. Measure the shared side
    # with the SAME classifier and the SAME grain, or the ratio is two different rulers.
    shared_law = 0
    for f in shared_files:
        fns, _ = seat_functions(f)
        shared_law += sum(x["sloc"] for x in fns if x["law_bearing"])
    total_law = tot_law + shared_law
    pct = (100.0 * tot_law / total_law) if total_law else 0.0

    print(f"COLLAPSE METER: {tot_redef} redefined function(s), {tot_redef_sloc} sloc.")
    print(f"law-bearing sloc: {tot_law} per-seat + {shared_law} shared = {total_law}")
    print(f"STILL PER-SEAT: {pct:.1f}%   (collapsed means 0.0%, and 0 redefined)")

    # Print the compared value on BOTH sides, always. A threshold guard that prints only
    # its verdict rots silently as the codebase grows: nobody can see it drifting toward
    # the limit until the day it crosses.
    failed = False
    if args.max_redefined is not None:
        print(f"ratchet redefined: {tot_redef} vs limit {args.max_redefined}")
        if tot_redef > args.max_redefined:
            print(f"::error::gate collapse regressed: {tot_redef} redefined functions "
                  f"exceeds the pinned limit of {args.max_redefined}", file=sys.stderr)
            failed = True
    if args.max_pct is not None:
        print(f"ratchet per-seat : {pct:.1f}% vs limit {args.max_pct:.1f}%")
        if pct > args.max_pct:
            print(f"::error::gate collapse regressed: {pct:.1f}% of law-bearing code is "
                  f"per-seat, above the pinned {args.max_pct:.1f}%. The engine is "
                  f"re-forking.", file=sys.stderr)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
