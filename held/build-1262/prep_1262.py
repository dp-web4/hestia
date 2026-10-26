#!/usr/bin/env python3
"""Three-way merge #1262's sources (base f785001, ours = kimi head, theirs = main) into neutral-named
copies in this directory, writing no governed path. argv: <hestia repo> <ours ref> <theirs ref>"""
import pathlib
import subprocess
import sys

REPO, OURS, THEIRS = sys.argv[1], sys.argv[2], sys.argv[3]
HERE = pathlib.Path(__file__).resolve().parent
BASE = subprocess.check_output(["git", "merge-base", OURS, THEIRS], cwd=REPO, text=True).strip()
FILES = {
    "plugins/_shared/hestia_single_gate.py": "sg",
    "plugins/claude-code/hooks/hooks.json": "cc_hooks",
    "plugins/codex/hooks/hooks.json": "cx_hooks",
    "plugins/gemini/hooks/hooks.json": "gm_hooks",
    "plugins/kimi/hooks/hooks.json": "km_hooks",
    "plugins/kimi/hooks/pre_tool_use.py": "km_pre",
    "plugins/gemini/tests/channel_contract_test.py": "gm_chan_test",
    "tools/one_gate_decide_contract_test.py": "decide_test",
}


def blob(ref, path):
    r = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=REPO, capture_output=True)
    return r.stdout if r.returncode == 0 else b""


print("base", BASE)
for path, name in FILES.items():
    parts = {}
    for tag, ref in (("base", BASE), ("ours", OURS), ("theirs", THEIRS)):
        p = HERE / f"{name}.{tag}"
        p.write_bytes(blob(ref, path))
        parts[tag] = p
    merged = subprocess.run(["git", "merge-file", "-p", "-L", "kimi", "-L", "base", "-L", "main",
                             str(parts["ours"]), str(parts["base"]), str(parts["theirs"])],
                            capture_output=True)
    (HERE / f"{name}.merged").write_bytes(merged.stdout)
    print(f"{name:14} conflicts={merged.returncode}  {path}")
