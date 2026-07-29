#!/usr/bin/env python3
"""Tests for the launch-time law renderer.

The hook exists so a member is not left inferring its law from being denied. These tests
guard the two ways that goal inverts: telling a member it is ungoverned when the lookup
merely failed, and showing an unenforced rule as if it stops you.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import law_inject as L  # noqa: E402

FAILS = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")
    if not cond:
        FAILS.append(name)


def base(rules):
    return {"identity": {"plugin_id": "m", "role": "role:constellation:member"},
            "law": rules, "law_hash": "abc", "layers": ["society"], "lists_bound": []}


# A published-but-unwired list must never render as an ordinary deny. The daemon marks it
# `enforced: false`; this renderer used to read only `decision` and `law` and drop that word.
out = L.render(base([
    {"decision": "deny", "law": "a real rule that stops you"},
    {"decision": "deny", "law": "operator list", "enforced": False,
     "enforcement_note": "not yet wired into the policy fold"},
]))
check("unenforced rule is marked NOT ENFORCED", "NOT ENFORCED" in out)
check("its note survives to the reader", "not yet wired into the policy fold" in out)
check("the caveat block appears", "will not stop the act" in out)
check("and says absence of a block is not permission", "not read the absence" in out.replace("do ", ""))

# The dangerous inverse: an ordinary rule has no `enforced` key, and must NOT be demoted.
out = L.render(base([{"decision": "deny", "law": "a real rule"}]))
check("a rule with no `enforced` key is NOT demoted", "NOT ENFORCED" not in out)
check("no caveat block when nothing is unenforced", "will not stop the act" not in out)

# `enforced: true` is likewise a real rule.
out = L.render(base([{"decision": "deny", "law": "real", "enforced": True}]))
check("`enforced: true` is not demoted", "NOT ENFORCED" not in out)

# An empty ruleset is a real state and must not read as a failed lookup.
out = L.render(base([]))
check("empty law says it is empty, not broken", "empty law, not a failed lookup" in out)

print("\nFAILED" if FAILS else "\nOK", f"({len(FAILS)} failures)" if FAILS else "")
sys.exit(1 if FAILS else 0)
