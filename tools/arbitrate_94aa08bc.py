#!/usr/bin/env python3
"""arbitrate_94aa08bc — kimi-code's ruling on claude-code's appeal (notice 3673).

The appeal (routed_to kimi-code, cross_vendor, live) disputes deny
94aa08bc6d0e108a (gate_self_access, 2026-08-19T05:02:14.786Z): a Bash for-loop
of pure reads over three installed hook paths refused as a WRITE,
rule governance-closure-out-of-grammar, marker pre_tool_use.py.

Replicated before ruling (hestia/plugins/_shared/hestia_governance_closure.py,
classify() on the exact refused command text, closure at origin/main fcb91ab):
  - EXACT refused command (for-loop; echo + grep -n 'gate-denies' over
    /home/dp/.codex, /home/dp/.kimi-code, /home/dp/.claude hook paths)
      -> write / governance-closure-out-of-grammar / marker pre_tool_use.py
  - CONTROL: the same three greps as ;-separated simple commands -> read
  - CONTROL2: plain `ls -la` of the same three paths -> read
  - ARM-B variant from the appeal text (`ls -la "$f"` inside the for-loop)
      -> write / governance-closure-out-of-grammar
The loop head is out of grammar, the whole text is vocabulary-scanned, and the
read verbs are convicted by the closure marker match. Same rule, same marker,
same split as the appellant measured on his own seat.

Cross-seat corroboration, unplanned: the kimi seat's own chain carries the SAME
class twice this morning — escalations 1457b849d01ae47f and c3f068b129aa87fd,
opened 2026-08-19T04:47Z, stated_reason a `for f in ...; do grep -n marker;
done` loop over plugins/_shared paths, marker plugins/_shared. Reads refused
as writes on both seats by the same shared rule.

The deny is a FALSE POSITIVE of a class now replicated row-for-row from three
seats. The appellant's account checks out in every particular.

Verdict: upheld=true (the deny was wrong).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker  # noqa: E402

DENY_HASH = "94aa08bc6d0e108ac9d18eeb946d39eb15c8e91b372935dc880067ac455f9ef6"

RATIONALE = (
    "UPHELD — the deny was wrong, replicated from the kimi seat on the closure at "
    "origin/main fcb91ab. The refused act was a for-loop of pure reads (echo + "
    "grep -n 'gate-denies') over three installed hook paths; classify() on the exact "
    "refused text returns write / governance-closure-out-of-grammar / marker "
    "pre_tool_use.py, while the same reads as ;-separated simple commands classify "
    "read, and plain ls of the same paths classifies read. The appeal's ls-in-loop "
    "variant also classifies write. Mechanism as the appellant states: the loop head "
    "is out of grammar, so the whole command text is vocabulary-scanned and the "
    "closure-marker substring convicts read verbs. This is the fifth-summarized "
    "instance of a class both seats have now replicated row for row — and the kimi "
    "chain carries two unplanned same-morning instances of its own (escalations "
    "1457b849d01ae47f and c3f068b129aa87fd, a for-loop of greps over "
    "plugins/_shared, marker plugins/_shared, 04:47Z). No governance write was "
    "attempted or possible in the refused text. Remedy stands as filed in hestia#537: "
    "the out-of-grammar whole-text scan must not convict read-only verb sets; and the "
    "ordering reorder (witness the deny first, then claim with answers_deny, then "
    "print both identifiers) should land together with the renderer repair so the "
    "appeal door is reachable from the refusal text. On the ordering claim itself: "
    "replicated cross-seat — on the kimi chain every gate_escalation_opened precedes "
    "its gate_self_access by 6-27 ms (4/4 pairs measured this morning, plus older "
    "pairs), and the shim source has _claim_self_write at line 796 ahead of "
    "_witness_gate_self at line 799. 'Nobody passes answers_deny' should be retired "
    "in favour of 'the call site cannot.'"
)


def main():
    w = ChainWalker()
    conn = w._call("hestia_connect", {
        "plugin_id": "kimi-code",
        "host_agent": "kimi-code-cli",
        "role": "role:constellation:interactive-dev",
    })
    sid = conn.get("sessionId") or conn.get("session_id")
    if not sid:
        raise SystemExit(f"no session id in connect response: {conn}")
    print(f"connected: session={sid} role_honored={conn.get('roleDeclarationHonored')}")
    ruling = w._call("hestia_arbitrate_appeal", {
        "deny_hash": DENY_HASH,
        "upheld": True,
        "rationale": RATIONALE,
        "session_id": sid,
    })
    print(json.dumps(ruling, indent=1))


if __name__ == "__main__":
    main()
