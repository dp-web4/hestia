#!/usr/bin/env python3
"""A subagent's ruling reaches the subagent, and its parent cannot consume it first.

dp, 2026-10-06: "we're supposed to have a mechanism that notifies the requestor of disposition,
without me doing it manually." That night escalation c96eb3d5 was opened by a SUBAGENT; dp approved
it and had to tell the parent session in chat so it could relay the ruling before the claim window
burned.

WHAT A SUBAGENT'S HOOK EVENT IS (measured, Claude Code 2.1.290, 2026-10-06, a hook that dumped its
raw stdin): a subagent's PreToolUse/PostToolUse carry the PARENT's `session_id` and
`transcript_path`, plus `agent_id` and `agent_type`; the parent's own events carry neither of the
last two. additionalContext returned on the subagent's PreToolUse reached the subagent and not the
parent. UserPromptSubmit fired only for the parent's prompt. The claude-code gate's adapter
(`pre_tool_use.to_event`) keeps `session_id` and drops `agent_id` (it survives only in `ev.raw`), and
that `session_id` is the `host_session_id` the daemon copies onto the escalation and writes as the
lane row's `for_session`. So the daemon addresses a subagent's escalation to its parent's session.

THE DEFECT THIS PINS. The reader kept one cursor per session_id: whichever of parent and subagent
fired first rendered the row and advanced the shared cursor, and the other never saw it. The parent
keeps making calls while a background subagent runs, so it is usually first. Measured against an
isolated daemon (real `hestia_gate_escalation_open` + a real CLI ruling, 2026-10-06): parent
rendered=True, subagent rendered=False -- #851's destruction, between two agents of one session.

THE ARMS. Today's daemon rows (no `for_agent` key): each agent of the session sees the row once, on
its own cursor, framed as session-addressed; neither consumes the other's. Rows carrying `for_agent`
(the proposed daemon slice: record the asker's agent id at open): only the named agent sees it.

Run: python3 tools/disposition_subagent_delivery_test.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
READER = REPO / "plugins" / "claude-code" / "hooks" / "disposition_deliver.py"
GATE = REPO / "plugins" / "claude-code" / "hooks" / "pre_tool_use.py"
PARENT = "9434487f-4f91-41a2-9a51-4531efe6dd22"     # the shape measured in the hook dump
AGENT = "a9a1a214082bf2737"
SIBLING = "a0000000000000001"
FRAME = "not to one agent of it"


def subagent_event(tool="Edit", path="/x/plugins/_shared/hestia_gate_core.py", agent=AGENT) -> dict:
    """A subagent's PreToolUse as Claude Code 2.1.290 delivers it (the measured key set)."""
    return {"session_id": PARENT, "transcript_path": f"/h/.claude/projects/p/{PARENT}.jsonl",
            "cwd": "/w", "permission_mode": "bypassPermissions", "prompt_id": "p-1",
            "agent_id": agent, "agent_type": "general-purpose", "hook_event_name": "PreToolUse",
            "tool_name": tool, "tool_input": {"file_path": path}, "tool_use_id": "toolu_1"}


def parent_event(tool="Read") -> dict:
    ev = subagent_event(tool=tool, path="/tmp/x")
    del ev["agent_id"], ev["agent_type"]
    return ev


def host_session_id_the_gate_sends(event: dict) -> str:
    """What the real claude-code gate adapter hands the daemon as host_session_id."""
    sys.path.insert(0, str(REPO / "plugins" / "_shared"))
    import hestia_single_gate as gate
    spec = importlib.util.spec_from_file_location("cc_pre_tool_use", GATE)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod.to_event(gate, event).session_id


def lane_row(esc: str, for_session, render: str, **extra) -> str:
    """One lane line in the shape `ensure_disposition_lane` (handler.rs) writes."""
    row = {"v": 1, "written_at": 1791270000, "escalation_id": esc, "plugin_id": "claude-code",
           "for_session": for_session, "decision": "approved", "decided_at": 1791269990,
           "decided_by": "operator", "ruling_hash": "ab" * 32, "pointer": "p", "claimable": True,
           "consumed_at": None, "pre_migration_horizon": 1791270590,
           "pre_migration_horizon_basis": "decided_at", "act_digest": "cd" * 32,
           "render": render}
    row.update(extra)
    return json.dumps(row) + "\n"


class Seat:
    def __init__(self, raw: str):
        self.home = Path(raw) / "hestia"
        self.state = Path(raw) / "seat"
        (self.home / "dispositions").mkdir(parents=True)
        self.lane = self.home / "dispositions" / "claude-code.jsonl"

    def append(self, text: str) -> None:
        with open(self.lane, "a", encoding="utf-8") as fh:
            fh.write(text)

    def fire(self, event: dict) -> str:
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.home.parent), "LANG": "C.UTF-8",
               "HESTIA_HOME": str(self.home), "HESTIA_SEAT_STATE": str(self.state)}
        r = subprocess.run([sys.executable, str(READER)], input=json.dumps(event), capture_output=True,
                           text=True, env=env, timeout=20)
        assert r.returncode == 0, r.stderr
        out = r.stdout.strip()
        if not out:
            return ""
        doc = json.loads(out)
        assert doc["hookSpecificOutput"]["hookEventName"] == event["hook_event_name"], doc
        return doc["hookSpecificOutput"]["additionalContext"]


