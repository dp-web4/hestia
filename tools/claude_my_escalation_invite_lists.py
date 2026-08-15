import sys, json, collections
sys.path.insert(0,"tools")
from chain_walk import ChainWalker, payload
d=json.load(open("/home/dp/.claude/hestia-mesh-primers/notice-YJfozJ.json"))
mine={r["pointer_uri"].split("/")[-1].split("#")[0] for r in d["unanswered"]["owed_to_me"] if r["pointer_uri"].startswith("hestia://escalation/")}
shown=0; bars=collections.Counter()
for e in ChainWalker().walk(max_entries=60000):
    if e.get("eventType")!="gate_escalation_opened": continue
    p=payload(e)
    if p.get("escalation_id") not in mine: continue
    bars[(p.get("bar"), len(p.get("invited_peers") or []), len(p.get("invitation_evidence") or []))]+=1
    if shown<2:
        shown+=1
        print("esc:", p.get("escalation_id"), "bar:", p.get("bar"))
        print("  invited_peers:", json.dumps(p.get("invited_peers"))[:300])
        print("  invitation_evidence:", json.dumps(p.get("invitation_evidence"))[:300])
        print("  withheld:", json.dumps(p.get("invitation_withheld"))[:200])
print("\n(bar, n_invited, n_evidence) over MY escalations:")
for k,v in bars.most_common(): print("  ",k,v)
