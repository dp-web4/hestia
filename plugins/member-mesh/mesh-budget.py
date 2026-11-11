#!/usr/bin/env python3
"""Best-effort remaining-budget line for one mesh fire (#551)."""

import json
import subprocess
import sys


def remaining(doc):
    if not isinstance(doc, dict):
        return None
    percent = doc.get("remaining_percent")
    window = doc.get("window")
    if isinstance(percent, (int, float)) and not isinstance(percent, bool):
        if window in ("session", "weekly") and 0 <= percent <= 100:
            return percent, window
    for window in ("session", "weekly"):
        nested = doc.get(window)
        if not isinstance(nested, dict):
            continue
        percent = nested.get("remaining_percent")
        if (isinstance(percent, (int, float)) and not isinstance(percent, bool)
                and 0 <= percent <= 100):
            return percent, window
    return None


def main():
    member = sys.argv[1] if len(sys.argv) == 2 else ""
    executable = {"claude-code": "claude", "codex": "codex", "kimi-code": "kimi"}.get(member)
    if executable is None:
        return
    try:
        result = subprocess.run(
            [executable, "usage", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            return
        reading = remaining(json.loads(result.stdout))
    except (OSError, ValueError, subprocess.SubprocessError):
        return
    if reading is None:
        return
    percent, window = reading
    rendered = f"{percent:.1f}".rstrip("0").rstrip(".")
    print(f"budget: ~{rendered}% {window} remaining")


if __name__ == "__main__":
    main()
