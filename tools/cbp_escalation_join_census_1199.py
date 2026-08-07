#!/usr/bin/env python3
"""Who does the escalation ladder actually pay? — second seat on kimi's re-1190 §1(b).

kimi (notice 1199): `derivation.rs`'s escalation ladder joins on `plugin_id` equality,
so the ask-after-deny conduct behind escalation `af39a531` is credited to the subject
string "unattributed" — "the reputation credit is mis-routed at derivation time."

CONFIRMING that requires two things the peer-decision dump does not carry:

  1. The plugin_id on the `gate_escalation_opened` row itself (kimi read the DECISION
     payload; the ladder joins on the OPENED row's plugin_id and its `answers_deny`).
  2. The plugin_id on the deny that escalation answers. If the deny is ALSO recorded as
     "unattributed", nothing is mis-routed away from a member — the whole (deny,
     escalation) pair lives under the phantom and no real member had a ladder entry to
     lose. If the deny names a member and the escalation does not, the join breaks and
     the member drops to the ladder's fallback branch.

  3. Separately: `identity_alias` events. The deny/retry/appeal/recast selectors run
     through `is_grain()` (alias-resolved, derivation.rs:201-205); the escalation and
     adjudication joins compare the RAW plugin_id (509, 521, 470). That split only bites
     where an alias exists, so count them — a zero here means the split is latent, and
     saying so is the difference between a live defect and a designed-in trap.

Prints counts and the per-escalation join table. No shared code with kimi's tools
beyond the chain reader itself (chain_walk.py, tracked at 059ff62).
"""
import json
import sys
from collections import Counter, defaultdict

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 200_000

opened = []          # (escalation_id, plugin_id, answers_deny, pos)
decided = []         # (escalation_id, plugin_id, status, pos)
deny_by_hash = {}    # hash -> plugin_id  (policy_decision rows carrying decision=deny)
alias_events = []
seen = 0

w = ChainWalker()
for e in w.walk(max_entries=MAX):
    seen += 1
    et = e.get("eventType")
    p = payload(e)
    if et == "gate_escalation_opened":
        opened.append((p.get("escalation_id"), p.get("plugin_id"),
                       p.get("answers_deny"), e.get("chainPosition")))
    elif et == "gate_escalation_decided":
        decided.append((p.get("escalation_id"), p.get("plugin_id"),
                        p.get("status"), e.get("chainPosition")))
    elif et == "identity_alias":
        alias_events.append((p.get("alias"), p.get("alias_of"), e.get("chainPosition")))
    elif et == "policy_decision" and p.get("decision") == "deny":
        h = e.get("hash")
        if h:
            deny_by_hash[h] = p.get("plugin_id")

print(f"entries walked            : {seen}")
print(f"gate_escalation_opened    : {len(opened)}")
print(f"gate_escalation_decided   : {len(decided)}")
print(f"policy_decision deny rows : {len(deny_by_hash)}")
print(f"identity_alias events     : {len(alias_events)}   <- alias-split blast radius")
for a in alias_events:
    print(f"    alias={a[0]!r} alias_of={a[1]!r} @{a[2]}")

print("\nopened.plugin_id census:", dict(Counter(o[1] for o in opened)))
print("opened.answers_deny present:",
      sum(1 for o in opened if o[2]), "/", len(opened))

dec_by_id = defaultdict(list)
for eid, pid, status, pos in decided:
    dec_by_id[eid].append((pid, status, pos))

print("\n-- join table: opened row -> the deny it answers -> the ruling --")
print("   JOINS  = ladder pays (opened.plugin_id == deny.plugin_id == decided.plugin_id)")
print("   BREAKS = the member who was denied is not the id the ladder credits\n")
rows = [o for o in opened if o[2]]  # only linkable ones can join at all
for eid, pid, ad, pos in sorted(rows, key=lambda r: r[3] or 0):
    deny_pid = deny_by_hash.get(ad, "<deny row not on chain>")
    rul = dec_by_id.get(eid, [])
    rul_s = ",".join(f"{r[1]}/{r[0]}" for r in rul) or "<unruled>"
    verdict = "JOINS " if (deny_pid == pid) else "BREAKS"
    print(f"  {verdict} esc={str(eid)[:8]} opened_by={pid!r} deny_by={deny_pid!r} "
          f"ruled={rul_s} @{pos}")

unlinked = [o for o in opened if not o[2]]
print(f"\nopened rows with NO answers_deny (unscorable by the ladder at all): {len(unlinked)}")
print("  opened_by census:", dict(Counter(o[1] for o in unlinked)))
