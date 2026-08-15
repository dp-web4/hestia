#!/usr/bin/env python3
"""Are the payload_sha256 recompute failures FORGED digests or COLLAPSED records?

A failed recompute has two causes that render identically in the chain: the member
misreported the digest, or `attempted` was stored with newlines collapsed to spaces while
the digest committed to the raw string. This probe separates them CONSTRUCTIVELY: for each
mismatching row, enumerate space->newline substitutions and look for one that reproduces the
stored digest. A hit proves the digest was honest and the RECORD was lossy.

Asymmetric by construction: a solve is proof of honesty; an unsolved row is NOT proof of
forgery, because repeated collapse, tabs and leading indentation destroy count information
this single transform cannot restore. Reported as unsolved, never as refuted.

Reads only. Run: python3 tools/claude_collapse_reconstruction_probe.py
"""
sys.path.insert(0, "tools")
from chain_walk import ChainWalker, payload
def c(a): return hashlib.sha256(json.dumps({"command": a}).encode()).hexdigest()[:16]
rows=[]
for e in ChainWalker().walk(max_entries=20000):
    if e.get("eventType")!="policy_decision": continue
    p=payload(e)
    if "payload_sha256" not in p or "rule_name" in p: continue
    d=(p.get("payload_sha256") or "").strip(); a=p.get("attempted") or ""
    if d and a and "…[truncated]" not in a and "[REDACTED" not in a and "***" not in a and c(a)!=d:
        rows.append((p.get("plugin_id"),a,d))
solved=unsolved=skipped=0
for seat,a,d in rows:
    idx=[i for i,ch in enumerate(a) if ch==" "]
    if len(idx)>20: skipped+=1; continue
    hit=None
    for r in range(1,len(idx)+1):
        for combo in itertools.combinations(idx,r):
            b=list(a)
            for i in combo: b[i]="\n"
            s="".join(b)
            if c(s)==d: hit=s; break
        if hit: break
    if hit:
        solved+=1
        if solved<=3: print(f"SOLVED {seat}: raw had {hit.count(chr(10))} newline(s)\n  {hit[:150]!r}\n")
    else: unsolved+=1
print(f"whitespace-collapse reconstruction: solved={solved} unsolved={unsolved} skipped(>20 spaces)={skipped} of {len(rows)}")
