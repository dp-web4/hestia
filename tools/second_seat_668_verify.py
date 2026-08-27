#!/usr/bin/env python3
"""Full second-seat verification at the matched window (start 2026-08-12T12:00Z)."""
import json, sys, math
from collections import Counter
sys.path.insert(0, "/tmp/wt-markerfp-kimi/tools")
from marker_fp_classify import classify

START = "2026-08-12T12:00:00"
d = json.load(open("/tmp/668_esc_corpus_wide.json"))
rows = d["rows"]
opened = {}
for r in rows:
    if r["type"] == "gate_escalation_opened":
        p = r["payload"]
        opened[p["escalation_id"]] = {"id": p["escalation_id"], "seat": p.get("plugin_id"),
            "tool": p.get("tool_name"), "marker": p.get("marker"),
            "reason": p.get("stated_reason") or "", "ts": r["ts"], "digest": p.get("act_digest")}
status, claimed = {}, set()
for r in rows:
    if r["type"] == "gate_escalation_decided":
        status[r["payload"]["escalation_id"]] = r["payload"].get("status")
    if r["type"] == "gate_escalation_claimed":
        claimed.add(r["payload"]["escalation_id"])
sel = []
for e in opened.values():
    if e["ts"] < START: continue
    e["approved"] = status.get(e["id"]) == "approved"
    e["claimed"] = e["id"] in claimed
    e["verdict"], e["why"] = classify(e["reason"], e["marker"] or "", e["tool"] or "Bash")
    sel.append(e)
ap = [e for e in sel if e["approved"]]

def fisher(a, b, c, d_):
    # one-sided-ish two-tailed Fisher via hypergeometric sum (small n ok)
    from math import comb
    n = a+b+c+d_; r1 = a+b; c1 = a+c
    def p(x): return comb(r1, x)*comb(n-r1, c1-x)/comb(n, c1)
    lo, hi = max(0, c1-(n-r1)), min(r1, c1)
    p_obs = p(a)
    return sum(p(x) for x in range(lo, hi+1) if p(x) <= p_obs + 1e-12)

EW = ("Edit","Write","apply_patch","NotebookEdit")
def cells(pred):
    x = [e for e in ap if pred(e)]
    return len(x), sum(1 for e in x if e["claimed"])

bw = cells(lambda e: e["tool"]=="Bash" and e["verdict"]=="WRITE")
bf = cells(lambda e: e["tool"]=="Bash" and e["verdict"]=="READ_ONLY")
ew = cells(lambda e: e["tool"] in EW and e["verdict"]=="WRITE")
print("Bash WRITE:", bw, "rate", f"{bw[1]/bw[0]:.1%}")
print("Bash FP(RO):", bf, "rate", f"{bf[1]/bf[0]:.1%}")
print("EW WRITE:", ew, "rate", f"{ew[1]/ew[0]:.1%}")
print("p(BashW vs EW):", f"{fisher(bw[1], bw[0]-bw[1], ew[1], ew[0]-ew[1]):.2e}")
print("p(BashW vs BashFP):", f"{fisher(bw[1], bw[0]-bw[1], bf[1], bf[0]-bf[1]):.3f}")
for s in ("claude-code","kimi-code","codex"):
    b = cells(lambda e: e["seat"]==s and e["tool"]=="Bash" and e["verdict"]=="WRITE")
    w = cells(lambda e: e["seat"]==s and e["tool"] in EW and e["verdict"]=="WRITE")
    p = fisher(b[1], b[0]-b[1], w[1], w[0]-w[1]) if b[0] and w[0] else float("nan")
    print(f"within {s}: Bash {b[1]}/{b[0]}={b[1]/b[0]:.0%} vs EW {w[1]}/{w[0]}={w[1]/w[0]:.0%} p={p:.2e}" if b[0] and w[0] else f"within {s}: Bash {b} EW {w}")

# /tmp class + decidable
decidable = [e for e in sel if e["verdict"] in ("WRITE","READ_ONLY","READ_ONLY_PREFIX","PROSE")]
print("decidable:", len(decidable), "(target 212)")
tmp = [e for e in decidable if e["verdict"]=="READ_ONLY" and ("/tmp" in e["why"])]
print("/tmp READ_ONLY:", len(tmp), "approved:", sum(1 for e in tmp if e["approved"]),
      "claimed:", sum(1 for e in tmp if e["claimed"]), "(target 53/46/26)")
print("/tmp by tool:", Counter(e["tool"] for e in tmp))
tc = cells(lambda e: e["verdict"]=="READ_ONLY" and "/tmp" in e["why"])
print("/tmp approved/claimed:", tc)
# per-seat /tmp approved share of that seat's approved (their per-seat rates: claude Edit 49%, codex apply_patch 50%, kimi Bash 24%)
print("verdict census (approved):", Counter(e["verdict"] for e in ap))
