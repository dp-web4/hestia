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

  1. FORKED (no judgment), in two grades, because one number was hiding two opposite risks.
     A seat function whose name the shared engine already owns AND whose body is not a
     delegating call. The grade is decided by comparing the two SOURCE TEXTS:

       DIVERGENT -- the bodies differ. Two implementations of one name, free to answer the
       same question differently. This is the shape the ratchet exists to stop, and it is
       the tight pin.

       VERBATIM -- the seat's source is character-for-character the shared engine's. Real
       debt (two copies to deploy, two places to edit) but provably not divergence: there is
       no input on which they can disagree, because they are the same program.

     Counting these as one number made the deploy-safe collapse of the largest seat
     unlandable. A seat imports the shared module from the INSTALLED path, so a move must
     publish first and delete in the follow-on release; between those merges the moved
     functions are duplicated ON PURPOSE. Under a single pin that transient reads exactly
     like drift, so the ratchet forbade the publish step -- while the four forks it was
     already tolerating carried 100% of the fleet's actual divergence. The instrument would
     again have gone red at the moment the work it measures succeeded.

     This is a tightening, not an exemption. Nothing is annotated and nothing is trusted:
     the grade is recomputed from source on every run, so the day a verbatim copy is edited
     it becomes DIVERGENT and trips the tight pin immediately -- which the old count-only
     ratchet would have missed entirely, since the count did not move. Reindentation also
     reads as divergent; the comparison errs toward the strict grade.

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
    # Renders a ruling the daemon already made, on this harness's context port. It reads one
    # file and prints one string: no predicate, no verdict, and it cannot block a call. Same
    # class as witness.py, one direction over -- that one records what happened, this one
    # reports what was decided (PRD_DISPOSITION_DELIVERY R4).
    "disposition_deliver.py",
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
    sources: dict[str, str] = {}
    for f in sorted(shared_dir.glob(SHARED_GLOB)):
        if is_test(f):
            continue
        files.append(f)
        src = f.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(f))
        # TOP LEVEL ONLY, and this is a correction rather than a tightening. `ast.walk`
        # collected NESTED functions too, so a private closure inside a shared function
        # became "a name the engine owns" -- and any unrelated local helper in a seat that
        # happened to share the name read as a second implementation of it. Caught when the
        # first real collapse slice moved `emit_attestation` in, whose internal `post` helper
        # instantly "forked" the unrelated `post` closures in codex and kimi and pushed the
        # ratchet from 4 to 6. The instrument would have gone red at the exact moment the
        # work it measures succeeded. A closure is not API; only what a seat could actually
        # import can be forked.
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
                if not isinstance(node, ast.ClassDef):
                    # First definition wins, matching `names`: if two shared modules define
                    # the same name the engine is already inconsistent, and a seat matching
                    # either one is not the thing this grade is claiming.
                    sources.setdefault(node.name, ast.get_source_segment(src, node) or "")
    return names, files, sources


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


def is_verbatim(fn: dict, shared_sources: dict) -> bool:
    """True when a fork's source is character-for-character the shared engine's.

    Equal text cannot disagree on any input, so such a copy is duplicate law (two places to
    deploy, two places to edit) but provably not divergence. Everything else is DIVERGENT,
    including a copy that differs only by indentation: the grade errs strict, because the
    cost of calling a divergent fork verbatim is an undetected second law, and the cost of
    calling a verbatim fork divergent is one honest line of ratchet noise.

    Recomputed from source on every run. There is no annotation to trust and nothing a seat
    can assert about itself -- editing a verbatim copy re-grades it on the next CI run."""
    return bool(fn.get("source")) and fn["source"] == shared_sources.get(fn["name"])


