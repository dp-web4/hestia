#!/usr/bin/env python3
"""blind_coreview_packet: build a round's probe packets and frozen manifest.

A packet is a PURE FUNCTION of the witness chain, so any seat can re-derive it and
compare digests — the builder exercises no discretion:

  packet bytes  = canonical JSON of {"packet_v": 1, "round", "eid", "opened_at",
                  "opened": the escalation's gate_escalation_opened payload VERBATIM}
  record_sha256 = sha256(packet bytes)   (no trailing newline; canonical form is the
                  instrument's: sort_keys, separators, ensure_ascii — blind_coreview.py)

The opened payload is the act as it was asked: it exists before any decision, so it
carries no ruling, no peer factors and no later commentary by construction ([A1]).
The builder reads ONLY the walker's pool record (blind_coreview_walk_pool.py), which
never stores terminal-event content, and as a second guard REFUSES a payload whose
keys name an outcome field. (expires_at is an opening-time TTL parameter, not an
outcome; the guard names its pattern so the line is checkable.)

Usage:
  blind_coreview_packet.py --pool pool.json --config round-config.json \
      --packets-dir DIR --manifest-out manifest.json

round-config.json is the manifest minus digests: {"round", "seats", "question",
"verdicts", "probes": [{"eid", "reviewers": [a, b]}]}. Build-time validation refuses
what verify --manifest would refuse at the first seal: probes unsorted or duplicated,
a pair that is not two distinct seats in sorted order, an empty question or verdict
encoding. Re-derivation: re-walk the chain, re-run this builder on the same config,
diff the manifest and packet bytes — any difference is evidence.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blind_coreview import canonical, record_digest  # noqa: E402

# Field names that belong to terminal or claimed events, never to an opened payload.
# "decid" covers decided/decided_by/decision; expiry (expires_at) is an opening-time
# parameter and deliberately NOT matched.
OUTCOME_KEY = re.compile(r"decid|withdraw|grant|ruling|verdict|outcome|terminal", re.I)


def fail(msg):
    sys.exit(f"blind_coreview_packet: {msg}")


def load_config(path):
    cfg = json.load(open(path))
    if not isinstance(cfg.get("round"), str) or not cfg["round"]:
        fail("config.round: want a non-empty string")
    seats = cfg.get("seats")
    if (not isinstance(seats, list) or len(seats) < 2
            or not all(isinstance(s, str) and s for s in seats)
            or seats != sorted(set(seats))):
        fail("config.seats: want >=2 distinct seat names, sorted")
    if not isinstance(cfg.get("question"), str) or not cfg["question"]:
        fail("config.question: the frozen question as presented must be non-empty")
    verdicts = cfg.get("verdicts")
    if (not isinstance(verdicts, list) or not verdicts
            or not all(isinstance(v, str) and v for v in verdicts)):
        fail("config.verdicts: the frozen encoding must be a non-empty list, "
             "abstention included as a verdict of its own")
    probes = cfg.get("probes")
    if not isinstance(probes, list) or not probes:
        fail("config.probes: want a non-empty list")
    eids = [p.get("eid") for p in probes]
    if (not all(isinstance(e, str) and e for e in eids)
            or eids != sorted(set(eids))):
        fail("config.probes: eids must be distinct and sorted")
    for p in probes:
        pair = p.get("reviewers")
        if (not isinstance(pair, list) or len(pair) != 2
                or not all(isinstance(r, str) and r for r in pair)
                or pair[0] == pair[1] or pair != sorted(pair)):
            fail(f"config probe {p.get('eid')!r}: reviewers must be two distinct "
                 f"seats in sorted order")
        if any(r not in seats for r in pair):
            fail(f"config probe {p.get('eid')!r}: pair {pair} names a non-seat")
    return cfg


def build(pool_path, cfg, packets_dir, manifest_out):
    opened = json.load(open(pool_path)).get("opened", {})
    os.makedirs(packets_dir, exist_ok=True)
    probes = []
    for p in cfg["probes"]:
        eid = p["eid"]
        rec = opened.get(eid)
        if rec is None:
            fail(f"{eid}: no gate_escalation_opened payload in the pool record")
        if "_ts" not in rec:
            fail(f"{eid}: pool record lacks the walker's _ts (chain timestamp)")
        payload = {k: v for k, v in rec.items() if k != "_ts"}
        bad = [k for k in payload if OUTCOME_KEY.search(k)]
        if bad:
            fail(f"{eid}: opened payload carries outcome-named field(s) {bad} — "
                 f"refusing to packetize")
        blob = canonical({"packet_v": 1, "round": cfg["round"], "eid": eid,
                          "opened_at": rec["_ts"], "opened": payload})
        with open(os.path.join(packets_dir, f"{eid}.json"), "wb") as f:
            f.write(blob)
        probes.append({"eid": eid, "record_sha256": record_digest(blob),
                       "reviewers": p["reviewers"]})
        print(f"{eid}  sha256:{record_digest(blob)[:16]}…  {len(blob)} B  "
              f"pair {' x '.join(p['reviewers'])}")
    manifest = {"round": cfg["round"], "seats": cfg["seats"],
                "question": cfg["question"], "verdicts": cfg["verdicts"],
                "probes": probes}
    with open(manifest_out, "wb") as f:
        f.write(canonical(manifest))
    print(f"manifest: {len(probes)} probes -> {manifest_out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pool", required=True,
                    help="walker pool record (blind_coreview_walk_pool.py output)")
    ap.add_argument("--config", required=True, help="round config JSON")
    ap.add_argument("--packets-dir", required=True)
    ap.add_argument("--manifest-out", required=True)
    a = ap.parse_args()
    build(a.pool, load_config(a.config), a.packets_dir, a.manifest_out)


if __name__ == "__main__":
    main()