def test_the_gate_addresses_a_subagents_escalation_to_the_parents_session():
    """The premise, read from the real adapter: the address cannot tell parent from subagent."""
    assert host_session_id_the_gate_sends(subagent_event()) == PARENT
    assert host_session_id_the_gate_sends(parent_event("Edit")) == PARENT


def test_todays_row_reaches_the_subagent_even_when_the_parent_fires_first():
    """c96eb3d5's sequence on today's daemon: the row names the session only. The parent's next
    call must not eat it; the subagent's next call must render it; each sees it once."""
    with tempfile.TemporaryDirectory() as d:
        seat = Seat(d)
        addr = host_session_id_the_gate_sends(subagent_event())
        assert seat.fire(subagent_event(tool="Read", path="/tmp/y")) == "", "nothing ruled yet"
        seat.append(lane_row("c96eb3d5aaaa0001", addr,
                             "APPROVED - escalation c96eb3d5aaaa0001. RE-ISSUE THE SAME WRITE to claim it."))
        p1 = seat.fire(parent_event())
        assert "c96eb3d5aaaa0001" in p1, "the address names the parent's session, so it is shown it"
        s1 = seat.fire(subagent_event(tool="Read", path="/tmp/y"))
        assert "c96eb3d5aaaa0001" in s1, "the PARENT consumed the subagent's ruling (one cursor per session_id)"
        assert "RE-ISSUE THE SAME WRITE" in s1, s1
        assert FRAME in p1 and FRAME in s1, "a session-addressed row must say it names no one agent"
        assert seat.fire(parent_event()) == "" and seat.fire(subagent_event(tool="Read", path="/tmp/y")) == "", \
            "delivered once per agent"
        post = dict(subagent_event(tool="Read", path="/tmp/y"), hook_event_name="PostToolUse")
        assert seat.fire(post) == "", "PostToolUse shares the agent's cursor: no second rendering"


def test_parent_and_subagent_cursors_are_distinct_and_the_parents_key_is_unchanged():
    """A cursor already on disk for a parent session keeps working after the upgrade."""
    with tempfile.TemporaryDirectory() as d:
        seat = Seat(d)
        seat.append(lane_row("e1", PARENT, "APPROVED - escalation e1."))
        seat.fire(parent_event())
        seat.fire(subagent_event(tool="Read", path="/tmp/y"))
        names = sorted(os.listdir(seat.state / "disposition-cursors"))
        legacy = "s-" + hashlib.sha256(PARENT.encode()).hexdigest() + ".json"
        assert legacy in names and len(names) == 2, names
        assert any(n.startswith("a-") for n in names), names


def test_an_agent_addressed_row_reaches_only_its_agent():
    """The proposed daemon slice: the asker's agent_id recorded at open, written as `for_agent`.
    The parent firing first renders nothing and consumes nothing; a sibling subagent renders
    nothing; the named subagent renders it, unframed."""
    with tempfile.TemporaryDirectory() as d:
        seat = Seat(d)
        seat.append(lane_row("e-agent", PARENT, "APPROVED - escalation e-agent.", for_agent=AGENT))
        assert seat.fire(parent_event()) == "", "the parent rendered a row addressed to its subagent"
        assert seat.fire(subagent_event(tool="Read", agent=SIBLING)) == "", "a sibling subagent rendered it"
        s = seat.fire(subagent_event(tool="Read", path="/tmp/y"))
        assert "e-agent" in s and FRAME not in s, s
        assert seat.fire(subagent_event(tool="Read", path="/tmp/y")) == ""


def test_a_parent_addressed_row_is_not_a_subagents():
    """`for_agent: null` names the parent (the asker had no agent id)."""
    with tempfile.TemporaryDirectory() as d:
        seat = Seat(d)
        seat.append(lane_row("e-parent", PARENT, "APPROVED - escalation e-parent.", for_agent=None))
        assert seat.fire(subagent_event(tool="Read", path="/tmp/y")) == ""
        p = seat.fire(parent_event())
        assert "e-parent" in p and FRAME not in p, p


def test_another_sessions_row_reaches_no_agent_of_this_one():
    with tempfile.TemporaryDirectory() as d:
        seat = Seat(d)
        seat.append(lane_row("e-other", "some-other-session", "APPROVED - escalation e-other."))
        assert seat.fire(parent_event()) == "" and seat.fire(subagent_event(tool="Read")) == ""


TESTS = [
    test_the_gate_addresses_a_subagents_escalation_to_the_parents_session,
    test_todays_row_reaches_the_subagent_even_when_the_parent_fires_first,
    test_parent_and_subagent_cursors_are_distinct_and_the_parents_key_is_unchanged,
    test_an_agent_addressed_row_reaches_only_its_agent,
    test_a_parent_addressed_row_is_not_a_subagents,
    test_another_sessions_row_reaches_no_agent_of_this_one,
]

if __name__ == "__main__":
    defined = {k for k in globals() if k.startswith("test_")}
    listed = {t.__name__ for t in TESTS}
    if defined != listed:
        print(f"TESTS list is stale: {sorted(defined ^ listed)}")
        sys.exit(1)
    failed = 0
    for t in TESTS:
        try:
            t()
            print(f"ok    {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)
