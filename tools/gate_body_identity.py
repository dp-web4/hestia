#!/usr/bin/env python3
"""How much of the un-collapsed gate surface is ONE law spelled N times?

`tools/gate_collapse_meter.py` answers "how much law still lives in seat files" (67.5%) and
names the 15 functions that live in 2+ gates with no shared owner. It does NOT answer the
question that decides the collapse SCHEDULE: of those duplicated bodies, how many are the
same code, and how many are genuinely different answers to the same question?

The difference is the whole plan. A duplicate that is byte-identical modulo comments is a
MOVE -- mechanical, reviewable in one diff, no behaviour to argue about. A duplicate whose
bodies diverge is a MERGE, and every divergence is one of exactly two things:

  * a BUG in the copy nobody was measuring (this is what `scope_fork_differential_test.py`
    found: 6 of 12 inputs diverged, all 6 the seat granting what the engine denies), or
  * a real per-harness difference, which belongs in a profile record and not in a fork.

Neither can be settled by a ratio, so this tool does not try. It classifies, prints the
evidence for each class, and leaves the judgement in the diff where a person can argue with
it.

## What it compares

For every function name defined in 2+ gates and owned by no shared module, the bodies are
compared as NORMALISED AST DUMPS: `ast.dump` with line/column attributes dropped and the
leading docstring removed. That normalisation deliberately keeps every string constant and
every identifier -- a different marker, a different plugin id, or a read of a different
global IS different law, and folding those away would manufacture agreement. What it drops
is exactly what carries no behaviour: comments, docstrings, formatting, line numbers.

Two bodies are:

  IDENTICAL  -- normalised dumps equal. The seats hold the same code. Collapsing is a move.
  NEAR       -- dumps differ, similarity >= --near (default 0.90). Same shape, small delta;
                the delta is printed, because it is either the bug or the profile knob.
  DIVERGENT  -- below --near. Same name, different answer. Read before touching.

Similarity is `difflib.SequenceMatcher` over the dumps. It orders work; it is not evidence.
The evidence is the printed delta.

## Why a pair-wise report and not a single number

With four gates a name can be identical in two seats and divergent in a third -- `main` is
exactly that. A single per-name verdict would have to pick a winner, and the seat it dropped
would be the one carrying the surprise. Every unordered pair is scored, and a name's class is
the WORST class among its pairs, so nothing is collapsed on the strength of its easiest pair.

Exit is 0 always: this reports, it does not gate. The ratchet lives in the meter.
"""

import argparse
import ast
import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate_collapse_meter import (  # noqa: E402
    LAW_VOCABULARY, discover_gates, is_test, repo_root, shared_symbols,
)


def strip_docstring(node):
    """Return the body with a leading string-constant expression removed.

    Docstrings are prose ABOUT the law, not the law. Two seats whose bodies agree and whose
    docstrings disagree are one implementation with two explanations -- collapsing them is
    still a move, and the explanation to keep is a review question, not a classification one.
    """
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        return body[1:]
    return body


def normalised_dump(node) -> str:
    """AST dump of the body, one node per line, with positions and docstring dropped.

    One node per line is what makes the unified diff readable AND what makes the similarity
    ratio mean something at statement grain rather than character grain.
    """
    parts = []
    for stmt in strip_docstring(node):
        parts.append(ast.dump(stmt, annotate_fields=True, include_attributes=False))
    # Split on the dump's own nesting punctuation so the diff has lines to align.
    text = ",\n".join(",".join(parts).split(", "))
    return text


def gate_functions(path: Path):
    """Top-level functions only, keyed by name, with source and normalised dump.

    NESTED functions are excluded for the same reason the meter excludes them from shared
    ownership: a closure is not a name another seat could import, so it cannot be the same
    function as anything. Including them made unrelated `post` helpers read as duplicates.
    """
    src = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src, filename=str(path))
    lines = src.splitlines()
    out = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = getattr(node, "end_lineno", node.lineno)
        body_text = "\n".join(lines[node.lineno - 1:end])
        out[node.name] = {
            "sloc": end - node.lineno + 1,
            "line": node.lineno,
            "dump": normalised_dump(node),
            "law_bearing": any(v in body_text.lower() or v in node.name.lower()
                               for v in LAW_VOCABULARY),
        }
    return out


def classify(ratio: float, near: float) -> str:
    if ratio == 1.0:
        return "IDENTICAL"
    return "NEAR" if ratio >= near else "DIVERGENT"


