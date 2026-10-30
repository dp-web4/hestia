"""Cut hestia #1331's follow-ups (globs/braces, a cd inside the line, readers that follow links) over the worktree's
HEAD core, read from git (never the working file). Replaces #1433's link_targets() with link_reach() (link_targets
keeps its name and contract) and adds the overflow refusal to egress_unsweepable_deny. Writes source-1331f.diff
beside this file for build_1331f.py. argv: <hestia worktree>"""
import difflib, pathlib, subprocess, sys

wt = pathlib.Path(sys.argv[1]).resolve()
here = pathlib.Path(__file__).resolve().parent
rel = "plugins/_shared/hestia_gate_core.py"
src = subprocess.check_output(["git", "show", f"HEAD:{rel}"], cwd=wt).decode()
new = src

start = new.index('def link_targets(event: "NormalizedEvent") -> list:')
end = new.index("\n\n\n", start) + 3
assert new[start:end].count("def ") == 1
new = new[:start] + (here / "new_block.py.txt").read_text() + new[end:]

old = "    bad = egress_unsweepable(event)\n    if not bad:\n        return None\n"
assert new.count(old) == 1
new = new.replace(old, (
    "    bad = egress_unsweepable(event)\n"
    "    if not bad:\n"
    "        # hestia #1331: a glob or link-following walk past its bound is refused unjudged, under the rule\n"
    "        # for a reach the gate cannot enumerate (the scope pass refuses past SCOPE_JUDGE_BUDGET the same way).\n"
    "        too_wide = link_reach(event)[1]\n"
    "        if too_wide:\n"
    "            return _deny(\"mrh.command.unenumerated\",\n"
    "                         f\"'{event.tool}': {too_wide}, so the gate cannot judge every link it reaches and it is \"\n"
    "                         f\"refused rather than judged in part: name the paths it needs\",\n"
    "                         target=UNENUMERATED_TARGET)\n"
    "        return None\n"))
for name in ("_fnmatch.fnmatchcase(", "_GLOB_CHARS.search(", "os.scandir(", "UNENUMERATED_TARGET"):
    assert name in new, name
diff = "".join(difflib.unified_diff(src.splitlines(True), new.splitlines(True), f"a/{rel}", f"b/{rel}"))
(here / "source-1331f.diff").write_text(f"diff --git a/{rel} b/{rel}\n" + diff)
print("source diff lines:", diff.count("\n"))
