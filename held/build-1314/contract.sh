#!/bin/bash
: "${HESTIA_1314_BASE:?Set HESTIA_1314_BASE to the separate historical base checkout}"
scratch=$(python3 "$(dirname "$0")/scratch.py" --check) || exit 1
overlay=$(python3 -c 'import json,sys; print(json.dumps({"hestia_gate_core":sys.argv[1]}))' "$scratch/core_rev.py") || exit 1
cd "$HESTIA_1314_BASE" || exit 1
base_root=$(git rev-parse --show-toplevel) || exit 1
head=$(git rev-parse --verify HEAD) || exit 1
base=$(git rev-parse --verify '2d79644f^{commit}') || exit 1
status=$(git status --porcelain --untracked-files=normal) || exit 1
if [ "$head" != "$base" ] || [ -n "$status" ]; then
  echo "Historical base checkout must be clean and at the required commit" >&2
  exit 1
fi
HESTIA_CONTRACT_REPO="$base_root" \
HESTIA_CONTRACT_OVERLAY="$overlay" \
timeout 900 python3 "$scratch/contract_held.py" > "$scratch/contract_out.txt" 2>&1
rc=$?
echo "exit $rc"
tail -5 "$scratch/contract_out.txt"
exit "$rc"
