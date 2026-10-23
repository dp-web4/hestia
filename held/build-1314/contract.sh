#!/bin/bash
cd /home/dp/ai-workspace/hestia/scratchpad/s1314e-base || exit 1
HESTIA_CONTRACT_REPO=/home/dp/ai-workspace/hestia/scratchpad/s1314e-base \
HESTIA_CONTRACT_OVERLAY='{"hestia_gate_core": "/tmp/s1314e/core_rev.py"}' \
timeout 900 python3 /tmp/s1314e/contract_held.py > /tmp/s1314e/contract_out.txt 2>&1
echo "exit $?"
tail -5 /tmp/s1314e/contract_out.txt
