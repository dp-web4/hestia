#!/usr/bin/env python3
"""Has an ancestry-NO false negative ever cost a seat a REDO of finished work?

Motivation
----------
`stranded_by_content.py` established that `git merge-base --is-ancestor` is a
ONE-SIDED test: a YES proves the cited object landed, a NO proves nothing about
whether its *change* landed, because squash-merge relands identical content under
a new sha.  The urgency attached to that correction was a cost claim -- "NO is the
direction that sends a seat to redo finished work."  That clause was never
measured.  This is the measurement.

Method
------
Population: every non-merge commit reachable from ANY ref (local + remote), so a
redo that never merged is still in the frame.

A DUPLICATE is a set of >1 commits sharing a `git patch-id --stable`.  For every
commit in a duplicate set except the earliest ("later twins"), classify how the
duplicate content came to exist:

  copy          author timestamp is IDENTICAL to an earlier twin's.  cherry-pick,
                rebase and squash all preserve author date, so this is a machine
                copying bytes, not a seat authoring them.
  squash-merge  fresh author timestamp, but the commit is on main's first-parent
                chain or its subject ends in `(#N)` -- the GitHub squash of a PR.
  FRESH-AUTHOR-DUPLICATE
                fresh author timestamp and neither of the above: content that
                already existed, authored again at a new date.  This is the
                CANDIDATE population for the cost claim, not proof of it.

Naming (codex, 2026-08-07): this bucket was called RE-DERIVED, which named an
actor's REASON.  The discriminator observes a fresh-author duplicate; it cannot
see whether a seat redid work, force-pushed a rewritten branch, or had a pull ref
move after merge.  Codex's ripgrep specimen `16268dba` is exactly that ambiguity:
a genuine fresh-author duplicate whose nearer account is a post-merge branch
rewrite.  Establishing the redo REASON needs event evidence this instrument does
not have.  The name now stops where the evidence stops.

Ref acquisition surface
-----------------------
"Reachable from ANY ref" means any ref THIS object store happened to fetch, not
every ref the forge retains.  Codex measured the gap on ripgrep: a default clone
sees 2265 commits and reports 0 fresh-author duplicates; a `--mirror` of the same
tip sees 4272 and reports 24.  So the census prints its own surface, and reports
per-namespace how many commits exist ONLY there -- if every namespace's exclusive
count is 0 the surface question is moot, and otherwise that count bounds how much
the answer could move under a wider fetch.

The bucket counts are asserted to sum to the unfiltered ref total.  That guard
exists because measuring this by hand produced a FALSE ZERO: `git for-each-ref
'refs/pull/*'` matches 0 refs (git's `*` does not cross `/`), `git rev-list --not`
over an empty positive set prints nothing, and every command exits 0.  The
hand-measured "0 commits exist only in pull refs" was a zero computed over an
empty population; the true figure on hestia is 67.  A bucket sum that does not
reach the total is the cheap detector for a pattern that is silently eating refs.

Independently, we reconstruct when each patch-id first became reachable from main
(walking main's first-parent chain and dating each commit by the merge that
introduced it) and report the later twins whose content was ALREADY in main when
they were committed.  That subset is where a landedness misjudgment could have
done damage at all.

Reading the output
------------------
FRESH-AUTHOR-DUPLICATE == 0 means the cost clause is unobserved in this repo, NOT
that the logical correction is wrong -- ancestry-NO still proves nothing.  It
means the class's real cost is elsewhere: duplicate shas that invalidate sha-based
citations.  A non-zero is a candidate list to READ, not a redo count to quote.

The `copy` discriminator degrades if two seats independently commit within the
same second (author timestamps would collide by coincidence).  The script reports
that exposure so the reader can see whether it bit.  A real copy has
commit_ts > author_ts; a same-second coincidence has commit_ts == author_ts.

Usage:  redo_census.py <repo> [main-ref]
Control: tools/redo_census_control_test.sh  (proves RE-DERIVED is reachable)
"""
import collections
import re
import subprocess
import sys


def sh(repo, cmd, stdin=None):
    return subprocess.run(cmd, shell=True, cwd=repo, input=stdin,
                          capture_output=True, text=True).stdout


def ref_surface(repo):
    """Report the ref namespaces this object store actually holds.

    Returns (total, buckets, exclusive, sum_ok).  `exclusive[ns]` is the number
    of non-merge commits reachable from refs/<ns>/... and from NO other
    namespace -- i.e. what a fetch that skipped that namespace would have missed.

    Refs are passed to rev-list on stdin, never as argv: a mirror can hold
    thousands, and they are never matched with a glob, because a glob is how the
    hand measurement this guard replaces produced its false zero.
    """
    refs = [r for r in sh(repo, "git for-each-ref --format='%(refname)'").split() if r]
    total = len(refs)
    by_ns = collections.defaultdict(list)
    for r in refs:
        parts = r.split('/')
        by_ns['/'.join(parts[:2]) if len(parts) > 2 else '<other>'].append(r)
    buckets = {ns: len(v) for ns, v in by_ns.items()}
    sum_ok = sum(buckets.values()) == total

    exclusive = {}
    for ns, own in by_ns.items():
        if len(by_ns) < 2:
            exclusive[ns] = 0
            continue
        others = [r for o, v in by_ns.items() if o != ns for r in v]
        spec = '\n'.join(own + ['^' + r for r in others]) + '\n'
        out = sh(repo, 'git rev-list --no-merges --stdin', stdin=spec)
        exclusive[ns] = len([l for l in out.split() if l])
    return total, buckets, exclusive, sum_ok


