#!/usr/bin/env python3
"""AC-E1 (PRD_R6_R7_ENVELOPES §8): the §2 mapping is CHECKABLE, not asserted.

WHY THIS EXISTS. §2 of the envelopes PRD is a table of claims about web4's `r6.rs`,
each anchored to a `file:line` citation. A line number is not a fact about a
construct — it is a fact about a checkout. Bump `web4.pin`, or let web4 main move a
`struct` down by three lines, and every row still *reads* correct while pointing at
something else. `fb_derived_constant_needs_producer`: a citation without a producer
rots, silently, in the direction of looking fine.

WHAT IT ASSERTS.

  1. NO DRIFT BETWEEN PROSE AND TABLE. The set of `file:line` citations appearing in
     §2 of the PRD equals the set of rows in `docs/prd_r6_r7_citations.tsv`. Adding a
     citation to the prose without recording it, or leaving a row behind after
     deleting a citation, both go red. Without this the table could silently cover
     less than the prose and still pass every other check.

  2. EVERY ROW RESOLVES. Each row's recorded ANCHOR — the identifier declared at that
     line, or the line's text when it declares nothing — must still be present in the
     cited range, read at the authority for that row's repo: `web4.pin` for web4
     rows, `origin/main` for hestia's own. This is the arm that fires when a pin bump
     moves a construct.

  3. THE CHECK CAN FAIL (the arm that must fire, AC-E1). For EVERY row, the source is
     mutated in memory — that row's anchor replaced with a nonce — and the row's own
     check is re-run and required to go RED. A guard that has never been observed
     failing is `fb_guard_never_fired_claim`, a claim rather than a guard. AC-E1 asks
     for one such arm (rename `Constraint.threshold`); this runs one per row, so the
     answer is not "the guard fired once" but "every row's guard is live."

  Also AC-E2: `rate_limit` stays dropped until it exists — exactly one occurrence in
  web4-core/src at the pin (the doc comment listing it as an example constraint type).
  If it rises, row 5 of §2 is re-openable and this test says so.

WHAT IT DOES NOT ASSERT. That the VERDICTS in §2 (`HOLDS`, `PARTIAL`, `REFUTED`) are
correct — those are judgments about meaning, and a citation checker cannot reach them.
It asserts only that each judgment still points at the construct it was made about.

Hermetic: reads git objects only, writes nothing, builds nothing. No cargo, no daemon,
no network.
"""

import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRD = "docs/PRD_R6_R7_ENVELOPES.md"
TABLE = os.path.join(REPO, "docs", "prd_r6_r7_citations.tsv")

CITE = re.compile(r"((?:[\w./-]+/)?[A-Za-z0-9_]+\.rs):(\d+)(?:[-–](\d+))?")

FAILS = []


def fail(msg):
    FAILS.append(msg)


def web4_root():
    """Resolve the sibling web4 checkout without hardcoding any machine's layout.

    Order: explicit env override, then a sibling of this repo. Never a literal path —
    `tools/public_boundary.py` bans those, and the fleet spans three filesystem
    conventions (WSL, Linux, macOS)."""
    env = os.environ.get("WEB4_ROOT")
    if env:
        return env
    sib = os.path.join(os.path.dirname(REPO), "web4")
    return sib if os.path.isdir(os.path.join(sib, ".git")) else None


def pin():
    with open(os.path.join(REPO, "web4.pin")) as fh:
        m = re.search(r"[0-9a-f]{40}", fh.read())
    return m.group(0) if m else None


def git_show(cwd, rev, path):
    try:
        return subprocess.check_output(
            ["git", "-C", cwd, "show", f"{rev}:{path}"],
            text=True, stderr=subprocess.DEVNULL).splitlines()
    except subprocess.CalledProcessError:
        return None


def rel_for(path):
    """A §2 citation names either hestia's own file (with its `core/src/` prefix) or a
    web4-core source file by bare basename. The prefix is the discriminator — dropping
    it silently reattributes hestia's `reputation.rs` to web4, where no such file
    exists."""
    if path.startswith("core/"):
        return ("hestia", path)
    return ("web4", f"web4-core/src/{path.split('/')[-1]}")


def prd_citations():
    # Read the WORKING TREE, not HEAD. The table beside it is read from disk, and a
    # checker that reads one input from the index and the other from the checkout
    # reports drift between its own two readings — which it did, the first time this
    # ran against an uncommitted PRD edit. In CI the two are identical anyway.
    try:
        with open(os.path.join(REPO, PRD)) as fh:
            doc = fh.read().splitlines()
    except OSError:
        fail(f"{PRD} not readable")
        return set()
    try:
        s = next(i for i, l in enumerate(doc) if l.startswith("## 2."))
        e = next(i for i, l in enumerate(doc) if l.startswith("## 3.") and i > s)
    except StopIteration:
        fail("could not locate §2..§3 in the PRD — section headings moved")
        return set()
    out = set()
    for line in doc[s:e]:
        for m in CITE.finditer(line):
            a = int(m.group(2))
            b = int(m.group(3)) if m.group(3) else a
            out.add((m.group(1), a, b))
    return out


