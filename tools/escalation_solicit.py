#!/usr/bin/env python3
"""Ask a PEER to rule on an escalation this seat opened, when the law says a peer may.

dp, 2026-09-03, on the operator being the only route: "makes sense" to solicit peers by
default for single-approver markers and keep the operator for two-factor ones.

WHY THIS EXISTS. Every governance write this seat needs was queueing behind one human, and
the queue is the delivery problem's twin: not "who may rule" but "who was asked". The refusal
text now names the peer route explicitly (`hestia gate approve <id> --as <peer-seat>`), and
`bar_for` already says which acts a peer alone may close. Nothing here changes who may rule.
It changes who gets asked, and it records the asking.

THE GUARDRAILS ARE THE POINT, because soliciting your own approver is one short step from
shopping for one:

  1. ONLY a pending escalation. A decided one has an answer; asking again is asking a second
     time for a different one.
  2. NEVER after a deny. A deny is a ruling. Re-soliciting after it, from anyone, is the
     shopping move this tool must not make easy, so it refuses by name rather than by
     omission.
  3. ONLY where the bar admits a peer. `sovereign_plus_peer` needs the sovereign conjunct
     (`bar_met_over`), so peers are invited to participate there but cannot close it: for
     those, this tool says so and asks nobody, rather than generating traffic that changes
     nothing.
  4. The request carries a POINTER, not an argument. The peer reads the act and rules; a
     solicitation that argued its own case would be lobbying with extra steps.
  5. The asker is never a recipient. Self-approval is refused by the daemon anyway; asking
     is still recorded conduct, and this must not put a request for it on the record.

The verdict is a pure function of the poll row, so it is testable without a daemon, and the
network half is a thin shell around it.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

PEERS = ("codex", "kimi-code", "gemini-cli")
MESH = os.path.expanduser("~/.claude/hooks/member-mesh/hestia-mesh.py")


def solicitation_verdict(row: dict, me: str = "claude-code"):
    """(peers_to_ask, reason). An empty list is a decision, and the reason says which one."""
    status = (row.get("status") or "").lower()
    bar = (row.get("bar") or "").lower()
    if status == "denied":
        return [], ("denied: a deny is a ruling, not a slot to refill. Re-asking anyone after "
                    "it is shopping for a different answer; appeal the rule instead")
    if status == "approved":
        return [], "approved already: re-issue the write byte-identically to claim it"
    if status in ("expired", "unknown"):
        return [], f"{status}: nothing to rule on; open a fresh petition if the act still stands"
    if row.get("consumed_at"):
        return [], "already spent: nothing left to authorise"
    if status != "pending":
        return [], f"status {status!r} is not pending; asking would be noise"
    if bar and bar != "single_approver":
        return [], (f"bar {bar!r} needs the sovereign conjunct, so a peer cannot close it. "
                    "Peers may still corroborate, and the operator is the route")
    asker = (row.get("plugin_id") or me).lower()
    return [p for p in PEERS if p.lower() != asker], f"bar {bar or 'single_approver'} admits a peer"


def poll(escalation_id: str) -> dict:
    out = subprocess.run(["hestia", "gate", "poll", escalation_id],
                         capture_output=True, text=True, timeout=120).stdout
    start = out.find("{")
    if start < 0:
        raise SystemExit(f"no poll payload for {escalation_id}")
    return json.loads(out[start:])


def send(to: str, pointer: str, me: str) -> str:
    env = dict(os.environ, HESTIA_MESH_PLUGIN=me,
               HESTIA_ROLE=os.environ.get("HESTIA_ROLE", "role:constellation:member"))
    r = subprocess.run([sys.executable, MESH, "send", to, "review_request", pointer],
                       capture_output=True, text=True, timeout=180, env=env)
    for key in ('"recipient_liveness": "', '"error": "'):
        if key in r.stdout:
            return r.stdout.split(key, 1)[1].split('"', 1)[0]
    return "sent" if r.returncode == 0 else f"rc={r.returncode}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("escalation_id")
    ap.add_argument("--me", default=os.environ.get("HESTIA_PLUGIN_ID", "claude-code"))
    ap.add_argument("--dry-run", action="store_true", help="say who would be asked, ask nobody")
    args = ap.parse_args()
    row = poll(args.escalation_id)
    peers, reason = solicitation_verdict(row, args.me)
    print(f"escalation {args.escalation_id}: status={row.get('status')} bar={row.get('bar')}")
    print(f"  {reason}")
    if not peers:
        return 0
    pointer = f"hestia://escalation/{args.escalation_id}#decide"
    for p in peers:
        if args.dry_run:
            print(f"  would ask {p}")
            continue
        print(f"  asked {p}: {send(p, pointer, args.me)}")
    print("  a peer may rule or refuse; either is an answer, and neither is asked twice")
    return 0


if __name__ == "__main__":
    sys.exit(main())
