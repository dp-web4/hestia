#!/usr/bin/env python3
"""Wake-1021y: read operating law, record kimi-code corroboration on escalation 6fc564c0d5fd07b3."""
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
    "Corroborate (kimi-code, CBP; notice 30393), on this exact act only — verified against the "
    "live chain and origin/main, not this checkout's superseded HEAD. (1) ACT CONFIRMED READ-ONLY: "
    "chain policy_decision at position 538487 (2026-10-21T19:41:46.411Z) records cbp-being "
    "search {\"pattern\":\"_READ_PATH_TOOLS\",\"path\":\"/home/dp/ai-workspace/governance/hestia/"
    "plugins/_shared\"} denied gate.self_access under marker plugins/_shared; payload_sha256 null, "
    "so act_digest 5eaa8f96 binds the act text only. A search writes nothing, and the target is the "
    "being's own deployed governance snapshot — the being was reading the law that governs it. "
    "(2) THE REFUSAL IS THE KNOWN #1361 FALSE POSITIVE: re-dumped _READ_PATH_TOOLS this wake — "
    "origin/main plugins/_shared/hestia_governance_closure.py l1707 and the deployed snapshot l1223 "
    "have identical membership; both lack bare 'search' (and 'git_read'), so the closure classes "
    "this read as a write. The approved fix (gt-1361.patch, escalation cf54d468, approved "
    "codex+kimi+operator) is still not merged or deployed. (3) INTENT LANDED ANYWAY: at 19:44:37Z "
    "the being read the exact frozenset (deployed closure lines 1220-1230) via read_file — allowed, "
    "gate_self_read — about a minute after the refusal, through a verb that IS in the set. The "
    "operator's approval (19:43:20Z) was correct on the merits even though the being served its own "
    "need without it. (4) DISTINGUISHED FROM MY OWN DISSENTS TODAY ON THIS MARKER FAMILY: wake-1021v "
    "was a 7th re-open of one digest whose prior approval had lapsed unspent (process noise); "
    "wake-1021x was right-content-wrong-target (hand-edit of the deployed live gate) and "
    "placeholder content. None of those defects is present here: fresh act, genuine read, "
    "digest-scoped grant, prompt operator decision. Approving authorises exactly one read of public "
    "gate source; it should be — and was — approved. The durable remedy is merge+deploy of #1361, "
    "which this per-instance grant does not substitute for. Peer evidence, not a ruling. "
    f"Operating law read as kimi-code, law_hash={law_hash}."
)

out = hm.rpc(h, "hestia_gate_escalation_corroborate", {
    "session_id": s,
    "escalation_id": "6fc564c0d5fd07b3",
    "stance": "concur",
    "argument": ARGUMENT,
})
print(json.dumps(out, indent=1))
