#!/usr/bin/env python3
"""Seed = hash of the OLDEST chain entry whose timestamp >= T (the first entry at/after T).
T is published before it arrives, so nobody can choose the seed.
Usage: python3 tools/blind_coreview_beacon.py 2026-09-25T05:10:00"""
import sys
sys.path.insert(0, sys.path[0])
from chain_walk import ChainWalker
T = sys.argv[1]; best = None
for e in ChainWalker(timeout=60).walk(max_entries=10**7):
    if e["timestamp"] < T:
        break
    best = e
print(best["hash"], best["timestamp"], best["chainPosition"])