def census(repo, main='origin/main'):
    meta = {}
    for line in sh(repo, "git rev-list --all --no-merges "
                         "--pretty=format:'%H|%at|%ct|%s' | grep -v ^commit").splitlines():
        p = line.split('|', 3)
        if len(p) == 4:
            meta[p[0]] = {'at': int(p[1]), 'ct': int(p[2]), 'subj': p[3]}

    ids = {}
    for line in sh(repo, 'git rev-list --all --no-merges | while read c; do '
                         'echo -n "$c "; git show "$c" | git patch-id --stable '
                         '| cut -d" " -f1; done').splitlines():
        p = line.split()
        if len(p) == 2:
            ids[p[0]] = p[1]

    # when did each commit become reachable from main?  a commit lands at the
    # date of the first-parent commit that introduced it.
    landed = {}
    for line in sh(repo, f"git rev-list --first-parent --format='%H %ct' {main} "
                         "| grep -v ^commit").splitlines():
        sha, ts = line.split()
        ts = int(ts)
        par = sh(repo, f"git log -1 --format=%P {sha}").split()
        base = f"--not {par[0]}" if par else ""
        for c in sh(repo, f"git rev-list {sha} {base}").split():
            landed.setdefault(c, ts)
    pid_landed = {}
    for sha, ts in landed.items():
        pid = ids.get(sha)
        if pid and ts < pid_landed.get(pid, 1 << 62):
            pid_landed[pid] = ts
    first_parent = set(sh(repo, f"git rev-list --first-parent {main}").split())

    groups = collections.defaultdict(list)
    for sha, pid in ids.items():
        if pid and sha in meta:
            groups[pid].append(sha)
    dups = {p: v for p, v in groups.items() if len(v) > 1}

    kinds = collections.Counter()
    rederived, already, ambiguous = [], [], []
    for pid, shas in dups.items():
        ordered = sorted(shas, key=lambda s: meta[s]['ct'])
        for later in ordered[1:]:
            m = meta[later]
            twins = [e for e in ordered if e != later and meta[e]['at'] == m['at']]
            if twins:
                kind = 'copy'
                # a genuine copy was authored before it was committed; equality
                # means this could be same-second independent authorship instead
                if m['ct'] == m['at']:
                    ambiguous.append((later, m['subj']))
            elif later in first_parent or re.search(r'\(#\d+\)$', m['subj']):
                kind = 'squash-merge'
            else:
                kind = 'FRESH-AUTHOR-DUPLICATE'
                rederived.append((later, m['subj']))
            kinds[kind] += 1
            lt = pid_landed.get(pid)
            if lt is not None and lt < m['ct']:
                already.append((later, kind, m['subj']))

    return {'population': len(meta), 'groups': len(dups),
            'later_twins': sum(kinds.values()), 'kinds': kinds,
            'rederived': rederived, 'already': already, 'ambiguous': ambiguous}


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    repo = sys.argv[1]
    ref = sys.argv[2] if len(sys.argv) > 2 else 'origin/main'
    total, buckets, exclusive, sum_ok = ref_surface(repo)
    r = census(repo, ref)
    print(f"repo={repo}  main={ref}")
    surface = '  '.join(f"{ns}/*:{n}" for ns, n in sorted(buckets.items(),
                                                          key=lambda kv: -kv[1]))
    print(f"  ref surface      : {total} refs = {surface}")
    if not sum_ok:
        print(f"  !! BUCKETS DO NOT SUM TO {total} — a ref pattern is eating refs; "
              f"the population below is NOT the full surface")
    dependent = {ns: n for ns, n in exclusive.items() if n}
    if dependent:
        for ns, n in sorted(dependent.items(), key=lambda kv: -kv[1]):
            print(f"    commits reachable ONLY from {ns}/* : {n}"
                  f"  ({100.0 * n / max(r['population'], 1):.1f}% of population)")
    else:
        print("    surface-independent: no namespace holds a commit the others lack")
    print(f"  population       : {r['population']} non-merge commits reachable from all refs")
    print(f"  duplicate groups : {r['groups']}   later-twins: {r['later_twins']}")
    for k in ('copy', 'squash-merge', 'FRESH-AUTHOR-DUPLICATE'):
        print(f"    {k:22s}: {r['kinds'][k]}")
    print(f"  copy discriminator ambiguous (commit_ts == author_ts): "
          f"{len(r['ambiguous'])} of {r['kinds']['copy']}")
    print(f"  later-twins whose content was ALREADY in main at commit time: "
          f"{len(r['already'])}")
    for sha, kind, subj in r['already']:
        print(f"      {sha[:8]} [{kind}] {subj[:60]}")
    if r['rederived']:
        print("  FRESH-AUTHOR-DUPLICATE detail (candidates to READ, not a redo count):")
        for sha, subj in r['rederived']:
            print(f"      {sha[:8]} {subj[:70]}")


if __name__ == '__main__':
    main()
