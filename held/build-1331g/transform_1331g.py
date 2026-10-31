"""Cut the #1435 fixes over the APPLIED core (git HEAD, never the working file). Two defects CI and the one-gate
contract found on the applied head 90b74740:

1. gate.internal_error on every single-gate act. hestia_single_gate._egress_precheck passes its GateEvent
   (tool_input, no command/paths) to core.egress_unsweepable_deny, which called link_reach, which read event.command:
   AttributeError, and the gate failed closed.
2. An out-of-scope glob lost its escalation. The overflow refusal sat in egress_unsweepable_deny (Gate 1a), BEFORE
   the scope pass, so `ls /etc/*` (more than 256 entries) was refused mrh.command.unenumerated instead of reaching
   the scope pass and escalating (tools/one_gate_decide_contract_test.py phantom-glob-still-escalates).

Fix: the overflow refusal moves out of egress_unsweepable_deny to just before evaluate's allow returns (the end, and
the unscoped early allow), so it bites only an act the gate would otherwise ALLOW, which is the only case it matters:
outside the grant the scope pass already refuses or escalates. link_reach also reads command/paths with getattr.
Writes source-1331g.diff beside this file. argv: <worktree>"""
import difflib, pathlib, subprocess, sys

wt = pathlib.Path(sys.argv[1]).resolve()
here = pathlib.Path(__file__).resolve().parent
rel = "plugins/_shared/hestia_gate_core.py"
src = subprocess.check_output(["git", "show", f"HEAD:{rel}"], cwd=wt).decode()
out = src


def swap(old, new, n=1):
    global out
    assert out.count(old) == n, (old[:70], out.count(old))
    out = out.replace(old, new)


# 1. getattr in link_reach
swap("    segs = _reach_segments(event.command) if event.command else []\n"
     "    words = [(w, False) for w in event.paths if isinstance(w, str) and w]\n",
     "    # getattr, as egress_blobs does: an event shape without command/paths (the single gate's GateEvent) must\n"
     "    # contribute nothing, never raise into gate.internal_error.\n"
     "    command = getattr(event, \"command\", None)\n"
     "    segs = _reach_segments(command) if command else []\n"
     "    words = [(w, False) for w in (getattr(event, \"paths\", None) or ()) if isinstance(w, str) and w]\n")

# 1a. the match cap: 256 refused an ordinary `ls dir/*` over a few hundred entries even under a trial grant, so the single
# gate (which re-evaluates with the would-be grant before escalating) found the act could never pass and did not
# escalate it (one_gate_decide_contract phantom-glob-still-escalates, `ls /etc/*`). The match cap only bounds the cheap
# per-match realpath; the WORK bound is LINK_GLOB_SCAN_LIMIT (10,000 entries read). 2,048 is a few ms.
swap("LINK_GLOB_LIMIT = 256          # paths a glob or brace may expand to, per act\n",
     "LINK_GLOB_LIMIT = 2048         # paths a glob or brace may expand to, per act (each a realpath: a few ms in all)\n")

# 1b. link_reach takes `within`: when given (the overflow check), a glob whose fixed base is neither inside a granted
# root nor contains one is not expanded, and a walk root outside the grants is not walked. link_targets (the innate
# secret sweep) passes nothing and sees everything, as before.
swap('def link_reach(event: "NormalizedEvent") -> tuple:\n',
     'def link_reach(event: "NormalizedEvent", within: Optional[tuple] = None) -> tuple:\n')
swap("    Not the Grep/Glob tools: whether they read through links is the host's, unmeasured. Never raises.\"\"\"\n"
     "    cwd = getattr(event, \"cwd\", None)\n",
     "    Not the Grep/Glob tools: whether they read through links is the host's, unmeasured. Never raises.\n"
     "    `within` (granted roots, absolute): when given, only reach rooted inside the grants is expanded or walked; the\n"
     "    overflow check passes it, so a pattern outside the grants is left to the scope pass and its escalation.\"\"\"\n"
     "    cwd = getattr(event, \"cwd\", None)\n")
swap("    def judge(p):\n"
     "        try:\n"
     "            if p in seen or not os.path.lexists(p):\n",
     "    roots_in = None if within is None else tuple(os.path.realpath(r).rstrip(\"/\") for r in within)\n"
     "\n"
     "    def counts(p):\n"
     "        \"\"\"Whether reach rooted at `p` is inside the grants (always, with no `within`).\"\"\"\n"
     "        if roots_in is None:\n"
     "            return True\n"
     "        rp = os.path.realpath(p).rstrip(\"/\") or \"/\"\n"
     "        return any(rp == r or rp.startswith(r + \"/\") or r.startswith(rp.rstrip(\"/\") + \"/\") for r in roots_in)\n"
     "\n"
     "    def judge(p):\n"
     "        try:\n"
     "            if p in seen or not os.path.lexists(p):\n")
swap("        _reach_words(words, resolve=resolve, judge=judge, budget=scan, matches=matches)\n"
     "        _reach_walks(segs, resolve=resolve, bases=bases, judge=judge, budget=walk)\n",
     "        _reach_words(words, resolve=resolve, judge=judge, budget=scan, matches=matches, counts=counts)\n"
     "        _reach_walks(segs, resolve=resolve, bases=bases, judge=judge, budget=walk, counts=counts)\n")
