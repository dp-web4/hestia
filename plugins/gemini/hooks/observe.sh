#!/usr/bin/env sh
# Hestia Phase-0 observe-only hook (Gemini CLI adapter).
#
# Contract (deliberate, load-bearing): FIRE-AND-FORGET observation. It NEVER emits a decision and
# ALWAYS exits 0 - fail-OPEN by design. An observation layer must never break the member's loop; if
# it could, it would be a gate, and gates are Phase 1. Wired only to non-blocking events
# (SessionStart / AfterTool / SessionEnd), so it is structurally incapable of blocking.
#
# It appends the raw Gemini event JSON (carrying hook_event_name, session_id, cwd, transcript_path,
# and for tool events tool_name/tool_input) as one JSONL line to Hestia's observation log - the
# substrate the adaptive baseline (drift detection) grows from. No jq / no external deps.
OBS_DIR="${HESTIA_OBSERVE_DIR:-${GEMINI_HOME:-$HOME/.gemini}/hestia-observe}"
mkdir -p "$OBS_DIR" 2>/dev/null
_ev="$(cat)"
printf '%s\n' "$_ev" >> "$OBS_DIR/observe.jsonl" 2>/dev/null
exit 0
