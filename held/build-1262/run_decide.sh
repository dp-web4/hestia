#!/bin/bash
# The #1262 decide() contract against a main worktree with build_1262.py's neutral copies overlaid.
# argv: <main worktree> <build out dir> [gate copy to overlay instead of <out>/sg_rev.py]
# Run the worktree from under the shared checkout, not /tmp (a /tmp fixture is implicitly granted).
WT="$1"
OUT="$2"
GATE="${3:-$OUT/sg_rev.py}"
[ -d "$WT" ] && [ -d "$OUT" ] || { echo "usage: $0 <main worktree> <build out dir> [gate]" >&2; exit 2; }
cd "$WT" || exit 2
export HESTIA_CONTRACT_REPO="$WT"
export HESTIA_CONTRACT_OVERLAY="{\"hestia_single_gate\": \"$GATE\"}"
export HESTIA_CONTRACT_SHIMS="{\"kimi\": \"$OUT/km_shim.py\"}"
timeout 900 python3 "$OUT/decide_test.py" 2>&1 | tail -25
