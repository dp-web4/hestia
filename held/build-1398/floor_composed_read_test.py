#!/usr/bin/env python3
"""hestia #1398, held: a composed read is a read on the read-only floor.

Fails on main by design (the floor admits only READ_ONLY_PATH_TOOLS there); passes on the patched
core. Moves into tools/floor_read_only_test.py when the held patch is applied.

Run: python3 held/build-1398/floor_composed_read_test.py
"""
import pathlib
import sys

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "plugins" / "_shared").is_dir())
sys.path.insert(0, str(ROOT / "tools"))
from floor_read_only_test import _Workspace, _snapshot, _policy, _verdict, check  # noqa: E402


def test_a_composed_read_is_a_read_on_the_read_only_floor():
    """#1398 (dp's forum floor, 2026-10-25): a being's `search` of a read-only floor entry was
    refused while a narrowed `r` grant on the same path admitted it. The floor now admits every act
    whose mode need is exactly r -- and still refuses every writer."""
    with _Workspace() as ws:
        forum = ws + "/shared-context/forum"
        snap = _snapshot(ws, floor_read=[{"path": forum, "recursive": True}])
        prof, pol = _policy(snap)
        for tool in ("search", "git_read", "Read"):
            v = _verdict(prof, pol, ws, tool, path=forum + "/note.md")
            check(f"{tool}_admitted", not v.blocks, str(v))
        for tool in ("Write", "Edit", "write_note", "run", "git_clean"):
            v = _verdict(prof, pol, ws, tool, path=forum + "/note.md")
            check(f"{tool}_refused", v.blocks, str(v))



if __name__ == "__main__":
    test_a_composed_read_is_a_read_on_the_read_only_floor()
    print("OK — 1 test (8 verdicts)")
