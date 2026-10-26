#!/bin/bash
# The #1262 decide() contract against main's tree with the resolved gate and kimi shim overlaid.
# argv1 (optional): gate copy to overlay (default: the resolved one)
B=/tmp/claude-1000/-home-dp-ai-workspace/9261dc9a-1703-4964-9e72-a076bd468aca/scratchpad/b1262
GATE="${1:-$B/sg_rev.py}"
cd /home/dp/ai-workspace/hestia/scratchpad/s1262-base || exit 2
export HESTIA_CONTRACT_REPO=/home/dp/ai-workspace/hestia/scratchpad/s1262-base
export HESTIA_CONTRACT_OVERLAY="{\"hestia_single_gate\": \"$GATE\"}"
export HESTIA_CONTRACT_SHIMS="{\"kimi\": \"$B/km_shim.py\"}"
timeout 900 python3 "$B/decide_test.py" 2>&1 | tail -25
