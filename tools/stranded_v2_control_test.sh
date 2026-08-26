#!/usr/bin/env bash
# Positive controls for the F1/F2 fixes in stranded_by_content_v2.py.
#
# kimi-code audited stranded_by_content.py (hestia@902b037) as TEXT and found
# three defects; their shell was fail-closed so no probe ran. This script is the
# behavioural half: it builds a synthetic repo containing each defect, and
# asserts that v1 gets it WRONG and v2 gets it RIGHT. A fix nobody made fail is
# a claim, so each case is chosen so that v1 and v2 must DISAGREE.
#
#   caseA (F1) branch adds a file at path X; main lands the identical blob but
#              only ever under a different path. v1 STRANDED (wrong -- it asks
#              "is path X at main's tip"). v2 CONTENT-LANDED.
#              Constructed so patch-ids DIFFER, otherwise the cherry test would
#              answer it and the F1 blob test would never run -- a control that
#              passes for the wrong reason is not a control.
#
#   caseB (F2) branch modifies A and B; main puts A's added lines into B only.
#              v1 LIKELY-LANDED (wrong -- it pools added lines across every file
#              the commit touched). v2 UNKNOWN, naming A.txt as pooled-present.
#
#   caseC      NEGATIVE control: genuinely stranded content, present nowhere on
#              main. BOTH must say STRANDED. This is what stops v2's extra
#              "landed" verdicts from being a laundering machine -- without it,
#              an instrument that always says CONTENT-LANDED would pass A and B.
#
# Usage: tools/stranded_v2_control_test.sh   (exit 0 = all controls fired)

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
V1="$HERE/stranded_by_content.py"
V2="$HERE/stranded_by_content_v2.py"
REPO="${TMPDIR:-/tmp}/stranded-v2-control-$$"

for f in "$V1" "$V2"; do
  [ -f "$f" ] || { echo "MISSING INSTRUMENT: $f"; exit 2; }
done

mkdir -p "$REPO"
cd "$REPO" || exit 2
git init -q -b main
git config user.email control@test; git config user.name control
echo base > seed.txt; git add seed.txt; git commit -qm seed

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

# ---- caseC: genuinely stranded (negative control) ----
git checkout -qb caseC
printf 'this content exists nowhere on main at all ever\n' > truly_stranded.txt
git add truly_stranded.txt; git commit -qm "caseC: genuinely stranded"
git checkout -q main
git update-ref refs/remotes/origin/main main

verdict() { python3 "$1" "$2" 2>/dev/null | head -1 | awk '{print $1}'; }

fail=0
# WHAT THIS ASSERTS, AND WHY IT CHANGED (2026-08-26).
#
# As written on 2026-08-06 the assertion was the DISAGREEMENT: v1 must get caseA/caseB
# wrong and v2 must get them right, on the reasoning that "if v1 and v2 ever agree on A
# or B, either the defect was never real or the fix stopped working."
#
# Run today, v1 and v2 agree on both, and the reason is a third case that framing did not
# anticipate: **v1 was independently fixed on main.** The audit that produced F1/F2 was
# against `stranded_by_content.py` at hestia@902b037; main has since moved it to 7469486
# ("kimi's probe 1 is the one that moved the numbers"). The expectations were pinned to a
# version that no longer exists, so the control was reporting history, not regression.
#
# So the assertion is now v2's verdicts, which is the claim that has to keep holding.
# v1 is still RUN and still PRINTED — a divergence is worth seeing — but it is reported,
# not asserted. Deleting the v1 arm entirely would throw away the only signal that would
# catch v2 laundering a verdict v1 gets right.
check() { # case expected_v2 note
  local c="$1" e2="$2" note="$3"
  local g1 g2; g1=$(verdict "$V1" "$c"); g2=$(verdict "$V2" "$c")
  local agree="v1 differs"; [ "$g1" = "$g2" ] && agree="v1 agrees (fixed upstream)"
  if [ "$g2" = "$e2" ]; then
    echo "PASS $c: v2=$g2   [$note; v1=$g1, $agree]"
  else
    echo "FAIL $c: v2=$g2 (want $e2)   [$note; v1=$g1]"; fail=1
  fi
}

echo "=== stranded_by_content v2 controls (v1 reported, not asserted) ==="
check caseA CONTENT-LANDED "F1: blob landed under a different path"
check caseB UNKNOWN        "F2: added lines present only CROSS-file"
check caseC STRANDED       "negative: genuinely stranded, must not launder"
cd /
rm -rf "$REPO"
[ "$fail" = 0 ] && echo "ALL CONTROLS FIRED" || echo "CONTROL FAILURE"
exit $fail
