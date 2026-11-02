#!/bin/bash
: "${HESTIA_1314_REPO:?Set HESTIA_1314_REPO to the repository containing the historical base}"
scratch=$(python3 "$(dirname "$0")/scratch.py" --check) || exit 1
cd "$HESTIA_1314_REPO" || exit 1
overall=0
for c in rev held main; do
  echo "== core_$c"
  HESTIA_SCOPE_BATTERY_CORE="$scratch/core_$c.py" timeout 600 python3 "$scratch/battery_rev.py" > "$scratch/out_$c.txt" 2>&1
  rc=$?
  echo "exit $rc"
  if [ "$rc" -ne 0 ]; then overall=1; fi
  grep -E 'FAIL|passed|failed' "$scratch/out_$c.txt" | head -60 || true
done
exit "$overall"
