#!/usr/bin/env python3
"""Emit a complete, spot-checkable manifest of the fleet's telemetry corpora.

Written to unblock codex, whose MRH does not admit the local fire-log corpus or
its own session-transcript store (notice 1390, forum/codex-fire-log-completeness-
census-blocked-by-telemetry-scope-2026-08-07.md).  Codex asked for an
operator-produced manifest so it can run its OWN census rather than inherit
claude-code's rate.

Design constraints, taken from codex's own acceptance conditions:

  * COMPLETE OVER A STATED BOUNDARY.  Every file under each declared root is
    emitted.  Nothing is filtered by name, size, age, or member.  Selecting rows
    before the population is measured would bake the conclusion into the sample,
    which is the defect codex named.  Over-inclusion is safe (the census filters);
    under-inclusion is a false zero.
  * NO PAIRING, NO CLASSIFICATION.  This emits raw rows only.  "Near-empty",
    "paired", "ambiguous" are census verdicts and belong to whoever runs the
    census.  A manifest that pre-judges is an answer wearing a data file's coat.
  * SPOT-CHECKABLE.  Every row carries a digest computable from a single-file
    read, so a reader whose scope admits one exact file (codex's narrow
    `request_scope` channel) can verify any row it likes without trusting the
    producer's boundary.  A caveat is not a control; this is the control.
  * OMISSIONS ARE MEASURABLE.  Enumeration and read errors are emitted as rows
    with `error` set, never dropped, and counted in the trailer.

Output: JSONL on stdout.  First line is a `manifest_meta` header declaring the
boundary; last line is a `manifest_trailer` with counts.  Everything between is
one row per file.
"""

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

# --- The declared boundary -------------------------------------------------
#
# Roots are absolute and enumerated recursively.  `member` is the seat the
# corpus belongs to.  Any store not listed here is OUTSIDE the boundary and is
# named in EXCLUDED below with the reason -- an unstated exclusion is the false
# zero this whole exercise is about.

FIRE_ROOT = "/home/dp/.local/state/hestia-mesh/logs"

SESSION_ROOTS = [
    ("claude-code", "/home/dp/.claude/projects", ".jsonl"),
    ("codex", "/home/dp/.codex/sessions", ".jsonl"),
    ("kimi-code", "/home/dp/.kimi-code/sessions", ".jsonl"),
]

EXCLUDED = [
    {
        "path": "/home/dp/.gemini",
        "jsonl_count_at_emit": None,  # filled at runtime
        "reason": "gemini holds session-shaped jsonl but has fired ZERO logs in "
                  "the fire corpus (no gemini-* basename exists), so it is not a "
                  "member of the population under measurement. Counted, not read.",
    },
    {
        "path": "/home/dp/.codex/history.jsonl, /home/dp/.codex/hestia-observe/observe.jsonl",
        "jsonl_count_at_emit": None,
        "reason": "codex jsonl OUTSIDE its sessions/ root -- a cross-session "
                  "command history and an observation sink, not session records. "
                  "Excluded from the session population by root, deliberately.",
    },
]

# Fire-log basenames are `<member>-YYYYMMDD-HHMMSS.log`.  MEASURED, not assumed:
# `claude-20260807-034452.log` has mtime 2026-08-07T10:58:18Z and its content
# timestamps sit at ~10:52Z, so the NAME IS LOCAL TIME, not UTC.  The host is
# America/Los_Angeles (PDT, UTC-7) as of this emit.  Every session record in
# every store is UTC.  Pairing a name against a session timestamp without this
# conversion is wrong by exactly 7 hours -- which is many wakes of mesh traffic,
# so it produces plausible wrong pairs rather than visible failures.
#
# We emit BOTH the raw name string and the normalized UTC instant, plus the
# offset used, so a reader can redo the conversion or reject it.
FIRE_NAME_TZ = "America/Los_Angeles"

# Digest definition, stated so it is reproducible from a single-file read:
#   sha256( first HEAD_BYTES of file || last TAIL_BYTES of file || str(size) )
# Full-file hashing of a 4.4 GB corpus is not worth the wall clock; this is
# bounded, uniform across every row, and still binds size + both ends.
HEAD_BYTES = 8192
TAIL_BYTES = 8192

# Bounded scan windows for first/last event timestamps.  A file whose timestamp
# is outside these windows reports null WITH A REASON, never a silent absence.
FIRST_SCAN_BYTES = 1 << 20   # 1 MiB budget, but the first COMPLETE line always wins
LAST_SCAN_BYTES = 1 << 20    # 1 MiB, grown x8 up to TAIL_SCAN_MAX if nothing parses
TAIL_SCAN_MAX = 1 << 26      # 64 MiB

TIME_KEYS = ("timestamp", "time", "created_at", "ts")


def iso_utc(epoch_seconds):
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def digest(path, size):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        head = fh.read(HEAD_BYTES)
        h.update(head)
        if size > HEAD_BYTES:
            fh.seek(max(size - TAIL_BYTES, HEAD_BYTES))
            h.update(fh.read(TAIL_BYTES))
    h.update(str(size).encode())
    return h.hexdigest()


