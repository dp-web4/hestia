#!/bin/bash
cd /home/dp/ai-workspace/hestia || exit 1
for c in rev held main; do
  echo "== core_$c"
  HESTIA_SCOPE_BATTERY_CORE=/tmp/s1314e/core_$c.py timeout 600 python3 /tmp/s1314e/battery_rev.py > /tmp/s1314e/out_$c.txt 2>&1
  grep -E 'FAIL|passed|failed' /tmp/s1314e/out_$c.txt | head -60
done
