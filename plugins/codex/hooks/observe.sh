#!/usr/bin/env sh
# Hestia Phase-0 observe-only hook (Codex adapter).
#
# Contract (deliberate, load-bearing): FIRE-AND-FORGET observation. It NEVER emits a permission
# decision and ALWAYS exits 0 — fail-OPEN by design. An observation layer must never break the
# member's loop; if it could, it would be a gate, and gates are Phase 1. Wired only to non-blocking
# events (SessionStart / PostToolUse / SessionEnd), so it is structurally incapable of blocking.
#
# It appends the raw Codex event JSON (which carries hook_event_name, session_id, cwd, tool_name,
# tool_input) as one JSONL line to Hestia's observation log — the substrate the adaptive baseline
# (drift detection, S7) grows from. Prompts live in Codex's own session 'rollout' files under
# ~/.codex, so we need not hook the blocking-capable UserPromptSubmit here.
#
# No jq / no external deps: the event is already a single JSON object; we append it verbatim.

OBS_DIR="${HESTIA_OBSERVE_DIR:-${CODEX_HOME:-$HOME/.codex}/hestia-observe}"
mkdir -p "$OBS_DIR" 2>/dev/null
# Read the whole event, then write it + newline in ONE printf to minimize interleave when parallel
# hook processes append concurrently. Not fully atomic above PIPE_BUF (~4KB); the durable fix is the
# consumer skip-and-count + off-host hash-chained ingest (PRD S10). Phase 0 only (disclosed).
_ev="$(cat)"
printf '%s\n' "$_ev" >> "$OBS_DIR/observe.jsonl" 2>/dev/null
exit 0
