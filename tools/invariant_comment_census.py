#!/usr/bin/env python3
"""How many of this repo's emphatic invariant claims can be falsified?

WHY THIS EXISTS. On 2026-09-18 I shipped a governance surface whose comment said a
member/daemon disagreement "is exactly the interesting case" while the code guaranteed no
disagreement could ever be observed, and — in the commit that fixed it — a second comment
claiming a disagreement "becomes durable evidence" that was false on the coalescing path. Both
were caught by a reviewer, neither by a test. GPT's rule from that review:

    a comment that asserts a security/governance property is a claim, not documentation;
    if the property matters, there should be a falsifier that fails when the comment
    becomes false.

A rule is not a mechanism. Before prescribing one, measure the population it would bind: how
many emphatic invariant claims exist, and how many already point at something that could fail.

WHAT IT MEASURES, AND WHAT IT DELIBERATELY DOES NOT.

Scope is the UPPERCASE emphasis form (`MUST`, `NEVER`, `CANNOT`, `ALWAYS`) — this repo's own
idiom for "this sentence is load-bearing". The any-case population is ~1,800 lines in
`core/src` alone, which is prose, not a guardable set. Narrowing to the emphatic form is a
choice about what a rule could realistically bind, and it is stated here rather than buried:
this census under-counts invariant claims on purpose.

A claim counts as ANCHORED when its comment BLOCK cites something that can fail — a test name,
a `pinned by`, an issue number. Per BLOCK, not per line: the first cut of this tool checked the
citation on the same line as the verb and reported 4 of 65, because these comments run for
paragraphs and the citation usually sits several lines from the claim. That is the windowing
error this repo keeps paying for, committed inside the tool written to measure a different
instance of it. The block walk is the repair, and the same-line number is printed beside it so
the difference is visible rather than asserted.

This is a MEASUREMENT, not a verdict. An unanchored claim is not necessarily wrong; it is
un-checkable, which is a different and smaller charge.

Usage:
    python3 tools/invariant_comment_census.py [--root DIR] [--json] [--list-unanchored N]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

VERBS = re.compile(r"\b(MUST|NEVER|CANNOT|ALWAYS)\b")
# What makes a claim checkable: a named test, an explicit pin, or an issue that owns it.
ANCHOR = re.compile(
    r"(pinned by|pins\b|_test\b|_tests\b|#\d{2,5}\b|`[a-z_]+_test(?:s)?\.(?:py|rs)`)"
)
COMMENT = re.compile(r"^\s*(///?!?|//)\s?(.*)$")


# A claim written ON a test is anchored BY that test: it does not cite a falsifier because it
# IS one. The first run of this tool counted five such blocks in `adjudicator.rs` as
# unanchored, which is a false accusation against exactly the discipline it exists to measure.
TEST_ATTR = re.compile(r"^\s*(#\[(tokio::)?test\]|#\[cfg\(test\)\]|(pub )?(async )?fn test_|def test_)")

# THE DETECTOR'S OWN FALSE NEGATIVE, found by using it. This repo names Rust tests
# DESCRIPTIVELY — `a_verdict_refuses_the_four_shapes_that_would_make_it_unreadable` — with no
# `_test` token anywhere in the name. So a comment that cites its falsifier by name, which is
# exactly the behaviour the rule wants, scored as unanchored. Three claims were anchored by
# hand and the count moved by one.
#
# The repair is to stop guessing at what a test name looks like and collect the real ones: a
# block is anchored if it names an identifier that IS a test in this repo. That also makes the
# citation checkable — a comment can no longer anchor itself to a test that does not exist.
TEST_DEF = re.compile(
    r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([a-z0-9_]+)\s*\(|^\s*def\s+(test_[a-z0-9_]+)\s*\("
)


def test_names(root: Path) -> set[str]:
    """Every test function name in the repo, for citation matching."""
    names: set[str] = set()
    for pat in ("*.rs", "*.py"):
        for path in root.rglob(pat):
            s = str(path)
            if "/target/" in s or "/node_modules/" in s or "/.git/" in s:
                continue
            try:
                lines = path.read_text(errors="replace").split("\n")
            except OSError:
                continue
            prev_is_test_attr = False
            for line in lines:
                m = TEST_DEF.match(line)
                if m:
                    name = m.group(1) or m.group(2)
                    # A Rust fn counts only under a test attribute; a Python def counts by
                    # its `test_` prefix, which is pytest's own contract.
                    if name and (prev_is_test_attr or name.startswith("test_")):
                        names.add(name)
                prev_is_test_attr = bool(
                    re.match(r"^\s*#\[(tokio::)?test\]", line)
                ) or (prev_is_test_attr and line.strip().startswith("#["))
    return {n for n in names if len(n) > 12}


def blocks(path: Path):
    """Yield (start_line, [lines], followed_by_test) for each run of contiguous comment lines."""
    try:
        text = path.read_text(errors="replace").split("\n")
    except OSError:
        return
    cur: list[str] = []
    start = 0
    for i, line in enumerate(text, 1):
        m = COMMENT.match(line)
        if m:
            if not cur:
                start = i
            cur.append(m.group(2))
        else:
            if cur:
                yield start, cur, bool(TEST_ATTR.match(line))
            cur = []
    if cur:
        yield start, cur, False


def census(root: Path, include: tuple[str, ...] = ("*.rs", "*.py")):
    known_tests = test_names(root)
    rows = []
    for pat in include:
        for path in root.rglob(pat):
            s = str(path)
            if "/target/" in s or "/node_modules/" in s or "/.git/" in s:
                continue
            for start, lines, on_test in blocks(path):
                body = "\n".join(lines)
                if not VERBS.search(body):
                    continue
                cites_real_test = any(t in body for t in known_tests)
                anchored = bool(ANCHOR.search(body)) or on_test or cites_real_test
                # The naive comparison: is the anchor on the SAME line as the verb? Kept so
                # the block-vs-line difference is a measured number and not a claim.
                same_line = any(VERBS.search(l) and ANCHOR.search(l) for l in lines)
                rows.append({
                    "file": str(path.relative_to(root)),
                    "line": start,
                    "anchored": anchored,
                    "anchor": "is_a_test" if on_test else
                              ("names_a_test" if cites_real_test else
                               ("cites" if ANCHOR.search(body) else None)),
                    "anchored_same_line": same_line,
                    "claim": next((l.strip() for l in lines if VERBS.search(l)), "")[:140],
                })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=".", help="repo root (default: cwd)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list-unanchored", type=int, default=0,
                    help="print this many unanchored claims, worst-first by file")
    a = ap.parse_args()

    root = Path(a.root).resolve()
    rows = census(root)
    total = len(rows)
    anchored = sum(r["anchored"] for r in rows)
    same_line = sum(r["anchored_same_line"] for r in rows)

    if a.json:
        print(json.dumps({
            "total_invariant_blocks": total,
            "anchored_blocks": anchored,
            "anchored_same_line_only": same_line,
            "rows": rows,
        }, indent=1))
        return 0

    if total == 0:
        print("no emphatic invariant claims found — check --root")
        return 0

    print(f"INVARIANT CLAIMS (UPPERCASE MUST/NEVER/CANNOT/ALWAYS), by comment block")
    print(f"  root: {root}")
    print(f"  blocks containing a claim : {total}")
    print(f"  anchored (block cites a falsifier): {anchored}  ({100*anchored/total:.1f}%)")
    print(f"  unanchored                        : {total-anchored}")
    print()
    print("  THE SAME-LINE ILLUSION, measured rather than asserted:")
    print(f"    citation on the SAME LINE as the verb: {same_line}"
          f"  ({100*same_line/total:.1f}%)")
    print(f"    the block walk finds {anchored - same_line} more. A same-line check would have")
    print( "    under-reported this population by that much — the windowing error this repo")
    print( "    keeps paying for, in the tool written to measure it.")

    by_file: dict[str, int] = {}
    for r in rows:
        if not r["anchored"]:
            by_file[r["file"]] = by_file.get(r["file"], 0) + 1
    if by_file:
        print()
        print("  unanchored claims, by file (top 10):")
        for f, n in sorted(by_file.items(), key=lambda kv: (-kv[1], kv[0]))[:10]:
            print(f"    {n:>4}  {f}")

    if a.list_unanchored:
        print()
        print(f"  first {a.list_unanchored} unanchored claims:")
        for r in [r for r in rows if not r["anchored"]][: a.list_unanchored]:
            print(f"    {r['file']}:{r['line']}")
            print(f"      {r['claim']}")

    print()
    print("  An unanchored claim is UN-CHECKABLE, not wrong. This is a measurement; what to")
    print("  require of new ones is a separate decision, and a ratchet on this number is the")
    print("  cheap version of it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
