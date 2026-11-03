"""Pure classification for supplied merge-census records.

No filesystem, network, chain walker or credential access happens here. A caller
is responsible for authorization, provenance, completeness and retention of its
input. A parsed target is only a candidate, never proof of execution or identity.
The output can still contain sensitive identifiers and timestamps: omitting raw
target text does not make it safe to retain, share or publish.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Iterable


_GH, _PR, _MERGE = "gh", "pr", "merge"


def merge_calls(target: object) -> list[tuple[int, str | None]] | None:
    """Recognize a simple direct candidate; everything else is unknown.

    shlex discards quote provenance, so its punctuation tokens cannot safely
    distinguish a quoted separator from shell syntax. Reject either form before
    lexing. This intentionally sacrifices recall and is not a shell parser.
    A candidate, even with a matching timestamp, does not prove execution.
    """
    if not isinstance(target, str):
        return None
    if any(marker in target for marker in ("$", "`", "#", "\\", "\n", "\r", ";", "&", "|", "(", ")", "<", ">", "*", "?", "[", "]", "{", "}", "~")):
        return None
    try:
        tokens = shlex.split(target, comments=False, posix=True)
    except ValueError:
        return None
    calls = _merge_in_segment(tokens)
    return calls if calls else None


def _merge_in_segment(seg: list[str]) -> list[tuple[int, str | None]]:
    if (len(seg) < 4 or seg[:3] != [_GH, _PR, _MERGE]
            or len(seg[3]) > 20 or not seg[3].isascii() or not seg[3].isdigit()):
        return []
    repo = None
    flags = {"--merge", "--squash", "--rebase", "--delete-branch",
             "--delete-branch=false", "--admin", "--auto", "--disable-auto"}
    i = 4
    while i < len(seg):
        tok = seg[i]
        if tok in flags:
            i += 1
            continue
        if tok in ("--repo", "-R") and i + 1 < len(seg):
            candidate = seg[i + 1]
            i += 2
        elif tok.startswith("--repo="):
            candidate = tok.split("=", 1)[1]
            i += 1
        else:
            return []
        if repo is not None or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", candidate):
            return []
        repo = candidate
    return [(int(seg[3]), repo)]


def classify_outcomes(entries: Iterable[dict]) -> list[dict]:
    """Classify supplied records only; never establish source or execution truth."""
    found: list[dict] = []
    ambiguous = 0
    for entry in entries:
        if not isinstance(entry, dict):
            ambiguous += 1
            continue
        event_type = entry.get("eventType")
        if not isinstance(event_type, str) or not event_type:
            ambiguous += 1
            continue
        if event_type != "outcome":
            continue
        data = entry.get("eventData")
        if not isinstance(data, dict):
            ambiguous += 1
            continue
        calls = merge_calls(data.get("target"))
        if calls is None:
            ambiguous += 1
            continue
        if calls == []:
            continue
        if data.get("success") is not True or data.get("error"):
            # A failed/unknown response does not prove that the effect did not
            # occur before a transport or post-effect failure.
            ambiguous += 1
            continue
        found.append({
            "action_id": data.get("action_id"),
            "plugin_id": data.get("plugin_id"),
            "ts": entry.get("timestamp"),
            "chain_position": entry.get("chainPosition"),
            "calls": [[n, r] for n, r in calls],
        })
    if ambiguous:
        found.append({"calls": None, "ambiguous_count": ambiguous})
    return found
