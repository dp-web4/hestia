#!/usr/bin/env python3
"""Read the scope pointers behind this wake's notices (23772-23775) + the auto-opened one."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from chain_walk import ChainWalker, ChainError
from kimi_read_1013_batch import read_resource

URIS = [
    ("23772/23773", "hestia://scope/scope-c2df6074368c"),
    ("23774/23775", "hestia://scope/scope-ca0753cf780c"),
    ("auto-opened", "hestia://scope/scope-d13a6ac382da"),
]


def main() -> int:
    w = ChainWalker()
    out = {}
    for notice_id, uri in URIS:
        try:
            r = read_resource(w, uri)
            c = r.get("contents") if isinstance(r, dict) else None
            if c and isinstance(c, list) and "text" in c[0]:
                out[notice_id] = json.loads(c[0]["text"])
            else:
                out[notice_id] = r
        except ChainError as e:
            out[notice_id] = {"_chain_error": f"{e.code}: {e.message}"}
        except Exception as e:  # noqa: BLE001
            out[notice_id] = {"_exception": repr(e)}
    json.dump(out, sys.stdout, indent=1)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
