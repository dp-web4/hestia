#!/usr/bin/env python3
"""kimi re-derivation of the 17-case table from cbp/redirect-target-resolvable,
using ONLY the worktree's own copies (plugins/_shared shipped at af354d6 +
tools/redirect_target_resolver.py at 3987de0). No /tmp scratchpad imports."""
import sys
WT = "/home/dp/ai-workspace/hestia/scratchpad/wt-resolver-verify"
sys.path.insert(0, WT + "/plugins/_shared")
sys.path.insert(0, WT + "/tools")
import hestia_governance_closure as g
import redirect_target_resolver as resolver

MARK = "plugins/_shared/hestia_governance_closure.py"
ABS  = "/home/dp/ai-workspace/hestia/" + MARK
CWD  = "/home/dp/ai-workspace/hestia"

CASES = [
 ("A verbatim refused cmd (out=$SP/..$(..))",
  'SP=/tmp/x/scratchpad\nmkdir -p $SP/shims\ncd /home/dp/ai-workspace/hestia\nfor p in %s; do\n  out=$SP/shims/$(echo "$p" | sed \'s#plugins/##\')\n  git show origin/main:$p > "$out"\ndone' % MARK),
 ("B assignment + var dest, no loop",  'OUT=/tmp/x/a.py\ngit show origin/main:%s > "$OUT"' % MARK),
 ("C assignment + var dest + loop",    'OUT=/tmp/x/a.py\nfor p in %s; do git show origin/main:$p > "$OUT"; done' % MARK),
 ("D loop var in dest (the #1062 arm)",'for s in a b; do git show HEAD:%s > /tmp/out/$s.py; done' % MARK),
 ("E loop, literal dest [control]",    'for p in %s; do git show origin/main:$p > /tmp/x.txt; done' % MARK),
 ("F no loop, literal [control]",      'git show origin/main:%s > /tmp/x.txt' % MARK),
 ("G loop, pipe (FP12) [control]",     'for p in %s; do git show origin/main:$p | wc -c; done' % MARK),
 ("H benign twin [control]",           'for s in a b; do git show HEAD:README.md > /tmp/out/$s.py; done'),
 ("I write AT the marker in a loop [HOLE]", 'for s in a b; do echo x > %s; done' % MARK),
 ("J var dest RESOLVING INTO closure [HOLE]", 'OUT=%s\necho hi > "$OUT"' % ABS),
 ("K var dest resolving outside closure",     'OUT=/tmp/safe.txt\necho %s > "$OUT"' % MARK),
 ("L loop var RESOLVING INTO closure [HOLE]", 'for f in README.md %s; do echo x > $f; done' % MARK),
 ("M reassigned var is ambiguous [HOLE]",     'OUT=/tmp/safe.txt\nOUT=%s\necho hi > "$OUT"' % ABS),
 ("N var from env, never bound [HOLE]",       'echo hi > "$UNBOUND"; touch %s' % MARK),
 ("O cd $VAR then relative write [HOLE]",     'D=/home/dp/ai-workspace/hestia\ncd $D\necho x > %s' % MARK),
 ("P dest is ${BRACED}",                      'OUT=/tmp/safe.txt\ngit show HEAD:%s > "${OUT}"' % MARK),
 ("Q fanout over 32 loop words",              'for s in %s; do git show HEAD:%s > /tmp/o/$s; done' % (" ".join("w%d"%i for i in range(40)), MARK)),
]

def row(cmd):
    v = g.classify("Bash", {"command": cmd}, cwd=CWD)
    return (v.classification, v.rule)

before = [(n, row(c)) for n, c in CASES]

# Inject the candidate the same way the findings doc describes: replace the
# shipped module's write-target extractor with the resolver's version.
_, _, new_bwt, _ = resolver.make(g)
g._bash_write_targets = new_bwt
after = [(n, row(c)) for n, c in CASES]

print(f"{'case':44s} {'shipped':34s} {'repaired':34s}")
moved = 0
for (n, b), (_, a) in zip(before, after):
    flag = ""
    if b != a:
        moved += 1
        flag = "  <-- MOVED"
    print(f"{n:44s} {str(b):34s} {str(a):34s}{flag}")
print(f"\nmoved: {moved}/17")
perm = [(n,b,a) for (n,b),(_,a) in zip(before,after)
        if b[0] != a[0] and a[0] in ("none",) or (b[0]=="write" and a[0]=="read" and "HOLE" in n)]
print("rows that moved PERMISSIVE on a [HOLE]:", perm)
