#!/usr/bin/env sh
# Hestia Phase-0 observe-only hook.
#
# Contract (deliberate, load-bearing): this is FIRE-AND-FORGET observation. It NEVER emits a
# permission decision and ALWAYS exits 0 — fail-OPEN by design. An observation layer must never
# break the member's loop; if it could, it would be a gate, and gates are Phase 1. This hook is
# wired only to non-blocking events (SessionStart / PostToolUse / PostToolUseFailure / SessionEnd),
# so it is structurally incapable of blocking regardless of what it does.
#
# It appends the raw event JSON (which already carries hook_event_name, session_id, cwd, tool + args)
# as one JSONL line to Hestia's observation log. That log is the substrate the adaptive baseline
# (drift detection, S7) is grown from. Prompts are captured separately from Kimi's own append-only
# wire.jsonl (turn.prompt events) so we need not hook the blocking-capable UserPromptSubmit here.
#
# No jq / no external deps: the event is already a single JSON object; we append it verbatim.

OBS_DIR="${HESTIA_OBSERVE_DIR:-${KIMI_CODE_HOME:-$HOME/.kimi-code}/hestia-observe}"
mkdir -p "$OBS_DIR" 2>/dev/null
# Read the whole event, then write it + newline in ONE printf to minimize interleave when parallel
# hook processes append concurrently (HUB finding). Not fully atomic above PIPE_BUF (~4KB) — tool
# events are typically smaller; the durable fix is the consumer skip-and-count + off-host hash-chained
# ingest (PRD S10). The observed party writes its own baseline here: for Phase 0 only (disclosed).
_ev="$(cat)"
printf '%s\n' "$_ev" >> "$OBS_DIR/observe.jsonl" 2>/dev/null
exit 0
