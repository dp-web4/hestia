#!/usr/bin/env python3
"""Census driver for the marker-FP refutation on issue #668.

WHY THIS EXISTS. The classifier (`marker_fp_classify.py`) was published; the driver that
turned it into the numbers in `findings/668-marker-fp-refutation.md` was NOT. A second
seat reproduced the classifier-dependent cells by reimplementing them against the
published table, and could not reproduce the two cells that depended on definitions
living only in the driver (the /tmp-scratch class and the re-escalation proxy). Those
two disagreed by 30-40% while the direction held. This file closes that gap.

THE WINDOW BUG THIS FILE ALSO FIXES. The original census bounded the corpus with a HOP
BUDGET (`walk(max_entries=N)`), not a date. That has three consequences, and only the
first is obvious:
  1. The boundary is unstated in the output, so a reader cannot re-run it.
  2. The boundary is not a round time. ~60k hops resolved to an instant between
     18:20 and 17:20 on 2026-08-12 -- a second seat recovered it empirically as
     "approximately 12:00Z" and landed one row off, which is the best anyone could do.
  3. THE BOUNDARY MOVES. The chain grows, so the same `max_entries=N` re-run a day later
     starts a day later. A hop-budgeted census is not re-runnable even by its own author,
     and two seats running the identical script on the same day get different windows
     because their walks start from different chain tips.
So this driver REFUSES to run without an explicit `--since`, walks until it passes that
timestamp rather than to a hop count, and prints the window and the hop cost it took.

Reproduce the published table:
    python3 marker_fp_census.py --since 2026-08-12T12:00:00Z
"""
import argparse, collections, json, sys, os, re, math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload
from marker_fp_classify import classify, CENSOR, _under_tmp, _matches, _segments

ESC_TYPES = ("gate_escalation_opened", "gate_escalation_decided", "gate_escalation_claimed")
WRITE_TOOLS = ("Edit", "Write", "apply_patch")


def collect(since, until, max_hops, cache=None):
    """Walk newest->oldest until the first row older than `since`. Returns joined records."""
    if cache and os.path.exists(cache):
        rows = json.load(open(cache))
        hops = None
    else:
        w = ChainWalker()
        rows, hops = [], 0
        for e in w.walk(max_entries=max_hops):
            hops += 1
            at = e.get("timestamp") or e.get("at") or ""
            et = e.get("eventType")
            if et in ESC_TYPES:
                rows.append({"eventType": et, "at": at, "payload": payload(e)})
            # terminate on TIME, not on a hop count -- see module docstring
            if at and at < since:
                break
        if cache:
            json.dump(rows, open(cache, "w"))
    return rows, hops


def join(rows, since, until):
    opened, decided, claimed = {}, {}, {}
    for r in rows:
        p = r["payload"]; eid = p.get("escalation_id")
        if not eid:
            continue
        if r["eventType"] == "gate_escalation_opened":
            opened.setdefault(eid, dict(p, at=r["at"]))
        elif r["eventType"] == "gate_escalation_decided":
            decided.setdefault(eid, dict(p, at=r["at"]))
        elif r["eventType"] == "gate_escalation_claimed":
            claimed.setdefault(eid, dict(p, at=r["at"]))
    recs = []
    for eid, o in opened.items():
        if not (since <= o["at"] <= until):
            continue
        d = decided.get(eid)
        recs.append({
            "id": eid, "at": o["at"], "tool": o.get("tool_name"),
            "seat": o.get("plugin_id"), "marker": o.get("marker"),
            "reason": o.get("stated_reason") or "", "digest": o.get("act_digest"),
            "status": (d or {}).get("status"), "decided": d is not None,
            "claimed": eid in claimed,
        })
    return recs


def censored(reason):
    """Which censor, if any, hid the act text. The two are SEAT-DISJOINT in this corpus."""
    if "[REDACTED" in reason:
        return "redacted"
    if any(c in reason for c in CENSOR):
        return "truncated"
    return None


