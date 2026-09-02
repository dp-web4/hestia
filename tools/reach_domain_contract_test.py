#!/usr/bin/env python3
"""The reach domain is a (tool, key) CONTRACT, and this is the instrument that can go red on it.

GPT's review of #830 falsified the flat census in two moves:

  1. The delegation check grepped for `_core.path_targets(` anywhere. A seat-local 3-key
     extractor on the real scope path plus one dead engine call elsewhere read as fully
     delegated, CI green.
  2. `engine_reach_keys` flattened the typed table to bare names and added "pattern"
     unconditionally. Delete "glob" from PATTERN_REACH_TOOLS -- the exact semantic this
     slice exists for -- and the 10/10 census stays green.

Three arms, each with the sabotage that proves it can fail:

  A  TYPED ENGINE CONTRACT   core.path_targets: Glob.pattern is reach; Grep and
                             search_file_content .pattern are NOT; include/exclude/paths
                             lists and strings; absolute_path/dir_path/notebook_path; and a
                             self-check that empties PATTERN_REACH_TOOLS and requires the
                             Glob arm to go red.
  B  LIVE SITE, NOT SUBSTRING  live_site_delegates() on every shipped seat, plus the exact
                             counterexample GPT named (dead engine call + local extractor
                             on the live path) must read NOT delegated.
  C  BEHAVIOUR ACROSS SEATS  through sprintF's stub-daemon harness: an out-of-scope Glob
                             pattern is DENIED on every seat, an out-of-scope Grep pattern
                             is NOT denied for scope, an out-of-scope include list is denied.
                             This is the arm no static reading can fake.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "plugins" / "_shared"))
import hestia_gate_core as core                     # noqa: E402
import path_key_vocabulary_probe as probe           # noqa: E402

FAILURES: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("ok  : " if ok else "FAIL: ") + msg)
    if not ok:
        FAILURES.append(msg)


def teardown_module(module=None) -> None:
    assert not FAILURES, FAILURES


# ── A: the typed contract ─────────────────────────────────────────────────────────────
def typed_contract(mod) -> list[str]:
    """Returns the list of violated clauses against `mod` (the core, or a sabotaged copy)."""
    bad = []
    pt = mod.path_targets
    if pt("Glob", {"pattern": "/etc/**", "path": "/w"}) != ["/w", "/etc/**"]:
        bad.append("Glob.pattern is reach (with its path)")
    if pt("glob", {"pattern": "/etc/**"}) != ["/etc/**"]:
        bad.append("glob.pattern is reach (gemini spelling)")
    if pt("Grep", {"pattern": "/etc/**", "path": "/w"}) != ["/w"]:
        bad.append("Grep.pattern is a regex, NOT reach")
    if pt("search_file_content", {"pattern": "secret", "dir_path": "/w"}) != ["/w"]:
        bad.append("search_file_content.pattern is a regex, NOT reach")
    if pt("read_many_files", {"include": ["a/**", "b"], "exclude": "c"}) != ["a/**", "b", "c"]:
        bad.append("include/exclude: list and str globs are reach")
    if pt("x", {"paths": ["/p", 3, ""], "file_paths": "/q"}) != ["/p", "/q"]:
        bad.append("paths/file_paths lists: strings only, blanks dropped")
    if pt("read_file", {"absolute_path": "/a", "notebook_path": "/n", "dir_path": "/d"}) != ["/a", "/n", "/d"]:
        bad.append("absolute_path/notebook_path/dir_path are reach")
    if pt("Write", "not-a-dict") != [] or pt(None, {"pattern": "/x"}) != []:
        bad.append("non-dict input and non-string tool name yield nothing")
    return bad


def test_typed_contract_holds_and_can_fail() -> None:
    bad = typed_contract(core)
    check(not bad, f"[A] typed contract on the shipped core: {bad or 'all clauses hold'}")
    # Sabotage: a copy of the core with the Glob/Grep qualification deleted must FAIL here.
    src = (REPO / "plugins" / "_shared" / "hestia_gate_core.py").read_text(encoding="utf-8")
    assert 'PATTERN_REACH_TOOLS = ("glob",)' in src
    sab = src.replace('PATTERN_REACH_TOOLS = ("glob",)', "PATTERN_REACH_TOOLS = ()", 1)
    with tempfile.TemporaryDirectory() as raw:
        p = Path(raw) / "sabotaged_core.py"
        p.write_text(sab, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("sabotaged_core", p)
        m = importlib.util.module_from_spec(spec)
        sys.modules["sabotaged_core"] = m          # dataclasses resolve cls.__module__
        try:
            spec.loader.exec_module(m)
            bad = typed_contract(m)
        finally:
            sys.modules.pop("sabotaged_core", None)
    check(any("Glob" in b or "glob" in b for b in bad),
          f"[A] emptying PATTERN_REACH_TOOLS turns the Glob clauses RED: {bad}")


# ── B: the live site, not a substring ─────────────────────────────────────────────────
SEATS = {
    "claude-code": REPO / "plugins" / "claude-code" / "hooks" / "pre_tool_use.py",
    "codex": REPO / "plugins" / "codex" / "hooks" / "pre_tool_use.py",
    "kimi": REPO / "plugins" / "kimi" / "hooks" / "pre_tool_use.py",
    "gemini": REPO / "plugins" / "gemini" / "hooks" / "before_tool.py",
}


def test_live_site_delegation_proven_per_seat() -> None:
    for seat, path in SEATS.items():
        check(probe.live_site_delegates(path), f"[B] {seat}: the live scope-extraction site IS the engine call")
    # GPT's counterexample: a dead engine call somewhere, and a local 3-key extractor on the
    # live path. The old substring check blessed this; the site rule must not.
    fake = '''
import os
_core = None
def _path_targets(ti):
    return [ti[k] for k in ("file_path", "path", "notebook_path") if isinstance(ti.get(k), str)]
def unrelated():
    return _core.path_targets("Read", {})    # dead: never feeds scope
def main():
    tinput = {}
    paths = _path_targets(tinput)            # the LIVE site re-forked
    return paths
'''
    with tempfile.TemporaryDirectory() as raw:
        p = Path(raw) / "fake_seat.py"
        p.write_text(fake, encoding="utf-8")
        check(not probe.live_site_delegates(p),
              "[B] dead engine call + local extractor on the live path reads NOT delegated")
        # and the mirror: a clean delegate reads delegated
        p.write_text('''
_core = None
def main():
    tinput = {}
    paths = _core.path_targets("Read", tinput)
    return paths
''', encoding="utf-8")
        check(probe.live_site_delegates(p), "[B] a clean live-site delegate reads delegated")
        # codex's shape: a pure harness-shape translator composed WITH the engine call
        p.write_text('''
import re
_core = None
def patch_targets(ti):
    blob = ti.get("input") or ""
    return re.findall(r"^\\*\\*\\* Add File: (.+)$", blob, re.M)
def main():
    tool, tinput = "apply_patch", {}
    paths = patch_targets(tinput) + _core.path_targets(tool, tinput)
    return paths
''', encoding="utf-8")
        check(probe.live_site_delegates(p),
              "[B] a pure shape-translator composed with the engine call reads delegated")
        # the same translator smuggling a key list is a second domain -- GPT's falsifier in
        # its subtler form (this was codex's apply_patch_targets before this commit)
        p.write_text('''
import re
_core = None
def patch_targets(ti):
    out = re.findall(r"^\\*\\*\\* Add File: (.+)$", ti.get("input") or "", re.M)
    for k in ("path", "file_path"):
        if isinstance(ti.get(k), str):
            out.append(ti[k])
    return out
def main():
    tool, tinput = "apply_patch", {}
    paths = patch_targets(tinput) + _core.path_targets(tool, tinput)
    return paths
''', encoding="utf-8")
        check(not probe.live_site_delegates(p),
              "[B] a translator that spells path keys reads NOT delegated (a second domain)")


# ── C: behaviour through the seats, stub daemon ───────────────────────────────────────
def test_behaviour_across_seats() -> None:
    spec = importlib.util.spec_from_file_location(
        "sprintF", REPO / "plugins" / "_shared" / "sprintF_test.py")
    sf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sf)
    tmp, ws = sf.make_workspace()
    stub = sf.StubDaemon()
    srv = sf.Server(stub)
    try:
        rows = [
            ("glob-pattern-oos", "Glob",
             {"pattern": f"{ws}/notgranted/**", "path": f"{ws}/granted"}, True),
            ("grep-pattern-oos-is-regex", "Grep",
             {"pattern": f"{ws}/notgranted/**", "path": f"{ws}/granted"}, False),
            ("include-list-oos", "read_many_files",
             {"include": [f"{ws}/notgranted/**"]}, True),
            ("absolute-path-oos", "read_file",
             {"absolute_path": f"{ws}/notgranted/x"}, True),
        ]
        for name, tool, tinput, want_deny in rows:
            for shim in ("claude", "kimi", "codex"):
                rc, err = sf.run_hook(shim, ws, sf._event(tool, tinput), srv.endpoint)
                scope_denied = rc == 2 and "notgranted" in err
                if want_deny:
                    check(scope_denied, f"[C] {name} {shim}: DENIED for scope (rc={rc}) {err[:100]!r}")
                else:
                    check(not scope_denied, f"[C] {name} {shim}: NOT denied for scope (rc={rc}) {err[:100]!r}")
    finally:
        srv.close()
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_typed_contract_holds_and_can_fail()
    test_live_site_delegation_proven_per_seat()
    test_behaviour_across_seats()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}", file=sys.stderr)
        sys.exit(1)
    print("ok: the (tool, key) reach contract holds, at the live site, on every seat, and can go red")