swap("def _reach_words(words, *, resolve, judge, budget, matches) -> None:\n",
     "def _reach_words(words, *, resolve, judge, budget, matches, counts=lambda p: True) -> None:\n")
swap("                    if expand and _GLOB_CHARS.search(pat):\n"
     "                        for h in _bounded_glob(os.path.abspath(full), budget, matches):\n",
     "                    if expand and _GLOB_CHARS.search(pat):\n"
     "                        absf = os.path.abspath(full)\n"
     "                        fixed = absf.split(\"/\")\n"
     "                        cut = next((i for i, c in enumerate(fixed) if _GLOB_CHARS.search(c)), len(fixed))\n"
     "                        if not counts(\"/\".join(fixed[:cut]) or \"/\"):\n"
     "                            continue        # a pattern outside the grants: the scope pass's, not ours\n"
     "                        for h in _bounded_glob(absf, budget, matches):\n")
swap("def _reach_walks(segs, *, resolve, bases, judge, budget) -> None:\n",
     "def _reach_walks(segs, *, resolve, bases, judge, budget, counts=lambda p: True) -> None:\n")
swap("        for root in roots:\n"
     "            for p in _bounded_walk(root, budget):\n",
     "        for root in roots:\n"
     "            if not counts(root):\n"
     "                continue                    # a walk outside the grants: the scope pass's, not ours\n"
     "            for p in _bounded_walk(root, budget):\n")

# 2a. the overflow refusal leaves egress_unsweepable_deny
swap("    bad = egress_unsweepable(event)\n"
     "    if not bad:\n"
     "        # hestia #1331: a glob or link-following walk past its bound is refused unjudged, under the rule\n"
     "        # for a reach the gate cannot enumerate (the scope pass refuses past SCOPE_JUDGE_BUDGET the same way).\n"
     "        too_wide = link_reach(event)[1]\n"
     "        if too_wide:\n"
     "            return _deny(\"mrh.command.unenumerated\",\n"
     "                         f\"'{event.tool}': {too_wide}, so the gate cannot judge every link it reaches and it is \"\n"
     "                         f\"refused rather than judged in part: name the paths it needs\",\n"
     "                         target=UNENUMERATED_TARGET)\n"
     "        return None\n",
     "    bad = egress_unsweepable(event)\n"
     "    if not bad:\n"
     "        return None\n")

# 2b. a helper, and the check before evaluate's allow returns
swap("def link_targets(event: \"NormalizedEvent\") -> list:\n",
     "def link_reach_too_wide(event: \"NormalizedEvent\", within: Optional[tuple] = None) -> Optional[\"Verdict\"]:\n"
     "    \"\"\"hestia #1331: an act whose glob or link-following walk passes its bound is refused unjudged, under the rule\n"
     "    for a reach the gate cannot enumerate (the scope pass refuses past SCOPE_JUDGE_BUDGET the same way). Called\n"
     "    only where evaluate is about to ALLOW: outside the grant the scope pass has already refused or escalated, and an\n"
     "    out-of-scope glob must keep its escalation (one_gate_decide_contract phantom-glob-still-escalates). `within`\n"
     "    is the granted roots: a pattern or walk rooted outside them is not counted (None = an unscoped policy).\"\"\"\n"
     "    too_wide = link_reach(event, within)[1]\n"
     "    if not too_wide:\n"
     "        return None\n"
     "    return _deny(\"mrh.command.unenumerated\",\n"
     "                 f\"'{event.tool}': {too_wide}, so the gate cannot judge every link it reaches and it is \"\n"
     "                 f\"refused rather than judged in part: name the paths it needs\",\n"
     "                 target=UNENUMERATED_TARGET)\n"
     "\n\n"
     "def link_targets(event: \"NormalizedEvent\") -> list:\n")
# (Not on the unscoped early allow: an unscoped policy means evaluate is not the layer enforcing scope there, and the
# single gate's own scope layer escalates AFTER evaluate returns: one_gate_decide_contract's `ls /etc/*` under a stub
# Policy() lost its escalation when this ran there. Unscoped acts still get the full innate link sweep in Gate 1a.)
end = ("                target=refused or \"\",\n"
       "            )\n"
       "\n"
       "    return ALLOW\n")
swap(end, end.replace("    return ALLOW\n",
     "    _repos, _roots = _scope_parts(scopes, ws)\n"
     "    _wsr = os.path.realpath(os.path.expanduser(ws)).rstrip(\"/\")\n"
     "    within = tuple(_roots) + tuple(os.path.join(_wsr, r) for r in _repos if r and r != AgentPolicy.UNSCOPED)\n"
     "    return link_reach_too_wide(event, within) or ALLOW\n"))

diff = "".join(difflib.unified_diff(src.splitlines(True), out.splitlines(True), f"a/{rel}", f"b/{rel}"))
(here / "source-1331g.diff").write_text(f"diff --git a/{rel} b/{rel}\n" + diff)
print("source diff lines:", diff.count("\n"))
