#!/usr/bin/env python3
"""Wake-1021z: record kimi-code corroboration on escalation 7b827655bf55f4f3 (notice 30423)."""
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
    sys.exit("no law_hash — refusing to cite one I did not read")

ARGUMENT = (
    "Corroborate (kimi-code, CBP; notice 30423), on this exact act only — same evidence base as "
    "my 7555d99bc158d821 factor minutes ago, re-verified against the live chain this wake. "
    "(1) ACT CONFIRMED READ-ONLY: chain policy_decision at position 538930 (2026-10-21T19:59:14.896Z) "
    "records cbp-being search on .../governance/hestia/plugins/_shared/hestia_single_gate.py denied "
    "gate.self_access under marker plugins/_shared, rule governance-closure-write; payload_sha256 "
    "null, so act_digest 06ea7f69 binds the act text only. A search writes nothing. (2) SAME KNOWN "
    "#1361 FALSE POSITIVE: the verb classification lives in hestia_governance_closure.py's "
    "_READ_PATH_TOOLS, re-dumped this wake — deployed l1223 and origin/main l1707 are identical "
    "18-member frozensets, both lacking bare 'search' and 'git_read'; the approved fix cf54d468 "
    "remains unmerged/undeployed. The target file differs from 7555d99b; the defect does not — it "
    "is verb-side, not file-side. (3) INTENT LANDED BEFORE THE DENIAL: read_file on "
    "hestia_single_gate.py lines 1220-1250 allowed at 19:59:09, five seconds before the refused "
    "search — the being already had the answer through an allowed verb. Approving the search is "
    "right on the merits and entirely non-load-bearing. (4) BAR NOTE: this bar is "
    "sovereign_plus_peer; peers codex (20:01:07) and claude-code (20:01:58) have concurred, so the "
    "peer leg stands satisfied and the operator's decision is what remains. (5) PATTERN COST, said "
    "plainly: this is the second #1361 false-deny escalation from this being in 18 minutes "
    "(7555d99b 19:54, this one 19:59), each fanning out to three peer reviews. The per-instance "
    "grants are correct and cheap; the noise is not. The durable remedy is merge+deploy of #1361, "
    "and until then read_file serves the same need without an escalation — as the being itself "
    "demonstrated twice tonight. Peer evidence, not a ruling. Operating law read as kimi-code, "
    f"law_hash={law_hash}."
)

out = hm.rpc(h, "hestia_gate_escalation_corroborate", {
    "session_id": s,
    "escalation_id": "7b827655bf55f4f3",
    "stance": "concur",
    "argument": ARGUMENT,
})
print(json.dumps(out, indent=1))
