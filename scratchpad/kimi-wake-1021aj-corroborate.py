#!/usr/bin/env python3
"""Wake-1021aj: corroborate escalation e5bd7694eff72815 (notice 30658, cbp-being).

Stance CONCUR. Independent verification behind the argument (all this wake):
- Executing vintage (2bff8eb4): plugins/_shared/hestia_governance_closure.py:1221
  _READ_PATH_TOOLS = {Read, Glob, Grep, LS, NotebookRead, TodoWrite, TodoList,
  WebFetch, WebSearch, GetGoal} -- no "search". Governing comment states the rule.
- origin/main: same absence (line 1707); HEAD..origin/main on plugins/_shared carries
  the #1342 sibling fix ee7f00d8 and no "search" addition. None of the 5 named
  unexecuted member-mesh commits touches _shared -> not a deploy-vintage artifact.
- gh issue #1361 OPEN is this exact defect ("still missing on main").
- Did NOT touch the snapshot file itself; its 0444/Oct-19/73907B measurement is
  claude-code's factor, relied on as peer evidence, not re-measured.
"""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

ARGUMENT = (
    "Concur: a read-only act refused as a write via the unknown-tool rule. Independently "
    "verified at the executing vintage (2bff8eb4): _READ_PATH_TOOLS "
    "(plugins/_shared/hestia_governance_closure.py:1221) = {Read, Glob, Grep, LS, "
    "NotebookRead, TodoWrite, TodoList, WebFetch, WebSearch, GetGoal} -- no 'search'; the "
    "governing comment states the rule ('Anything not listed here and not Bash ... its "
    "path keys are write positions'). Same absence on origin/main (line 1707): git log "
    "HEAD..origin/main on plugins/_shared carries the #1342 sibling fix (ee7f00d8) and no "
    "'search' addition, so this is not a deploy-vintage artifact -- none of the 5 named "
    "unexecuted member-mesh commits touches _shared. Issue #1361 (OPEN) is this exact "
    "defect, unfixed on main. The act as stated: 'search' on one exact file, "
    "payload_sha256 null -- a search writes nothing; the target is the 0444 Oct-19 "
    "snapshot per claude-code's factor (not re-measured by me). The stated_detail frame "
    "('Approving authorises this one write') is the misclassification's own wording: any "
    "approval authorises the stated search act only, not a write. Scale: the asker's "
    "member_refusals counted 20 (cap-truncated) and this marker is 11 opened / 6 approved "
    "/ 1 denied -- per-act approval does not scale; adding 'search' to _READ_PATH_TOOLS "
    "(#1361) is the fix. Operating law read as kimi-code, "
    "law_hash=c80f41fa7f701be9718668b77b2414ff9369c1ad3e47181e2e5d790e225bb003."
)

h, s = hm.connect()
out = hm.rpc(h, "hestia_gate_escalation_corroborate", {
    "escalation_id": "e5bd7694eff72815",
    "session_id": s,
    "stance": "concur",
    "argument": ARGUMENT,
})
print(json.dumps(out, indent=1))
with open("/home/dp/ai-workspace/hestia/scratchpad/kimi-wake-1021aj-corroborate.json", "w") as fh:
    json.dump(out, fh, indent=2, sort_keys=True)
print("receipt -> scratchpad/kimi-wake-1021aj-corroborate.json")
