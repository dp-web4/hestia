#!/usr/bin/env python3
"""How long was each merged mesh-transport commit NOT running?

The three watcher units ExecStart a path inside the SHARED developer worktree
(#909).  So the bytes in force are whatever branch that tree happens to be on.
This measures the consequence directly, with no deploy required:

  * walk the tree's HEAD reflog -> (interval, blob-of-file-in-force)
  * walk origin/main's history of the same file -> (merge time, blob)
  * for each merged commit, find the first interval running that blob or any
    LATER merged blob.  That delta is the time the fix was merged-but-not-running.

Read-only.  Run it from any checkout of this repo that shares the reflog.
"""
import subprocess, datetime, statistics, sys, collections

FILE = sys.argv[1] if len(sys.argv) > 1 else 'plugins/member-mesh/hestia-watch-member.sh'
# The reflog is PER-WORKTREE.  The deployment history of the mesh transport lives
# in the reflog of the tree the systemd units ExecStart from -- pass it as argv[2],
# or this measures whatever tree you happen to be standing in (a fresh worktree has
# a one-entry reflog and will report a flat 100% "current").
REPO = subprocess.run(['git', 'rev-parse', '--show-toplevel'],
                      capture_output=True, text=True).stdout.strip()
TREE = sys.argv[2] if len(sys.argv) > 2 else REPO


def g(*a):
    return subprocess.run(['git', '-C', REPO] + list(a), capture_output=True, text=True)


_blob = {}


def blob(sha):
    if sha not in _blob:
        r = g('rev-parse', f'{sha}:{FILE}')
        _blob[sha] = r.stdout.strip() if r.returncode == 0 else None
    return _blob[sha]


def head_timeline():
    """(time, blob) for every HEAD position, oldest first."""
    out = subprocess.run(['git', '-C', TREE, 'reflog', 'show', '--date=iso-strict',
                          'HEAD', '--format=%H%x01%gd'], capture_output=True, text=True).stdout
    rows = []
    for ln in out.strip().split('\n'):
        p = ln.split('\x01')
        if len(p) < 2:
            continue
        gd = p[1]
        ts = gd[gd.index('{') + 1:gd.rindex('}')]
        rows.append((datetime.datetime.fromisoformat(ts), blob(p[0])))
    rows.reverse()
    return rows


def main_timeline():
    """(merge time, sha, blob, subject) for main's history of FILE, oldest first."""
    out = g('log', '--first-parent', 'origin/main', '--format=%H%x01%cI%x01%s', '--', FILE).stdout
    rows = []
    for ln in out.strip().split('\n'):
        if not ln:
            continue
        sha, ci, sub = ln.split('\x01', 2)
        rows.append((datetime.datetime.fromisoformat(ci), sha, blob(sha), sub))
    rows.reverse()
    return rows


def main():
    tl, ml = head_timeline(), main_timeline()
    if not tl or not ml:
        print(f'no history for {FILE}')
        return 1
    now = datetime.datetime.now(datetime.timezone.utc).astimezone(tl[-1][0].tzinfo)

    print(f'file: {FILE}')
    print(f'reflog read from worktree: {TREE}')
    print(f'{"merged":15s} {"undeployed":>12s}  commit / subject')
    lat = []
    for i, (ci, sha, b, sub) in enumerate(ml):
        # this blob, or any later merged blob, delivers the fix
        delivers = {x[2] for x in ml[i:]}
        hit = next((t for t, hb in tl if t >= ci and hb in delivers), None)
        live = hit is None
        d = ((now if live else hit) - ci).total_seconds() / 3600
        lat.append(d)
        print(f'{ci.strftime("%m-%d %H:%M"):15s} {d:10.2f}h{"*" if live else " "}  {sha[:7]} {sub[:64]}')

    print('\n* = still not running as of now')
    print(f'n={len(lat)} median={statistics.median(lat):.2f}h mean={statistics.mean(lat):.2f}h '
          f'max={max(lat):.2f}h  >1h:{sum(1 for x in lat if x > 1)}/{len(lat)}  '
          f'>24h:{sum(1 for x in lat if x > 24)}/{len(lat)}')

    # wall-clock share: was the running file the merged file?
    def main_blob_at(t):
        cur = None
        for ci, _, b, _ in ml:
            if ci <= t:
                cur = b
            else:
                break
        return cur

    ever = {b for _, _, b, _ in ml}
    for days in (1, 7, 30):
        cut = now - datetime.timedelta(days=days)
        acc, tot = collections.Counter(), 0.0
        for j, (t, b) in enumerate(tl):
            end = tl[j + 1][0] if j + 1 < len(tl) else now
            if end <= cut:
                continue
            dt = (end - max(t, cut)).total_seconds()
            if dt <= 0:
                continue
            tot += dt
            mb = main_blob_at(max(t, cut))
            k = ('file-absent' if b is None else
                 'current' if b == mb else
                 'behind (older merged version)' if b in ever else
                 'UNMERGED (never on main)')
            acc[k] += dt
        if tot:
            parts = ', '.join(f'{k} {100 * v / tot:.1f}%' for k, v in acc.most_common())
            print(f'  last {days:2d}d: {parts}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
