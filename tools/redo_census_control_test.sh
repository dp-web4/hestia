#!/usr/bin/env bash
# Positive control for tools/redo_census.py.
#
# redo_census.py reports RE-DERIVED == 0 on every fleet repo measured so far.
# A zero from an instrument that has never emitted a non-zero is not evidence.
# This builds a synthetic repo containing one instance of EACH shape the
# classifier is supposed to separate, and asserts every bucket fires:
#
#   copy          a cherry-pick of a branch commit (author date preserved)
#   squash-merge  `git merge --squash` landed on main with a (#N) subject
#   RE-DERIVED    a second seat authoring identical content at a fresh date,
#                 never merged -- the shape whose real-world count is the finding
#
# It also exercises the ALREADY-in-main path: the cherry-pick is committed after
# the squash landed, so its content was in main when it was written.
#
# Exit 0 = the instrument can tell the four shapes apart. Exit 1 = the zero it
# reports on real repos is uninterpretable.
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CENSUS="$HERE/redo_census.py"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

cd "$WORK" || exit 1
git init -q -b main .
git config user.email control@test
git config user.name Control

export GIT_AUTHOR_DATE="2026-01-01T00:00:00" GIT_COMMITTER_DATE="2026-01-01T00:00:00"
echo one > a.txt && git add a.txt && git commit -q -m "feat: base"
BASE=$(git rev-parse HEAD)

# --- shape 1+2: a branch commit, then its squash-merge onto main -------------
export GIT_AUTHOR_DATE="2026-01-01T01:00:00" GIT_COMMITTER_DATE="2026-01-01T01:00:00"
git checkout -q -b feat1
echo bee > b.txt && git add b.txt && git commit -q -m "feat: add b"
SRC=$(git rev-parse HEAD)
git checkout -q main
export GIT_AUTHOR_DATE="2026-01-01T02:00:00" GIT_COMMITTER_DATE="2026-01-01T02:00:00"
git merge -q --squash feat1 >/dev/null 2>&1
git commit -q -m "feat: add b (#7)"

# --- shape 3: a cherry-pick copy, committed AFTER the squash landed ----------
git checkout -q -b feat2 "$BASE"
unset GIT_AUTHOR_DATE
export GIT_COMMITTER_DATE="2026-01-01T03:00:00"
git cherry-pick "$SRC" >/dev/null 2>&1 || { echo "FAIL: control could not build the copy arm"; exit 1; }

# --- shape 4: a genuine re-derivation, distinct author date, never merged ----
git checkout -q -b feat3 main
export GIT_AUTHOR_DATE="2026-01-01T04:00:00" GIT_COMMITTER_DATE="2026-01-01T04:00:00"
echo cee > c.txt && git add c.txt && git commit -q -m "feat: add c"
git checkout -q -b feat4 main
export GIT_AUTHOR_DATE="2026-01-01T05:00:00" GIT_COMMITTER_DATE="2026-01-01T05:00:00"
echo cee > c.txt && git add c.txt && git commit -q -m "feat: add c again, a second seat authored it fresh"
git checkout -q main

OUT="$(python3 "$CENSUS" "$WORK" main 2>&1)"
echo "$OUT"
echo

rc=0
check() {  # check <label> <grep-pattern>
  if grep -qE "$2" <<<"$OUT"; then
    echo "  PASS  $1"
  else
    echo "  FAIL  $1  (no line matching: $2)"
    rc=1
  fi
}
check "copy bucket fires"                 '^ *copy *: *[1-9]'
check "squash-merge bucket fires"         '^ *squash-merge *: *[1-9]'
check "RE-DERIVED bucket fires"           '^ *RE-DERIVED *: *[1-9]'
check "the re-derivation is named"        'a second seat authored it fresh'
check "ALREADY-in-main path fires"        'ALREADY in main at commit time: [1-9]'
check "copy discriminator is unambiguous" 'ambiguous \(commit_ts == author_ts\): 0 of'

echo
[ $rc -eq 0 ] && echo "CONTROL PASSED - RE-DERIVED is reachable, so a real-repo zero is a measurement" \
              || echo "CONTROL FAILED - do not interpret RE-DERIVED == 0 on real repos"
exit $rc
