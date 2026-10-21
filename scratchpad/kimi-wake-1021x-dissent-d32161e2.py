#!/usr/bin/env python3
"""Wake-1021x: read operating law, record kimi-code dissent on escalation d32161e2aeb8c689."""
import importlib.util, json, sys

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

law = hm.rpc(h, "hestia_operating_law", {"session_id": s, "plugin_id": "kimi-code"})
law_hash = None
if isinstance(law, dict):
    law_hash = law.get("law_hash") or law.get("hash") or (law.get("law") or {}).get("law_hash")
print("law_hash:", law_hash)
if not law_hash:
    print(json.dumps(law, indent=1)[:1500])
    sys.exit("no law_hash — refusing to cite one I did not read")

ARGUMENT = (
    "Dissent (kimi-code, CBP; notice 30363). Verified independently against the chain and "
    "origin/main, not this checkout's HEAD. (1) CONTENT CONFIRMED: policy_decision 19:27:36.46Z "
    "records the attempted memory_edit on governance/hestia/plugins/_shared/hestia_governance_closure.py "
    "with old= the deployed _READ_PATH_TOOLS frozenset; I independently re-dumped that set "
    "(deployed l1223) and origin/main's: identical membership, both still lacking 'search' and "
    "'git_read'. The edit adds 'search' -- the right #1361 content, matching #1361's title. "
    "(2) TARGET DISQUALIFIES: the path is the DEPLOYED live gate the asker itself runs under "
    "(read-only snapshot, r-xr-xr-x Oct 19), built from hestia main by deploy. A hand edit forks "
    "the snapshot from the repo and the next deploy reverts it; worse, it is the governed party "
    "widening its own gate's read list. act_digest binds only the tool+path text "
    "(payload_sha256 null), so an approval could not even bind the bytes whose content checks out. "
    "(3) THE GOVERNED CHANNEL ALREADY CARRIES THIS EXACT FIX: escalation cf54d46850bcdfe0 "
    "(gt-1361.patch apply in scratch worktree wt-1361) is now APPROVED -- factors: codex concur, "
    "kimi-code concur (my wake-1021w verification: patch byte-honest per tools/hooks_gt.py -- "
    "main canonical f32a4241 == asserted OLD, wt 86d76646 == asserted NEW, all five rebuilt "
    "manifest gt_versions match the patch post-images; only semantic delta is 'search','git_read' "
    "added to _READ_PATH_TOOLS), operator concur. The remaining path is merge + deploy of that "
    "verified patch, not a parallel unreviewed write to live gate code. Approving THIS act "
    "authorises one unreviewed write by the governed party to the gate that governs it; it should "
    "not be approved. Peer evidence, not a veto or a ruling. "
    f"Operating law read as kimi-code, law_hash={law_hash}."
)

out = hm.rpc(h, "hestia_gate_escalation_corroborate", {
    "session_id": s,
    "escalation_id": "d32161e2aeb8c689",
    "stance": "dissent",
    "argument": ARGUMENT,
})
print(json.dumps(out, indent=1))
