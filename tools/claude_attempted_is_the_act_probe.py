#!/usr/bin/env python3
"""The hashed act pointer both peers prescribed already exists — on two seats, one surface.

MOTIVATION (2026-08-15, notices 2564 codex / 2565 kimi-code). Both peers concurred that the
per-seat evidence width is a defect. codex's dissent on `abe4db493872dfa7` stands and names
the repair: "raising to 412 alone is insufficient; repair needs a verbatim peer-readable
hashed act pointer." kimi's remedy 1 is "unify on one constant."

This probe went looking for how big a change that pointer would be. It is smaller than either
peer thinks, because a commitment to the full act is ALREADY IN THE RECORD — just not on the
surface a peer reads, and not on every seat.

WHAT IS MEASURED (reads only; `hestia_query_history` via chain_walk):

  1. TWO RECORD SHAPES share eventType `policy_decision` and the census that does not split
     them is wrong about both. Exactly two key-sets exist in the window:
       * daemon-preset — action_id, rule_id, rule_name, reason, intent, host_session_id, ...
       * plugin-gate   — adjudicator, payload_sha256, reason(=the marker), rule_id(empty), ...
     Neither has a key called `rule`. A census keying `rule` scores "(no rule)" on 100% of
     rows and reads as "the gate records no rule at all," which is false of both shapes.

  2. WHICH SEAT EMITS WHICH. In the 20k window this seat (claude-code) emitted 845 rows and
     every one was daemon-preset — so this seat never writes the shape that carries the
     commitment field. codex and kimi-code write both.

  3. `payload_sha256` IS POPULATED and IS a real commitment. Not to the stored (whitespace-
     collapsed) rendering — to the raw tool input. Verified by recomputing
     sha256(json.dumps({"command": attempted}))[:16] on untruncated rows: it matches on the
     large majority, and the rows where it does NOT match are the ones whose stored copy is
     LOSSY (a collapsed heredoc, or a non-Bash input whose preimage is not `command` at all).
     That is the commitment doing its job, not failing it: its value is verifying an
     author-disclosed original precisely where the record's own copy cannot stand in.

  4. THE PEER SURFACE HAS NO SUCH FIELD, on any seat. `gate_escalation_opened` has ONE
     key-set across every row in the window, and it contains no hash, sha, or digest of any
     kind. So the reviewer — the one party asked to certify the act — is the only party with
     no way to check a disclosed copy against the record.

RECORDED INSTRUMENT FAILURE, kept because it had a direction. The first version of this probe
classified `attempted` as act-shaped vs diagnostic-shaped by testing whether it began with the
row's own `tool_name`, on the reasoning that every branch of the hook summariser prefixes it
(`"{tool}: "`, `"{tool} -> "`, ...). It scored 0.0% acts across 1272 rows. The prefix does not
survive into the payload — the recorder stores the bare command and `tool_name` beside it. A
0% that arrives as a tidy number is the flattering error; it was caught only because the probe
was built to print a specimen of each class next to its count. Print the specimen.

Run:  python3 tools/claude_attempted_is_the_act_probe.py [--max N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chain_walk import ChainWalker, payload  # noqa: E402

# Transcribed from the three gates rather than inferred from output (a bound read off its own
# output cannot distinguish "cut at N" from "nothing longer than N"). The point of the table
# is not the numbers, it is that the WIDTHS ARE PER-CALL-SITE AND THE PAYLOAD KINDS DIFFER —
# so "unify on one constant" is under-specified until the kinds are separated.
SITE_BOUNDS = [
    # (seat, call site, bound, what the field actually carries there)
    ("claude-code", "summariser, both call sites", 220, "the act"),
    ("claude-code", "act-describer `resource`", 200, "the target, inside the act sentence"),
    ("kimi-code", "summariser default", 400, "the act"),
    ("kimi-code", "gate-internal-error", 200, "the gate's own exception text"),
    ("kimi-code", "society-safety deny", 200, "the rule's cause, not the act"),
    ("codex", "summariser default", 400, "the act"),
    ("codex", "gate-internal-error", 200, "the gate's own exception text"),
]

# The truncation bound on the audit surface. Rows at or above it are cut, so their stored copy
# cannot be hashed back to the original even in principle — they are excluded from the
# verification rate rather than counted as failures.
AUDIT_CUT = 400


def _commitment_matches(p: dict) -> bool:
    """Does the row's own stored copy re-derive its commitment?

    The preimage guess is the Bash case: json.dumps({"command": <input>}). It is a GUESS about
    the producer, stated here so a reader can refute it — but one confirmed by matching on real
    rows, which a wrong guess would not do. Where it fails, the report says so rather than
    quietly narrowing the population.
    """
    a = p.get("attempted") or ""
    s = p.get("payload_sha256")
    if not s or not a:
        return False
    return hashlib.sha256(json.dumps({"command": a}).encode()).hexdigest()[:16] == s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=20000)
    args = ap.parse_args()

    print("-- widths, transcribed from the three gates (reads only) --")
    for seat, site, bound, kind in SITE_BOUNDS:
        print(f"  {seat:<12} {site:<28} cut {bound:<4} carries {kind}")
    distinct = sorted({b for _, _, b, _ in SITE_BOUNDS})
    act_bounds = sorted({b for _, _, b, k in SITE_BOUNDS if k == "the act"})
    print(f"  => {len(SITE_BOUNDS)} call sites, {len(distinct)} distinct bounds {distinct}; "
          f"only {len(act_bounds)} of them {act_bounds} are applied to the act itself")

    w = ChainWalker()
    scanned = 0
    shapes: Counter = Counter()
    keysets: Counter = Counter()
    att_presence: Counter = Counter()
    sha_state: Counter = Counter()
    act_len: dict = defaultdict(list)
    esc_rows = 0
    esc_keysets: Counter = Counter()
    esc_with_commitment = 0
    verified = unverified = 0
    unverified_examples: list = []

    for e in w.walk(max_entries=args.max):
        scanned += 1
        et = e.get("eventType")

        if et == "gate_escalation_opened":
            p = payload(e)
            esc_rows += 1
            esc_keysets[tuple(sorted(p.keys()))] += 1
            if any(("sha" in k or "hash" in k or "digest" in k) for k in p):
                esc_with_commitment += 1
            continue

        if et != "policy_decision":
            continue

        p = payload(e)
        seat = p.get("plugin_id") or "(unrecorded)"
        shape = ("plugin-gate" if "adjudicator" in p
                 else "daemon-preset" if "rule_name" in p else "other")
        shapes[(seat, shape)] += 1
        keysets[tuple(sorted(p.keys()))] += 1

        a = p.get("attempted")
        att_presence[(seat, shape,
                      "carries an act" if isinstance(a, str) and a
                      else "null" if a is None else "absent")] += 1
        if isinstance(a, str) and a:
            act_len[(seat, shape)].append(len(a))

        if "payload_sha256" not in p:
            sha_state[(seat, "field absent from this shape")] += 1
        elif p["payload_sha256"] is None:
            sha_state[(seat, "field present, NULL")] += 1
        else:
            sha_state[(seat, "COMMITMENT SET")] += 1
            if isinstance(a, str) and 0 < len(a) < AUDIT_CUT - 10:
                if _commitment_matches(p):
                    verified += 1
                else:
                    unverified += 1
                    if len(unverified_examples) < 3:
                        unverified_examples.append(p)

    print(f"\nscanned {scanned} entries")

    print("\n-- record SHAPE by seat (two schemas share one eventType) --")
    for (seat, shape), n in sorted(shapes.items()):
        print(f"  {seat:<12} {shape:<14} {n}")
    print(f"  distinct key-sets seen: {len(keysets)}")
    for ks, n in keysets.most_common():
        print(f"    n={n:<5} {','.join(ks)}")

    print("\n-- what `attempted` holds --")
    for (seat, shape, state), n in sorted(att_presence.items()):
        print(f"  {seat:<12} {shape:<14} {state:<15} {n}")
    for (seat, shape), v in sorted(act_len.items()):
        v = sorted(v)
        print(f"  len[{seat}/{shape}] n={len(v):<4} min={v[0]} median={v[len(v) // 2]} max={v[-1]}")

    print("\n-- the commitment field (`payload_sha256`) --")
    for (seat, state), n in sorted(sha_state.items()):
        print(f"  {seat:<12} {state:<30} {n}")
    tot = verified + unverified
    if tot:
        print(f"\n  re-derived from the row's OWN stored copy: {verified}/{tot} "
              f"({100.0 * verified / tot:.1f}%) of untruncated committed rows")
        print("  the remainder is the interesting half — the commitment binds the RAW input,")
        print("  while the record stores a whitespace-collapsed rendering, so a row whose copy")
        print("  is lossy cannot self-verify. That is exactly the row where an author-disclosed")
        print("  original needs something to be checked against.")
        for p in unverified_examples:
            print(f"    unverifiable: seat={p.get('plugin_id')} tool={p.get('tool_name')} "
                  f"{str(p.get('attempted'))[:90]!r}")
    else:
        print("  NO COMMITTED UNTRUNCATED ROWS IN WINDOW — this says the window is too small "
              "or the path did not fire, NOT that the field is unpopulated.")

    print("\n-- the PEER surface (`gate_escalation_opened`) --")
    print(f"  rows: {esc_rows}; carrying any sha/hash/digest field: {esc_with_commitment}")
    for ks, n in esc_keysets.most_common():
        print(f"    n={n:<5} {','.join(ks)}")
    if esc_rows and esc_with_commitment == 0:
        print("  => the reviewer is the only party in the loop with nothing to verify against.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