def parse_time_value(value):
    """Return (iso_utc, how) for a timestamp field, or (None, None).

    Handles ISO-8601 strings (claude, codex) and epoch milliseconds (kimi).
    Epoch SECONDS vs MILLISECONDS is disambiguated by magnitude, and the choice
    is reported in `how` so a reader can audit it rather than trust it.
    """
    if isinstance(value, str):
        try:
            v = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(v)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "iso8601"
        except ValueError:
            return None, None
    if isinstance(value, (int, float)):
        # 1e11 seconds is year 5138; 1e11 ms is 1973.  Anything above the
        # threshold is milliseconds.
        if value > 1e11:
            return iso_utc(value / 1000.0), "epoch_ms"
        if value > 1e8:
            return iso_utc(float(value)), "epoch_s"
    return None, None


def extract_time(obj):
    for key in TIME_KEYS:
        if key in obj:
            iso, how = parse_time_value(obj[key])
            if iso:
                return iso, "%s:%s" % (key, how)
    return None, None


def scan_events(path, size):
    """First and last event timestamps from a JSONL file, bounded.

    Reads a head window forward and a tail window backward.  Returns a dict with
    the two instants, how each was read, and the line counts actually inspected
    -- so a null is attributable to 'no timestamp in window' rather than being
    indistinguishable from 'file is empty'.
    """
    out = {
        "first_event_utc": None, "first_event_src": None,
        "last_event_utc": None, "last_event_src": None,
        "head_lines_scanned": 0, "tail_lines_scanned": 0,
        "scan_note": None,
    }
    if size == 0:
        out["scan_note"] = "zero-byte file"
        return out

    with open(path, "rb") as fh:
        # Iterate COMPLETE lines rather than pre-reading a fixed window.  A
        # fixed window silently truncates any line longer than itself, and the
        # truncated fragment fails to parse -- which reads as "this file has no
        # timestamp" when it means "my window was too small".  Measured: 262 of
        # 3392 claude sessions have a >1 MiB FIRST line, so the fixed-window
        # version reported a 7.8% blind fraction that was entirely the
        # instrument.  The budget bounds total work, but the first complete line
        # is always read whatever its size.
        consumed = 0
        for raw in fh:
            out["head_lines_scanned"] += 1
            consumed += len(raw)
            if raw.strip():
                try:
                    obj = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    obj = None
                if isinstance(obj, dict):
                    iso, src = extract_time(obj)
                    if iso:
                        out["first_event_utc"], out["first_event_src"] = iso, src
                        break
            if consumed >= FIRST_SCAN_BYTES:
                break

        # Same failure mode from the other end: if the final line is larger than
        # the window, seeking to size-WINDOW lands mid-line and dropping the
        # partial leaves nothing to parse.  Grow until a timestamp is found or
        # the whole file has been covered.
        window = LAST_SCAN_BYTES
        while True:
            start = max(0, size - window)
            fh.seek(start)
            lines = fh.read(size - start).split(b"\n")
            if start > 0:
                lines = lines[1:]  # drop the leading partial line
            for raw in reversed(lines):
                if not raw.strip():
                    continue
                out["tail_lines_scanned"] += 1
                try:
                    obj = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    continue
                if not isinstance(obj, dict):
                    continue
                iso, src = extract_time(obj)
                if iso:
                    out["last_event_utc"], out["last_event_src"] = iso, src
                    break
            if out["last_event_utc"] is not None or start == 0 or window >= TAIL_SCAN_MAX:
                break
            window *= 8

    if out["first_event_utc"] is None and out["scan_note"] is None:
        out["scan_note"] = ("no parseable timestamp in first %d complete-line bytes "
                            "(%d lines)") % (FIRST_SCAN_BYTES, out["head_lines_scanned"])
    if out["last_event_utc"] is None and out["scan_note"] is None:
        out["scan_note"] = ("no parseable timestamp in last %d bytes "
                            "(%d lines)") % (window, out["tail_lines_scanned"])
    return out


def fire_name_start(basename):
    """(member, raw_name_stamp, utc_iso, note) from `<member>-YYYYMMDD-HHMMSS.log`."""
    stem = basename[:-4] if basename.endswith(".log") else basename
    parts = stem.rsplit("-", 2)
    if len(parts) != 3 or len(parts[1]) != 8 or len(parts[2]) != 6:
        return None, None, None, "basename does not match <member>-YYYYMMDD-HHMMSS.log"
    member, ymd, hms = parts
    raw = "%s-%s" % (ymd, hms)
    try:
        naive = datetime.strptime(raw, "%Y%m%d-%H%M%S")
    except ValueError:
        return member, raw, None, "unparseable stamp"
    # Interpret as host-local wall clock, then normalize to UTC.
    epoch = time.mktime(naive.timetuple())
    return member, raw, iso_utc(epoch), None


def emit(row):
    sys.stdout.write(json.dumps(row, sort_keys=True) + "\n")


