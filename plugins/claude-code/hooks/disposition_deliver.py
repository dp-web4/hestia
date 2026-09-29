#!/usr/bin/env python3
"""Deliver a governance disposition to the asker's LIVE session, on the seat's own hook stream.

dp, 2026-09-02: "regardless of window, the mechanism is supposed to notify the asker of the
disposition the moment it takes place."  PRD_DISPOSITION_DELIVERY R4, claude-code's port.

WHAT THIS IS NOT.  It is not a gate: it decides nothing, refuses nothing, and cannot block a
tool call.  It renders one line the DAEMON composed, on the one channel this harness reads
mid-turn (`hookSpecificOutput.additionalContext`, accepted on PreToolUse, PostToolUse and
UserPromptSubmit).  SHIM_LEDGER class: refusal-channel.  Every judgement -- what was decided,
whether a grant still authorises anything, until when, and what the asker may do -- is the
daemon's, carried verbatim in the lane line's `render` field.

IT IS ALSO NOT PROOF OF RECEIPT.  Rendering is availability, not an acknowledgement: nothing
here is witnessed, so no clock may start from it.  The ACK that makes receipt a fact is the
next slice (#845 R5/R8).  Until it exists, "delivered" in this file means "put in front of the
model", and the daemon's horizon stays anchored where it always was.

WHY A FILE AND NOT A POLL.  A poll costs a round trip on a daemon that serializes every member,
and `mark_observed` starts the asker's claim fuse: a hook that polled on every call would light
the fuse before the model could read the answer (#732).  Reading a file consumes nothing and
burns nothing.

THE CURSOR IS PER SESSION, AND THAT IS THE WHOLE CORRECTION (#851).  The first cut kept one
cursor per SEAT and advanced it over lines addressed to other sessions, which meant a co-seat
session -- one of the mesh wakes that exist BECAUSE delivery is broken -- silently destroyed a
ruling it rendered to nobody.  Measured: 48 claude-seat wakes on 2026-09-02, and for 48.4% of
that span a fresh co-seat session starts within one claim window.  `tools/disposition_deliver_
bystander_probe.py` runs the sequence (bystander first, asker second) and the fix on the same
sequence.  One cursor per (seat, session): a session advances only its own, so no session can
consume another's mail, and no read is destructive to anyone else.

A SESSION'S FIRST SIGHT READS THE WHOLE LANE BUT DELIVERS ONLY WHAT NAMES IT.  Two failures
sit on either side of this rule.  Start a first-sight cursor at offset 0 and deliver
everything, and each new session inherits the backlog of every unaddressed line ever written.
Start it at end-of-lane instead, and an asker whose ruling landed before its first hook event
never learns of it -- measured against the bystander probe, which writes the ruling first and
fires afterwards: every arm read `delivered=False`.  So first sight scans from the start and
renders only lines whose `for_session` IS this session; unaddressed lines are delivered from
the second sight on, when "I was here already" is true.

FAILURE POSTURE.  Silence.  Any error -- no lane, unreadable cursor, malformed line, missing
field -- exits 0 with no output.  A delivery mechanism that could break a session would be
worse than the manual relay it replaces, and this hook holds no verdict to fail closed over.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time

PLUGIN_ID = os.environ.get("HESTIA_PLUGIN_ID") or "claude-code"
HESTIA_HOME = os.environ.get("HESTIA_HOME") or os.path.expanduser("~/.hestia")
LANE = os.path.join(HESTIA_HOME, "dispositions", PLUGIN_ID + ".jsonl")
STATE_DIR = os.environ.get("HESTIA_SEAT_STATE") or os.path.expanduser("~/.hestia-claude")
CURSOR_DIR = os.path.join(STATE_DIR, "disposition-cursors")
MAX_RENDER = 4000            # one delivery is a paragraph, never a transcript
MAX_LINES = 20               # a backlog is delivered; a runaway lane is not a context bomb
CURSOR_TTL_SECS = 7 * 86400  # a cursor outlives its session by a week, then it is litter


def cursor_path(session_id: str) -> str:
    """One cursor per (seat, session), named by a HASH of the full session identity.

    The first cut sanitised the id into a filename (`[^A-Za-z0-9_.-]` -> `_`, cut at 120), which
    is lossy: `a/b` and `a_b` shared one cursor, and so did any two ids agreeing on their first
    120 characters -- one session's read then advanced another's position, the #851 failure by a
    different road (GPT review of f5baa33). A digest cannot select a path outside this dir and
    cannot collide two sessions; #1148's prompt watch keys its state the same way."""
    if not session_id:
        return os.path.join(CURSOR_DIR, "no-session.json")
    return os.path.join(CURSOR_DIR, "s-" + hashlib.sha256(session_id.encode("utf-8")).hexdigest() + ".json")


def reap_cursors(now: float) -> None:
    """Sessions end without saying so, and their cursors would accumulate forever."""
    try:
        for name in os.listdir(CURSOR_DIR):
            p = os.path.join(CURSOR_DIR, name)
            try:
                if now - os.stat(p).st_mtime > CURSOR_TTL_SECS:
                    os.remove(p)
            except OSError:
                pass
    except OSError:
        pass


