#!/usr/bin/env python3
"""Wake-1022zb: verify terminal state of scope-0979143d386a and check what the
incidental scope-af7b884a1251 (opened by my denied `ls ~/.local/bin` probe) looks like."""
from __future__ import annotations

import json
import sys

sys.path.insert(0, "/home/dp/ai-workspace/hestia/tools")
from claude_daemon_client import call  # type: ignore


def show(request_id: str) -> None:
    try:
        st = call("hestia_scope_status", {"plugin_id": "kimi-code", "request_id": request_id})
    except Exception as e:  # noqa: BLE001
        print(f"{request_id}: ERROR {e}")
        return
    print(f"== {request_id} ==")
    print(json.dumps(st, indent=2)[:3000])


for rid in ("scope-0979143d386a", "scope-af7b884a1251", "scope-524d3bbb9c4c", "scope-a8e98dbea8d7"):
    show(rid)
