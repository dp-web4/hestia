#!/usr/bin/env python3
"""Is the one cryptographic field on the peer-facing deny record load-bearing for scoring,
and who computes it?

CODE FACTS this probe measures the consequences of (grep-able, not line-pinned):

  1. `tool_witness_decision` (core/src/server/handler.rs) obtains the field with
     `optional_string(args, "payload_sha256")` and writes it straight into the chain.
     `payload_sha256` occurs exactly TWICE in that file — the read and the write. There is
     no third occurrence, and no `sha256_hex` call anywhere in handler.rs. So the daemon
     never computes, recomputes, or compares it: on the plugin-gate shape the commitment is
     ASSERTED BY THE PARTY BEING RECORDED.

  2. `derivation.rs` builds `deny_sig` from (session_id, tool_name, payload_sha256, target)
     and matches a later policy_decision as `retried` when session+tool match AND
     (digest matches, OR target matches). `retried` scores **0.0**; the comply fallthrough
     scores **0.85**. Evading that join is the largest single swing in the ladder.

  3. The daemon's OWN gate site emits the daemon-preset shape with `full_command` in scope
     (it is the value handed to `redact_secrets` for `attempted`) but writes NO digest.

Put together: the shape that HAS the commitment cannot verify it, and the shape that CAN
compute it does not carry it. This probe asks how often (1)+(2) actually bite — i.e. how
often the self-asserted digest is the SOLE join key, with no `target` to fall back on.

A row is SOLE-KEY if payload_sha256 is non-empty and target is empty/absent: there, the
only thing that can make a re-run countable as a retry is a value the re-runner supplied.

Reads only. No governed surface written. Run: python3 tools/claude_commitment_is_self_asserted_probe.py [--max N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chain_walk import ChainWalker, payload  # noqa: E402

TRUNC_MARK = "…[truncated]"
REDACT_HINTS = ("[REDACTED", "***")


def commitment_of(attempted: str) -> str:
    """The preimage established by `claude_attempted_is_the_act_probe.py` (158/188 on
    untruncated rows): a JSON object wrapping the command, hex TRUNCATED TO 16 chars.
    Do not "simplify" this to sha256(raw) — that spelling scores 0/190 and reads as a
    refutation of the sender rather than as a wrong guess about the preimage."""
    return hashlib.sha256(json.dumps({"command": attempted}).encode()).hexdigest()[:16]


def _shape(p: dict) -> str:
    """Same two-shape split kimi's exact-key-set classifier established; a row that is
    neither is reported rather than folded, so 'no third shape' stays falsifiable here too."""
    keys = p.keys()
    if "payload_sha256" in keys and "rule_name" not in keys:
        return "plugin-gate"
    if "rule_name" in keys and "action_id" in keys:
        return "daemon-preset"
    return "UNSEEN-SHAPE"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=20000)
    args = ap.parse_args()

    shapes: Counter = Counter()
    # per-seat tallies over plugin-gate DENY/WARN rows
    have_digest: Counter = Counter()
    no_digest: Counter = Counter()
    sole_key: Counter = Counter()          # digest present, target absent -> digest is the only join key
    target_backstop: Counter = Counter()   # digest present AND target present -> join survives a bad digest
    # recompute check, restricted to rows whose stored `attempted` shows no lossy marker
    recompute_ok: Counter = Counter()
    recompute_bad: Counter = Counter()
    recompute_skipped_lossy: Counter = Counter()
    # daemon-preset rows: how many HAVE the raw-command surrogate but no digest
    preset_with_attempted: Counter = Counter()
    # THE JOIN CENSUS. `retried` fires only when (digest present AND matches) OR
    # (target present AND matches). A row with NEITHER is UNJOINABLE: no later act can
    # ever be scored 0.0 against it, so it necessarily falls through to the comply band.
    # Counted over BOTH shapes and every seat, because that is the population the
    # temperament ladder actually scores.
    joinable: Counter = Counter()    # (seat, shape) -> rows with digest or target
    unjoinable: Counter = Counter()  # (seat, shape) -> rows with neither

    scanned = 0
    for e in ChainWalker().walk(max_entries=args.max):
        scanned += 1
        if e.get("eventType") != "policy_decision":
            continue
        p = payload(e)
        seat = p.get("plugin_id") or "(unrecorded)"
        shape = _shape(p)
        shapes[shape] += 1

        digest = (p.get("payload_sha256") or "").strip()
        target = (p.get("target") or "").strip()
        attempted = p.get("attempted") or ""

        if shape in ("daemon-preset", "plugin-gate"):
            if digest or target:
                joinable[(seat, shape)] += 1
            else:
                unjoinable[(seat, shape)] += 1

        if shape == "daemon-preset":
            if attempted:
                preset_with_attempted[seat] += 1
            continue
        if shape != "plugin-gate":
            continue

        if not digest:
            no_digest[seat] += 1
            continue
        have_digest[seat] += 1
        if target:
            target_backstop[seat] += 1
        else:
            sole_key[seat] += 1

        lossy = TRUNC_MARK in attempted or any(h in attempted for h in REDACT_HINTS)
        if not attempted or lossy:
            recompute_skipped_lossy[seat] += 1
        elif commitment_of(attempted) == digest:
            recompute_ok[seat] += 1
        else:
            recompute_bad[seat] += 1

    print(f"scanned {scanned} entries")
    print("\npolicy_decision rows by shape: " + ", ".join(f"{k}={v}" for k, v in shapes.most_common()))

    print("\n-- plugin-gate rows: who supplies the commitment, and is it load-bearing? --")
    print(f"  {'seat':<14} {'digest':>7} {'no-dig':>7} {'SOLE-KEY':>9} {'target-backstop':>16}")
    for seat in sorted(set(have_digest) | set(no_digest)):
        print(f"  {seat:<14} {have_digest[seat]:>7} {no_digest[seat]:>7} "
              f"{sole_key[seat]:>9} {target_backstop[seat]:>16}")

    print("\n-- can an auditor CHECK the self-asserted digest after the fact? --")
    print(f"  {'seat':<14} {'recompute-ok':>13} {'MISMATCH':>9} {'skipped(lossy)':>15}")
    for seat in sorted(set(recompute_ok) | set(recompute_bad) | set(recompute_skipped_lossy)):
        print(f"  {seat:<14} {recompute_ok[seat]:>13} {recompute_bad[seat]:>9} "
              f"{recompute_skipped_lossy[seat]:>15}")
    tot_ok, tot_bad = sum(recompute_ok.values()), sum(recompute_bad.values())
    tot_skip = sum(recompute_skipped_lossy.values())
    denom = tot_ok + tot_bad + tot_skip
    if denom:
        print(f"  checkable at read time: {tot_ok + tot_bad}/{denom} "
              f"({100.0 * (tot_ok + tot_bad) / denom:.1f}%) — the rest are lossy stored copies, "
              f"where a wrong digest is INDISTINGUISHABLE from an honest one.")

    print("\n-- CAN THE RETRY JOIN FIRE AT ALL? (digest or target present) --")
    print(f"  {'seat':<14} {'shape':<14} {'joinable':>9} {'UNJOINABLE':>11} {'unjoinable %':>13}")
    for k in sorted(set(joinable) | set(unjoinable)):
        seat, shape = k
        j, u = joinable[k], unjoinable[k]
        pct = f"{100.0 * u / (j + u):.1f}%" if (j + u) else "n/a"
        print(f"  {seat:<14} {shape:<14} {j:>9} {u:>11} {pct:>13}")
    tj, tu = sum(joinable.values()), sum(unjoinable.values())
    print(f"  {'ALL':<14} {'':<14} {tj:>9} {tu:>11} "
          f"{(f'{100.0 * tu / (tj + tu):.1f}%' if tj + tu else 'n/a'):>13}")
    print("  An UNJOINABLE deny can never be matched by `retried` (0.0). It falls through to "
          "the comply band (0.85) no matter what the member does next.")

    print("\n-- daemon-preset rows: the shape that could compute it and doesn't --")
    for seat, n in sorted(preset_with_attempted.items()):
        print(f"  {seat:<14} {n} rows carry a scrubbed `attempted` but NO digest "
              f"(the raw string was in daemon scope when the row was built)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
