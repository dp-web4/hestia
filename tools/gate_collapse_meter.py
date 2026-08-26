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

THREE MEASUREMENTS. The first two are mechanical; the third takes a judgment call and prints
the judgment so it can be argued with rather than trusted.

  1. FORKED (no judgment). A seat function whose name the shared engine already owns AND
     whose body is a second implementation. That is the shape that lets two seats answer the
     same question differently, so it is what CI ratchets on.

  2. ADAPTER (no judgment, and NOT a fork). Same name, but the body is one delegating call
     to the shared name -- `return _core.path_in_scope(...)`. That is the collapse pattern
     working, not a regression, and an earlier draft of this file counted it as a fork: it
     charged kimi 2 violations for having done the correct thing and gemini 4 for carrying
     four genuine second implementations, at the same weight. A meter that scores the cure
     and the disease alike cannot steer the work. The test is structural (one Return of one
     Call to the same attribute name), never vocabulary.

  3. LAW-BEARING LOCAL (judgment, printed). A seat-local function whose source mentions the
     decision vocabulary below. It over-counts on purpose: a helper that merely formats a
     deny message is counted. An over-count that shrinks to zero is still a usable meter.

DISCOVERY IS THE PART THAT CAN LIE. The first version of this file found seats by one
hard-coded basename, `hooks/pre_tool_use.py`, while claiming in this docstring that "if a
seat is added, discovery picks it up". gemini's gate is `hooks/before_tool.py`. It was
therefore absent from every number the meter printed and from the ratchet -- an installed,
wired, non-dead gate carrying FOUR forked scope predicates, sitting in the blind spot of the
guard whose whole job is to notice forked scope predicates. Discovery now classifies EVERY
hook module in EVERY plugin as gate or non-gate, and an unrecognised one is a hard failure.
A new gate cannot be added silently; it can only be added loudly or declared.

GRAIN: one Python function definition, at any nesting depth, in a discovered gate module.
SLOC: end_lineno - lineno + 1 (blank and comment lines included; the same rule on both
sides of the ratio, which is what makes it a ratio).

Exit status is a verdict, not an error:
  0  the ratchet held
  1  the ratchet broke, or discovery found nothing, or discovery found something it could
     not classify
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

# A gate is a hook module that decides. Both spellings below are live in this tree; the
# fleet never standardised the basename, which is exactly how one of them stayed invisible.
GATE_BASENAMES = ("pre_tool_use.py", "before_tool.py")

# Hook modules declared NOT to decide. This list is the point of the coverage check: a hook
# that is neither a known gate nor declared here stops the run, so the call is always made
# by a person in a diff and never by a glob that happens to miss.
NON_GATE_BASENAMES = (
    "witness.py",      # records what happened; holds no verdict
    "law_inject.py",   # puts the law in context; does not apply it
    "__init__.py",
)


def repo_root(start: Path) -> Path:
    """Walk up to the checkout this file sits in. No literal path is spelled here."""
    for p in [start, *start.parents]:
        if (p / "plugins" / "_shared").is_dir():
            return p
    raise SystemExit("cannot determine: no plugins/_shared above this file")


def is_test(path: Path) -> bool:
    return path.name.endswith("_test.py") or path.name.startswith("test_")


def discover_gates(root: Path):
    """Every gate in the tree, plus anything that could not be classified.

    A non-empty `unclassified` is a stop, not a warning."""
    gates = []
    unclassified = []
    for pdir in sorted((root / "plugins").iterdir()):
        hooks = pdir / "hooks"
        if not hooks.is_dir():
            continue
        for f in sorted(hooks.glob("*.py")):
            if is_test(f):
                continue
            if f.name in GATE_BASENAMES:
                gates.append((pdir.name, f))
            elif f.name not in NON_GATE_BASENAMES:
                unclassified.append(f.relative_to(root))
    return gates, unclassified


def shared_symbols(shared_dir: Path):
    """Every name the shared engine defines. Tests are not the engine."""
    names = set()
    files = []
    for f in sorted(shared_dir.glob(SHARED_GLOB)):
        if is_test(f):
            continue
        files.append(f)
        tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"), filename=str(f))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
    return names, files


def delegates(node) -> bool:
    """True when the body is exactly one call forwarding to the same name elsewhere.

    Structural on purpose. `return _core.path_in_scope(path, scopes, WORKSPACE, ...)` is a
    call-site adapter: the seat keeps its local call shape and the answer comes from the one
    implementation. Anything with a second statement, a branch, or a call to a DIFFERENT
    name is not delegating and is counted as a fork."""
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]                       # drop the docstring
    if len(body) != 1:
        return False
    stmt = body[0]
    call = stmt.value if isinstance(stmt, (ast.Return, ast.Expr)) else None
    if not isinstance(call, ast.Call):
        return False
    func = call.func
    return isinstance(func, ast.Attribute) and func.attr == node.name


