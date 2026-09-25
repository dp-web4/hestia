#!/usr/bin/env python3
"""blind_coreview v2: seal / reveal / stats for blind co-review rounds.

v2, after the pilot's two reviews (claude-code on 14554, codex on 14555):

- THE SEAL BINDS ITS ASSIGNMENT. v1 hashed only (verdict, basis); codex demonstrated that
  editing reviewer/eid/sealed_at still verified. The v2 commitment is sha256 over a
  versioned canonical serialization of: round id, reviewer, probe id, **digest of the
  exact presented record**, verdict, basis, and a fresh nonce (the nonce also kills
  guessing short bases from the published hash — claude-code's point).
- ORDER EVIDENCE IS THE MESH RECEIPT, not the sealer's clock. `sealed_at` remains for
  debugging; the auditable ordering claim is the forum-note's daemon-stamped queued_at.
- THE TWO NULLS ARE LABELED. `stats` reports the external-marginal independence null
  (each reviewer's dissent rate from live work, with its source window) separately from
  the within-sample expectation κ uses — the pilot oversamples contested classes, so a
  live-work null is a different baseline, not the same one (codex, response §3).
- Inputs are validated: verdicts are literal tokens, dissent bits literal booleans, rates
  finite in [0,1]. Pair records carry BOTH reviewer names per pair; no positional pooling.

Usage:
  blind_coreview.py seal   --round R1 --reviewer kimi-code --eid <id> \
      --record-file packet.md --verdict concur --basis-file basis.md
  blind_coreview.py reveal --seal-file s.json   # prints the full payload for publication
  blind_coreview.py verify --seal-file s.json --revealed-file r.json
  blind_coreview.py stats  --pairs pairs.json --rate kimi-code=0.263@window:2026-07..09-23 ...
"""
import argparse
import hashlib
import json
import secrets
import sys
import time

VERSION = 2
VERDICTS = ("concur", "dissent", "abstain")


def canonical(p: dict) -> bytes:
    """Byte-stable serialization of the whole commitment payload."""
    keys = ("version", "round", "reviewer", "eid", "record_sha256",
            "verdict", "basis", "nonce")
    return "\x00".join(str(p[k]) for k in keys).encode()


def seal(round_id: str, reviewer: str, eid: str, record_bytes: bytes,
         verdict: str, basis: str) -> dict:
    if verdict not in VERDICTS:
        raise SystemExit(f"verdict must be one of {VERDICTS}")
    payload = {"version": VERSION, "round": round_id, "reviewer": reviewer, "eid": eid,
               "record_sha256": hashlib.sha256(record_bytes).hexdigest(),
               "verdict": verdict, "basis": basis.strip(), "nonce": secrets.token_hex(16)}
    return {"commitment": hashlib.sha256(canonical(payload)).hexdigest(),
            "round": round_id, "reviewer": reviewer, "eid": eid,
            "sealed_at": time.time(),
            "note": "commitment over the full payload; publish via mesh (its queued_at is "
                    "the ordering evidence). Payload revealed only after all seals land.",
            "_payload": payload}


def reveal(seal_doc: dict) -> dict:
    return seal_doc["_payload"]


def verify(seal_doc: dict, revealed: dict) -> bool:
    return hashlib.sha256(canonical(revealed)).hexdigest() == seal_doc["commitment"] and \
        all(revealed[k] == seal_doc[k] for k in ("round", "reviewer", "eid"))


def stats(pairs: list, rates: dict) -> dict:
    """raw agreement; external-marginal independence null; within-sample kappa + PABAK."""
    n = len(pairs)
    if not n:
        return {"n": 0}
    for p in pairs:
        if not (isinstance(p.get("a_dissent"), bool) and isinstance(p.get("b_dissent"), bool)):
            raise SystemExit("dissent fields must be literal booleans")
    for name, (rate, window) in rates.items():
        if not (0.0 <= rate <= 1.0):
            raise SystemExit(f"rate for {name} outside [0,1]")

    agree = sum(1 for p in pairs if p["a_dissent"] == p["b_dissent"])
    po = agree / n
    ext_null = None
    if rates:
        vals = []
        for p in pairs:
            ra = rates.get(p["a_name"])
            rb = rates.get(p["b_name"])
            if ra and rb:
                vals.append(ra[0] * rb[0] + (1 - ra[0]) * (1 - rb[0]))
        ext_null = sum(vals) / len(vals) if vals else None
    a_d = sum(p["a_dissent"] for p in pairs) / n
    b_d = sum(p["b_dissent"] for p in pairs) / n
    pe = a_d * b_d + (1 - a_d) * (1 - b_d)
    kappa = (po - pe) / (1 - pe) if pe < 1 else None
    return {
        "n": n, "agree": agree, "raw_agreement": round(po, 4),
        "independence_null_EXTERNAL_marginals": (round(ext_null, 4) if ext_null is not None else None),
        "external_rates_source": {k: v[1] for k, v in rates.items()},
        "excess_pts_vs_external": (round(100 * (po - ext_null), 1) if ext_null is not None else None),
        "within_sample_expected_agreement": round(pe, 4),
        "kappa": round(kappa, 3) if kappa is not None else None,
        "pabak": round(2 * po - 1, 3),
        "round_marginals": {"a_dissent": round(a_d, 3), "b_dissent": round(b_d, 3)},
        "verdict_2x2": {
            "both_dissent": sum(1 for p in pairs if p["a_dissent"] and p["b_dissent"]),
            "both_concur": sum(1 for p in pairs if not p["a_dissent"] and not p["b_dissent"]),
            "a_only": sum(1 for p in pairs if p["a_dissent"] and not p["b_dissent"]),
            "b_only": sum(1 for p in pairs if not p["a_dissent"] and p["b_dissent"]),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seal")
    s.add_argument("--round", required=True, dest="round_id")
    s.add_argument("--reviewer", required=True)
    s.add_argument("--eid", required=True)
    s.add_argument("--record-file", required=True)
    s.add_argument("--verdict", required=True)
    s.add_argument("--basis-file", required=True)
    r = sub.add_parser("reveal")
    r.add_argument("--seal-file", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--seal-file", required=True)
    v.add_argument("--revealed-file", required=True)
    st = sub.add_parser("stats")
    st.add_argument("--pairs", required=True)
    st.add_argument("--rate", action="append", default=[],
                    help="name=rate@window, e.g. kimi-code=0.263@2026-07..2026-09-23")
    a = ap.parse_args()
    if a.cmd == "seal":
        doc = seal(a.round_id, a.reviewer, a.eid, open(a.record_file, "rb").read(),
                   a.verdict, open(a.basis_file).read())
        print(json.dumps(doc, indent=1))
    elif a.cmd == "reveal":
        print(json.dumps(reveal(json.load(open(a.seal_file))), indent=1))
    elif a.cmd == "verify":
        ok = verify(json.load(open(a.seal_file)), json.load(open(a.revealed_file)))
        print("VERIFIED" if ok else "SEAL OR ASSIGNMENT MISMATCH")
        return 0 if ok else 1
    else:
        rates = {}
        for spec in a.rate:
            name, rest = spec.split("=", 1)
            rate, _, window = rest.partition("@")
            rates[name] = (float(rate), window or "unspecified")
        print(json.dumps(stats(json.load(open(a.pairs)), rates), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