def read_cursor(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            c = json.load(fh)
        return c if isinstance(c, dict) else {}
    except Exception:
        return {}


def write_cursor(path: str, offset: int, inode: int, boundary: int = 0) -> None:
    """Best effort, atomic. A lost cursor re-delivers to ONE session; a corrupt one is ignored.

    `boundary` is the lane's size when this session FIRST saw it, kept for the session's life:
    an unaddressed row that starts before it predates the session and is never its to render,
    however many bounded passes the backlog takes to drain (GPT re-review of e053cc4)."""
    try:
        os.makedirs(CURSOR_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"offset": offset, "inode": inode, "boundary": boundary}, fh)
        os.replace(tmp, path)
    except Exception:
        pass


def unread_records(lane: str, cursor: dict):
    """([(line, start, end)], inode, boundary, offset, first_sight) for THIS session.

    Each COMPLETE unread line comes with its start and end byte offsets, so the caller can judge
    it against the session's boundary and advance exactly as far as it processed.

    A session with no cursor for this lane reads it whole, and its BOUNDARY is set to the lane's
    size at that moment and persisted: only what names the session is rendered from before it,
    and an unaddressed row is eligible only if it STARTS at or after it. The first cut derived
    that from "is there a cursor yet", which the first bounded pass writes -- so a backlog of
    more than MAX_LINES addressed rows handed the new session the pre-existing unaddressed rows
    on its second pass (GPT re-review of e053cc4). A cursor written before the boundary existed
    carries none and reads as boundary 0, which is exactly its old behaviour. Keyed on the inode
    as well as the offset, so a rotated or truncated lane starts over (with a new boundary)."""
    try:
        st = os.stat(lane)
    except OSError:
        return [], None, 0, 0, False
    first_sight = "offset" not in cursor or cursor.get("inode") != st.st_ino
    offset = 0 if first_sight else (cursor.get("offset") or 0)
    if offset > st.st_size:                     # truncated under us: start over
        offset, first_sight = 0, True
    boundary = st.st_size if first_sight else int(cursor.get("boundary") or 0)
    if offset == st.st_size:
        return [], st.st_ino, boundary, offset, first_sight
    try:
        with open(lane, "rb") as fh:
            fh.seek(offset)
            payload = fh.read()
    except OSError:
        return [], st.st_ino, boundary, offset, first_sight
    out, pos = [], offset
    for chunk in payload.split(b"\n")[:-1]:    # the last piece has no newline: not yet complete
        start = pos
        pos += len(chunk) + 1
        text = chunk.decode("utf-8", "replace")
        if text.strip():
            out.append((text, start, pos))
    return out, st.st_ino, boundary, offset, first_sight


def select(records, session_id: str, boundary: float = 0):
    """(texts to render, offset to advance to) -- addressing FIRST, then the bound.

    The first cut sliced `lines[-MAX_LINES:]` BEFORE filtering on `for_session`, while the cursor
    advanced to the end of the whole lane: an approval for the asker followed by 20 rows for a
    sibling was sliced away and the cursor moved past it, so it was never rendered, on that call
    or any later one (GPT review of f5baa33). Now every record is judged in order; a record not
    ours is processed (the cursor may pass it); a record that IS ours is rendered until the bound
    is reached, and the first one past the bound stops the pass WITHOUT advancing over it, so the
    next hook event renders it. Oldest first: a backlog drains in order across events, and no
    addressed ruling is ever passed without being shown.

    `records` are (line, start, end). A row naming this session is always ours; a row naming
    another never is; an UNADDRESSED row is ours only if it starts at or after `boundary`, the
    lane's size when this session first saw it."""
    out, advance = [], None
    for raw, start, end in records:
        try:
            row = json.loads(raw)
        except Exception:
            advance = end
            continue
        if not isinstance(row, dict):
            advance = end
            continue
        want = row.get("for_session")
        text = row.get("render")
        named = bool(want and session_id and want == session_id)
        other = bool(want and session_id and want != session_id)
        ours = named or (not other and start >= boundary)
        # (an unaddressed row before the boundary predates this session: not ours to render)
        if ours and isinstance(text, str) and text.strip():
            if len(out) >= MAX_LINES:
                break         # the bound: this record waits for the next event, unpassed
            out.append(text.strip()[:MAX_RENDER])
        advance = end
    return out, advance


def deliverable(lines, session_id: str, first_sight: bool = False):
    """The lines addressed to THIS asker, rendered by the daemon -- the same judgement as `select`,
    over a plain list (kept for callers and the review's composed case).

    `for_session` absent means the daemon could not prove the asker's session (`asker_basis`
    asserted): those are delivered to any session of the seat, because the alternative is not
    delivering a ruling at all. `for_session` present and different is another asker's mail,
    and skipping it costs that asker nothing now that the cursor is its own."""
    boundary = float("inf") if first_sight else 0
    return select([(ln, i, i + 1) for i, ln in enumerate(lines)], session_id, boundary)[0]


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    hook_event = event.get("hook_event_name") or "PreToolUse"
    session_id = event.get("session_id") or ""
    path = cursor_path(session_id)
    reap_cursors(time.time())
    records, inode, boundary, offset, first_sight = unread_records(LANE, read_cursor(path))
    if inode is None:
        return 0
    texts, advance = select(records, session_id, boundary)
    if advance is not None or first_sight:
        # This session's own position only, and only as far as it PROCESSED: an addressed
        # ruling held back by the bound is not passed (GPT, f5baa33). No other session's
        # delivery is affected, which is the property #851 falsified in the first cut. On first
        # sight the boundary is recorded even when nothing was rendered, so an unaddressed row
        # appended later is recognisably newer than the session (e053cc4 re-review).
        write_cursor(path, advance if advance is not None else offset, inode, boundary)
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
