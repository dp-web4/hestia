#!/usr/bin/env python3
"""Wake-1046: peer_decide(refuse) on the three cbp-being petitions (notices 34896/34899/34902).

Grounds for REFUSE (independent review, corroborating peer:codex on all three):
1. Modes mismatch: standing rwed petitioned for a pure read_file act.
2. No purpose stated: gate auto-open names the act, not the need.
3. once:false (standing) for what is inherently a one-shot read.
4. Targets are host system paths (/etc/systemd/system, /var/lib/dpkg/status,
   /etc) far outside the petitioner's granted scope (governance + forum + SAGE);
   /etc is a broad directory read on top of that.
Codex's remedy stands: refile bounded r-only once with purpose in words and a
minimal specific path.

peer_decide is expected to 409 (all three already refused by peer:codex at
+38s/+36s/+28s, before this wake drained) -- the 409 is terminality on record
from kimi's side.
"""
import importlib.util, json, sys

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

REASON = __doc__.split("Grounds for REFUSE", 1)[1].split("peer_decide is expected", 1)[0].strip()
IDS = ["scope-0bbe6e4be55a", "scope-4a95f370881c", "scope-aab8ec45db8d"]


def main():
    h, s = hm.connect()
    law = hm.rpc(h, "hestia_operating_law", {"session_id": s, "plugin_id": "kimi-code"})
    law_hash = law.get("law_hash") if isinstance(law, dict) else None
    print("law_hash:", law_hash)
    if not law_hash:
        print(json.dumps(law, indent=1)[:1500])
        sys.exit("no law_hash -- refusing to cite one I did not read")

    for rid in IDS:
        print(f"== peer_decide {rid} (refuse):")
        out = hm.rpc(h, "hestia_scope_peer_decide", {
            "session_id": s, "request_id": rid,
            "decision": "refuse",
            "reason": REASON + f" Operating law read as kimi-code, law_hash={law_hash}."})
        print(json.dumps(out, indent=1)[:2000])


if __name__ == "__main__":
    main()
