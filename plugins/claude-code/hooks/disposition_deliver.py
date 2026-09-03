#!/usr/bin/env python3
"""Deliver a governance disposition to the asker's LIVE session, on the seat's own hook stream.

dp, 2026-09-02: "regardless of window, the mechanism is supposed to notify the asker of the
disposition the moment it takes place."  PRD_DISPOSITION_DELIVERY R4, claude-code's port.

WHAT THIS IS NOT.  It is not a gate: it decides nothing, refuses nothing, and cannot block a
tool call.  It renders one line the DAEMON composed, on the one channel this harness reads
mid-turn (`hookSpecificOutput.additionalContext`, accepted on PreToolUse, PostToolUse and
UserPromptSubmit).  SHIM_LEDGER class: refusal-channel.  Every judgement -- what was decided,
whether a grant is still claimable, when it dies, what the asker may do -- is the daemon's,
carried verbatim in the lane line's `render` field.

WHY A FILE AND NOT A POLL.  A poll would cost a daemon round trip on every tool call, and the
daemon serializes all members.  Worse, `mark_observed` starts the asker's claim fuse: a hook
that polled on every call would light the fuse before the model could read the answer (#732).
Reading a file consumes nothing and burns nothing, so a bystander session reading its seat's
lane cannot harm the asker (PRD R6).

THE LANE.  `$HESTIA_HOME/dispositions/<plugin>.jsonl`, append-only, written by the daemon in
the same transaction that appends the chain entry.  Each line carries `for_session` -- the
asker's `host_session_id`, which is this harness's own `session_id` (the gate hook sends it on
connect).  A line addressed to another session of the same seat is skipped, not rendered: two
sessions of one member are two askers.

FAILURE POSTURE.  Silence.  Any error -- no lane, unreadable cursor, malformed line, missing
field -- exits 0 with no output.  A delivery mechanism that could break a session would be
worse than the manual relay it replaces, and this hook holds no verdict to fail closed over.
"""
from __future__ import annotations

import json
import os
import sys

PLUGIN_ID = os.environ.get("HESTIA_PLUGIN_ID") or "claude-code"
HESTIA_HOME = os.environ.get("HESTIA_HOME") or os.path.expanduser("~/.hestia")
LANE = os.path.join(HESTIA_HOME, "dispositions", PLUGIN_ID + ".jsonl")
STATE_DIR = os.environ.get("HESTIA_SEAT_STATE") or os.path.expanduser("~/.hestia-claude")
CURSOR = os.path.join(STATE_DIR, "disposition-cursor.json")
MAX_RENDER = 4000          # one delivery is a paragraph, never a transcript
MAX_LINES = 20             # a backlog is delivered, but a runaway lane is not a context bomb


def _read_cursor() -> dict:
    try:
        with open(CURSOR, "r", encoding="utf-8") as fh:
            c = json.load(fh)
        return c if isinstance(c, dict) else {}
    except Exception:
        return {}


def _write_cursor(offset: int, inode: int) -> None:
    """Best effort, atomic. A lost cursor re-delivers; a corrupt one delivers nothing."""
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = CURSOR + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"offset": offset, "inode": inode}, fh)
        os.replace(tmp, CURSOR)
    except Exception:
        pass


def unread_lines(lane: str, cursor: dict):
    """New bytes since the cursor, plus the offset to record. ([], None) when there is nothing.

    Keyed on the inode as well as the offset: a rotated or truncated lane resets to 0 rather
    than seeking past the end of a new file and delivering nothing forever."""
    try:
        st = os.stat(lane)
    except OSError:
        return [], None
    offset = cursor.get("offset") or 0
    if cursor.get("inode") != st.st_ino or offset > st.st_size:
        offset = 0
    if offset == st.st_size:
        return [], None
    try:
        with open(lane, "r", encoding="utf-8", errors="replace") as fh:
            fh.seek(offset)
            payload = fh.read()
            end = fh.tell()
    except OSError:
        return [], None
    return [ln for ln in payload.splitlines() if ln.strip()], (end, st.st_ino)


def deliverable(lines, session_id: str):
    """The lines addressed to THIS asker, rendered by the daemon.

    `for_session` absent means the daemon could not prove the asker's session (asker_basis
    asserted): those are delivered to any session of the seat, because the alternative is not
    delivering a ruling at all. `for_session` present and different is another asker's mail."""
    out = []
    for raw in lines[-MAX_LINES:]:
        try:
            row = json.loads(raw)
        except Exception:
            continue
        if not isinstance(row, dict):
            continue
        want = row.get("for_session")
        if want and session_id and want != session_id:
            continue
        text = row.get("render")
        if isinstance(text, str) and text.strip():
            out.append(text.strip()[:MAX_RENDER])
    return out


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    hook_event = event.get("hook_event_name") or "PreToolUse"
    session_id = event.get("session_id") or ""
    cursor = _read_cursor()
    lines, advance = unread_lines(LANE, cursor)
    if not lines or advance is None:
        return 0
    texts = deliverable(lines, session_id)
    # The cursor advances over lines addressed to another session too: they were read, and
    # re-reading them on every event would deliver another asker's mail forever.
    _write_cursor(advance[0], advance[1])
    if not texts:
        return 0
    body = ("hestia: governance disposition (the daemon ruled; this is the ruling, not a gate)\n\n"
            + "\n\n".join(texts))
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": hook_event,
        "additionalContext": body,
    }}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
