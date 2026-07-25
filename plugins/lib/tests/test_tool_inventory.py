#!/usr/bin/env python3
"""Drift tripwire: every upstream tool an adapter knows about must have an explicit class.

A shared enforcement lib cannot catch a tool the adapter never heard of. The CBP review of
2026-07-24 found five tools registered upstream in Crush (`web_fetch`, `web_search`,
`sourcegraph`, `read_mcp_resource`, `list_mcp_resources`) that were in no class table, had no
recognized argument key, and were therefore swept by nothing - they passed Gate-1 having been
examined for nothing. This test turns "upstream added a tool and nobody classified it" from a
silent exfil channel into a red test.

It asserts, for each adapter's tools.json:
  1. every listed name classifies to the class the inventory declares, and
  2. no listed name classifies as UNKNOWN.

It deliberately does NOT assert the inverse (that VOCAB lists nothing outside the inventory):
the vocab may carry defensive supersets, and an unlisted tool is safe anyway - UNKNOWN is the
strictest path, not the weakest.

Run: python3 plugins/lib/tests/test_tool_inventory.py
"""
import json
import os
import sys
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.abspath(os.path.join(HERE, ".."))
PLUGINS = os.path.abspath(os.path.join(LIB, ".."))
sys.path.insert(0, LIB)

import gate_core as gc  # noqa: E402

ADAPTERS = ("crush", "kiro_cli")


def load_vocab(adapter):
    """Import the adapter's gate module and hand back its VOCAB.

    The gate exits at import time if the shared lib is missing, so this doubles as a smoke test
    that the adapter still imports cleanly."""
    path = os.path.join(PLUGINS, adapter, "hooks", "pre_tool_use.py")
    spec = importlib.util.spec_from_file_location(f"{adapter}_gate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.VOCAB


def main():
    failures, checked = [], 0
    for adapter in ADAPTERS:
        inv_path = os.path.join(PLUGINS, adapter, "tools.json")
        if not os.path.exists(inv_path):
            failures.append(f"{adapter}: tools.json is missing - the drift tripwire is disarmed")
            continue
        with open(inv_path, encoding="utf-8") as fh:
            inv = json.load(fh)
        vocab = load_vocab(adapter)
        for entry in inv.get("tools", []):
            name, want = entry["name"], entry["class"]
            got = vocab.classify(name)
            checked += 1
            if got == gc.UNKNOWN:
                failures.append(
                    f"{adapter}: '{name}' is registered upstream but classified by NOTHING "
                    f"(expected '{want}'). Add it to the VOCAB table in "
                    f"plugins/{adapter}/hooks/pre_tool_use.py.")
            elif got != want:
                failures.append(
                    f"{adapter}: '{name}' classifies as '{got}' but the inventory declares "
                    f"'{want}'.")

    print(f"checked {checked} upstream tool names across {len(ADAPTERS)} adapters")
    if failures:
        print(f"\nFAIL ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS - every inventoried upstream tool has an explicit class")
    return 0


if __name__ == "__main__":
    sys.exit(main())
