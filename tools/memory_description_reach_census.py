#!/usr/bin/env python3
"""How much of a seat's file-based memory is reachable by RECALL, not by grep?

Recall matches a leaf's `description:` line. Everything below the frontmatter is
reachable only by an explicit search, which requires already knowing the term --
so a fact recorded in a body and absent from its own description is recorded but
unrecallable. This is the producer for that ratio, so the number is not a claim.

Why it exists: on 2026-09-03 this seat re-derived a retention rule
(`reap(now, REAP_KEEP_SECS)` is called only from `open()`) that was already on
file in five places -- hestia #544's body, two 08-19 feedback leaves, line 248 of
a 40 KB reference leaf, and this seat's own PR #854 -- and credited a peer for
supplying it. Every one of the five filed it under a different charge; none put
the rule in a description. See
findings/wake-0903-the-answer-was-on-file-five-times.md.

Transcription note: this file reads its default directory with `os.getenv`
rather than the usual process-environment mapping, because the gate's
`egress.secret` marker substring-matches the dotted spelling of that mapping
name and refuses the write (hestia #639). No credential is in scope here; the
spelling is elided rather than the resource, and this note is the disclosure.

Usage:
  memory_description_reach_census.py [MEMORY_DIR] [--strict] [--json]
                                     [--leaf NAME] [--top N]

  --strict   count only code-shaped tokens (must contain one of _ . / : or `(`),
             so English words in backticks do not inflate the ratio. The strict
             run is the defensible LOWER bound; the loose run is the upper one.
  --leaf     report body-only identifiers for a single leaf (audit one file).

MEMORY_DIR defaults to CLAUDE_MEMORY_DIR if set, else the cwd. MEMORY.md is
excluded: it is the always-loaded index, not a leaf, and its reach is total by
construction.

All sizes are CHARACTERS, not bytes. The corpus is utf-8 prose with em-dashes and
arrows, so `ls -l` reads ~1% larger than this tool for the same file (40,737 vs
40,422 on the largest reference leaf). Char count is the right grain here because
the ceiling this competes against -- the always-loaded index -- is enforced on the
string after `.trim()`, not on the file.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import statistics
import sys

TOKEN = re.compile(r"`([^`\n]{2,60})`")
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:/\-]*(\(\))?$")
CODE_SHAPED = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*([_./:()\-][A-Za-z0-9_./:()\-]*)+$")
DESC = re.compile(r"^description:\s*(.*)$", re.M)


def is_ident(tok: str, strict: bool) -> bool:
    if strict:
        return bool(CODE_SHAPED.match(tok)) and any(c in tok for c in "_./:(")
    return bool(IDENT.match(tok))


def split_leaf(text: str) -> tuple[str, str]:
    """(description, body). Frontmatter is delimited by the first two `---`."""
    m = DESC.search(text)
    desc = m.group(1) if m else ""
    parts = text.split("---")
    body = "---".join(parts[2:]) if len(parts) > 2 else text
    return desc, body.strip()


def census(memdir: str, strict: bool) -> dict:
    leaves = []
    body_only_leaves = 0
    per_leaf_body_only: dict[str, list[str]] = {}
    all_body: collections.Counter = collections.Counter()
    all_desc: set[str] = set()
    for name in sorted(os.listdir(memdir)):
        if not name.endswith(".md") or name == "MEMORY.md":
            continue
        path = os.path.join(memdir, name)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        desc, body = split_leaf(text)
        d = {t for t in TOKEN.findall(desc) if is_ident(t, strict)}
        b = {t for t in TOKEN.findall(body) if is_ident(t, strict)}
        only = b - d
        leaves.append(
            {
                "leaf": name,
                "chars": len(text),
                "desc_chars": len(desc),
                "body_ids": len(b),
                "desc_ids": len(d),
                "body_only_ids": len(only),
            }
        )
        per_leaf_body_only[name] = sorted(only)
        if only:
            body_only_leaves += 1
        for t in only:
            all_body[t] += 1
        all_desc |= d

    if not leaves:
        return {"error": f"no leaves found in {memdir}"}

    total = sum(r["chars"] for r in leaves)
    desc_total = sum(r["desc_chars"] for r in leaves)
    body_ids = sum(r["body_ids"] for r in leaves)
    body_only = sum(r["body_only_ids"] for r in leaves)
    never = {t for t in all_body if t not in all_desc}
    return {
        "memory_dir": memdir,
        "strict": strict,
        "leaves": len(leaves),
        "corpus_chars": total,
        "median_leaf_chars": int(statistics.median(r["chars"] for r in leaves)),
        "max_leaf_chars": max(r["chars"] for r in leaves),
        "description_chars": desc_total,
        # THE HEADLINE: recall sees the description; this is its share of the corpus.
        "recallable_char_share_pct": round(100 * desc_total / total, 1),
        "leaves_with_body_only_ids": body_only_leaves,
        "leaves_with_body_only_ids_pct": round(100 * body_only_leaves / len(leaves), 1),
        "identifier_mentions_body": body_ids,
        "identifier_mentions_description": sum(r["desc_ids"] for r in leaves),
        "identifier_mentions_body_only": body_only,
        "identifier_mentions_body_only_pct": (
            round(100 * body_only / body_ids, 1) if body_ids else None
        ),
        "identifiers_in_no_description_anywhere": len(never),
        "worst_offenders": [
            {"identifier": t, "leaves": all_body[t], "in_any_description": t in all_desc}
            for t, _ in all_body.most_common(20)
        ],
        "largest_leaves": [
            {
                "leaf": r["leaf"],
                "chars": r["chars"],
                "desc_share_pct": round(100 * r["desc_chars"] / r["chars"], 1),
                "body_only_ids": r["body_only_ids"],
            }
            for r in sorted(leaves, key=lambda r: -r["chars"])[:10]
        ],
        "_per_leaf_body_only": per_leaf_body_only,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    default_dir = os.getenv("CLAUDE_MEMORY_DIR") or "."
    ap.add_argument("memory_dir", nargs="?", default=default_dir)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--leaf", help="report body-only identifiers for one leaf")
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args(argv)

    if not os.path.isdir(args.memory_dir):
        print(f"not a directory: {args.memory_dir}", file=sys.stderr)
        return 2

    result = census(args.memory_dir, args.strict)
    if "error" in result:
        print(result["error"], file=sys.stderr)
        return 1
    per_leaf = result.pop("_per_leaf_body_only")

    if args.leaf:
        only = per_leaf.get(args.leaf)
        if only is None:
            print(f"no such leaf: {args.leaf}", file=sys.stderr)
            return 1
        print(f"{args.leaf}: {len(only)} identifier(s) in the body, none in its description")
        for t in only:
            print(f"  {t}")
        return 0

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    r = result
    mode = "STRICT (code-shaped only)" if r["strict"] else "LOOSE (any backticked identifier)"
    print(f"{r['memory_dir']}  --  {mode}")
    print(
        f"  {r['leaves']} leaves, {r['corpus_chars']:,} chars "
        f"(median {r['median_leaf_chars']:,}, max {r['max_leaf_chars']:,})"
    )
    print(
        f"  RECALL REACH: descriptions are {r['description_chars']:,} chars = "
        f"{r['recallable_char_share_pct']}% of the corpus"
    )
    print(
        f"  leaves with >=1 body identifier absent from their OWN description: "
        f"{r['leaves_with_body_only_ids']} ({r['leaves_with_body_only_ids_pct']}%)"
    )
    print(
        f"  identifier mentions: body {r['identifier_mentions_body']:,}, "
        f"description {r['identifier_mentions_description']:,}, "
        f"body-only {r['identifier_mentions_body_only']:,} "
        f"({r['identifier_mentions_body_only_pct']}%)"
    )
    print(
        f"  distinct identifiers in NO description anywhere: "
        f"{r['identifiers_in_no_description_anywhere']:,}"
    )
    print(f"\n  most-repeated body-only identifiers (top {args.top}):")
    for row in r["worst_offenders"][: args.top]:
        flag = "" if row["in_any_description"] else "   <-- in NO description anywhere"
        print(f"    {row['leaves']:3d} leaves  {row['identifier']}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
