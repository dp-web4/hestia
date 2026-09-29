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
  7. corrupt cursor           -> delivers rather than crashing the session, with the cursor
                                 path DERIVED from the hook: the hand-spelled path in the first
                                 cut kept passing after the cursor moved per session, because
                                 it corrupted a file nothing reads
  8. runaway lane (60 lines)  -> at most MAX_LINES per event, oldest first, and the rest DRAIN
                                 on later events -- each ruling exactly once, none skipped
 11. asker + 20 sibling rows  -> the asker's ruling is rendered although 20 rows for another
                                 session follow it (bound AFTER addressing; GPT, f5baa33)
 13. bounded first drain      -> >20 addressed rows + an OLD unaddressed row before first firing:
                                 the old row is never rendered on any pass; a later one is
 12. cursor identity          -> `a/b` and `a_b` (and two ids sharing 120 characters) keep
                                 separate cursors
  9. BYSTANDER FIRST           -> a co-seat session fires before the asker: it renders nothing
                                 AND the asker is still delivered. This is #851, which the
                                 first cut of this file failed while every arm above stayed
                                 green: one seat-wide cursor, advanced past a line addressed
                                 to another session, destroyed a ruling it showed to nobody.
                                 Arm 3 could not catch it -- it fires ONE session and asserts
                                 silence, which is true of the correct hook and the broken one
                                 alike. The order is the axis, so the order is the test.
 10. first sight               -> a session that has never read the lane renders what NAMES it
                                 (its ruling may predate its first hook event) and does not
                                 inherit unaddressed backlog written before it existed

