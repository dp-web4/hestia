# #1232 refusal-rate measurement output (2026-10-10)

Reference scripts, run from a scratch layout: `replay3.py` judges the corpus (`mine.py`, every seat's shell commands since 2026-09-20) under main's core, the reviewed 01e68a1c core, 01e68a1c merged onto main, and the narrowed core; `replay_exp.py` adds the literal-assignment experiment (`make_exp.py`). Core paths are the staging copies named in each script. `results*.jsonl` (seat, timestamp, verdict class per core; no command text) are not committed.

## replay3.py → aggregate.py

### Window of the 2026-10-05 run (2026-09-20 .. 2026-10-05T20:05Z): 33054 commands (claude-code 24536, codex 3359, kimi-code 5159)
| core | grants | refused (delta over main) | of which: path | once-only request | plain incomplete | claude-code | codex | kimi-code |
|---|---|---|---|---|---|---|---|---|
| orig | none | 3415 (10.3%) | 2612 | 0 | 799 | 2726 (11.1%) | 67 (2.0%) | 622 (12.1%) | errors=4
| orig | proposed | 1607 (4.9%) | 783 | 0 | 820 | 1432 (5.8%) | 27 (0.8%) | 148 (2.9%) | errors=4
| before | none | 3415 (10.3%) | 2612 | 0 | 799 | 2726 (11.1%) | 67 (2.0%) | 622 (12.1%) | errors=4
| before | proposed | 1607 (4.9%) | 783 | 0 | 820 | 1432 (5.8%) | 27 (0.8%) | 148 (2.9%) | errors=4
| after | none | 7051 (21.3%) | 2773 | 4278 | 0 | 6080 (24.8%) | 76 (2.3%) | 895 (17.3%) |
| after | proposed | 5660 (17.1%) | 1079 | 4581 | 0 | 5182 (21.1%) | 36 (1.1%) | 442 (8.6%) |

### Full window (2026-09-20 .. now): 53502 commands (claude-code 41142, codex 5651, kimi-code 6709)
| core | grants | refused (delta over main) | of which: path | once-only request | plain incomplete | claude-code | codex | kimi-code |
|---|---|---|---|---|---|---|---|---|
| orig | none | 6629 (12.4%) | 3841 | 0 | 2784 | 5655 (13.7%) | 114 (2.0%) | 860 (12.8%) | errors=4
| orig | proposed | 4025 (7.5%) | 1156 | 0 | 2865 | 3777 (9.2%) | 51 (0.9%) | 197 (2.9%) | errors=4
| before | none | 6629 (12.4%) | 3841 | 0 | 2784 | 5655 (13.7%) | 114 (2.0%) | 860 (12.8%) | errors=4
| before | proposed | 4025 (7.5%) | 1156 | 0 | 2865 | 3777 (9.2%) | 51 (0.9%) | 197 (2.9%) | errors=4
| after | none | 13265 (24.8%) | 4125 | 9140 | 0 | 11941 (29.0%) | 125 (2.2%) | 1199 (17.9%) |
| after | proposed | 11364 (21.2%) | 1687 | 9677 | 0 | 10744 (26.1%) | 62 (1.1%) | 558 (8.3%) |

main itself refuses 1426 of 53502 (pass 1/2, unchanged by this PR)

## replay_exp.py → aggregate_exp.py

### Window of the 2026-10-05 run (2026-09-20 .. 2026-10-05T20:05Z): 33054 commands (claude-code 24536, codex 3359, kimi-code 5159)
| core | grants | refused (delta over main) | of which: path | once-only request | plain incomplete | claude-code | codex | kimi-code |
|---|---|---|---|---|---|---|---|---|
| after | none | 7051 (21.3%) | 2773 | 4278 | 0 | 6080 (24.8%) | 76 (2.3%) | 895 (17.3%) |
| after | proposed | 5660 (17.1%) | 1079 | 4581 | 0 | 5182 (21.1%) | 36 (1.1%) | 442 (8.6%) |
| exp | none | 5409 (16.4%) | 2773 | 2636 | 0 | 4556 (18.6%) | 76 (2.3%) | 777 (15.1%) |
| exp | proposed | 3911 (11.8%) | 1080 | 2831 | 0 | 3558 (14.5%) | 36 (1.1%) | 317 (6.1%) |

### Full window (2026-09-20 .. now): 53590 commands (claude-code 41230, codex 5651, kimi-code 6709)
| core | grants | refused (delta over main) | of which: path | once-only request | plain incomplete | claude-code | codex | kimi-code |
|---|---|---|---|---|---|---|---|---|
| after | none | 13316 (24.8%) | 4126 | 9190 | 0 | 11992 (29.1%) | 125 (2.2%) | 1199 (17.9%) |
| after | proposed | 11415 (21.3%) | 1688 | 9727 | 0 | 10795 (26.2%) | 62 (1.1%) | 558 (8.3%) |
| exp | none | 10409 (19.4%) | 4127 | 6282 | 0 | 9212 (22.3%) | 125 (2.2%) | 1072 (16.0%) |
| exp | proposed | 8342 (15.6%) | 1690 | 6652 | 0 | 7856 (19.1%) | 62 (1.1%) | 424 (6.3%) |

main itself refuses 1426 of 53590 (pass 1/2, unchanged by this PR)

## shapes.py (once-only requests, narrowed core, proposed grants, full window)
```
once-only requests after the proposed grants: 9677
    4239   43.8%  variable: assigned a LITERAL in the same command (one assignment)
    2480   25.6%  variable: assigned an EXPANSION in the same command
    1242   12.8%  variable: a for-loop variable
     472    4.9%  command substitution used as a path
     272    2.8%  an expansion exported in …
     152    1.6%  an expansion handed to … in …
     139    1.4%  an expansion used as the program
     115    1.2%  variable: a `read` variable (stdin)
     112    1.2%  variable: assigned a LITERAL in the same command (several)
     110    1.1%  a process substitution used as a path
      79    0.8%  argv built from stdin (…)
      77    0.8%  a home spelling after HOME is reassigned
      71    0.7%  variable: from the environment / unknown
      50    0.5%  parameter expansion ${…}
      27    0.3%  positional parameter
      17    0.2%  brace expansion
      13    0.1%  an unbalanced double quote
       6    0.1%  an unbalanced single quote
       1    0.0%  a relative path after a directory change to …
       1    0.0%  more than 16 directory changes
       1    0.0%  <incomplete: more distinct paths than the gate judges in one
       1    0.0%  a heredoc form the parser does not model
```