def module_functions(path: Path):
    """Every function a module defines, with its own source extent and classification."""
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
                "delegates": delegates(node),
                "law_bearing": any(v in body or v in node.name.lower() for v in LAW_VOCABULARY),
            })
    return out, len(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-forked", type=int, default=None,
                    help="ratchet: fail if the forked-function count exceeds this")
    ap.add_argument("--max-pct", type=float, default=None,
                    help="ratchet: fail if the still-per-seat percentage exceeds this. "
                         "This is the number that matters; --max-forked is the one that is "
                         "beyond argument. Pin both.")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = repo_root(Path(__file__).resolve())
    names, shared_files = shared_symbols(root / "plugins" / "_shared")
    gates, unclassified = discover_gates(root)

    # A discovery that matches nothing must fail loudly. Silent zero reads as collapsed,
    # which is the failure this whole file exists to refuse.
    if not gates:
        print("cannot determine: no gate modules discovered", file=sys.stderr)
        return 1
    if not names:
        print("cannot determine: shared engine defines no symbols", file=sys.stderr)
        return 1
    if unclassified:
        print("cannot determine: hook module(s) that are neither a known gate nor declared "
              "non-deciding. Add the basename to GATE_BASENAMES or NON_GATE_BASENAMES -- "
              "guessing here is how gemini's gate went unmeasured:", file=sys.stderr)
        for f in unclassified:
            print(f"    {f}", file=sys.stderr)
        return 1

    print(f"shared engine : {len(shared_files)} module(s), {len(names)} names")
    for f in shared_files:
        print(f"                {f.name}")
    print(f"gates         : {len(gates)} discovered")
    for seat, f in gates:
        print(f"                {seat:<14} {f.relative_to(root)}")
    print(f"vocabulary    : {', '.join(LAW_VOCABULARY)}")
    print()

    tot_fork = tot_fork_sloc = tot_adapt = tot_law = tot_local = 0
    rows = []
    for seat, path in gates:
        fns, filelines = module_functions(path)
        same = [f for f in fns if f["name"] in names]
        fork = [f for f in same if not f["delegates"]]
        adapt = [f for f in same if f["delegates"]]
        law = [f for f in fns if f["law_bearing"]]
        local_sloc = sum(f["sloc"] for f in fns)
        rows.append((seat, len(fns), fork, adapt, len(law),
                     sum(f["sloc"] for f in law), local_sloc, filelines))
        tot_fork += len(fork)
        tot_fork_sloc += sum(f["sloc"] for f in fork)
        tot_adapt += len(adapt)
        tot_law += sum(f["sloc"] for f in law)
        tot_local += local_sloc

    hdr = (f"{'seat':<14}{'funcs':>7}{'fork':>6}{'fork':>7}{'adapt':>7}"
           f"{'law':>6}{'law':>7}{'local':>8}{'file':>7}")
    print(hdr)
    print(f"{'':<14}{'':>7}{'':>6}{'sloc':>7}{'':>7}{'fns':>6}{'sloc':>7}{'sloc':>8}{'lines':>7}")
    print("-" * len(hdr))
    for seat, nf, fork, adapt, nl, nls, ls, fl in rows:
        print(f"{seat:<14}{nf:>7}{len(fork):>6}{sum(f['sloc'] for f in fork):>7}"
              f"{len(adapt):>7}{nl:>6}{nls:>7}{ls:>8}{fl:>7}")
    print("-" * len(hdr))
    print(f"{'TOTAL':<14}{'':>7}{tot_fork:>6}{tot_fork_sloc:>7}{tot_adapt:>7}"
          f"{'':>6}{tot_law:>7}{tot_local:>8}")
    print()

    if not args.quiet:
        for seat, _, fork, adapt, _, _, _, _ in rows:
            if fork:
                print(f"{seat}: FORKS names the shared engine owns (second implementations)")
                for f in sorted(fork, key=lambda r: -r["sloc"]):
                    print(f"    {f['sloc']:>5} sloc  line {f['line']:>5}  {f['name']}")
            if adapt:
                print(f"{seat}: adapts (delegates to the shared name -- this is the cure)")
                for f in sorted(adapt, key=lambda r: -r["sloc"]):
                    print(f"    {f['sloc']:>5} sloc  line {f['line']:>5}  {f['name']}")
            if fork or adapt:
                print()

    # The per-seat law figure means nothing on its own: 3,000 lines is small next to a
    # 30,000-line engine and enormous next to a 3,000-line one. Measure the shared side
    # with the SAME classifier and the SAME grain, or the ratio is two different rulers.
    shared_law = 0
    for f in shared_files:
        fns, _ = module_functions(f)
        shared_law += sum(x["sloc"] for x in fns if x["law_bearing"])
    total_law = tot_law + shared_law
    pct = (100.0 * tot_law / total_law) if total_law else 0.0

    print(f"COLLAPSE METER: {tot_fork} forked function(s), {tot_fork_sloc} sloc; "
          f"{tot_adapt} adapter(s) (not counted against the ratchet).")
    print(f"law-bearing sloc: {tot_law} per-seat + {shared_law} shared = {total_law}")
    print(f"STILL PER-SEAT: {pct:.1f}%   (collapsed means 0.0%, and 0 forked)")

    # Print the compared value on BOTH sides, always. A threshold guard that prints only its
    # verdict rots silently as the codebase grows: nobody can see it drifting toward the
    # limit until the day it crosses.
    failed = False
    if args.max_forked is not None:
        print(f"ratchet forked   : {tot_fork} vs limit {args.max_forked}")
        if tot_fork > args.max_forked:
            print(f"::error::gate collapse regressed: {tot_fork} forked functions exceeds "
                  f"the pinned limit of {args.max_forked}", file=sys.stderr)
            failed = True
    if args.max_pct is not None:
        # Compare the number that is PRINTED, not the float behind it. The first version
        # compared raw 69.31747... against a limit reported as "69.3%", so a pin written
        # from the tool's own output failed against the tool's own output. A guard whose
        # displayed value and compared value differ teaches everyone to distrust the display.
        shown = round(pct, 1)
        print(f"ratchet per-seat : {shown:.1f}% vs limit {args.max_pct:.1f}%")
        if shown > args.max_pct:
            print(f"::error::gate collapse regressed: {pct:.1f}% of law-bearing code is "
                  f"per-seat, above the pinned {args.max_pct:.1f}%. The engine is "
                  f"re-forking.", file=sys.stderr)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
