#!/usr/bin/env python3
"""Wake-1026e: bind the three review_request notices to the witness chain.

Each notice carries chain_hash; it must resolve to a scope_requested event
whose content names the same request_id/act as the pending petition.
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, "/home/dp/ai-workspace/hestia/scratchpad")
import importlib.util

spec = importlib.util.spec_from_file_location(
    "kct", "/home/dp/ai-workspace/hestia/scratchpad/kimi-chain-tool.py")
kct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kct)

PAIRS = [
    (33244, "scope-dc543677cd8f", "72d4e8594846e4a2a44b155e52a3718c16875fc11078de744e10d65dc8e3ea4d"),
    (33247, "scope-4ad0d35d6d1c", "8a2a661d25eafc5167c736b43e03d186c583ed384324e51af8206854eeeedc31"),
    (33250, "scope-6e04f8018a7f", "5e2ffb6b850607e3c7e07ae18ae0ab6927fa7ff2914ec18733c7f73356cc1d12"),
]

h = kct.connect()
for nid, rid, chash in PAIRS:
    out = kct.rpc(h, "hestia_query_history", {"filter": {"hash": chash}})
    rows = out if isinstance(out, list) else out.get("events", out.get("rows", out))
    print(f"### notice {nid} -> {rid}")
    print(json.dumps(rows, indent=1, default=str)[:2500])
    print()
