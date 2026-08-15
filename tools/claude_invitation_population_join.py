import sys, json, collections
sys.path.insert(0,"tools")
from chain_walk import ChainWalker, payload
d=json.load(open("/home/dp/.claude/hestia-mesh-primers/notice-YJfozJ.json"))
mine={r["pointer_uri"].split("/")[-1].split("#")[0] for r in d["unanswered"]["owed_to_me"] if r["pointer_uri"].startswith("hestia://escalation/")}
pools={}; corr=collections.Counter(); who=collections.Counter()
for e in ChainWalker().walk(max_entries=60000):
    t=e.get("eventType",""); p=payload(e)
    eid=p.get("escalation_id")
    if t=="gate_escalation_opened":
        v=p.get("invitation_evidence") or p.get("invited_peers") or []
        names={(it.get("plugin_id") if isinstance(it,dict) else it) for it in v if it}
        if eid: pools[eid]=names
    if t=="gate_escalation_corroborated":
        corr[eid]+=1; who[p.get("plugin_id")]+=1
print(f"my unanswered escalation ids: {len(mine)}")
hit=[e for e in mine if e in pools]
print(f"  of which found in chain window: {len(hit)}")
c=collections.Counter()
for e in hit:
    for n in pools[e]: c[n]+=1
print("\ninvite pool composition on MY escalations:")
for k,v in c.most_common(): print(f"  {str(k):<34} {v}/{len(hit)}")
print(f"\ntotal corroborations in window: {sum(corr.values())} across {len(corr)} escalations")
print("corroborating seats:", dict(who.most_common()))
print("corroborations on MY escalations:", sum(corr[e] for e in mine))
