#!/usr/bin/env python3
"""The deliverer renders the daemon's ruling to the ASKER's session, and to nobody else.

PRD_DISPOSITION_DELIVERY R4/R6, claude-code's port. Arms, each with the sabotage that proves
it can fail:

  1. no lane                  -> no output, rc 0 (a seat with no rulings is silent)
  2. a line for THIS session  -> hookSpecificOutput.additionalContext carries the daemon's
                                 `render` verbatim, and hookEventName echoes the event that
                                 delivered it (the field is per-event; a wrong name is dropped)
  3. a line for ANOTHER       -> nothing rendered: two sessions of one member are two askers
     session
  4. already delivered        -> the second event on an unchanged lane renders nothing
  5. lane rotated/truncated   -> the cursor resets and the line is delivered, rather than the
                                 seat seeking past a new file's end and going silent forever
  6. malformed line, missing  -> skipped; the good line beside it is still delivered
     `render`
  7. corrupt cursor           -> delivers from the start rather than crashing the session
  8. runaway lane (60 lines)  -> at most MAX_LINES rendered, and still valid JSON out

Arm 2 is the one that matters: it is the whole mechanism. It is witnessed by arm 4, which
proves the delivery is not simply "print the lane every time".
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE / "disposition_deliver.py"
FAILURES: list[str] = []
SESSION = "sess-asker-0001"
OTHER = "sess-bystander-9999"


def check(ok: bool, msg: str) -> None:
    print(("ok  : " if ok else "FAIL: ") + msg)
    if not ok:
        FAILURES.append(msg)


def teardown_module(module=None) -> None:
    assert not FAILURES, FAILURES


def line(render: str, for_session=SESSION, **extra) -> str:
    row = {"escalation_id": "e" * 16, "decision": "approved", "render": render}
    if for_session is not None:
        row["for_session"] = for_session
    row.update(extra)
    return json.dumps(row)


class Seat:
    """One seat: its own HESTIA_HOME lane and its own cursor state dir."""

    def __init__(self, raw: str):
        self.home = Path(raw) / "hestia"
        self.state = Path(raw) / "seat"
        (self.home / "dispositions").mkdir(parents=True)
        self.state.mkdir()
        self.lane = self.home / "dispositions" / "claude-code.jsonl"

    def write(self, *lines: str, append: bool = True) -> None:
        with open(self.lane, "a" if append else "w", encoding="utf-8") as fh:
            for ln in lines:
                fh.write(ln + "\n")

    def fire(self, event="PreToolUse", session=SESSION) -> tuple[int, str]:
        env = dict(os.environ, HESTIA_HOME=str(self.home), HESTIA_SEAT_STATE=str(self.state))
        env.pop("HESTIA_PLUGIN_ID", None)
        payload = json.dumps({"hook_event_name": event, "session_id": session,
                              "tool_name": "Bash", "tool_input": {"command": "true"}})
        r = subprocess.run([sys.executable, str(TOOL)], input=payload, env=env,
                           capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout

    def context(self, **kw):
        """The additionalContext of one firing, or None when the hook stayed silent."""
        rc, out = self.fire(**kw)
        if rc != 0:
            return rc, None
        if not out.strip():
            return rc, None
        try:
            return rc, json.loads(out)["hookSpecificOutput"]
        except Exception:
            return rc, {"MALFORMED": out[:200]}


def test_no_lane_is_silence() -> None:
    with tempfile.TemporaryDirectory() as raw:
        seat = Seat(raw)
        rc, ctx = seat.context()
        check(rc == 0 and ctx is None, f"[1] no lane: silent, rc 0 (rc={rc}, ctx={ctx})")


def test_the_askers_line_is_delivered() -> None:
    with tempfile.TemporaryDirectory() as raw:
        seat = Seat(raw)
        seat.write(line("APPROVED e4de. Claimable until 22:41:07Z. Re-issue the same write."))
        rc, ctx = seat.context(event="PostToolUse")
        ok = bool(ctx) and "APPROVED e4de" in (ctx.get("additionalContext") or "")
        check(ok, f"[2] the asker's ruling is delivered verbatim: {str(ctx)[:160]}")
        check(bool(ctx) and ctx.get("hookEventName") == "PostToolUse",
              f"[2] hookEventName echoes the delivering event: {ctx and ctx.get('hookEventName')}")


def test_another_sessions_line_is_not_delivered() -> None:
    with tempfile.TemporaryDirectory() as raw:
        seat = Seat(raw)
        seat.write(line("this ruling belongs to someone else", for_session=OTHER))
        rc, ctx = seat.context()
        check(rc == 0 and ctx is None, f"[3] a bystander's ruling is not rendered: {str(ctx)[:120]}")


def test_delivered_once() -> None:
    with tempfile.TemporaryDirectory() as raw:
        seat = Seat(raw)
        seat.write(line("APPROVED once"))
        _, first = seat.context()
        _, second = seat.context()
        check(bool(first) and second is None,
              f"[4] delivered on the first event, silent on the next: {str(second)[:120]}")
        seat.write(line("APPROVED twice"))
        _, third = seat.context()
        check(bool(third) and "twice" in (third.get("additionalContext") or "")
              and "once" not in (third.get("additionalContext") or ""),
              f"[4] a NEW line is delivered, the old one is not repeated: {str(third)[:160]}")


def test_rotated_lane_resets_the_cursor() -> None:
    with tempfile.TemporaryDirectory() as raw:
        seat = Seat(raw)
        seat.write(line("APPROVED before rotation"))
        seat.context()
        os.replace(seat.lane, str(seat.lane) + ".1")          # rotate: new inode at the same path
        seat.write(line("APPROVED after rotation"), append=False)
        _, ctx = seat.context()
        check(bool(ctx) and "after rotation" in (ctx.get("additionalContext") or ""),
              f"[5] a rotated lane re-delivers from its start: {str(ctx)[:160]}")


def test_malformed_lines_are_skipped() -> None:
    with tempfile.TemporaryDirectory() as raw:
        seat = Seat(raw)
        seat.write("{not json at all", json.dumps({"for_session": SESSION}),
                   json.dumps(["a", "list"]), line("APPROVED beside the garbage"))
        rc, ctx = seat.context()
        check(rc == 0 and bool(ctx) and "beside the garbage" in (ctx.get("additionalContext") or ""),
              f"[6] garbage lines are skipped, the good one is delivered: {str(ctx)[:160]}")


def test_corrupt_cursor_still_delivers() -> None:
    with tempfile.TemporaryDirectory() as raw:
        seat = Seat(raw)
        (seat.state / "disposition-cursor.json").write_text("<<<not json>>>", encoding="utf-8")
        seat.write(line("APPROVED despite the cursor"))
        rc, ctx = seat.context()
        check(rc == 0 and bool(ctx) and "despite the cursor" in (ctx.get("additionalContext") or ""),
              f"[7] a corrupt cursor does not silence delivery: {str(ctx)[:160]}")


def test_runaway_lane_is_bounded() -> None:
    with tempfile.TemporaryDirectory() as raw:
        seat = Seat(raw)
        seat.write(*[line(f"APPROVED number {i}") for i in range(60)])
        rc, ctx = seat.context()
        body = (ctx or {}).get("additionalContext") or ""
        check(rc == 0 and bool(ctx) and body.count("APPROVED number") <= 20,
              f"[8] a runaway lane is bounded ({body.count('APPROVED number')} rendered)")
        check("number 59" in body, "[8] and the bound keeps the NEWEST rulings")


if __name__ == "__main__":
    test_no_lane_is_silence()
    test_the_askers_line_is_delivered()
    test_another_sessions_line_is_not_delivered()
    test_delivered_once()
    test_rotated_lane_resets_the_cursor()
    test_malformed_lines_are_skipped()
    test_corrupt_cursor_still_delivers()
    test_runaway_lane_is_bounded()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}", file=sys.stderr)
        sys.exit(1)
    print("ok: the ruling reaches the asker's session, once, and reaches no other")
