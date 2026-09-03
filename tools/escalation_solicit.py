#!/usr/bin/env python3
"""Route a ruling request to whoever the law says may rule, or say why nobody was asked.

dp, 2026-09-03: peers by default for single-approver markers, the operator for two-factor ones.

WHY. Every governance write this seat needs was queueing behind one human, which is the
delivery problem's twin: not who MAY rule, but who was ASKED. The refusal text names the peer
route (`hestia gate approve <id> --as <peer-seat>`) and `bar_for` says which markers a peer
alone may close. This changes who gets asked. It is a request router and never a second
authority table: it grants nothing, and the daemon refuses anything it gets wrong.

THREE ANSWERS, NOT TWO. `ask these peers`, `ask nobody, here is why`, and INDETERMINATE, which
is the one that matters. Every place this tool cannot establish a fact, it stops:

  - the bar must be EXPLICITLY `single_approver`. A missing or unrecognised bar used to fall
    through to the peer branch, which made ABSENCE into peer authority. That is the inversion
    this whole codebase keeps catching in other instruments (GPT review of #866).
  - `expired` and `unknown` are not evidence of a lapse. #867 measured that a reaped row polls
    as synthetic `expired` whether it was ruled or never ruled, and whether that ruling was
    approve or DENY. Recommending a fresh petition there would re-open a denied question by
    another door, which is precisely the shopping this tool exists to refuse. Without canonical
    chain evidence the answer is INDETERMINATE, and the missing surface is named rather than
    guessed around: a resolver that distinguishes ruled-and-evicted from lapsed-undecided.
    `HESTIA_RULING_RESOLVER` may supply one (a command taking an escalation id and printing
    exactly `approved`, `denied` or `undecided`). Its answer is passed IN, validated, and never
    read from the ambient environment: an env var consulted inside the verdict would mean any
    caller could export `undecided` and reopen a reaped deny without evidence, which is the
    shopping this tool exists to refuse, reached by setting a variable. Anything the resolver
    prints other than those three words is discarded as unresolved.
  - the peer roster comes from the roster substrate (`HESTIA_PEERS`, else the workspace's
    agent registry). A baked list is one seat's view of the fleet wearing a general name, and
    it silently excluded claude-code from ever being a peer. No roster means no solicitation.

GUARDRAILS THAT SURVIVE ALL OF THAT: never after a deny (a deny is a ruling, not a slot to
refill; appeal is the route), never the asker itself, and a POINTER rather than an argument,
because a solicitation that argued its case would be lobbying with extra steps.

EXIT: 0 asked or deliberately asked nobody; 2 INDETERMINATE.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

ASK, NOBODY, INDETERMINATE = "ask", "nobody", "indeterminate"
SINGLE_APPROVER = "single_approver"


def resolve_peers(me: str, workspace: str | None) -> tuple[list[str], str]:
    """The eligible peer seats, from the roster substrate. ([], reason) when it cannot be read."""
    named = [p.strip() for p in (os.environ.get("HESTIA_PEERS") or "").split(",") if p.strip()]
    if named:
        return [p for p in named if p.lower() != me.lower()], "HESTIA_PEERS"
    registry = os.path.join(workspace or "", "agent-atlas", "talk-to")
    if workspace and os.path.isdir(registry):
        try:
            seats = sorted(
                d for d in os.listdir(registry)
                if os.path.isdir(os.path.join(registry, d)) and not d.startswith(".")
            )
            return [s for s in seats if s.lower() != me.lower()], f"registry {registry}"
        except OSError as e:
            return [], f"registry unreadable ({e})"
    return [], ("no roster: set HESTIA_PEERS, or point --workspace at a readable agent registry. "
                "A baked list would be one seat's view of the fleet wearing a general name")


RULINGS = ("approved", "denied", "undecided")


def solicitation_verdict(row: dict, peers: list[str], me: str = "claude-code",
                         prior_ruling: str | None = None):
    """(state, recipients, reason). Pure, so the judgement is testable without a daemon.

    `prior_ruling` is canonical evidence about a reaped row, supplied by the caller and
    validated here. It is a parameter and not an environment lookup on purpose: ambient state
    that unlocks an ask is a deny anyone can reopen by exporting a word."""
    if prior_ruling is not None and prior_ruling not in RULINGS:
        prior_ruling = None
    status = (row.get("status") or "").lower()
    bar = (row.get("bar") or "").lower()

    if status == "denied":
        return NOBODY, [], ("denied: a deny is a ruling, not a slot to refill. Asking anyone "
                            "again is shopping for a different answer; appeal the rule instead")
    if status == "approved":
        return NOBODY, [], ("approved already: re-issue the same act to claim it. The binding is "
                            "a digest over a bounded summary, not the bytes (#539), so state what "
                            "you stated before")
    if row.get("consumed_at"):
        return NOBODY, [], "already spent: nothing left to authorise"
    if status in ("expired", "unknown", ""):
        ruling = (prior_ruling or "").lower()
        if ruling == "denied":
            return NOBODY, [], "reaped, and the canonical ruling was DENY: appeal, never re-ask"
        if ruling == "approved":
            return NOBODY, [], "reaped after an approval: the grant's horizon governs, not a new ask"
        if ruling == "undecided":
            return (ASK, peers, "reaped while genuinely undecided: a fresh petition is honest") \
                if peers else (INDETERMINATE, [], "undecided, but no roster to ask")
        return INDETERMINATE, [], (
            f"status {status or 'absent'!r} does not distinguish ruled-and-evicted from "
            "lapsed-undecided: a reaped row polls as synthetic expired whichever it was (#867). "
            "Resolve the canonical ruling on the chain first; if it was a deny, appeal is the "
            "route. Set HESTIA_RULING_RESOLVER to supply that answer")
    if status != "pending":
        return INDETERMINATE, [], f"status {status!r} is not a state this tool knows how to route"
    if bar != SINGLE_APPROVER:
        return INDETERMINATE, [], (
            f"bar {bar or 'absent'!r} is not explicitly {SINGLE_APPROVER}: a peer may not close it, "
            "and an absent bar is not evidence that one may. Peers can still corroborate; the "
            "operator is the route")
    asker = (row.get("plugin_id") or me).lower()
    eligible = [p for p in peers if p.lower() != asker]
    if not eligible:
        return INDETERMINATE, [], "bar admits a peer, but the roster yielded none to ask"
    return ASK, eligible, f"bar {bar} admits a peer"


def poll(escalation_id: str) -> dict:
    out = subprocess.run(["hestia", "gate", "poll", escalation_id],
                         capture_output=True, text=True, timeout=120).stdout
    start = out.find("{")
    if start < 0:
        raise SystemExit(f"no poll payload for {escalation_id}")
    return json.loads(out[start:])


def resolve_prior_ruling(escalation_id: str) -> str | None:
    """Ask the configured resolver what the chain says. Returns one of RULINGS, or None.

    The answer is RETURNED, never stashed in the environment, and anything outside the three
    accepted words is None. A resolver that errors, times out, or answers something else leaves
    the question unresolved, which keeps the escalation INDETERMINATE rather than askable."""
    cmd = os.environ.get("HESTIA_RULING_RESOLVER")
    if not cmd:
        return None
    try:
        r = subprocess.run([cmd, escalation_id], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return None
        answer = (r.stdout or "").strip().splitlines()[-1].strip().lower()
        return answer if answer in RULINGS else None
    except Exception:
        return None


def mesh_cli(me: str) -> str | None:
    for cand in (os.environ.get("HESTIA_MESH_CLI"),
                 os.path.expanduser(f"~/.{me}/hooks/member-mesh/hestia-mesh.py"),
                 os.path.expanduser("~/.hestia/member-mesh/hestia-mesh.py")):
        if cand and os.path.isfile(cand):
            return cand
    return None


def send(cli: str, to: str, pointer: str, me: str) -> str:
    env = dict(os.environ, HESTIA_MESH_PLUGIN=me,
               HESTIA_ROLE=os.environ.get("HESTIA_ROLE", "role:constellation:member"))
    r = subprocess.run([sys.executable, cli, "send", to, "review_request", pointer],
                       capture_output=True, text=True, timeout=180, env=env)
    for key in ('"recipient_liveness": "', '"error": "'):
        if key in r.stdout:
            return r.stdout.split(key, 1)[1].split('"', 1)[0]
    return "sent" if r.returncode == 0 else f"rc={r.returncode}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("escalation_id")
    ap.add_argument("--me", default=os.environ.get("HESTIA_PLUGIN_ID", "claude-code"))
    ap.add_argument("--workspace", default=os.environ.get("HESTIA_WORKSPACE"))
    ap.add_argument("--dry-run", action="store_true", help="say who would be asked, ask nobody")
    args = ap.parse_args()

    row = poll(args.escalation_id)
    prior = resolve_prior_ruling(args.escalation_id)
    peers, roster_note = resolve_peers(args.me, args.workspace)
    state, recipients, reason = solicitation_verdict(row, peers, args.me, prior)

    print(f"escalation {args.escalation_id}: status={row.get('status')} bar={row.get('bar')}")
    print(f"  roster: {roster_note}")
    print(f"  prior ruling: {prior or 'unresolved (no resolver, or an answer outside approved/denied/undecided)'}")
    print(f"  {state.upper()}: {reason}")
    if state != ASK:
        return 2 if state == INDETERMINATE else 0

    cli = mesh_cli(args.me)
    if cli is None:
        print("  INDETERMINATE: no mesh client found; set HESTIA_MESH_CLI")
        return 2
    pointer = f"hestia://escalation/{args.escalation_id}#decide"
    for p in recipients:
        print(f"  would ask {p}" if args.dry_run else f"  asked {p}: {send(cli, p, pointer, args.me)}")
    print("  a peer may rule or refuse; either is an answer, and neither is asked twice")
    return 0


if __name__ == "__main__":
    sys.exit(main())
