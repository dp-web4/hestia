"""Aggregate replay3's results.jsonl into the cost table for #1232's narrowing."""
import collections
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OLD_END = datetime.datetime(2026, 10, 5, 20, 5, tzinfo=datetime.timezone.utc).timestamp()
rows = [json.loads(ln) for ln in open(os.path.join(HERE, "results.jsonl"))]
SEATS = ("claude-code", "codex", "kimi-code")
CORES = ("orig", "before", "after")


def table(rs, title):
    n = collections.Counter(r["seat"] for r in rs)
    tot = len(rs)
    print(f"\n### {title}: {tot} commands ({', '.join(f'{s} {n[s]}' for s in SEATS)})")
    print("| core | grants | refused (delta over main) | of which: path | once-only request | "
          "plain incomplete | claude-code | codex | kimi-code |")
    print("|---|---|---|---|---|---|---|---|---|")
    out = {}
    for core in CORES:
        for tag in ("", "+g"):
            base = "main" + tag
            c = collections.Counter()
            per = collections.Counter()
            for r in rs:
                if r.get(base) != "allow":
                    continue                      # main refuses it too: not this change's effect
                k = r.get(core + tag, "error")
                if k == "allow":
                    continue
                c[k.split(":")[0]] += 1
                per[r["seat"]] += 1
            ref = sum(c.values())
            out[(core, tag)] = (ref, c)
            pct = lambda x, d: f"{x} ({100.0 * x / max(1, d):.1f}%)"
            print(f"| {core} | {'proposed' if tag else 'none'} | {pct(ref, tot)} | {c['path']} | "
                  f"{c['request']} | {c['incomplete']} | "
                  + " | ".join(pct(per[s], n[s]) for s in SEATS) + " |"
                  + (f" errors={c['error']}" if c['error'] else ""))
    return out


def shapes(rs, core="after", top=12):
    """What the unenumerated requests are made of (first reason is not stored; class by text)."""
    return None


old = [r for r in rs] if False else [r for r in rows if r["ts"] <= OLD_END]
table(old, "Window of the 2026-10-05 run (2026-09-20 .. 2026-10-05T20:05Z)")
table(rows, "Full window (2026-09-20 .. now)")
main_ref = sum(1 for r in rows if r.get("main") != "allow")
print(f"\nmain itself refuses {main_ref} of {len(rows)} (pass 1/2, unchanged by this PR)")
