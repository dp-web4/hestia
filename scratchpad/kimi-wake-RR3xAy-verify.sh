#!/usr/bin/env bash
# kimi wake RR3xAy: independent verification for escalation bd5857e71648dc11
# (patch e0cceeaf9546e5b323b7035645d7b092c05563837c802a197882a5d569bf66fe, hestia#1327 v3).
# Read-only on the repo: all writes go to /tmp/kimi-1327-verify.
set -u
WT=/home/dp/ai-workspace/hestia/scratchpad/wt-1327-v3
PATCH=$WT/held/e0cceeaf9546e5b323b7035645d7b092c05563837c802a197882a5d569bf66fe.patch
SCRATCH=/tmp/kimi-1327-verify

echo "== 1. patch sha256 (expect filename) =="
sha256sum "$PATCH"

echo "== 2. git apply --check + stat against worktree HEAD bytes =="
git -C "$WT" apply --check "$PATCH" && echo APPLY_CHECK_CLEAN
git -C "$WT" apply --stat "$PATCH" | tail -12

echo "== 3. scratch apply (plain dir, p1) =="
rm -rf "$SCRATCH"
mkdir -p "$SCRATCH/plugins/_shared" "$SCRATCH/hooks-gt/_shared" "$SCRATCH/hooks-gt/claude-code" \
         "$SCRATCH/hooks-gt/codex" "$SCRATCH/hooks-gt/gemini" "$SCRATCH/hooks-gt/kimi" "$SCRATCH/tools"
cp "$WT/plugins/_shared/hestia_gate_core.py"            "$SCRATCH/plugins/_shared/hestia_gate_core.py"
cp "$WT/hooks-gt/_shared/hestia_gate_core.py"           "$SCRATCH/hooks-gt/_shared/hestia_gate_core.py"
cp "$WT/hooks-gt/_shared/manifest.json"                 "$SCRATCH/hooks-gt/_shared/manifest.json"
cp "$WT/hooks-gt/claude-code/manifest.json"             "$SCRATCH/hooks-gt/claude-code/manifest.json"
cp "$WT/hooks-gt/codex/manifest.json"                   "$SCRATCH/hooks-gt/codex/manifest.json"
cp "$WT/hooks-gt/gemini/manifest.json"                  "$SCRATCH/hooks-gt/gemini/manifest.json"
cp "$WT/hooks-gt/kimi/manifest.json"                    "$SCRATCH/hooks-gt/kimi/manifest.json"
cp "$WT/tools/one_gate_decide_contract_test.py"         "$SCRATCH/tools/one_gate_decide_contract_test.py"
cp "$WT/tools/shell_scope_reach_battery_test.py"        "$SCRATCH/tools/shell_scope_reach_battery_test.py"
(cd "$SCRATCH" && git apply "$PATCH" && echo SCRATCH_APPLY_OK)

echo "== 4. GT hash (expect 127d414a...) + GT-minus-header == core =="
sha256sum "$SCRATCH/hooks-gt/_shared/hestia_gate_core.py"
diff <(sed '2d' "$SCRATCH/hooks-gt/_shared/hestia_gate_core.py") \
     "$SCRATCH/plugins/_shared/hestia_gate_core.py" && echo GT_MINUS_HEADER_EQUALS_CORE

echo "== 5. py_compile patched files =="
python3 -m py_compile "$SCRATCH/plugins/_shared/hestia_gate_core.py" \
  "$SCRATCH/hooks-gt/_shared/hestia_gate_core.py" \
  "$SCRATCH/tools/one_gate_decide_contract_test.py" \
  "$SCRATCH/tools/shell_scope_reach_battery_test.py" && echo PY_COMPILE_OK

echo "== 6. rule occurrences in patched core =="
grep -n "mrh.command.nonexistent" "$SCRATCH/plugins/_shared/hestia_gate_core.py"

echo "== 7. contract test, patched core overlay (expect all pass) =="
HESTIA_CONTRACT_REPO=$WT \
HESTIA_CONTRACT_OVERLAY="{\"hestia_gate_core\": \"$SCRATCH/plugins/_shared/hestia_gate_core.py\"}" \
python3 "$SCRATCH/tools/one_gate_decide_contract_test.py" 2>&1 | tail -8

echo "== 8. contract test, MAIN core (expect exactly the new phantom row's checks fail) =="
HESTIA_CONTRACT_REPO=$WT \
python3 "$SCRATCH/tools/one_gate_decide_contract_test.py" 2>&1 | tail -12

echo "== 9. battery, patched core, worktree battery file =="
HESTIA_SCOPE_BATTERY_CORE="$SCRATCH/plugins/_shared/hestia_gate_core.py" \
python3 "$WT/tools/shell_scope_reach_battery_test.py" 2>&1 | tail -4

echo "== 10. battery, patched core, patched battery file =="
HESTIA_SCOPE_BATTERY_CORE="$SCRATCH/plugins/_shared/hestia_gate_core.py" \
python3 "$SCRATCH/tools/shell_scope_reach_battery_test.py" 2>&1 | tail -4

echo "== DONE =="
