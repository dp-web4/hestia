#!/usr/bin/env python3
"""Who ASKED? — and does the one live alias pair actually split evidence?

Two follow-ups the raw dump forced.

(A) THE DENOMINATOR. `answers_deny` is present as a key on 212/288 opened rows and
    absent on 76 — the field shipped 2026-08-01 (389c645), so the lifetime 0/288 mixes
    a pre-field era with the post-field one. The honest rate is over rows minted while
    the field existed. Census presence-vs-null against that denominator.

(B) WHO OPENED IT. Three sampled rows all carried `stated_detail: "Auto-opened by the
    gate on a refused write; the member stated no rationale because it did not choose
    to escalate."` Three is a sample, not a census. The escalation ladder scores "the
    asking, not the outcome" — so if every escalation on the chain was opened BY THE
    GATE rather than by a member choosing to ask, the conduct the top of the
    Temperament scale is reserved for has never occurred, which is a different fact
    from "it occurred and was mis-credited". Count the two authorship shapes.

(C) THE ALIAS PAIR. One `identity_alias` exists (`codex-cli` -> `codex`). `codex-cli`
    carries 14 `policy_decision` and 1 `adjudication`. Denies fold into derive("codex")
    via `is_grain`; the adjudication join compares the raw subject string. Dump both so
    the split can be priced rather than asserted.
"""
import json
import sys
from collections import Counter

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 200_000
AUTO = "Auto-opened by the gate on a refused write"

key_present = 0
key_null = 0
key_absent = 0
authorship = Counter()
auto_by_pid = Counter()
member_by_pid = Counter()
member_rows = []
cli_rows = []
seen = 0

w = ChainWalker()
for e in w.walk(max_entries=MAX):
    seen += 1
    et = e.get("eventType")
    raw = e.get("eventData") or {}
    if et == "gate_escalation_opened":
        if "answers_deny" in raw:
            key_present += 1
            if raw.get("answers_deny") is None:
                key_null += 1
        else:
            key_absent += 1
        # THREE buckets, not two. "field absent" (minted before the rationale fields
        # existed) and "field present but null" (the caller had somewhere to put its
        # words and put nothing) are different facts, and collapsing them would report
        # a wire gap as an age gap. First pass did collapse them; the counts moved.
        detail = raw.get("stated_detail") or ""
        pid = raw.get("plugin_id")
        has_key = "stated_detail" in raw or "stated_reason" in raw
        if detail.startswith(AUTO):
            authorship["gate-auto-opened (the gate's own text)"] += 1
            auto_by_pid[pid] += 1
        elif detail or raw.get("stated_reason"):
            authorship["member-stated (someone's own words)"] += 1
            member_by_pid[pid] += 1
            if len(member_rows) < 8:
                member_rows.append((e.get("chainPosition"), raw))
        elif has_key:
            authorship["field PRESENT, value null (nothing said)"] += 1
        else:
            authorship["field ABSENT (minted before the field existed)"] += 1
    p = payload(e)
    if (p.get("plugin_id") == "codex-cli" or p.get("subject_plugin_id") == "codex-cli"):
        cli_rows.append((e.get("chainPosition"), et, p))

print(f"entries walked: {seen}\n")
print("-- (A) answers_deny, against the denominator that could carry it --")
print(f"  key PRESENT on opened rows (post-389c645) : {key_present}")
print(f"      of those, value null                  : {key_null}")
print(f"      of those, value SET (the linked ones)  : {key_present - key_null}")
print(f"  key ABSENT (minted before the field)      : {key_absent}")

print("\n-- (B) who opened it --")
for k, n in authorship.most_common():
    print(f"  {n:5d}  {k}")
print(f"  gate-auto-opened by plugin_id : {dict(auto_by_pid)}")
print(f"  member-stated   by plugin_id  : {dict(member_by_pid)}")
for pos, raw in member_rows:
    print(f"    MEMBER-STATED @{pos}: {json.dumps(raw, sort_keys=True)[:500]}")

print(f"\n-- (C) every row under the alias spelling `codex-cli` ({len(cli_rows)}) --")
for pos, et, p in sorted(cli_rows, key=lambda r: r[0] or 0):
    if et == "policy_decision":
        print(f"  @{pos} {et}: decision={p.get('decision')!r} enforced={p.get('enforced')!r} "
              f"role={p.get('role_lct')!r} tool={p.get('tool_name')!r}")
    elif et == "adjudication":
        print(f"  @{pos} {et}: axis={p.get('axis')!r} verdict={p.get('verdict')!r} "
              f"score={p.get('score')!r} subject_role={p.get('subject_role')!r} "
              f"about_deny_hash={str(p.get('about_deny_hash'))[:12]!r} upheld={p.get('upheld')!r}")
    else:
        print(f"  @{pos} {et}: {json.dumps(p, sort_keys=True)[:300]}")
