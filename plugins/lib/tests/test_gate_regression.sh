#!/usr/bin/env bash
# Shared Gate-1 regression suite for the kiro_cli + crush adapters.
#
# CBP's kc_gate_holes_repro.sh proves the eleven fail-opens are closed. This suite covers the
# other half, which is the half a hardening pass usually breaks: that the fix did NOT simply
# trade fail-open for over-block, that UNKNOWN-tool default-deny actually gates, and that the
# gate still fails CLOSED when its own foundations are missing.
#
# Every deny assertion here runs against an ALLOWING governor stub, so Gate-1 is the only thing
# that can deny - otherwise Gate-2 would deny everything and the tests would pass for the wrong
# reason. (That is the trap that made an earlier round's first cut of these tests worthless.)
#
# Run: bash plugins/lib/tests/test_gate_regression.sh
set -u
H="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"   # .../plugins
R="${TMPDIR:-/tmp}/hestia-gate-regression.$$"
trap 'rm -rf "$R"' EXIT

mkdir -p "$R/ws/web4/sub" "$R/ws/private-context" "$R/kiro-id" "$R/crush-id"
printf 'import sys\nsys.exit(0)\n' > "$R/stub_gov.py"          # ALLOWS -> isolates Gate-1
printf 'import sys\nsys.exit(2)\n' > "$R/deny_gov.py"          # DENIES -> proves Gate-2 is reached
printf '{"mrh":{"in_scope":["repo:web4"]}}\n' > "$R/kiro-id/identity.json"
printf '{"mrh":{"in_scope":["repo:web4"]}}\n' > "$R/crush-id/identity.json"

export HESTIA_WORKSPACE="$R/ws"
export HESTIA_SOCIETY_GATE="$R/stub_gov.py"
export HESTIA_KIRO_IDENTITY="$R/kiro-id/identity.json"
export HESTIA_CRUSH_IDENTITY="$R/crush-id/identity.json"
export HESTIA_KIRO_LAUNCH_CWD="$R/ws/web4"
export HESTIA_CRUSH_LAUNCH_CWD="$R/ws/web4"
export HESTIA_KIRO_GATE_MODE=enforce HESTIA_CRUSH_GATE_MODE=enforce

for g in kiro_cli crush; do
  [ -f "$H/$g/hooks/pre_tool_use.py" ] || { echo "FATAL: $H/$g/hooks/pre_tool_use.py missing"; exit 3; }
done

PASS=0; FAIL=0
run() {  # run <label> <gate> <expect deny|allow> <json>
  local label="$1" gate="$2" expect="$3" json="$4" out rc got
  out=$(printf '%s' "$json" | python3 "$H/$gate/hooks/pre_tool_use.py" 2>&1); rc=$?
  got=allow; [ "$rc" = 2 ] && got=deny
  if [ "$got" = "$expect" ]; then PASS=$((PASS+1)); printf '  ok   %-56s %s(rc=%s)\n' "$label" "$got" "$rc"
  else FAIL=$((FAIL+1)); printf '  FAIL %-56s got=%s want=%s (rc=%s)\n' "$label" "$got" "$expect" "$rc"
       printf '       %s\n' "$(printf '%s' "$out" | head -1)"; fi
}

