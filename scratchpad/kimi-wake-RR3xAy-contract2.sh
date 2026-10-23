#!/usr/bin/env bash
# Rerun of the decide contract from cwd=$WT so launch_cwd_repo grants 'hestia' (author conditions).
# Full failure-name lists, no tail truncation.
set -u
WT=/home/dp/ai-workspace/hestia/scratchpad/wt-1327-v3
SCRATCH=/tmp/kimi-1327-verify
cd "$WT"

echo "== A. patched core overlay, cwd=$WT =="
HESTIA_CONTRACT_REPO=$WT \
HESTIA_CONTRACT_OVERLAY="{\"hestia_gate_core\": \"$SCRATCH/plugins/_shared/hestia_gate_core.py\"}" \
python3 "$SCRATCH/tools/one_gate_decide_contract_test.py" > /tmp/kimi-1327-verify/contract-patched.log 2>&1
echo "rc=$?"
grep -c "^  - " /tmp/kimi-1327-verify/contract-patched.log | sed 's/^/FAIL_COUNT=/'
grep "^  - " /tmp/kimi-1327-verify/contract-patched.log | sed 's/^\(  - [a-zA-Z0-9_-]*\).*/\1/' | sort | uniq -c
tail -2 /tmp/kimi-1327-verify/contract-patched.log

echo "== B. main core, cwd=$WT (expect exactly the 6 phantom checks) =="
HESTIA_CONTRACT_REPO=$WT \
python3 "$SCRATCH/tools/one_gate_decide_contract_test.py" > /tmp/kimi-1327-verify/contract-main.log 2>&1
echo "rc=$?"
grep -c "^  - " /tmp/kimi-1327-verify/contract-main.log | sed 's/^/FAIL_COUNT=/'
grep "^  - " /tmp/kimi-1327-verify/contract-main.log | sed 's/^\(  - [a-zA-Z0-9_-]*\).*/\1/' | sort | uniq -c
tail -2 /tmp/kimi-1327-verify/contract-main.log

echo "== DONE =="
