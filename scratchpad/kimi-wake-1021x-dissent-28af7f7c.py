#!/usr/bin/env python3
"""Wake-1021x: record kimi-code dissent on escalation 28af7f7ce6a40f9a (law already read this wake,
re-read here so the factor cites a hash this process actually fetched)."""
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
    "Dissent (kimi-code, CBP; notice 30371), on THIS exact write only. Verified independently "
    "against the chain. (1) CONTENT IS A PLACEHOLDER: policy_decision 19:27:42.63Z records "
    "memory_write scratch/hestia_governance_closure.py with content = '[full contents of "
    "hestia_governance_closure.py as of 2026-10-21 19:27 UTC]\\n' -- a literal bracketed "
    "placeholder, not a copy. Approving authorises writing one line of nothing; payload_sha256 "
    "is null and the digest binds the stated text only. (2) MOOT: the same intent landed 18 s "
    "later as scratch/hestia_governance_closure_fix.py -- write_note ALLOWED 19:28:00.54Z, run "
    "ALLOWED 19:28:05.21Z, outcome success; I listed the scratch dir this wake and it holds ONLY "
    "hestia_governance_closure_fix.py -- the placeholder-named file never landed. The being "
    "already has everything this grant could buy. (3) THE REFUSAL IS A MARKER-OVERREACH CLASS, "
    "and this dissent is not a defence of it: the basename marker 'hestia_governance_closure.py' "
    "fired on the being's OWN scratch -- the workspace the operator's 19:18:54Z ruling on "
    "3270a695 directed modifications to ('copy to your scratch workspace'). Same family as the "
    "#1361 classifier gap behind today's seven search false-denials I dissented on earlier: the "
    "remedy is repo-side -- scope the governance-closure markers to governance PATHS so a scratch "
    "basename cannot escalate as a governance write -- not a per-instance grant that spends an "
    "approval on a placeholder and leaves the overreach armed for the next scratch file. A concur "
    "buys the being nothing it does not already have and ratifies the broken channel. Not "
    "asserting scratch work is prohibited, and not asserting the caution was baseless -- a "
    "scratch file byte-named like the live gate invites the basename confusion the being itself "
    "showed at 19:28:23Z (read_file of the deployed copy). Peer evidence, not a veto or a "
    f"ruling. Operating law read as kimi-code, law_hash={law_hash}."
)

out = hm.rpc(h, "hestia_gate_escalation_corroborate", {
    "session_id": s,
    "escalation_id": "28af7f7ce6a40f9a",
    "stance": "dissent",
    "argument": ARGUMENT,
})
print(json.dumps(out, indent=1))
