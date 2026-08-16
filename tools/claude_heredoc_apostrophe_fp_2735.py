#!/usr/bin/env python3
"""Independent reproduction of the FP codex reported upholding appeal 2731 (notice 2735).

Claim under test: a quoted-heredoc BODY is payload, never a write-position haystack.
Codex's mechanism: ordinary prose apostrophes inside the body break the shell lexer;
the except-path then hands the WHOLE payload up as conservative write candidates, so a
governance path merely CITED in a commit message is reported as the write target.

This probe does not inherit codex's table. It runs the classifier on this seat and
varies exactly one axis: presence of an apostrophe in the heredoc prose. Everything
else -- the citation, the surrounding command substitution, the tool -- is held fixed.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "plugins", "_shared"))
import hestia_governance_closure as gc  # noqa: E402

CITE = "plugins/_shared/hestia_governance_closure.py"


def commit(body: str, wrap: bool) -> str:
    inner = "git commit-tree e74cc02 -p a4e8fb8 -F /dev/stdin <<'MSG'\n%s\nMSG" % body
    return "COMMIT=$(%s)" % inner if wrap else inner


# (label, heredoc body, expected-by-contract)
CASES = [
    ("cite alone, no apostrophe",
     "forum: the classifier at %s reads payload" % CITE),
    ("cite + apostrophe in prose",
     "forum: the author's note on %s reads payload" % CITE),
    ("cite + double quote in prose",
     'forum: the so-called "payload" rule in %s' % CITE),
    ("apostrophe, NO cite (negative control)",
     "forum: the author's note on tools/unrelated.py"),
    ("cite + apostrophe, prose only, no path (control)",
     "forum: the author's note on the governance closure"),
]


def main() -> int:
    rows = []
    for label, body in CASES:
        for wrap in (False, True):
            v = gc.classify("Bash", {"command": commit(body, wrap)})
            rows.append((label, wrap, v.classification, v.rule, v.resource))
    w = max(len(r[0]) for r in rows)
    print(f"{'case'.ljust(w)}  wrap  verdict  rule / resource")
    print("-" * (w + 48))
    for label, wrap, cls, rule, res in rows:
        print(f"{label.ljust(w)}  {'yes' if wrap else ' no'}   {cls:7}  "
              f"{rule or '-'} | {res or '-'}")

    # The finding, asserted rather than eyeballed: the apostrophe alone flips the verdict.
    plain = gc.classify("Bash", {"command": commit(CASES[0][1], False)})
    apos = gc.classify("Bash", {"command": commit(CASES[1][1], False)})
    neg = gc.classify("Bash", {"command": commit(CASES[3][1], False)})
    print()
    print("APOSTROPHE IS THE ONLY VARIED AXIS:")
    print(f"  without: {plain.classification} ({plain.rule or 'no rule'})")
    print(f"  with   : {apos.classification} ({apos.rule or 'no rule'})")
    print(f"  negative control (apostrophe, no governance cite): "
          f"{neg.classification} ({neg.rule or 'no rule'})")
    reproduced = (plain.classification != "write" and apos.classification == "write")
    print(f"\nREPRODUCED: {reproduced}")
    # A positive control that does NOT depend on the bug: a real redirect into the
    # closure must still be a write, or this probe is measuring a dead classifier.
    live = gc.classify("Bash", {"command": "echo x > %s" % CITE})
    print(f"POSITIVE CONTROL (real redirect into closure) -> {live.classification} "
          f"({live.rule}) [must be 'write', else the probe is inert]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
