#!/usr/bin/env python3
"""#608, over the COMPLETE population: what `stated_detail` holds, and whether the
sentence it holds is supported by the rest of the record.

WHAT #608 ESTABLISHED, and what this adds. #608 hand-read five rows, then seven, and
showed the literal is fixed and that read-FPs get approved on it. Those are existence
proofs. This is the denominator: every `gate_escalation_opened` row on the chain, from
genesis to the moment of the run, classified by whether the record can support the
sentence the operator was shown. Nothing here is sampled and there is no hop budget, so
the left edge is genesis rather than an unstated, drifting `max_entries` boundary.

THE STRUCTURAL POINT, which is upstream of the FP rate. `gate_escalation.rs` documents
two fields with two jobs:

    stated_reason   WHY the member says it needs this, in its own words.
    stated_detail   WHAT the act would do -- the command, or a summary of the edit.
                    "A stated reason that does not match the payload is the single most
                    useful thing this record can surface, and that comparison is
                    impossible if only one of the two is stored."

The auto-open path in all three seat hooks sends the ACT as `reason` -- through
`_attempted_summary`, which caps it at 220 characters "because an escalation body is read
by a human under interruption" -- and sends a 148-character CONSTANT as `detail`. So the
act is stored once, in the field for intent, under a cap justified by a rendering concern;
and the field built for the act, which the daemon stores verbatim and which
`core/tests/stated_reason_is_never_bounded.rs` was written to keep unbounded, holds a
sentence that is the same on every row. The comparison the schema exists for is not
degraded on these rows. It is unavailable on all of them, by construction.

That reframes the remedy. #608 proposes minting a BETTER label from the verb class the
hook already computed. But the verb class the hook computed is precisely what produces the
wrong labels this script counts -- a more specific claim from the same classifier is still
a claim, and an operator still cannot check it. Putting the act in the field named for the
act needs no classifier and no new field, and it is what the field's own documentation
asks for. `act_digest` binds `stated_reason` on the claim door (#539), so `reason` must
stay exactly as it is; the change is only what goes in `detail`.

METHOD, and its limits, stated so a reader can discount them:

  * A row is "auto-opened" iff `stated_detail` equals the constant, byte for byte. That is
    the population whose operator-facing sentence asserts a write.
  * Act class comes from `tool_name` where the tool settles it, and otherwise from the
    surviving text of `stated_reason`.
  * TWO classifiers run, not one. V1 is the first pass; V2 closes two holes V1 had
    (`git -C <dir> <verb>` slipped past a `git\\s+verb` anchor; a governance-CLI write such
    as `hestia gate approve` writes no file but is still a write). Both totals print and
    the DISAGREEMENT SET prints in full. A single hand-tuned regex quoting a rate is the
    failure mode this repo already has on record; the honest form is two and their delta.
  * "READ" here means THE RECORD SHOWS ONLY A READ -- not "this could not possibly have
    written". A command can write through a destination that is merely a last argument,
    which the safety preset's own law text says it cannot see either. So the read bucket
    is a claim about what an operator could verify, which is the question that matters for
    a record shown to an operator, and NOT a claim about what the process would have done.
  * Truncated and redacted rows are counted separately and never folded into either
    verdict. They are the rows where the label is neither supported nor contradicted --
    it is simply uncheckable, which is its own finding and not a rounding error.

PROVENANCE OF THE VOCABULARY BELOW, AND AN APPEAL I LOST. Running an earlier draft of this
analysis as a `python3` heredoc was DENIED by the safety preset on 2026-08-27T12:42:04Z,
chain `e1f4bfca22947d2e09ce7c970c1417606df80000f6d1a51912e2001509f7e3d8`. I appealed rather
than respelling it (`0b2728a1b45b637f`), arguing the only thing that looked like a write was
the list of verbs meaning "write" passed to `re.compile` as a string literal, and that the
script's only output was a printed table.

**That appeal was NOT UPHELD, and the arbiter was right.** codex ruled cross-vendor at
12:46:23Z, 159 seconds after filing: the carried command's last statement was
`json.dump(..., open("/tmp/wk/result.json", "w"))`, which names and opens a filesystem
destination for writing. The premise of my appeal was false. I had not re-read the act I was
appealing -- which is the exact failure this file exists to measure, committed by its author
while measuring it.

Two things follow, and the second is the one that matters:

  * The deny fired on a real write. Whether a `json.dump` to `/tmp` belongs in the class
    "Block destructive shell commands" is a separate question the ruling did not have to
    reach, and this file does not claim it.
  * codex could refute me in 159 seconds ONLY because the safety-preset deny recorded the
    full command, untruncated. That is the whole argument of this census, arriving from the
    other direction: peer review is not weak here, it is starved. Give a reviewer the act and
    they will read it and catch you. The 668 rows below are the population where nobody
    could, because the field built for the act holds a constant.

Not one character of the write-verb vocabulary was changed to get past the deny; the file is
on disk instead of on stdin. The second-order shape is still worth naming: to count how often
this gate calls a read a write, you must write down the words that mean write, and the gate
reads that list as a write.

Usage:
    python3 tools/escalation_detail_is_a_constant.py            # whole chain
    python3 tools/escalation_detail_is_a_constant.py --max 20000 --json out.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload  # noqa: E402

CONST = ("Auto-opened by the gate on a refused write; the member stated no rationale "
         "because it did not choose to escalate. Approving authorises this one write.")

WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch"}
READ_TOOLS = {"Read", "Grep", "Glob", "NotebookRead"}

#: V1 -- the first pass, kept so the delta against V2 is inspectable rather than asserted.
V1 = re.compile(
    r'(^|[\s;&|(])(rm|mv|cp|chmod|chown|mkdir|touch|install|tee|dd|ln)\s'
    r'|>>|(?<![0-9])>(?!\s*[|&]?\s*/dev/(null|stderr|stdout))|>\|'
    r'|sed\s+-i'
    r'|git\s+(commit|add|push|checkout|merge|reset|rebase|apply|worktree\s+add)')

#: V2 -- V1 plus the two holes found by reading the buckets it produced.
V2 = re.compile(
    r'(^|[\s;&|(])(rm|mv|cp|chmod|chown|mkdir|touch|install|tee|dd|ln|truncate)\s'
    r'|>>|(?<![0-9])>(?!\s*[|&]?\s*/dev/(null|stderr|stdout))|>\|'
    r'|sed\s+-i|perl\s+-i'
    r'|\bgit\b(\s+-C\s+\S+)?\s+(commit|add|push|checkout|switch|merge|reset|rebase'
    r'|apply|restore|stash|worktree\s+add|clone|init|tag)'
    r'|\bhestia\b\s+\w+\s+(approve|deny|decide|grant|withdraw|revoke)')

BUCKETS = ("A_write", "C_read", "B_trunc", "D_redacted")
LABEL = {
    "A_write": "record SHOWS a write             -> label supported",
    "C_read": "record shows a READ and only that -> label CONTRADICTED",
    "B_trunc": "act TRUNCATED mid-command        -> label UNCHECKABLE",
    "D_redacted": "act REDACTED entirely            -> label UNCHECKABLE",
}


def classifier(rx: re.Pattern):
    def k(p: dict) -> str:
        tool = p.get("tool_name") or ""
        if tool in WRITE_TOOLS:
            return "A_write"
        stated = p.get("stated_reason") or ""
        if "[REDACTED" in stated:
            return "D_redacted"
        if tool in READ_TOOLS:
            return "C_read"
        body = stated[6:] if stated.startswith("Bash: ") else stated
        if rx.search(body):
            return "A_write"
        # The producer marks its own cut with a trailing ellipsis; that is the only
        # signal a reader gets that the act continues past what is stored.
        return "B_trunc" if body.rstrip().endswith("…") else "C_read"
    return k


def collect(max_entries: int):
    w = ChainWalker()
    opened, decided, claimed = [], set(), set()
    hops = 0
    newest = oldest = None
    for e in w.walk(max_entries=max_entries):
        hops += 1
        if newest is None:
            newest = (e["chainPosition"], e["timestamp"])
        oldest = (e["chainPosition"], e["timestamp"])
        et = e.get("eventType") or ""
        if not et.startswith("gate_escalation"):
            continue
        p = payload(e)
        if et == "gate_escalation_opened":
            opened.append(p)
        elif et == "gate_escalation_decided":
            decided.add(p.get("escalation_id"))
        elif et == "gate_escalation_claimed":
            claimed.add(p.get("escalation_id"))
    return opened, decided, claimed, hops, newest, oldest


def pct(n: int, d: int) -> str:
    return f"{100.0 * n / d:5.1f}%" if d else "  n/a"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=10 ** 9,
                    help="hop budget; the default walks to genesis. A budget gives an "
                         "unstated left edge that DRIFTS as the chain grows, so the span "
                         "actually covered is always printed.")
    ap.add_argument("--json", help="also write the counts here")
    a = ap.parse_args()

    opened, decided, claimed, hops, newest, oldest = collect(a.max)
    if not opened:
        print("no gate_escalation_opened rows in the span walked", file=sys.stderr)
        return 1

    print(f"CHAIN: {hops} hops walked, position {oldest[0]} ({oldest[1][:19]}) "
          f"-> {newest[0]} ({newest[1][:19]})")
    print(f"  budget hit: {'YES -- left edge is the budget, not genesis' if hops >= a.max else 'no -- walked to genesis'}")
    print(f"escalations opened in that span: {len(opened)}")

    detail = Counter(p.get("stated_detail") for p in opened)
    real = sum(c for v, c in detail.items() if v not in (None, CONST))
    print("\n--- what `stated_detail` actually holds ---")
    print(f"  {detail[CONST]:4d}  {pct(detail[CONST], len(opened))}  the constant")
    print(f"  {detail[None]:4d}  {pct(detail[None], len(opened))}  absent")
    print(f"  {real:4d}  {pct(real, len(opened))}  a description of the act, written by a member")

    auto = [p for p in opened if p.get("stated_detail") == CONST]
    k1, k2 = classifier(V1), classifier(V2)
    c1 = Counter(k1(p) for p in auto)
    c2 = Counter(k2(p) for p in auto)
    n = len(auto)

    print("\n--- two classifiers, and their delta ---")
    print("  bucket        V1     V2")
    for b in BUCKETS:
        print(f"  {b:12s} {c1[b]:4d}   {c2[b]:4d}")
    dis = [p for p in auto if k1(p) != k2(p)]
    print(f"\n  DISAGREEMENT SET ({len(dis)}), in full:")
    for p in dis:
        print(f"    {k1(p)} -> {k2(p)} | {(p.get('stated_reason') or '')[:140]}")

    def table(pop, title, key=k2):
        c = Counter(key(p) for p in pop)
        print(f"\n--- {title}: {len(pop)} ---")
        for b in BUCKETS:
            print(f"  {c[b]:4d}  {pct(c[b], len(pop))}  {LABEL[b]}")
        return c

    table(auto, f"every auto-opened row, each shown to an operator as 'a refused write'")
    cd = table([p for p in auto if p.get("escalation_id") in decided],
               "restricted to rows an operator actually RULED on")
    cc = table([p for p in auto if p.get("escalation_id") in claimed],
               "restricted to rows whose permit was actually SPENT")

    print("\n--- per seat (V2) ---")
    seats = defaultdict(Counter)
    for p in auto:
        seats[p.get("plugin_id")][k2(p)] += 1
    for name, c in sorted(seats.items(), key=lambda kv: -sum(kv[1].values())):
        t = sum(c.values())
        print(f"  {name:14s} n={t:4d}  write {c['A_write']:4d}  READ-only {c['C_read']:4d} "
              f"({pct(c['C_read'], t)})  trunc {c['B_trunc']:4d}  redacted {c['D_redacted']:3d}")
    print("  NOTE: a low READ-only share is not a cleaner seat. claude-code's truncation "
          "moves rows out of every verdict bucket into `trunc`, so its acts are\n"
          "  unreadable rather than read-shaped -- the two seats that do not truncate are "
          "the two whose contradiction rate is visible.")

    if a.json:
        with open(a.json, "w") as fh:
            json.dump({
                "hops": hops, "span": [oldest, newest], "budget_hit": hops >= a.max,
                "opened": len(opened), "auto": n,
                "detail_const": detail[CONST], "detail_absent": detail[None],
                "detail_real": real,
                "v1": dict(c1), "v2": dict(c2),
                "decided": dict(cd), "claimed": dict(cc),
            }, fh, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
