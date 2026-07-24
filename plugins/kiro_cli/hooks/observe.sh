#!/usr/bin/env sh
# Hestia Phase-0 observe-only hook (Kiro CLI adapter). FIRE-AND-FORGET: never emits a decision, ALWAYS
# exits 0 (fail-open by design). Wired to non-blocking events only (SessionStart / PostToolUse / Stop),
# so it is structurally incapable of blocking. Appends the raw Kiro event JSON as one JSONL line to
# Hestia's observation log. No jq / no deps. (Kiro is a closed AWS product with no documented tailable
# transcript, so this event stream IS the observation substrate - see README transcript note.)
OBS_DIR="${HESTIA_OBSERVE_DIR:-${KIRO_HOME:-$HOME/.kiro}/hestia-observe}"
mkdir -p "$OBS_DIR" 2>/dev/null
_ev="$(cat)"
printf '%s\n' "$_ev" >> "$OBS_DIR/observe.jsonl" 2>/dev/null
exit 0
