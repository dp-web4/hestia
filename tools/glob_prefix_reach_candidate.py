#!/usr/bin/env python3
"""A candidate rule that satisfies BOTH recorded glob incidents. Not installed anywhere.

Two seats decided the same question opposite ways, each after a live failure, and each wrote
the reason into the code:

  codex/kimi `path_targets`:  "'pattern' (Glob/Grep) is deliberately NOT here -- it is a
      matcher ('*.md', a regex), not a filesystem reach. Checking the pattern as a path
      false-denied every Glob whose pattern didn't look like a granted repo (Kimi live,
      2026-07-23)."

  gemini `path_targets`:      "read_many_files takes `include`/`exclude` GLOBS, not `paths`
      (SOURCE-VERIFIED). Scanning only paths/file_paths skipped Gate-1b for this tool
      entirely - an out-of-scope `include:["../restricted-project/**"]` was ALLOWED."

Both are right about their own incident. Collapsing them by union re-imports codex's
false-deny; collapsing by picking a winner re-opens gemini's hole. So neither collapse is
available, which is why this fork has outlived every other one.

THE CANDIDATE: a glob pattern is neither "a path" nor "not a path". Its LITERAL PREFIX -- the
segments before the first segment containing a wildcard -- is a reach, and the wildcard tail
is a matcher. `*.md` has an empty prefix and therefore constrains nothing;
`../restricted-project/**` has the prefix `../restricted-project`, which resolves and scopes.
One predicate, and both incident records are its test cases.

This driver implements the candidate, re-implements both seat rules from their own sources'
behaviour, and runs all three over the two incidents plus every distinct glob pattern found in
the local transcripts. It changes no gate. Exit 1 if the candidate fails either incident.
"""

import argparse
import collections
import json
import sys
from pathlib import Path

WILDCARD = set("*?[{")

# THE KEY NAME DOES NOT DETERMINE THE LANGUAGE, and the first version of this driver got that
# wrong. `pattern` is a GLOB under `Glob` and a REGEX under `Grep` -- the same key, two
# languages -- and running the glob rule over both denied 802 calls in the corpus, nearly all
# of them ordinary Grep regexes like `def step` (no wildcard character, so the whole regex read
# as a literal relative path, so out of scope, so denied). That is codex's 2026-07-23 incident
# reproduced by the very rule proposed to prevent it.
#
# So the domain table cannot be keyed on argument name. It has to be keyed on (tool, key) ->
# value kind, which is a stronger claim than this file set out to make and the reason it is
# spelled out here rather than assumed.
GLOB_PATTERN_TOOLS = frozenset({"Glob"})


def glob_prefix(pattern: str):
    """The literal directory prefix of a glob pattern, or None if it constrains nothing.

    Segment-wise, not character-wise: `/a/b*/c` yields `/a`, never `/a/b`. Truncating inside a
    segment would invent a directory that the pattern does not name, and inventing a reach is
    the failure mode on the deny side of this rule.

    A trailing literal segment is NOT dropped: `/a/b/c.md` (a pattern with no wildcard at all)
    is entirely literal and its whole self is the reach, which is the same answer the ordinary
    path rule gives -- the candidate degrades to the existing behaviour when nothing is
    wildcarded, rather than opening a second, laxer door for path-shaped patterns.
    """
    if not isinstance(pattern, str) or not pattern.strip():
        return None
    segs = pattern.replace("\\", "/").split("/")
    literal = []
    for s in segs:
        if WILDCARD & set(s):
            break
        literal.append(s)
    if len(literal) == len(segs):
        prefix = "/".join(literal)          # no wildcard anywhere: the pattern IS a path
    else:
        prefix = "/".join(literal)
    prefix = prefix.rstrip("/")
    # An empty or bare-root prefix names no directory the member chose. `*.md` and `**/x`
    # land here, and this is exactly the branch that keeps codex's Glob from being denied.
    if not prefix or prefix in (".", "/"):
        return None
    return prefix


# The three rules, as functions from a pattern to "what the scope check is handed".
def rule_codex(pattern):
    """`pattern` is never a path. Nothing is handed to the scope check."""
    return None


def rule_gemini(pattern):
    """`pattern` is a path. The whole string is handed to the scope check."""
    return pattern


def rule_candidate(pattern):
    return glob_prefix(pattern)


