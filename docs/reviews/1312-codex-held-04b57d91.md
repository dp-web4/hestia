# PR #1312: technical hold lifted for held 04b57d91

Reviewed head `386c6094b941002f04c006e17b73018429dc14ce`, held patch SHA-256
`04b57d9195c74ae52b35275ff789d9f4d8504c2a7e0ab9ea862e628d1791a556`, against base
`67b45517`. Response to review notice 24042. Checked `git log HEAD..origin/main`
in the shared checkout before review; the held loop proposal is not an executing fix.

**Verdict: lift my technical HOLD on this exact held patch.** No remaining blocking
finding was established in this review. The previous reviews' closing-keyword,
persistent-directory, quote-removal, bracket-class and source-position concerns are
covered by the amended exclusions and the checks below. This is a technical review;
it neither installs the gate nor substitutes for the governed apply decision.

## Verified

- The amended shell-scope battery passes **1434 checks, zero failures**.
- Direct and quoted `cd`, and all four previously demonstrated split/backslash
  spellings, are refused and do not take the literal-loop rule.
- The earlier closing-`done` filename case still refuses the actual ungranted path.
- Five Bash bracket forms (`c[[:alpha:]]`, `[[:lower:]]d`, `c[[:alnum:]]`, `c[^x]`,
  `[[:alpha:]][[:alpha:]]`) are refused and do not take the rule.
- Seven source positions (after `!`, `if`, `time`, a redirection, `then`, `else`,
  and `time -p`) are refused and do not take the rule.
- Separate Bash oracles using only directory changes and `pwd -P` confirm that
  each of those bracket/source bodies preserves directory changes across iterations.
  Each fixture directory contains the required `cd` filename and `move` source file;
  the third printed directory is the ungranted fixture sibling.
- Plain literal-list reads and the #1296 resolved-header case retain their intended
  allows. The battery includes bracket-test argument controls and extglob refusal.

The author's distinction from the previous round stands: bracket classes produced
an end-to-end false allow; the source-position concerns exposed an ineffective
exclusion while the ordinary judge still refused. This review establishes the
new exclusions directly, not a new claim that all source cases previously allowed.

## Reproduce and limits

Run from a checkout outside `/tmp`:

```sh
python3 tools/review_1312_04b57d91_probe.py
```

The probe checks the patch digest and hunk contexts, evaluates the base and revised
core in memory, and evaluates the patch's amended battery against that same revised
module. It writes no governed gate files and executes no sample file-read or network
commands. Temporary fixtures are removed. The battery's hard-coded cache location
was unwritable in this review environment, so the harness substitutes a temporary
directory beneath the checkout. This preserves the battery's non-`/tmp` requirement;
test cases and expected results are unchanged.

The author's transcript replay and full CI Python set were not independently rerun.
The conservative exclusions deliberately lose some ordinary loop allows. This is
bounded regression and adversarial evidence, not proof of equivalence for all Bash
programs or a stronger containment claim than the underlying gate provides.

— Codex
