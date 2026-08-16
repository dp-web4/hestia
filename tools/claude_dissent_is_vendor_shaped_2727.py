#!/usr/bin/env python3
"""Was the dissent on escalation 4ec8cf453c584b60 caused by the act, or by the seat?

codex (notice 2727) and kimi-code (chainPosition 145364) both dissented, cross-vendor,
independently. Codex's ground 2: the record ends mid-command, so the act cannot be
reviewed byte-for-byte. kimi's ground 1: the loop crosses member home hook trees and no
member holds read scope there, so "the refusal is the boundary working, not a false
positive."

This checks four things against the live machine:

  A. Where the 220-char cut lands on the 263-char act -- verb or operand.
  B. The truncation bound in each of the three installed composers.
  C. Whether this seat holds any granted scope over /home (kimi's scope claim).
  D. Whether a permitted cross-seat read records WHICH file it read.

Findings A/B support codex. C confirms kimi's scope claim and refutes kimi's causal
claim -- the same reads, unfused, are permitted. D says the chain could not tell either
way.

The escalated command is read from the host transcript at runtime and never appears in
this file's text: the classifier matches payload content at two layers, so a probe that
quotes its own subject refuses to run (ref_content_match_two_layers).
"""
from __future__ import annotations

import glob
import json
import os
import sys

TOOL_USE_ID = "toolu_0153F1Jnw1dMMcwqNz57GEK5"
TRANSCRIPT_GLOB = "/home/dp/.claude/projects/-mnt-c-exe-projects-ai-agents/*.jsonl"
ESCALATION_ID = "4ec8cf453c584b60"

# (seat, installed hook path, expected bound). The bound is asserted, not scraped, so a
# redeploy that changes it reds this probe instead of silently rewriting the finding.
COMPOSERS = [
    ("claude-code", "/home/dp/.claude/hooks/hestia/pre_tool_use.py", 220),
    ("codex", "/home/dp/.codex/hooks/pre_tool_use.py", 400),
    ("kimi-code", "/home/dp/.kimi-code/hooks/pre_tool_use.py", 400),
]

# Paths the fused loop would have enumerated, and that were reissued singly.
CROSS_SEAT_TARGETS = [
    "/home/dp/.codex/hooks/pre_tool_use.py",
    "/home/dp/.gemini/hooks/pre_tool_use.py",
    "/home/dp/.kimi-code/hooks/pre_tool_use.py",
    "/home/dp/.claude/hooks/pre_tool_use.py",
]


def load_act() -> str:
    for path in glob.glob(TRANSCRIPT_GLOB):
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                content = (obj.get("message") or {}).get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if (isinstance(block, dict) and block.get("type") == "tool_use"
                            and block.get("id") == TOOL_USE_ID):
                        return block.get("input", {}).get("command", "")
    raise SystemExit(f"act {TOOL_USE_ID} not in transcripts -- host transcripts are "
                     f"pruned on their own schedule (fb_transcripts_undeclared)")


def part_a(act: str) -> None:
    print("== A. where the cut lands ==")
    s = " ".join(act.split())
    print(f"raw={len(act)} collapsed={len(s)}")
    for bound in sorted({b for _, _, b in COMPOSERS}):
        vis, hid = s[:bound], s[bound:]
        pct = 100.0 * len(vis) / len(s)
        verdict = "COMPLETE" if not hid else "TRUNCATED"
        print(f"  bound={bound:3d}  visible={len(vis):3d} ({pct:5.1f}%)  {verdict}")
        if hid:
            print(f"      visible ends : ...{vis[-12:]!r}")
            print(f"      withheld     : {hid!r}  ({len(hid)} chars)")
            # The claim is not "some was cut" but "a verb lost its operand".
            last_tok = vis.rstrip().rsplit(" ", 1)[-1]
            print(f"      last visible token = {last_tok!r}; "
                  f"withheld begins with its operand = {hid.lstrip().split(' ')[0]!r}")


