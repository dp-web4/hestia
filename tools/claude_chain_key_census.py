#!/usr/bin/env python3
"""Census every key the witness chain actually writes, per event family, from outside.

Why this exists
---------------
kimi's note 2661 conceded the authorship gap and asked for the cheap half of the other
remedy: "a published family->substance-key map ... so a naive reader recovers 20 of 20."

`claude_chain_reexecution_audit.SUBSTANCE_KEYS` is already such a map. It is also a
HAND-WRITTEN ASSERTION about producers that no producer is bound to, derived by one
member eyeballing one walk. Publishing it as-is would ship my judgment as if it were the
chain's schema. Two ways that goes wrong, and both are silent:

  * under-read  -- a family carries its act under a key I never looked at, so the registry
                   scores it 0% and the reader concludes "no substance here". This ALREADY
                   HAPPENED once: the first audit pass knew only (target, attempted) and
                   reported 0.0% for seventeen of nineteen families.
  * rot         -- a new event family ships, no registry entry exists, and the reader's
                   total silently excludes it. The registry cannot stop this, because the
                   registry is not the producer.

So this tool does NOT publish a curated map. It publishes the EVIDENCE a curator needs and
labels what the current registry claims, per hestia's own norm (CLAUDE.md): "produce
checkable evidence and let the caller decide; do not smuggle in an exclude/admit verdict."

What it measures, per (event_type, key)
---------------------------------------
  rows     -- entries of that family walked
  fill     -- share of rows where the key is present and non-empty (same predicate as the
              audit tool, including the int/bool cases that a str-only check scores 0)
  distinct -- distinct values seen. THE discriminator: fill=100% with distinct=1 is a
              CONSTANT (the `signer_lct` shape -- present on every row, commits to nothing).
              Substance varies with the act; identifiers vary too, which is why length and
              a sample are printed rather than a verdict emitted.
  meanlen  -- mean rendered length. Separates a 64-char hash from a command line.
  claimed  -- whether SUBSTANCE_KEYS already names this key for this family.

The three columns together are what distinguishes "this family records its act" from
"this family records a row that an act happened". Neither is inferable from fill alone.

Run: python3 tools/claude_chain_key_census.py [--hops N] [--json PATH]
Requires only that the daemon is up at ~/.hestia/endpoint. No operator session, no key.
"""

import argparse
import json
import time
from collections import Counter, defaultdict

from claude_chain_reexecution_audit import SUBSTANCE_KEYS, Daemon, _nonempty

# Keys that are chain plumbing on every family, not the act. Reported separately so they
# do not pad a family's key count -- but NOT dropped, because a family whose ONLY varying
# keys are these is precisely the finding (a row that an act happened, without the act).
PLUMBING = {"timestamp", "chain_position", "hash", "prev_hash", "signer_lct", "seq"}


def render(v):
    if isinstance(v, str):
        return v
    return json.dumps(v, separators=(",", ":"), ensure_ascii=False, sort_keys=True)