def disposition(rec):
    """WRITE / READ_ONLY / READ_ONLY_PREFIX / AMBIGUOUS for the marker-matched token."""
    body = rec["reason"]
    # stated_reason is prefixed with the tool name: "Bash <command>" / "Edit <path>"
    m = re.match(r"^(\w+):?\s+(.*)$", body, re.S)
    body = m.group(2) if m else body
    return classify(body, rec["marker"] or "", rec["tool"] or "Bash")[0]


# --- the /tmp-scratch class -------------------------------------------------------
# DEFINITION (this is the cell a second seat could not reproduce; publish it, don't
# describe it). An escalation is in the class iff EVERY token in the act text that the
# marker matches resolves under /tmp. Tokens come from the same segmenter the classifier
# uses, so the class is defined against the same tokenisation as the verdicts. A record
# whose act text is censored is NOT decidable and is excluded from the denominator --
# that exclusion is what makes this "one clean number that needs no grammar", and it is
# also the largest single source of divergence from a looser construction.
def tmp_only(rec):
    if censored(rec["reason"]):
        return None                      # not decidable
    marker = rec["marker"] or ""
    body = rec["reason"]
    m = re.match(r"^(\w+):?\s+(.*)$", body, re.S)
    body = m.group(2) if m else body
    hits = [t for seg in _segments(body) for t in seg.split() if _matches(t, marker)]
    if not hits:
        return None                      # marker matched nothing tokenisable
    return all(_under_tmp(t) for t in hits)


def fisher_2x2(a, b, c, d):
    """Two-sided Fisher exact. (a of a+b) vs (c of c+d)."""
    def logC(n, k):
        return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
    n = a + b + c + d
    r1, r2, c1 = a + b, c + d, a + c
    def p(x):
        return math.exp(logC(r1, x) + logC(r2, c1 - x) - logC(n, c1))
    p0 = p(a)
    lo, hi = max(0, c1 - r2), min(r1, c1)
    return sum(p(x) for x in range(lo, hi + 1) if p(x) <= p0 * (1 + 1e-9))


def rate(num, den):
    return f"{num}/{den} = {100.0*num/den:.0f}%" if den else f"{num}/0 = n/a"


# --- the re-escalation proxy ------------------------------------------------------
# DEFINITION (the second unreproducible cell). A record is a RE-ESCALATION if, within
# `gap` seconds AFTER it opened, the SAME seat opened another escalation on the SAME tool
# whose act text is a near-duplicate (SequenceMatcher ratio >= `sim`) but whose
# `act_digest` DIFFERS. Different digest is what makes it a respelling rather than a
# retry of the identical act; the similarity floor is what makes it a respelling rather
# than unrelated later work.
# BOTH act texts must be uncensored -- a censored pair cannot be scored for similarity,
# and counting it either way is a guess. Records without a digest are excluded from the
# DENOMINATOR, not scored as negative: the digest field is a vintage cutover (it is
# absent before 2026-08-25), so scoring its absence as "did not re-escalate" would mix a
# recording change into a behaviour rate.
# A looser proxy -- no similarity floor, or scoring censored/digestless rows as negative
# -- roughly triples the rate. State which one you ran.
import difflib
from datetime import datetime