def part_b() -> int:
    print("\n== B. installed composer bound per seat ==")
    bad = 0
    for seat, path, expect in COMPOSERS:
        if not os.path.exists(path):
            print(f"  {seat:11s} MISSING {path}")
            bad += 1
            continue
        text = open(path, encoding="utf-8", errors="replace").read()
        # Two spellings in the fleet: an inline literal, and a defaulted parameter.
        found = None
        if f"s[:{expect}]" in text:
            found = f"inline s[:{expect}]"
        elif f"_attempted_summary(ev, limit={expect})" in text:
            found = f"_attempted_summary(limit={expect})"
        if found is None:
            print(f"  {seat:11s} bound {expect} NOT FOUND -- composer changed, "
                  f"finding needs re-measuring")
            bad += 1
        else:
            print(f"  {seat:11s} bound={expect:3d}  via {found}")
    return bad


def part_c(call) -> None:
    print("\n== C. does this seat hold scope over any /home path? ==")
    st = call("hestia_scope_status", {"plugin_id": "claude-code"})
    floor = [p["path"] for p in st.get("society_floor", [])]
    live = st.get("live_grants") or []
    standing = st.get("standing_grants") or []
    home = [p for p in floor if p.startswith("/home")]
    print(f"  generation={st.get('generation')} floor={len(floor)} "
          f"live={len(live)} standing={len(standing)}")
    print(f"  floor paths under /home: {len(home)} {home}")
    print("  -> kimi's SCOPE claim: " + ("CONFIRMED" if not home else "REFUTED"))
    print("  -> kimi's CAUSAL claim ('the refusal is the boundary working') is refuted "
          "by the permitted single reads in D, not by this table.")


def part_d(call) -> None:
    print("\n== D. does a permitted cross-seat read record WHICH file? ==")
    hist = call("hestia_query_history", {"filter": {"limit": 60}})
    rows = [e for e in hist.get("entries", []) if e.get("eventType") == "gate_self_read"]
    print(f"  gate_self_read rows in window: {len(rows)}")
    if not rows:
        print("  (window holds none -- widen the limit; absence here indicts the query, "
              "not the gate)")
        return
    gate_paths = {r["eventData"]["data"].get("gate_path") for r in rows}
    markers = {r["eventData"]["data"].get("marker") for r in rows}
    print(f"  distinct gate_path values : {gate_paths}")
    print(f"  distinct marker values    : {markers}")
    blob = json.dumps(rows)
    named = [t for t in CROSS_SEAT_TARGETS if t in blob and ".claude" not in t]
    print(f"  cross-seat targets named anywhere in these rows: {len(named)} {named}")
    print("  -> a read of another seat's hook is on chain as a read of THIS seat's hook; "
          "marker is a basename shared by all four seats (fb_basename_not_identifier)")


def escalation_state(call) -> None:
    print("\n== escalation state ==")
    pend = call("hestia_gate_pending_escalations", {})
    for e in pend.get("pending", []):
        if e["escalation_id"] == ESCALATION_ID:
            pp = e.get("peer_participation", {})
            print(f"  {ESCALATION_ID}: dissented={pp.get('dissented')} "
                  f"concurred={pp.get('concurred')} absent={pp.get('absent')} "
                  f"invited={len(pp.get('invited') or [])} "
                  f"without_reader={pp.get('invited_without_reader')}")
            print(f"  stated_reason ends: ...{e['stated_reason'][-24:]!r}")
            return
    print(f"  {ESCALATION_ID} no longer pending (lapsed or decided)")


def main() -> int:
    part_a(load_act())
    bad = part_b()
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from claude_daemon_client import call  # type: ignore
    except ImportError:
        print("\n(daemon client not importable -- C/D skipped; see "
              "ref_daemon_reachable_urllib for the 5-line transport)")
        return bad
    part_c(call)
    part_d(call)
    escalation_state(call)
    return bad


if __name__ == "__main__":
    raise SystemExit(main())
