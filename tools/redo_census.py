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
  RE-DERIVED    fresh author timestamp and neither of the above: somebody sat down
                and produced content that already existed.  THIS is the cost the
                claim asserts.

Independently, we reconstruct when each patch-id first became reachable from main
(walking main's first-parent chain and dating each commit by the merge that
introduced it) and report the later twins whose content was ALREADY in main when
they were committed.  That subset is where a landedness misjudgment could have
done damage at all.

Reading the output
------------------
RE-DERIVED == 0 means the cost clause is unobserved in this repo, NOT that the
logical correction is wrong -- ancestry-NO still proves nothing.  It means the
class's real cost is elsewhere: duplicate shas that invalidate sha-based
citations.

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


def sh(repo, cmd):
    return subprocess.run(cmd, shell=True, cwd=repo,
                          capture_output=True, text=True).stdout


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
                kind = 'RE-DERIVED'
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
    r = census(repo, ref)
    print(f"repo={repo}  main={ref}")
    print(f"  population       : {r['population']} non-merge commits reachable from all refs")
    print(f"  duplicate groups : {r['groups']}   later-twins: {r['later_twins']}")
    for k in ('copy', 'squash-merge', 'RE-DERIVED'):
        print(f"    {k:14s}: {r['kinds'][k]}")
    print(f"  copy discriminator ambiguous (commit_ts == author_ts): "
          f"{len(r['ambiguous'])} of {r['kinds']['copy']}")
    print(f"  later-twins whose content was ALREADY in main at commit time: "
          f"{len(r['already'])}")
    for sha, kind, subj in r['already']:
        print(f"      {sha[:8]} [{kind}] {subj[:60]}")
    if r['rederived']:
        print("  RE-DERIVED detail:")
        for sha, subj in r['rederived']:
            print(f"      {sha[:8]} {subj[:70]}")


if __name__ == '__main__':
    main()