echo "== NO-OVER-BLOCK: ordinary in-scope work must still pass =="
run "kiro fs_read in-scope"            kiro_cli allow '{"hook_event_name":"PreToolUse","tool_name":"fs_read","tool_input":{"path":"'"$R"'/ws/web4/a.txt"}}'
run "kiro fs_write nested in-scope"    kiro_cli allow '{"hook_event_name":"PreToolUse","tool_name":"fs_write","tool_input":{"path":"'"$R"'/ws/web4/sub/b.txt","command":"create"}}'
run "kiro execute_bash in-scope"       kiro_cli allow '{"hook_event_name":"PreToolUse","tool_name":"execute_bash","tool_input":{"command":"ls '"$R"'/ws/web4"}}'
run "kiro grep plain term (own repo)"  kiro_cli allow '{"hook_event_name":"PreToolUse","tool_name":"grep","tool_input":{"pattern":"credentials","path":"'"$R"'/ws/web4"}}'
run "kiro use_aws benign"              kiro_cli allow '{"hook_event_name":"PreToolUse","tool_name":"use_aws","tool_input":{"service_name":"s3","operation_name":"ListBuckets","region":"us-east-1"}}'
run "kiro MCP benign in-scope arg"     kiro_cli allow '{"hook_event_name":"PreToolUse","tool_name":"mcp_github_create_issue","tool_input":{"repo":"web4","body":"a normal issue body"}}'
run "crush view in-scope"              crush    allow '{"event":"PreToolUse","tool_name":"view","tool_input":{"file_path":"'"$R"'/ws/web4/a.txt"}}'
run "crush bash in-scope"              crush    allow '{"event":"PreToolUse","tool_name":"bash","tool_input":{"command":"ls '"$R"'/ws/web4"}}'
run "crush grep plain term (own repo)" crush    allow '{"event":"PreToolUse","tool_name":"grep","tool_input":{"pattern":"credentials","path":"'"$R"'/ws/web4"}}'
run "crush web_fetch benign url"       crush    allow '{"event":"PreToolUse","tool_name":"web_fetch","tool_input":{"url":"https://example.com/docs/guide.html"}}'
run "crush fetch benign url"           crush    allow '{"event":"PreToolUse","tool_name":"fetch","tool_input":{"url":"https://pkg.go.dev/net/http"}}'
run "crush web_search benign query"    crush    allow '{"event":"PreToolUse","tool_name":"web_search","tool_input":{"query":"golang http client timeout"}}'
run "crush lsp_hover (reader) in-scope" crush   allow '{"event":"PreToolUse","tool_name":"lsp_hover","tool_input":{"uri":"file://'"$R"'/ws/web4/a.go"}}'
run "crush lsp_rename in-scope"        crush    allow '{"event":"PreToolUse","tool_name":"lsp_rename","tool_input":{"uri":"file://'"$R"'/ws/web4/a.go","newName":"x"}}'
run "crush read_mcp_resource in-scope" crush    allow '{"event":"PreToolUse","tool_name":"read_mcp_resource","tool_input":{"mcpName":"x","uri":"file://'"$R"'/ws/web4/a.txt"}}'
echo "   ^ a benign URL must NOT be realpath-scoped (that would deny every fetch) and must NOT be"
echo "     command-scoped (a network endpoint is not a local repo path)"

echo
echo "== UNKNOWN-TOOL DEFAULT-DENY: a tool in no class is gated HARDEST, not least =="
run "kiro unknown tool, secret in a novel key"  kiro_cli deny '{"hook_event_name":"PreToolUse","tool_name":"kiro_teleport","tool_input":{"whatever":"/home/dp/.ssh/id_rsa"}}'
run "kiro unknown tool, oos repo in novel key"  kiro_cli deny '{"hook_event_name":"PreToolUse","tool_name":"kiro_teleport","tool_input":{"whatever":"'"$R"'/ws/private-context/x"}}'
run "crush unknown tool, secret in novel key"   crush    deny '{"event":"PreToolUse","tool_name":"crush_teleport","tool_input":{"whatever":"/home/dp/.ssh/id_rsa"}}'
run "crush unknown tool, oos repo in novel key" crush    deny '{"event":"PreToolUse","tool_name":"crush_teleport","tool_input":{"whatever":"'"$R"'/ws/private-context/x"}}'
run "kiro unknown tool, deeply nested secret"   kiro_cli deny '{"hook_event_name":"PreToolUse","tool_name":"kiro_teleport","tool_input":{"a":{"b":{"c":["/home/dp/.ssh/id_rsa"]}}}}'

echo
echo "== UNKNOWN + EGRESS + MCP must REACH the governor (Gate-2), not skip it =="
HESTIA_SOCIETY_GATE="$R/deny_gov.py" \
  run "kiro unknown tool meets a DENYING governor"  kiro_cli deny '{"hook_event_name":"PreToolUse","tool_name":"kiro_teleport","tool_input":{"x":"benign"}}'
HESTIA_SOCIETY_GATE="$R/deny_gov.py" \
  run "crush unknown tool meets a DENYING governor" crush    deny '{"event":"PreToolUse","tool_name":"crush_teleport","tool_input":{"x":"benign"}}'
HESTIA_SOCIETY_GATE="$R/deny_gov.py" \
  run "crush web_fetch meets a DENYING governor"    crush    deny '{"event":"PreToolUse","tool_name":"web_fetch","tool_input":{"url":"https://example.com/"}}'
