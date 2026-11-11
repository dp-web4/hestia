#!/bin/bash
# The gate suites that read the core, each against the patched core (core_rev.py) and main's core.
# argv: <hestia worktree at the base> <build.py out dir>
WT=$(cd "${1:?worktree}" && pwd) || exit 1
D=$(cd "${2:?build out dir}" && pwd) || exit 1
cd "$WT" || exit 1
for which in patched main; do
  if [ "$which" = patched ]; then C=$D/core_rev.py; else C=$WT/plugins/_shared/hestia_gate_core.py; fi
  echo "===== $which core"
  echo "== new: gate_false_deny_test"
  if [ "$which" = patched ]; then python3 "$WT/held/build-1494/gate_false_deny_rows.py" "$D" | tail -1
  else python3 "$WT/held/build-1494/gate_false_deny_rows.py" /nonexistent | tail -1; fi
  echo "== decide contract"
  if [ "$which" = patched ]; then
    HESTIA_CONTRACT_REPO=$WT HESTIA_CONTRACT_OVERLAY="{\"hestia_gate_core\": \"$C\"}" timeout 900 python3 tools/one_gate_decide_contract_test.py 2>&1 | tail -2
  else
    HESTIA_CONTRACT_REPO=$WT timeout 900 python3 tools/one_gate_decide_contract_test.py 2>&1 | tail -2
  fi
  echo "== shell battery"
  HESTIA_SCOPE_BATTERY_CORE=$C timeout 900 python3 tools/shell_scope_reach_battery_test.py 2>&1 | tail -1
  echo "== egress prose"
  if [ "$which" = patched ]; then python3 tools/egress_prose_test.py "$D" | tail -1; else python3 tools/egress_prose_test.py | tail -1; fi
done