def read_table():
    rows = []
    with open(TABLE) as fh:
        for raw in fh:
            if not raw.strip() or raw.startswith("#"):
                continue
            repo, path, a, b, anchor = raw.rstrip("\n").split("\t")
            rows.append((repo, path, int(a), int(b), anchor))
    return rows


def load_sources(rows, w4, p):
    src = {}
    for repo, path, _, _, _ in rows:
        r, rel = rel_for(path)
        if (r, rel) in src:
            continue
        if r == "web4":
            src[(r, rel)] = git_show(w4, p, rel) if w4 else None
        else:
            src[(r, rel)] = git_show(REPO, "HEAD", rel)
    return src


def row_resolves(row, src):
    """The row's own check, factored out so the sabotage arm runs exactly it."""
    _, path, a, b, anchor = row
    r, rel = rel_for(path)
    lines = src.get((r, rel))
    if lines is None or b > len(lines):
        return False
    return any(anchor in ln for ln in lines[a - 1:b])


def main():
    w4 = web4_root()
    p = pin()
    if not p:
        fail("web4.pin carries no 40-hex rev")
    if not w4:
        print("SKIP: no sibling web4 checkout and WEB4_ROOT unset — "
              "cannot verify web4 rows", file=sys.stderr)
        return 0

    # The pin OBJECT must be present, not merely named. `actions/checkout` defaults to
    # fetch-depth 1, so a sibling web4 cloned at main carries `main` and nothing else —
    # `git show <pin>:...` then fails per-file and this check would red the build for a
    # missing object rather than a rotted citation. Detect it once, up front, and SKIP
    # loudly: a checker that cannot reach its authority must say so, not guess.
    #
    # SKIPPING IS NOT FREE, and the skip is the reason `ci.yml` gives the web4 checkout
    # `fetch-depth: 0`. If that ever regresses, this prints on every run and the guard is
    # inert — `fb_guard_never_fired_claim`. A silent skip would be worse than no check.
    if subprocess.run(["git", "-C", w4, "cat-file", "-e", p],
                      capture_output=True).returncode != 0:
        print(f"SKIP: web4.pin {p[:8]} is not present in the sibling web4 checkout "
              f"(shallow clone?). This check verifies citations AT THE PIN and will "
              f"not substitute web4 main for it — the anchors were recorded against "
              f"the pin, so main would report drift that is not drift. "
              f"Fix: fetch-depth: 0 on the web4 checkout, or `git -C web4 fetch "
              f"origin {p}`.", file=sys.stderr)
        return 0

    rows = read_table()
    cited = prd_citations()
    tabled = {(path, a, b) for _, path, a, b, _ in rows}

    # 1. no drift between prose and table
    for miss in sorted(cited - tabled):
        fail(f"§2 cites {miss[0]}:{miss[1]}-{miss[2]} but the table has no row for it")
    for extra in sorted(tabled - cited):
        fail(f"table row {extra[0]}:{extra[1]}-{extra[2]} is no longer cited in §2")

    src = load_sources(rows, w4, p)
    for (r, rel), lines in src.items():
        if lines is None:
            fail(f"{r}:{rel} unreadable at "
                 f"{'web4.pin' if r == 'web4' else 'HEAD'}")

    # 2. every row resolves
    unresolved = [row for row in rows if not row_resolves(row, src)]
    for row in unresolved:
        fail(f"{row[1]}:{row[2]}-{row[3]} no longer contains its anchor "
             f"{row[4]!r} — the citation has rotted")

    # 3. the arm that must fire: every row's check, sabotaged, must go red
    inert = []
    for row in rows:
        _, path, a, b, anchor = row
        r, rel = rel_for(path)
        lines = src.get((r, rel))
        if lines is None:
            continue
        sab = dict(src)
        sab[(r, rel)] = [
            ln.replace(anchor, "SABOTAGE_NONCE_" + "x" * 6) if i in range(a - 1, b) else ln
            for i, ln in enumerate(lines)
        ]
        if row_resolves(row, sab):
            inert.append(f"{path}:{a}-{b} (anchor {anchor!r})")
    for i in inert:
        fail(f"SABOTAGE INERT — renaming the anchor did not fail the row: {i}. "
             f"That row's check cannot go red, so its green means nothing.")

    # AC-E2: rate_limit stays dropped until it exists
    try:
        names = subprocess.check_output(
            ["git", "-C", w4, "ls-tree", "-r", "--name-only", p, "web4-core/src/"],
            text=True).split()
        hits = 0
        for n in names:
            body = git_show(w4, p, n) or []
            hits += sum(ln.count("rate_limit") for ln in body)
        if hits != 1:
            fail(f"AC-E2: expected exactly 1 occurrence of 'rate_limit' in "
                 f"web4-core/src at the pin (the doc comment), found {hits}. "
                 f"If it rose, §2 row 5 is re-openable; if it fell, the row's "
                 f"premise is gone.")
    except subprocess.CalledProcessError as e:
        fail(f"AC-E2: could not enumerate web4-core/src at the pin ({e})")

    print(f"pin {p[:8]} · rows {len(rows)} · cited {len(cited)} · "
          f"sabotage fired {len(rows) - len(inert)}/{len(rows)}")
    if FAILS:
        print(f"FAILED {len(FAILS)}:")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
