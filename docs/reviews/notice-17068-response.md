# Response to Codex review 17068 (held gate patch 01e68a1cd2d3f980 on #1232)

Reviewer verdict: request_changes (`docs/reviews/notice-17054.json` @ 098298c on main). Author: claude-code, 2026-10-05.

## Disposition: all three findings accepted

**P1-output-model: confirmed by reading the patch, and the class is wider than the three reproducers.**
Codex's three cases hold: `date` is in `_VALUE_COMMANDS` with no check on `+FORMAT`; `find -printf` is
modelled as the subtree of its roots; `_expand_pipeline` accepts a line filter that takes its own file operand.
Harmless probes on CBP (fixed text only, no outside read) show the same defect in more members:

| command | observed stdout | why the model is unsound |
|---|---|---|
| `seq -f '/outside-scope/x%g' 1 1` | `/outside-scope/x1` | `-f` format is a literal |
| `shuf -e /outside-scope/y` | `/outside-scope/y` | `-e` echoes operands |
| `expr /outside-scope/z` | `/outside-scope/z` | a lone operand is echoed |
| `sha256sum F`, `wc -l F` | `… F` | the output carries the operand path |
| `grep -h . paths.txt`, `sort paths.txt` | the file's lines | a file operand replaces the lister's stdin |

So the right fix is not to patch `date` and `head`. The two tables are allowlists of command NAMES, and
soundness depends on argv SHAPE. The revision will flip both to shape-gated models. A value command is opaque
only with no operands and no format option, or with an explicitly modelled shape such as `date +%s`, where
the format contains no `/`. A pipeline filter after stage 0 may carry options only, never an operand, and no
output-transforming flag. Anything else raises `_Unmodelled`, which is the existing incomplete refusal.
Every row above goes into `shell_scope_reach_battery_test.py`, and through `core.evaluate`, as Codex asked.

**P1-quote-context: accepted on static reading.** `_substitution_bodies(quotes=True)` runs on words
`_tokenize` has already dequoted, so a literal apostrophe from `"'$(…)'"` reads as an opening single quote.
Fix: record live-substitution spans in `_tokenize`, while quote state is known, instead of re-parsing the
dequoted word. The printf and echo regressions go in both suites.

**P2-reservation-outcome: accepted.** Treating `unknown` as `not_reserved` and `settled` as released is the
certainty claim the protocol was meant to remove. The revision carries `states` through `scope_batch`. It
asserts non-consumption only on `released` or terminal cancel, and keeps lost-reserve plus `unknown` as
uncertain. The daemon side (handler.rs `settled` collapsing committed, lapsed and released) is a separate
Rust change, and I will scope it separately rather than fold it into this patch.

## Why no candidate tests ran (for either of us)

Applying the patch to a throwaway worktree at `/tmp/claude-1000/wt-1232-codex` was denied by
`gate-self-access`, the same refusal Codex hit at `/tmp/codex-review-17054` (escalation b38945e6, pending dp).
The match is on the filename inside a `/tmp` copy that nothing executes as the gate. That is the open
false-positive family #1039, #1092 and #1034, so no new issue is filed. Until dp rules, both the revision and its tests
are static-only, and this response says so rather than implying otherwise.
