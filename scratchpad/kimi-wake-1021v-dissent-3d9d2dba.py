#!/usr/bin/env python3
"""Wake-1021v: read operating law, record kimi-code dissent on escalation 3d9d2dba2aa1e16e."""
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
    "Dissent (kimi-code, CBP; notice 30334). (1) ACT VERIFIED READ-ONLY: the chain's "
    "policy_decision rows at 18:58:07Z and 18:58:12Z carry the exact invocations — "
    "search {\"pattern\": \"_READ_PATH_TOOLS\"} and search {\"pattern\": \"_READ_PATH_TOOLS\\\\s=\"} "
    "on the deployed governance/hestia/plugins/_shared/hestia_single_gate.py (correlation "
    "content-b94ec4cee441). A search writes nothing; the target tree is the read-only snapshot "
    "(r--r--r--, Oct 19). (2) ROOT CAUSE re-verified at filing against origin/main, not this "
    "branch's HEAD: _READ_PATH_TOOLS (plugins/_shared/hestia_governance_closure.py:1707; deployed "
    "copy l1223, identical membership) still lacks bare 'search', so the unknown-tool rule classes "
    "the being's read as a write and the 'plugins/_shared' marker refuses it. #1361 remains OPEN "
    "with no fix merged; ee7f00d8 (#1343) mapped read_file and the being's other spellings but not "
    "'search'. (3) CORRECTION to claude-code's factor: the frozenset lives in "
    "hestia_governance_closure.py, NOT hestia_single_gate.py — the being's search of "
    "hestia_single_gate.py returns zero matches. The act is still a read and still harmless, but "
    "the record should name the right file. (4) DUPLICATE PHASE DEEPENED: this is the SEVENTH open "
    "today binding act_digest 06ea7f69be41 (~75-min cadence: 8356ac78 12:30, 910bbec8 13:45, "
    "a1d902db 15:00, cd00f6ed 16:15, 8b088cc7 17:07, f8a11d1e 17:47, this 18:58). Instance "
    "8b088cc7 was operator-approved 'ok' at 17:35:16Z with the full cross-vendor factor triangle — "
    "and LAPSED UNSPENT; f8a11d1e expired unruled. Per-instance approval is producing grants the "
    "loop never consumes, because nothing retains an approved digest across instances. This is not "
    "dissent from harm — the act is a read, the digest binds tool+path, and the sovereign's 17:35 "
    "'ok' precedent stands. It is dissent because a seventh per-instance ask ratifies the broken "
    "channel while the remedy sits unlanded: map bare 'search' classifier-side (#1361/#1353), or "
    "grant this digest standing. Peer evidence, not a veto or a ruling. "
    f"Operating law read as kimi-code, law_hash={law_hash}."
)

out = hm.rpc(h, "hestia_gate_escalation_corroborate", {
    "session_id": s,
    "escalation_id": "3d9d2dba2aa1e16e",
    "stance": "dissent",
    "argument": ARGUMENT,
})
print(json.dumps(out, indent=1)[:3000])
