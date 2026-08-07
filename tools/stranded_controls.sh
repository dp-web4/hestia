#!/usr/bin/env bash
# Behavioural controls for stranded_by_content.py.
#
# kimi-code audited this instrument as TEXT (shared-context
# forum/kimi-re-1256-instrument-audit-three-findings-2026-08-06.md) -- their shell
# was fail-closed, so no probe ran. f417127 fixed the three findings and measured
# them against the live repo. This script is the missing third thing: synthetic
# cases where the OLD behaviour is known-wrong, so each fix has something it must
# actually make fail. A fix measured only on a population that contains zero
# instances of the defect is a fix nobody has seen work.
#
# Each case is built so the defect is the ONLY reason the verdict could differ.
#
#   caseA (F1)  branch adds a file at path X; main lands the identical blob but
#               only ever under a DIFFERENT path. Pre-fix: STRANDED (it asked "is
#               path X at main's tip"). Post-fix: not stranded, on blob evidence.
#               Built so patch-ids DIFFER -- otherwise probe 1 would answer it and
#               the F1 path would never execute. A control that passes for the
#               wrong reason is not a control.
#
#   caseB (F2)  branch modifies A and B; main puts A's added lines into B only.
#               Pre-fix: LIKELY-LANDED (added lines were pooled across every file
#               the commit touched). Post-fix: STRANDED, naming the sibling-file
#               matches as such.
#
#   caseP (probe 1) branch commits are REBASED onto main -- same patches, different
#               hashes, so ancestry fails and every path/line test has to infer.
#               Patch-id sees it outright. This is the class that moved 24 of 75
#               verdicts in the live sweep.
#
#   caseS (probe 1 NEGATIVE) a SQUASH-merge: main has the same net content but as
#               one commit, so patch-ids differ. probe 1 must ABSTAIN here -- a
#               CHERRY-LANDED verdict would mean patch-id was laundering. The
#               content did land, so LIKELY-LANDED is the right answer; the
#               assertion is on WHICH test answered, not on the verdict being
#               negative. (First written as "want STRANDED"; that expectation was
#               wrong and the run said so. Recorded because a control that is
#               quietly retuned until it passes has stopped being a control.)
#
#   caseC (negative) genuinely stranded content, on main under no path, ever. Must
#               stay STRANDED. Without it, an instrument that simply says "landed"
#               to everything would pass every case above.
#
# Usage: tools/stranded_controls.sh   (exit 0 = every control fired)

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOL="$HERE/stranded_by_content.py"
REPO="${TMPDIR:-/tmp}/stranded-controls-$$"
[ -f "$TOOL" ] || { echo "MISSING INSTRUMENT: $TOOL"; exit 2; }

mkdir -p "$REPO"
cd "$REPO" || exit 2
git init -q -b main
git config user.email control@test; git config user.name control
echo base > seed.txt; git add seed.txt; git commit -qm seed
ROOT=$(git rev-parse HEAD)

# ---- caseA: content landed on main under a DIFFERENT path (F1) ----
git checkout -qb caseA
printf 'alpha unique line one here\nalpha unique line two here\n' > added_by_branch.txt
git add added_by_branch.txt; git commit -qm "caseA: add new file at path X"
git checkout -q main
printf 'alpha unique line one here\nalpha unique line two here\n' > renamed_elsewhere.txt
git add renamed_elsewhere.txt; git commit -qm "main: same content, different path"

# ---- caseB: A's added lines landed in B, not A (F2) ----
printf 'fileA original content line\n' > A.txt
printf 'fileB original content line\n' > B.txt
git add A.txt B.txt; git commit -qm "seed A and B"
git checkout -qb caseB
printf 'fileA original content line\nSHARED MIGRATED LINE NUMBER ONE\nSHARED MIGRATED LINE NUMBER TWO\n' > A.txt
printf 'fileB original content line\nbranch only line in B here\n' > B.txt
git add A.txt B.txt; git commit -qm "caseB: modify A and B"
git checkout -q main
printf 'fileA original content line\n' > A.txt
printf 'fileB original content line\nSHARED MIGRATED LINE NUMBER ONE\nSHARED MIGRATED LINE NUMBER TWO\nbranch only line in B here\n' > B.txt
git add A.txt B.txt; git commit -qm "main: A's lines live in B, A unchanged"

# ---- caseP: rebased duplicate -- same patch, different hash (probe 1) ----
git checkout -q -b caseP_src "$ROOT"
printf 'rebased content line number one\nrebased content line number two\n' > rebased.txt
git add rebased.txt; git commit -qm "caseP: the patch"
git checkout -q main
git cherry-pick -q caseP_src 2>/dev/null || git cherry-pick caseP_src >/dev/null 2>&1
git branch -qD caseP_src 2>/dev/null
git checkout -q -b caseP "$ROOT"
printf 'rebased content line number one\nrebased content line number two\n' > rebased.txt
git add rebased.txt; git commit -qm "caseP: the patch"
git checkout -q main

# ---- caseS: squash-merge -- same net content, ONE commit, different patch-id ----
git checkout -q -b caseS "$ROOT"
printf 'squashed one alpha content here\n' > sq.txt
git add sq.txt; git commit -qm "caseS part 1"
printf 'squashed one alpha content here\nsquashed two beta content here\n' > sq.txt
git add sq.txt; git commit -qm "caseS part 2"
git checkout -q main
printf 'squashed one alpha content here\nsquashed two beta content here\n' > sq.txt
git add sq.txt; git commit -qm "main: squash of caseS"

# ---- caseC: genuinely stranded (negative control) ----
git checkout -qb caseC "$ROOT"
printf 'this content exists nowhere on main at all ever\n' > truly_stranded.txt
git add truly_stranded.txt; git commit -qm "caseC: genuinely stranded"
git checkout -q main
git update-ref refs/remotes/origin/main main

verdict() { python3 "$TOOL" "$1" 2>/dev/null | head -1 | awk '{print $1}'; }

fail=0
check() { # case expected note
  local c="$1" e="$2" note="$3" g
  g=$(verdict "$c")
  if [ "$g" = "$e" ]; then
    echo "PASS $c -> $g   [$note]"
  else
    echo "FAIL $c -> $g (want $e)   [$note]"; fail=1
  fi
}

echo "=== stranded_by_content behavioural controls (BASE=origin/main) ==="
check caseA CONTENT-LANDED "F1: blob landed under another path; pre-fix said STRANDED"
check caseB STRANDED       "F2: A's lines only in sibling B; pre-fix said LIKELY-LANDED"
check caseP CHERRY-LANDED  "probe 1: rebased duplicate, ancestry blind, patch-id sees it"
check caseS LIKELY-LANDED  "probe 1 NEGATIVE: squash-merge answered by CONTENT, not patch-id"
check caseC STRANDED       "negative: genuinely stranded must survive every new verdict"

cd /
rm -rf "$REPO"
if [ "$fail" = 0 ]; then echo "ALL CONTROLS FIRED"; else echo "CONTROL FAILURE"; fi
exit $fail
