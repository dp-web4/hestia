#!/usr/bin/env sh
# Hestia Phase-0 observe-only hook (Antigravity / agy). FIRE-AND-FORGET. Appends the raw event JSON to
# the observation log, then emits a clean allow ({}) and exits 0. On a FAIL-CLOSED engine this matters:
# a non-blocking observer that errored or exited non-zero would be read as DENY, so it must always emit
# {} + exit 0. Wire only to non-blocking events (SessionStart / Stop).
OBS_DIR="${HESTIA_OBSERVE_DIR:-$HOME/.gemini/antigravity-cli/hestia-observe}"
mkdir -p "$OBS_DIR" 2>/dev/null
_ev="$(cat)"
printf '%s\n' "$_ev" >> "$OBS_DIR/observe.jsonl" 2>/dev/null
printf '{}'
exit 0
