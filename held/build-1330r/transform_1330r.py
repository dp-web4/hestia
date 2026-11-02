"""Cut the #1330 revision (Nova, #1427 exact-head review): read the APPLIED core from git HEAD (never the
working file), replace the prose table and egress_command_text with new_block.py.txt, and write the
source diff the build consumes. argv: <hestia worktree>"""
import difflib, pathlib, subprocess, sys

wt = pathlib.Path(sys.argv[1]).resolve()
here = pathlib.Path(__file__).resolve().parent
rel = "plugins/_shared/hestia_gate_core.py"
src = subprocess.check_output(["git", "show", f"HEAD:{rel}"], cwd=wt).decode()
start = src.index("#: A value a program's own contract makes TEXT")
end_marker = '    return " ".join(kept)\n'
end = src.index(end_marker, start) + len(end_marker)
assert src.count("#: A value a program's own contract makes TEXT") == 1
assert src[start:end].count("def egress_command_text") == 1
new = src[:start] + (here / "new_block.py.txt").read_text() + src[end:]
diff = "".join(difflib.unified_diff(src.splitlines(True), new.splitlines(True), f"a/{rel}", f"b/{rel}"))
(here / "source-1330r.diff").write_text(f"diff --git a/{rel} b/{rel}\n" + diff)
print("source diff lines:", diff.count("\n"))
