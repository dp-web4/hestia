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

  1. NOT the renderer. All 270 ellipsis-space rows sit at `len(tool)+224`, 270/270, on every
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

  4. AND THE DAEMON DOES TRUNCATE — on a DIFFERENT RECORD PATH. This is a SECOND CUT SITE,
     not a correction to 853c5b4 (see WHAT THIS IS NOT, below). `const ATTEMPTED_MAX = 400`
     in `core/src/server/handler.rs` clamps the `attempted` field of `policy_decision` rows
     at BOTH of its sites, to 400 + `"…[truncated]"` = 412 — MEASURED at 1,214 rows, all
     three seats:

         policy_decision `attempted` cut at 412:  claude-code 766/1033 = 74.2%
                                                  kimi-code   280/1022 = 27.4%
                                                  codex       168/750  = 22.4%

     claude-code is the seat with NO 400-limit anywhere in its hook, and it is the seat the
     daemon cuts MOST. Its hook bounds at 220 for `stated_reason` and does not bound
     `attempted` at all, so the daemon's clamp does all of it.

     WHAT THIS IS NOT — codex's dissent on #681, SUSTAINED. An earlier draft of this file
     read 853c5b4's "The daemon does not truncate" as a UNIVERSAL claim and called it
     refuted. It is not universal. That sentence's own paragraph is about `stated_reason`,
     and its evidence is `optional_string` plus a 1340-char `stated_detail` — a DIFFERENT
     FIELD, on a DIFFERENT EVENT TYPE, reached by a DIFFERENT INGEST. `reason`/`detail`
     enter through bare `optional_string` (literally `String::from`: no clamp, no redaction)
     and land in `gate_escalation` UNBOUNDED, while `attempted` enters the `policy_decision`
     path and is redacted AND clamped. On the path 853c5b4 scopes itself to, 853c5b4 is
     CORRECT. Two record paths that share a marker are not interchangeable.

     What DOES survive as a correction to 853c5b4 is its OTHER sentence, "only one seat's
     rows are cut" — refuted on 853c5b4's own field, where every seat is cut:
     claude-code 48.9%, codex 67.1%, kimi-code 24.6%, unattributed 65.5%; all 329/692 = 47.5%.

  5. SO THE MARKER DOES NOT NAME A LAYER. `"…[truncated]"` at exactly 412 is emitted by the
     seat hooks (`_attempted_summary(ev, limit=400)`, codex:418 and kimi:392) into
     `stated_reason`, AND by the daemon into `attempted`. Same marker, same number, three
     sites, no shared constant — raise one and two keep cutting at the old width, silently.
     What DOES name the layer is the pair (FIELD, does-the-length-track-`len(tool_name)`).

     This file's own author then committed exactly that error one finding earlier: saw 412 +
     `"…[truncated]"` on two record paths and merged them into one claim about "the daemon".
     The hazard is not hypothetical, and noticing it in the abstract does not inoculate you
     against it — a reviewer who read the SCOPE of the disputed sentence caught it, and a
     reviewer who re-ran the NUMBERS did not.

CITING LINES vs CITING SYMBOLS. An earlier draft pinned `ATTEMPTED_MAX` to `handler.rs:2580`
and its second clamp site to `:3576`. At main@534c8e8 they are at **2623** and **3618** — and
a second seat re-verified that draft and reported the numbers "present as cited", offering its
own, differently-wrong ranges. Both seats agreed on the CONCLUSION (the constant is there, it
clamps) while the EVIDENCE POINTER was false, which is the failure a concur is least able to
catch: re-deriving a number tests the number, but a line cite is only ever re-read. Cite the
SYMBOL, and a commit when a location is genuinely needed. The load-bearing claims here survive
this precisely because they are chain arithmetic (`len(tool)+224`), not file coordinates.

SINGLE-SEAT EVIDENCE. The hook-file cites — claude-code's producer line, `codex:418`,
`kimi:392`, and "claude-code's hook contains no 400" — are readable only from this seat; peer
review of them was correctly DENIED by scope. They are testimony, not replicated measurement.
Finding 1's discriminator does not depend on them: constant-offset-across-tool-names is a
property of the chain, and it replicated exactly from a second seat.

Read-only: walks the chain, writes nothing.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
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
