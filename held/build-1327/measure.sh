#!/bin/bash
# Run the decide contract and the shell battery, both revised, against the patched core and main's core.
# argv: <hestia worktree at the base> <build_v3.py out dir>
WT=$(cd "${1:?worktree}" && pwd) || exit 1
D=$(cd "${2:?build out dir}" && pwd) || exit 1
cd "$WT" || exit 1
echo "== contract, patched core"
HESTIA_CONTRACT_REPO=$WT HESTIA_CONTRACT_OVERLAY="{\"hestia_gate_core\": \"$D/core_rev.py\"}" timeout 900 python3 $D/contract_rev.py 2>&1 | tail -6
echo "== contract, main core"
HESTIA_CONTRACT_REPO=$WT timeout 900 python3 $D/contract_rev.py 2>&1 | grep -E "FAIL|PASS|passed|failed" | tail -12
echo "== battery, patched core"
HESTIA_SCOPE_BATTERY_CORE=$D/core_rev.py timeout 900 python3 $D/battery_rev.py 2>&1 | tail -3
echo "== battery, main core"
HESTIA_SCOPE_BATTERY_CORE=$WT/plugins/_shared/hestia_gate_core.py timeout 900 python3 $D/battery_rev.py 2>&1 | tail -3