RULES = (("codex/kimi", rule_codex), ("gemini", rule_gemini), ("candidate", rule_candidate))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", required=True, help="workspace root")
    ap.add_argument("--granted", default="hestia", help="the single granted repo")
    ap.add_argument("--transcripts", default=str(Path.home() / ".claude" / "projects"))
    ap.add_argument("--limit-files", type=int, default=400,
                    help="transcripts to sample for real patterns (0 = all)")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root / "plugins" / "_shared"))
    import hestia_gate_core as core

    ws = args.workspace.rstrip("/")
    prof = core.HarnessProfile(member_id="claude-code",
                               identity_path="/nonexistent/identity.json",
                               home_markers=("~/.claude",))
    scopes = (args.granted,)

    def scoped(pattern, rule):
        """ALLOW / DENY as the scope check would answer, given what the rule hands it."""
        handed = rule(pattern)
        if handed is None:
            return "allow"          # nothing to check -- the call proceeds
        return "allow" if core.path_in_scope(handed, scopes, ws, prof, cwd=ws) else "deny"

    # The two incidents, each with the answer its own record says is correct.
    INCIDENTS = [
        ("*.md", "allow",
         "codex/kimi 2026-07-23: a bare matcher must not be read as a reach"),
        ("../restricted-project/**", "deny",
         "gemini: an out-of-scope include glob was ALLOWED and should not have been"),
    ]

    print(f"workspace {ws}   scope {scopes}\n")
    print(f"{'pattern':34} {'want':6} " + " ".join(f"{n:12}" for n, _ in RULES))
    print("-" * 84)
    failures = collections.Counter()
    for pattern, want, why in INCIDENTS:
        answers = [scoped(pattern, r) for _, r in RULES]
        print(f"{pattern:34} {want:6} " +
              " ".join(f"{a:12}" for a in answers))
        print(f"{'':41}{why}")
        for (name, _), a in zip(RULES, answers):
            if a != want:
                failures[name] += 1
    print()
    for name, _ in RULES:
        n = failures[name]
        verdict = "satisfies both records" if not n else f"FAILS {n} of 2"
        print(f"  {name:12} {verdict}")

    # Every distinct pattern actually seen in the wild, and where the three rules disagree.
    files = sorted(Path(args.transcripts).rglob("*.jsonl"))
    if args.limit_files:
        files = files[:args.limit_files]
    seen = collections.Counter()
    for t in files:
        try:
            with open(t, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"tool_use"' not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    for b in ((rec.get("message") or {}).get("content") or []):
                        if not isinstance(b, dict) or b.get("type") != "tool_use":
                            continue
                        ti = b.get("input")
                        if isinstance(ti, dict) and isinstance(ti.get("pattern"), str) \
                                and b.get("name") in GLOB_PATTERN_TOOLS:
                            seen[ti["pattern"]] += 1
        except OSError:
            continue

    print(f"\n{len(seen)} distinct `pattern` value(s) in {len(files)} transcript(s)")
    disagree = []
    for pattern, n in seen.items():
        answers = tuple(scoped(pattern, r) for _, r in RULES)
        if len(set(answers)) > 1:
            disagree.append((n, pattern, answers))
    disagree.sort(reverse=True)
    print(f"{len(disagree)} where the three rules do not agree\n")
    print(f"{'n':>5} {'pattern':46} " + " ".join(f"{n:10}" for n, _ in RULES))
    print("-" * 92)
    for n, pattern, answers in disagree[:25]:
        print(f"{n:5} {pattern[:46]:46} " + " ".join(f"{a:10}" for a in answers))
    if len(disagree) > 25:
        print(f"... {len(disagree) - 25} more")

    cand_denies = sum(n for n, _p, a in disagree if a[2] == "deny")
    gem_denies = sum(n for n, _p, a in disagree if a[1] == "deny")
    print(f"\nOn the disagreeing patterns: gemini's rule would deny {gem_denies} call(s), "
          f"the candidate {cand_denies}.")
    print("codex/kimi's rule denies none of them, by construction -- it never checks.")
    print("\nThose two deny counts are UPPER BOUNDS and not comparable to a live rate: every")
    print("relative pattern here resolves against --workspace, while a real call resolves")
    print("against its own cwd, usually inside a granted repo. `sage/snarc/**/*.py` denies")
    print("here and would not from inside SAGE. What the numbers do support is the ORDERING,")
    print("which holds under any cwd: the candidate hands the scope check a strict prefix of")
    print("what gemini hands it, so it cannot deny anything gemini would allow.")
    return 1 if failures["candidate"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
