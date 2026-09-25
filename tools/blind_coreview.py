#!/usr/bin/env python3
"""blind_coreview: seal / reveal / stats for blind co-review rounds.

The mesh's echo measurement (findings/echo-or-independence-the-mesh-measured-2026-09-23.md)
bottomed out at n=10 provably-blind pairs in five weeks of chain. Retrospective mining is
exhausted; this instrument manufactures blindness prospectively:

  seal   — a reviewer commits sha256(verdict + basis) BEFORE reading any peer factor
  reveal — both seals published; the texts follow; nothing can be revised after
  stats  — agreement vs the independence null (the arc's own formula), with PABAK
           alongside Cohen's kappa because the marginals here are prevalence-lopsided
           (constraint 1 of the labeling protocol, written before the reveal, proved
           load-bearing at it)

Probe records are terminal historical escalations — nothing to authorize, so the probe
is cheap and safe, and a reviewer's seal cannot leak into a ruling.

Usage:
  blind_coreview.py seal  --reviewer kimi-code --eid <id> --verdict concur --basis-file f.md
  blind_coreview.py verify --seal-file s.json --verdict concur --basis-file f.md
  blind_coreview.py stats --pairs pairs.json   # pairs.json: [{a_dissent: bool, b_dissent: bool,
                                              #   marginals: {name: dissent_rate}}]
"""
import argparse
import hashlib
import json
import sys
import time


def canonical(verdict: str, basis: str) -> bytes:
    return (verdict.strip().lower() + "\n---\n" + basis.strip()).encode()


def seal(reviewer: str, eid: str, verdict: str, basis: str) -> dict:
    blob = canonical(verdict, basis)
    return {"reviewer": reviewer, "eid": eid, "sha256": hashlib.sha256(blob).hexdigest(),
            "sealed_at": time.time(),
            "note": "commitment over (verdict, basis); text revealed only after both seals"}


def verify(seal_doc: dict, verdict: str, basis: str) -> bool:
    return hashlib.sha256(canonical(verdict, basis)).hexdigest() == seal_doc["sha256"]


def stats(pairs: list) -> dict:
    """agreement, independence null, excess; kappa and PABAK on the dissent bit."""
    n = len(pairs)
    if not n:
        return {"n": 0}
    agree = sum(1 for p in pairs if p["a_dissent"] == p["b_dissent"])
    null = 0.0
    for p in pairs:
        pa = p["marginals"][p["a_name"]]
        pb = p["marginals"][p["b_name"]]
        null += pa * pb + (1 - pa) * (1 - pb)
    null /= n
    # kappa family on the dissent bit
    a_d = sum(p["a_dissent"] for p in pairs) / n
    b_d = sum(p["b_dissent"] for p in pairs) / n
    po = agree / n
    pe = a_d * b_d + (1 - a_d) * (1 - b_d)
    kappa = (po - pe) / (1 - pe) if pe < 1 else None
    pabak = 2 * po - 1
    return {"n": n, "agree": agree, "raw_agreement": round(po, 4),
            "independence_null": round(null, 4), "excess_pts": round(100 * (po - null), 1),
            "kappa": round(kappa, 3) if kappa is not None else None,
            "pabak": round(pabak, 3),
            "marginals": {"a_dissent": round(a_d, 3), "b_dissent": round(b_d, 3)}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seal")
    s.add_argument("--reviewer", required=True)
    s.add_argument("--eid", required=True)
    s.add_argument("--verdict", required=True)
    s.add_argument("--basis-file", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--seal-file", required=True)
    v.add_argument("--verdict", required=True)
    v.add_argument("--basis-file", required=True)
    st = sub.add_parser("stats")
    st.add_argument("--pairs", required=True)
    a = ap.parse_args()
    if a.cmd == "seal":
        print(json.dumps(seal(a.reviewer, a.eid, a.verdict, open(a.basis_file).read()), indent=1))
    elif a.cmd == "verify":
        ok = verify(json.load(open(a.seal_file)), a.verdict, open(a.basis_file).read())
        print("VERIFIED" if ok else "SEAL MISMATCH")
        return 0 if ok else 1
    else:
        print(json.dumps(stats(json.load(open(a.pairs))), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
