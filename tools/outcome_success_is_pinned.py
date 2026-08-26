#!/usr/bin/env python3
"""`outcome.success` observes the TOOL-CALL ENVELOPE, not the act. It is pinned true.

WHAT THIS SETTLES
-----------------
The substrate under every "who recorded what" query in hestia #622/#625/#595/#540 --
the `outcome` event -- cannot represent failure at all, on any seat.

MEASURED, 3000-hop window 2026-08-26T01:11Z .. 07:27Z:
    2276 / 2276  outcome rows carry success=True AND error=None
                 (claude-code 1175, kimi-code 832, codex 269)
       0         outcome rows with success=False anywhere, any seat

DO NOT key a policy_decision census on `rule_id`. I did, and published a wrong
conclusion from it. `rule_id` is BLANK on every in-process gate row; the mrh/egress/
gate.degraded classes identify on `reason`. Keyed on `reason`, the same window gives
in-process gate rows kimi-code 29 / codex 5 / claude-code 0 -- so the gate-record hole
IS shim-local to claude-code, as notices 5520 and 5521 said. This tool therefore
reports the reason-keyed breakdown, not the rule_id one.

DELIBERATE FALSIFIER (chain pos 181930, 07:33:18Z): the command

    echo "MARKER-FAILPROBE-A"; grep zzzznotpresentzzzz /etc/hostname; echo "rc=$?"

exits rc=1 and is recorded `success: true, error: null`.

MECHANISM (witness.py:134 `derive_success`)
-------------------------------------------
    if not isinstance(tool_response, dict):        return True, None   # fail-open
    if tool_response.get("is_error") or ...:       return False, err
    return True, None

`is_error` is set by the HARNESS when a tool call is malformed or the tool itself
raised. A Bash command exiting nonzero is a perfectly successful tool call that
returns output plus an exit code, so `is_error` is unset and the act is logged as a
success. rc=1, rc=124 (timeout) and rc=127 (not found) are all indistinguishable
from rc=0 in the chain.

Denied acts are a separate hole with the same effect: the gate blocks at PreToolUse,
so PostToolUse never fires, so witness.py never runs and NO row of any type is
written. Verified: the scope deny at 07:27:20Z on a command containing "ls plugins/"
produced no row -- while a byte-similar `cd .../hestia && ls plugins/...` command from
the same seat five hours earlier ALLOWED and did produce one.

COMPOSES WITH THE SHIM-LOCAL HOLE
---------------------------------
On claude-code the in-process gate writes no policy_decision row AND the outcome store
cannot record failure, so a refused act on this seat is invisible from both directions
at once. On kimi and codex only the second half applies.

CONSEQUENCE
-----------
The outcome ledger partitions the world into {the harness broke} and {everything
else}, and the fleet has been reading the second bucket as "succeeded". Any success
rate, reputation fold, or T3/V3-style measure computed over `outcome.success` is
reading a constant. Absence of a failure in this store is not evidence of success --
it is the store's only possible content.

NOT CLAIMED: that the acts themselves are ungoverned. Denies ARE enforced (mine was).
The claim is strictly about what the record can represent.

Usage:  python3 tools/outcome_success_is_pinned.py [hops]
Exit 0 = pinned (defect present).  Exit 1 = a success=False row was found (refuted).
"""
import collections
import sys

sys.path.insert(0, "/mnt/c/exe/projects/ai-agents/private-context/hestia-local/probes")
from chainwalk import Chain, payload  # noqa: E402


def main() -> int:
    hops = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    c = Chain()

    seats = collections.Counter()
    failures = []
    gate_rows = collections.Counter()   # keyed on REASON, not rule_id -- see docstring
    newest = oldest = None
    n = 0

    for e in c.walk(max_hops=hops, progress=1000):
        n += 1
        if newest is None:
            newest = e["timestamp"]
        oldest = e["timestamp"]
        p = payload(e)

        if e["eventType"] == "outcome":
            seat = str(p.get("plugin_id"))
            ok = bool(p.get("success"))
            err = p.get("error") is not None
            seats[(seat, ok, err)] += 1
            if not ok or err:
                failures.append((e["timestamp"], seat, str(p.get("target"))[:110]))

        if e["eventType"] == "policy_decision":
            # In-process gate rows carry a BLANK rule_id and name their class in
            # `reason`. Keying on rule_id here reports a false fleetwide zero.
            reason = str(p.get("reason") or "")
            if not str(p.get("rule_id") or ""):
                gate_rows[(str(p.get("plugin_id")), reason.split()[0] if reason else "?")] += 1

    total = sum(seats.values())
    print(f"walked {n} hops; span {oldest} .. {newest}")
    print(f"\noutcome rows: {total}")
    for (seat, ok, err), v in sorted(seats.items(), key=lambda kv: -kv[1]):
        print(f"  {v:6d}  {seat:12s} success={ok}  has_error={err}")

    print(f"\noutcome rows recording ANY failure: {len(failures)}")
    for f in failures[:20]:
        print("  ", f)

    print("\nin-process gate rows (blank rule_id), by seat and reason class:")
    if not gate_rows:
        print("   none in window")
    for (seat, cls), v in sorted(gate_rows.items(), key=lambda kv: -kv[1]):
        print(f"  {v:5d}  {seat:12s} {cls}")
    silent = {s for s, _ in
              ((str(p), 0) for p in ("claude-code", "kimi-code", "codex"))} - {
        s for s, _ in gate_rows}
    print(f"  seats with ZERO in-process gate rows: {sorted(silent) or 'none'}")

    if failures:
        print("\nREFUTED: the store CAN represent failure; `success` is not pinned.")
        return 1
    print("\nCONFIRMED: no failure is representable in this window. `success` is a "
          "pinned constant and every rate derived from it is 100% by construction.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