def module_functions(path: Path):
    """Every function a module defines, with its own source extent and classification."""
    src = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src, filename=str(path))
    lines = src.splitlines()
    out = []
    top = {id(n) for n in tree.body}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            body = "\n".join(lines[node.lineno - 1:end]).lower()
            out.append({
                "name": node.name,
                "sloc": end - node.lineno + 1,
                "line": node.lineno,
                "top_level": id(node) in top,
                "delegates": delegates(node),
                "law_bearing": any(v in body or v in node.name.lower() for v in LAW_VOCABULARY),
                "source": ast.get_source_segment(src, node) or "",
            })
    return out, len(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-forked", type=int, default=None,
                    help="ratchet: fail if the TOTAL forked-function count exceeds this")
    ap.add_argument("--max-divergent-forked", type=int, default=None,
                    help="ratchet: fail if the count of forks whose source DIFFERS from the "
                         "shared engine's exceeds this. The tight pin: these are the forks "
                         "that can answer a question two ways.")
    ap.add_argument("--max-verbatim-forked", type=int, default=None,
                    help="ratchet: fail if the count of forks that are character-for-"
                         "character the shared engine's exceeds this. Duplicate law with a "
                         "receipt -- a move that has published but not yet deleted. Declared "
                         "so it is visible, and it must come back down.")
    ap.add_argument("--max-pct", type=float, default=None,
                    help="ratchet: fail if the still-per-seat percentage exceeds this. "
                         "This is the number that matters; --max-forked is the one that is "
                         "beyond argument. Pin both.")
    ap.add_argument("--max-seat-pct", action="append", default=[], metavar="SEAT=PCT",
                    help="per-seat ceiling on local law %% (#771); repeatable; a named seat "
                         "that is not discovered fails, since unmeasurable is not compliant")
    ap.add_argument("--min-agreed-keys", type=int, default=None,
                    help="ratchet the OTHER half of the gate: fail if the number of path-key "
                         "names every seat extracts falls below this. The predicate is shared; "
                         "the domain it is applied to is not, and nothing gated it before.")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = repo_root(Path(__file__).resolve())
    names, shared_files, shared_sources = shared_symbols(root / "plugins" / "_shared")
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
    tot_div = tot_verb = 0
    rows = []
    for seat, path in gates:
        fns, filelines = module_functions(path)
        same = [f for f in fns if f["name"] in names and f["top_level"]]
        fork = [f for f in same if not f["delegates"]]
        for f in fork:
            f["verbatim"] = is_verbatim(f, shared_sources)
        adapt = [f for f in same if f["delegates"]]
        law = [f for f in fns if f["law_bearing"]]
        local_sloc = sum(f["sloc"] for f in fns)
        rows.append((seat, len(fns), fork, adapt, len(law),
                     sum(f["sloc"] for f in law), local_sloc, filelines))
        tot_fork += len(fork)
        tot_fork_sloc += sum(f["sloc"] for f in fork)
        tot_div += sum(1 for f in fork if not f["verbatim"])
        tot_verb += sum(1 for f in fork if f["verbatim"])
        tot_adapt += len(adapt)
        tot_law += sum(f["sloc"] for f in law)
        tot_local += local_sloc

    hdr = (f"{'seat':<14}{'funcs':>7}{'diver':>6}{'verb':>6}{'fork':>7}{'adapt':>7}"
           f"{'law':>6}{'law':>7}{'local':>8}{'file':>7}")
    print(hdr)
    print(f"{'':<14}{'':>7}{'gent':>6}{'atim':>6}{'sloc':>7}{'':>7}"
          f"{'fns':>6}{'sloc':>7}{'sloc':>8}{'lines':>7}")
    print("-" * len(hdr))
    for seat, nf, fork, adapt, nl, nls, ls, fl in rows:
        nd = sum(1 for f in fork if not f["verbatim"])
        nv = sum(1 for f in fork if f["verbatim"])
        print(f"{seat:<14}{nf:>7}{nd:>6}{nv:>6}{sum(f['sloc'] for f in fork):>7}"
              f"{len(adapt):>7}{nl:>6}{nls:>7}{ls:>8}{fl:>7}")
    print("-" * len(hdr))
    print(f"{'TOTAL':<14}{'':>7}{tot_div:>6}{tot_verb:>6}{tot_fork_sloc:>7}{tot_adapt:>7}"
          f"{'':>6}{tot_law:>7}{tot_local:>8}")
    print()

    # THE UNSHARED FORK SURFACE, and it is the one that names the WORK.
    #
    # FORKED above can only count names the shared engine ALREADY owns -- a seat overriding
    # something that was successfully shared once. That set is small here (4) precisely
    # because the sharing mostly never happened: you cannot override a name nobody shared.
    #
    # This counts the other direction: a name defined in TWO OR MORE gates that no shared
    # module owns at all. Nobody is overriding anything, so nothing flags -- and yet two
    # seats are answering the same question with two bodies, each seat's tests pass from its
    # own directory, and CI compares them never. That is the fork surface that produced
    # every drift incident to date, and every name in this list is a candidate to MOVE into
    # the shared engine rather than to delete.
    by_name = {}
    for seat, path in gates:
        fns, _ = module_functions(path)
        for f in fns:
            if f["name"] in names:
                continue  # shared owns it: that is the FORKED/ADAPTER axis, counted above
            by_name.setdefault(f["name"], []).append((seat, f))
    unshared = {n: v for n, v in by_name.items() if len({s for s, _ in v}) > 1}
    law_unshared = {n: v for n, v in unshared.items() if any(f["law_bearing"] for _, f in v)}
    unshared_sloc = sum(f["sloc"] for v in law_unshared.values() for _, f in v)

    print(f"UNSHARED FORK SURFACE: {len(unshared)} name(s) live in 2+ gates and are owned by "
          f"NO shared module; {len(law_unshared)} law-bearing, {unshared_sloc} sloc.")
    print("These are candidates to MOVE into the engine. Nothing flags them today.")
    if not args.quiet and law_unshared:
        for n, v in sorted(law_unshared.items(),
                           key=lambda kv: -sum(f["sloc"] for _, f in kv[1])):
            spread = sum(f["sloc"] for _, f in v)
            where = "  ".join(f"{s}:{f['sloc']}" for s, f in sorted(v))
            print(f"    {spread:>5} sloc  {n:<36} {where}")
    print()

    if not args.quiet:
        for seat, _, fork, adapt, _, _, _, _ in rows:
            if fork:
                print(f"{seat}: FORKS names the shared engine owns")
                for f in sorted(fork, key=lambda r: -r["sloc"]):
                    grade = "verbatim " if f["verbatim"] else "DIVERGENT"
                    print(f"    {grade} {f['sloc']:>5} sloc  line {f['line']:>5}  {f['name']}")
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

    print(f"COLLAPSE METER: {tot_fork} forked function(s) "
          f"({tot_div} divergent, {tot_verb} verbatim), {tot_fork_sloc} sloc; "
          f"{tot_adapt} adapter(s) (not counted against the ratchet).")
    print(f"law-bearing sloc: {tot_law} per-seat + {shared_law} shared = {total_law}")
    # PER SEAT FIRST (#771). One fleet number is a trend, not a compliance signal: one shim
    # adding local authority moves it for everyone, and three nearly-empty adapters can
    # dilute one badly forked shim. The unit is the seat, and the ratio is that seat's own
    # law against the SAME shared engine, same classifier, same grain.
    seat_pct = {}
    for seat, nf, fork, adapt, nl, nls, ls, fl in rows:
        seat_pct[seat] = (100.0 * nls / (nls + shared_law)) if (nls + shared_law) else 0.0
    print("PER-SEAT LOCAL LAW (seat law / (seat law + shared law)):")
    for seat, v in seat_pct.items():
        print(f"    {seat:<13} {v:>5.1f}%")
    print(f"TREND (secondary, not a verdict) STILL PER-SEAT: {pct:.1f}%   "
          f"(collapsed means 0.0%, and 0 forked)")

    # The percentage above measures the PREDICATE. It says nothing about the domain the
    # predicate is applied to, and that domain is built per-seat before the engine is called
    # (#734). A gate can score 0.0% here and still disagree with every other seat about which
    # argument is a path. Printed unconditionally, next to the number it qualifies, so the
    # collapse figure is never read as covering both halves.
    agreed_n = union_n = None
    try:
        from path_key_vocabulary_probe import gate_key_vocabularies  # lazy: probe imports us
        vocab = gate_key_vocabularies(root)
        per_seat = {s: d["keys"] for s, d in vocab.items()}
        union = set().union(*per_seat.values())
        agreed = set.intersection(*per_seat.values())
        agreed_n, union_n = len(agreed), len(union)
        print(f"EXTRACTION DOMAIN: {agreed_n} of {union_n} path-key names are extracted by all "
              f"{len(per_seat)} seats   (collapsed means agreed == union)")
        for seat in sorted(per_seat):
            missing = sorted(union - per_seat[seat])
            if missing:
                print(f"    {seat:<13} omits {len(missing):>2}: {', '.join(missing)}")
    except Exception as exc:
        # Loud, never silent. An extraction figure that vanishes on error would let the
        # per-seat percentage be quoted alone again, which is the exact gap this line closes.
        print(f"EXTRACTION DOMAIN: cannot determine ({type(exc).__name__}: {exc})")

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
    if args.max_divergent_forked is not None:
        print(f"ratchet divergent: {tot_div} vs limit {args.max_divergent_forked}")
        if tot_div > args.max_divergent_forked:
            print(f"::error::gate collapse regressed: {tot_div} DIVERGENT forked functions "
                  f"exceeds the pinned limit of {args.max_divergent_forked}. Two bodies for "
                  f"one name can answer one question two ways.", file=sys.stderr)
            failed = True
    if args.max_verbatim_forked is not None:
        print(f"ratchet verbatim : {tot_verb} vs limit {args.max_verbatim_forked}")
        if tot_verb > args.max_verbatim_forked:
            print(f"::error::duplicate law grew: {tot_verb} verbatim copies of shared "
                  f"functions exceeds the pinned limit of {args.max_verbatim_forked}. A "
                  f"published-but-not-yet-deleted move is allowed, but it is DECLARED here "
                  f"and the follow-on release must bring this back down.", file=sys.stderr)
            failed = True
    for bound in args.max_seat_pct or []:
        seat, _, lim = bound.partition("=")
        if not seat or not lim:
            print(f"::error::bad --max-seat-pct {bound!r}; want SEAT=PCT", file=sys.stderr)
            failed = True
            continue
        lim = float(lim)
        if seat not in seat_pct:
            # A pinned seat that is not in the tree is INDETERMINATE, and indeterminate is not
            # a pass: a seat that vanished from discovery would otherwise read as compliant.
            print(f"::error::--max-seat-pct names {seat!r}, which is not a discovered gate "
                  f"({', '.join(seat_pct)}). Unmeasurable is not compliant.", file=sys.stderr)
            failed = True
            continue
        shown = round(seat_pct[seat], 1)
        print(f"ratchet seat {seat:<12}: {shown:.1f}% vs limit {lim:.1f}%")
        if shown > lim:
            print(f"::error::{seat} regressed: {shown:.1f}% of its law is local, above its "
                  f"pinned {lim:.1f}%. This names the seat; the other seats' numbers are "
                  f"unchanged by it.", file=sys.stderr)
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
    if args.min_agreed_keys is not None:
        if agreed_n is None:
            print("::error::extraction domain could not be measured, so its ratchet cannot "
                  "pass. Treating unmeasurable as failing.", file=sys.stderr)
            failed = True
        else:
            print(f"ratchet key-agree: {agreed_n} of {union_n} vs floor "
                  f"{args.min_agreed_keys}")
            if agreed_n < args.min_agreed_keys:
                print(f"::error::extraction domain diverged: only {agreed_n} of {union_n} "
                      f"path-key names are extracted by every seat, below the pinned floor of "
                      f"{args.min_agreed_keys}. A seat is reaching for a different domain than "
                      f"the law was written against.", file=sys.stderr)
                failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