Arm 2 is the whole mechanism; arm 4 proves it is not "print the lane every time"; arm 9 proves
one session's read cannot cost another its mail.
"""
from __future__ import annotations

import importlib.util
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


def cursor_file(seat, session=SESSION) -> Path:
    """The cursor path the HOOK itself would use, asked of the hook.

    Arm 7 used to spell `disposition-cursor.json` by hand. When the cursor moved to one file
    per session (#851) the arm kept passing, because it corrupted a file nothing reads: a test
    that spells a path the implementation owns drifts from it exactly once, silently, and then
    guards nothing. Deriving it means the arm cannot go vacuous that way again."""
    prev = os.environ.get("HESTIA_SEAT_STATE")
    os.environ["HESTIA_SEAT_STATE"] = str(seat.state)
    try:
        spec = importlib.util.spec_from_file_location("deliverer_paths", TOOL)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return Path(mod.cursor_path(session))
    finally:
        if prev is None:
            os.environ.pop("HESTIA_SEAT_STATE", None)
        else:
            os.environ["HESTIA_SEAT_STATE"] = prev


def test_corrupt_cursor_still_delivers() -> None:
    with tempfile.TemporaryDirectory() as raw:
        seat = Seat(raw)
        seat.write(line("APPROVED first, to make the cursor real"))
        seat.context()
        path = cursor_file(seat)
        # This is only a test of corruption if the file it corrupts is the live one.
        check(path.is_file(), f"[7] the hook's own cursor path exists after a delivery: {path}")
        path.write_text("<<<not json>>>", encoding="utf-8")
        seat.write(line("APPROVED despite the cursor"))
        rc, ctx = seat.context()
        check(rc == 0 and bool(ctx) and "despite the cursor" in (ctx.get("additionalContext") or ""),
              f"[7] a corrupt cursor does not silence delivery: {str(ctx)[:160]}")


def test_runaway_lane_is_bounded() -> None:
    import re
    with tempfile.TemporaryDirectory() as raw:
        seat = Seat(raw)
        seat.write(*[line(f"APPROVED number {i:02d}.") for i in range(60)])
        rc, ctx = seat.context()
        body = (ctx or {}).get("additionalContext") or ""
        check(rc == 0 and bool(ctx) and body.count("APPROVED number") <= 20,
              f"[8] one event is bounded ({body.count('APPROVED number')} rendered)")
        # The first cut kept the NEWEST 20 and moved the cursor past the other 40, which is how an
        # addressed ruling was lost. Now the backlog drains: every ruling, once, in order.
        seen = re.findall(r"APPROVED number (\d\d)\.", body)
        for _ in range(5):
            _, more = seat.context()
            seen += re.findall(r"APPROVED number (\d\d)\.", (more or {}).get("additionalContext") or "")
        check(seen == [f"{i:02d}" for i in range(60)],
              f"[8] across events the whole backlog drains, each ruling exactly once, in order "
              f"({len(seen)} delivered; first {seen[:3]}, last {seen[-3:]})")


def test_asker_ruling_survives_twenty_sibling_rows() -> None:
    """GPT's composed case (f5baa33): the bound was applied BEFORE addressing."""
    with tempfile.TemporaryDirectory() as raw:
        seat = Seat(raw)
        seat.write(line("ASKER-OPENS: a ruling to make this session's cursor real"))
        seat.context()
        seat.write(line("APPROVED for the asker, then buried"),
                   *[line(f"SIBLING row {i}", for_session=OTHER) for i in range(20)])
        rc, ctx = seat.context()
        body = (ctx or {}).get("additionalContext") or ""
        check(rc == 0 and "then buried" in body,
              f"[11] the asker's ruling is rendered although 20 sibling rows follow it: {body[:120]}")
        check("SIBLING" not in body, "[11] and no sibling row is rendered to the asker")
        # The pure function, exactly as the review composed it: first sight, asker first.
        spec = importlib.util.spec_from_file_location("deliverer_pure", TOOL)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rows = [line("ASKER approval", for_session="asker")] + \
               [line(f"sib {i}", for_session="sibling") for i in range(20)]
        check(mod.deliverable(rows, "asker", True) == ["ASKER approval"],
              f"[11] deliverable(asker + 20 siblings, first sight) returns the asker's row: "
              f"{mod.deliverable(rows, 'asker', True)}")


def test_cursor_identity_does_not_collide() -> None:
    with tempfile.TemporaryDirectory() as raw:
        seat = Seat(raw)
        a, b = cursor_file(seat, "a/b"), cursor_file(seat, "a_b")
        check(a != b, f"[12] `a/b` and `a_b` keep separate cursors: {a.name} vs {b.name}")
        long1, long2 = "x" * 120 + "one", "x" * 120 + "two"
        check(cursor_file(seat, long1) != cursor_file(seat, long2),
              "[12] two ids sharing their first 120 characters keep separate cursors")
        check(cursor_file(seat, "../../etc/passwd").parent == cursor_file(seat, "a").parent,
              "[12] and no session id selects a path outside the cursor dir")
        # Behaviour, not only names: the sibling `a_b` reading does not advance `a/b`.
        seat.write(line("APPROVED for a/b", for_session="a/b"))
        _, sib = seat.context(session="a_b")
        _, own = seat.context(session="a/b")
        check(sib is None and bool(own) and "for a/b" in (own.get("additionalContext") or ""),
              f"[12] `a_b` firing first does not consume `a/b`'s ruling: {str(own)[:120]}")


def test_bystander_first_does_not_eat_the_askers_ruling() -> None:
    """#851, measured live: the sessions that exist BECAUSE delivery is broken were breaking it.

    48 claude-seat wakes on 2026-09-02, median gap 938 s; for 48.4% of that span a fresh
    co-seat session starts within one claim window, and each fires PreToolUse on its first
    tool call. With a seat-wide cursor, whichever fires first consumes the line."""
    with tempfile.TemporaryDirectory() as raw:
        seat = Seat(raw)
        seat.write(line("APPROVED for the asker alone"))
        rc_b, bystander = seat.context(session=OTHER)
        check(rc_b == 0 and bystander is None,
              f"[9] the bystander renders nothing: {str(bystander)[:120]}")
        rc_a, asker = seat.context(session=SESSION)
        check(rc_a == 0 and bool(asker)
              and "for the asker alone" in (asker.get("additionalContext") or ""),
              f"[9] and the asker is STILL delivered after it: {str(asker)[:160]}")
        _, again = seat.context(session=OTHER)
        check(again is None, "[9] the bystander's second look is still silent")


def test_first_sight_takes_what_names_it_and_no_backlog() -> None:
    with tempfile.TemporaryDirectory() as raw:
        seat = Seat(raw)
        seat.write(line("UNADDRESSED backlog from before this session", for_session=None),
                   line("APPROVED and addressed to this session"))
        rc, ctx = seat.context()
        body = (ctx or {}).get("additionalContext") or ""
        check(rc == 0 and "addressed to this session" in body,
              f"[10] first sight delivers what names this session: {body[:160]}")
        check("UNADDRESSED backlog" not in body,
              "[10] and not the backlog that predates it")
        seat.write(line("UNADDRESSED after this session was reading", for_session=None))
        _, later = seat.context()
        check(bool(later) and "after this session was reading" in (later.get("additionalContext") or ""),
              "[10] an unaddressed line written LATER is delivered, because now it may be ours")


def test_bounded_drain_never_inherits_the_preexisting_backlog() -> None:
    """GPT re-review of e053cc4, composed exactly: a fresh session, 21 rows addressed to it, then an
    OLD unaddressed row, all written before its first firing. The first pass renders 20 and writes
    a cursor; the second must render the 21st and NOT the old unaddressed row -- which the cursor's
    mere existence used to admit. Control: an unaddressed row appended AFTER first sight shows."""
    with tempfile.TemporaryDirectory() as raw:
        seat = Seat(raw)
        seat.write(*[line(f"OWN ruling {i:02d}.") for i in range(21)],
                   line("OLD unaddressed backlog", for_session=None))
        bodies = []
        for _ in range(3):
            _, ctx = seat.context()
            bodies.append((ctx or {}).get("additionalContext") or "")
        allb = "\n".join(bodies)
        check(bodies[0].count("OWN ruling") == 20 and "OWN ruling 20." in bodies[1],
              f"[13] the 21 addressed rulings drain 20 then 1: {[b.count('OWN ruling') for b in bodies]}")
        check("OLD unaddressed backlog" not in allb,
              "[13] and the pre-existing unaddressed row is NEVER rendered, on any bounded pass")
        seat.write(line("LATER unaddressed, after first sight", for_session=None))
        _, later = seat.context()
        check(bool(later) and "LATER unaddressed" in (later.get("additionalContext") or ""),
              "[13] control: an unaddressed row appended after first sight IS delivered")
        cur = json.loads(cursor_file(seat).read_text())
        check(isinstance(cur.get("boundary"), int) and cur["boundary"] > 0,
              f"[13] the first-sight boundary is persisted with the cursor: {cur}")


if __name__ == "__main__":
    test_no_lane_is_silence()
    test_the_askers_line_is_delivered()
    test_another_sessions_line_is_not_delivered()
    test_delivered_once()
    test_rotated_lane_resets_the_cursor()
    test_malformed_lines_are_skipped()
    test_corrupt_cursor_still_delivers()
    test_runaway_lane_is_bounded()
    test_bystander_first_does_not_eat_the_askers_ruling()
    test_first_sight_takes_what_names_it_and_no_backlog()
    test_asker_ruling_survives_twenty_sibling_rows()
    test_cursor_identity_does_not_collide()
    test_bounded_drain_never_inherits_the_preexisting_backlog()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}", file=sys.stderr)
        sys.exit(1)
    print("ok: the ruling reaches the asker's session, once, and reaches no other")
