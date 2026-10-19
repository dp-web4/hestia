#!/usr/bin/env python3
"""A read is a read under every harness's name for it (#1342).

The closure classifier keys write positions off the tool NAME: a tool it does not list as a
reader has its path keys treated as write destinations. The gemini shim maps `read_file` and
friends to `Read` before the gate sees them, but a SAGE being's memory_read reaches the gate
as `read_file` unmapped. So a being reading `plugins/_shared/hestia_single_gate.py` was refused
as a governance WRITE and opened a sovereign_plus_peer escalation (eded0f439bee5c59,
2026-10-19), including on the read-only governance snapshot dp's directive invites members to
read.

Three lists name the same read tools: the closure's _READ_PATH_TOOLS, the witness magnitude
table (hestia_witness_core.magnitude_for, 0.2 = read) and the gemini shim's lineage map. They
had drifted; this test keeps them equal and pins the classification end to end.

Run: python3 tools/closure_read_tool_names_test.py
"""
import ast
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHARED = ROOT / "plugins" / "_shared"
sys.path.insert(0, str(SHARED))
import hestia_governance_closure as g  # noqa: E402
import hestia_witness_core as w  # noqa: E402

GATE_FILE = str(SHARED / "hestia_single_gate.py")
NEUTRAL_CWD = tempfile.mkdtemp(prefix="hgc-names-")


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {detail}")


def gemini_lineage_map() -> dict:
    """The gemini shim's `lineage_tool` dict literal, read from source (it is a local)."""
    tree = ast.parse((ROOT / "plugins" / "gemini" / "hooks" / "before_tool.py").read_text())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "lineage_tool"):
            return ast.literal_eval(node.value)
    raise AssertionError("lineage_tool not found in plugins/gemini/hooks/before_tool.py")


def test_a_being_read_of_a_gate_file_is_a_read():
    for key in ("path", "file_path"):
        v = g.classify("read_file", {key: GATE_FILE}, cwd=NEUTRAL_CWD)
        check(f"read_file_{key}_is_read", v.classification == "read", str(v))


def test_every_lowercase_reader_is_a_read():
    for tool in ("read_file", "read_many_files", "glob", "search_file_content",
                 "list_directory", "web_fetch", "google_web_search"):
        v = g.classify(tool, {"path": GATE_FILE}, cwd=NEUTRAL_CWD)
        check(f"{tool}_is_read", v.classification == "read", str(v))


def test_writers_and_unknown_tools_still_write():
    # Controls: the fix must not widen into the write names, and an unknown tool keeps the
    # conservative default (its path keys are destinations).
    for tool in ("Write", "Edit", "write_file", "replace", "some_new_tool"):
        v = g.classify(tool, {"file_path": GATE_FILE}, cwd=NEUTRAL_CWD)
        check(f"{tool}_is_write", v.classification == "write", str(v))


def test_gemini_readers_are_closure_readers():
    lineage = gemini_lineage_map()
    readers = {k for k, v in lineage.items() if v in g._READ_PATH_TOOLS}
    missing = sorted(readers - g._READ_PATH_TOOLS)
    check("gemini_readers_listed", not missing,
          f"gemini maps these to a read tool but the closure would class them as writes: {missing}")


def test_witness_read_names_are_closure_readers():
    lineage = gemini_lineage_map()
    names = set(lineage) | set(g._READ_PATH_TOOLS) | {"search_file_content", "list_directory"}
    witness_reads = {n for n in names if w.magnitude_for(n) == 0.2}
    missing = sorted(witness_reads - g._READ_PATH_TOOLS)
    check("witness_readers_listed", not missing,
          f"the witness scores these as reads but the closure would class them as writes: {missing}")


ALL = [
    test_a_being_read_of_a_gate_file_is_a_read,
    test_every_lowercase_reader_is_a_read,
    test_writers_and_unknown_tools_still_write,
    test_gemini_readers_are_closure_readers,
    test_witness_read_names_are_closure_readers,
]

if __name__ == "__main__":
    failed = []
    for t in ALL:
        try:
            t()
            print("PASS", t.__name__)
        except AssertionError as e:
            failed.append(t.__name__)
            print("FAIL", t.__name__, "::", e)
    if failed:
        print(f"FAILURES: {failed}")
        sys.exit(1)
    print(f"OK — {len(ALL)} tests")
