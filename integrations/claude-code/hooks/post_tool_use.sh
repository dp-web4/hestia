#!/bin/bash
# Hestia PostToolUse hook — fire-and-forget so Claude Code doesn't wait for
# the MCP round-trip. Exits 0 immediately; the background Python records
# the outcome to the Hestia witness chain at its own pace.

set -e

# Buffer stdin (closes when this shell exits, so we MUST capture before backgrounding).
INPUT="$(cat)"

# Spawn the recorder, fully detached.
(
  echo "$INPUT" | exec python3 \
    "$(dirname "$0")/hestia_witness.py" \
    >/dev/null 2>&1
) &
disown
exit 0
