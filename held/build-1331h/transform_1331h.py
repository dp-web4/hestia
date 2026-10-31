"""Cut Nova's #1435 hold (exact-head review of 748469d2) over the applied core (git HEAD, never the working file).

Nova: link_targets discards link_reach's too_wide, and link_reach_too_wide ran only on evaluate's scoped success path.
Two other paths ALLOW after Gate 1a swept only the PARTIAL target list: evaluate's early allow for an authoritative
unscoped `*` policy, and degraded_verdict's READ / read-only-Bash allows. Both promise Gate 1a's innate secret check
is never relaxed. The innate too-wide condition now guards every path that can allow; only the scope-specific
refinement (`within`, the granted roots) stays after scope adjudication, so an out-of-scope pattern still reaches the
scope pass and escalates (phantom-glob-still-escalates).

(The unscoped guard was removed in 417465d5 on a wrong diagnosis: the `ls /etc/*` escalation it seemed to break was
the 256-match cap under the single gate's trial grant, fixed in the same cut by raising the cap to 2,048.)
Writes source-1331h.diff beside this file. argv: <worktree>"""
import difflib, pathlib, subprocess, sys

wt = pathlib.Path(sys.argv[1]).resolve()
here = pathlib.Path(__file__).resolve().parent
rel = "plugins/_shared/hestia_gate_core.py"
src = subprocess.check_output(["git", "show", f"HEAD:{rel}"], cwd=wt).decode()
out = src


def swap(old, new):
    global out
    assert out.count(old) == 1, (old[:70], out.count(old))
    out = out.replace(old, new)


# (b) the unscoped early allow: innate too-wide, everything counted (an unscoped policy reaches everything)
swap("    if pol.is_unscoped():\n"
     "        if not pol.stale:\n"
     "            return ALLOW\n",
     "    if pol.is_unscoped():\n"
     "        if not pol.stale:\n"
     "            # Gate 1a swept only what link_reach reached; past its bound the rest is unchecked, so an\n"
     "            # unscoped allow still refuses it (Nova's #1435 review: innate checks are never relaxed by scope).\n"
     "            return link_reach_too_wide(event) or ALLOW\n")

# (c) degraded_verdict's two allows
swap("    if event.tool in READ_CLASS:\n"
     "        return ALLOW\n"
     "    if event.tool.lower() in (\"bash\", \"shell\") and event.command \\\n",
     "    # Degraded mode allows reads, but never one whose links Gate 1a checked only in part (Nova's #1435 review).\n"
     "    too_wide = link_reach_too_wide(event)\n"
     "    if event.tool in READ_CLASS:\n"
     "        return too_wide or ALLOW\n"
     "    if event.tool.lower() in (\"bash\", \"shell\") and event.command \\\n")
swap("        # any write-redirect/substitution/unknown verb keeps the deny.\n"
     "        return ALLOW\n",
     "        # any write-redirect/substitution/unknown verb keeps the deny.\n"
     "        return too_wide or ALLOW\n")

# the helper's contract, said where it lives
swap("    \"\"\"hestia #1331: an act whose glob or link-following walk passes its bound is refused unjudged, under the rule\n"
     "    for a reach the gate cannot enumerate (the scope pass refuses past SCOPE_JUDGE_BUDGET the same way). Called\n"
     "    only where evaluate is about to ALLOW: outside the grant the scope pass has already refused or escalated, and an\n",
     "    \"\"\"hestia #1331: an act whose glob or link-following walk passes its bound is refused unjudged, under the rule\n"
     "    for a reach the gate cannot enumerate (the scope pass refuses past SCOPE_JUDGE_BUDGET the same way). Called\n"
     "    before EVERY allow (Nova's #1435 review): evaluate's final allow (with `within`), its unscoped early allow and\n"
     "    degraded_verdict's read allows (with none: no scope layer there to defer to). Outside the grant the scope pass\n"
     "    refuses or escalates first, and an\n")

diff = "".join(difflib.unified_diff(src.splitlines(True), out.splitlines(True), f"a/{rel}", f"b/{rel}"))
(here / "source-1331h.diff").write_text(f"diff --git a/{rel} b/{rel}\n" + diff)
print("source diff lines:", diff.count("\n"))
