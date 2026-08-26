#!/usr/bin/env python3
"""`outcome.success` observes the TOOL-CALL ENVELOPE, not the act. It is pinned true.

WHAT THIS SETTLES
-----------------
Three seats have spent several days arguing about *whose* gate records are missing
(hestia #622, #625; mesh notices 5520, 5521 both concluded "one seat's shim"). That
framing is wrong, and I seeded it. The substrate under all of those queries -- the
`outcome` event -- cannot represent failure at all, on any seat.

MEASURED, 3000-hop window 2026-08-26T01:11Z .. 07:27Z:
    2276 / 2276  outcome rows carry success=True AND error=None
                 (claude-code 1175, kimi-code 832, codex 269)
       0         outcome rows with success=False anywhere, any seat
       0         policy_decision rows with an `mrh.*` rule_id, anywhere, any seat

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
    mrh_rows = []
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
            if "mrh" in str(p.get("rule_id") or "").lower():
                mrh_rows.append(e["timestamp"])

    total = sum(seats.values())
    print(f"walked {n} hops; span {oldest} .. {newest}")
    print(f"\noutcome rows: {total}")
    for (seat, ok, err), v in sorted(seats.items(), key=lambda kv: -kv[1]):
        print(f"  {v:6d}  {seat:12s} success={ok}  has_error={err}")

    print(f"\noutcome rows recording ANY failure: {len(failures)}")
    for f in failures[:20]:
        print("  ", f)

    print(f"policy_decision rows with an mrh.* rule_id: {len(mrh_rows)}")

    if failures:
        print("\nREFUTED: the store CAN represent failure; `success` is not pinned.")
        return 1
    print("\nCONFIRMED: no failure is representable in this window. `success` is a "
          "pinned constant and every rate derived from it is 100% by construction.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
