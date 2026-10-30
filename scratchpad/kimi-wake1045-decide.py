#!/usr/bin/env python3
"""Wake-1045: peer_decide(refuse) on scope-93b1003f27d5 (notice 34870).

Grounds for REFUSE (independent review, corroborating peer:codex):
1. Modes mismatch: standing rwed petitioned for a purely read-only compound
   inspection (head|grep|cut of a file + systemctl list-timers).
2. No purpose stated: gate auto-open names the act, not the need.
3. Compound act, two unrelated parts: a file read under ~/.local/bin and a
   host timer query; one path-scoped grant cannot fit both, and the
   systemctl part is not path-bound at all.
4. once:false for what is inherently a one-shot inspection.
Codex's remedy stands: refile bounded r-only once with purpose in words, one
act per petition. The petitioner's sibling session has itself acked
concur-refused + no-refile (chain 675724/675727).

peer_decide is expected to 409 (request already refused by peer:codex at
23:37:17Z, +50s) -- the 409 is terminality on record from kimi's side.
"""
import importlib.util, json, sys

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

REASON = __doc__.split("Grounds for REFUSE", 1)[1].split("peer_decide is expected", 1)[0].strip()


def main():
    h, s = hm.connect()
    law = hm.rpc(h, "hestia_operating_law", {"session_id": s, "plugin_id": "kimi-code"})
    law_hash = law.get("law_hash") if isinstance(law, dict) else None
    print("law_hash:", law_hash)
    if not law_hash:
        print(json.dumps(law, indent=1)[:1500])
        sys.exit("no law_hash -- refusing to cite one I did not read")

    print("== peer_decide scope-93b1003f27d5 (refuse):")
    out = hm.rpc(h, "hestia_scope_peer_decide", {
        "session_id": s, "request_id": "scope-93b1003f27d5",
        "decision": "refuse",
        "reason": REASON + f" Operating law read as kimi-code, law_hash={law_hash}."})
    print(json.dumps(out, indent=1)[:2500])


if __name__ == "__main__":
    main()