HESTIA_SOCIETY_GATE="$R/deny_gov.py" \
  run "kiro fs_read (READ) still SKIPS the governor" kiro_cli allow '{"hook_event_name":"PreToolUse","tool_name":"fs_read","tool_input":{"path":"'"$R"'/ws/web4/a.txt"}}'
echo "   ^ the last one is the control: read-class is the only class allowed to skip Gate-2"

echo
echo "== ENVELOPE: an unrecognized event field must not silently disarm the gate =="
run "kiro accepts crush-style 'event' key"      kiro_cli deny '{"event":"PreToolUse","tool_name":"execute_bash","tool_input":{"command":"cat /home/dp/.ssh/id_rsa"}}'
run "crush accepts claude-style key"            crush    deny '{"hook_event_name":"PreToolUse","tool_name":"bash","tool_input":{"command":"cat /home/dp/.ssh/id_rsa"}}'
run "kiro gates an envelope with NO event key"  kiro_cli deny '{"tool_name":"execute_bash","tool_input":{"command":"cat /home/dp/.ssh/id_rsa"}}'
run "crush gates an envelope with NO event key" crush    deny '{"tool_name":"bash","tool_input":{"command":"cat /home/dp/.ssh/id_rsa"}}'
run "kiro ignores a genuine non-tool event"     kiro_cli allow '{"hook_event_name":"Stop"}'
run "crush ignores a genuine non-tool event"    crush    allow '{"event":"Stop"}'
echo "   ^ the last two are the control: a real non-PreToolUse event with no tool_name still exits 0"

echo
echo "== FAIL-CLOSED: a crashing or unfounded gate must DENY, never exit 1 =="
run "kiro non-string tool_name (crash path)"  kiro_cli deny '{"hook_event_name":"PreToolUse","tool_name":{"a":1},"tool_input":{"path":"'"$R"'/ws/private-context/x"}}'
run "crush non-string tool_name (crash path)" crush    deny '{"event":"PreToolUse","tool_name":{"a":1},"tool_input":{"file_path":"'"$R"'/ws/private-context/x"}}'
run "kiro unparseable stdin"                  kiro_cli deny 'not json at all'
run "crush unparseable stdin"                 crush    deny '{{{'

# The shared lib is now a hard dependency. An ImportError at module scope raises BEFORE the
# deny-on-exception wrapper exists, and an uncaught exception exits 1 = ALLOW on both engines.
echo "  -- with plugins/lib hidden (simulates a partial checkout) --"
LIBHIDE="$R/plugins"
mkdir -p "$LIBHIDE"
cp -r "$H/crush" "$H/kiro_cli" "$LIBHIDE/" 2>/dev/null
for g in kiro_cli crush; do
  ev=$([ "$g" = crush ] && echo event || echo hook_event_name)
  out=$(printf '{"%s":"PreToolUse","tool_name":"x","tool_input":{"path":"/etc/passwd"}}' "$ev" \
        | python3 "$LIBHIDE/$g/hooks/pre_tool_use.py" 2>&1); rc=$?
  if [ "$rc" = 2 ]; then PASS=$((PASS+1)); printf '  ok   %-56s deny(rc=2)\n' "$g with no plugins/lib"
  else FAIL=$((FAIL+1)); printf '  FAIL %-56s got rc=%s want 2 (exit 1 = ALLOW on this engine)\n' "$g with no plugins/lib" "$rc"; fi
done

# An unenumerable workspace used to disarm command-scope entirely: no repo could be found to be
# "out of scope", so command_in_scope() passed everything.
echo "  -- with a dead HESTIA_WORKSPACE --"
HESTIA_WORKSPACE="$R/does-not-exist" \
  run "kiro command-scope with a dead workspace" kiro_cli deny '{"hook_event_name":"PreToolUse","tool_name":"execute_bash","tool_input":{"command":"ls /anywhere"}}'
HESTIA_WORKSPACE="$R/does-not-exist" \
  run "crush command-scope with a dead workspace" crush   deny '{"event":"PreToolUse","tool_name":"bash","tool_input":{"command":"ls /anywhere"}}'

echo
echo "PASS=$PASS  FAIL=$FAIL"
[ "$FAIL" = 0 ] || exit 1
