"""Strict census: a refusal is a tool_result that IS the gate's deny, not one that mentions it."""
import json, os, sys, glob, re, collections
sys.path.insert(0, "/tmp/wt-gaterepair/plugins/_shared"); sys.path.insert(0, "/tmp/gaterepair")
import hestia_governance_closure as g, resolver
ROOTS = ["/home/dp/.claude/projects/-home-dp-ai-workspace",
         "/home/dp/.claude/projects/-tmp",
         "/home/dp/.claude/projects/-mnt-c-exe-projects-ai-agents"]
# The shim's own wording, anchored: the result must BEGIN with the hook's refusal envelope.
START = re.compile(r"\A\s*(?:PreToolUse[^\n]*?hook error:[^\n]*?\n?)?\s*hestia: (?:ESCALATION [0-9a-f]{16} opened|deny \[gate-self-access\])")
MARKERTEXT = re.compile(r"governance marker '([^']+)' in its governance-closure-(\w+) text")
def blocks(m):
    c = m.get("content"); return c if isinstance(c, list) else []
calls, denied = {}, []
for root in ROOTS:
    for fp in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
        try: fh = open(fp, errors="replace")
        except OSError: continue
        with fh:
            for line in fh:
                if "toolu_" not in line: continue
                try: rec = json.loads(line)
                except Exception: continue
                msg, cwd = rec.get("message") or {}, rec.get("cwd")
                for b in blocks(msg):
                    if not isinstance(b, dict): continue
                    if b.get("type") == "tool_use":
                        calls[b.get("id")] = (b.get("name"), b.get("input"), cwd, rec.get("timestamp"))
                    elif b.get("type") == "tool_result":
                        t = b.get("content")
                        if isinstance(t, list):
                            t = " ".join(x.get("text","") for x in t if isinstance(x, dict))
                        if isinstance(t, str) and "gate-self-access" in t and START.match(t):
                            denied.append((b.get("tool_use_id"), t))
print(f"{len(denied)} results that ARE a gate-self-access refusal (anchored), "
      f"{len(calls)} tool_use indexed")
shipped = g._bash_write_targets
_, _, new_bwt, _ = resolver.make(g)
rows, seen = [], set()
for tid, txt in denied:
    if tid not in calls: continue
    name, inp, cwd, ts = calls[tid]
    k = json.dumps(inp, sort_keys=True)[:4000]
    if k in seen: continue
    seen.add(k)
    m = MARKERTEXT.search(txt)
    pos = m.group(2) if m else "?"
    g._bash_write_targets = shipped
    try: b = g.classify(name, inp, cwd=cwd)
    except Exception: b = None
    g._bash_write_targets = new_bwt
    try: a = g.classify(name, inp, cwd=cwd)
    except Exception: a = None
    rows.append((ts, name, pos, b, a, inp))
g._bash_write_targets = shipped
print(f"{len(rows)} DISTINCT refused calls\n")
c = collections.Counter((r[1], r[2], r[3].classification if r[3] else "?",
                         r[4].classification if r[4] else "?") for r in rows)
print(f"{'tool':8s} {'deny text says':16s} {'today':8s} {'repaired':8s}  n")
for (tool, pos, b, a), n in sorted(c.items(), key=lambda kv: -kv[1]):
    flag = "  <== resolver clears" if b == "write" and a != "write" else ""
    print(f"{tool:8s} {pos:16s} {b:8s} {a:8s}  {n:4d}{flag}")
cleared = [r for r in rows if r[3] and r[3].classification == "write" and r[4] and r[4].classification != "write"]
still  = [r for r in rows if r[3] and r[3].classification == "write"]
notrep = [r for r in rows if not (r[3] and r[3].classification == "write")]
print(f"\nrefusals today's classifier still calls write : {len(still)}")
print(f"  of those, cleared by the resolver           : {len(cleared)}")
print(f"refusals today's classifier does NOT call write: {len(notrep)}")
byyear = collections.Counter(r[0][:7] for r in rows if r[0])
print("by month:", dict(sorted(byyear.items())))
nm = collections.Counter(r[0][:7] for r in notrep if r[0])
print("  not-write by month:", dict(sorted(nm.items())))