WORST = {"IDENTICAL": 0, "NEAR": 1, "DIVERGENT": 2}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--near", type=float, default=0.90,
                    help="similarity at or above which a differing pair is NEAR (default 0.90)")
    ap.add_argument("--delta-lines", type=int, default=12,
                    help="max diff lines printed per NEAR/DIVERGENT pair (0 = none)")
    ap.add_argument("--law-only", action="store_true",
                    help="report only law-bearing names")
    args = ap.parse_args()

    root = repo_root(Path(__file__).resolve())
    gates, unclassified = discover_gates(root)
    if unclassified:
        print("UNCLASSIFIED hook module(s) -- classify them in gate_collapse_meter.py:")
        for u in unclassified:
            print(f"  {u}")
        return 2
    owned, _ = shared_symbols(root / "plugins" / "_shared")

    per_seat = {seat: gate_functions(path) for seat, path in gates}
    seats = sorted(per_seat)

    # Names duplicated across gates and owned by no shared module. Same population the
    # meter's UNSHARED FORK SURFACE prints, so the two reports are about one thing.
    dup = {}
    for seat in seats:
        for name, fn in per_seat[seat].items():
            if name in owned:
                continue
            dup.setdefault(name, []).append(seat)
    dup = {n: s for n, s in dup.items() if len(s) > 1}

    print(f"gates: {', '.join(f'{s}' for s in seats)}")
    print(f"near threshold: {args.near}   law vocabulary: {', '.join(LAW_VOCABULARY)}")
    print()

    rows = []
    for name, holders in sorted(dup.items()):
        law = any(per_seat[s][name]["law_bearing"] for s in holders)
        if args.law_only and not law:
            continue
        pairs = []
        for i, a in enumerate(holders):
            for b in holders[i + 1:]:
                r = difflib.SequenceMatcher(
                    None, per_seat[a][name]["dump"], per_seat[b][name]["dump"]).ratio()
                pairs.append((a, b, r, classify(r, args.near)))
        verdict = max((p[3] for p in pairs), key=lambda c: WORST[c])
        sloc = sum(per_seat[s][name]["sloc"] for s in holders)
        rows.append({"name": name, "holders": holders, "pairs": pairs,
                     "verdict": verdict, "sloc": sloc, "law": law})

    rows.sort(key=lambda r: (WORST[r["verdict"]], -r["sloc"]))

    print(f"{'name':34} {'verdict':10} {'sloc':>5}  {'law':3}  seats")
    print("-" * 78)
    for r in rows:
        print(f"{r['name']:34} {r['verdict']:10} {r['sloc']:5}  "
              f"{'yes' if r['law'] else '   ':3}  {' '.join(r['holders'])}")

    totals = {}
    for r in rows:
        t = totals.setdefault(r["verdict"], {"n": 0, "sloc": 0, "law_sloc": 0})
        t["n"] += 1
        t["sloc"] += r["sloc"]
        if r["law"]:
            t["law_sloc"] += r["sloc"]
    print()
    total_sloc = sum(t["sloc"] for t in totals.values())
    for v in ("IDENTICAL", "NEAR", "DIVERGENT"):
        t = totals.get(v, {"n": 0, "sloc": 0, "law_sloc": 0})
        pct = (100.0 * t["sloc"] / total_sloc) if total_sloc else 0.0
        print(f"{v:10} {t['n']:3} name(s)  {t['sloc']:5} sloc ({pct:4.1f}%)  "
              f"law-bearing {t['law_sloc']:5}")
    print(f"{'TOTAL':10} {len(rows):3} name(s)  {total_sloc:5} sloc")
    print()
    print("IDENTICAL is a MOVE: one body, no behaviour to argue about.")
    print("NEAR/DIVERGENT is a MERGE: every delta below is a bug or a profile knob.")

    if args.delta_lines:
        for r in rows:
            for a, b, ratio, cls in r["pairs"]:
                if cls == "IDENTICAL":
                    continue
                print()
                print(f"== {r['name']}  {a} vs {b}   similarity {ratio:.3f}  [{cls}]")
                fa = per_seat[a][r["name"]]
                fb = per_seat[b][r["name"]]
                print(f"   {a}:{fa['line']} ({fa['sloc']} sloc)   "
                      f"{b}:{fb['line']} ({fb['sloc']} sloc)")
                diff = list(difflib.unified_diff(
                    fa["dump"].splitlines(), fb["dump"].splitlines(),
                    fromfile=a, tofile=b, lineterm="", n=0))[2:]
                shown = [d for d in diff if not d.startswith("@@")]
                for line in shown[:args.delta_lines]:
                    print(f"   {line[:150]}")
                if len(shown) > args.delta_lines:
                    print(f"   ... {len(shown) - args.delta_lines} more delta line(s) "
                          f"(raise --delta-lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
