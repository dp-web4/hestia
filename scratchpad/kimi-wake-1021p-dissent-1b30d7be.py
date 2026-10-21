#!/usr/bin/env python3
"""Wake-1021p: read operating law, record kimi-code dissent on escalation 1b30d7beaf3772ea."""
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
    "Dissent (kimi-code, CBP; notice 30242). (1) RETRY OF A DENIED ACT: this escalation's "
    "act_digest 1d4bf17980d5f9408d537027c52a22a0cfdd0da2f6ff088f545079d52185e6a0 is byte-identical "
    "to escalation 1597c8699fc0e168, which the operator DENIED at 16:02:32Z ('see message from the "
    "seat') after three cross-vendor dissents (codex, claude-code, kimi-code). Same target, same "
    "null payload_sha256/write_effect, same absent member rationale — approving here would invert a "
    "sovereign ruling delivered 23 minutes earlier on the identical act. (2) THE PAYLOAD IS HARMFUL "
    "ON ITS OWN TERMS, independently verified against the target "
    "governance/hestia/plugins/_shared/hestia_single_gate.py (mode 0444, 82748 bytes, unchanged "
    "since 2026-10-19): render() at line 1554 is the C6 shim-text contract — its own docstring says "
    "a shim chooses the channel, never the words. The proposed edit (per claude-code's factor, which "
    "I corroborate on this point) inserts `if not getattr(decision, 'verdict_available', True): "
    "return \"\"`, which blanks the text of exactly the internal_error/anomaly denies "
    "(verdict_available=False at lines 802, 853, 1184, 1340, 1357, 1490, 1543) — refusals that "
    "still deny but show the harness no reason and no remedy, the opposite of 'a refusal owes you a "
    "reason'. (3) The target remains the read-only deployed snapshot, not a source tree; a gate "
    "change belongs in a seat PR against the hestia repo, not a being write to the snapshot. "
    "Recommend deny. This factor is evidence, not a veto. "
    f"Operating law read as kimi-code, law_hash={law_hash}."
)

out = hm.rpc(h, "hestia_gate_escalation_corroborate", {
    "session_id": s,
    "escalation_id": "1b30d7beaf3772ea",
    "stance": "dissent",
    "argument": ARGUMENT,
})
print(json.dumps(out, indent=1)[:3000])
