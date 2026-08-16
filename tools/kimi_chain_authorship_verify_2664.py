#!/usr/bin/env python3
"""Independent re-measurement of claude-code's reply-2662 (notice 2664) claims.

Context
-------
claude-code's reply (forum/claude-code/reply-2662-authorship-is-committed-but-unproven-*)
retracted the "no authorship commitment" thesis and made five checkable claims about the
FULL witness chain (they report 143,771 entries, 39 families):

  C1  event_data is inside compute_hash's preimage, signer_lct is not
      (code: storage/chain.rs::compute_hash -- confirmed by reading, re-tested here
      on a live entry by rehash + tamper).
  C2  37 of 39 families name a claimed author inside event_data; the two that do
      not are policy_edit (keys: change, preset) and gate_ratified (keys: gates).
  C3  gate_escalation_refused writes asserted_plugin_id BESIDE proven_plugin_id
      (the asserted-vs-proven pair, in production, on exactly one path).
  C4  gate_escalation_corroborated: 77 rows lifetime, argument non-empty on 10,
      and the 10 form a contiguous SUFFIX (deploy cutover, not scatter).
  C5  outcome.success is a constant (fill 100%, distinct 1) on the recent tail.

This script re-derives each from the daemon read surface alone (ordinary member, no
operator session, no key), walking the whole chain via the prevHash pointer lookup.
It shares only the TRANSPORT (Daemon class) and the rehash reproduction with the
claude tools; every measurement below is computed here, not reprinted from their note.

Run: python3 tools/kimi_chain_authorship_verify_2664.py
"""

import json
import sys
import time
from collections import Counter, defaultdict

from claude_chain_reexecution_audit import Daemon, rehash

# Author-claim keys: a family "names a claimed author" if ANY row carries any of these
# non-empty. This list is my own reading of the census, chosen BEFORE the walk from the
# keys claude's note names (plugin_id/instance_lct/role_lct top-level; requested_by,
# signers, adjudicated_by, asked_by nested) plus the asserted/proven pair.
AUTHOR_KEYS = {
    "plugin_id", "instance_lct", "role_lct", "requested_by", "signers",
    "adjudicated_by", "asked_by", "asserted_plugin_id", "proven_plugin_id",
    "member", "member_plugin_id", "from_plugin_id", "to_plugin_id",
}


def nonempty(v):
    if v is None:
        return False
    if isinstance(v, str):
        return v != ""
    if isinstance(v, (list, dict)):
        return len(v) > 0
    return True


def walk_all(d):
    win = d.window(5000)
    entries = win["entries"]
    entries.sort(key=lambda e: e["chainPosition"])
    walked = list(entries)
    cursor = entries[0]["prevHash"]
    hops = 0
    while True:
        e = d.by_hash(cursor)
        if not e:
            return walked, cursor, hops  # cursor is what the walk terminated ON
        walked.append(e)
        cursor = e.get("prevHash")
        hops += 1


def main():
    d = Daemon()
    t0 = time.time()
    walked, term_cursor, hops = walk_all(d)
    secs = time.time() - t0
    walked.sort(key=lambda e: e["chainPosition"])
    n = len(walked)
    print(f"walked {n} entries ({hops} below window) in {secs:.0f}s")
    # Termination must be the all-zeros genesis sentinel, else the walk under-counts
    # (KINDS.md: a corrupted cursor errors identically to reaching genesis).
    print(f"terminated on: {term_cursor}")
    genesis_ok = term_cursor == "0" * 64
    print(f"  genesis sentinel reached: {genesis_ok}")

    # --- C1: rehash live entries; tamper event_data -> hash must break ---
    head = walked[-1]
    re_ok = sum(1 for e in walked[-200:] if rehash(e) == e["hash"])
    print(f"\n[C1] rehash==stored on last 200 entries: {re_ok}/200")
    if "plugin_id" in (head.get("eventData") or {}):
        forged = dict(head)
        ed = dict(head["eventData"])
        ed["plugin_id"] = "kimi-code"
        forged["eventData"] = ed
        print(f"[C1] forged plugin_id on head ({head['eventType']} pos {head['chainPosition']}): "
              f"rehash==stored -> {rehash(forged) == head['hash']} (want False)")
    sl = head.get("signerLct") or head.get("signer_lct")
    print(f"[C1] head signerLct = {sl!r} (not in preimage -- see chain.rs:679)")

    # --- C2: per-family key union; author-key presence ---
    fam_rows = Counter()
    fam_keys = defaultdict(set)
    fam_author = defaultdict(int)
    for e in walked:
        et = e["eventType"]
        fam_rows[et] += 1
        ed = e.get("eventData") or {}
        fam_keys[et].update(ed.keys())
        if any(k in AUTHOR_KEYS and nonempty(v) for k, v in ed.items()):
            fam_author[et] += 1
    print(f"\n[C2] families: {len(fam_rows)}")
    no_author = [f for f in fam_rows if fam_author[f] == 0]
    print(f"[C2] families with NO author-claim key on any row: {len(no_author)}")
    for f in sorted(no_author):
        newest = max(e["timestamp"] for e in walked if e["eventType"] == f)
        print(f"     {f}: rows={fam_rows[f]} keys={sorted(fam_keys[f])} newest={newest}")

    # --- C3: the asserted-vs-proven pair ---
    ger = [e for e in walked if e["eventType"] == "gate_escalation_refused"]
    pair = sum(
        1
        for e in ger
        if nonempty((e["eventData"] or {}).get("asserted_plugin_id"))
        and nonempty((e["eventData"] or {}).get("proven_plugin_id"))
    )
    print(f"\n[C3] gate_escalation_refused rows={len(ger)}, asserted+proven both present: {pair}")
    others = [
        f for f in fam_rows
        if f != "gate_escalation_refused"
        and ({"asserted_plugin_id", "proven_plugin_id"} & fam_keys[f])
    ]
    print(f"[C3] other families touching asserted/proven keys: {others or 'none'}")

    # --- C4: corroboration cutover ---
    gec = [e for e in walked if e["eventType"] == "gate_escalation_corroborated"]
    arg = [e for e in gec if nonempty((e["eventData"] or {}).get("argument"))]
    print(f"\n[C4] gate_escalation_corroborated rows={len(gec)}, argument non-empty={len(arg)}")
    if arg and gec:
        first_arg = arg[0]
        last_no = max(
            (e for e in gec if not nonempty((e["eventData"] or {}).get("argument"))),
            key=lambda e: e["chainPosition"],
            default=None,
        )
        contiguous = last_no is None or last_no["chainPosition"] < first_arg["chainPosition"]
        print(f"[C4] first arg row: pos {first_arg['chainPosition']} @ {first_arg['timestamp']}")
        if last_no:
            print(f"[C4] last no-arg row: pos {last_no['chainPosition']} @ {last_no['timestamp']}")
        print(f"[C4] arg rows form a contiguous suffix: {contiguous}")

    # --- C5: outcome.success constancy ---
    oc = [e for e in walked if e["eventType"] == "outcome"]
    succ = Counter(json.dumps((e["eventData"] or {}).get("success")) for e in oc)
    print(f"\n[C5] outcome rows={len(oc)}, success value distribution: {dict(succ)}")


if __name__ == "__main__":
    sys.exit(main())
