#!/usr/bin/env python3
"""WHICH LAYER CUT THIS STRING — the seat's hook, or the daemon? (#627)

THE LEAD, filed 2026-08-27 and not chased at the time. A truncation census of the
escalation population showed codex's cell carrying `stated_reason` lengths 228 (15/79) and
235 (8/79) flagged by the `" …"` ellipsis-space marker — a 220-family marker on a seat whose
own idiom is `"…[truncated]"` at 412. Two readings, far apart in consequence: either the
escalation RENDERER owns that cap, in which case "which seat truncates" is the wrong question
and every per-seat truncation rate is one shared component wearing three seat labels; or `" …"`
arrives at those lengths some other way.

THE DISCRIMINATOR IS ARITHMETIC, NOT PROSE, and it generalises past this question:

    A cut whose LENGTH TRACKS `len(tool_name)` was made by a TEMPLATE producer.
    A cut whose LENGTH IS CONSTANT across tool names was made by a `s[:limit]` clamp.

claude-code's producer is one line (`~/.claude/hooks/hestia/pre_tool_use.py:2057`):

    return f"{tool_name}: {s[:220]}" + (" …" if len(s) > 220 else "")

so anything it cut is EXACTLY `len(tool_name) + 2 + 220 + 2` = `len(tool)+224`, with no freedom
left: 228 for a 4-char tool, 235 for an 11-char one. A renderer clamps the FINISHED string, so
its lengths would pile on ONE number regardless of the tool. The record answers which happened.

WHAT IT FINDS (CBP, 194,598-entry chain, 2026-05-16 -> 2026-08-27):

  1. NOT the renderer. All 269 ellipsis-space rows sit at `len(tool)+224`, 269/269, on every
     seat that has them. The offset is constant across `Bash` (4) and `apply_patch` (11), so
     the length moves 7 chars with the tool name. That is the producer's template, not a clamp.

  2. `apply_patch` at 235 is the proof, and it is stronger than "similar". `apply_patch` is a
     CODEX-ONLY tool name, and it comes through claude-code's template byte-for-byte —
     `"{tool}: "` prefix, 220 chars, `" …"` suffix. Codex's gate once ran claude-code's exact
     producer.

  3. It stopped running it on 2026-08-14. Sorting codex's cut rows oldest->newest gives
     `A×23 B×30` — ONE transition, interleave 0, so this is a cutover and not a mixture. Last
     220-family row 2026-08-14T02:50:02Z, first 412-family row 2026-08-15T15:09:05Z. Reading
     today's hooks tells you "codex caps at 400" and cannot tell you that; only the wire dates
     the swap.

  4. AND THE DAEMON DOES TRUNCATE — on a different field, and 853c5b4's correction overshoots
     into the converse error. That commit ("open-petitions attributes the reason cap to the
     wrong layer", 2026-08-27, in force via the dev tree, not on main) is RIGHT that
     `stated_reason` is uncapped daemon-side and seat-capped. But it says flatly "The daemon
     does not truncate", and `handler.rs:2580 const ATTEMPTED_MAX: usize = 400` plus
     `handler.rs:1429/3576` cut the `attempted` field of every `policy_decision` row at
     400 + `"…[truncated]"` = 412 — MEASURED at 1,214 rows, all three seats:

         policy_decision `attempted` cut at 412:  claude-code 766/1033 = 74.2%
                                                  kimi-code   280/1022 = 27.4%
                                                  codex       168/750  = 22.4%

     claude-code is the seat with NO 400-limit anywhere in its hook, and it is the seat the
     daemon cuts MOST. Its hook bounds at 220 for `stated_reason` and does not bound
     `attempted` at all, so the daemon's clamp does all of it. The commit's other sentence,
     "only one seat's rows are cut", is refuted on both fields: on `stated_reason` every seat
     is cut (claude-code 48.8%, codex 67.1%, kimi 24.8%, unattributed 65.5%).

  5. SO THE MARKER DOES NOT NAME A LAYER. `"…[truncated]"` at exactly 412 is emitted by the
     seat hooks (`_attempted_summary(ev, limit=400)`, codex:418 and kimi:392) into
     `stated_reason`, AND by the daemon into `attempted`. Same marker, same number, three
     sites, no shared constant — raise one and two keep cutting at the old width, silently.
     What DOES name the layer is the pair (FIELD, does-the-length-track-`len(tool_name)`).

Read-only: walks the chain, writes nothing.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict

sys.path.insert(0, "/mnt/c/exe/projects/ai-agents/hestia/tools")
from chain_walk import ChainWalker, payload  # noqa: E402

ELL_SP = " …"              # claude-code's template marker
TRUNC = "…[truncated]"     # the 400-limit marker — seat hooks AND the daemon
TEMPLATE_OFFSET = 224      # len(": ") + 220 + len(" …")


def family(s):
    if not isinstance(s, str):
        return None
    if s.endswith(ELL_SP):
        return "A_220_ellipsis_sp"
    if s.endswith(TRUNC):
        return "B_412_trunc_bracket"
    return "uncut"


def main(max_entries: int = 250000) -> int:
    w = ChainWalker()
    esc, att = [], []
    scanned = 0
    for e in w.walk(max_entries=max_entries):
        scanned += 1
        p = payload(e)
        if not isinstance(p, dict):
            continue
        if e.get("eventType") == "gate_escalation_opened":
            sr, tn = p.get("stated_reason"), p.get("tool_name")
            if isinstance(sr, str) and isinstance(tn, str):
                esc.append((e.get("timestamp"), p.get("plugin_id"), tn, sr))
        a = p.get("attempted")
        if isinstance(a, str):
            att.append((e.get("eventType"), p.get("plugin_id"), a))
    print(f"scanned {scanned} chain entries\n")

    # --- 1. THE DISCRIMINATOR: does the cut length track len(tool_name)? -----------------
    print("=== stated_reason, 220-family: does the length TRACK len(tool_name)? ===")
    print("    constant offset => a TEMPLATE producer.  constant LENGTH => a clamp/renderer.")
    for pid in sorted({r[1] for r in esc}):
        items = [(tn, sr) for _, p2, tn, sr in esc
                 if p2 == pid and family(sr) == "A_220_ellipsis_sp"]
        if not items:
            continue
        offs = Counter(len(sr) - len(tn) for tn, sr in items)
        fits = sum(1 for tn, sr in items if len(sr) == len(tn) + TEMPLATE_OFFSET)
        print(f"  {pid:14s} n={len(items):4d}  tools={sorted({tn for tn, _ in items})}")
        print(f"                 lengths={dict(Counter(len(sr) for _, sr in items).most_common(4))}")
        print(f"                 len-len(tool)={dict(offs)}   == len(tool)+224: {fits}/{len(items)}")

    # --- 2. The cutover: is codex a mixture, or one swap? --------------------------------
    print("\n=== codex: mixture or cutover? (oldest -> newest, A=220-family B=412-family) ===")
    cx = sorted((ts, family(sr)) for ts, pid, _, sr in esc
                if pid == "codex" and family(sr) in ("A_220_ellipsis_sp", "B_412_trunc_bracket"))
    seq = "".join("A" if f.startswith("A") else "B" for _, f in cx)
    trans = sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1])
    print(f"  {seq}")
    print(f"  transitions={trans}  (1 => ONE cutover, not a mixture)")
    if any(f.startswith("A") for _, f in cx) and any(f.startswith("B") for _, f in cx):
        print(f"  last  220-family: {max(t for t, f in cx if f.startswith('A'))}")
        print(f"  first 412-family: {min(t for t, f in cx if f.startswith('B'))}")

    # --- 3. Per-seat cut rate on stated_reason ------------------------------------------
    print("\n=== stated_reason: cut RATE per seat (\"only one seat's rows are cut\"?) ===")
    tot = cut = 0
    for pid in sorted({r[1] for r in esc}):
        rows = [sr for _, p2, _, sr in esc if p2 == pid]
        c = sum(1 for sr in rows if family(sr) != "uncut")
        tot += len(rows)
        cut += c
        print(f"  {pid:14s} {c:4d}/{len(rows):4d} = {100*c/len(rows):5.1f}%")
    print(f"  {'ALL':14s} {cut:4d}/{tot:4d} = {100*cut/tot:5.1f}%")

    # --- 4. The daemon's OWN cap, on a different field -----------------------------------
    print("\n=== `attempted` (policy_decision): the DAEMON's ATTEMPTED_MAX=400, all seats ===")
    by = defaultdict(Counter)
    lens = defaultdict(Counter)
    for et, pid, a in att:
        f = family(a)
        by[(et, pid)][f] += 1
        if f != "uncut":
            lens[(et, pid)][len(a)] += 1
    for k in sorted(by, key=lambda k: -sum(by[k].values())):
        d = by[k]
        n = sum(d.values())
        c = n - d.get("uncut", 0)
        print(f"  {k[0]}/{k[1]:14s} cut {c:4d}/{n:4d} = {100*c/n:5.1f}%  lengths={dict(lens[k])}")
    print("\n  claude-code's hook has NO 400-limit — every one of its cuts here is the daemon's.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
