#!/usr/bin/env python3
"""Resolve the 3-way merge of #1247 onto #1239's c535619d in the neutral copies under merged/.
#1239's cleared `ClosureVerdict.resolved` (tuple of every other spelling) wins; #1247's single
location is renamed `landing`. Writes only merged/*.py (neutral names)."""
import re
from pathlib import Path
M = Path(__file__).resolve().parent / "merged"

def sub1(text, old, new):
    assert text.count(old) == 1, (text.count(old), old[:80])
    return text.replace(old, new)

def conflict(text, n_ours_start):
    """Return (full conflict block) for the conflict whose ours side starts with n_ours_start."""
    m = re.search(r"<<<<<<< ours/[a-z]+\.py\n" + re.escape(n_ours_start) + r".*?>>>>>>> theirs/[a-z]+\.py\n",
                  text, re.S)
    assert m, n_ours_start[:60]
    return m.group(0)

# ── closure ──
p = M / "closure.py"; s = p.read_text()
s = sub1(s, """    that destination to the escalation's price, not only the alias (Codex review of #1239).
    \"\"\"""", """    that destination to the escalation's price, not only the alias (Codex review of #1239).
    `landing` is the one LOCATION the write reaches (#1247), what the daemon prices a member's
    gate entry by: home-expanded, cwd-joined, realpath'd (`resolve_location`). It is a
    separate field, not `resolved`, because the two answer different questions: `resolved`
    lists every spelling the match consulted; `landing` names where the bytes go.
    \"\"\"""")
blk = conflict(s, "    # The LOCATION the write reaches")
s = s.replace(blk, """    resolved: tuple = ()
    # The LOCATION the write reaches, as this classifier resolved it: home-expanded, joined
    # onto the caller's cwd when relative, realpath'd (symlinks and `..` resolved). `resource`
    # is the argument as written (it can be relative, or a name inside a `cd`); this is where it
    # lands. Set on a resolved write only. It is what the daemon prices a member's gate entry
    # from, by location, so the price never depends on how the act was spelled or summarised.
    # (#1247 named this `resolved`; re-stacked on #1239, whose cleared `resolved` is the tuple
    # above, it is `landing`.)
    landing: Optional[str] = None
""")
blk = conflict(s, "                # `resolved`: where this write lands")
s = s.replace(blk, """                # Lazily, so `classify` stops matching at the first target exactly as before.
                # `landing`: where this write lands (cwd-joined, symlinks and `..` resolved), so
                # every write verdict carries the LOCATION the daemon prices member gate entries
                # by, not only the argument as written and its other spellings (#1247).
                yield ClosureVerdict("write", rule, marker, t, src,
                                     tuple(closure.forms(t, cwd=cwd)[1:]),
                                     landing=resolve_location(t, cwd) if rule == RULE_WRITE
                                     else None)
""")
assert "<<<<<<<" not in s and ">>>>>>>" not in s and "=======\n" not in s
p.write_text(s)

# ── single gate ──
p = M / "single.py"; s = p.read_text()
s = sub1(s, "    if _reaches_registered_entry(rv.resolved, reg.entries):",
            "    if _reaches_registered_entry(getattr(rv, \"landing\", None), reg.entries):")
blk = conflict(s, "    Each is the LOCATION the closure resolved")
s = s.replace(blk, """    Each target rides with the other spellings the closure matched it by (cwd-joined,
    realpath'd), so an alias carries its destination (Codex review of #1239, P1-2), and with
    the LOCATION it lands at (`landing`, #1247) where that is not already among them: the
    daemon prices a member's gate entry by where it is, and a relative or `cd`-qualified
    spelling names no location.
    `against`: the closure to enumerate with — the seat's registered surface when it has one, so
    a write the executed surface governs is enumerated too (#1247).
    `complete` is False when the write set could not be enumerated: an opaque writer, an
    internal error, no target named, a command outside the grammar or unparseable (its
    targets are vocabulary that matched, not resolved write positions: `$TARGET` names no
    file), or a relative target with no cwd to resolve it against (P1-1). The daemon then
    prices the highest bar; the targets that are known still ride. Never raises.\"\"\"
""")
blk = conflict(s, "            verdicts = closure.write_verdicts(tool, ti, cwd=event.cwd, closure=against)\n")
s = s.replace(blk, """            verdicts = closure.write_verdicts(tool, ti, cwd=event.cwd, closure=against)
        resolved = []
        for v in verdicts:
            if v.marker and v.resource:
                resolved.append(v.resource)
                resolved.extend(getattr(v, "resolved", ()))
                landing = getattr(v, "landing", None)
                if isinstance(landing, str) and landing and landing not in resolved:
                    resolved.append(landing)
        # COMPLETE: #1239's rule (every verdict a resolved write whose target is absolute or
        # was pinned by a cwd-join / realpath), AND #1247's (its landing is an absolute
        # location). Two conjuncts, so neither cleared rule can be the weaker reading: a write
        # set either one calls incomplete rides the `unenumerated` sentinel, priced highest.
        complete = bool(resolved) and all(
            v.marker and v.rule == closure.RULE_WRITE
            and (os.path.isabs(v.resource) or getattr(v, "resolved", ()))
            and isinstance(getattr(v, "landing", None), str) and os.path.isabs(v.landing)
""")
s = sub1(s, """            # path the closure resolved, not only the one `cv` reports — each as the LOCATION it
            # lands at (#1247). The daemon""", """            # path the closure resolved, not only the one `cv` reports — each with its other
            # spellings and the LOCATION it lands at (#1247). The daemon""")
assert "<<<<<<<" not in s and ">>>>>>>" not in s
p.write_text(s)

# ── #1247's own test: the location is `landing` now ──
p = M / "mistest.py"; s = p.read_text()
s = sub1(s, """            check(f"{member}-{label}-resolved", v.resolved == want, (ti, v.resolved, want))""",
            """            check(f"{member}-{label}-resolved", v.landing == want, (ti, v.landing, want))""")
s = sub1(s, """              v.resolved is None or not v.resolved.startswith(dest + os.sep), v)""",
            """              v.landing is None or not v.landing.startswith(dest + os.sep), v)""")
s = sub1(s, """    check("a-read-carries-no-resolved", v.resolved is None, v)""",
            """    check("a-read-carries-no-resolved", v.landing is None, v)""")
p.write_text(s)
print("resolved")