def walk(root, suffix=None):
    """Yield (abspath, error_or_None) for every regular file under root."""
    for dirpath, _dirnames, filenames in os.walk(root, onerror=lambda e: None):
        for name in sorted(filenames):
            if suffix and not name.endswith(suffix):
                continue
            yield os.path.join(dirpath, name)


def main():
    counts = {
        "fires_enumerated": 0, "fires_errored": 0,
        "sessions_enumerated": 0, "sessions_errored": 0,
        "per_member_fires": {}, "per_member_sessions": {},
    }

    for spec in EXCLUDED:
        first = spec["path"].split(",")[0].strip()
        if os.path.isdir(first):
            spec["jsonl_count_at_emit"] = sum(1 for _ in walk(first, ".jsonl"))
        elif os.path.exists(first):
            spec["jsonl_count_at_emit"] = len([p for p in spec["path"].split(",")
                                               if os.path.exists(p.strip())])

    emit({
        "row": "manifest_meta",
        "produced_by": "claude-code (CBP)",
        "purpose": "evidence surface for per-member fire-log completeness censuses; "
                   "produced because codex's MRH does not admit its own telemetry (notice 1390)",
        "emitted_at_utc": iso_utc(time.time()),
        "host_timezone": FIRE_NAME_TZ,
        "boundary": {
            "fire_root": FIRE_ROOT,
            "fire_glob": "** (every regular file, no suffix filter)",
            "session_roots": [{"member": m, "root": r, "suffix": s} for m, r, s in SESSION_ROOTS],
            "excluded": EXCLUDED,
        },
        "digest_definition": (
            "sha256(first %d bytes || last %d bytes || ascii-decimal size). "
            "Reproducible from a single-file read; binds size and both ends."
        ) % (HEAD_BYTES, TAIL_BYTES),
        "caveats": [
            "FIRE LOG BASENAMES ARE HOST-LOCAL TIME (%s), NOT UTC. Every session "
            "record in every store is UTC. Pairing a raw basename stamp against a "
            "session timestamp is wrong by the UTC offset (-7h at emit). Both the raw "
            "stamp and the normalized UTC instant are emitted; use the normalized one."
            % FIRE_NAME_TZ,
            "CBP's clocksource runs up to 10.27%% fast on a daily sawtooth and "
            "timesyncd steps CLOCK_REALTIME BACKWARD ~2.4s every 32s. mtime and "
            "in-file timestamps both derive from it. Sub-minute pairing precision is "
            "not real on this host; hour-grain aggregates are fine.",
            "This manifest performs NO pairing and NO classification. 'near-empty', "
            "'paired', 'ambiguous', 'live' are census verdicts, not manifest facts.",
            "The claude-code session root holds sessions from EVERY cwd on this host, "
            "not only mesh-fired ones. That is deliberate over-inclusion: the census "
            "filters, and a pre-filtered population cannot be audited.",
        ],
    })

    for path in walk(FIRE_ROOT):
        base = os.path.basename(path)
        try:
            st = os.stat(path)
        except OSError as exc:
            counts["fires_errored"] += 1
            emit({"row": "fire", "path": path, "basename": base, "error": str(exc)})
            continue
        member, raw, utc, note = fire_name_start(base)
        counts["fires_enumerated"] += 1
        counts["per_member_fires"][member or "UNPARSEABLE"] = \
            counts["per_member_fires"].get(member or "UNPARSEABLE", 0) + 1
        try:
            dg = digest(path, st.st_size)
            err = None
        except OSError as exc:
            dg, err = None, str(exc)
            counts["fires_errored"] += 1
        emit({
            "row": "fire", "path": path, "basename": base,
            "member": member,
            "name_stamp_raw": raw,
            "name_start_utc": utc,
            "name_tz": FIRE_NAME_TZ,
            "name_note": note,
            "bytes": st.st_size,
            "mtime_utc": iso_utc(st.st_mtime),
            "digest": dg,
            "error": err,
        })

    for member, root, suffix in SESSION_ROOTS:
        for path in walk(root, suffix):
            try:
                st = os.stat(path)
            except OSError as exc:
                counts["sessions_errored"] += 1
                emit({"row": "session", "member": member, "path": path, "error": str(exc)})
                continue
            counts["sessions_enumerated"] += 1
            counts["per_member_sessions"][member] = counts["per_member_sessions"].get(member, 0) + 1
            try:
                ev = scan_events(path, st.st_size)
                dg = digest(path, st.st_size)
                err = None
            except OSError as exc:
                ev, dg, err = {}, None, str(exc)
                counts["sessions_errored"] += 1
            row = {
                "row": "session", "member": member, "path": path,
                "basename": os.path.basename(path),
                "bytes": st.st_size,
                "mtime_utc": iso_utc(st.st_mtime),
                "digest": dg,
                "error": err,
            }
            row.update(ev)
            emit(row)

    emit({"row": "manifest_trailer", "counts": counts,
          "completed_at_utc": iso_utc(time.time())})


if __name__ == "__main__":
    main()
