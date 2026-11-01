#!/usr/bin/env python3
"""peek-new — the print-only watcher's non-consuming inbox read (#1389 A).

A print-only watcher used to DRAIN the member's inbox (consume-once) into a primer the seat cannot read, so the live
session's own hooks (session-mesh-inbox.sh at SessionStart, prompt-disposition-watch.sh at UserPromptSubmit), which
only PEEK, always found it empty: two delivery paths that excluded each other. Now print-only PEEKS, and this filter
keeps only notices it has not reported before, so each one is journalled once and stays queued for the session that
drains it.

stdin:  the `hestia_member_inbox` response of a peek ({"notices": [...], "total": N, ...}).
argv:   <seen-file>  one notice id per line; appended atomically; the newest MAX_SEEN ids are kept.
stdout: the same envelope with `notices` cut to the unseen ones, `total` recounted, and `peeked: true`.
A notice with no id cannot be remembered, so it is reported every time (never silently dropped).
An unreadable response is passed through as {"total": 0, "peek_error": ...}: unknown, said aloud, never a fake list.
"""
import json
import os
import sys
import tempfile

MAX_SEEN = 5000


def main():
    if len(sys.argv) != 2:
        print("usage: peek-new.py <seen-file>", file=sys.stderr)
        return 2
    seen_path = sys.argv[1]
    raw = sys.stdin.read()
    try:
        d = json.loads(raw)
        notices = d.get("notices")
        if not isinstance(notices, list):
            raise ValueError("no notices list")
    except (ValueError, AttributeError) as e:
        print(json.dumps({"total": 0, "peek_error": f"unreadable inbox response: {e}"}))
        return 0
    try:
        with open(seen_path, encoding="utf-8") as f:
            seen = [ln.strip() for ln in f if ln.strip()]
    except OSError:
        seen = []
    known = set(seen)
    new = [n for n in notices if not isinstance(n, dict) or str(n.get("id", "")) == "" or str(n["id"]) not in known]
    add = [str(n["id"]) for n in new if isinstance(n, dict) and str(n.get("id", "")) != ""]
    if add:
        keep = (seen + add)[-MAX_SEEN:]
        d_ = os.path.dirname(os.path.abspath(seen_path))
        os.makedirs(d_, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=d_, delete=False, encoding="utf-8") as f:
            f.write("\n".join(keep) + "\n")
            tmp = f.name
        os.replace(tmp, seen_path)
    d["notices"] = new
    d["total"] = len(new)
    d["peeked"] = True
    print(json.dumps(d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