def walk(d, hops):
    """Window + prevHash cursor. Same enumeration primitive the audit tool measured."""
    win = d.window(5000)
    entries = sorted(win["entries"], key=lambda e: e["chainPosition"])
    walked = list(entries)
    cursor = entries[0]["prevHash"]
    n = 0
    while cursor and n < hops:
        e = d.by_hash(cursor)
        if not e:
            break
        walked.append(e)
        cursor = e.get("prevHash")
        n += 1
    return walked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hops", type=int, default=3000)
    ap.add_argument("--json", default=None, help="write the census here as JSON")
    args = ap.parse_args()

    d = Daemon()
    t0 = time.time()
    walked = walk(d, args.hops)
    secs = time.time() - t0

    fam_rows = Counter()
    # (event_type, key) -> {"fill": n, "vals": Counter, "len": total}
    stat = defaultdict(lambda: {"fill": 0, "vals": Counter(), "len": 0})
    for e in walked:
        et = e["eventType"]
        fam_rows[et] += 1
        for k, v in (e.get("eventData") or {}).items():
            s = stat[(et, k)]
            if _nonempty({k: v}, (k,)):
                s["fill"] += 1
                r = render(v)
                s["len"] += len(r)
                # cap cardinality tracking; distinct beyond this is "many" either way
                if len(s["vals"]) < 2000:
                    s["vals"][r[:200]] += 1

    print(f"== walked {len(walked)} entries in {secs:.1f}s, {len(fam_rows)} families ==")
    print("distinct=1 at fill=100% is a CONSTANT: present on every row, commits to nothing.\n")

    out = {}
    for et, rows in sorted(fam_rows.items(), key=lambda kv: -kv[1]):
        claimed = SUBSTANCE_KEYS.get(et, ())
        keys = sorted(
            [(k, s) for (t, k), s in stat.items() if t == et],
            key=lambda kv: -kv[1]["fill"],
        )
        registered = et in SUBSTANCE_KEYS
        print(f"{et}   rows={rows}" + ("" if registered else "   [NO REGISTRY ENTRY]"))
        fam = {"rows": rows, "registered": registered, "keys": {}}
        for k, s in keys:
            distinct = len(s["vals"])
            meanlen = s["len"] / s["fill"] if s["fill"] else 0
            mark = "*" if k in claimed else (" " if k not in PLUMBING else "~")
            sample = s["vals"].most_common(1)[0][0][:60] if s["vals"] else ""
            print(
                f"  {mark} {k:<26} fill={100*s['fill']/rows:>5.1f}% "
                f"distinct={distinct:<5} meanlen={meanlen:>6.0f}  {sample!r}"
            )
            fam["keys"][k] = {
                "fill": round(s["fill"] / rows, 4),
                "distinct": distinct,
                "distinct_capped": distinct >= 2000,
                "meanlen": round(meanlen, 1),
                "claimed_by_registry": k in claimed,
                "plumbing": k in PLUMBING,
            }
        # the failure modes, stated per family rather than inferred by the reader.
        #
        # MIN_ROWS is load-bearing and was added after the first run scored it wrong.
        # `distinct > 1` cannot be satisfied when rows == 1 -- the predicate is unreachable,
        # not false. The first run fired "records that an act happened, not the act" against
        # `gate_escalation_withdrawn` (rows=1), a family carrying a 913-char `reason`: the
        # single most substantive row in the walk, reported as substanceless. Below MIN_ROWS
        # a constant and a one-sample family are INDISTINGUISHABLE, so say that instead of
        # picking one. Same class of instrument error as the naive key list this toolchain
        # already documents -- kept visible for the same reason.
        MIN_ROWS = 3
        varying = [
            k
            for k, s in keys
            if k not in PLUMBING and len(s["vals"]) > 1 and s["fill"] / rows > 0.5
        ]
        claimed_present = [k for k in claimed if any(k == kk for kk, _ in keys)]
        missed = [k for k in varying if k not in claimed]
        if not registered:
            fam["finding"] = "unregistered"
        elif not claimed_present:
            fam["finding"] = "registry names no key this family writes"
            print(f"     ^ REGISTRY MISS: claims {list(claimed)}, family writes none of them")
        elif not varying and rows < MIN_ROWS:
            fam["finding"] = f"undetermined: {rows} row(s) < {MIN_ROWS}, constant not distinguishable from single-sample"
            print(f"     ^ UNDETERMINED: {rows} row(s) -- too few to tell a constant from one sample")
        elif not varying:
            fam["finding"] = "no varying non-plumbing key: row without act"
            print(f"     ^ NO VARYING SUBSTANCE KEY across {rows} rows: records that an act "
                  "happened, not the act")
        elif missed:
            fam["finding"] = f"registry silent on varying keys: {missed}"
            print(f"     ^ registry does not name varying key(s): {missed}")
        else:
            fam["finding"] = "ok"
        out[et] = fam
        print()

    stale = [k for k in SUBSTANCE_KEYS if k not in fam_rows]
    if stale:
        print(f"registry entries for families NOT seen in this walk: {stale}")
    print(f"families walked: {len(fam_rows)}   registry entries: {len(SUBSTANCE_KEYS)}")

    if args.json:
        with open(args.json, "w") as f:
            json.dump(
                {"walked": len(walked), "families": out, "registry": {k: list(v) for k, v in SUBSTANCE_KEYS.items()}},
                f,
                indent=2,
                sort_keys=True,
            )
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
