#!/usr/bin/env python3
"""Write source-1262.diff: each resolved neutral copy against main's blob. argv: <hestia worktree at main>"""
import difflib
import pathlib
import subprocess
import sys

WT = sys.argv[1]
HERE = pathlib.Path(__file__).resolve().parent
NAMES = {
    "plugins/_shared/hestia_single_gate.py": "sg",
    "plugins/claude-code/hooks/hooks.json": "cc_hooks",
    "plugins/codex/hooks/hooks.json": "cx_hooks",
    "plugins/gemini/hooks/hooks.json": "gm_hooks",
    "plugins/kimi/hooks/hooks.json": "km_hooks",
    "plugins/kimi/hooks/pre_tool_use.py": "km_pre",
    "plugins/gemini/tests/channel_contract_test.py": "gm_chan_test",
    "tools/one_gate_decide_contract_test.py": "decide_test",
}
out = []
for path, name in NAMES.items():
    a = subprocess.check_output(["git", "show", f"HEAD:{path}"], cwd=WT, text=True).splitlines(True)
    b = (HERE / f"{name}.resolved").read_text(encoding="utf-8").splitlines(True)
    if a != b:
        out.append(f"diff --git a/{path} b/{path}\n" + "".join(
            difflib.unified_diff(a, b, f"a/{path}", f"b/{path}", n=3)))
(HERE / "source-1262.diff").write_text("".join(out), encoding="utf-8")
print(len(out), "files")