def _ts(at):
    try:
        return datetime.fromisoformat(at.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _acttext(rec):
    m = re.match(r"^(\w+):?\s+(.*)$", rec["reason"], re.S)
    return m.group(2) if m else rec["reason"]


def reescalations(recs, gap=1800, sim=0.90):
    scored, hits = [], []
    by_seat = collections.defaultdict(list)
    for r in recs:
        by_seat[r["seat"]].append(r)
    for lst in by_seat.values():
        lst.sort(key=lambda r: r["at"])
    for r in recs:
        if r["tool"] != "Bash" or r["claimed"] or not r["digest"] or censored(r["reason"]):
            continue
        scored.append(r)
        t0 = _ts(r["at"]); a = _acttext(r)
        for s in by_seat[r["seat"]]:
            if s["id"] == r["id"] or s["tool"] != "Bash" or censored(s["reason"]):
                continue
            t1 = _ts(s["at"])
            if t0 is None or t1 is None or not (0 < t1 - t0 <= gap):
                continue
            if s["digest"] and s["digest"] == r["digest"]:
                continue          # identical act, not a respelling
            if difflib.SequenceMatcher(None, a, _acttext(s)).ratio() >= sim:
                hits.append((r, s))
                break
    return scored, hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True,
                    help="ISO8601 window start. REQUIRED -- a hop budget is not a window.")
    ap.add_argument("--until", default="9999")
    ap.add_argument("--max-hops", type=int, default=200000,
                    help="safety stop only; the walk terminates on --since, not on this")
    ap.add_argument("--cache", default=None)
    ap.add_argument("--gap", type=int, default=1800)
    ap.add_argument("--sim", type=float, default=0.90)
    a = ap.parse_args()

    rows, hops = collect(a.since, a.until, a.max_hops, a.cache)
    recs = join(rows, a.since, a.until)
    ats = [r["at"] for r in recs]
    print(f"WINDOW  --since {a.since}  --until {a.until}")
    print(f"        observed {min(ats)} -> {max(ats)}   ({len(recs)} escalations"
          + (f", {hops} hops)" if hops else ", cached)"))
    print(f"        re-escalation proxy: gap<={a.gap}s  similarity>={a.sim}")
    print()

    # --- censorship, Bash only (the two mechanisms are seat-disjoint) ---
    print("CENSORSHIP of the act text (Bash escalations)")
    print(f"  {'seat':<14}{'n':>5}{'truncated':>12}{'redacted':>11}{'intact':>9}")
    for seat in ("claude-code", "kimi-code", "codex"):
        b = [r for r in recs if r["tool"] == "Bash" and r["seat"] == seat]
        t = sum(1 for r in b if censored(r["reason"]) == "truncated")
        d = sum(1 for r in b if censored(r["reason"]) == "redacted")
        print(f"  {seat:<14}{len(b):>5}{t:>12}{d:>11}{len(b)-t-d:>9}")
    print()

    # --- the refutation table ---
    print("CLAIM RATE by act disposition (approved escalations only)")
    print(f"  {'disposition':<26}{'tool':<14}{'approved':>9}{'claimed':>9}{'rate':>7}")
    appr = [r for r in recs if r["status"] == "approved"]
    for r in appr:
        r["disp"] = disposition(r)
    cells = {}
    for label, pred in (("genuinely writes gated path", lambda d: d == "WRITE"),
                        ("marker FP (read/named only)", lambda d: d == "READ_ONLY")):
        for tlabel, tpred in (("Bash", lambda t: t == "Bash"),
                              ("Edit/Write/patch", lambda t: t in WRITE_TOOLS)):
            sel = [r for r in appr if pred(r["disp"]) and tpred(r["tool"])]
            c = sum(1 for r in sel if r["claimed"])
            cells[(label, tlabel)] = (len(sel), c)
            print(f"  {label:<26}{tlabel:<14}{len(sel):>9}{c:>9}{(100.0*c/len(sel) if sel else 0):>6.0f}%")
    (n1, c1) = cells[("genuinely writes gated path", "Bash")]
    (n2, c2) = cells[("genuinely writes gated path", "Edit/Write/patch")]
    (n3, c3) = cells[("marker FP (read/named only)", "Bash")]
    print(f"\n  Bash writes vs Edit/Write writes : p = {fisher_2x2(c1, n1-c1, c2, n2-c2):.2g}")
    print(f"  within Bash, writes vs marker FPs: p = {fisher_2x2(c1, n1-c1, c3, n3-c3):.2g}"
          "   (direction is BACKWARDS from the FP hypothesis)")
    print("\n  within-seat, genuine writes only, Bash vs Edit/Write:")
    for seat in ("claude-code", "kimi-code", "codex"):
        s = [r for r in appr if r["disp"] == "WRITE" and r["seat"] == seat]
        b = [r for r in s if r["tool"] == "Bash"]; e = [r for r in s if r["tool"] in WRITE_TOOLS]
        bc = sum(1 for r in b if r["claimed"]); ec = sum(1 for r in e if r["claimed"])
        p = fisher_2x2(bc, len(b)-bc, ec, len(e)-ec) if b and e else float("nan")
        print(f"    {seat:<14}Bash {rate(bc,len(b)):>14}   Edit/Write {rate(ec,len(e)):>14}   p={p:.2g}")
    print()

    # --- the /tmp-scratch class ---
    dec = [(r, tmp_only(r)) for r in recs]
    decidable = [(r, v) for r, v in dec if v is not None]
    inclass = [r for r, v in decidable if v]
    ia = [r for r in inclass if r["status"] == "approved"]
    ic = [r for r in ia if r["claimed"]]
    print("THE /tmp-SCRATCH CLASS  (every marker-matched token resolves under /tmp)")
    print(f"  decidable escalations (act text uncensored, marker tokenisable): {len(decidable)}")
    print(f"  in class                : {rate(len(inclass), len(decidable))}")
    print(f"  ...of those, approved   : {len(ia)}")
    print(f"  ...of those, CLAIMED    : {len(ic)}   <- a governance permit spent to write to scratch")
    print("  by seat+tool:")
    bt = collections.Counter((r["seat"], r["tool"]) for r in inclass)
    for (s, t), n in bt.most_common(6):
        print(f"    {s:<14}{t:<12}{n:>4}")
    print()

    # --- re-escalation ---
    # PRINTED AS A SURFACE, NEVER A POINT. The published 22% was a single (gap, sim)
    # setting quoted without either parameter. The sweep below is why that was wrong:
    # the SIMILARITY FLOOR carries essentially all the variance (0% -> 22% across
    # defensible thresholds) while the GAP -- the parameter that LOOKS arbitrary -- is
    # nearly inert. Quoting this rate without the similarity floor is quoting a knob.
    scored, _ = reescalations(recs, a.gap, a.sim)
    print("RE-ESCALATION (unclaimed Bash, respelled, different act_digest)")
    print(f"  scorable (unclaimed Bash, has digest, act text intact): {len(scored)}")
    print(f"  {'':<10}" + "".join(f"gap<={g}s".rjust(12) for g in (600, 1800, 7200)))
    for sim in (0.70, 0.80, 0.90, 0.95):
        cells = []
        for g in (600, 1800, 7200):
            sc, h = reescalations(recs, g, sim)
            cells.append(f"{len(h)}/{len(sc)} = {100.0*len(h)/len(sc):.0f}%" if sc else "n/a")
        print(f"  sim>={sim:<5}" + "".join(c.rjust(12) for c in cells))
    print("  ^ the similarity floor moves this by 20 points; the gap moves it by 5.")
    _, hits = reescalations(recs, a.gap, a.sim)
    print(f"  exemplars at gap<={a.gap}s sim>={a.sim}:")
    for r, s in hits[:3]:
        ratio = difflib.SequenceMatcher(None, _acttext(r), _acttext(s)).ratio()
        print(f"    sim={ratio:.2f}  +{int(_ts(s['at'])-_ts(r['at']))}s  {_acttext(r)[:60]!r}")
    print("\n  CONFOUND, stated so it is not re-derived: respelling and claim-path failure")
    print("  are not separable in this corpus. The clearest exemplars were already")
    print("  explained as instrumental re-escalation BECAUSE claims were not landing.")


if __name__ == "__main__":
    main()
